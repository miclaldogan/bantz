"""PC / Desktop Control Intent Handlers (Issue #420).

Extracted from Router._dispatch() — handles app_*, pc_mouse_*, pc_hotkey,
clipboard_*, and app_session_exit intents.
"""

from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handler
from bantz.router.types import RouterResult
from bantz.skills.pc import (
    open_app, close_app, focus_app, list_windows, type_text, send_key,
    move_mouse, click_mouse, scroll_mouse, hotkey, clipboard_set, clipboard_get,
)


def _follow(in_queue: bool) -> str:
    return "" if in_queue else " Başka ne yapayım?"


def _get_overlay_hook():
    from bantz.router.engine import get_overlay_hook
    return get_overlay_hook()


def _preview(text: str, duration_ms: int = 900) -> None:
    hook = _get_overlay_hook()
    if hook and hasattr(hook, "preview_action_sync"):
        try:
            getattr(hook, "preview_action_sync")(text, duration_ms)
        except Exception:
            pass


def _cursor_dot(x: int, y: int, duration_ms: int = 700) -> None:
    hook = _get_overlay_hook()
    if hook and hasattr(hook, "cursor_dot_sync"):
        try:
            getattr(hook, "cursor_dot_sync")(x, y, duration_ms)
        except Exception:
            pass


def handle_app_open(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    app_name = str(slots.get("app", "")).strip().lower()
    ok, msg, window_id = open_app(app_name)
    if ok:
        ctx.set_active_app(app_name, window_id)
        session_hint = f" 🎯 {app_name} oturumu başladı. Komut verebilirsin ('yaz:', 'gönder', 'kapat') veya 'uygulamadan çık' de."
        return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_app_close(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    app_name = str(slots.get("app", "")).strip().lower() if slots.get("app") else None
    if not app_name and ctx.has_active_app():
        app_name = ctx.active_app
    if not app_name:
        return RouterResult(ok=False, intent=intent, user_text="Hangi uygulamayı kapatayım?" + _follow(in_queue))
    ok, msg = close_app(app_name)
    if ok and ctx.active_app == app_name:
        ctx.clear_active_app()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_app_focus(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    app_name = str(slots.get("app", "")).strip().lower()
    ok, msg, window_id = focus_app(app_name)
    if ok:
        ctx.set_active_app(app_name, window_id)
        session_hint = f" 🎯 {app_name} oturumuna geçtim."
        return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_app_list(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    ok, msg, windows = list_windows()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue), data={"windows": windows})


def handle_app_type(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    text_to_type = str(slots.get("text", "")).strip()
    if not text_to_type:
        return RouterResult(ok=False, intent=intent, user_text="Ne yazayım?" + _follow(in_queue))
    _preview(f"Yazıyorum: {text_to_type[:60]}", 1200)
    target_window = ctx.active_window_id if ctx.has_active_app() else None
    ok, msg = type_text(text_to_type, window_id=target_window)
    ctx.last_intent = intent
    session_hint = f" ({ctx.active_app} oturumunda)" if ctx.has_active_app() else ""
    return RouterResult(ok=ok, intent=intent, user_text=msg + session_hint + _follow(in_queue))


def handle_app_submit(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    target_window = ctx.active_window_id if ctx.has_active_app() else None
    _preview("Enter gönderiyorum…", 800)
    ok, msg = send_key("Return", window_id=target_window)
    ctx.last_intent = intent
    session_hint = f" ({ctx.active_app} oturumunda)" if ctx.has_active_app() else ""
    return RouterResult(ok=ok, intent=intent, user_text="Gönderildi." + session_hint + _follow(in_queue))


def handle_pc_mouse_move(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    x = int(slots.get("x", 0))
    y = int(slots.get("y", 0))
    duration_ms = int(slots.get("duration_ms", 0) or 0)
    _cursor_dot(x, y)
    _preview(f"İmleci ({x}, {y}) konumuna götürüyorum…")
    ok, msg = move_mouse(x, y, duration_ms=duration_ms)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_pc_mouse_click(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    x = slots.get("x")
    y = slots.get("y")
    button = str(slots.get("button", "left"))
    double = bool(slots.get("double", False))
    btn_tr = "sol" if button == "left" else "sağ" if button == "right" else "orta"
    click_tr = "çift tık" if double else "tık"
    where = f"({int(x)}, {int(y)})" if x is not None and y is not None else "mevcut konum"
    _preview(f"{btn_tr} {click_tr}: {where}")
    if x is not None and y is not None:
        _cursor_dot(int(x), int(y))
    ok, msg = click_mouse(button=button, x=int(x) if x is not None else None, y=int(y) if y is not None else None, double=double)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_pc_mouse_scroll(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    direction = str(slots.get("direction", "down"))
    amount = int(slots.get("amount", 3) or 3)
    tr = "aşağı" if direction == "down" else "yukarı"
    _preview(f"Kaydırıyorum: {tr} ({amount})")
    ok, msg = scroll_mouse(direction=direction, amount=amount)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_pc_hotkey(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    combo = str(slots.get("combo", "")).strip()
    _preview(f"Kısayol: {combo}")
    ok, msg = hotkey(combo)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_clipboard_set(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    txt = str(slots.get("text", ""))
    _preview("Panoya kopyalıyorum…")
    ok, msg = clipboard_set(txt)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_clipboard_get(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    ok, msg, val = clipboard_get()
    ctx.last_intent = intent
    if ok:
        return RouterResult(ok=True, intent=intent, user_text=(msg + "\n" + val).strip() + _follow(in_queue), data={"clipboard": val})
    return RouterResult(ok=False, intent=intent, user_text=msg + _follow(in_queue))


def handle_app_session_exit(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    if ctx.has_active_app():
        old_app = ctx.active_app
        ctx.clear_active_app()
        return RouterResult(ok=True, intent=intent, user_text=f"✅ {old_app} oturumundan çıktım. Normal moda döndüm." + _follow(in_queue))
    return RouterResult(ok=True, intent=intent, user_text="Zaten aktif uygulama oturumu yok." + _follow(in_queue))


# ── Registration ──────────────────────────────────────────────────────────

def register_all() -> None:
    """Register all PC/desktop control intent handlers."""
    register_handler("app_open", handle_app_open)
    register_handler("app_close", handle_app_close)
    register_handler("app_focus", handle_app_focus)
    register_handler("app_list", handle_app_list)
    register_handler("app_type", handle_app_type)
    register_handler("app_submit", handle_app_submit)
    register_handler("pc_mouse_move", handle_pc_mouse_move)
    register_handler("pc_mouse_click", handle_pc_mouse_click)
    register_handler("pc_mouse_scroll", handle_pc_mouse_scroll)
    register_handler("pc_hotkey", handle_pc_hotkey)
    register_handler("clipboard_set", handle_clipboard_set)
    register_handler("clipboard_get", handle_clipboard_get)
    register_handler("app_session_exit", handle_app_session_exit)
