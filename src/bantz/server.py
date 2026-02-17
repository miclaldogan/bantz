"""Bantz Session Server - Unix socket daemon.

Keeps browser and context alive.
Receives CLI commands via socket, returns results.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import sys
import threading
import atexit
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from bantz.router.engine import Router, OverlayStateHook, set_overlay_hook
from bantz.router.policy import Policy
from bantz.router.context import ConversationContext
from bantz.logs.logger import JsonlLogger
from bantz.scheduler.reminder import get_reminder_manager
from bantz.core.events import get_event_bus, Event


# Default socket path
DEFAULT_SOCKET_DIR = Path("/tmp/bantz_sessions")
DEFAULT_SESSION = "default"


# Background server threads (used by voice mode for auto-start)
_bg_server_threads: dict[str, threading.Thread] = {}
_bg_server_errors: dict[str, str] = {}


def start_server_in_background(
    session_name: str = DEFAULT_SESSION,
    policy_path: str = "config/policy.json",
    log_path: str = "artifacts/logs/bantz.log.jsonl",
) -> bool:
    """Start a server for the given session in a daemon thread.

    This is primarily used by voice mode so users can run `bantz --voice/--wake`
    without separately starting the session server.

    Returns:
        True if a start was initiated (or already running), False if thread could
        not be started.
    """

    if is_server_running(session_name):
        return True

    # Avoid double-start attempts for the same session.
    t = _bg_server_threads.get(session_name)
    if t is not None and t.is_alive():
        return True

    def _runner() -> None:
        try:
            start_server(session_name=session_name, policy_path=policy_path, log_path=log_path)
        except Exception:
            _bg_server_errors[session_name] = traceback.format_exc()

    try:
        thread = threading.Thread(target=_runner, name=f"bantz-server:{session_name}", daemon=True)
        _bg_server_threads[session_name] = thread
        thread.start()
        return True
    except Exception:
        _bg_server_errors[session_name] = traceback.format_exc()
        return False


def ensure_server_running(
    session_name: str = DEFAULT_SESSION,
    policy_path: str = "config/policy.json",
    log_path: str = "artifacts/logs/bantz.log.jsonl",
    timeout_s: float = 8.0,
) -> tuple[bool, bool, str]:
    """Ensure a session server is running.

    Returns:
        (ok, started_here, message)
    """

    if is_server_running(session_name):
        return True, False, "already_running"

    def _format_err(raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        # Keep full traceback only in debug.
        if os.environ.get("BANTZ_DEBUG", "").strip() in {"1", "true", "True"}:
            return raw
        # Otherwise, show the last non-empty line (most relevant exception).
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        return lines[-1] if lines else ""

    started = start_server_in_background(session_name=session_name, policy_path=policy_path, log_path=log_path)
    if not started:
        err = _format_err(_bg_server_errors.get(session_name, ""))
        hint = " (hint: try 'bantz --serve --session {s}' in terminal)".format(s=session_name)
        return False, False, f"start_failed:{err}{hint}" if err else f"start_failed{hint}"

    # Wait for socket to come up.
    deadline = time.time() + float(timeout_s)
    while time.time() < deadline:
        if is_server_running(session_name):
            return True, True, "started"

        # If server thread crashed, surface its error.
        err = _bg_server_errors.get(session_name)
        if err:
            short = _format_err(err)
            hint = " (hint: run 'bantz --serve --session {s}' to see error output)".format(s=session_name)
            return False, True, f"crashed:{short}{hint}" if short else f"crashed{hint}"

        time.sleep(0.1)

    return False, True, "timeout (hint: start with 'bantz --serve --session {s}' and check logs)".format(s=session_name)


class InboxStore:
    def __init__(self, maxlen: int = 200):
        self._items: deque[dict] = deque(maxlen=maxlen)
        self._next_id: int = 1
        self._lock = threading.Lock()

    def push_from_event(self, event: Event) -> None:
        if not event.data.get("proactive"):
            return

        # Derive kind from payload if provided; fallback from intent.
        kind = event.data.get("kind")
        if not kind:
            intent = str(event.data.get("intent") or "")
            if intent == "checkin_fired":
                kind = "checkin"
            elif intent == "reminder_fired":
                kind = "reminder"
            else:
                kind = "system"

        ts = event.timestamp.isoformat()
        text = str(event.data.get("text", ""))
        source = str(getattr(event, "source", None) or event.data.get("source") or "core")

        with self._lock:
            item = {
                "id": self._next_id,
                "ts": ts,
                "kind": str(kind),
                "text": text,
                "source": source,
                "read": False,
                # Backward-compatible alias (older clients used this)
                "timestamp": ts,
            }
            self._items.append(item)
            self._next_id += 1

    def snapshot(self) -> dict:
        with self._lock:
            items = list(self._items)
        unread = sum(1 for x in items if not x.get("read"))
        return {"items": items, "unread": unread}

    def mark_read(self, target_id: int) -> bool:
        with self._lock:
            for it in self._items:
                if int(it.get("id", -1)) == int(target_id):
                    it["read"] = True
                    it["read_at"] = datetime.now().isoformat()
                    return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def get_socket_path(session_name: str = DEFAULT_SESSION) -> Path:
    """Get socket path for a session."""
    DEFAULT_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_SOCKET_DIR / f"{session_name}.sock"


# ─────────────────────────────────────────────────────────────
# IPC Overlay Integration
# ─────────────────────────────────────────────────────────────

class IPCOverlayHook(OverlayStateHook):
    """
    Overlay state hook implementation using IPC.
    
    Communicates with overlay process via Unix socket.
    """
    
    def __init__(self):
        self._client = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._server_ref = None  # Reference to BantzServer for command handling
    
    def start(self) -> bool:
        """Start overlay client and spawn overlay process."""
        if self._running:
            return True
        
        try:
            from bantz.ipc.overlay_client import OverlayClient
            
            self._client = OverlayClient()
            
            # Create event loop in background thread
            self._running = True
            self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
            self._thread.start()
            
            # Wait for loop to be ready
            import time
            for _ in range(50):  # 5 seconds max
                if self._loop is not None:
                    break
                time.sleep(0.1)
            
            if self._loop is None:
                print("   Overlay: başlatılamadı (loop timeout)")
                return False
            
            # Start client in the async loop
            # auto_spawn=False: Electron overlay is started independently
            # and creates the socket server; we just connect to it.
            future = asyncio.run_coroutine_threadsafe(
                self._client.start(auto_spawn=False),
                self._loop,
            )
            
            # Wait for connection (max 30 seconds — overlay may still be booting)
            connected = future.result(timeout=30.0)
            
            if connected:
                print("   Overlay: bağlandı ✓")
                # Wire command callback for text commands from overlay UI
                self._client.set_command_callback(self._handle_overlay_command)
                return True
            else:
                print("   Overlay: bağlanamadı")
                return False
                
        except Exception as e:
            print(f"   Overlay: hata ({e})")
            return False
    
    def stop(self) -> None:
        """Stop overlay client and terminate overlay process."""
        self._running = False
        
        if self._client and self._loop:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._client.stop(),
                    self._loop,
                )
                future.result(timeout=5.0)
            except Exception:
                pass
        
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        self._client = None
        self._loop = None
    
    def _run_async_loop(self):
        """Run asyncio event loop in background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            while self._running:
                self._loop.run_until_complete(asyncio.sleep(0.1))
        except Exception:
            pass
        finally:
            self._loop.close()
            self._loop = None
    
    def _run_async(self, coro):
        """Run async coroutine from sync context."""
        if not self._loop or not self._client:
            return None
        
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=5.0)
        except Exception:
            return None
    
    async def wake(self, text: str = "Sizi dinliyorum efendim.") -> None:
        """Show wake state."""
        if self._client:
            from bantz.ipc.protocol import OverlayState
            await self._client.set_state(
                OverlayState.WAKE.value,
                text=text,
                timeout_ms=15000,  # 15 seconds timeout
            )
    
    async def listening(self, text: str = "Dinliyorum...") -> None:
        """Show listening state."""
        if self._client:
            from bantz.ipc.protocol import OverlayState
            await self._client.set_state(OverlayState.LISTENING.value, text=text)
    
    async def thinking(self, text: str = "Anlıyorum...") -> None:
        """Show thinking state."""
        if self._client:
            from bantz.ipc.protocol import OverlayState
            await self._client.set_state(OverlayState.THINKING.value, text=text)
    
    async def speaking(self, text: str = "") -> None:
        """Show speaking state with response text."""
        if self._client:
            from bantz.ipc.protocol import OverlayState
            await self._client.set_state(
                OverlayState.SPEAKING.value,
                text=text,
                timeout_ms=10000,  # 10 seconds timeout
            )
    
    async def idle(self) -> None:
        """Hide overlay (return to idle)."""
        if self._client:
            await self._client.hide()
    
    async def set_position(self, position: str) -> bool:
        """Update overlay position."""
        if self._client:
            return await self._client.set_position(position)
        return False

    async def preview_action(self, text: str, duration_ms: int = 1200) -> None:
        """Show a transient action preview on the overlay."""
        if self._client:
            try:
                await self._client.preview(text=text, duration_ms=duration_ms)
            except Exception:
                return

    async def cursor_dot(self, x: int, y: int, duration_ms: int = 800) -> None:
        """Show a transient cursor dot at screen coordinate."""
        if self._client:
            try:
                await self._client.cursor_dot(x=x, y=y, duration_ms=duration_ms)
            except Exception:
                return

    async def highlight_rect(self, x: int, y: int, w: int, h: int, duration_ms: int = 1200) -> None:
        """Highlight a rectangle region on screen."""
        if self._client:
            try:
                await self._client.highlight_rect(x=x, y=y, w=w, h=h, duration_ms=duration_ms)
            except Exception:
                return
    
    # Sync wrappers for use from engine (sync context)
    def wake_sync(self, text: str = "Sizi dinliyorum efendim.") -> None:
        self._run_async(self.wake(text))
    
    def listening_sync(self, text: str = "Dinliyorum...") -> None:
        self._run_async(self.listening(text))
    
    def thinking_sync(self, text: str = "Anlıyorum...") -> None:
        self._run_async(self.thinking(text))
    
    def speaking_sync(self, text: str = "") -> None:
        self._run_async(self.speaking(text))
    
    def idle_sync(self) -> None:
        self._run_async(self.idle())
    
    def set_position_sync(self, position: str) -> bool:
        result = self._run_async(self.set_position(position))
        return result if result is not None else False

    def preview_action_sync(self, text: str, duration_ms: int = 1200) -> None:
        self._run_async(self.preview_action(text=text, duration_ms=duration_ms))

    def cursor_dot_sync(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._run_async(self.cursor_dot(x=x, y=y, duration_ms=duration_ms))

    def highlight_rect_sync(self, x: int, y: int, w: int, h: int, duration_ms: int = 1200) -> None:
        self._run_async(self.highlight_rect(x=x, y=y, w=w, h=h, duration_ms=duration_ms))
    
    def is_connected(self) -> bool:
        """Check if overlay is connected."""
        return self._client is not None and self._client.connected
    
    def set_server_ref(self, server: 'BantzServer') -> None:
        """Set reference to BantzServer for command processing."""
        self._server_ref = server
    
    async def _handle_overlay_command(self, text: str) -> None:
        """Handle text command from overlay UI — runs handle_command in thread."""
        if not self._server_ref:
            logger.warning("[IPCOverlayHook] No server reference, cannot process command")
            return
        
        # Show thinking state
        await self.thinking("Düşünüyorum...")
        
        try:
            # Run blocking handle_command in executor
            import asyncio as _asyncio
            loop = _asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._server_ref.handle_command, text
            )
            
            response_text = result.get("text", "")
            
            # Show speaking state with response
            if response_text:
                await self.speaking(response_text[:200])
            else:
                await self.speaking("Tamam!")
            
            # Send response as a raw message so the overlay can display it
            if self._client:
                await self._client.send_raw({
                    "type": "response",
                    "text": response_text,
                    "ok": result.get("ok", False),
                })
            
            # Auto-hide after a delay
            await _asyncio.sleep(8)
            await self.idle()
            
        except Exception as e:
            logger.error(f"[IPCOverlayHook] Command processing error: {e}")
            await self.speaking(f"Hata: {e}")
            await _asyncio.sleep(3)
            await self.idle()


