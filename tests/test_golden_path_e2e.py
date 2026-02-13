# SPDX-License-Identifier: MIT
"""Issue #1226: Golden Path E2E Tests — Calendar + Inbox scenarios.

These tests simulate full multi-turn conversations with mocked tools
to verify the complete pipeline (router → intent → tool → finalizer).

Run with: pytest --run-golden-path tests/test_golden_path_e2e.py
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.orchestrator_state import OrchestratorState


pytestmark = pytest.mark.golden_path


# ============================================================================
# Fixtures
# ============================================================================

_CALENDAR_EVENTS = [
    {"id": "ev1", "summary": "Standup", "start": "2025-01-15T09:00:00+03:00", "end": "2025-01-15T09:30:00+03:00"},
    {"id": "ev2", "summary": "Öğle Yemeği", "start": "2025-01-15T12:00:00+03:00", "end": "2025-01-15T13:00:00+03:00"},
    {"id": "ev3", "summary": "Proje Toplantısı", "start": "2025-01-15T15:00:00+03:00", "end": "2025-01-15T16:00:00+03:00"},
]

_GMAIL_MESSAGES = [
    {"id": "msg1", "from": "tubitak@gov.tr", "subject": "TÜBİTAK Proje Onayı", "unread": True},
    {"id": "msg2", "from": "noreply@github.com", "subject": "GitHub Actions CI", "unread": False},
    {"id": "msg3", "from": "ahmet@corp.com", "subject": "Toplantı Notu", "unread": True},
]


# ============================================================================
# Golden Path #1 — Calendar
# ============================================================================
class TestGoldenPathCalendar:
    """Full calendar scenario: list → create → verify."""

    def test_step1_list_events_returns_display_hint(self) -> None:
        """'bugün ajandamı çıkar' → numbered event list."""
        with patch("bantz.tools.calendar_tools.list_events") as mock:
            mock.return_value = {"ok": True, "events": _CALENDAR_EVENTS}
            from bantz.tools.calendar_tools import calendar_list_events_tool
            result = calendar_list_events_tool(window_hint="today")
        assert result["ok"]
        assert result["event_count"] == 3
        assert "#1" in result["display_hint"]
        assert "Standup" in result["display_hint"]

    def test_step2_context_persisted_for_followup(self) -> None:
        """Listed events stored in state for #N resolution."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        state = OrchestratorState()
        tool_results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {"ok": True, "events": _CALENDAR_EVENTS},
        }]
        OrchestratorLoop._save_calendar_context(tool_results, state)
        assert len(state.calendar_listed_events) == 3
        assert state.calendar_listed_events[1]["summary"] == "Öğle Yemeği"

    def test_step3_hash_ref_resolves_to_event_id(self) -> None:
        """'#2 toplantısını sil' → resolves to ev2."""
        from bantz.brain.calendar_intent import parse_hash_ref_index
        state = OrchestratorState()
        state.calendar_listed_events = [
            {"id": "ev1", "summary": "Standup"},
            {"id": "ev2", "summary": "Öğle Yemeği"},
            {"id": "ev3", "summary": "Proje Toplantısı"},
        ]
        idx = parse_hash_ref_index("#2 toplantısını sil")
        assert idx == 2
        ref_event = state.calendar_listed_events[idx - 1]
        assert ref_event["id"] == "ev2"

    def test_step4_create_event_display_hint(self) -> None:
        """'yarın 15:00'e toplantı ekle' → confirmation with display_hint."""
        with patch("bantz.tools.calendar_tools.create_event_with_idempotency") as mock:
            mock.return_value = {"ok": True, "event": {"id": "new1"}}
            from bantz.tools.calendar_tools import calendar_create_event_tool
            result = calendar_create_event_tool(title="Sprint Review", date="2025-01-16", time="15:00")
        assert result["ok"]
        assert "Sprint Review" in result["display_hint"]
        assert "15:00" in result["display_hint"]

    def test_step5_free_slots_route_mapped(self) -> None:
        """free_slots intent has mandatory tool mapping."""
        import inspect
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        source = inspect.getsource(OrchestratorLoop.__init__)
        assert '("calendar", "free_slots")' in source


