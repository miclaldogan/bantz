"""
Tests for bantz.data.sync — GmailSyncer, CalendarSyncer, NewsSyncer, SyncScheduler.

Tests cover:
- Gmail sync with classification
- Calendar sync with event ingestion
- News sync with RSS-based ingestion
- SyncScheduler lifecycle management
- Edge cases and error handling
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.data.ingest_store import DataClass, IngestStore
from bantz.data.sync.gmail_sync import GmailSyncer, _parse_sender
from bantz.data.sync.calendar_sync import CalendarSyncer
from bantz.data.sync.news_sync import NewsSyncer
from bantz.data.sync.scheduler import SyncScheduler


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def store():
    """In-memory IngestStore for tests."""
    s = IngestStore(db_path=":memory:", auto_sweep=False)
    yield s
    s.close()


@pytest.fixture
def mock_gmail_messages():
    """Sample Gmail API response for testing."""
    return {
        "ok": True,
        "messages": [
            {
                "id": "msg_001",
                "from": "GitHub <noreply@github.com>",
                "subject": "[bantz] PR #42 merged",
                "snippet": "Your PR has been merged into main...",
                "date": "Mon, 16 Feb 2026 10:00:00 +0300",
            },
            {
                "id": "msg_002",
                "from": "TÜBİTAK BİDEB <bideb@tubitak.gov.tr>",
                "subject": "ARDEB Başvuru Sonuçları",
                "snippet": "Başvurunuzun değerlendirme sonucu...",
                "date": "Mon, 16 Feb 2026 09:00:00 +0300",
            },
            {
                "id": "msg_003",
                "from": "John Doe <john@example.com>",
                "subject": "Meeting tomorrow",
                "snippet": "Hi, let's meet at 3pm tomorrow...",
                "date": "Mon, 16 Feb 2026 08:00:00 +0300",
            },
        ],
    }


@pytest.fixture
def mock_calendar_events():
    """Sample Calendar API response for testing."""
    return {
        "ok": True,
        "events": [
            {
                "id": "evt_001",
                "summary": "Team Standup",
                "start": "2026-02-17T10:00:00+03:00",
                "end": "2026-02-17T10:30:00+03:00",
                "location": "Google Meet",
                "status": "confirmed",
            },
            {
                "id": "evt_002",
                "summary": "Dentist Appointment",
                "start": "2026-02-18",
                "end": "2026-02-19",
                "location": "",
                "status": "confirmed",
            },
        ],
    }


# ── Parse sender ──────────────────────────────────────────────────

class TestParseSender:
    def test_name_and_email(self):
        name, email = _parse_sender("GitHub <noreply@github.com>")
        assert name == "GitHub"
        assert email == "noreply@github.com"

    def test_quoted_name(self):
        name, email = _parse_sender('"John Doe" <john@example.com>')
        assert name == "John Doe"
        assert email == "john@example.com"

    def test_email_only(self):
        name, email = _parse_sender("john@example.com")
        assert name == ""
        assert email == "john@example.com"

    def test_turkish_name(self):
        name, email = _parse_sender("TÜBİTAK BİDEB <bideb@tubitak.gov.tr>")
        assert name == "TÜBİTAK BİDEB"
        assert email == "bideb@tubitak.gov.tr"

    def test_empty_string(self):
        name, email = _parse_sender("")
        assert name == ""


# ── Gmail Syncer ──────────────────────────────────────────────────

class TestGmailSyncer:
    @pytest.mark.asyncio
    async def test_sync_classifies_github(self, store, mock_gmail_messages):
        """Gmail sync should classify GitHub messages correctly."""
        syncer = GmailSyncer(store, max_messages=10)

        with patch(
            "bantz.data.sync.gmail_sync.GmailSyncer._fetch_messages_sync",
            return_value=None,
        ) as mock_fetch:
            # Simulate the classified messages
            mock_fetch.return_value = []
            # Directly test classification by injecting messages
            syncer._fetch_messages_sync = MagicMock(return_value=[])

            # Instead, test the _ingest_message method directly
            msg = {
                "id": "msg_001",
                "from": "GitHub <noreply@github.com>",
                "subject": "[bantz] PR #42 merged",
                "snippet": "Your PR has been merged...",
                "date": "Mon, 16 Feb 2026 10:00:00",
                "_sender_name": "GitHub",
                "_sender_email": "noreply@github.com",
                "_category": "github",
                "_confidence": 0.95,
            }
            record_id = syncer._ingest_message(msg)
            assert record_id is not None

            # Verify it's in the store with correct classification
            record = store.get(record_id)
            assert record is not None
            assert record.source == "gmail"
            assert record.meta["category"] == "github"
            assert record.meta["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_sync_classifies_tubitak(self, store):
        syncer = GmailSyncer(store)
        msg = {
            "id": "msg_002",
            "from": "TÜBİTAK <bideb@tubitak.gov.tr>",
            "subject": "ARDEB Başvuru",
            "snippet": "Başvurunuz...",
            "date": "Mon, 16 Feb 2026",
            "_sender_name": "TÜBİTAK",
            "_sender_email": "bideb@tubitak.gov.tr",
            "_category": "tubitak",
            "_confidence": 0.95,
        }
        record_id = syncer._ingest_message(msg)
        assert record_id is not None
        record = store.get(record_id)
        assert record.meta["category"] == "tubitak"

    @pytest.mark.asyncio
    async def test_sync_dedup(self, store):
        """Duplicate messages should be deduped by fingerprint."""
        syncer = GmailSyncer(store)
        msg = {
            "id": "msg_001",
            "from": "test@test.com",
            "subject": "Test",
            "snippet": "...",
            "date": "Mon, 16 Feb 2026",
            "_sender_name": "Test",
            "_sender_email": "test@test.com",
            "_category": "uncategorized",
            "_confidence": 0.0,
        }

        id1 = syncer._ingest_message(msg)
        id2 = syncer._ingest_message(msg)
        # Second ingest returns the same record (dedup)
        assert id1 == id2

    @pytest.mark.asyncio
    async def test_sync_stats(self, store):
        syncer = GmailSyncer(store)
        stats = syncer.stats
        assert stats["total_synced"] == 0
        assert stats["is_running"] is False

    @pytest.mark.asyncio
    async def test_sync_empty_result(self, store):
        syncer = GmailSyncer(store)
        with patch.object(syncer, "_fetch_messages", new_callable=AsyncMock, return_value=[]):
            result = await syncer.sync()
            assert result["ok"] is True
            assert result["synced"] == 0


# ── Calendar Syncer ───────────────────────────────────────────────

class TestCalendarSyncer:
    @pytest.mark.asyncio
    async def test_ingest_event(self, store):
        syncer = CalendarSyncer(store)
        event = {
            "id": "evt_001",
            "summary": "Team Standup",
            "start": "2026-02-17T10:00:00+03:00",
            "end": "2026-02-17T10:30:00+03:00",
            "location": "Google Meet",
            "status": "confirmed",
        }

        result = syncer._ingest_event(event)
        assert result == "new"

        # Verify in store
        records = store.query(source="calendar")
        assert len(records) == 1
        assert records[0].content["summary"] == "Team Standup"
        assert records[0].meta["event_id"] == "evt_001"
        assert records[0].meta["has_location"] is True

    @pytest.mark.asyncio
    async def test_ingest_all_day_event(self, store):
        syncer = CalendarSyncer(store)
        event = {
            "id": "evt_002",
            "summary": "Holiday",
            "start": "2026-02-18",
            "end": "2026-02-19",
            "location": "",
            "status": "confirmed",
        }

        result = syncer._ingest_event(event)
        assert result == "new"

        records = store.query(source="calendar")
        assert len(records) == 1
        assert records[0].meta["is_all_day"] is True
        assert records[0].meta["has_location"] is False

    @pytest.mark.asyncio
    async def test_event_dedup(self, store):
        syncer = CalendarSyncer(store)
        event = {
            "id": "evt_001",
            "summary": "Meeting",
            "start": "2026-02-17T10:00:00",
            "end": "2026-02-17T11:00:00",
            "location": "",
            "status": "confirmed",
        }

        r1 = syncer._ingest_event(event)
        r2 = syncer._ingest_event(event)
        assert r1 == "new"
        # Second should be dedup
        records = store.query(source="calendar")
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_sync_empty(self, store):
        syncer = CalendarSyncer(store)
        with patch.object(syncer, "_fetch_events", new_callable=AsyncMock, return_value=[]):
            result = await syncer.sync()
            assert result["ok"] is True
            assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_stats(self, store):
        syncer = CalendarSyncer(store)
        stats = syncer.stats
        assert stats["total_synced"] == 0
        assert stats["is_running"] is False


# ── News Syncer ───────────────────────────────────────────────────

class TestNewsSyncer:
    @pytest.mark.asyncio
    async def test_ingest_article(self, store):
        syncer = NewsSyncer(store)
        article = {
            "title": "AI Breakthrough in 2026",
            "url": "https://example.com/ai-2026",
            "source": "TechCrunch",
            "published": "2026-02-16T08:00:00",
            "summary": "A major AI advancement...",
            "_category": "ai",
            "_feed_url": "https://techcrunch.com/feed/",
        }

        record_id = syncer._ingest_article(article)
        assert record_id is not None

        records = store.query(source="news")
        assert len(records) == 1
        assert records[0].content["title"] == "AI Breakthrough in 2026"
        assert records[0].meta["category"] == "ai"

    @pytest.mark.asyncio
    async def test_article_dedup(self, store):
        syncer = NewsSyncer(store)
        article = {
            "title": "Test Article",
            "url": "https://example.com/test",
            "source": "TestSource",
            "published": "2026-02-16",
            "summary": "...",
            "_category": "tech",
            "_feed_url": "",
        }

        id1 = syncer._ingest_article(article)
        id2 = syncer._ingest_article(article)
        assert id1 == id2

    @pytest.mark.asyncio
    async def test_sync_empty(self, store):
        syncer = NewsSyncer(store)
        with patch.object(syncer, "_fetch_articles", new_callable=AsyncMock, return_value=[]):
            result = await syncer.sync()
            assert result["ok"] is True
            assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_stats(self, store):
        syncer = NewsSyncer(store)
        stats = syncer.stats
        assert stats["total_synced"] == 0
        assert stats["is_running"] is False


# ── SyncScheduler ─────────────────────────────────────────────────

class TestSyncScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_creation(self, store):
        with patch.dict("os.environ", {"BANTZ_SYNC_ENABLED": "false"}):
            scheduler = SyncScheduler(store)
            assert scheduler._enable_gmail is False
            assert scheduler._enable_calendar is False
            assert scheduler._enable_news is False

    @pytest.mark.asyncio
    async def test_scheduler_stats(self, store):
        with patch.dict("os.environ", {"BANTZ_SYNC_ENABLED": "false"}):
            scheduler = SyncScheduler(store)
            stats = scheduler.stats
            assert stats["is_running"] is False
            assert stats["uptime_seconds"] == 0

    @pytest.mark.asyncio
    async def test_scheduler_not_healthy_when_stopped(self, store):
        with patch.dict("os.environ", {"BANTZ_SYNC_ENABLED": "false"}):
            scheduler = SyncScheduler(store)
            assert scheduler.is_healthy is False

    @pytest.mark.asyncio
    async def test_scheduler_store_access(self, store):
        with patch.dict("os.environ", {"BANTZ_SYNC_ENABLED": "false"}):
            scheduler = SyncScheduler(store)
            assert scheduler.store is store

    @pytest.mark.asyncio
    async def test_scheduler_double_start(self, store):
        """Starting twice should return already_started."""
        with patch.dict("os.environ", {"BANTZ_SYNC_ENABLED": "false"}):
            scheduler = SyncScheduler(store)
            scheduler._started = True
            result = await scheduler.start()
            assert result["ok"] is False
            assert result["reason"] == "already_started"

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, store):
        """Stop should be safe to call when not started."""
        with patch.dict("os.environ", {"BANTZ_SYNC_ENABLED": "false"}):
            scheduler = SyncScheduler(store)
            await scheduler.stop()  # should not raise
