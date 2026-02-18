"""
Sync-powered search tools — agent-facing tools that query the IngestStore.

These tools allow the agent to search locally synced data instead of
making live API calls.  This is faster, works offline after initial
sync, and enables cross-source queries.

Tool catalog::

    inbox.search          — Search synced Gmail messages by keyword
    inbox.by_category     — List messages by classification category
    inbox.categories      — List available inbox categories with counts
    inbox.summary         — Get inbox summary (unread, top categories)
    calendar.upcoming     — Get upcoming events from local DB
    calendar.search       — Search synced calendar events
    news.latest           — Get latest news from local DB
    news.search           — Search synced news by keyword/category
    sync.status           — Show sync health and stats
    sync.now              — Trigger immediate sync for a source
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lazy singleton — set by init_sync_tools() at boot
_scheduler: Any = None
_store: Any = None


def init_sync_tools(scheduler: Any) -> None:
    """Initialize sync tools with the shared scheduler instance.

    Called once at boot from daemon or orchestrator.
    """
    global _scheduler, _store
    _scheduler = scheduler
    _store = scheduler.store


def _get_store():
    """Get the IngestStore, lazy-init if needed."""
    global _store
    if _store is not None:
        return _store
    try:
        from bantz.data.ingest_store import IngestStore
        _store = IngestStore()
        return _store
    except Exception as e:
        logger.warning("[SyncTools] Failed to init store: %s", e)
        return None


# ── Inbox tools ──────────────────────────────────────────────

def inbox_search_tool(query: str = "", limit: int = 20) -> Dict[str, Any]:
    """Search synced Gmail messages by keyword.

    Searches across subject, sender, snippet, and classification metadata.
    Much faster than live Gmail API calls since data is already local.

    Args:
        query: Search keyword (searches subject, sender, snippet).
        limit: Max results to return.

    Returns:
        Dict with matched messages and their classifications.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "messages": []}

    if not query.strip():
        # No query — return most recent synced messages
        records = store.query(source="gmail", limit=limit)
    else:
        records = store.search(query, source="gmail", limit=limit)

    messages = []
    for r in records:
        content = r.content or {}
        meta = r.meta or {}
        messages.append({
            "message_id": content.get("message_id", ""),
            "from": content.get("from", ""),
            "sender_name": content.get("sender_name", ""),
            "subject": content.get("subject", ""),
            "snippet": content.get("snippet", ""),
            "date": content.get("date", ""),
            "category": meta.get("category", content.get("category", "uncategorized")),
            "confidence": meta.get("confidence", 0),
        })

    return {
        "ok": True,
        "query": query,
        "count": len(messages),
        "messages": messages,
        "display_hint": (
            f"DB'de '{query}' araması: {len(messages)} sonuç bulundu."
            if query else f"Son {len(messages)} senkronize mesaj."
        ),
    }


def inbox_by_category_tool(
    category: str = "", limit: int = 20,
) -> Dict[str, Any]:
    """List synced messages filtered by classification category.

    Categories: github, tubitak, linkedin, google, amazon, bank,
    newsletter, social, education, shopping, travel, uncategorized.

    Args:
        category: Classification category to filter by.
        limit: Max results to return.

    Returns:
        Dict with messages matching the category.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "messages": []}

    if not category.strip():
        return {"ok": False, "error": "category parameter required", "messages": []}

    # Search by category in meta
    records = store.search(category, source="gmail", limit=limit)

    # Filter to exact category match
    messages = []
    for r in records:
        meta = r.meta or {}
        content = r.content or {}
        record_cat = meta.get("category", content.get("category", ""))
        if record_cat.lower() == category.lower():
            messages.append({
                "message_id": content.get("message_id", ""),
                "from": content.get("from", ""),
                "sender_name": content.get("sender_name", ""),
                "subject": content.get("subject", ""),
                "snippet": content.get("snippet", ""),
                "date": content.get("date", ""),
                "category": record_cat,
            })

    return {
        "ok": True,
        "category": category,
        "count": len(messages),
        "messages": messages,
        "display_hint": f"'{category}' kategorisinde {len(messages)} mesaj bulundu.",
    }


def inbox_categories_tool() -> Dict[str, Any]:
    """List available inbox categories with message counts.

    Returns all classification categories that have at least one
    synced message, with counts.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "categories": []}

    records = store.query(source="gmail", limit=500)

    counts: Dict[str, int] = {}
    for r in records:
        meta = r.meta or {}
        content = r.content or {}
        cat = meta.get("category", content.get("category", "uncategorized"))
        counts[cat] = counts.get(cat, 0) + 1

    categories = [
        {"category": cat, "count": count}
        for cat, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "ok": True,
        "total_messages": sum(counts.values()),
        "categories": categories,
        "display_hint": f"Toplam {sum(counts.values())} mesaj, {len(categories)} kategori.",
    }


