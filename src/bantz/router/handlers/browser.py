"""Browser Intent Handlers (Issue #420).

Extracted from Router._dispatch() — handles all browser_* and page_* intents.
"""

from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handler
from bantz.router.types import RouterResult


def _follow(in_queue: bool) -> str:
    return "" if in_queue else " Başka ne yapayım?"


def handle_ai_chat(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_ai_chat
    service = str(slots.get("service", "duck")).lower()
    prompt = str(slots.get("prompt", "")).strip()
    ok, msg = browser_ai_chat(service, prompt)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_open(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_open
    url = str(slots.get("url", "")).strip()
    ok, msg = browser_open(url)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_scan(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_scan
    ok, msg, scan = browser_scan()
    ctx.last_intent = intent
    data = {"scan": scan} if scan else None
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue), data=data)


def handle_browser_click(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
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
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_type(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_type_text
    text_to_type = str(slots.get("text", "")).strip()
    idx = slots.get("index")
    if idx is not None:
        ok, msg = browser_type_text(text_to_type, int(idx))
    else:
        ok, msg = browser_type_text(text_to_type)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_scroll_down(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_scroll_down
    ok, msg = browser_scroll_down()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_scroll_up(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_scroll_up
    ok, msg = browser_scroll_up()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_back(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_go_back
    ok, msg = browser_go_back()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_info(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_current_info
    ok, msg = browser_current_info()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_detail(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_detail
    idx = int(slots.get("index", 0))
    ok, msg = browser_detail(idx)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_wait(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_wait
    seconds = int(slots.get("seconds", 3))
    ok, msg = browser_wait(seconds)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_browser_search(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.browser.skills import browser_search_in_page
    query = str(slots.get("query", "")).strip()
    if not query:
        return RouterResult(ok=False, intent=intent, user_text="Ne arayayım?")
    ok, msg = browser_search_in_page(query)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


# ── Registration ──────────────────────────────────────────────────────────

def register_all() -> None:
    """Register all browser intent handlers."""
    register_handler("ai_chat", handle_ai_chat)
    register_handler("browser_open", handle_browser_open)
    register_handler("browser_scan", handle_browser_scan)
    register_handler("browser_click", handle_browser_click)
    register_handler("browser_type", handle_browser_type)
    register_handler("browser_scroll_down", handle_browser_scroll_down)
    register_handler("browser_scroll_up", handle_browser_scroll_up)
    register_handler("browser_back", handle_browser_back)
    register_handler("browser_info", handle_browser_info)
    register_handler("browser_detail", handle_browser_detail)
    register_handler("browser_wait", handle_browser_wait)
    register_handler("browser_search", handle_browser_search)
