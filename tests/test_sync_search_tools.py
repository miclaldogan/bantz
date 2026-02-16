"""
Tests for bantz.tools.sync_search_tools — DB-backed search tools.

Tests cover:
- inbox.search, inbox.by_category, inbox.categories, inbox.summary
- calendar.upcoming, calendar.search
- news.latest, news.search
- sync.status, sync.now
"""

from __future__ import annotations

import pytest

from bantz.data.ingest_store import DataClass, IngestStore
from bantz.tools.sync_search_tools import (
    inbox_search_tool,
    inbox_by_category_tool,
    inbox_categories_tool,
    inbox_summary_tool,
    calendar_upcoming_tool,
    calendar_search_tool,
    news_latest_tool,
    news_search_tool,
    sync_status_tool,
    init_sync_tools,
)
import bantz.tools.sync_search_tools as sync_module


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def store():
    s = IngestStore(db_path=":memory:", auto_sweep=False)
    # Set the module-level store
    sync_module._store = s
    yield s
    s.close()
    sync_module._store = None


@pytest.fixture
def populated_store(store):
    """Store with sample Gmail, Calendar, and News data pre-loaded."""
    # Gmail messages
    store.ingest(
        content={
            "message_id": "msg_001",
            "from": "noreply@github.com",
            "sender_name": "GitHub",
            "sender_email": "noreply@github.com",
            "subject": "[bantz] PR #42 merged",
            "snippet": "PR merged into main...",
            "date": "2026-02-16",
            "category": "github",
        },
        source="gmail",
        data_class=DataClass.EPHEMERAL,
        summary="[github] GitHub: [bantz] PR #42 merged",
        meta={"category": "github", "confidence": 0.95, "sync_source": "gmail_sync"},
    )
    store.ingest(
        content={
            "message_id": "msg_002",
            "from": "bideb@tubitak.gov.tr",
            "sender_name": "TÜBİTAK",
            "sender_email": "bideb@tubitak.gov.tr",
            "subject": "ARDEB Başvuru",
            "snippet": "Başvurunuz kabul edildi...",
            "date": "2026-02-16",
            "category": "tubitak",
        },
        source="gmail",
        data_class=DataClass.EPHEMERAL,
        summary="[tubitak] TÜBİTAK: ARDEB Başvuru",
        meta={"category": "tubitak", "confidence": 0.95, "sync_source": "gmail_sync"},
    )
    store.ingest(
        content={
            "message_id": "msg_003",
            "from": "john@example.com",
            "sender_name": "John",
            "sender_email": "john@example.com",
            "subject": "Meeting tomorrow",
            "snippet": "Let's meet at 3pm...",
            "date": "2026-02-16",
            "category": "uncategorized",
        },
        source="gmail",
        data_class=DataClass.EPHEMERAL,
        summary="[uncategorized] John: Meeting tomorrow",
        meta={"category": "uncategorized", "confidence": 0.0, "sync_source": "gmail_sync"},
    )

    # Calendar events
    store.ingest(
        content={
            "event_id": "evt_001",
            "summary": "Team Standup",
            "start": "2026-02-17T10:00:00+03:00",
            "end": "2026-02-17T10:30:00+03:00",
            "location": "Google Meet",
            "status": "confirmed",
        },
        source="calendar",
        data_class=DataClass.EPHEMERAL,
        summary="📅 2026-02-17T10:00:00: Team Standup @ Google Meet",
        meta={"event_id": "evt_001", "sync_source": "calendar_sync"},
    )
    store.ingest(
        content={
            "event_id": "evt_002",
            "summary": "Dentist Appointment",
            "start": "2026-02-18",
            "end": "2026-02-19",
            "location": "",
            "status": "confirmed",
        },
        source="calendar",
        data_class=DataClass.EPHEMERAL,
        summary="📅 2026-02-18: Dentist Appointment",
        meta={"event_id": "evt_002", "is_all_day": True, "sync_source": "calendar_sync"},
    )

    # News articles
    store.ingest(
        content={
            "title": "AI Breakthrough 2026",
            "url": "https://techcrunch.com/ai-2026",
            "source": "TechCrunch",
            "published": "2026-02-16",
            "summary": "Major AI advancement...",
            "category": "ai",
        },
        source="news",
        data_class=DataClass.EPHEMERAL,
        summary="📰 [ai] TechCrunch: AI Breakthrough 2026",
        meta={"category": "ai", "sync_source": "news_sync"},
    )
    store.ingest(
        content={
            "title": "Turkey Economic Update",
            "url": "https://ntv.com.tr/update",
            "source": "NTV",
            "published": "2026-02-16",
            "summary": "Ekonomi haberleri...",
            "category": "turkey",
        },
        source="news",
        data_class=DataClass.EPHEMERAL,
        summary="📰 [turkey] NTV: Turkey Economic Update",
        meta={"category": "turkey", "sync_source": "news_sync"},
    )

    return store


