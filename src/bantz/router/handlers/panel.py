"""Panel Intent Handlers (Issue #420).

Extracted from Router._dispatch() — handles Jarvis Panel intents (Issue #19).
"""

from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handler
from bantz.router.types import RouterResult
from bantz.skills.daily import open_url


def _follow(in_queue: bool) -> str:
    return "" if in_queue else " Başka ne yapayım?"


def handle_panel_move(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    position = str(slots.get("position", "")).strip()
    if not position:
        return RouterResult(ok=False, intent=intent, user_text="Nereye taşıyayım efendim?")
    controller = ctx.get_panel_controller()
    if controller:
        controller.move_panel(position)
        return RouterResult(ok=True, intent=intent, user_text=f"Panel {position} tarafına taşındı efendim.")
    return RouterResult(ok=False, intent=intent, user_text="Panel henüz açık değil efendim.")


def handle_panel_hide(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    controller = ctx.get_panel_controller()
    if controller:
        controller.hide_panel()
        ctx.set_panel_visible(False)
        return RouterResult(ok=True, intent=intent, user_text="Panel kapatıldı efendim.")
    return RouterResult(ok=True, intent=intent, user_text="Panel zaten kapalı efendim.")


def handle_panel_minimize(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    controller = ctx.get_panel_controller()
    if controller:
        controller.minimize_panel()
        return RouterResult(ok=True, intent=intent, user_text="Panel küçültüldü efendim.")
    return RouterResult(ok=False, intent=intent, user_text="Panel açık değil efendim.")


def handle_panel_maximize(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    controller = ctx.get_panel_controller()
    if controller:
        controller.maximize_panel()
        return RouterResult(ok=True, intent=intent, user_text="Panel büyütüldü efendim.")
    return RouterResult(ok=False, intent=intent, user_text="Panel açık değil efendim.")


def handle_panel_next_page(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    controller = ctx.get_panel_controller()
    if controller:
        controller.next_page()
        page = controller.current_page
        total = controller.total_pages
        return RouterResult(ok=True, intent=intent, user_text=f"Sayfa {page}/{total} efendim.", data={"page": page, "total": total})
    return RouterResult(ok=False, intent=intent, user_text="Gösterilecek sonuç yok efendim.")


def handle_panel_prev_page(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    controller = ctx.get_panel_controller()
    if controller:
        controller.prev_page()
        page = controller.current_page
        total = controller.total_pages
        return RouterResult(ok=True, intent=intent, user_text=f"Sayfa {page}/{total} efendim.", data={"page": page, "total": total})
    return RouterResult(ok=False, intent=intent, user_text="Gösterilecek sonuç yok efendim.")


def handle_panel_select_item(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    index = slots.get("index", 0)
    if not index:
        return RouterResult(ok=False, intent=intent, user_text="Kaçıncı sonucu açayım efendim?")
    item = ctx.get_panel_result_by_index(index)
    if item:
        url = item.get("url", "")
        if url:
            ok, msg = open_url(url)
            ctx.last_intent = intent
            return RouterResult(ok=ok, intent=intent, user_text=f"{index}. sonuç açılıyor efendim.", data={"index": index, "url": url})
        return RouterResult(ok=False, intent=intent, user_text=f"{index}. sonuçta URL yok efendim.")
    total = len(ctx.get_panel_results())
    if total > 0:
        return RouterResult(ok=False, intent=intent, user_text=f"Geçersiz numara. 1 ile {total} arasında bir sayı söyleyin efendim.")
    return RouterResult(ok=False, intent=intent, user_text="Gösterilecek sonuç yok efendim.")


# ── Registration ──────────────────────────────────────────────────────────

def register_all() -> None:
    """Register all panel intent handlers."""
    register_handler("panel_move", handle_panel_move)
    register_handler("panel_hide", handle_panel_hide)
    register_handler("panel_minimize", handle_panel_minimize)
    register_handler("panel_maximize", handle_panel_maximize)
    register_handler("panel_next_page", handle_panel_next_page)
    register_handler("panel_prev_page", handle_panel_prev_page)
    register_handler("panel_select_item", handle_panel_select_item)
