# SPDX-License-Identifier: MIT
"""Tests for Issue #1224: Golden Path Calendar.

Covers:
1. Calendar context persistence (calendar_listed_events)
2. #N reference resolution to event_id
3. Display hints in tool results (deterministic reply format)
4. free_slots route in mandatory tool map
5. Deterministic list, create, update display hints
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.orchestrator_state import OrchestratorState


# ============================================================================
# Calendar context persistence
# ============================================================================
class TestCalendarContextPersistence:
    """_save_calendar_context stores listed events for follow-up."""

    def _make_tool_results(self, events: list[dict]) -> list[dict[str, Any]]:
        return [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {"ok": True, "events": events},
        }]

    def test_saves_events_to_state(self) -> None:
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        state = OrchestratorState()
        events = [
            {"id": "e1", "summary": "Standup", "start": "2025-01-15T09:00:00", "end": "2025-01-15T09:30:00"},
            {"id": "e2", "summary": "Lunch", "start": "2025-01-15T12:00:00", "end": "2025-01-15T13:00:00"},
        ]
        OrchestratorLoop._save_calendar_context(self._make_tool_results(events), state)
        assert len(state.calendar_listed_events) == 2
        assert state.calendar_listed_events[0]["id"] == "e1"
        assert state.calendar_listed_events[1]["summary"] == "Lunch"

    def test_ignores_failed_results(self) -> None:
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        state = OrchestratorState()
        results = [{"tool": "calendar.list_events", "success": False, "raw_result": {}}]
        OrchestratorLoop._save_calendar_context(results, state)
        assert state.calendar_listed_events == []

    def test_ignores_non_calendar_tools(self) -> None:
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        state = OrchestratorState()
        results = [{"tool": "gmail.list_messages", "success": True, "raw_result": {"events": []}}]
        OrchestratorLoop._save_calendar_context(results, state)
        assert state.calendar_listed_events == []

    def test_empty_events_clears_state(self) -> None:
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        state = OrchestratorState()
        state.calendar_listed_events = [{"id": "old"}]
        OrchestratorLoop._save_calendar_context(
            self._make_tool_results([]), state
        )
        assert state.calendar_listed_events == []

    def test_state_reset_clears_calendar_events(self) -> None:
        state = OrchestratorState()
        state.calendar_listed_events = [{"id": "e1"}]
        state.reset()
        assert state.calendar_listed_events == []


# ============================================================================
# #N reference resolution
# ============================================================================
class TestHashRefResolution:
    """parse_hash_ref_index resolves #N to event index."""

    def test_parse_hash_1(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        assert parse_hash_ref_index("#1 toplantısını sil") == 1

    def test_parse_hash_3(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        assert parse_hash_ref_index("#3'ü güncelle") == 3

    def test_no_hash_returns_none(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        assert parse_hash_ref_index("toplantıyı sil") is None

    def test_zero_returns_none(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        assert parse_hash_ref_index("#0 sil") is None


# ============================================================================
# Display hints — list_events
# ============================================================================
class TestListEventsDisplayHint:
    """calendar_list_events_tool adds display_hint field."""

    @patch("bantz.tools.calendar_tools.list_events")
    def test_display_hint_generated(self, mock_list: MagicMock) -> None:
        from bantz.tools.calendar_tools import calendar_list_events_tool
        mock_list.return_value = {
            "ok": True,
            "events": [
                {"id": "e1", "summary": "Standup", "start": "2025-01-15T09:00:00+03:00", "end": "2025-01-15T09:30:00+03:00"},
                {"id": "e2", "summary": "Lunch", "start": "2025-01-15T12:00:00+03:00", "end": "2025-01-15T13:00:00+03:00"},
            ],
        }
        result = calendar_list_events_tool(date="2025-01-15")
        assert result.get("display_hint") is not None
        assert "#1 09:00-09:30 Standup" in result["display_hint"]
        assert "#2 12:00-13:00 Lunch" in result["display_hint"]
        assert result["event_count"] == 2

    @patch("bantz.tools.calendar_tools.list_events")
    def test_empty_events_hint(self, mock_list: MagicMock) -> None:
        from bantz.tools.calendar_tools import calendar_list_events_tool
        mock_list.return_value = {"ok": True, "events": []}
        result = calendar_list_events_tool(date="2025-01-15")
        assert "bulunamadı" in result.get("display_hint", "")
        assert result["event_count"] == 0


# ============================================================================
# Display hints — create_event
# ============================================================================
class TestCreateEventDisplayHint:
    """calendar_create_event_tool adds display_hint on success."""

    @patch("bantz.tools.calendar_tools.create_event_with_idempotency")
    def test_create_display_hint(self, mock_create: MagicMock) -> None:
        from bantz.tools.calendar_tools import calendar_create_event_tool
        mock_create.return_value = {"ok": True, "event": {"id": "e1"}}
        result = calendar_create_event_tool(title="Toplantı", date="2025-01-15", time="15:00")
        assert result.get("display_hint") is not None
        assert "Toplantı" in result["display_hint"]
        assert "15:00" in result["display_hint"]

    @patch("bantz.tools.calendar_tools.create_event_with_idempotency")
    def test_duplicate_display_hint(self, mock_create: MagicMock) -> None:
        from bantz.tools.calendar_tools import calendar_create_event_tool
        mock_create.return_value = {"ok": True, "duplicate": True}
        result = calendar_create_event_tool(title="Toplantı", date="2025-01-15", time="15:00")
        assert "zaten mevcut" in result.get("display_hint", "")


# ============================================================================
# Display hints — update_event
# ============================================================================
class TestUpdateEventDisplayHint:
    """calendar_update_event_tool adds display_hint on success."""

    @patch("bantz.tools.calendar_tools.update_event")
    def test_update_display_hint(self, mock_update: MagicMock) -> None:
        from bantz.tools.calendar_tools import calendar_update_event_tool
        mock_update.return_value = {"ok": True, "id": "e1"}
        result = calendar_update_event_tool(event_id="e1", title="Yeni Başlık")
        assert result.get("display_hint") is not None
        assert "Yeni Başlık" in result["display_hint"]
        assert "güncellendi" in result["display_hint"]


# ============================================================================
# free_slots route in mandatory tool map
# ============================================================================
class TestFreeSlotsRoute:
    """calendar/free_slots should be in the mandatory tool map."""

    def test_free_slots_in_mandatory_map(self) -> None:
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        # Create a minimal OrchestratorLoop to inspect its _mandatory_tool_map
        loop = OrchestratorLoop.__new__(OrchestratorLoop)
        loop._mandatory_tool_map = {}
        # Call __init__ partially — just check the class-level map
        # Instead, grep the source for the mapping
        import inspect
        source = inspect.getsource(OrchestratorLoop.__init__)
        assert '("calendar", "free_slots")' in source
        assert "calendar.find_free_slots" in source
