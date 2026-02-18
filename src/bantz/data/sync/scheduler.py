"""
Unified sync scheduler — orchestrates all data synchronization tasks.

Manages lifecycle of Gmail, Calendar, and News syncers as a single
cohesive unit.  Provides health checks, stats aggregation, and
graceful shutdown.

Usage::

    from bantz.data import IngestStore
    from bantz.data.sync import SyncScheduler

    store = IngestStore()
    scheduler = SyncScheduler(store)
    await scheduler.start()     # starts all syncers
    stats = scheduler.stats     # aggregated stats
    await scheduler.stop()      # graceful shutdown

The scheduler is intended to be started once at boot via the daemon
or orchestrator initialization.

Environment config::

    BANTZ_SYNC_GMAIL_INTERVAL=300       # 5 min (default)
    BANTZ_SYNC_CALENDAR_INTERVAL=180    # 3 min (default)
    BANTZ_SYNC_NEWS_INTERVAL=1800       # 30 min (default)
    BANTZ_SYNC_ENABLED=true             # master switch
    BANTZ_SYNC_GMAIL=true               # per-source toggle
    BANTZ_SYNC_CALENDAR=true
    BANTZ_SYNC_NEWS=true
    BANTZ_SYNC_BOOT_STAGGER=5          # seconds between syncer starts
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from bantz.data.ingest_store import IngestStore
from bantz.data.sync.calendar_sync import CalendarSyncer
from bantz.data.sync.gmail_sync import GmailSyncer
from bantz.data.sync.news_sync import NewsSyncer

logger = logging.getLogger(__name__)


def _env_bool(key: str, default: bool = True) -> bool:
    """Read a boolean environment variable."""
    val = os.getenv(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    """Read an integer environment variable."""
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


class SyncScheduler:
    """Orchestrates all data synchronization tasks.

    Parameters
    ----------
    store : IngestStore
        Shared ingest store for all syncers.
    gmail_interval : int, optional
        Override Gmail sync interval (seconds).
    calendar_interval : int, optional
        Override Calendar sync interval (seconds).
    news_interval : int, optional
        Override News sync interval (seconds).
    """

    def __init__(
        self,
        store: IngestStore,
        *,
        gmail_interval: Optional[int] = None,
        calendar_interval: Optional[int] = None,
        news_interval: Optional[int] = None,
        boot_stagger: Optional[int] = None,
    ) -> None:
        self._store = store
        self._started = False
        self._start_time: float = 0.0

        # Stagger delay between syncer starts at boot (Issue #1371)
        self._boot_stagger = boot_stagger if boot_stagger is not None else _env_int(
            "BANTZ_SYNC_BOOT_STAGGER", 5,
        )

        # Read config from env with overrides
        self._enable_gmail = _env_bool("BANTZ_SYNC_GMAIL")
        self._enable_calendar = _env_bool("BANTZ_SYNC_CALENDAR")
        self._enable_news = _env_bool("BANTZ_SYNC_NEWS")
        master = _env_bool("BANTZ_SYNC_ENABLED")
        if not master:
            self._enable_gmail = False
            self._enable_calendar = False
            self._enable_news = False

        g_interval = gmail_interval or _env_int("BANTZ_SYNC_GMAIL_INTERVAL", 300)
        c_interval = calendar_interval or _env_int("BANTZ_SYNC_CALENDAR_INTERVAL", 180)
        n_interval = news_interval or _env_int("BANTZ_SYNC_NEWS_INTERVAL", 1800)

        # Create syncers (they don't start until start() is called)
        self._gmail_syncer: Optional[GmailSyncer] = None
        self._calendar_syncer: Optional[CalendarSyncer] = None
        self._news_syncer: Optional[NewsSyncer] = None

        if self._enable_gmail:
            self._gmail_syncer = GmailSyncer(
                store, sync_interval=g_interval,
            )
        if self._enable_calendar:
            self._calendar_syncer = CalendarSyncer(
                store, sync_interval=c_interval,
            )
        if self._enable_news:
            self._news_syncer = NewsSyncer(
                store, sync_interval=n_interval,
            )

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> Dict[str, Any]:
        """Start all enabled syncers.  Returns a summary of what started.

        Syncers are started with a staggered delay (default 5s) between
        each source to avoid burst API traffic at boot (Issue #1371).
        """
        if self._started:
            logger.warning("[SyncScheduler] Already started.")
            return {"ok": False, "reason": "already_started"}

        self._started = True
        self._start_time = time.time()
        started: list[str] = []
        stagger = self._boot_stagger

        # Run initial sync for all sources, then start periodic
        # Stagger between sources to spread boot load
        if self._gmail_syncer:
            try:
                await self._gmail_syncer.sync()
                await self._gmail_syncer.start_periodic()
                started.append("gmail")
            except Exception as e:
                logger.error("[SyncScheduler] Gmail syncer failed to start: %s", e)

        if self._calendar_syncer:
            if stagger > 0 and started:
                logger.debug(
                    "[SyncScheduler] Stagger delay %ds before calendar sync",
                    stagger,
                )
                await asyncio.sleep(stagger)
            try:
                await self._calendar_syncer.sync()
                await self._calendar_syncer.start_periodic()
                started.append("calendar")
            except Exception as e:
                logger.error("[SyncScheduler] Calendar syncer failed to start: %s", e)

        if self._news_syncer:
            if stagger > 0 and started:
                logger.debug(
                    "[SyncScheduler] Stagger delay %ds before news sync",
                    stagger,
                )
                await asyncio.sleep(stagger)
            try:
                await self._news_syncer.sync()
                await self._news_syncer.start_periodic()
                started.append("news")
            except Exception as e:
                logger.error("[SyncScheduler] News syncer failed to start: %s", e)

        logger.info("[SyncScheduler] Started syncers: %s", started)
        return {"ok": True, "started": started}

    async def stop(self) -> None:
        """Gracefully stop all syncers."""
        tasks = []
        if self._gmail_syncer:
            tasks.append(self._gmail_syncer.stop())
        if self._calendar_syncer:
            tasks.append(self._calendar_syncer.stop())
        if self._news_syncer:
            tasks.append(self._news_syncer.stop())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._started = False
        logger.info("[SyncScheduler] All syncers stopped.")

    # ── Manual sync ───────────────────────────────────────────

    async def sync_now(self, source: Optional[str] = None) -> Dict[str, Any]:
        """Trigger an immediate sync for a specific source or all.

        Parameters
        ----------
        source : str, optional
            One of 'gmail', 'calendar', 'news'.
            If None, syncs all enabled sources.
        """
        results: Dict[str, Any] = {}

        if source is None or source == "gmail":
            if self._gmail_syncer:
                results["gmail"] = await self._gmail_syncer.sync()

        if source is None or source == "calendar":
            if self._calendar_syncer:
                results["calendar"] = await self._calendar_syncer.sync()

        if source is None or source == "news":
            if self._news_syncer:
                results["news"] = await self._news_syncer.sync()

        return results

    # ── Stats & health ────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Aggregated stats from all syncers."""
        result: Dict[str, Any] = {
            "is_running": self._started,
            "uptime_seconds": int(time.time() - self._start_time) if self._started else 0,
        }

        if self._gmail_syncer:
            result["gmail"] = self._gmail_syncer.stats
        if self._calendar_syncer:
            result["calendar"] = self._calendar_syncer.stats
        if self._news_syncer:
            result["news"] = self._news_syncer.stats

        # Ingest store stats
        try:
            result["store"] = self._store.stats()
        except Exception:
            result["store"] = {"error": "unavailable"}

        return result

    @property
    def is_healthy(self) -> bool:
        """Simple health check — at least one syncer is running."""
        if not self._started:
            return False
        healthy = False
        if self._gmail_syncer and self._gmail_syncer.stats.get("is_running"):
            healthy = True
        if self._calendar_syncer and self._calendar_syncer.stats.get("is_running"):
            healthy = True
        if self._news_syncer and self._news_syncer.stats.get("is_running"):
            healthy = True
        return healthy

    @property
    def store(self) -> IngestStore:
        """Direct access to the shared store."""
        return self._store
