"""Google Data Sync → SQLite IngestStore.

Pulls Gmail messages, Calendar events, and Classroom data from Google
APIs and stores them locally in the IngestStore (SQLite WAL).  This
gives the orchestrator fast, offline-capable access to the user's data
without hitting Google APIs on every turn.

Issue #1450: Gmail/Calendar/Classroom → SQLite ingestion pipeline.
Issue #1451: Unified contact classification via sender name.
Issue #1452: Calendar events used as context in LLM turns.

Usage::

    from bantz.data.google_sync import GoogleSyncManager
    manager = GoogleSyncManager()
    await manager.sync_all()          # full sync
    await manager.sync_gmail()        # gmail only
    await manager.sync_calendar()     # calendar only

Sync schedule (recommended):
    - On startup: full sync (gmail + calendar)
    - Every 5 minutes: calendar events (time-sensitive)
    - Every 15 minutes: gmail (new messages)
    - On demand: triggered by orchestrator tool results
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_data_class(name: str) -> Any:
    """Lazy-import DataClass enum to avoid hard dependency at import time."""
    from bantz.data.ingest_store import DataClass
    return DataClass[name]


# ══════════════════════════════════════════════════════════════════
# Gmail Sync
# ══════════════════════════════════════════════════════════════════

class GmailSyncer:
    """Pulls recent Gmail messages into IngestStore."""

    SOURCE = "gmail"

    def __init__(self, store: Any) -> None:
        self._store = store

    async def sync(self, max_messages: int = 30) -> int:
        """Fetch recent messages and ingest into SQLite.

        Args:
            max_messages: Maximum number of messages to sync per run.

        Returns:
            Number of new records ingested (0 if all already cached).
        """
        try:
            messages = await asyncio.to_thread(self._fetch_messages, max_messages)
        except Exception as exc:
            logger.warning("[GmailSync] Failed to fetch messages: %s", exc)
            return 0

        ingested = 0
        for msg in messages:
            try:
                record_id = self._store.ingest(
                    content=msg,
                    source=self.SOURCE,
                    data_class=_get_data_class("EPHEMERAL"),
                    summary=msg.get("subject") or msg.get("title") or "",
                )
                if record_id:
                    ingested += 1
            except Exception as exc:
                logger.debug("[GmailSync] Ingest failed for msg %s: %s", msg.get("id"), exc)

        logger.info("[GmailSync] Synced %d/%d messages into SQLite", ingested, len(messages))

        # ── Index sender names as PERSISTENT contacts ─────────────
        await self._index_senders(messages)

        return ingested

    def _fetch_messages(self, max_messages: int) -> List[Dict[str, Any]]:
        """Synchronous Gmail API fetch (runs in thread pool)."""
        try:
            from bantz.google.gmail import GmailClient
        except ImportError:
            logger.warning("[GmailSync] GmailClient not available — skipping")
            return []

        try:
            client = GmailClient()
            raw = client.list_messages(max_results=max_messages)
            return raw if isinstance(raw, list) else []
        except FileNotFoundError:
            logger.info("[GmailSync] No Gmail credentials found — skip sync")
            return []
        except Exception as exc:
            logger.warning("[GmailSync] list_messages error: %s", exc)
            return []

    def _build_tags(self, msg: Dict[str, Any]) -> List[str]:
        tags = ["gmail", "email"]
        labels = msg.get("labelIds", [])
        if "INBOX" in labels:
            tags.append("inbox")
        if "UNREAD" in labels:
            tags.append("unread")
        if "SENT" in labels:
            tags.append("sent")
        sender = msg.get("from", "") or msg.get("sender", "")
        if sender:
            # Short sender tag for classification
            name_part = sender.split("<")[0].strip().lower().replace(" ", "_")
            if name_part:
                tags.append(f"sender:{name_part[:40]}")
        return tags

    async def _index_senders(self, messages: List[Dict[str, Any]]) -> None:
        """Store unique sender names as PERSISTENT contact records for classification."""
        seen: Dict[str, str] = {}
        for msg in messages:
            sender_raw = msg.get("from", "") or msg.get("sender", "")
            if not sender_raw or sender_raw in seen:
                continue
            seen[sender_raw] = sender_raw

        for sender_raw in seen:
            try:
                payload = {"type": "contact", "raw": sender_raw}
                # Derive email and name
                if "<" in sender_raw and ">" in sender_raw:
                    name = sender_raw.split("<")[0].strip().strip('"')
                    email = sender_raw.split("<")[1].rstrip(">").strip()
                    payload["name"] = name
                    payload["email"] = email
                else:
                    payload["email"] = sender_raw
                self._store.ingest(
                    content=payload,
                    source="gmail_contact",
                    data_class=_get_data_class("PERSISTENT"),
                    summary=payload.get("name") or payload.get("email", ""),
                )
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
# Calendar Sync
# ══════════════════════════════════════════════════════════════════

class CalendarSyncer:
    """Pulls Calendar events into IngestStore."""

    SOURCE = "google_calendar"

    def __init__(self, store: Any) -> None:
        self._store = store

    async def sync(self, days_ahead: int = 14) -> int:
        """Fetch upcoming events and ingest into SQLite.

        Args:
            days_ahead: How many days into the future to pull events for.

        Returns:
            Number of new records ingested.
        """
        try:
            events = await asyncio.to_thread(self._fetch_events, days_ahead)
        except Exception as exc:
            logger.warning("[CalendarSync] Failed to fetch events: %s", exc)
            return 0

        ingested = 0
        for event in events:
            try:
                # Calendar events are ephemeral (they change frequently)
                record_id = self._store.ingest(
                    content=event,
                    source=self.SOURCE,
                    data_class=_get_data_class("EPHEMERAL"),
                    summary=event.get("summary") or event.get("title") or "",
                )
                if record_id:
                    ingested += 1
            except Exception as exc:
                logger.debug("[CalendarSync] Ingest failed for event %s: %s", event.get("id"), exc)

        logger.info("[CalendarSync] Synced %d/%d events into SQLite", ingested, len(events))
        return ingested

    def _fetch_events(self, days_ahead: int) -> List[Dict[str, Any]]:
        """Synchronous Calendar API fetch (runs in thread pool)."""
        try:
            from bantz.google.calendar import GoogleCalendar
        except ImportError:
            logger.warning("[CalendarSync] GoogleCalendar not available — skipping")
            return []

        try:
            cal = GoogleCalendar()
            now_utc = datetime.now(timezone.utc)
            end_utc = now_utc + timedelta(days=days_ahead)

            raw = cal.list_events(
                time_min=now_utc.isoformat(),
                time_max=end_utc.isoformat(),
                max_results=100,
                single_events=True,
                order_by="startTime",
            )
            if isinstance(raw, dict):
                return raw.get("items", [])
            if isinstance(raw, list):
                return raw
            return []
        except FileNotFoundError:
            logger.info("[CalendarSync] No Calendar credentials found — skip sync")
            return []
        except Exception as exc:
            logger.warning("[CalendarSync] list_events error: %s", exc)
            return []

    def _build_tags(self, event: Dict[str, Any]) -> List[str]:
        tags = ["calendar", "event"]
        status = event.get("status", "")
        if status == "confirmed":
            tags.append("confirmed")
        elif status == "tentative":
            tags.append("tentative")
        # All-day vs timed
        start = event.get("start", {})
        if "date" in start and "dateTime" not in start:
            tags.append("all_day")
        # Time-sensitive: within 24h
        try:
            dt_raw = start.get("dateTime") or start.get("date")
            if dt_raw:
                dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if dt - now <= timedelta(hours=24):
                    tags.append("imminent")
        except Exception:
            pass
        return tags


# ══════════════════════════════════════════════════════════════════
# Classroom Sync
# ══════════════════════════════════════════════════════════════════

class ClassroomSyncer:
    """Pulls Google Classroom courses and assignments into IngestStore."""

    SOURCE = "google_classroom"

    def __init__(self, store: Any) -> None:
        self._store = store

    async def sync(self) -> int:
        """Fetch active courses and their assignments."""
        try:
            data = await asyncio.to_thread(self._fetch_courses)
        except Exception as exc:
            logger.warning("[ClassroomSync] Failed: %s", exc)
            return 0

        ingested = 0
        for record in data:
            try:
                tags = record.pop("_tags", ["classroom"])
                # Persist record type in content so query filters can distinguish
                # courses from assignments without relying on the popped _tags.
                if "record_type" not in record:
                    if "assignment" in tags:
                        record["record_type"] = "assignment"
                    elif "course" in tags:
                        record["record_type"] = "course"
                name = record.get("name") or record.get("title") or ""
                rid = self._store.ingest(
                    content=record,
                    source=self.SOURCE,
                    data_class=_get_data_class("SESSION"),
                    summary=name,
                )
                if rid:
                    ingested += 1
            except Exception:
                pass
        logger.info("[ClassroomSync] Synced %d Classroom records", ingested)
        return ingested

    def _fetch_courses(self) -> List[Dict[str, Any]]:
        try:
            from bantz.google.classroom import ClassroomConnector
        except ImportError:
            return []

        try:
            connector = ClassroomConnector()
            courses = connector.list_courses()
            records = []
            for course in (courses or []):
                d = course.to_dict() if hasattr(course, "to_dict") else dict(course)
                d["_tags"] = ["classroom", "course"]
                records.append(d)

                # Also fetch assignments for active courses
                if d.get("state") == "ACTIVE":
                    try:
                        assignments = connector.list_assignments(d["id"])
                        for assignment in (assignments or []):
                            ad = assignment.to_dict() if hasattr(assignment, "to_dict") else dict(assignment)
                            ad["_tags"] = ["classroom", "assignment", f"course:{d.get('name','')[:30]}"]
                            ad["course_name"] = d.get("name", "")
                            records.append(ad)
                    except Exception:
                        pass
            return records
        except FileNotFoundError:
            logger.info("[ClassroomSync] No Classroom credentials — skip")
            return []
        except Exception as exc:
            logger.warning("[ClassroomSync] fetch error: %s", exc)
            return []


# ══════════════════════════════════════════════════════════════════
# Unified Sync Manager
# ══════════════════════════════════════════════════════════════════

class GoogleSyncManager:
    """Orchestrates Google data sync into the local SQLite IngestStore.

    Designed to be called:
    - Once on startup (full sync)
    - Periodically via asyncio background task (partial syncs)
    - On demand when user asks about email/calendar/classroom

    Usage::

        manager = GoogleSyncManager()          # uses default IngestStore
        await manager.sync_all()

    Or inject a specific IngestStore::

        manager = GoogleSyncManager(store=my_store)
    """

    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._gmail_syncer: Optional[GmailSyncer] = None
        self._cal_syncer: Optional[CalendarSyncer] = None
        self._classroom_syncer: Optional[ClassroomSyncer] = None
        self._last_sync: Dict[str, float] = {}

    def _get_store(self) -> Any:
        if self._store is not None:
            return self._store
        # Lazy-create default IngestStore
        try:
            from bantz.data.ingest_store import IngestStore
            self._store = IngestStore()
            return self._store
        except Exception as exc:
            logger.error("[GoogleSync] Cannot open IngestStore: %s", exc)
            return None

    def _ensure_syncers(self) -> None:
        store = self._get_store()
        if store is None:
            return
        if self._gmail_syncer is None:
            self._gmail_syncer = GmailSyncer(store)
        if self._cal_syncer is None:
            self._cal_syncer = CalendarSyncer(store)
        if self._classroom_syncer is None:
            self._classroom_syncer = ClassroomSyncer(store)

    async def sync_gmail(self, max_messages: int = 30) -> int:
        """Sync Gmail messages. Returns ingested count."""
        self._ensure_syncers()
        if self._gmail_syncer is None:
            return 0
        count = await self._gmail_syncer.sync(max_messages=max_messages)
        self._last_sync["gmail"] = time.time()
        return count

    async def sync_calendar(self, days_ahead: int = 14) -> int:
        """Sync Calendar events. Returns ingested count."""
        self._ensure_syncers()
        if self._cal_syncer is None:
            return 0
        count = await self._cal_syncer.sync(days_ahead=days_ahead)
        self._last_sync["calendar"] = time.time()
        return count

    async def sync_classroom(self) -> int:
        """Sync Classroom courses & assignments. Returns ingested count."""
        self._ensure_syncers()
        if self._classroom_syncer is None:
            return 0
        count = await self._classroom_syncer.sync()
        self._last_sync["classroom"] = time.time()
        return count

    async def sync_all(self) -> Dict[str, int]:
        """Run all syncs in parallel. Returns dict of source → count."""
        results = await asyncio.gather(
            self.sync_gmail(),
            self.sync_calendar(),
            self.sync_classroom(),
            return_exceptions=True,
        )

        gmail_count = results[0] if isinstance(results[0], int) else 0
        cal_count   = results[1] if isinstance(results[1], int) else 0
        class_count = results[2] if isinstance(results[2], int) else 0

        summary = {
            "gmail": gmail_count,
            "calendar": cal_count,
            "classroom": class_count,
            "total": gmail_count + cal_count + class_count,
        }
        logger.info("[GoogleSync] Sync complete: %s", summary)
        return summary

    def should_sync(self, source: str, interval_seconds: int = 900) -> bool:
        """Returns True if source hasn't been synced recently."""
        last = self._last_sync.get(source, 0)
        return (time.time() - last) > interval_seconds

    async def start_background_sync(
        self,
        *,
        gmail_interval: int = 900,    # 15 min
        calendar_interval: int = 300, # 5 min
        classroom_interval: int = 3600,
    ) -> None:
        """Start an asyncio background task that syncs periodically.

        Should be called once after the event loop is running.
        Does NOT block — schedules a task and returns immediately.
        """
        async def _loop() -> None:
            logger.info("[GoogleSync] Background sync task started")
            while True:
                try:
                    if self.should_sync("gmail", gmail_interval):
                        await self.sync_gmail()
                    if self.should_sync("calendar", calendar_interval):
                        await self.sync_calendar()
                    if self.should_sync("classroom", classroom_interval):
                        await self.sync_classroom()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("[GoogleSync] Background sync error: %s", exc)
                # Wake up every minute to check intervals
                await asyncio.sleep(60)

        asyncio.ensure_future(_loop())

    def query_recent_emails(
        self,
        *,
        limit: int = 10,
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Query recently synced Gmail messages from SQLite.

        Returns dicts sorted by ingest time (newest first).
        This lets the orchestrator read emails WITHOUT hitting Google API.
        """
        store = self._get_store()
        if store is None:
            return []
        try:
            from bantz.data.ingest_store import DataClass
            records = store.query(
                source="gmail",
                data_class=DataClass.EPHEMERAL,
                limit=limit,
            )
            payloads = [r.content if hasattr(r, "content") else (r.get("content") if isinstance(r, dict) else r) for r in records]
            if unread_only:
                payloads = [p for p in payloads if "UNREAD" in (p.get("labelIds") or [])]
            return payloads
        except Exception as exc:
            logger.warning("[GoogleSync] query_recent_emails failed: %s", exc)
            return []

    def query_upcoming_events(
        self,
        *,
        limit: int = 20,
        imminent_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Query upcoming calendar events from SQLite.

        Returns events sorted by start time (soonest first).
        """
        store = self._get_store()
        if store is None:
            return []
        try:
            from bantz.data.ingest_store import DataClass
            records = store.query(
                source="google_calendar",
                data_class=DataClass.EPHEMERAL,
                limit=limit,
            )
            payloads = [r.content if hasattr(r, "content") else (r.get("content") if isinstance(r, dict) else r) for r in records]
            # Filter imminent (within 24h)
            if imminent_only:
                now = datetime.now(timezone.utc)
                def _is_imminent(ev: Dict[str, Any]) -> bool:
                    try:
                        s = ev.get("start", {})
                        dt_raw = s.get("dateTime") or s.get("date")
                        if not dt_raw:
                            return False
                        dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                        return dt - now <= timedelta(hours=24) and dt > now
                    except Exception:
                        return False
                payloads = [p for p in payloads if _is_imminent(p)]
            # Sort by start time
            def _start_key(ev: Dict[str, Any]) -> str:
                s = ev.get("start", {})
                return s.get("dateTime") or s.get("date") or ""
            return sorted(payloads, key=_start_key)
        except Exception as exc:
            logger.warning("[GoogleSync] query_upcoming_events failed: %s", exc)
            return []

    def query_classroom(
        self,
        *,
        limit: int = 30,
        assignments_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Query Classroom data from SQLite."""
        store = self._get_store()
        if store is None:
            return []
        try:
            from bantz.data.ingest_store import DataClass
            records = store.query(
                source="google_classroom",
                data_class=DataClass.SESSION,
                limit=limit,
            )
            payloads = [r.content if hasattr(r, "content") else (r.get("content") if isinstance(r, dict) else r) for r in records]
            if assignments_only:
                payloads = [p for p in payloads if p.get("record_type") == "assignment"]
            return payloads
        except Exception as exc:
            logger.warning("[GoogleSync] query_classroom failed: %s", exc)
            return []

    def close(self) -> None:
        """Close the underlying IngestStore if we own it."""
        if self._store is not None:
            try:
                self._store.close()
            except Exception:
                pass
            self._store = None


# ── Module-level singleton (lazy) ─────────────────────────────────

_default_manager: Optional[GoogleSyncManager] = None


def get_default_manager() -> GoogleSyncManager:
    """Return the process-wide GoogleSyncManager (created on first call)."""
    global _default_manager
    if _default_manager is None:
        _default_manager = GoogleSyncManager()
    return _default_manager
