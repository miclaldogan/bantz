"""Sync-powered data search intent handlers.

Maps the 9 sync intents (inbox_search, calendar_upcoming, etc.)
to the sync_search_tools functions, following the handler protocol.
"""

from __future__ import annotations

import json
import logging

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handler
from bantz.router.types import RouterResult

logger = logging.getLogger(__name__)


def _follow(in_queue: bool) -> str:
    return "" if in_queue else " Başka ne yapayım?"


def _format_result(data: dict) -> str:
    """Format a sync tool result dict into human-readable text."""
    if not data.get("ok"):
        return data.get("error", "Bir hata oluştu.")

    hint = data.get("display_hint", "")
    if hint:
        return hint
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── Inbox handlers ────────────────────────────────────────────


def handle_inbox_search(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import inbox_search_tool
    query = str(slots.get("query", slots.get("text", ""))).strip()
    limit = int(slots.get("limit", 20))
    result = inbox_search_tool(query=query, limit=limit)
    ctx.last_intent = intent
    text = _format_result(result)
    if result.get("messages"):
        lines = [text]
        for m in result["messages"][:10]:
            cat = m.get("category", "")
            subj = m.get("subject", "")
            sender = m.get("sender_name") or m.get("from", "")
            lines.append(f"  • [{cat}] {sender}: {subj}")
        text = "\n".join(lines)
    return RouterResult(ok=result["ok"], intent=intent, user_text=text + _follow(in_queue), data=result)


def handle_inbox_classify(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import inbox_by_category_tool
    category = str(slots.get("category", slots.get("text", ""))).strip().lower()
    limit = int(slots.get("limit", 20))
    result = inbox_by_category_tool(category=category, limit=limit)
    ctx.last_intent = intent
    text = _format_result(result)
    if result.get("messages"):
        lines = [text]
        for m in result["messages"][:10]:
            sender = m.get("sender_name") or m.get("from", "")
            subj = m.get("subject", "")
            lines.append(f"  • {sender}: {subj}")
        text = "\n".join(lines)
    return RouterResult(ok=result["ok"], intent=intent, user_text=text + _follow(in_queue), data=result)


def handle_inbox_summary(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import inbox_summary_tool
    result = inbox_summary_tool()
    ctx.last_intent = intent
    if result.get("ok"):
        lines = [_format_result(result)]
        if result.get("top_categories"):
            lines.append("Kategoriler:")
            for c in result["top_categories"]:
                lines.append(f"  • {c['category']}: {c['count']} mesaj")
        if result.get("top_senders"):
            lines.append("En çok gönderenler:")
            for s in result["top_senders"]:
                lines.append(f"  • {s['sender']}: {s['count']} mesaj")
        text = "\n".join(lines)
    else:
        text = _format_result(result)
    return RouterResult(ok=result.get("ok", False), intent=intent, user_text=text + _follow(in_queue), data=result)


# ── Calendar handlers ─────────────────────────────────────────


def handle_calendar_upcoming(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import calendar_upcoming_tool
    days = int(slots.get("days", 7))
    limit = int(slots.get("limit", 20))
    result = calendar_upcoming_tool(days=days, limit=limit)
    ctx.last_intent = intent
    text = _format_result(result)
    if result.get("events"):
        lines = [text]
        for e in result["events"][:10]:
            start = e.get("start", "")
            summary = e.get("summary", "")
            loc = e.get("location", "")
            line = f"  • {start}: {summary}"
            if loc:
                line += f" @ {loc}"
            lines.append(line)
        text = "\n".join(lines)
    return RouterResult(ok=result["ok"], intent=intent, user_text=text + _follow(in_queue), data=result)


def handle_calendar_search(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import calendar_search_tool
    query = str(slots.get("query", slots.get("text", ""))).strip()
    limit = int(slots.get("limit", 20))
    result = calendar_search_tool(query=query, limit=limit)
    ctx.last_intent = intent
    text = _format_result(result)
    if result.get("events"):
        lines = [text]
        for e in result["events"][:10]:
            lines.append(f"  • {e.get('start', '')}: {e.get('summary', '')}")
        text = "\n".join(lines)
    return RouterResult(ok=result["ok"], intent=intent, user_text=text + _follow(in_queue), data=result)


# ── News handlers ─────────────────────────────────────────────


def handle_news_latest(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import news_latest_tool
    category = str(slots.get("category", "")).strip().lower()
    limit = int(slots.get("limit", 5))
    result = news_latest_tool(category=category, limit=limit)
    ctx.last_intent = intent
    text = _format_result(result)
    if result.get("articles"):
        lines = [text]
        for a in result["articles"][:10]:
            src = a.get("source", "")
            title = a.get("title", "")
            lines.append(f"  • [{src}] {title}")
        text = "\n".join(lines)
    return RouterResult(ok=result["ok"], intent=intent, user_text=text + _follow(in_queue), data=result)


def handle_news_search(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import news_search_tool
    query = str(slots.get("query", slots.get("text", ""))).strip()
    limit = int(slots.get("limit", 10))
    result = news_search_tool(query=query, limit=limit)
    ctx.last_intent = intent
    text = _format_result(result)
    if result.get("articles"):
        lines = [text]
        for a in result["articles"][:10]:
            lines.append(f"  • [{a.get('source', '')}] {a.get('title', '')}")
        text = "\n".join(lines)
    return RouterResult(ok=result["ok"], intent=intent, user_text=text + _follow(in_queue), data=result)


# ── Sync management handlers ─────────────────────────────────


def handle_sync_status(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import sync_status_tool
    result = sync_status_tool()
    ctx.last_intent = intent
    if result.get("ok"):
        running = "çalışıyor ✓" if result.get("is_running") else "durdu ✗"
        uptime = result.get("uptime_seconds", 0)
        lines = [f"Senkronizasyon: {running} (uptime: {uptime}s)"]
        for src in ("gmail", "calendar", "news"):
            if src in result:
                s = result[src]
                synced = s.get("total_synced", 0)
                last = s.get("last_sync", 0)
                state = "aktif" if s.get("is_running") else "pasif"
                lines.append(f"  • {src}: {synced} kayıt, {state}")
        text = "\n".join(lines)
    else:
        text = _format_result(result)
    return RouterResult(ok=result.get("ok", False), intent=intent, user_text=text + _follow(in_queue), data=result)


def handle_sync_now(
    *, intent: str, slots: dict, ctx: ConversationContext,
    router: object, in_queue: bool,
) -> RouterResult:
    from bantz.tools.sync_search_tools import sync_now_tool
    source = str(slots.get("source", slots.get("text", ""))).strip().lower()
    result = sync_now_tool(source=source)
    ctx.last_intent = intent
    text = _format_result(result)
    return RouterResult(ok=result.get("ok", False), intent=intent, user_text=text + _follow(in_queue), data=result)


# ── Registration ──────────────────────────────────────────────


def register_all() -> None:
    """Register all sync-powered data search intent handlers."""
    register_handler("inbox_search", handle_inbox_search)
    register_handler("inbox_classify", handle_inbox_classify)
    register_handler("inbox_summary", handle_inbox_summary)
    register_handler("calendar_upcoming", handle_calendar_upcoming)
    register_handler("calendar_search", handle_calendar_search)
    register_handler("news_latest", handle_news_latest)
    register_handler("news_search", handle_news_search)
    register_handler("sync_status", handle_sync_status)
    register_handler("sync_now", handle_sync_now)
