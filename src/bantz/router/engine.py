from __future__ import annotations

from dataclasses import asdict
from typing import Optional, Callable, Awaitable

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.dev_bridge import DevBridge
from bantz.router.nlu import parse_intent, split_chain, Parsed
from bantz.router.policy import Policy
from bantz.router.types import RouterResult
from bantz.skills.daily import (
    open_btop,
    open_browser,
    open_path,
    open_url,
    google_search,
    notify,
)
from bantz.skills.pc import (
    open_app,
    close_app,
    focus_app,
    list_windows,
    type_text,
    send_key,
    move_mouse,
    click_mouse,
    scroll_mouse,
    hotkey,
    clipboard_set,
    clipboard_get,
)


# ─────────────────────────────────────────────────────────────
# Overlay State Hook Protocol
# ─────────────────────────────────────────────────────────────
# These hooks are called by the router to update overlay state.
# The actual implementation uses IPC to communicate with overlay process.

class OverlayStateHook:
    """Protocol for overlay state updates."""
    
    async def wake(self, text: str = "Sizi dinliyorum efendim.") -> None:
        """Show wake state."""
        pass
    
    async def listening(self, text: str = "Dinliyorum...") -> None:
        """Show listening state."""
        pass
    
    async def thinking(self, text: str = "Anlıyorum...") -> None:
        """Show thinking state."""
        pass
    
    async def speaking(self, text: str = "") -> None:
        """Show speaking state with response text."""
        pass
    
    async def idle(self) -> None:
        """Hide overlay (return to idle)."""
        pass
    
    async def set_position(self, position: str) -> bool:
        """Update overlay position. Returns True if valid position."""
        return False

    async def preview_action(self, text: str, duration_ms: int = 1200) -> None:
        """Show transient action preview text."""
        pass

    async def cursor_dot(self, x: int, y: int, duration_ms: int = 800) -> None:
        """Show transient cursor dot at (x,y)."""
        pass

    async def highlight_rect(self, x: int, y: int, w: int, h: int, duration_ms: int = 1200) -> None:
        """Highlight rectangle region."""
        pass


# Global overlay hook instance (set by daemon)
_overlay_hook: Optional[OverlayStateHook] = None


def set_overlay_hook(hook: OverlayStateHook) -> None:
    """Set the global overlay hook (called by daemon on startup)."""
    global _overlay_hook
    _overlay_hook = hook


def get_overlay_hook() -> Optional[OverlayStateHook]:
    """Get the current overlay hook."""
    return _overlay_hook


