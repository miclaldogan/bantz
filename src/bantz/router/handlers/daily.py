"""Daily Skills Intent Handlers (Issue #420).

Extracted from Router._dispatch() — handles open_browser, google_search,
open_path, open_url, notify, open_btop intents.
"""

from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handler
from bantz.router.types import RouterResult
from bantz.skills.daily import open_btop, open_browser, open_path, open_url, google_search, notify


def _follow(in_queue: bool) -> str:
    return "" if in_queue else " Başka ne yapayım?"


def handle_open_browser(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    ok, msg = open_browser()
    ctx.last_intent = intent
    if not in_queue:
        ctx.awaiting = "search_query"
    search_follow = "" if in_queue else " Ne arayayım?"
    return RouterResult(ok=ok, intent=intent, user_text=msg + search_follow)


def handle_google_search(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    query = str(slots.get("query", "")).strip()
    if not query:
        if not in_queue:
            ctx.awaiting = "search_query"
        return RouterResult(ok=False, intent=intent, user_text="Ne arayayım?")
    ok, msg = google_search(query=query)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_open_path(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    target = str(slots.get("target", "")).strip()
    ok, msg = open_path(target)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_open_url(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    url = str(slots.get("url", "")).strip()
    ok, msg = open_url(url)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_notify(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    message = str(slots.get("message", "")).strip()
    ok, msg = notify(message)
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


def handle_open_btop(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    ok, msg = open_btop()
    ctx.last_intent = intent
    return RouterResult(ok=ok, intent=intent, user_text=msg + _follow(in_queue))


# ── Registration ──────────────────────────────────────────────────────────

def register_all() -> None:
    """Register all daily skills intent handlers."""
    register_handler("open_browser", handle_open_browser)
    register_handler("google_search", handle_google_search)
    register_handler("open_path", handle_open_path)
    register_handler("open_url", handle_open_url)
    register_handler("notify", handle_notify)
    register_handler("open_btop", handle_open_btop)
