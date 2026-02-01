"""Bantz Session Server - Unix socket daemon.

Tarayıcıyı ve context'i canlı tutar.
CLI komutları socket üzerinden alır, sonuçları döner.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
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
        hint = " (ipuçu: terminalde 'bantz --serve --session {s}' deneyebilirsin)".format(s=session_name)
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
            hint = " (ipuçu: 'bantz --serve --session {s}' ile hata çıktısını gör)".format(s=session_name)
            return False, True, f"crashed:{short}{hint}" if short else f"crashed{hint}"

        time.sleep(0.1)

    return False, True, "timeout (ipuçu: 'bantz --serve --session {s}' ile manuel başlatıp logu gör)".format(s=session_name)


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
            future = asyncio.run_coroutine_threadsafe(
                self._client.start(auto_spawn=True),
                self._loop,
            )
            
            # Wait for connection (max 10 seconds)
            connected = future.result(timeout=10.0)
            
            if connected:
                print("   Overlay: bağlandı ✓")
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
                    "pending": self.ctx.pending is not None,
                },
            }

        # Pagination commands
        if command.lower() in {"daha fazla", "daha", "more", "next"}:
            return self._paginate_next()

        if command.lower() in {"önceki", "previous", "prev", "geri"}:
            return self._paginate_prev()

        # Browser commands need browser init
        from bantz.router.nlu import parse_intent
        parsed = parse_intent(command)
        if parsed.intent.startswith("browser_"):
            self._init_browser()

        # Show thinking state on overlay
        overlay = get_ipc_overlay_hook()
        if overlay._client and overlay._client.connected:
            overlay.thinking_sync("Anlıyorum...")

        # Route command
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
        except:
            pass

        # Close browser
        from bantz.browser.controller import get_controller
        try:
            get_controller().close()
        except:
            pass

        print("\n👋 Bantz Server kapatıldı.")

    def _handle_client(self, conn: socket.socket) -> None:
        """Handle a single client connection."""
        try:
            data = conn.recv(65536).decode("utf-8")
            if not data:
                return

            request = json.loads(data)
            command = request.get("command", "")

            response = self.handle_command(command)
            conn.sendall(json.dumps(response).encode("utf-8"))
        except Exception as e:
            error_response = {"ok": False, "text": f"Server hatası: {e}"}
            try:
                conn.sendall(json.dumps(error_response).encode("utf-8"))
            except:
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
        client.sendall(request.encode("utf-8"))

        response_data = client.recv(65536).decode("utf-8")
        client.close()

        return json.loads(response_data)
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
    except:
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