class Router:
    def __init__(self, policy: Policy, logger: JsonlLogger):
        self._policy = policy
        self._logger = logger
        self._dev_bridge = DevBridge()

        # Agent framework (lazy import usage)
        self._agent_history: list[dict] = []
        self._agent_history_by_id: dict[str, dict] = {}

    def _agent_rec(self, task_id: str | None) -> Optional[dict]:
        if not task_id:
            return None
        return self._agent_history_by_id.get(task_id)

    def handle(self, text: str, ctx: ConversationContext) -> RouterResult:
        ctx.reset_if_expired()
        ctx.reset_pending_if_expired()

        ctx_before = ctx.snapshot()
        parsed = parse_intent(text)

        # ─────────────────────────────────────────────────────────────
        # Agent mode: plan -> queue (Issue #3)
        # Explicitly triggered by NLU prefix (agent: / planla: ...)
        # Uses existing queue runner for execution + policy gating.
        #
        # Two modes:
        #   - agent: ... → preview plan first, wait for confirmation
        #   - agent!: ... → skip preview, execute immediately
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "agent_run":
            if ctx.queue_active():
                result = RouterResult(
                    ok=False,
                    intent="agent_run",
                    user_text=(
                        "Şu an aktif bir kuyruk var. Önce 'agent iptal' / 'iptal et' deyip temizleyebilirsin, "
                        "ya da 'devam et' ile devam ettirebilirsin."
                    ),
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            request = str(parsed.slots.get("request") or "").strip()
            if not request:
                result = RouterResult(ok=False, intent="agent_run", user_text="Agent için bir istek yazmalısın. Örn: agent: YouTube'a git, Coldplay ara")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            skip_preview = bool(parsed.slots.get("skip_preview", False))

            try:
                from bantz.agent.builtin_tools import build_default_registry
                from bantz.agent.core import Agent
                from bantz.agent.planner import Planner

                tools = build_default_registry()
                agent = Agent(planner=Planner(), tools=tools)

                task_id = f"agent-{len(self._agent_history) + 1}"
                task = agent.plan(request, task_id=task_id)

                steps: list[QueueStep] = []
                step_recs: list[dict] = []
                for s in task.steps:
                    # Planned tool names map to router intents.
                    steps.append(QueueStep(original_text=s.description, intent=str(s.action), slots=dict(s.params)))
                    step_recs.append({
                        "description": s.description,
                        "action": str(s.action),
                        "params": dict(s.params),
                        "status": "pending",
                    })

                if not steps:
                    raise ValueError("agent_empty_plan")

                rec = {
                    "id": str(task.id),
                    "request": request,
                    "state": "planned",
                    "steps": step_recs,
                }
                self._agent_history.append(rec)
                self._agent_history_by_id[str(task.id)] = rec

                # If skip_preview, execute immediately
                if skip_preview:
                    ctx.set_queue(steps, source="agent", task_id=str(task.id))
                    return self._run_queue(ctx, ctx_before, text)

                # Otherwise, show preview and wait for confirmation
                rec["state"] = "awaiting_confirmation"
                ctx.set_pending_agent_plan(task_id=str(task.id), steps=steps)

                # Build preview message
                preview_lines = [f"📋 Agent Planı ({len(steps)} adım):"]
                for i, s in enumerate(step_recs, start=1):
                    desc = str(s.get("description") or s.get("action") or "?")
                    preview_lines.append(f"  {i}. {desc}")
                preview_lines.append("")
                preview_lines.append("Bu planı çalıştırmak için:")
                preview_lines.append("  • 'evet' / 'onayla' / 'başlat' → çalıştırır")
                preview_lines.append("  • 'hayır' / 'iptal' → iptal eder")

                result = RouterResult(
                    ok=True,
                    intent="agent_run",
                    user_text="\n".join(preview_lines),
                    needs_confirmation=True,
                    confirmation_prompt="Planı onaylıyor musun?",
                    data={"task_id": str(task.id), "step_count": len(steps)},
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            except Exception as e:
                result = RouterResult(
                    ok=False,
                    intent="agent_run",
                    user_text=(
                        "Agent planı çıkaramadım. Daha net söyler misin? "
                        "Örn: agent: youtube'a git ve coldplay ara"
                    ),
                    data={"error": str(e)},
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

        # ─────────────────────────────────────────────────────────────
        # Agent plan confirmation (after preview)
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "agent_confirm_plan":
            pending_plan = ctx.get_pending_agent_plan()
            if not pending_plan:
                result = RouterResult(
                    ok=False,
                    intent="agent_confirm_plan",
                    user_text="Onaylanacak bekleyen bir agent planı yok. 'agent: ...' diyerek yeni bir plan oluşturabilirsin.",
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            task_id = pending_plan.get("task_id")
            steps = pending_plan.get("steps", [])
            ctx.clear_pending_agent_plan()

            if not steps:
                result = RouterResult(ok=False, intent="agent_confirm_plan", user_text="Plan boş görünüyor.")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            # Update task state
            rec = self._agent_rec(task_id)
            if rec is not None:
                rec["state"] = "running"

            ctx.set_queue(steps, source="agent", task_id=str(task_id))
            return self._run_queue(ctx, ctx_before, text)

        if parsed.intent == "agent_status":
            task_id = getattr(ctx, "current_agent_task_id", None)
            if ctx.queue_source != "agent" or not ctx.queue_active() or not task_id:
                result = RouterResult(ok=True, intent="agent_status", user_text="Şu an çalışan bir agent görevi yok. Örn: agent: youtube'a git ve coldplay ara")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            rec = self._agent_rec(str(task_id))
            total = len(ctx.queue)
            idx = int(ctx.queue_index)
            current = ctx.current_step()

            lines = ["🤖 Agent durum:"]
            lines.append(f"- id: {task_id}")
            if rec is not None:
                lines.append(f"- state: {rec.get('state')}")
                lines.append(f"- istek: {rec.get('request')}")
            lines.append(f"- ilerleme: {idx+1}/{max(total, 1)}")
            if current is not None:
                lines.append(f"- şu an: {current.original_text}")

            result = RouterResult(ok=True, intent="agent_status", user_text="\n".join(lines) + "\nBaşka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "agent_history":
            if not self._agent_history:
                result = RouterResult(ok=True, intent="agent_history", user_text="Henüz agent görevi çalıştırmadım. Örn: agent: YouTube'a git, Coldplay ara")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            n = parsed.slots.get("n")
            if isinstance(n, int):
                n = max(1, min(int(n), 10))
            else:
                n = 1

            # If user asks for multiple, show compact list.
            if n > 1:
                recent = self._agent_history[-n:]
                lines = [f"🤖 Son {len(recent)} agent task:"]
                for item in reversed(recent):
                    tid = item.get("id")
                    state = item.get("state")
                    req = str(item.get("request") or "")
                    lines.append(f"- {tid} [{state}] {req[:60]}{'…' if len(req) > 60 else ''}")
                result = RouterResult(ok=True, intent="agent_history", user_text="\n".join(lines) + "\nBaşka ne yapayım?")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            last = self._agent_history[-1]
            lines = ["🤖 Son agent planı:"]
            lines.append(f"- id: {last.get('id')}")
            lines.append(f"- istek: {last.get('request')}")
            state = str(last.get("state") or "?")
            lines.append(f"- durum: {state}")

            steps = last.get("steps") or []
            if steps:
                lines.append("- adımlar:")
                for i, s in enumerate(steps, start=1):
                    if isinstance(s, dict):
                        desc = str(s.get("description") or "")
                        st = str(s.get("status") or "pending")
                        meta_bits: list[str] = []
                        attempts = s.get("attempts")
                        if isinstance(attempts, int) and attempts > 1:
                            meta_bits.append(f"attempts={attempts}")
                        resolved_index = s.get("resolved_index")
                        if isinstance(resolved_index, int) and resolved_index > 0:
                            meta_bits.append(f"resolved=[{resolved_index}]")
                        resolved_text = str(s.get("resolved_text") or "").strip()
                        if resolved_text:
                            short = (resolved_text[:22] + "…") if len(resolved_text) > 23 else resolved_text
                            meta_bits.append(f"target='{short}'")
                        if s.get("recovery_attempted"):
                            strat = str(s.get("recovery_strategy") or "?")
                            rres = str(s.get("recovery_result") or "?")
                            meta_bits.append(f"recovery={strat}:{rres}")
                        if s.get("verification_attempted"):
                            vok = s.get("verification_ok")
                            vreason = str(s.get("verification_reason") or "")
                            if vok is True:
                                meta_bits.append("verify=ok")
                            else:
                                meta_bits.append(f"verify=fail{(':'+vreason) if vreason else ''}")
                        suffix = f" ({', '.join(meta_bits)})" if meta_bits else ""
                        lines.append(f"  {i}. [{st}] {desc}{suffix}")
                    else:
                        lines.append(f"  {i}. {s}")

            # Also show count of past tasks (short)
            if len(self._agent_history) > 1:
                lines.append(f"\nToplam agent task: {len(self._agent_history)}")

            result = RouterResult(ok=True, intent="agent_history", user_text="\n".join(lines) + "\nBaşka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Agent retry: son başarısız/yarım kalan task'ı tekrar çalıştır
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "agent_retry":
            # Check if there's an active queue
            if ctx.queue_active():
                result = RouterResult(
                    ok=False,
                    intent="agent_retry",
                    user_text="Şu an aktif bir kuyruk var. Önce 'iptal et' deyip temizle, sonra 'agent tekrar' dene.",
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            # Find the last failed/paused/aborted task
            retryable_task: dict | None = None
            for rec in reversed(self._agent_history):
                state = str(rec.get("state") or "")
                if state in {"paused", "aborted", "failed"}:
                    retryable_task = rec
                    break

            if retryable_task is None:
                result = RouterResult(
                    ok=False,
                    intent="agent_retry",
                    user_text="Tekrar deneyecek başarısız bir agent task bulamadım. 'agent geçmişi' diyerek geçmiş task'lara bakabilirsin.",
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            # Re-run the original request
            original_request = str(retryable_task.get("request") or "")
            if not original_request:
                result = RouterResult(
                    ok=False,
                    intent="agent_retry",
                    user_text="Eski task'ın isteğini bulamadım.",
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            # Mark old task as retried
            retryable_task["state"] = "retried"
            retryable_task["retried_as"] = f"agent-{len(self._agent_history) + 1}"

            # Delegate to agent_run logic
            try:
                from bantz.agent.builtin_tools import build_default_registry
                from bantz.agent.core import Agent
                from bantz.agent.planner import Planner

                tools = build_default_registry()
                agent = Agent(planner=Planner(), tools=tools)

                task_id = f"agent-{len(self._agent_history) + 1}"
                task = agent.plan(original_request, task_id=task_id)

                steps: list[QueueStep] = []
                step_recs: list[dict] = []
                for s in task.steps:
                    steps.append(QueueStep(original_text=s.description, intent=str(s.action), slots=dict(s.params)))
                    step_recs.append({
                        "description": s.description,
                        "action": str(s.action),
                        "params": dict(s.params),
                        "status": "pending",
                    })

                if not steps:
                    raise ValueError("agent_empty_plan")

                ctx.set_queue(steps, source="agent", task_id=str(task.id))

                rec = {
                    "id": str(task.id),
                    "request": original_request,
                    "state": "planned",
                    "steps": step_recs,
                    "retry_of": str(retryable_task.get("id")),
                }
                self._agent_history.append(rec)
                self._agent_history_by_id[str(task.id)] = rec

                return self._run_queue(ctx, ctx_before, text)

            except Exception as e:
                result = RouterResult(
                    ok=False,
                    intent="agent_retry",
                    user_text=f"Tekrar planlama başarısız: {e}",
                    data={"error": str(e)},
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

        # ─────────────────────────────────────────────────────────────
        # App session exit (always works, even with pending/queue)
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "app_session_exit":
            had_session = ctx.has_active_app()
            old_app = ctx.active_app
            ctx.cancel_all()
            ctx.clear_active_app()
            msg = (
                f"✅ {old_app} oturumundan çıktım. Normal moda döndüm."
                if had_session and old_app
                else "Zaten aktif uygulama oturumu yok."
            )
            result = RouterResult(ok=True, intent="app_session_exit", user_text=msg + " Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Mode transitions (always work, even with pending/queue)
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "enter_dev_mode":
            ctx.set_mode("dev")
            result = RouterResult(ok=True, intent="enter_dev_mode", user_text="Dev Mode aktif. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "exit_dev_mode":
            ctx.set_mode("normal")
            result = RouterResult(ok=True, intent="exit_dev_mode", user_text="Normal moda döndüm. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Overlay / UI control commands (always work)
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "overlay_move":
            position = parsed.slots.get("position", "orta")
            hook = get_overlay_hook()
            if hook:
                import asyncio
                try:
                    # Map Turkish position names to IPC positions
                    position_map = {
                        "sol üst": "top_left", "üst sol": "top_left",
                        "sağ üst": "top_right", "üst sağ": "top_right",
                        "sol alt": "bottom_left", "alt sol": "bottom_left",
                        "sağ alt": "bottom_right", "alt sağ": "bottom_right",
                        "orta": "center", "ortaya": "center", "merkez": "center",
                    }
                    ipc_position = position_map.get(position.lower(), "center")
                    
                    # Run async in sync context
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(hook.set_position(ipc_position))
                        success = True
                    else:
                        success = loop.run_until_complete(hook.set_position(ipc_position))
                    
                    if success:
                        result = RouterResult(ok=True, intent="overlay_move", user_text=f"{position.title()} konumuna taşındım.")
                    else:
                        result = RouterResult(ok=False, intent="overlay_move", user_text="O konumu anlayamadım.")
                except Exception as e:
                    result = RouterResult(ok=False, intent="overlay_move", user_text=f"Overlay hatası: {e}")
            else:
                result = RouterResult(ok=False, intent="overlay_move", user_text="Overlay bağlı değil.")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "overlay_hide":
            hook = get_overlay_hook()
            if hook:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(hook.idle())
                    else:
                        loop.run_until_complete(hook.idle())
                    result = RouterResult(ok=True, intent="overlay_hide", user_text="Gizlendim.")
                except Exception as e:
                    result = RouterResult(ok=False, intent="overlay_hide", user_text=f"Overlay hatası: {e}")
            else:
                result = RouterResult(ok=False, intent="overlay_hide", user_text="Overlay bağlı değil.")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Queue control commands
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "queue_pause":
            if ctx.queue_active():
                ctx.queue_paused = True
                if ctx.queue_source == "agent":
                    rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                    if rec is not None:
                        rec["state"] = "paused"
                result = RouterResult(ok=True, intent="queue_pause", user_text="Kuyruk duraklatıldı. 'devam et' diyebilirsin.")
            else:
                result = RouterResult(ok=False, intent="queue_pause", user_text="Aktif kuyruk yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "queue_resume":
            if ctx.queue_active() and ctx.queue_paused:
                ctx.queue_paused = False
                if ctx.queue_source == "agent":
                    rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                    if rec is not None:
                        rec["state"] = "running"
                return self._run_queue(ctx, ctx_before, text)
            elif ctx.queue_active():
                result = RouterResult(ok=False, intent="queue_resume", user_text="Kuyruk zaten çalışıyor.")
            else:
                result = RouterResult(ok=False, intent="queue_resume", user_text="Devam edilecek kuyruk yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "queue_abort":
            if ctx.queue_active():
                if ctx.queue_source == "agent":
                    rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                    if rec is not None:
                        rec["state"] = "aborted"
                        try:
                            steps = rec.get("steps") or []
                            # Mark remaining pending/running steps as skipped
                            for s in steps[int(ctx.queue_index):]:
                                if isinstance(s, dict) and s.get("status") in {"pending", "running", "waiting_confirmation"}:
                                    s["status"] = "skipped"
                        except Exception:
                            pass
                ctx.clear_queue()
                result = RouterResult(ok=True, intent="queue_abort", user_text="Kuyruk iptal edildi. Başka ne yapayım?")
            else:
                result = RouterResult(ok=True, intent="queue_abort", user_text="Aktif kuyruk yoktu. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "queue_skip":
            if ctx.queue_active():
                skipped = ctx.current_step()
                ctx.skip_current()
                msg = f"'{skipped.original_text if skipped else '?'}' adımını atladım."
                if ctx.queue_active():
                    return self._run_queue(ctx, ctx_before, text)
                else:
                    result = RouterResult(ok=True, intent="queue_skip", user_text=msg + " Kuyruk bitti. Başka ne yapayım?")
            else:
                result = RouterResult(ok=False, intent="queue_skip", user_text="Atlanacak adım yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "queue_status":
            if ctx.queue_active():
                remaining = ctx.remaining_steps()
                lines = [f"{i+1}. {s.original_text}" for i, s in enumerate(remaining)]
                paused_note = " (duraklatılmış)" if ctx.queue_paused else ""
                agent_note = ""
                if ctx.queue_source == "agent" and getattr(ctx, "current_agent_task_id", None):
                    agent_note = f" [agent:{ctx.current_agent_task_id}]"
                result = RouterResult(
                    ok=True,
                    intent="queue_status",
                    user_text=f"Kalan adımlar{paused_note}{agent_note}:\n" + "\n".join(lines) + "\nBaşka ne yapayım?",
                )
            else:
                result = RouterResult(ok=True, intent="queue_status", user_text="Aktif kuyruk yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Handle pending agent plan confirmation (before queue execution)
        # ─────────────────────────────────────────────────────────────
        pending_plan = ctx.get_pending_agent_plan()
        if pending_plan:
            if parsed.intent in {"confirm_yes", "agent_confirm_plan"}:
                task_id = pending_plan.get("task_id")
                steps = pending_plan.get("steps", [])
                ctx.clear_pending_agent_plan()

                if not steps:
                    result = RouterResult(ok=False, intent="agent_confirm_plan", user_text="Plan boş görünüyor.")
                    self._log(text, result, parsed, ctx_before, ctx)
                    return result

                # Update task state
                rec = self._agent_rec(task_id)
                if rec is not None:
                    rec["state"] = "running"

                ctx.set_queue(steps, source="agent", task_id=str(task_id))
                return self._run_queue(ctx, ctx_before, text)

            if parsed.intent in {"confirm_no", "cancel"}:
                task_id = pending_plan.get("task_id")
                ctx.clear_pending_agent_plan()

                # Update task state
                rec = self._agent_rec(task_id)
                if rec is not None:
                    rec["state"] = "cancelled"

                result = RouterResult(ok=True, intent="cancel", user_text="Agent planı iptal edildi. Başka ne yapayım?")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            # Waiting for confirmation, show reminder
            result = RouterResult(
                ok=False,
                intent="unknown",
                user_text="Bekleyen bir agent planı var. 'evet' / 'başlat' diyerek çalıştır veya 'iptal' de.",
                needs_confirmation=True,
            )
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Handle pending confirmation (queue step or single action)
        # ─────────────────────────────────────────────────────────────
        if ctx.pending and not ctx.pending.expired():
            if parsed.intent in {"confirm_no", "cancel"}:
                # "hayır" = bu adımı atla, kalan kuyruğa devam
                ctx.clear_pending()
                if ctx.queue_active():
                    ctx.skip_current()
                    if ctx.queue_active():
                        return self._run_queue(ctx, ctx_before, text)
                    else:
                        result = RouterResult(ok=True, intent=parsed.intent, user_text="Bu adımı atladım. Kuyruk bitti. Başka ne yapayım?")
                else:
                    result = RouterResult(ok=True, intent=parsed.intent, user_text="Tamam, iptal ettim. Başka ne yapayım?")
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            if parsed.intent == "confirm_yes":
                pending = ctx.pending
                ctx.clear_pending()
                decision, reason = self._policy.decide(
                    text=pending.original_text,
                    intent=pending.intent,
                    confirmed=True,
                )

                if decision == "deny":
                    # Still denied after confirmation (asla)
                    if ctx.queue_active():
                        ctx.skip_current()
                        if ctx.queue_active():
                            result = RouterResult(
                                ok=False,
                                intent="unknown",
                                user_text="Bu isteği güvenlik nedeniyle asla yapamam. Adımı atlıyorum.",
                            )
                            self._log(text, result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason})
                            return self._run_queue(ctx, ctx_before, text)
                        else:
                            result = RouterResult(ok=False, intent="unknown", user_text="Bu isteği güvenlik nedeniyle asla yapamam. Kuyruk bitti. Başka ne yapayım?")
                    else:
                        result = RouterResult(ok=False, intent="unknown", user_text="Bu isteği güvenlik nedeniyle asla yapamam. Başka ne yapayım?")
                    self._log(text, result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason})
                    return result

                # Execute the pending action
                exec_result = self._dispatch(intent=pending.intent, slots=pending.slots, ctx=ctx, in_queue=ctx.queue_active())
                self._log(text, exec_result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason}, executed={"intent": pending.intent, "slots": pending.slots})

                # If queue active, advance and continue
                if ctx.queue_active():
                    ctx.advance_queue()
                    if ctx.queue_active():
                        return self._run_queue(ctx, ctx_before, text)
                    else:
                        return RouterResult(ok=exec_result.ok, intent=exec_result.intent, user_text=exec_result.user_text.replace(" Ne arayayım?", "").rstrip() + " Kuyruk bitti. Başka ne yapayım?")

                return exec_result

            # Still awaiting confirmation
            result = RouterResult(
                ok=False,
                intent="unknown",
                user_text="Onay bekliyorum: evet / hayır / iptal",
                data={"pending_intent": ctx.pending.intent},
            )
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Session-aware intent remapping (active app context)
        # ─────────────────────────────────────────────────────────────
        if ctx.has_active_app():
            # "kapat" alone → close active app
            if parsed.intent == "cancel" and text.strip().lower() in {"kapat", "uygulamayı kapat", "bunu kapat", "pencereyi kapat"}:
                parsed = Parsed(intent="app_close", slots={"app": ctx.active_app})
            # "gönder" / "enter" → submit in active app
            elif parsed.intent == "unknown" and text.strip().lower() in {"gönder", "gonder", "enter", "enter bas"}:
                parsed = Parsed(intent="app_submit", slots={})

        # ─────────────────────────────────────────────────────────────
        # No pending: cancellation clears follow-up state & queue
        # ─────────────────────────────────────────────────────────────
        if parsed.intent == "cancel":
            ctx.cancel_all()
            result = RouterResult(ok=True, intent="cancel", user_text="Tamam. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # No pending: stray yes/no
        if parsed.intent in {"confirm_yes", "confirm_no"}:
            result = RouterResult(ok=False, intent=parsed.intent, user_text="Şu an onay bekleyen bir iş yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Context-based follow-up (free-text -> query)
        # ─────────────────────────────────────────────────────────────
        if ctx.awaiting == "search_query" and parsed.intent == "unknown":
            parsed = parse_intent(f"şunu ara: {text}")
            ctx.awaiting = None

        # ─────────────────────────────────────────────────────────────
        # Dev mode routing
        # ─────────────────────────────────────────────────────────────
        if ctx.mode == "dev":
            if parsed.intent not in {
                "debug_tail_logs",
                "cancel",
                "confirm_yes",
                "confirm_no",
                "enter_dev_mode",
                "exit_dev_mode",
                "queue_pause",
                "queue_resume",
                "queue_abort",
                "queue_skip",
                "queue_status",
            }:
                parsed = parse_intent("projede " + text)
                if parsed.intent != "dev_task":
                    parsed = Parsed(intent="dev_task", slots={"text": text, "original_intent": parsed.intent})

        intent = parsed.intent

        # ─────────────────────────────────────────────────────────────
        # Multi-step chain detection (sonra / ve sonra / ardından)
        # ─────────────────────────────────────────────────────────────
        chain_parts = split_chain(text)
        if len(chain_parts) > 1:
            steps: list[QueueStep] = []
            for part in chain_parts:
                p = parse_intent(part)
                if p.intent == "unknown" and not p.slots.get("risky"):
                    # Belirsiz adım → zincir başlatma (risky komutlar hariç)
                    result = RouterResult(
                        ok=False,
                        intent="unknown",
                        user_text=f"'{part}' adımını anlayamadım. Zinciri başlatamıyorum. Daha net söyler misin?",
                        data={"ambiguous_step": part},
                    )
                    self._log(text, result, parsed, ctx_before, ctx)
                    return result
                steps.append(QueueStep(original_text=part, intent=p.intent, slots=p.slots))

            ctx.set_queue(steps)
            return self._run_queue(ctx, ctx_before, text)

        # ─────────────────────────────────────────────────────────────
        # Debug command: tail logs
        # ─────────────────────────────────────────────────────────────
        if intent == "debug_tail_logs":
            n = int(parsed.slots.get("n", 20))
            entries = self._logger.tail(n=max(1, min(n, 200)))
            if not entries:
                result = RouterResult(ok=True, intent=intent, user_text="Log yok. Başka ne yapayım?")
            else:
                lines = []
                for e in entries:
                    req = str(e.get("request", ""))
                    res = e.get("result", {})
                    ok = res.get("ok")
                    it = res.get("intent")
                    mode = e.get("mode")
                    bridge = None
                    rdata = res.get("data") if isinstance(res, dict) else None
                    if isinstance(rdata, dict):
                        bridge = rdata.get("bridge")
                    extra = f" mode={mode}" if mode else ""
                    if bridge:
                        extra += f" bridge={bridge}"
                    lines.append(f"- ok={ok} intent={it}{extra} req={req}")
                result = RouterResult(
                    ok=True,
                    intent=intent,
                    user_text="Son komutlar:\n" + "\n".join(lines) + "\nBaşka ne yapayım?",
                )
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Show events (event bus history)
        # ─────────────────────────────────────────────────────────────
        if intent == "show_events":
            from bantz.core.events import get_event_bus
            n = int(parsed.slots.get("n", 10))
            bus = get_event_bus()
            events = bus.get_history(limit=n)
            
            if not events:
                result = RouterResult(ok=True, intent=intent, user_text="📭 Henüz olay yok. Başka ne yapayım?")
            else:
                lines = ["📋 Son olaylar:"]
                for ev in events:
                    time_str = ev.timestamp.strftime("%H:%M:%S")
                    data_preview = str(ev.data)[:50] + "..." if len(str(ev.data)) > 50 else str(ev.data)
                    lines.append(f"  [{time_str}] {ev.event_type}: {data_preview}")
                result = RouterResult(ok=True, intent=intent, user_text="\n".join(lines) + "\nBaşka ne yapayım?")
            
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Dev task handling
        # ─────────────────────────────────────────────────────────────
        if intent == "dev_task":
            if ctx.mode != "dev":
                result = RouterResult(
                    ok=False,
                    intent=intent,
                    user_text="Bu bir dev işi gibi görünüyor. 'dev moda geç' dersen Dev Bridge'e yönlendirebilirim. Başka ne yapayım?",
                    data={"text": parsed.slots.get("text")},
                )
                self._log(text, result, parsed, ctx_before, ctx)
                return result

            dev_result = self._dev_bridge.handle(text=str(parsed.slots.get("text", text)), ctx=ctx)
            self._log(text, dev_result, parsed, ctx_before, ctx, bridge="dev_stub", executed={"intent": "dev_bridge", "slots": {"bridge": "dev_stub"}})
            return dev_result

        # ─────────────────────────────────────────────────────────────
        # Unknown intent: ask to repeat instead of policy deny
        # ─────────────────────────────────────────────────────────────
        if intent == "unknown":
            result = RouterResult(
                ok=False,
                intent=intent,
                user_text=(
                    "Bunu komut olarak anlayamadım. Tekrar eder misin? "
                    "Örn: 'hatırlat: yarın 10'da toplantı' veya 'discord aç'."
                ),
                needs_confirmation=False,
                data={"reason": "unknown_intent"},
            )
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        # ─────────────────────────────────────────────────────────────
        # Policy evaluation (single action)
        # ─────────────────────────────────────────────────────────────
        # For browser_click, get click target text for risky check
        click_target = None
        if intent == "browser_click":
            click_target = self._get_click_target_text(parsed.slots)

        decision, reason = self._policy.decide(text=text, intent=intent, confirmed=False, click_target=click_target)
        if decision == "deny":
            result = RouterResult(
                ok=False,
                intent=intent,
                user_text="Bu isteği güvenlik nedeniyle yapamam.",
                needs_confirmation=False,
                data={"reason": reason},
            )
            self._log(text, result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason})
            return result

        if decision == "confirm":
            confirm_msg = "Bu istek riskli olabilir. Onaylıyor musun? (evet/hayır/iptal)"
            if reason.startswith("risky_click:"):
                target_text = reason.split(":", 1)[1] if ":" in reason else ""
                confirm_msg = f"'{target_text}' butonuna tıklamak istiyorsun. Bu işlem geri alınamayabilir. Onaylıyor musun? (evet/hayır/iptal)"
            ctx.set_pending(original_text=text, intent=intent, slots=parsed.slots, policy_decision=reason)
            result = RouterResult(
                ok=False,
                intent=intent,
                user_text=confirm_msg,
                needs_confirmation=True,
                confirmation_prompt="Onaylıyor musun?",
                data={"reason": reason, "parsed": parsed.slots},
            )
            self._log(text, result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason})
            return result

        # ─────────────────────────────────────────────────────────────
        # Execute single action
        # ─────────────────────────────────────────────────────────────
        result = self._dispatch(intent=intent, slots=parsed.slots, ctx=ctx, in_queue=False)
        self._log(text, result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason}, executed={"intent": intent, "slots": parsed.slots})
        return result

    # ─────────────────────────────────────────────────────────────────
    # Queue runner
    # ─────────────────────────────────────────────────────────────────
    def _run_queue(self, ctx: ConversationContext, ctx_before: dict, original_text: str) -> RouterResult:
        """Execute steps in the queue until done, paused, or needing confirmation."""

        hook = get_overlay_hook()

        # Agent task status tracking
        if ctx.queue_source == "agent":
            rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
            if rec is not None:
                rec["state"] = "running"

        import time as _time
        from bantz.agent.recovery import get_step_timeout

        while ctx.queue_active() and not ctx.queue_paused:
            step = ctx.current_step()
            if step is None:
                break

            step_start_time = _time.time()
            step_pos = int(getattr(ctx, "queue_index", 0))
            step_timeout = get_step_timeout(str(step.intent))

            if ctx.queue_source == "agent":
                rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                if rec is not None:
                    try:
                        srec = (rec.get("steps") or [])[step_pos]
                        if isinstance(srec, dict):
                            srec["status"] = "running"
                            srec["attempts"] = int(srec.get("attempts", 0) or 0) + 1
                            srec["started_at"] = step_start_time
                            srec["timeout_seconds"] = step_timeout

                            # Capture a lightweight pre-signature for verification (Issue #3)
                            if "pre_sig" not in srec:
                                pre_sig = self._collect_agent_signature(
                                    ctx=ctx,
                                    original_text=original_text,
                                    ctx_before=ctx_before,
                                    include_scan=False,
                                )
                                if pre_sig is not None:
                                    srec["pre_sig"] = pre_sig
                    except Exception:
                        pass

            # Agent-only: preflight validation for click/type based on scan
            preflight: dict | None = None
            if ctx.queue_source == "agent" and str(step.intent) in {"browser_click", "browser_type"}:
                try:
                    preflight = self._agent_preflight_scan_validate(
                        ctx=ctx,
                        step=step,
                        step_pos=step_pos,
                        original_text=original_text,
                        ctx_before=ctx_before,
                    )
                except Exception:
                    preflight = None

                # Deterministic execution: if we resolved a click target to an index, rewrite slots.
                if str(step.intent) == "browser_click" and isinstance(preflight, dict):
                    resolved_index = preflight.get("resolved_index")
                    if resolved_index is not None and "index" not in (step.slots or {}):
                        try:
                            step.slots = {"index": int(resolved_index)}
                        except Exception:
                            pass

                # Deterministic execution: if we resolved a type target to an index, rewrite slots.
                if str(step.intent) == "browser_type" and isinstance(preflight, dict):
                    resolved_index = preflight.get("resolved_index")
                    if resolved_index is not None and "index" not in (step.slots or {}):
                        try:
                            # preserve text
                            step.slots = {"text": str(step.slots.get("text", "")), "index": int(resolved_index)}
                        except Exception:
                            pass

                if isinstance(preflight, dict) and preflight.get("pause"):
                    # Early pause with a clear message (Issue #3)
                    ctx.queue_paused = True
                    if ctx.queue_source == "agent":
                        rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                        if rec is not None:
                            rec["state"] = "paused"
                            try:
                                srec = (rec.get("steps") or [])[step_pos]
                                if isinstance(srec, dict):
                                    srec["status"] = "failed"
                                    srec["error"] = str(preflight.get("message") or "preflight_failed")
                            except Exception:
                                pass

                    return RouterResult(
                        ok=False,
                        intent=step.intent,
                        user_text=str(preflight.get("message") or "Bu adım için gerekli hedefi sayfada bulamadım. Kuyruk duraklatıldı."),
                    )

            # Agent-only: preview step before execution (Issue #3 integrates w/ overlay)
            if ctx.queue_source == "agent" and hook is not None:
                try:
                    import asyncio

                    preview_text = str(step.original_text or "").strip()
                    if preview_text:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(hook.preview_action(preview_text, duration_ms=1200))
                        else:
                            loop.run_until_complete(hook.preview_action(preview_text, duration_ms=1200))
                except Exception:
                    pass

            parsed = Parsed(intent=step.intent, slots=step.slots)
            click_target = None
            if str(step.intent) == "browser_click":
                # Prefer scan-derived click target if available.
                if isinstance(preflight, dict) and preflight.get("click_target"):
                    click_target = str(preflight.get("click_target"))
                else:
                    click_target = self._get_click_target_text(step.slots)
            decision, reason = self._policy.decide(text=step.original_text, intent=step.intent, confirmed=False, click_target=click_target)

            if decision == "deny":
                # Skip this step, continue
                if ctx.queue_source == "agent":
                    rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                    if rec is not None:
                        try:
                            srec = (rec.get("steps") or [])[step_pos]
                            if isinstance(srec, dict):
                                srec["status"] = "skipped"
                        except Exception:
                            pass
                ctx.advance_queue()
                continue

            if decision == "confirm":
                ctx.set_pending(original_text=step.original_text, intent=step.intent, slots=step.slots, policy_decision=reason)
                if ctx.queue_source == "agent":
                    rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                    if rec is not None:
                        rec["state"] = "waiting_confirmation"
                        try:
                            srec = (rec.get("steps") or [])[step_pos]
                            if isinstance(srec, dict):
                                srec["status"] = "waiting_confirmation"
                        except Exception:
                            pass
                result = RouterResult(
                    ok=False,
                    intent=step.intent,
                    user_text=f"Adım '{step.original_text}' riskli olabilir. Onaylıyor musun? (evet/hayır/iptal)",
                    needs_confirmation=True,
                    confirmation_prompt="Onaylıyor musun?",
                    data={"reason": reason, "step": step.original_text},
                )
                self._log(original_text, result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason})
                return result

            # Execute step
            exec_result = self._dispatch(intent=step.intent, slots=step.slots, ctx=ctx, in_queue=True)
            self._log(original_text, exec_result, parsed, ctx_before, ctx, policy={"decision": decision, "reason": reason}, executed={"intent": step.intent, "slots": step.slots})

            if not exec_result.ok:
                # Agent-only: attempt lightweight recovery before pausing (Issue #3)
                if ctx.queue_source == "agent":
                    recovered = self._attempt_agent_recovery(
                        ctx=ctx,
                        step=step,
                        step_pos=step_pos,
                        original_text=original_text,
                        ctx_before=ctx_before,
                        failed_result=exec_result,
                    )
                    if recovered is not None and recovered.ok:
                        exec_result = recovered
                        # fall through to normal success path (status + verification + advance)

                # If recovery succeeded, continue as a normal success.
                if exec_result.ok:
                    pass
                else:
                    # Step failed, pause queue with interactive recovery options
                    ctx.queue_paused = True
                    if ctx.queue_source == "agent":
                        rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                        if rec is not None:
                            rec["state"] = "paused"
                            try:
                                srec = (rec.get("steps") or [])[step_pos]
                                if isinstance(srec, dict):
                                    srec["status"] = "failed"
                                    srec["error"] = exec_result.user_text
                            except Exception:
                                pass

                    # Build interactive recovery message
                    recovery_options = [
                        "• 'devam et' veya 'tekrar dene' → bu adımı tekrar dener",
                        "• 'sıradaki' veya 'atla' → bu adımı atlayıp devam eder",
                        "• 'iptal et' → tüm kuyruğu iptal eder",
                        "• 'agent tekrar' → tüm task'ı baştan planlar",
                    ]
                    recovery_msg = (
                        f"❌ Adım başarısız: {exec_result.user_text}\n\n"
                        "Ne yapmak istersin?\n" + "\n".join(recovery_options)
                    )
                    return RouterResult(
                        ok=False,
                        intent=step.intent,
                        user_text=recovery_msg,
                        data={"failed_step": step.original_text, "recovery_options": ["devam et", "sıradaki", "iptal et", "agent tekrar"]},
                    )

            if ctx.queue_source == "agent":
                rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                if rec is not None:
                    try:
                        srec = (rec.get("steps") or [])[step_pos]
                        if isinstance(srec, dict):
                            srec["status"] = "completed"
                            # Record execution time
                            step_end_time = _time.time()
                            elapsed = step_end_time - step_start_time
                            srec["elapsed_seconds"] = round(elapsed, 2)
                            srec["completed_at"] = step_end_time
                    except Exception:
                        pass

            # Agent-only: best-effort verification after success (Issue #3)
            if ctx.queue_source == "agent":
                try:
                    self._verify_agent_step(
                        ctx=ctx,
                        step=step,
                        step_pos=step_pos,
                        original_text=original_text,
                        ctx_before=ctx_before,
                    )
                except Exception:
                    pass

                # Also verify browser_type filled the correct value (Issue #3 enhancement)
                if str(step.intent) == "browser_type":
                    try:
                        self._verify_type_result(
                            ctx=ctx,
                            step=step,
                            step_pos=step_pos,
                        )
                    except Exception:
                        pass

                # Verification may pause the queue for "strong" failures.
                if ctx.queue_paused:
                    rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                    if rec is not None:
                        rec["state"] = "paused"
                    return RouterResult(
                        ok=False,
                        intent=step.intent,
                        user_text=(
                            "Doğrulama başarısız görünüyor. Kuyruğu duraklattım. "
                            "İstersen 'devam et' diyerek sürdür veya 'sıradaki' ile atla."
                        ),
                    )

            ctx.advance_queue()

        # Queue finished or paused
        if ctx.queue_paused:
            if ctx.queue_source == "agent":
                rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
                if rec is not None:
                    rec["state"] = "paused"
            return RouterResult(ok=True, intent="queue_pause", user_text="Kuyruk duraklatıldı. 'devam et' diyebilirsin.")

        if ctx.queue_source == "agent":
            rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
            if rec is not None:
                rec["state"] = "completed"

        ctx.clear_queue()
        return RouterResult(ok=True, intent="unknown", user_text="Zincir tamamlandı. Başka ne yapayım?")

    def _attempt_agent_recovery(
        self,
        *,
        ctx: ConversationContext,
        step: QueueStep,
        step_pos: int,
        original_text: str,
        ctx_before: dict,
        failed_result: RouterResult,
    ) -> Optional[RouterResult]:
        """Try a small, safe recovery strategy for agent queue steps.

        Current strategy (site-agnostic):
        - For browser_click/browser_type failures: run browser_scan, then retry the same step once.

        Returns a RouterResult if a retry was attempted (success or failure), otherwise None.
        """

        intent = str(step.intent)
        if intent not in {"browser_click", "browser_type"}:
            return None

        rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
        srec: dict | None = None
        if rec is not None:
            try:
                candidate = (rec.get("steps") or [])[step_pos]
                if isinstance(candidate, dict):
                    srec = candidate
            except Exception:
                srec = None

        if srec is not None:
            srec["recovery_attempted"] = True
            srec["recovery_strategy"] = "scan_retry"
            # Keep the original error around for debugging.
            srec.setdefault("errors", [])
            if isinstance(srec.get("errors"), list):
                srec["errors"].append(str(failed_result.user_text))

        # 1) Policy-check and run a scan
        scan_decision, scan_reason = self._policy.decide(text="agent_recovery:scan", intent="browser_scan", confirmed=False)
        if scan_decision != "allow":
            if srec is not None:
                srec["recovery_blocked"] = True
                srec["recovery_block_reason"] = scan_reason
            return None

        scan_parsed = Parsed(intent="browser_scan", slots={})
        scan_result = self._dispatch(intent="browser_scan", slots={}, ctx=ctx, in_queue=True)
        self._log(
            original_text,
            scan_result,
            scan_parsed,
            ctx_before,
            ctx,
            policy={"decision": scan_decision, "reason": scan_reason},
            executed={"intent": "browser_scan", "slots": {}, "agent_recovery": True},
        )
        if not scan_result.ok:
            if srec is not None:
                srec["recovery_result"] = "scan_failed"
            return scan_result

        # 2) Retry the failed step once
        if srec is not None:
            srec["attempts"] = int(srec.get("attempts", 1) or 1) + 1

        retry_parsed = Parsed(intent=step.intent, slots=step.slots)
        retry_result = self._dispatch(intent=step.intent, slots=step.slots, ctx=ctx, in_queue=True)
        self._log(
            original_text,
            retry_result,
            retry_parsed,
            ctx_before,
            ctx,
            policy={"decision": "allow", "reason": "agent_recovery_retry"},
            executed={"intent": step.intent, "slots": step.slots, "agent_recovery": True},
        )

        if srec is not None:
            srec["recovered"] = bool(retry_result.ok)
            srec["recovery_result"] = "recovered" if retry_result.ok else "retry_failed"
            if not retry_result.ok and isinstance(srec.get("errors"), list):
                srec["errors"].append(str(retry_result.user_text))

        return retry_result

    def _verify_agent_step(
        self,
        *,
        ctx: ConversationContext,
        step: QueueStep,
        step_pos: int,
        original_text: str,
        ctx_before: dict,
    ) -> None:
        """Best-effort verification for agent steps.

        This is intentionally non-blocking: verification failure does not pause the queue.
        It exists to support the Issue #3 "verification loop" with minimal risk.

        Current strategy:
        - For key browser navigation/interaction intents, call browser_info and record the result.
        - If a navigation intent produces no visible page change (based on title/url), pause the queue.
        """

        intent = str(step.intent)
        if intent not in {"browser_open", "browser_click", "browser_type", "browser_back", "browser_search"}:
            return

        rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
        if rec is None:
            return

        try:
            candidate = (rec.get("steps") or [])[step_pos]
        except Exception:
            return

        if not isinstance(candidate, dict):
            return

        srec: dict = candidate
        srec["verification_attempted"] = True
        srec["verification_strategy"] = "browser_info_signature"

        decision, reason = self._policy.decide(text="agent_verify:browser_info", intent="browser_info", confirmed=False)
        if decision != "allow":
            srec["verification_ok"] = False
            srec["verification_blocked"] = True
            srec["verification_block_reason"] = reason
            return

        post_sig = self._collect_agent_signature(
            ctx=ctx,
            original_text=original_text,
            ctx_before=ctx_before,
            include_scan=False,
        )
        if post_sig is not None:
            srec["post_sig"] = post_sig

        # If we can't collect a signature, keep it non-blocking.
        if not post_sig or not bool(post_sig.get("ok")):
            srec["verification_ok"] = False
            srec["verification_reason"] = "no_signature"
            srec["verification_summary"] = str((post_sig or {}).get("summary") or "")[:300]
            return

        pre_sig = srec.get("pre_sig") if isinstance(srec.get("pre_sig"), dict) else None
        srec["verification_ok"] = True
        srec["verification_summary"] = str(post_sig.get("summary") or "")[:300]

        if pre_sig and bool(pre_sig.get("ok")):
            changed = self._signature_changed(pre_sig, post_sig)
            srec["signature_changed"] = bool(changed)
            if not changed:
                # For clicks/types: no visible page change is common.
                # Treat as a warning, not a hard failure.
                if intent in {"browser_click", "browser_type"}:
                    srec["verification_ok"] = True
                    srec["verification_warn"] = True
                    srec["verification_reason"] = "no_change_detected"
                    return

                srec["verification_ok"] = False
                srec["verification_reason"] = "no_change_detected"

                # Strong failure: navigation intents should generally change the page.
                if intent in {"browser_open", "browser_back", "browser_search"}:
                    # One small delay before concluding
                    wait_result = self._dispatch(intent="browser_wait", slots={"seconds": 2}, ctx=ctx, in_queue=True)
                    self._log(
                        original_text,
                        wait_result,
                        Parsed(intent="browser_wait", slots={"seconds": 2}),
                        ctx_before,
                        ctx,
                        policy={"decision": "allow", "reason": "agent_verify_wait"},
                        executed={"intent": "browser_wait", "slots": {"seconds": 2}, "agent_verification": True},
                    )
                    post2 = self._collect_agent_signature(
                        ctx=ctx,
                        original_text=original_text,
                        ctx_before=ctx_before,
                        include_scan=False,
                    )
                    if post2 and bool(post2.get("ok")):
                        srec["post_sig2"] = post2
                        if self._signature_changed(pre_sig, post2):
                            srec["verification_ok"] = True
                            srec["verification_reason"] = "changed_after_wait"
                            srec["signature_changed"] = True
                            srec["verification_summary"] = str(post2.get("summary") or "")[:300]
                            return

                    # Still no change: pause for attention.
                    ctx.queue_paused = True
                    return

    def _verify_type_result(
        self,
        *,
        ctx: ConversationContext,
        step: QueueStep,
        step_pos: int,
    ) -> None:
        """Verify that browser_type actually filled the expected text.

        This is a lightweight, non-blocking check:
        - Get the current value of the targeted input field.
        - Compare to the expected text.
        - Record as a warning if mismatch (do not pause queue).
        """
        rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
        if rec is None:
            return

        try:
            srec = (rec.get("steps") or [])[step_pos]
        except Exception:
            return

        if not isinstance(srec, dict):
            return

        expected_text = str(step.slots.get("text", "")).strip()
        if not expected_text:
            return

        # Try to get the resolved index if we have it
        resolved_idx = srec.get("resolved_index")
        if resolved_idx is None:
            resolved_idx = step.slots.get("index")

        if resolved_idx is None:
            # No specific target to verify
            srec["type_verification_attempted"] = True
            srec["type_verification_ok"] = None
            srec["type_verification_reason"] = "no_target_index"
            return

        # Run a scan to get current element state
        scan_decision, _ = self._policy.decide(text="agent_verify_type:scan", intent="browser_scan", confirmed=False)
        if scan_decision != "allow":
            srec["type_verification_attempted"] = True
            srec["type_verification_ok"] = None
            srec["type_verification_reason"] = "scan_blocked"
            return

        scan_result = self._dispatch(intent="browser_scan", slots={}, ctx=ctx, in_queue=True)
        elements = self._extract_scan_elements(scan_result)
        
        srec["type_verification_attempted"] = True

        if not elements:
            srec["type_verification_ok"] = None
            srec["type_verification_reason"] = "no_elements"
            return

        # Find the element by index
        target = self._find_scan_element_by_index(elements, int(resolved_idx))
        if target is None:
            srec["type_verification_ok"] = False
            srec["type_verification_reason"] = "target_not_found"
            return

        # Check if element has the expected text/value
        actual_value = str(target.get("value") or target.get("text") or "").strip()
        
        # Normalize for comparison (case-insensitive, whitespace tolerant)
        expected_norm = expected_text.lower().strip()
        actual_norm = actual_value.lower().strip()

        if expected_norm in actual_norm or actual_norm.endswith(expected_norm):
            srec["type_verification_ok"] = True
            srec["type_verification_reason"] = "text_found"
            srec["type_actual_value"] = actual_value[:100]
        else:
            # Mismatch - record as warning but don't pause
            srec["type_verification_ok"] = False
            srec["type_verification_warn"] = True
            srec["type_verification_reason"] = "text_mismatch"
            srec["type_expected"] = expected_text[:100]
            srec["type_actual_value"] = actual_value[:100]

    def _collect_agent_signature(
        self,
        *,
        ctx: ConversationContext,
        original_text: str,
        ctx_before: dict,
        include_scan: bool,
    ) -> Optional[dict]:
        """Collect a lightweight browser signature for verification.

        Returns a dict like:
        {"ok": bool, "title": str|None, "url": str|None, "summary": str}

        Uses browser_info output format from bantz.browser.skills.browser_current_info.
        """

        decision, reason = self._policy.decide(text="agent_sig:browser_info", intent="browser_info", confirmed=False)
        if decision != "allow":
            return {"ok": False, "summary": f"blocked:{reason}"}

        parsed = Parsed(intent="browser_info", slots={})
        info_result = self._dispatch(intent="browser_info", slots={}, ctx=ctx, in_queue=True)
        self._log(
            original_text,
            info_result,
            parsed,
            ctx_before,
            ctx,
            policy={"decision": decision, "reason": reason},
            executed={"intent": "browser_info", "slots": {}, "agent_signature": True},
        )

        title, url = self._parse_browser_info_text(str(info_result.user_text))

        sig: dict = {
            "ok": bool(info_result.ok),
            "title": title,
            "url": url,
            "summary": str(info_result.user_text),
        }

        if include_scan:
            scan_decision, scan_reason = self._policy.decide(text="agent_sig:browser_scan", intent="browser_scan", confirmed=False)
            if scan_decision == "allow":
                scan_result = self._dispatch(intent="browser_scan", slots={}, ctx=ctx, in_queue=True)
                self._log(
                    original_text,
                    scan_result,
                    Parsed(intent="browser_scan", slots={}),
                    ctx_before,
                    ctx,
                    policy={"decision": scan_decision, "reason": scan_reason},
                    executed={"intent": "browser_scan", "slots": {}, "agent_signature": True},
                )
                sig["scan_ok"] = bool(scan_result.ok)
                if isinstance(scan_result.data, dict) and isinstance(scan_result.data.get("scan"), dict):
                    elements = scan_result.data.get("scan", {}).get("elements")
                    if isinstance(elements, list):
                        sig["elements"] = len(elements)

        return sig

    def _agent_preflight_scan_validate(
        self,
        *,
        ctx: ConversationContext,
        step: QueueStep,
        step_pos: int,
        original_text: str,
        ctx_before: dict,
    ) -> dict:
        """Agent-only: scan the page and validate step target exists.

        For browser_click:
        - If index is provided: ensure an element with that index exists.
        - If text is provided: ensure at least one element contains that text.

        For browser_type:
        - If index is provided: ensure an element with that index exists.
        - If no index: can't validate reliably (still records scan summary).

        Returns a dict with optional:
        - pause: bool
        - message: str
        - click_target: str (for policy risky-click checks)
        - elements_count: int
        """

        rec = self._agent_rec(getattr(ctx, "current_agent_task_id", None))
        srec: dict | None = None
        if rec is not None:
            try:
                candidate = (rec.get("steps") or [])[step_pos]
                if isinstance(candidate, dict):
                    srec = candidate
            except Exception:
                srec = None

        result: dict = {"pause": False}

        # Scan
        scan_decision, scan_reason = self._policy.decide(text="agent_preflight:scan", intent="browser_scan", confirmed=False)
        if scan_decision != "allow":
            if srec is not None:
                srec["preflight_attempted"] = True
                srec["preflight_ok"] = False
                srec["preflight_reason"] = f"blocked:{scan_reason}"
            return result

        scan_rr = self._dispatch(intent="browser_scan", slots={}, ctx=ctx, in_queue=True)
        self._log(
            original_text,
            scan_rr,
            Parsed(intent="browser_scan", slots={}),
            ctx_before,
            ctx,
            policy={"decision": scan_decision, "reason": scan_reason},
            executed={"intent": "browser_scan", "slots": {}, "agent_preflight": True},
        )

        elements = self._extract_scan_elements(scan_rr)
        if srec is not None:
            srec["preflight_attempted"] = True
            srec["preflight_ok"] = bool(scan_rr.ok)
            srec["preflight_elements"] = len(elements)

        result["elements_count"] = len(elements)

        # If scan failed or no elements, do not block; execution may still succeed.
        if not scan_rr.ok or not elements:
            return result

        intent = str(step.intent)
        slots = dict(step.slots or {})

        # Validate by index
        if "index" in slots and slots.get("index") is not None:
            try:
                idx = int(slots.get("index"))
            except Exception:
                idx = None

            if idx is None:
                result["pause"] = True
                result["message"] = "Index değerini anlayamadım. Kuyruğu duraklattım. 'tarayıcıyı tara' deyip doğru index ile tekrar deneyebiliriz."
                return result

            found = self._find_scan_element_by_index(elements, idx)
            if found is None:
                result["pause"] = True
                result["message"] = (
                    f"Sayfada [{idx}] index'li bir öğe bulamadım (toplam {len(elements)} öğe). Kuyruğu duraklattım. "
                    "İstersen 'tarayıcıyı tara' deyip yeni listeye göre tekrar deneriz."
                )
                return result

            # For click, provide click_target text to policy
            try:
                ridx = int(found.get("index"))
            except Exception:
                ridx = None

            if ridx is not None:
                result["resolved_index"] = ridx

            t = str((found.get("text") or "")).strip()
            if intent == "browser_click":
                if t:
                    result["click_target"] = t
                if srec is not None:
                    if ridx is not None:
                        srec["resolved_index"] = ridx
                    if t:
                        srec["resolved_text"] = t
                    srec["resolved_click_hint"] = {
                        "tag": found.get("tag"),
                        "role": found.get("role"),
                        "href": found.get("href"),
                        "text": t[:80],
                    }

            if intent == "browser_type":
                if srec is not None:
                    if ridx is not None:
                        srec["resolved_index"] = ridx
                    srec["resolved_type_target"] = True
                    srec["resolved_type_hint"] = {
                        "tag": found.get("tag"),
                        "role": found.get("role"),
                        "inputType": found.get("inputType"),
                        "text": t[:80] if t else "",
                    }
            return result

        # Validate by text (click only)
        if intent == "browser_click" and "text" in slots and slots.get("text"):
            needle = str(slots.get("text") or "").strip()
            found = self._select_best_scan_text_match(elements, needle)
            if found is None:
                result["pause"] = True
                result["message"] = (
                    f"Sayfada '{needle}' metnine uyan bir öğe bulamadım. Kuyruğu duraklattım. "
                    "İstersen önce 'tarayıcıyı tara' deyip listeden index seçelim."
                )
                return result
            t = str((found.get("text") or "")).strip()
            if t:
                result["click_target"] = t

            # Also return resolved index so we can execute deterministically.
            try:
                ridx = int(found.get("index"))
                result["resolved_index"] = ridx
            except Exception:
                ridx = None
            if srec is not None:
                srec["resolved_text"] = t
                if ridx is not None:
                    srec["resolved_index"] = ridx
            return result

        # Resolve best target for typing when no index is specified.
        if intent == "browser_type" and ("index" not in slots or slots.get("index") is None):
            found = self._select_best_type_target(elements)
            if found is None:
                # Can't reliably resolve; proceed without blocking.
                if srec is not None:
                    srec["resolved_type_target"] = False
                return result

            try:
                ridx = int(found.get("index"))
            except Exception:
                ridx = None

            if ridx is not None:
                result["resolved_index"] = ridx
                if srec is not None:
                    srec["resolved_index"] = ridx
                    srec["resolved_type_target"] = True
                    srec["resolved_type_hint"] = {
                        "tag": found.get("tag"),
                        "role": found.get("role"),
                        "inputType": found.get("inputType"),
                        "text": str(found.get("text") or "")[:80],
                    }
            return result

        # No specific target to validate
        return result

    def _extract_scan_elements(self, scan_result: RouterResult) -> list[dict]:
        """Extract scan elements from RouterResult produced by browser_scan."""
        if not isinstance(scan_result.data, dict):
            return []
        scan = scan_result.data.get("scan")
        if not isinstance(scan, dict):
            return []
        elements = scan.get("elements")
        if not isinstance(elements, list):
            return []
        out: list[dict] = []
        for e in elements:
            if isinstance(e, dict):
                out.append(e)
        return out

    def _find_scan_element_by_index(self, elements: list[dict], index: int) -> Optional[dict]:
        for e in elements:
            try:
                if int(e.get("index")) == int(index):
                    return e
            except Exception:
                continue
        return None

    def _find_scan_element_by_text(self, elements: list[dict], needle: str) -> Optional[dict]:
        n = str(needle or "").strip().casefold()
        if not n:
            return None
        for e in elements:
            t = str(e.get("text") or "").strip().casefold()
            if not t:
                continue
            if n in t:
                return e
        return None

    def _select_best_scan_text_match(self, elements: list[dict], needle: str) -> Optional[dict]:
        """Pick the best scan element for a click-by-text request.

        Strategy:
        1) Exact case-insensitive match
        2) Startswith match
        3) Contains match

        Ties are resolved by shorter element text.
        """

        n = str(needle or "").strip().casefold()
        if not n:
            return None

        best: dict | None = None
        best_score: int | None = None
        best_len: int | None = None

        for e in elements:
            t_raw = str(e.get("text") or "").strip()
            t = t_raw.casefold()
            if not t:
                continue

            score: int | None
            if t == n:
                score = 0
            elif t.startswith(n):
                score = 1
            elif n in t:
                score = 2
            else:
                score = None

            if score is None:
                continue

            tlen = len(t_raw)
            if best is None:
                best = e
                best_score = score
                best_len = tlen
                continue

            if best_score is None or score < best_score:
                best = e
                best_score = score
                best_len = tlen
                continue

            if score == best_score and best_len is not None and tlen < best_len:
                best = e
                best_len = tlen

        return best

    def _select_best_type_target(self, elements: list[dict]) -> Optional[dict]:
        """Pick a good typing target (input/textarea/textbox) from scan elements."""

        best: dict | None = None
        best_score: int | None = None

        def score(e: dict) -> int | None:
            tag = str(e.get("tag") or "").strip().casefold()
            role = str(e.get("role") or "").strip().casefold()
            itype = str(e.get("inputType") or "").strip().casefold()
            txt = str(e.get("text") or "").strip().casefold()

            # Strong signals
            if role in {"searchbox"} or itype == "search":
                return 0

            # Common typing targets
            if tag in {"input", "textarea"} or role in {"textbox"}:
                # Prefer text-ish inputs
                if itype in {"text", "email", "tel", "url", "password", ""}:
                    # Heuristic boost: labels mentioning search
                    if any(k in txt for k in ("search", "ara", "bul")):
                        return 1
                    return 2
                return 3

            # Fallback: clickable divs with search label aren't safe typing targets
            return None

        for e in elements:
            if not isinstance(e, dict):
                continue
            s = score(e)
            if s is None:
                continue
            if best is None or best_score is None or s < best_score:
                best = e
                best_score = s
                continue

            if s == best_score:
                # tie-break: smaller index
                try:
                    bi = int(best.get("index"))
                    ei = int(e.get("index"))
                    if ei < bi:
                        best = e
                except Exception:
                    pass

        return best

    def _parse_browser_info_text(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Parse browser_info output into (title, url)."""
        if not text:
            return None, None

        title = None
        url = None
        for raw in str(text).splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.lower().startswith("sayfa:"):
                title = line.split(":", 1)[1].strip() if ":" in line else None
            if line.lower().startswith("url:"):
                url = line.split(":", 1)[1].strip() if ":" in line else None
        return title, url

    def _signature_changed(self, before: dict, after: dict) -> bool:
        """Heuristic: did the page signature change?"""
        b_title = str(before.get("title") or "").strip()
        a_title = str(after.get("title") or "").strip()
        b_url = str(before.get("url") or "").strip()
        a_url = str(after.get("url") or "").strip()

        if b_url and a_url and b_url != a_url:
            return True
        if b_title and a_title and b_title != a_title:
            return True
        b_el = before.get("elements")
        a_el = after.get("elements")
        if isinstance(b_el, int) and isinstance(a_el, int) and b_el != a_el:
            return True
        return False

    # ─────────────────────────────────────────────────────────────────
    # Dispatch single action
    # ─────────────────────────────────────────────────────────────────
    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:
        follow_up = "" if in_queue else " Başka ne yapayım?"
        search_follow = "" if in_queue else " Ne arayayım?"

        # ─────────────────────────────────────────────────────────────
        # AI Chat commands (duck.ai, chatgpt, claude, etc.)
        # ─────────────────────────────────────────────────────────────
        if intent == "ai_chat":
            from bantz.browser.skills import browser_ai_chat
            service = str(slots.get("service", "duck")).lower()
            prompt = str(slots.get("prompt", "")).strip()
            ok, msg = browser_ai_chat(service, prompt)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        # ─────────────────────────────────────────────────────────────
        # Browser Agent commands (Firefox primary)
        # ─────────────────────────────────────────────────────────────
        if intent == "browser_open":
            from bantz.browser.skills import browser_open
            url = str(slots.get("url", "")).strip()
            ok, msg = browser_open(url)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_scan":
            from bantz.browser.skills import browser_scan
            ok, msg, scan = browser_scan()
            ctx.last_intent = intent
            data = {"scan": scan} if scan else None
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up, data=data)

        if intent == "browser_click":
            from bantz.browser.skills import browser_click_index, browser_click_text
            if "index" in slots:
                idx = int(slots["index"])
                ok, msg = browser_click_index(idx)
            elif "text" in slots:
                txt = str(slots["text"])
                ok, msg = browser_click_text(txt)
            else:
                ok, msg = False, "Neye tıklayacağımı anlamadım."
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_type":
            from bantz.browser.skills import browser_type_text
            text_to_type = str(slots.get("text", "")).strip()
            idx = slots.get("index")
            if idx is not None:
                ok, msg = browser_type_text(text_to_type, int(idx))
            else:
                ok, msg = browser_type_text(text_to_type)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_scroll_down":
            from bantz.browser.skills import browser_scroll_down
            ok, msg = browser_scroll_down()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_scroll_up":
            from bantz.browser.skills import browser_scroll_up
            ok, msg = browser_scroll_up()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_back":
            from bantz.browser.skills import browser_go_back
            ok, msg = browser_go_back()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_info":
            from bantz.browser.skills import browser_current_info
            ok, msg = browser_current_info()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_detail":
            from bantz.browser.skills import browser_detail
            idx = int(slots.get("index", 0))
            ok, msg = browser_detail(idx)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_wait":
            from bantz.browser.skills import browser_wait
            seconds = int(slots.get("seconds", 3))
            ok, msg = browser_wait(seconds)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "browser_search":
            # Context-aware search - uses current site or defaults to YouTube
            from bantz.browser.skills import browser_search_in_page
            query = str(slots.get("query", "")).strip()
            if not query:
                return RouterResult(ok=False, intent=intent, user_text="Ne arayayım?")
            ok, msg = browser_search_in_page(query)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        # ─────────────────────────────────────────────────────────────
        # News Briefing commands (Jarvis-style)
        # ─────────────────────────────────────────────────────────────
        if intent == "news_briefing":
            from bantz.skills.news import NewsBriefing, extract_news_query
            from bantz.llm.persona import JarvisPersona
            from bantz.browser.extension_bridge import get_bridge
            
            persona = JarvisPersona()
            query = str(slots.get("query", "gündem")).strip()
            
            # If query not explicitly set, try to extract from raw text
            if query == "gündem" and "slots" in dir(slots) and slots.get("_raw_text"):
                query = extract_news_query(slots.get("_raw_text", ""))
            
            # Get bridge for browser interaction
            bridge = get_bridge()
            news = NewsBriefing(extension_bridge=bridge)
            
            # Store news instance in context for follow-up commands
            ctx.set_news_briefing(news)
            
            # Return thinking response - actual search happens async
            searching_msg = persona.for_news_search(query if query != "gündem" else "")
            ctx.last_intent = intent
            ctx.set_pending_news_search(query)
            
            return RouterResult(
                ok=True, 
                intent=intent, 
                user_text=searching_msg,
                data={"query": query, "state": "searching"}
            )

        if intent == "news_open_result":
            from bantz.llm.persona import JarvisPersona
            
            persona = JarvisPersona()
            index = int(slots.get("index", 1))
            
            # Get news instance from context
            news = ctx.get_news_briefing()
            if not news or not news.has_results:
                return RouterResult(
                    ok=False, 
                    intent=intent, 
                    user_text="Önce haber araması yapmalısın efendim. 'Bugünkü haberler' diyebilirsin."
                )
            
            # Open the result
            import asyncio
            loop = asyncio.get_event_loop()
            success = loop.run_until_complete(news.open_result(index))
            
            if success:
                msg = persona.for_opening_item(index)
                ctx.last_intent = intent
                return RouterResult(ok=True, intent=intent, user_text=msg + follow_up)
            else:
                return RouterResult(
                    ok=False, 
                    intent=intent, 
                    user_text=f"Geçersiz numara efendim. 1 ile {news.result_count} arasında bir numara söyleyin."
                )

        if intent == "news_open_current":
            from bantz.llm.persona import JarvisPersona
            
            persona = JarvisPersona()
            
            news = ctx.get_news_briefing()
            if not news or not news.has_results:
                return RouterResult(
                    ok=False, 
                    intent=intent, 
                    user_text="Önce haber araması yapmalısın efendim."
                )
            
            import asyncio
            loop = asyncio.get_event_loop()
            success = loop.run_until_complete(news.open_current())
            
            if success:
                msg = persona.get_response("opening")
                ctx.last_intent = intent
                return RouterResult(ok=True, intent=intent, user_text=msg + follow_up)
            else:
                return RouterResult(ok=False, intent=intent, user_text="Açılacak haber bulunamadı efendim.")

        if intent == "news_more":
            from bantz.llm.persona import JarvisPersona
            
            persona = JarvisPersona()
            
            news = ctx.get_news_briefing()
            if not news or not news.has_results:
                return RouterResult(
                    ok=False, 
                    intent=intent, 
                    user_text="Önce haber araması yapmalısın efendim."
                )
            
            # Format more results for TTS
            more_text = news.format_more_for_tts(start=4, count=3)
            ctx.last_intent = intent
            
            return RouterResult(
                ok=True, 
                intent=intent, 
                user_text=more_text,
                data=news.format_for_overlay()
            )

        # ─────────────────────────────────────────────────────────────
        # Page Summarization commands (Jarvis-style)
        # ─────────────────────────────────────────────────────────────
        if intent == "page_summarize":
            from bantz.skills.summarizer import PageSummarizer
            from bantz.llm.persona import JarvisPersona
            from bantz.llm.ollama_client import OllamaClient
            from bantz.browser.extension_bridge import get_bridge
            
            persona = JarvisPersona()
            
            # Get bridge for page extraction
            bridge = get_bridge()
            if not bridge or not bridge.has_client():
                return RouterResult(
                    ok=False,
                    intent=intent,
                    user_text="Tarayıcı bağlantısı yok efendim. Firefox eklentisi aktif mi?"
                )
            
            # Create LLM client and summarizer
            try:
                llm = OllamaClient()
                summarizer = PageSummarizer(extension_bridge=bridge, llm_client=llm)
                
                # Store in context for follow-up commands
                ctx.set_page_summarizer(summarizer)
                
                # Return thinking response - actual summarization will happen
                thinking_msg = persona.get_response("thinking")
                ctx.last_intent = intent
                ctx.set_pending_page_summarize(detail_level="short")
                
                return RouterResult(
                    ok=True,
                    intent=intent,
                    user_text=thinking_msg,
                    data={"state": "extracting", "detail_level": "short"}
                )
            except Exception as e:
                logger.error(f"[Router] Page summarize error: {e}")
                return RouterResult(
                    ok=False,
                    intent=intent,
                    user_text=persona.get_response("error")
                )

        if intent == "page_summarize_detailed":
            from bantz.skills.summarizer import PageSummarizer
            from bantz.llm.persona import JarvisPersona
            from bantz.llm.ollama_client import OllamaClient
            from bantz.browser.extension_bridge import get_bridge
            
            persona = JarvisPersona()
            
            # Check if we have existing summary - can just expand
            summarizer = ctx.get_page_summarizer()
            if summarizer and summarizer.has_summary:
                # Already have content, just need detailed summary
                summary = summarizer.last_summary
                if summary and summary.detailed_summary:
                    # Already have detailed summary
                    overlay_data = summarizer.format_for_overlay(summary, detailed=True)
                    ctx.last_intent = intent
                    return RouterResult(
                        ok=True,
                        intent=intent,
                        user_text=persona.get_response("results_found"),
                        data=overlay_data
                    )
            
            # Need to extract and generate detailed summary
            bridge = get_bridge()
            if not bridge or not bridge.has_client():
                return RouterResult(
                    ok=False,
                    intent=intent,
                    user_text="Tarayıcı bağlantısı yok efendim."
                )
            
            try:
                llm = OllamaClient()
                summarizer = PageSummarizer(extension_bridge=bridge, llm_client=llm)
                ctx.set_page_summarizer(summarizer)
                
                thinking_msg = persona.get_response("thinking")
                ctx.last_intent = intent
                ctx.set_pending_page_summarize(detail_level="detailed")
                
                return RouterResult(
                    ok=True,
                    intent=intent,
                    user_text=thinking_msg,
                    data={"state": "extracting", "detail_level": "detailed"}
                )
            except Exception as e:
                logger.error(f"[Router] Page summarize detailed error: {e}")
                return RouterResult(
                    ok=False,
                    intent=intent,
                    user_text=persona.get_response("error")
                )

        if intent == "page_question":
            from bantz.skills.summarizer import PageSummarizer
            from bantz.llm.persona import JarvisPersona
            from bantz.llm.ollama_client import OllamaClient
            from bantz.browser.extension_bridge import get_bridge
            
            persona = JarvisPersona()
            question = str(slots.get("question", "")).strip()
            
            if not question:
                return RouterResult(
                    ok=False,
                    intent=intent,
                    user_text="Ne sormak istiyorsun efendim?"
                )
            
            # Check if we have existing summarizer with content
            summarizer = ctx.get_page_summarizer()
            
            if not summarizer or not summarizer.has_content:
                # Need to extract first
                bridge = get_bridge()
                if not bridge or not bridge.has_client():
                    return RouterResult(
                        ok=False,
                        intent=intent,
                        user_text="Tarayıcı bağlantısı yok efendim."
                    )
                
                try:
                    llm = OllamaClient()
                    summarizer = PageSummarizer(extension_bridge=bridge, llm_client=llm)
                    ctx.set_page_summarizer(summarizer)
                except Exception as e:
                    logger.error(f"[Router] Page question setup error: {e}")
                    return RouterResult(
                        ok=False,
                        intent=intent,
                        user_text=persona.get_response("error")
                    )
            
            thinking_msg = persona.get_response("thinking")
            ctx.last_intent = intent
            ctx.set_pending_page_question(question)
            
            return RouterResult(
                ok=True,
                intent=intent,
                user_text=thinking_msg,
                data={"state": "answering", "question": question}
            )

        # ─────────────────────────────────────────────────────────────
        # Original daily skills
        # ─────────────────────────────────────────────────────────────
        if intent == "open_browser":
            ok, msg = open_browser()
            ctx.last_intent = intent
            if not in_queue:
                ctx.awaiting = "search_query"
            return RouterResult(ok=ok, intent=intent, user_text=msg + search_follow)

        if intent == "google_search":
            query = str(slots.get("query", "")).strip()
            if not query:
                if not in_queue:
                    ctx.awaiting = "search_query"
                return RouterResult(ok=False, intent=intent, user_text="Ne arayayım?")
            ok, msg = google_search(query=query)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "open_path":
            target = str(slots.get("target", "")).strip()
            ok, msg = open_path(target)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "open_url":
            url = str(slots.get("url", "")).strip()
            ok, msg = open_url(url)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "notify":
            message = str(slots.get("message", "")).strip()
            ok, msg = notify(message)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "open_btop":
            ok, msg = open_btop()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        # ─────────────────────────────────────────────────────────────
        # Reminder / Scheduler commands
        # ─────────────────────────────────────────────────────────────
        if intent == "reminder_add":
            from bantz.scheduler.reminder import get_reminder_manager
            manager = get_reminder_manager()
            time_str = str(slots.get("time", "")).strip()
            message = str(slots.get("message", "")).strip()
            result_data = manager.add_reminder(time_str, message)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "reminder_list":
            from bantz.scheduler.reminder import get_reminder_manager
            manager = get_reminder_manager()
            result_data = manager.list_reminders()
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "reminder_delete":
            from bantz.scheduler.reminder import get_reminder_manager
            manager = get_reminder_manager()
            reminder_id = int(slots.get("id", 0))
            result_data = manager.delete_reminder(reminder_id)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "reminder_snooze":
            from bantz.scheduler.reminder import get_reminder_manager
            manager = get_reminder_manager()
            reminder_id = int(slots.get("id", 0))
            minutes = int(slots.get("minutes", 10))
            result_data = manager.snooze_reminder(reminder_id, minutes)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        # ─────────────────────────────────────────────────────────────
        # Check-in commands (proactive conversations)
        # ─────────────────────────────────────────────────────────────
        if intent == "checkin_add":
            from bantz.scheduler.checkin import get_checkin_manager
            manager = get_checkin_manager()
            schedule_str = str(slots.get("schedule", "")).strip()
            prompt = str(slots.get("prompt", "")).strip()
            result_data = manager.add_checkin(schedule_str, prompt)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "checkin_list":
            from bantz.scheduler.checkin import get_checkin_manager
            manager = get_checkin_manager()
            result_data = manager.list_checkins()
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "checkin_delete":
            from bantz.scheduler.checkin import get_checkin_manager
            manager = get_checkin_manager()
            checkin_id = int(slots.get("id", 0))
            result_data = manager.delete_checkin(checkin_id)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "checkin_pause":
            from bantz.scheduler.checkin import get_checkin_manager
            manager = get_checkin_manager()
            checkin_id = int(slots.get("id", 0))
            result_data = manager.pause_checkin(checkin_id)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        if intent == "checkin_resume":
            from bantz.scheduler.checkin import get_checkin_manager
            manager = get_checkin_manager()
            checkin_id = int(slots.get("id", 0))
            result_data = manager.resume_checkin(checkin_id)
            ctx.last_intent = intent
            return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + follow_up)

        # ─────────────────────────────────────────────────────────────
        # PC / App Control commands (session-aware)
        # ─────────────────────────────────────────────────────────────
        if intent == "app_open":
            app_name = str(slots.get("app", "")).strip().lower()
            ok, msg, window_id = open_app(app_name)
            if ok:
                ctx.set_active_app(app_name, window_id)
                session_hint = f" 🎯 {app_name} oturumu başladı. Komut verebilirsin ('yaz:', 'gönder', 'kapat') veya 'uygulamadan çık' de."
                return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "app_close":
            app_name = str(slots.get("app", "")).strip().lower() if slots.get("app") else None
            # If no app specified and we have active session, close that
            if not app_name and ctx.has_active_app():
                app_name = ctx.active_app
            if not app_name:
                return RouterResult(ok=False, intent=intent, user_text="Hangi uygulamayı kapatayım?" + follow_up)
            ok, msg = close_app(app_name)
            if ok and ctx.active_app == app_name:
                ctx.clear_active_app()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "app_focus":
            app_name = str(slots.get("app", "")).strip().lower()
            ok, msg, window_id = focus_app(app_name)
            if ok:
                ctx.set_active_app(app_name, window_id)
                session_hint = f" 🎯 {app_name} oturumuna geçtim."
                return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "app_list":
            ok, msg, windows = list_windows()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up, data={"windows": windows})

        if intent == "app_type":
            text_to_type = str(slots.get("text", "")).strip()
            if not text_to_type:
                return RouterResult(ok=False, intent=intent, user_text="Ne yazayım?" + follow_up)

            hook = get_overlay_hook()
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    getattr(hook, "preview_action_sync")(f"Yazıyorum: {text_to_type[:60]}", 1200)
                except Exception:
                    pass

            # Use active window if we have a session
            target_window = ctx.active_window_id if ctx.has_active_app() else None
            ok, msg = type_text(text_to_type, window_id=target_window)
            ctx.last_intent = intent
            session_hint = f" ({ctx.active_app} oturumunda)" if ctx.has_active_app() else ""
            return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint + follow_up)

        if intent == "app_submit":
            # Send Enter key to submit
            target_window = ctx.active_window_id if ctx.has_active_app() else None

            hook = get_overlay_hook()
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    getattr(hook, "preview_action_sync")("Enter gönderiyorum…", 800)
                except Exception:
                    pass

            ok, msg = send_key("Return", window_id=target_window)
            ctx.last_intent = intent
            session_hint = f" ({ctx.active_app} oturumunda)" if ctx.has_active_app() else ""
            return RouterResult(ok=ok, intent=intent, user_text="Gönderildi." + session_hint + follow_up)

        # ─────────────────────────────────────────────────────────────
        # Advanced desktop input (Issue #2)
        # ─────────────────────────────────────────────────────────────
        if intent == "pc_mouse_move":
            x = int(slots.get("x", 0))
            y = int(slots.get("y", 0))
            duration_ms = int(slots.get("duration_ms", 0) or 0)

            hook = get_overlay_hook()
            if hook and hasattr(hook, "cursor_dot_sync"):
                try:
                    getattr(hook, "cursor_dot_sync")(x, y, 700)
                except Exception:
                    pass
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    getattr(hook, "preview_action_sync")(f"İmleci ({x}, {y}) konumuna götürüyorum…", 900)
                except Exception:
                    pass

            ok, msg = move_mouse(x, y, duration_ms=duration_ms)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "pc_mouse_click":
            x = slots.get("x")
            y = slots.get("y")
            button = str(slots.get("button", "left"))
            double = bool(slots.get("double", False))

            hook = get_overlay_hook()
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    btn_tr = "sol" if button == "left" else "sağ" if button == "right" else "orta"
                    click_tr = "çift tık" if double else "tık"
                    where = f"({int(x)}, {int(y)})" if x is not None and y is not None else "mevcut konum"
                    getattr(hook, "preview_action_sync")(f"{btn_tr} {click_tr}: {where}", 900)
                except Exception:
                    pass
            if x is not None and y is not None and hook and hasattr(hook, "cursor_dot_sync"):
                try:
                    getattr(hook, "cursor_dot_sync")(int(x), int(y), 700)
                except Exception:
                    pass

            ok, msg = click_mouse(button=button, x=int(x) if x is not None else None, y=int(y) if y is not None else None, double=double)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "pc_mouse_scroll":
            direction = str(slots.get("direction", "down"))
            amount = int(slots.get("amount", 3) or 3)
            hook = get_overlay_hook()
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    tr = "aşağı" if direction == "down" else "yukarı"
                    getattr(hook, "preview_action_sync")(f"Kaydırıyorum: {tr} ({amount})", 900)
                except Exception:
                    pass
            ok, msg = scroll_mouse(direction=direction, amount=amount)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "pc_hotkey":
            combo = str(slots.get("combo", "")).strip()
            hook = get_overlay_hook()
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    getattr(hook, "preview_action_sync")(f"Kısayol: {combo}", 900)
                except Exception:
                    pass
            ok, msg = hotkey(combo)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "clipboard_set":
            txt = str(slots.get("text", ""))
            hook = get_overlay_hook()
            if hook and hasattr(hook, "preview_action_sync"):
                try:
                    getattr(hook, "preview_action_sync")("Panoya kopyalıyorum…", 900)
                except Exception:
                    pass
            ok, msg = clipboard_set(txt)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

        if intent == "clipboard_get":
            ok, msg, val = clipboard_get()
            ctx.last_intent = intent
            if ok:
                return RouterResult(ok=True, intent=intent, user_text=(msg + "\n" + val).strip() + follow_up, data={"clipboard": val})
            return RouterResult(ok=False, intent=intent, user_text=msg + follow_up)

        if intent == "app_session_exit":
            if ctx.has_active_app():
                old_app = ctx.active_app
                ctx.clear_active_app()
                return RouterResult(ok=True, intent=intent, user_text=f"✅ {old_app} oturumundan çıktım. Normal moda döndüm." + follow_up)
            return RouterResult(ok=True, intent=intent, user_text="Zaten aktif uygulama oturumu yok." + follow_up)

        # ─────────────────────────────────────────────────────────────────
        # Coding Agent intents (Issue #4)
        # ─────────────────────────────────────────────────────────────────
        coding_intents = {
            "file_read", "file_write", "file_edit", "file_create", "file_delete",
            "file_undo", "file_list", "file_search",
            "terminal_run", "terminal_background", "terminal_background_output",
            "terminal_background_kill", "terminal_background_list",
            "code_apply_diff", "code_replace_function", "code_replace_class",
            "code_insert_lines", "code_delete_lines", "code_format", "code_search_replace",
            "project_info", "project_tree", "project_symbols", "project_search_symbol",
            "project_related_files", "project_imports",
        }
        
        if intent in coding_intents:
            try:
                from bantz.coding import CodingToolExecutor
                
                # Initialize executor (lazily cached)
                if not hasattr(self, "_coding_executor"):
                    from pathlib import Path
                    workspace = Path.cwd()
                    self._coding_executor = CodingToolExecutor(workspace_root=workspace)
                
                import asyncio
                
                # Run async execute
                loop = asyncio.new_event_loop()
                try:
                    ok, result_text = loop.run_until_complete(
                        self._coding_executor.execute(intent, slots)
                    )
                finally:
                    loop.close()
                
                ctx.last_intent = intent
                return RouterResult(ok=ok, intent=intent, user_text=result_text + follow_up)
                
            except Exception as e:
                ctx.last_intent = intent
                return RouterResult(ok=False, intent=intent, user_text=f"❌ Coding agent hatası: {e}" + follow_up)

        ctx.last_intent = "unknown"
        return RouterResult(
            ok=False,
            intent="unknown",
            user_text="Bunu anlayamadım. Örnek: 'google'ı aç', 'şunu ara: ...', 'indirilenler klasörünü aç'" + follow_up,
            data={"text": slots.get("text")},
        )

    # ─────────────────────────────────────────────────────────────────
    # Helper: Get click target text for risky check
    # ─────────────────────────────────────────────────────────────────
    def _get_click_target_text(self, slots: dict) -> str | None:
        """Get the text of the element that will be clicked (for risky check)."""
        try:
            from bantz.browser.skills import get_page_memory
        except ModuleNotFoundError:
            return None

        mem = get_page_memory()
        if not mem:
            return None

        if "index" in slots:
            el = mem.find_by_index(int(slots["index"]))
            return el.text if el else None
        elif "text" in slots:
            return str(slots["text"])

        return None

    # ─────────────────────────────────────────────────────────────────
    # Logging helper
    # ─────────────────────────────────────────────────────────────────
    def _log(
        self,
        request: str,
        result: RouterResult,
        parsed: Parsed,
        ctx_before: dict,
        ctx: ConversationContext,
        *,
        policy: dict | None = None,
        executed: dict | None = None,
        bridge: str | None = None,
    ) -> None:
        extra: dict = {}
        if policy:
            extra["policy"] = policy
        if executed:
            extra["executed"] = executed
        if bridge:
            extra["bridge"] = bridge

        self._logger.log(
            request=request,
            result=asdict(result),
            mode=ctx_before.get("mode"),
            parsed={"intent": parsed.intent, "slots": parsed.slots},
            ctx_before=ctx_before,
            ctx_after=ctx.snapshot(),
            **extra,
        )
        ctx.touch()
