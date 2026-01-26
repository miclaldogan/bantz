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

    def handle(self, text: str, ctx: ConversationContext) -> RouterResult:
        ctx.reset_if_expired()
        ctx.reset_pending_if_expired()

        ctx_before = ctx.snapshot()
        parsed = parse_intent(text)

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
                result = RouterResult(ok=True, intent="queue_pause", user_text="Kuyruk duraklatıldı. 'devam et' diyebilirsin.")
            else:
                result = RouterResult(ok=False, intent="queue_pause", user_text="Aktif kuyruk yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "queue_resume":
            if ctx.queue_active() and ctx.queue_paused:
                ctx.queue_paused = False
                return self._run_queue(ctx, ctx_before, text)
            elif ctx.queue_active():
                result = RouterResult(ok=False, intent="queue_resume", user_text="Kuyruk zaten çalışıyor.")
            else:
                result = RouterResult(ok=False, intent="queue_resume", user_text="Devam edilecek kuyruk yok. Başka ne yapayım?")
            self._log(text, result, parsed, ctx_before, ctx)
            return result

        if parsed.intent == "queue_abort":
            if ctx.queue_active():
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
                result = RouterResult(
                    ok=True,
                    intent="queue_status",
                    user_text=f"Kalan adımlar{paused_note}:\n" + "\n".join(lines) + "\nBaşka ne yapayım?",
                )
            else:
                result = RouterResult(ok=True, intent="queue_status", user_text="Aktif kuyruk yok. Başka ne yapayım?")
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

        while ctx.queue_active() and not ctx.queue_paused:
            step = ctx.current_step()
            if step is None:
                break

            parsed = Parsed(intent=step.intent, slots=step.slots)
            decision, reason = self._policy.decide(text=step.original_text, intent=step.intent, confirmed=False)

            if decision == "deny":
                # Skip this step, continue
                ctx.advance_queue()
                continue

            if decision == "confirm":
                ctx.set_pending(original_text=step.original_text, intent=step.intent, slots=step.slots, policy_decision=reason)
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
                # Step failed, pause queue
                ctx.queue_paused = True
                return RouterResult(
                    ok=False,
                    intent=step.intent,
                    user_text=exec_result.user_text + " Kuyruk duraklatıldı. 'devam et' veya 'sıradaki' diyebilirsin.",
                )

            ctx.advance_queue()

        # Queue finished or paused
        if ctx.queue_paused:
            return RouterResult(ok=True, intent="queue_pause", user_text="Kuyruk duraklatıldı. 'devam et' diyebilirsin.")

        ctx.clear_queue()
        return RouterResult(ok=True, intent="unknown", user_text="Zincir tamamlandı. Başka ne yapayım?")

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
            ok, msg, _ = browser_scan()
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=msg + follow_up)

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
            # Use active window if we have a session
            target_window = ctx.active_window_id if ctx.has_active_app() else None
            ok, msg = type_text(text_to_type, window_id=target_window)
            ctx.last_intent = intent
            session_hint = f" ({ctx.active_app} oturumunda)" if ctx.has_active_app() else ""
            return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint + follow_up)

        if intent == "app_submit":
            # Send Enter key to submit
            target_window = ctx.active_window_id if ctx.has_active_app() else None
            ok, msg = send_key("Return", window_id=target_window)
            ctx.last_intent = intent
            session_hint = f" ({ctx.active_app} oturumunda)" if ctx.has_active_app() else ""
            return RouterResult(ok=ok, intent=intent, user_text="Gönderildi." + session_hint + follow_up)

        if intent == "app_session_exit":
            if ctx.has_active_app():
                old_app = ctx.active_app
                ctx.clear_active_app()
                return RouterResult(ok=True, intent=intent, user_text=f"✅ {old_app} oturumundan çıktım. Normal moda döndüm." + follow_up)
            return RouterResult(ok=True, intent=intent, user_text="Zaten aktif uygulama oturumu yok." + follow_up)

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
