"""
News synchronizer — pulls RSS feed news into IngestStore.

Bridges the existing ``RSSNewsProvider`` from ``bantz.skills.news_briefing``
into the data sync layer, writing articles into IngestStore with category
metadata so the agent can search news locally.

Integrates with Issue #11 (News briefing pipeline) by providing
persistent, searchable news storage with TTL-based expiration.

Usage::

    syncer = NewsSyncer(store)
    await syncer.sync()             # one-shot (all categories)
    await syncer.sync("ai")        # single category
    await syncer.start_periodic()  # background loop

Each ingested article gets metadata::

    meta = {
        "category": "ai",
        "source_feed": "https://techcrunch.com/feed/",
        "published": "2026-02-16T08:30:00",
        "author": "John Doe",
        "sync_source": "news_sync",
    }
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from bantz.data.ingest_store import DataClass, IngestStore

logger = logging.getLogger(__name__)

# Sync config defaults
_DEFAULT_SYNC_INTERVAL = 1800      # 30 minutes
_INGEST_SOURCE = "news"


class NewsSyncer:
    """RSS news → IngestStore synchronizer.

    Parameters
    ----------
    store : IngestStore
        Target ingest store.
    sync_interval : int
        Seconds between periodic syncs.
    categories : list[str], optional
        Which news categories to sync.  Defaults to all configured categories.
    max_items_per_category : int
        Max articles per category per sync pass.
    """

    def __init__(
        self,
        store: IngestStore,
        *,
        sync_interval: int = _DEFAULT_SYNC_INTERVAL,
        categories: Optional[List[str]] = None,
        max_items_per_category: int = 5,
    ) -> None:
        self._store = store
        self._sync_interval = sync_interval
        self._categories = categories
        self._max_items = max_items_per_category
        self._last_sync: float = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        # Stats
        self._total_synced = 0
        self._by_category: Dict[str, int] = {}

    # ── Public API ────────────────────────────────────────────

    async def sync(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Run a single sync pass.  Optionally sync only one category."""
        logger.info("[NewsSync] Starting sync pass (category=%s)...", category or "all")
        start = time.time()

        try:
            articles = await self._fetch_articles(category)
            if not articles:
                logger.info("[NewsSync] No new articles to sync.")
                return {"ok": True, "synced": 0, "elapsed_ms": 0}

            ingested = 0
            categories: Dict[str, int] = {}

            for article in articles:
                record_id = self._ingest_article(article)
                if record_id:
                    ingested += 1
                    cat = article.get("_category", "general")
                    categories[cat] = categories.get(cat, 0) + 1

            elapsed_ms = int((time.time() - start) * 1000)
            self._last_sync = time.time()
            self._total_synced += ingested

            for cat, count in categories.items():
                self._by_category[cat] = self._by_category.get(cat, 0) + count

            logger.info(
                "[NewsSync] Synced %d articles in %dms — categories: %s",
                ingested, elapsed_ms, categories,
            )
            return {
                "ok": True,
                "synced": ingested,
                "categories": categories,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.error("[NewsSync] Sync failed: %s", e, exc_info=True)
            return {"ok": False, "error": str(e), "synced": 0}

    async def start_periodic(self) -> None:
        """Start periodic background sync."""
        if self._running:
            logger.warning("[NewsSync] Already running.")
            return
        self._running = True
        self._task = asyncio.create_task(self._periodic_loop())
        logger.info(
            "[NewsSync] Periodic sync started (interval=%ds)",
            self._sync_interval,
        )

    async def stop(self) -> None:
        """Stop the periodic sync loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[NewsSync] Stopped.")

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cumulative sync stats."""
        return {
            "total_synced": self._total_synced,
            "by_category": dict(self._by_category),
            "last_sync": self._last_sync,
            "is_running": self._running,
        }

    # ── Private helpers ───────────────────────────────────────

    async def _periodic_loop(self) -> None:
        """Background loop: sync → sleep → repeat."""
        while self._running:
            try:
                await self.sync()
            except Exception as e:
                logger.error("[NewsSync] Periodic sync error: %s", e)
            await asyncio.sleep(self._sync_interval)

    async def _fetch_articles(
        self, category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch news articles from RSS providers.

        Runs the blocking fetch in an executor thread.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._fetch_articles_sync, category,
        )

    def _fetch_articles_sync(
        self, category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Synchronous RSS fetch (runs in thread pool)."""
        try:
            from bantz.skills.news_briefing import (
                NEWS_CATEGORIES,
                RSSNewsProvider,
            )
        except ImportError:
            logger.warning("[NewsSync] bantz.skills.news_briefing not available")
            return []

        provider = RSSNewsProvider()
        target_categories = (
            [category] if category
            else (self._categories or list(NEWS_CATEGORIES.keys()))
        )

        articles: List[Dict[str, Any]] = []

        for cat_name in target_categories:
            cat_def = NEWS_CATEGORIES.get(cat_name)
            if cat_def is None:
                logger.warning("[NewsSync] Unknown category: %s", cat_name)
                continue

            try:
                items = provider.fetch(cat_def)
                for item in items[:self._max_items]:
                    articles.append({
                        "title": item.title,
                        "url": item.url,
                        "source": item.source,
                        "published": item.published or "",
                        "summary": getattr(item, "summary", "") or "",
                        "_category": cat_name,
                        "_feed_url": getattr(item, "feed_url", ""),
                    })
            except Exception as e:
                logger.warning("[NewsSync] Failed to fetch category %s: %s", cat_name, e)

        return articles

    def _ingest_article(self, article: Dict[str, Any]) -> Optional[str]:
        """Ingest a single news article into the store."""
        category = article.get("_category", "general")
        title = article.get("title", "")
        url = article.get("url", "")
        source = article.get("source", "")
        published = article.get("published", "")

        content = {
            "title": title,
            "url": url,
            "source": source,
            "published": published,
            "summary": article.get("summary", ""),
            "category": category,
        }

        meta = {
            "category": category,
            "source_feed": article.get("_feed_url", ""),
            "published": published,
            "sync_source": "news_sync",
        }

        display_summary = f"📰 [{category}] {source}: {title}"

        try:
            return self._store.ingest(
                content=content,
                source=_INGEST_SOURCE,
                data_class=DataClass.EPHEMERAL,
                summary=display_summary,
                meta=meta,
            )
        except Exception as e:
            logger.warning("[NewsSync] Failed to ingest article '%s': %s", title[:50], e)
            return None
