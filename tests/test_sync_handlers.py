"""
Tests for bantz.router.handlers.sync — intent handler dispatch.

Verifies that all 9 sync intent handlers:
- Accept the standard handler signature
- Return valid RouterResult
- Call the correct sync_search_tools function
- Format output text properly
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bantz.router.context import ConversationContext
from bantz.router.types import RouterResult

# Import all handlers
from bantz.router.handlers.sync import (
    handle_inbox_search,
    handle_inbox_classify,
    handle_inbox_summary,
    handle_calendar_upcoming,
    handle_calendar_search,
    handle_news_latest,
    handle_news_search,
    handle_sync_status,
    handle_sync_now,
    register_all,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def ctx():
    return ConversationContext(timeout_seconds=60)


def _call(handler, ctx, **slots):
    """Shorthand for calling a handler with standard args."""
    return handler(
        intent="test_intent",
        slots=slots,
        ctx=ctx,
        router=MagicMock(),
        in_queue=False,
    )


# ── Registration ──────────────────────────────────────────────────

class TestRegistration:
    def test_register_all_runs(self):
        register_all()  # should not raise

    def test_all_handlers_registered(self):
        from bantz.router.handler_registry import get_handler
        register_all()
        for intent in [
            "inbox_search", "inbox_classify", "inbox_summary",
            "calendar_upcoming", "calendar_search",
            "news_latest", "news_search",
            "sync_status", "sync_now",
        ]:
            assert get_handler(intent) is not None, f"{intent} not registered"


_TOOLS = "bantz.tools.sync_search_tools"


# ── Inbox handlers ────────────────────────────────────────────────

class TestInboxSearch:
    @patch(f"{_TOOLS}.inbox_search_tool")
    def test_returns_router_result(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "query": "github", "count": 1,
            "messages": [{"subject": "PR merged", "from": "github", "category": "github", "sender_name": "GitHub"}],
            "display_hint": "1 sonuç",
        }
        result = _call(handle_inbox_search, ctx, query="github")
        assert isinstance(result, RouterResult)
        assert result.ok is True
        mock_tool.assert_called_once_with(query="github", limit=20)

    @patch(f"{_TOOLS}.inbox_search_tool")
    def test_formats_messages(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "query": "test", "count": 1,
            "messages": [{"subject": "Test", "from": "a@b.com", "category": "uncategorized", "sender_name": ""}],
            "display_hint": "1 sonuç",
        }
        result = _call(handle_inbox_search, ctx, query="test")
        assert "Test" in result.user_text


class TestInboxClassify:
    @patch(f"{_TOOLS}.inbox_by_category_tool")
    def test_category_filter(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "category": "github", "count": 2,
            "messages": [
                {"subject": "PR #1", "from": "gh@github.com", "category": "github", "sender_name": "GitHub"},
                {"subject": "PR #2", "from": "gh@github.com", "category": "github", "sender_name": "GitHub"},
            ],
            "display_hint": "2 mesaj",
        }
        result = _call(handle_inbox_classify, ctx, category="github")
        assert result.ok is True
        mock_tool.assert_called_once_with(category="github", limit=20)


class TestInboxSummary:
    @patch(f"{_TOOLS}.inbox_summary_tool")
    def test_summary_format(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "total_messages": 10,
            "top_categories": [{"category": "github", "count": 5}],
            "top_senders": [{"sender": "GitHub", "count": 5}],
            "recent_subjects": ["PR merged"],
            "display_hint": "10 mesaj",
        }
        result = _call(handle_inbox_summary, ctx)
        assert result.ok is True
        assert "github" in result.user_text.lower()


# ── Calendar handlers ─────────────────────────────────────────────

class TestCalendarUpcoming:
    @patch(f"{_TOOLS}.calendar_upcoming_tool")
    def test_upcoming_events(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "count": 1,
            "events": [{"summary": "Standup", "start": "2026-02-17T10:00", "location": "Meet"}],
            "display_hint": "1 etkinlik",
        }
        result = _call(handle_calendar_upcoming, ctx, days=3)
        assert result.ok is True
        assert "Standup" in result.user_text
        mock_tool.assert_called_once_with(days=3, limit=20)


class TestCalendarSearch:
    @patch(f"{_TOOLS}.calendar_search_tool")
    def test_search(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "query": "standup", "count": 1,
            "events": [{"summary": "Team Standup", "start": "2026-02-17"}],
            "display_hint": "1 etkinlik",
        }
        result = _call(handle_calendar_search, ctx, query="standup")
        assert result.ok is True
        mock_tool.assert_called_once_with(query="standup", limit=20)


# ── News handlers ─────────────────────────────────────────────────

class TestNewsLatest:
    @patch(f"{_TOOLS}.news_latest_tool")
    def test_latest_all(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "category": "all", "count": 2,
            "articles": [
                {"title": "AI News", "source": "TC", "category": "ai"},
                {"title": "Tech News", "source": "TC", "category": "tech"},
            ],
            "display_hint": "2 haber",
        }
        result = _call(handle_news_latest, ctx)
        assert result.ok is True
        assert "AI News" in result.user_text


class TestNewsSearch:
    @patch(f"{_TOOLS}.news_search_tool")
    def test_search(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "query": "AI", "count": 1,
            "articles": [{"title": "AI Paper", "source": "arXiv"}],
            "display_hint": "1 sonuç",
        }
        result = _call(handle_news_search, ctx, query="AI")
        assert result.ok is True
        mock_tool.assert_called_once_with(query="AI", limit=10)


# ── Sync management handlers ─────────────────────────────────────

class TestSyncStatus:
    @patch(f"{_TOOLS}.sync_status_tool")
    def test_status(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "is_running": True, "uptime_seconds": 120,
            "gmail": {"total_synced": 50, "is_running": True, "last_sync": 1},
            "calendar": {"total_synced": 10, "is_running": True, "last_sync": 1},
            "news": {"total_synced": 15, "is_running": True, "last_sync": 1},
        }
        result = _call(handle_sync_status, ctx)
        assert result.ok is True
        assert "çalışıyor" in result.user_text


class TestSyncNow:
    @patch(f"{_TOOLS}.sync_now_tool")
    def test_sync_gmail(self, mock_tool, ctx):
        mock_tool.return_value = {
            "ok": True, "status": "sync_triggered", "source": "gmail",
            "display_hint": "gmail senkronizasyonu başlatıldı.",
        }
        result = _call(handle_sync_now, ctx, source="gmail")
        assert result.ok is True
        mock_tool.assert_called_once_with(source="gmail")


# ── Error handling ────────────────────────────────────────────────

class TestErrorHandling:
    @patch(f"{_TOOLS}.inbox_search_tool")
    def test_error_result(self, mock_tool, ctx):
        mock_tool.return_value = {"ok": False, "error": "Store unavailable", "messages": []}
        result = _call(handle_inbox_search, ctx, query="test")
        assert result.ok is False
        assert "Store unavailable" in result.user_text