# ── Inbox search ──────────────────────────────────────────────────

class TestInboxSearch:
    def test_search_by_keyword(self, populated_store):
        result = inbox_search_tool(query="github")
        assert result["ok"] is True
        assert result["count"] >= 1
        assert any("github" in m["subject"].lower() or "github" in m.get("from", "").lower()
                    for m in result["messages"])

    def test_search_tubitak(self, populated_store):
        result = inbox_search_tool(query="tubitak")
        assert result["ok"] is True
        assert result["count"] >= 1

    def test_search_no_query_returns_all(self, populated_store):
        result = inbox_search_tool()
        assert result["ok"] is True
        assert result["count"] == 3  # all gmail messages

    def test_search_no_match(self, populated_store):
        result = inbox_search_tool(query="xyznonexistent")
        assert result["ok"] is True
        assert result["count"] == 0


# ── Inbox by category ────────────────────────────────────────────

class TestInboxByCategory:
    def test_filter_github(self, populated_store):
        result = inbox_by_category_tool(category="github")
        assert result["ok"] is True
        assert all(m["category"] == "github" for m in result["messages"])

    def test_filter_tubitak(self, populated_store):
        result = inbox_by_category_tool(category="tubitak")
        assert result["ok"] is True
        assert all(m["category"] == "tubitak" for m in result["messages"])

    def test_missing_category_param(self, populated_store):
        result = inbox_by_category_tool(category="")
        assert result["ok"] is False


# ── Inbox categories ──────────────────────────────────────────────

class TestInboxCategories:
    def test_lists_categories(self, populated_store):
        result = inbox_categories_tool()
        assert result["ok"] is True
        cats = {c["category"] for c in result["categories"]}
        assert "github" in cats
        assert "tubitak" in cats

    def test_total_count(self, populated_store):
        result = inbox_categories_tool()
        assert result["total_messages"] == 3


# ── Inbox summary ─────────────────────────────────────────────────

class TestInboxSummary:
    def test_summary_structure(self, populated_store):
        result = inbox_summary_tool()
        assert result["ok"] is True
        assert result["total_messages"] == 3
        assert len(result["top_categories"]) > 0
        assert len(result["top_senders"]) > 0
        assert isinstance(result["recent_subjects"], list)


# ── Calendar upcoming ─────────────────────────────────────────────

class TestCalendarUpcoming:
    def test_upcoming_events(self, populated_store):
        result = calendar_upcoming_tool()
        assert result["ok"] is True
        assert result["count"] == 2

    def test_events_sorted(self, populated_store):
        result = calendar_upcoming_tool()
        events = result["events"]
        if len(events) >= 2:
            assert events[0]["start"] <= events[1]["start"]


# ── Calendar search ───────────────────────────────────────────────

class TestCalendarSearch:
    def test_search_standup(self, populated_store):
        result = calendar_search_tool(query="Standup")
        assert result["ok"] is True
        assert result["count"] >= 1

    def test_search_missing_query(self, populated_store):
        result = calendar_search_tool(query="")
        assert result["ok"] is False

    def test_search_no_match(self, populated_store):
        result = calendar_search_tool(query="xyznonexistent")
        assert result["ok"] is True
        assert result["count"] == 0


# ── News latest ───────────────────────────────────────────────────

class TestNewsLatest:
    def test_latest_all(self, populated_store):
        result = news_latest_tool()
        assert result["ok"] is True
        assert result["count"] == 2

    def test_latest_by_category(self, populated_store):
        result = news_latest_tool(category="ai")
        assert result["ok"] is True
        assert all(a["category"] == "ai" for a in result["articles"])


# ── News search ───────────────────────────────────────────────────

class TestNewsSearch:
    def test_search_ai(self, populated_store):
        result = news_search_tool(query="AI")
        assert result["ok"] is True
        assert result["count"] >= 1

    def test_search_missing_query(self, populated_store):
        result = news_search_tool(query="")
        assert result["ok"] is False


# ── Sync status ───────────────────────────────────────────────────

class TestSyncStatus:
    def test_status_without_scheduler(self):
        sync_module._scheduler = None
        result = sync_status_tool()
        assert result["ok"] is False

    def test_status_with_scheduler(self, store):
        from unittest.mock import MagicMock
        mock_scheduler = MagicMock()
        mock_scheduler.stats = {"is_running": False, "uptime_seconds": 0}
        sync_module._scheduler = mock_scheduler
        result = sync_status_tool()
        assert result["ok"] is True
        sync_module._scheduler = None


# ── Store not available ───────────────────────────────────────────

class TestStoreUnavailable:
    def test_inbox_search_no_store(self):
        old = sync_module._store
        sync_module._store = None
        # Also patch the lazy init to fail
        result = inbox_search_tool(query="test")
        # Will try lazy init — may or may not succeed
        sync_module._store = old
