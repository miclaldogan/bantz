"""
Calendar synchronizer — pulls Google Calendar events into IngestStore.

Periodically fetches upcoming events and writes them into the IngestStore
so the agent can answer calendar questions from local data.

The sync covers a configurable time window (default: 7 days forward +
1 day back) and uses fingerprint dedup to avoid storing duplicates.

Usage::

    syncer = CalendarSyncer(store)
    await syncer.sync()           # one-shot
    await syncer.start_periodic() # background loop

Each ingested event gets metadata::

    meta = {
        "event_id": "abc123...",
        "calendar_id": "primary",
        "start": "2026-02-16T10:00:00+03:00",
        "end": "2026-02-16T11:00:00+03:00",
        "is_all_day": False,
        "is_recurring": False,
        "has_location": True,
        "status": "confirmed",
        "sync_source": "calendar_sync",
    }
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bantz.data.ingest_store import DataClass, IngestStore

logger = logging.getLogger(__name__)

# Sync config defaults
_DEFAULT_SYNC_INTERVAL = 180       # 3 minutes
_DEFAULT_FORWARD_DAYS = 7          # sync 7 days forward
_DEFAULT_BACKWARD_DAYS = 1         # sync 1 day back
_DEFAULT_MAX_EVENTS = 100
_INGEST_SOURCE = "calendar"


class CalendarSyncer:
    """Incremental Google Calendar → IngestStore synchronizer.

    Parameters
    ----------
    store : IngestStore
        Target ingest store.
    sync_interval : int
        Seconds between periodic syncs.
    forward_days : int
        How many days forward to sync.
    backward_days : int
        How many days backward to sync.
    max_events : int
        Max events to fetch per sync pass.
    calendar_id : str
        Google Calendar ID.  Defaults to 'primary'.
    """

    def __init__(
        self,
        store: IngestStore,
        *,
        sync_interval: int = _DEFAULT_SYNC_INTERVAL,
        forward_days: int = _DEFAULT_FORWARD_DAYS,
        backward_days: int = _DEFAULT_BACKWARD_DAYS,
        max_events: int = _DEFAULT_MAX_EVENTS,
        calendar_id: str = "primary",
    ) -> None:
        self._store = store
        self._sync_interval = sync_interval
        self._forward_days = forward_days
        self._backward_days = backward_days
        self._max_events = max_events
        self._calendar_id = calendar_id
        self._last_sync: float = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

        # Stats
        self._total_synced = 0

    # ── Public API ────────────────────────────────────────────

    async def sync(self) -> Dict[str, Any]:
        """Run a single sync pass.  Returns stats dict."""
        logger.info("[CalendarSync] Starting sync pass...")
        start = time.time()

        try:
            events = await self._fetch_events()
            if not events:
                logger.info("[CalendarSync] No events to sync.")
                return {"ok": True, "synced": 0, "elapsed_ms": 0}

            ingested = 0
            updated = 0

            for event in events:
                result = self._ingest_event(event)
                if result == "new":
                    ingested += 1
                elif result == "dedup":
                    updated += 1

            elapsed_ms = int((time.time() - start) * 1000)
            self._last_sync = time.time()
            self._total_synced += ingested

            logger.info(
                "[CalendarSync] Synced %d new + %d dedup events in %dms",
                ingested, updated, elapsed_ms,
            )
            return {
                "ok": True,
                "synced": ingested,
                "dedup": updated,
                "total_fetched": len(events),
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.error("[CalendarSync] Sync failed: %s", e, exc_info=True)
            return {"ok": False, "error": str(e), "synced": 0}

    async def start_periodic(self) -> None:
        """Start periodic background sync."""
        if self._running:
            logger.warning("[CalendarSync] Already running.")
            return
        self._running = True
        self._task = asyncio.create_task(self._periodic_loop())
        logger.info(
            "[CalendarSync] Periodic sync started (interval=%ds, window=-%dd/+%dd)",
            self._sync_interval, self._backward_days, self._forward_days,
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
        logger.info("[CalendarSync] Stopped.")

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cumulative sync stats."""
        return {
            "total_synced": self._total_synced,
            "last_sync": self._last_sync,
            "is_running": self._running,
            "window": f"-{self._backward_days}d/+{self._forward_days}d",
        }

    # ── Private helpers ───────────────────────────────────────

    async def _periodic_loop(self) -> None:
        """Background loop: sync → sleep → repeat."""
        while self._running:
            try:
                await self.sync()
            except Exception as e:
                logger.error("[CalendarSync] Periodic sync error: %s", e)
            await asyncio.sleep(self._sync_interval)

    async def _fetch_events(self) -> List[Dict[str, Any]]:
        """Fetch events from Google Calendar API.

        Runs the blocking API call in an executor thread.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_events_sync)

    def _fetch_events_sync(self) -> List[Dict[str, Any]]:
        """Synchronous Google Calendar API fetch (runs in thread pool)."""
        try:
            from bantz.google.calendar import list_events
        except ImportError:
            logger.warning("[CalendarSync] bantz.google.calendar not available")
            return []

        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=self._backward_days)).isoformat()
        time_max = (now + timedelta(days=self._forward_days)).isoformat()

        result = list_events(
            calendar_id=self._calendar_id,
            max_results=self._max_events,
            time_min=time_min,
            time_max=time_max,
            interactive=False,
        )

        if not result.get("ok"):
            logger.warning("[CalendarSync] list_events failed: %s", result.get("error"))
            return []

        return result.get("events", [])

    def _ingest_event(self, event: Dict[str, Any]) -> str:
        """Ingest a single calendar event.  Returns 'new' or 'dedup'."""
        event_id = event.get("id", "")
        summary = event.get("summary", "(no title)")
        start = event.get("start", "")
        end = event.get("end", "")
        location = event.get("location", "")
        status = event.get("status", "confirmed")

        is_all_day = isinstance(start, str) and "T" not in start
        has_location = bool(location)

        content = {
            "event_id": event_id,
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "status": status,
            "html_link": event.get("htmlLink", ""),
        }

        meta = {
            "event_id": event_id,
            "calendar_id": self._calendar_id,
            "start": start,
            "end": end,
            "is_all_day": is_all_day,
            "has_location": has_location,
            "status": status,
            "sync_source": "calendar_sync",
        }

        display_summary = f"📅 {start}: {summary}"
        if location:
            display_summary += f" @ {location}"

        try:
            record_id = self._store.ingest(
                content=content,
                source=_INGEST_SOURCE,
                data_class=DataClass.EPHEMERAL,
                summary=display_summary,
                meta=meta,
            )
            # ingest() returns existing ID on dedup hit
            return "new" if record_id else "dedup"
        except Exception as e:
            logger.warning("[CalendarSync] Failed to ingest event %s: %s", event_id, e)
            return "dedup"