def inbox_summary_tool() -> Dict[str, Any]:
    """Get a summary of the synced inbox.

    Returns total message count, top categories, and recent senders.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available"}

    records = store.query(source="gmail", limit=200)

    cats: Dict[str, int] = {}
    senders: Dict[str, int] = {}
    recent_subjects: list[str] = []

    for i, r in enumerate(records):
        meta = r.meta or {}
        content = r.content or {}
        cat = meta.get("category", content.get("category", "uncategorized"))
        cats[cat] = cats.get(cat, 0) + 1

        sender = content.get("sender_name") or content.get("from", "unknown")
        senders[sender] = senders.get(sender, 0) + 1

        if i < 5:
            subj = content.get("subject", "")
            if subj:
                recent_subjects.append(subj)

    top_categories = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
    top_senders = sorted(senders.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "ok": True,
        "total_messages": len(records),
        "top_categories": [{"category": c, "count": n} for c, n in top_categories],
        "top_senders": [{"sender": s, "count": n} for s, n in top_senders],
        "recent_subjects": recent_subjects,
        "display_hint": f"Gelen kutusu: {len(records)} mesaj, en çok {top_categories[0][0] if top_categories else 'yok'}.",
    }


# ── Calendar tools ───────────────────────────────────────────

def calendar_upcoming_tool(
    days: int = 7, limit: int = 20,
) -> Dict[str, Any]:
    """Get upcoming events from locally synced calendar data.

    Faster than live API calls since data is already in the database.

    Args:
        days: How many days forward to look (default 7).
        limit: Max events to return.

    Returns:
        Dict with upcoming events.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "events": []}

    records = store.query(source="calendar", limit=limit)

    events = []
    for r in records:
        content = r.content or {}
        meta = r.meta or {}
        events.append({
            "event_id": content.get("event_id", ""),
            "summary": content.get("summary", ""),
            "start": content.get("start", ""),
            "end": content.get("end", ""),
            "location": content.get("location", ""),
            "status": content.get("status", ""),
            "is_all_day": meta.get("is_all_day", False),
        })

    # Sort by start time
    events.sort(key=lambda e: e.get("start", ""))

    return {
        "ok": True,
        "count": len(events),
        "events": events,
        "display_hint": f"Önümüzdeki {days} günde {len(events)} etkinlik.",
    }