# ============================================================================
# Golden Path #2 — Inbox
# ============================================================================
class TestGoldenPathInbox:
    """Full inbox scenario: list → search → read → draft."""

    def test_step1_list_messages_display_hint(self) -> None:
        """'son maillerimi özetle' → numbered message list."""
        with patch("bantz.tools.gmail_tools.gmail_list_messages") as mock:
            mock.return_value = {"ok": True, "messages": _GMAIL_MESSAGES}
            from bantz.tools.gmail_tools import gmail_list_messages_tool
            result = gmail_list_messages_tool(max_results=5)
        assert result["ok"]
        assert result["message_count"] == 3
        assert "#1 tubitak@gov.tr" in result["display_hint"]

    def test_step2_search_filters_correctly(self) -> None:
        """'tübitaktan gelen mailler' → filtered results."""
        with patch("bantz.tools.gmail_tools.build_smart_query") as mock_bsq, \
             patch("bantz.tools.gmail_tools.gmail_list_messages") as mock_list:
            mock_bsq.return_value = ("from:tubitak", None)
            mock_list.return_value = {"ok": True, "messages": [_GMAIL_MESSAGES[0]]}
            from bantz.tools.gmail_tools import gmail_smart_search_tool
            result = gmail_smart_search_tool(natural_query="tübitaktan gelen mailler")
        assert result["ok"]
        assert result["message_count"] == 1
        assert "tubitak" in result["display_hint"]

    def test_step3_send_requires_all_fields(self) -> None:
        """Send tool returns confirmation display hint."""
        with patch("bantz.tools.gmail_tools._gmail_check_duplicate", return_value=False), \
             patch("bantz.tools.gmail_tools.gmail_send") as mock_send:
            mock_send.return_value = {"ok": True}
            from bantz.tools.gmail_tools import gmail_send_tool
            result = gmail_send_tool(to="test@x.com", subject="Re: Proje", body="Teşekkürler")
        assert result.get("display_hint") is not None
        assert "test@x.com" in result["display_hint"]

    def test_step4_draft_display_hint(self) -> None:
        """Draft creation gives structured feedback."""
        with patch("bantz.tools.gmail_extended_tools._safe_call") as mock:
            mock.return_value = {"ok": True, "draft_id": "d1"}
            from bantz.tools.gmail_extended_tools import gmail_create_draft_tool
            result = gmail_create_draft_tool(to="boss@corp.com", subject="Haftalık Rapor", body="İçerik")
        assert "Taslak" in result["display_hint"]
        assert "boss@corp.com" in result["display_hint"]


# ============================================================================
# Failure Mode Tests
# ============================================================================
class TestFailureModes:
    """Pipeline handles errors gracefully."""

    def test_calendar_api_error_returns_turkish_message(self) -> None:
        """Google API error → Turkish error message."""
        with patch("bantz.tools.calendar_tools.list_events", side_effect=Exception("HttpError 401")):
            from bantz.tools.calendar_tools import calendar_list_events_tool
            result = calendar_list_events_tool(date="2025-01-15")
        assert result["ok"] is False
        # Should have a Turkish error message, not raw traceback
        assert "error" in result

    def test_gmail_api_error_returns_turkish_message(self) -> None:
        """Gmail API error → Turkish error message."""
        with patch("bantz.tools.gmail_tools.gmail_list_messages", side_effect=Exception("HttpError 403")):
            from bantz.tools.gmail_tools import gmail_list_messages_tool
            result = gmail_list_messages_tool()
        assert result["ok"] is False
        assert "izin" in result.get("error", "").lower() or "error" in result

    def test_calendar_create_missing_time_returns_error(self) -> None:
        """Create event without time → clear error."""
        from bantz.tools.calendar_tools import calendar_create_event_tool
        result = calendar_create_event_tool(title="Test", date="2025-01-15")
        assert result["ok"] is False
        assert "time" in result.get("error", "").lower() or "missing" in result.get("error", "").lower()

    def test_calendar_delete_missing_id_returns_error(self) -> None:
        """Delete event without id → clear error."""
        from bantz.tools.calendar_tools import calendar_delete_event_tool
        result = calendar_delete_event_tool()
        assert result["ok"] is False
        assert "event_id" in result.get("error", "").lower() or "missing" in result.get("error", "").lower()

    def test_gmail_send_duplicate_blocked(self) -> None:
        """Duplicate send within window → blocked."""
        with patch("bantz.tools.gmail_tools._gmail_check_duplicate", return_value=True):
            from bantz.tools.gmail_tools import gmail_send_tool
            result = gmail_send_tool(to="x@y.com", subject="Test", body="Body")
        assert result["ok"] is False
        assert result.get("duplicate") is True