# Global overlay hook instance
_overlay_hook: Optional[IPCOverlayHook] = None


def get_ipc_overlay_hook() -> IPCOverlayHook:
    """Get or create global IPC overlay hook."""
    global _overlay_hook
    if _overlay_hook is None:
        _overlay_hook = IPCOverlayHook()
    return _overlay_hook


class BantzServer:
    """Session server that holds browser and context alive."""

    def __init__(
        self,
        session_name: str = DEFAULT_SESSION,
        policy_path: str = "config/policy.json",
        log_path: str = "bantz.log.jsonl",
    ):
        self.session_name = session_name
        self.socket_path = get_socket_path(session_name)
        self.policy = Policy.from_json_file(policy_path)
        self.logger = JsonlLogger(path=log_path)
        self.router: Optional[Router] = None
        self.ctx = ConversationContext(timeout_seconds=300)  # 5 min timeout
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._browser_initialized = False

        # Brain is the default runtime (Issue #567 → #851: legacy path removed).
        self._brain = None
        self._brain_state = None
        try:
            from bantz.brain.runtime_factory import create_runtime
            from bantz.brain.orchestrator_state import OrchestratorState

            self._brain = create_runtime()
            self._brain_state = OrchestratorState()
            # Banner is printed by create_runtime() (Issue #588)
        except Exception as e:
            logging.getLogger(__name__).error(
                "Brain init failed: %s", e
            )

        # Proactive inbox (FIFO) for bantz_message events
        self._inbox = InboxStore(maxlen=200)

        def on_bantz_message(event: Event) -> None:
            self._inbox.push_from_event(event)

        self._event_bus = get_event_bus()
        self._on_bantz_message = on_bantz_message
        self._event_bus.subscribe("bantz_message", self._on_bantz_message)

        # Page memory pagination state
        self._scan_page_index = 0
        self._scan_page_size = 10
        self._last_scan: Optional[dict] = None

        # ── Data Sync Scheduler (Gmail, Calendar, News → IngestStore) ──
        self._sync_scheduler = None
        self._sync_loop = None      # dedicated asyncio loop for sync
        self._sync_thread = None    # background thread running the loop
        try:
            import asyncio as _aio
            import threading
            from bantz.data import IngestStore, SyncScheduler
            from bantz.tools.sync_search_tools import init_sync_tools

            _sync_store = IngestStore()
            self._sync_scheduler = SyncScheduler(_sync_store)

            # Run sync scheduler in a dedicated background thread with
            # its own event loop so it works in both interactive and
            # daemon modes (the main thread is sync/blocking).
            self._sync_loop = _aio.new_event_loop()

            def _sync_thread_target(loop, scheduler):
                _aio.set_event_loop(loop)
                loop.run_until_complete(scheduler.start())
                loop.run_forever()

            self._sync_thread = threading.Thread(
                target=_sync_thread_target,
                args=(self._sync_loop, self._sync_scheduler),
                daemon=True,
                name="bantz-sync",
            )
            self._sync_thread.start()
            init_sync_tools(self._sync_scheduler)
            logging.getLogger(__name__).info("Data sync scheduler started.")
        except Exception as _sync_err:
            logging.getLogger(__name__).warning(
                "Data sync init failed (non-fatal): %s", _sync_err,
            )

    def _get_router(self) -> Router:
        if self.router is None:
            self.router = Router(policy=self.policy, logger=self.logger)
        return self.router

    def _cleanup_socket(self) -> None:
        """Remove stale socket file."""
        if self.socket_path.exists():
            self.socket_path.unlink()

    def _init_browser(self) -> None:
        """Initialize browser extension bridge (NOT Playwright anymore)."""
        if not self._browser_initialized:
            try:
                # Extension bridge is started by daemon, just mark as ready
                # OLD: Playwright controller - REMOVED
                # from bantz.browser.controller import get_controller
                # get_controller()
                self._browser_initialized = True
            except Exception:
                self._browser_initialized = False

    def handle_command(self, command: str) -> dict:
        """Process a command and return result dict."""
        command = command.strip()

        # ─────────────────────────────────────────────────────────────
        # Proactive inbox commands (UI helper)
        # ─────────────────────────────────────────────────────────────
        if command.lower() == "__inbox__":
            snap = self._inbox.snapshot()
            return {"ok": True, "text": "OK", "inbox": snap["items"], "unread": snap["unread"]}

        if command.lower().startswith("__inbox_mark__"):
            # Usage: __inbox_mark__ 3  (mark item id=3 as read)
            parts = command.split()
            if len(parts) < 2:
                return {"ok": False, "text": "Eksik parametre. Örnek: __inbox_mark__ 3"}
            try:
                target_id = int(parts[1])
            except ValueError:
                return {"ok": False, "text": "Geçersiz id."}

            updated = self._inbox.mark_read(target_id)
            return {"ok": updated, "text": "OK" if updated else "Bulunamadı"}

        if command.lower() == "__inbox_clear__":
            self._inbox.clear()
            return {"ok": True, "text": "OK"}

        # Server control commands
        if command.lower() in {"__shutdown__", "__exit__"}:
            self._running = False
            return {"ok": True, "text": "Server kapatılıyor...", "shutdown": True}

        if command.lower() == "__status__":
            browser_url = "kapalı"
            if self._browser_initialized:
                try:
                    # Use extension bridge instead of Playwright
                    from bantz.browser.extension_bridge import get_bridge
                    bridge = get_bridge()
                    if bridge and bridge.has_client():
                        page = bridge.get_current_page()
                        browser_url = page.get("url", "bağlı") if page else "bağlı"
                    else:
                        browser_url = "extension bağlı değil"
                except Exception:
                    browser_url = "kapalı"
            return {
                "ok": True,
                "text": "Server çalışıyor",
                "status": {
                    "session": self.session_name,
                    "mode": self.ctx.mode,
                    "browser": browser_url,
                    "overlay": "bağlı" if (get_ipc_overlay_hook()._client and get_ipc_overlay_hook()._client.connected) else "kapalı",
                    "queue_active": self.ctx.queue_active(),
                    "pending": (
                        self.ctx.pending is not None
                        or (self._brain_state is not None and self._brain_state.has_pending_confirmation())
                    ),
                },
            }

        # Pagination commands
        if command.lower() in {"daha fazla", "daha", "more", "next"}:
            return self._paginate_next()

        if command.lower() in {"önceki", "previous", "prev", "geri"}:
            return self._paginate_prev()

        # ─────────────────────────────────────────────────────────────
        # Self-Evolving Agent — skill approval / rejection (Issue #837)
        # ─────────────────────────────────────────────────────────────
        try:
            from bantz.skills.declarative.generator import get_self_evolving_manager
            mgr = get_self_evolving_manager()
            if mgr is not None and mgr.has_pending:
                lower = command.strip().lower()
                if lower in {"evet", "yes", "kur", "onayla", "approve", "evet kur"}:
                    result = mgr.approve_pending()
                    return {"ok": result.get("ok", False), "text": result.get("text", ""), "skill_approved": True}
                elif lower in {"hayır", "no", "reddet", "reject", "iptal", "vazgeç"}:
                    result = mgr.reject_pending()
                    return {"ok": result.get("ok", False), "text": result.get("text", ""), "skill_rejected": True}
        except ImportError:
            pass

        # ─────────────────────────────────────────────────────────────
        # Overnight mode — "gece şunu yap" intent (Issue #836)
        # ─────────────────────────────────────────────────────────────
        try:
            from bantz.automation.overnight import is_overnight_request, parse_overnight_tasks

            if is_overnight_request(command):
                tasks = parse_overnight_tasks(command)
                if not tasks:
                    return {"ok": False, "text": "Gece modu için görev belirtmelisin. Örnek: 'gece şunları yap: 1. X  2. Y'"}
                from bantz.automation.overnight import OvernightRunner
                runner = OvernightRunner(bantz_server=self)
                runner.add_tasks(tasks)
                import threading
                t = threading.Thread(target=runner.run, daemon=True, name="overnight-runner")
                t.start()
                task_list = "\n".join(f"  {i+1}. {desc}" for i, desc in enumerate(tasks))
                return {
                    "ok": True,
                    "text": f"🌙 Gece modu başlatıldı! {len(tasks)} görev sıraya alındı:\n{task_list}\n\nSabah raporu inbox'ınıza gelecek.",
                    "overnight": True,
                    "session_id": runner.state.session_id if runner.state else None,
                    "task_count": len(tasks),
                }
        except ImportError:
            pass

        # Browser commands need browser init
        from bantz.router.nlu import parse_intent
        parsed = parse_intent(command)
        if parsed.intent.startswith("browser_"):
            self._init_browser()

        # ── Cross-system confirmation: if old Router has ctx.pending and user
        #    says yes/no (NLU → confirm_yes/confirm_no which doesn't start with
        #    "browser_"), route to old Router so it can resolve its own pending. ──
        if self.ctx.pending is not None and parsed.intent in ("confirm_yes", "confirm_no"):
            router = self._get_router()
            result = router.handle(text=command, ctx=self.ctx)
            overlay = get_ipc_overlay_hook()
            if overlay._client and overlay._client.connected:
                if result.ok:
                    overlay.speaking_sync(result.user_text[:100] if result.user_text else "Tamam!")
                else:
                    overlay.speaking_sync(result.user_text[:100] if result.user_text else "Bir sorun oluştu.")
            return {
                "ok": result.ok,
                "text": result.user_text or ("Tamam." if result.ok else "Hata oluştu."),
            }

        # Show thinking state on overlay
        overlay = get_ipc_overlay_hook()
        if overlay._client and overlay._client.connected:
            overlay.thinking_sync("Anlıyorum...")

        # Brain handles all non-browser commands (Issue #851: legacy Router path removed).
        if self._brain is not None and not parsed.intent.startswith("browser_"):
            try:
                # ── Issue #869: Handle pending confirmation from previous turn ──
                if (
                    self._brain_state is not None
                    and self._brain_state.has_pending_confirmation()
                ):
                    from bantz.brain.orchestrator_state import OrchestratorState

                    pending = self._brain_state.peek_pending_confirmation() or {}
                    pending_tool = str(pending.get("tool") or "")
                    prompt = str(pending.get("prompt") or "")
                    lower = command.strip().lower()

                    # Accept confirmation
                    _yes_tokens = {
                        "evet", "e", "ok", "tamam", "onay", "onaylıyorum",
                        "kabul", "yes", "y", "olur", "peki", "ekle", "yap",
                        "koy", "kaydet", "gönder", "at", "yolla",
                    }
                    _no_tokens = {
                        "hayır", "hayir", "h", "no", "n", "iptal", "vazgeç",
                        "vazgec", "reddet", "istemiyorum", "olmaz", "yok",
                    }
                    first_word = lower.split()[0] if lower.split() else ""

                    if lower in _yes_tokens or first_word in _yes_tokens:
                        # User confirmed — set confirmed_tool and re-run
                        self._brain_state.confirmed_tool = pending_tool
                        output, self._brain_state = self._brain.process_turn(
                            command, self._brain_state
                        )
                        # Safety net: if the confirmed tool was not consumed
                        # (e.g. preroute intercepted "evet"), clear stale state
                        # so the next query doesn't re-show the old prompt.
                        if self._brain_state.confirmed_tool is not None:
                            logging.getLogger(__name__).warning(
                                "[CONFIRMATION] confirmed_tool '%s' was not consumed "
                                "by process_turn — clearing stale confirmation state.",
                                self._brain_state.confirmed_tool,
                            )
                            self._brain_state.clear_pending_confirmation()
                        reply = str(getattr(output, "assistant_reply", "") or "").strip()
                        return {
                            "ok": True,
                            "text": reply or "Tamamdır efendim.",
                            "brain": True,
                            "route": getattr(output, "route", "unknown"),
                        }
                    elif lower in _no_tokens or first_word in _no_tokens:
                        # User rejected — clear pending
                        self._brain_state.clear_pending_confirmation()
                        return {
                            "ok": True,
                            "text": "Anlaşıldı efendim, iptal ettim.",
                            "brain": True,
                            "route": "cancelled",
                        }
                    else:
                        # Unknown response — re-show confirmation prompt
                        return {
                            "ok": True,
                            "text": prompt or "Efendim, devam etmek için 'evet' veya 'hayır' diyebilir misiniz?",
                            "brain": True,
                            "route": "confirmation",
                            "needs_confirmation": True,
                            "confirmation_prompt": prompt,
                            "confirmation_tool": pending_tool,
                        }

                # Snapshot tool results before this turn
                _prev_tool_count = len(self._brain_state.last_tool_results) if self._brain_state else 0

                output, self._brain_state = self._brain.process_turn(
                    command, self._brain_state
                )
                reply = str(getattr(output, "assistant_reply", "") or "").strip()
                if not reply and getattr(output, "ask_user", False):
                    reply = str(getattr(output, "question", "") or "").strip()

                # Extract only THIS turn's tool results
                _current_tools = (
                    self._brain_state.last_tool_results[_prev_tool_count:]
                    if self._brain_state else []
                )

                # ── Issue #869: Check if this turn created a pending confirmation ──
                confirmation_pending = (
                    self._brain_state is not None
                    and self._brain_state.has_pending_confirmation()
                )
                if confirmation_pending:
                    pending = self._brain_state.peek_pending_confirmation() or {}
                    conf_prompt = str(pending.get("prompt") or "").strip()
                    conf_tool = str(pending.get("tool") or "")
                    # Use the confirmation prompt as the reply text
                    if conf_prompt:
                        reply = conf_prompt

                # Show speaking state on overlay
                if overlay._client and overlay._client.connected and reply:
                    overlay.speaking_sync(reply[:100])

                return {
                    "ok": True,
                    "text": reply or "Anlayamadım efendim.",
                    "brain": True,
                    "route": getattr(output, "route", "unknown"),
                    "needs_confirmation": confirmation_pending,
                    "confirmation_prompt": (
                        str((self._brain_state.peek_pending_confirmation() or {}).get("prompt", ""))
                        if confirmation_pending else None
                    ),
                    "confirmation_tool": (
                        str((self._brain_state.peek_pending_confirmation() or {}).get("tool", ""))
                        if confirmation_pending else None
                    ),
                    "tools_used": [
                        {"tool": r.get("tool", ""), "args": r.get("params", {})}
                        for r in _current_tools
                    ] or None,
                }
            except Exception as e:
                logging.getLogger(__name__).error("Brain handler failed: %s", e)
                # Show error on overlay then idle
                if overlay._client and overlay._client.connected:
                    overlay.speaking_sync(f"Hata: {e}"[:100])
                return {
                    "ok": False,
                    "text": f"İşlem sırasında hata oluştu: {e}",
                    "brain": True,
                    "route": "error",
                }
            finally:
                # Always return overlay to idle after brain processing
                if overlay._client and overlay._client.connected:
                    try:
                        overlay.idle_sync()
                    except Exception:
                        pass

        # Route command (Router path — browser_* intents or brain unavailable)
        router = self._get_router()
        result = router.handle(text=command, ctx=self.ctx)

        # Show speaking state with result
        if overlay._client and overlay._client.connected:
            if result.ok:
                # Show response text, then auto-hide after timeout
                overlay.speaking_sync(result.user_text[:100] if result.user_text else "Tamam!")
            else:
                overlay.speaking_sync(result.user_text[:100] if result.user_text else "Bir sorun oluştu.")

        # If this was a scan, store pagination state
        if parsed.intent == "browser_scan" and result.ok:
            scan = None
            if result.data and isinstance(result.data, dict):
                scan = result.data.get("scan")

            if not scan:
                try:
                    from bantz.browser.extension_bridge import get_bridge
                    bridge = get_bridge()
                    if bridge:
                        scan = bridge.get_last_scan()
                except Exception:
                    scan = None

            if scan:
                self._last_scan = scan
                self._scan_page_index = 0
                return self._format_scan_result(scan)

        return {
            "ok": result.ok,
            "text": result.user_text,
            "intent": result.intent,
            "needs_confirmation": result.needs_confirmation,
            "data": result.data,
        }

    def _format_scan_result(self, scan: dict) -> dict:
        """Format scan result with pagination."""
        elements = list(scan.get("elements") or [])
        total = len(elements)
        start = self._scan_page_index * self._scan_page_size
        end = min(start + self._scan_page_size, total)
        page_elements = elements[start:end]

        title = str(scan.get("title") or "?")
        url = str(scan.get("url") or "?")

        lines = [f"Sayfa: {title}", f"URL: {url}", ""]
        for el in page_elements:
            try:
                idx = el.get("index")
                role = el.get("role")
                text = str(el.get("text") or "")
            except AttributeError:
                idx, role, text = "?", "?", str(el)
            lines.append(f"  [{idx}] ({role}) {text[:40]}{'…' if len(text) > 40 else ''}")

        if end < total:
            lines.append(f"\n... ve {total - end} öğe daha. 'daha fazla' de.")
        else:
            lines.append("")

        return {
            "ok": True,
            "text": "\n".join(lines) + " Başka ne yapayım?",
            "intent": "browser_scan",
            "pagination": {"total": total, "showing": f"{start+1}-{end}", "page": self._scan_page_index + 1},
        }

    def _paginate_next(self) -> dict:
        """Show next page of scan results."""
        scan = self._last_scan
        if not scan:
            try:
                from bantz.browser.extension_bridge import get_bridge
                bridge = get_bridge()
                if bridge:
                    scan = bridge.get_last_scan()
            except Exception:
                scan = None

        if not scan:
            return {"ok": False, "text": "Gösterilecek tarama yok. Önce 'sayfayı tara' de."}

        total = len(list(scan.get("elements") or []))
        max_page = (total - 1) // self._scan_page_size
        if self._scan_page_index < max_page:
            self._scan_page_index += 1
        self._last_scan = scan
        return self._format_scan_result(scan)

    def _paginate_prev(self) -> dict:
        """Show previous page of scan results."""
        scan = self._last_scan
        if not scan:
            try:
                from bantz.browser.extension_bridge import get_bridge
                bridge = get_bridge()
                if bridge:
                    scan = bridge.get_last_scan()
            except Exception:
                scan = None

        if not scan:
            return {"ok": False, "text": "Gösterilecek tarama yok. Önce 'sayfayı tara' de."}

        if self._scan_page_index > 0:
            self._scan_page_index -= 1
        self._last_scan = scan
        return self._format_scan_result(scan)

    def _run_startup_briefing(self, overlay_hook: "IPCOverlayHook") -> None:
        """Run startup briefing in background thread — sends news, calendar,
        weather, and system data to the overlay via IPC.

        This wires together:
        - DailyBriefingService (news, calendar, email sections)
        - BriefingOverlay protocol (briefing_start/card/end IPC messages)
        - Calendar + weather data fetched from IngestStore or live APIs
        """
        import threading

        def _briefing_thread() -> None:
            import asyncio as _aio

            loop = _aio.new_event_loop()
            _aio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    self._send_startup_briefing_async(overlay_hook)
                )
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "[STARTUP_BRIEFING] failed: %s", e
                )
            finally:
                loop.close()

        t = threading.Thread(
            target=_briefing_thread,
            daemon=True,
            name="bantz-startup-briefing",
        )
        t.start()
        print("   Startup Briefing: arka planda hazırlanıyor...")

    async def _send_startup_briefing_async(
        self, overlay_hook: "IPCOverlayHook"
    ) -> None:
        """Async startup briefing — fetches live data and sends to overlay."""
        from bantz.services.briefing_overlay import (
            BriefingStartMessage,
            BriefingCardMessage,
            BriefingEndMessage,
        )

        _log = logging.getLogger(__name__)

        # ── Helper: send a dict to the overlay ──
        def _send_msg(msg_dict: dict) -> None:
            if overlay_hook._client and overlay_hook._client.connected:
                try:
                    import asyncio as _aio2

                    if overlay_hook._loop and overlay_hook._loop.is_running():
                        fut = _aio2.run_coroutine_threadsafe(
                            overlay_hook._client.send_raw(msg_dict),
                            overlay_hook._loop,
                        )
                        fut.result(timeout=5.0)
                    else:
                        _log.debug("[BRIEFING] overlay loop not running")
                except Exception as e:
                    _log.debug("[BRIEFING] send failed: %s", e)

        # ── 1. Generate briefing via DailyBriefingService ──
        calendar_events = []
        unread_emails = 0
        important_emails = 0

        # Try to fetch calendar data from IngestStore (synced data)
        try:
            from bantz.data.ingest_store import IngestStore

            store = IngestStore()
            cached_cal = store.query(source="calendar_sync", limit=20)
            if cached_cal:
                import json

                for rec in cached_cal:
                    try:
                        data = (
                            json.loads(rec.content)
                            if isinstance(rec.content, str)
                            else rec.content
                        )
                        if isinstance(data, dict):
                            calendar_events.append(data)
                    except Exception:
                        pass
                _log.info(
                    "[BRIEFING] %d calendar events from IngestStore",
                    len(calendar_events),
                )
        except Exception as e:
            _log.debug("[BRIEFING] IngestStore calendar fetch failed: %s", e)

        # Fallback: fetch calendar from Google API directly
        if not calendar_events:
            try:
                from bantz.google.calendar import list_events

                raw_events = list_events(max_results=10)
                if isinstance(raw_events, list):
                    calendar_events = raw_events
                elif isinstance(raw_events, dict):
                    calendar_events = raw_events.get("events", [])
                _log.info(
                    "[BRIEFING] %d calendar events from Google API",
                    len(calendar_events),
                )
            except Exception as e:
                _log.debug("[BRIEFING] Google Calendar fetch failed: %s", e)

        # Try to get Gmail summary from IngestStore
        try:
            from bantz.data.ingest_store import IngestStore

            store = IngestStore()
            cached_mail = store.query(source="gmail_sync", limit=50)
            if cached_mail:
                unread_emails = len(cached_mail)
                # Rough heuristic: emails from classified "important" sources
                important_emails = sum(
                    1
                    for r in cached_mail
                    if r.meta
                    and r.meta.get("classification", {}).get("category") in (
                        "work", "bank", "tubitak", "education",
                    )
                )
        except Exception:
            pass

        # ── 2. Run the briefing service ──
        from bantz.services.startup_hook import run_startup_briefing

        briefing_dict = await run_startup_briefing(
            event_bus=self._event_bus,
            overlay_client=None,  # We handle overlay sending ourselves
            calendar_events=calendar_events,
            unread_emails=unread_emails,
            important_emails=important_emails,
        )

        # ── 3. Send briefing_start ──
        import asyncio

        news_cards = briefing_dict.get("news_cards", [])
        sections = briefing_dict.get("sections", [])

        # Count total cards we'll send
        cal_events = []
        for sec in sections:
            if sec.get("type") == "calendar":
                cal_events = sec.get("items", [])

        total_cards = len(news_cards) + len(cal_events) + 1  # +1 for weather

        start_msg = BriefingStartMessage(
            greeting=briefing_dict.get("greeting", ""),
            time_context=briefing_dict.get("time_context", {}),
            total_cards=total_cards,
            days_away=briefing_dict.get("days_away", 0),
        )
        _send_msg(start_msg.to_dict())
        await asyncio.sleep(2.0)

        cards_shown = 0

        # ── 4. Send news cards ──
        for i, card in enumerate(news_cards):
            card_msg = BriefingCardMessage(
                index=i,
                total=total_cards,
                title=card.get("title", ""),
                summary=card.get("summary", ""),
                source=card.get("source", ""),
                category="news",
                image_url=card.get("image_url"),
                url=card.get("url", ""),
            )
            _send_msg(card_msg.to_dict())
            cards_shown += 1
            await asyncio.sleep(3.0)

        # ── 5. Send calendar cards ──
        for i, evt in enumerate(cal_events):
            cal_card = {
                "type": "briefing_card",
                "category": "calendar",
                "title": evt.get("title", evt.get("summary", "")),
                "start": evt.get("start", evt.get("start_time", "")),
                "end": evt.get("end", evt.get("end_time", "")),
                "all_day": evt.get("all_day", False),
                "id": evt.get("id", f"cal-{i}"),
            }
            _send_msg(cal_card)
            cards_shown += 1
            await asyncio.sleep(0.3)

        # ── 6. Send weather card ──
        try:
            import urllib.request
            import json as _json

            location = os.environ.get(
                "BANTZ_WEATHER_LOCATION",
                os.environ.get("BANTZ_LOCATION", "Corum"),
            )
            url = f"https://wttr.in/{location}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "bantz/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                weather_data = _json.loads(resp.read())

            current = weather_data.get("current_condition", [{}])[0]
            weather_card = {
                "type": "briefing_card",
                "category": "weather",
                "temperature": int(current.get("temp_C", 0)),
                "condition": current.get("weatherDesc", [{}])[0].get("value", ""),
                "humidity": int(current.get("humidity", 0)),
                "wind_speed": int(current.get("windspeedKmph", 0)),
            }
            _send_msg(weather_card)
            cards_shown += 1
        except Exception as e:
            _log.debug("[BRIEFING] weather fetch failed: %s", e)

        # ── 7. Send system metrics card ──
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            uptime = int(time.time() - psutil.boot_time())

            sys_card = {
                "type": "briefing_card",
                "category": "system",
                "cpu": round(cpu, 1),
                "ram": round(mem.percent, 1),
                "disk": round(disk.percent, 1),
                "uptime_seconds": uptime,
            }
            _send_msg(sys_card)
            cards_shown += 1
        except Exception as e:
            _log.debug("[BRIEFING] system metrics failed: %s", e)

        await asyncio.sleep(1.0)

        # ── 8. Send briefing_end ──
        end_msg = BriefingEndMessage(
            total_shown=cards_shown,
            summary=briefing_dict.get("spoken_text", ""),
        )
        _send_msg(end_msg.to_dict())

        _log.info(
            "[STARTUP_BRIEFING] complete: %d cards sent (news=%d, cal=%d)",
            cards_shown,
            len(news_cards),
            len(cal_events),
        )

    def run_socket_only(self) -> None:
        """Start ONLY the session socket accept loop.

        Unlike ``run()`` this does NOT start overlay, extension bridge,
        reminder scheduler or startup briefing — those are managed by the
        orchestrator.  Use this when the server is embedded inside
        ``BantzOrchestrator`` to avoid double-init.
        """
        self._cleanup_socket()

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(str(self.socket_path))
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)

        import atexit
        atexit.register(self._cleanup_socket)
        self._running = True

        print(f"   Session socket: {self.socket_path}")

        while self._running:
            try:
                conn, _ = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            self._handle_client(conn)

        self._server_socket.close()
        self._cleanup_socket()

    def run(self) -> None:
        """Start the server loop."""
        self._cleanup_socket()

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(str(self.socket_path))
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)  # For graceful shutdown

        atexit.register(self._cleanup_socket)
        self._running = True

        # Start reminder scheduler background thread
        reminder_manager = get_reminder_manager()
        reminder_manager.start_scheduler()

        # Start IPC overlay (separate process)
        overlay_hook = get_ipc_overlay_hook()
        overlay_started = overlay_hook.start()
        if overlay_started:
            set_overlay_hook(overlay_hook)
        else:
            print("   Overlay: devre dışı (başlatılamadı)")

        # Start extension bridge WebSocket server
        from bantz.browser.extension_bridge import start_extension_bridge, stop_extension_bridge
        ws_started = start_extension_bridge(command_handler=self.handle_command)
        if ws_started:
            print("   Extension Bridge: ws://localhost:9876 ✓")
        else:
            print("   Extension Bridge: devre dışı (websockets yükleyin)")

        # ── Startup Briefing (news, calendar, weather → overlay) ──
        if overlay_started:
            self._run_startup_briefing(overlay_hook)

        print(f"🚀 Bantz Server başlatıldı (session: {self.session_name})")
        print(f"   Socket: {self.socket_path}")
        print(f"   Kapatmak için: Ctrl+C veya başka terminalden 'bantz --session {self.session_name} --stop'")

        while self._running:
            try:
                conn, _ = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            # Handle client in SAME thread (critical for Playwright greenlet)
            # Playwright's sync API uses greenlet which cannot switch threads
            self._handle_client(conn)

        # Cleanup
        self._server_socket.close()
        self._cleanup_socket()

        # Stop overlay IPC
        try:
            overlay_hook = get_ipc_overlay_hook()
            overlay_hook.stop()
            set_overlay_hook(None)
            print("   Overlay: durduruldu")
        except Exception:
            pass

        # Stop extension bridge
        try:
            from bantz.browser.extension_bridge import stop_extension_bridge
            stop_extension_bridge()
        except Exception:
            pass

        # Unsubscribe inbox listener
        try:
            self._event_bus.unsubscribe("bantz_message", self._on_bantz_message)
        except Exception:
            pass

        # Stop scheduler
        try:
            reminder_manager = get_reminder_manager()
            reminder_manager.stop_scheduler()
        except Exception:
            pass

        # Stop data sync scheduler
        try:
            if self._sync_scheduler is not None and self._sync_loop is not None:
                import asyncio as _aio
                future = _aio.run_coroutine_threadsafe(
                    self._sync_scheduler.stop(), self._sync_loop,
                )
                future.result(timeout=5)
                self._sync_loop.call_soon_threadsafe(self._sync_loop.stop)
                if self._sync_thread is not None:
                    self._sync_thread.join(timeout=3)
                logging.getLogger(__name__).info("Data sync scheduler stopped.")
        except Exception:
            pass

        # Close browser
        from bantz.browser.controller import get_controller
        try:
            get_controller().close()
        except Exception:
            pass

        print("\n👋 Bantz Server kapatıldı.")

    # ── length-prefix framing helpers ─────────────────────────

    @staticmethod
    def _send_framed(sock: socket.socket, payload: bytes) -> None:
        """Send *payload* prefixed with a 4-byte big-endian length header."""
        header = struct.pack("!I", len(payload))
        sock.sendall(header + payload)

    @staticmethod
    def _recv_framed(sock: socket.socket) -> bytes:
        """Read a length-prefixed frame."""
        # Read the first 4 bytes (length header)
        header = b""
        while len(header) < 4:
            chunk = sock.recv(4 - len(header))
            if not chunk:
                return b""
            header += chunk

        length = struct.unpack("!I", header)[0]

        # Sanity check: a realistic JSON payload < 64 MB
        if length > 67_108_864:
            raise ValueError(f"Frame too large: {length} bytes")

        # Read exactly *length* bytes
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(min(65536, length - len(data)))
            if not chunk:
                break
            data += chunk
        return bytes(data)

    def _handle_client(self, conn: socket.socket) -> None:
        """Handle a single client connection."""
        try:
            raw = self._recv_framed(conn)
            if not raw:
                return

            data = raw.decode("utf-8")
            request = json.loads(data)
            command = request.get("command", "")

            response = self.handle_command(command)
            self._send_framed(conn, json.dumps(response).encode("utf-8"))
        except Exception as e:
            error_response = {"ok": False, "text": f"Server hatası: {e}"}
            try:
                self._send_framed(conn, json.dumps(error_response).encode("utf-8"))
            except Exception:
                pass
        finally:
            conn.close()