def calendar_search_tool(
    query: str = "", limit: int = 20,
) -> Dict[str, Any]:
    """Search synced calendar events by keyword.

    Args:
        query: Search keyword (searches title, location).
        limit: Max results to return.

    Returns:
        Dict with matched events.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "events": []}

    if not query.strip():
        return {"ok": False, "error": "query parameter required", "events": []}

    records = store.search(query, source="calendar", limit=limit)

    events = []
    for r in records:
        content = r.content or {}
        events.append({
            "event_id": content.get("event_id", ""),
            "summary": content.get("summary", ""),
            "start": content.get("start", ""),
            "end": content.get("end", ""),
            "location": content.get("location", ""),
            "status": content.get("status", ""),
        })

    events.sort(key=lambda e: e.get("start", ""))

    return {
        "ok": True,
        "query": query,
        "count": len(events),
        "events": events,
        "display_hint": f"Takvimde '{query}' araması: {len(events)} etkinlik bulundu.",
    }


# ── News tools ───────────────────────────────────────────────

def news_latest_tool(
    category: str = "", limit: int = 5,
) -> Dict[str, Any]:
    """Get latest news from locally synced RSS feeds.

    Args:
        category: Filter by category (ai, tech, turkey). Empty = all.
        limit: Max articles to return.

    Returns:
        Dict with latest news articles.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "articles": []}

    if category.strip():
        records = store.search(category, source="news", limit=limit)
    else:
        records = store.query(source="news", limit=limit)

    articles = []
    for r in records:
        content = r.content or {}
        meta = r.meta or {}
        article_cat = meta.get("category", content.get("category", ""))
        # Filter by category if specified
        if category.strip() and article_cat.lower() != category.lower():
            continue
        articles.append({
            "title": content.get("title", ""),
            "url": content.get("url", ""),
            "source": content.get("source", ""),
            "published": content.get("published", ""),
            "summary": content.get("summary", ""),
            "category": article_cat,
        })

    return {
        "ok": True,
        "category": category or "all",
        "count": len(articles),
        "articles": articles,
        "display_hint": (
            f"'{category}' kategorisinde {len(articles)} haber."
            if category else f"Son {len(articles)} haber."
        ),
    }


def news_search_tool(
    query: str = "", limit: int = 10,
) -> Dict[str, Any]:
    """Search synced news articles by keyword.

    Args:
        query: Search keyword (searches title, source, summary).
        limit: Max results to return.

    Returns:
        Dict with matched articles.
    """
    store = _get_store()
    if store is None:
        return {"ok": False, "error": "IngestStore not available", "articles": []}

    if not query.strip():
        return {"ok": False, "error": "query parameter required", "articles": []}

    records = store.search(query, source="news", limit=limit)

    articles = []
    for r in records:
        content = r.content or {}
        meta = r.meta or {}
        articles.append({
            "title": content.get("title", ""),
            "url": content.get("url", ""),
            "source": content.get("source", ""),
            "published": content.get("published", ""),
            "summary": content.get("summary", ""),
            "category": meta.get("category", content.get("category", "")),
        })

    return {
        "ok": True,
        "query": query,
        "count": len(articles),
        "articles": articles,
        "display_hint": f"Haberlerde '{query}' araması: {len(articles)} sonuç.",
    }


# ── Sync management tools ────────────────────────────────────

def sync_status_tool() -> Dict[str, Any]:
    """Show sync health, stats, and last sync times.

    Returns:
        Dict with sync status for all sources.
    """
    global _scheduler
    if _scheduler is None:
        return {"ok": False, "error": "SyncScheduler not initialized"}

    return {
        "ok": True,
        **_scheduler.stats,
        "display_hint": "Senkronizasyon durumu gösterildi.",
    }


def sync_now_tool(source: str = "") -> Dict[str, Any]:
    """Trigger an immediate sync for a specific source.

    Args:
        source: One of 'gmail', 'calendar', 'news'.
                Empty string syncs all sources.

    Returns:
        Dict with sync results.
    """
    global _scheduler
    if _scheduler is None:
        return {"ok": False, "error": "SyncScheduler not initialized"}

    import asyncio

    valid_sources = {"gmail", "calendar", "news", ""}
    if source.lower() not in valid_sources:
        return {
            "ok": False,
            "error": f"Unknown source: {source}. Valid: gmail, calendar, news",
        }

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    src = source.lower() if source else None

    if loop and loop.is_running():
        # Already in async context — schedule as task
        # The caller (orchestrator) will await the result
        import concurrent.futures
        future: concurrent.futures.Future = concurrent.futures.Future()  # type: ignore[type-arg]

        async def _do_sync():
            try:
                result = await _scheduler.sync_now(src)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

        asyncio.ensure_future(_do_sync())
        return {
            "ok": True,
            "status": "sync_triggered",
            "source": source or "all",
            "display_hint": f"{'Tüm kaynaklar' if not source else source} senkronizasyonu başlatıldı.",
        }
    else:
        # Not in async context — run synchronously
        result = asyncio.run(_scheduler.sync_now(src))
        return {"ok": True, "results": result}