def send_to_server(command: str, session_name: str = DEFAULT_SESSION, timeout: float = 30.0) -> dict:
    """Send command to running server and get response."""
    socket_path = get_socket_path(session_name)

    if not socket_path.exists():
        return {"ok": False, "text": f"Session '{session_name}' çalışmıyor. Önce 'bantz --serve' ile başlat.", "not_running": True}

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(socket_path))

        request = json.dumps({"command": command})
        payload = request.encode("utf-8")
        header = struct.pack("!I", len(payload))
        client.sendall(header + payload)

        # Read length-prefixed response
        resp_header = b""
        while len(resp_header) < 4:
            chunk = client.recv(4 - len(resp_header))
            if not chunk:
                break
            resp_header += chunk

        if len(resp_header) < 4:
            client.close()
            return {"ok": False, "text": "Server yanıt başlığı okunamadı."}

        resp_length = struct.unpack("!I", resp_header)[0]
        resp_data = bytearray()
        while len(resp_data) < resp_length:
            chunk = client.recv(min(65536, resp_length - len(resp_data)))
            if not chunk:
                break
            resp_data += chunk

        client.close()

        return json.loads(resp_data.decode("utf-8"))
    except socket.timeout:
        return {"ok": False, "text": "Server yanıt vermedi (timeout)."}
    except ConnectionRefusedError:
        return {"ok": False, "text": f"Session '{session_name}' bağlantısı reddedildi.", "not_running": True}
    except Exception as e:
        return {"ok": False, "text": f"Bağlantı hatası: {e}"}


def is_server_running(session_name: str = DEFAULT_SESSION) -> bool:
    """Check if server is running."""
    socket_path = get_socket_path(session_name)
    if not socket_path.exists():
        return False

    try:
        response = send_to_server("__status__", session_name, timeout=2.0)
        return response.get("ok", False)
    except Exception:
        return False


def start_server(
    session_name: str = DEFAULT_SESSION,
    policy_path: str = "config/policy.json",
    log_path: str = "bantz.log.jsonl",
) -> None:
    """Start a new server instance."""
    server = BantzServer(session_name=session_name, policy_path=policy_path, log_path=log_path)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n🛑 Interrupt alındı, kapatılıyor...")
