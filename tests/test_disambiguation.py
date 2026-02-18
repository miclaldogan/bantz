"""Tests for DisambiguationDialog (Issue #875)."""
from __future__ import annotations

import pytest

from bantz.brain.disambiguation import (
    DisambiguationDialog,
    DisambiguationRequest,
    DisambiguationResult,
    DISAMBIGUATION_INTENTS,
    MIN_ITEMS_FOR_DISAMBIGUATION,
    create_disambiguation_dialog,
)
from bantz.brain.anaphora import ReferenceItem, ReferenceTable
from bantz.brain.orchestrator_state import OrchestratorState


# ── helpers ──────────────────────────────────────────────────────

def _calendar_tool_results(n: int = 3) -> list[dict]:
    """Mock calendar.list_events tool results with n events."""
    events = [
        {"title": f"Toplantı {i}", "start": f"2025-07-{10+i}T{10+i}:00:00",
         "event_id": f"evt_{i}"}
        for i in range(1, n + 1)
    ]
    return [{"tool": "calendar.list_events", "success": True,
             "result": events, "result_summary": str(events)}]


def _email_tool_results(n: int = 2) -> list[dict]:
    """Mock gmail.list_messages tool results."""
    msgs = [
        {"from": f"user{i}@test.com", "subject": f"Konu {i}",
         "message_id": f"msg_{i}"}
        for i in range(1, n + 1)
    ]
    return [{"tool": "gmail.list_messages", "success": True,
             "result": msgs, "result_summary": str(msgs)}]


# ── DisambiguationDialog.check_tool_results ──────────────────────

class TestCheckToolResults:

    def test_triggers_on_multiple_items(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_delete_event"
        )
        assert req is not None
        assert req.item_count >= 2
        assert "hangisi" in req.question_text.lower() or "Hangisini" in req.question_text

    def test_no_trigger_single_item(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(1), intent="calendar_delete_event"
        )
        assert req is None

    def test_no_trigger_non_disambiguation_intent(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_list_events"
        )
        assert req is None

    def test_no_trigger_empty_results(self):
        d = DisambiguationDialog()
        assert d.check_tool_results([], intent="calendar_delete_event") is None

    def test_stores_reference_table(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_update_event"
        )
        assert req is not None
        assert isinstance(req.reference_table, ReferenceTable)
        assert len(req.reference_table) >= 2


# ── DisambiguationDialog._build_question ─────────────────────────

class TestBuildQuestion:

    def test_contains_item_labels(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_delete_event"
        )
        assert req is not None
        assert "#1" in req.question_text
        assert "#2" in req.question_text

    def test_contains_action_verb(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(2), intent="gmail_reply"
        )
        # gmail_reply won't extract calendar events — use email results
        req = d.check_tool_results(
            _email_tool_results(2), intent="gmail_reply"
        )
        assert req is not None
        assert "yanıtlamamı" in req.question_text

    def test_source_label_calendar(self):
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_delete_event"
        )
        assert req is not None
        assert "Takvimde" in req.question_text


# ── DisambiguationDialog.resolve_response ────────────────────────

class TestResolveResponse:

    @pytest.fixture
    def pending(self):
        d = DisambiguationDialog()
        return d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_delete_event"
        )

    def test_resolve_by_number(self, pending):
        d = DisambiguationDialog()
        result = d.resolve_response("#1", pending)
        assert result.resolved is True
        assert result.selected_index == 1

    def test_resolve_by_bare_digit(self, pending):
        d = DisambiguationDialog()
        result = d.resolve_response("2", pending)
        assert result.resolved is True
        assert result.selected_index == 2

    def test_resolve_invalid_number(self, pending):
        d = DisambiguationDialog()
        result = d.resolve_response("99", pending)
        assert result.resolved is False
        assert result.error

    def test_resolve_no_pending(self):
        d = DisambiguationDialog()
        result = d.resolve_response("#1", None)
        assert result.resolved is False
        assert "yok" in result.error.lower()


# ── OrchestratorState integration ───────────────────────────────

class TestStateIntegration:

    def test_disambiguation_pending_default_none(self):
        state = OrchestratorState()
        assert state.disambiguation_pending is None

    def test_disambiguation_pending_survives_assignment(self):
        state = OrchestratorState()
        d = DisambiguationDialog()
        req = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_delete_event"
        )
        state.disambiguation_pending = req
        assert state.disambiguation_pending is not None
        assert state.disambiguation_pending.item_count >= 2

    def test_disambiguation_cleared_on_reset(self):
        state = OrchestratorState()
        d = DisambiguationDialog()
        state.disambiguation_pending = d.check_tool_results(
            _calendar_tool_results(3), intent="calendar_delete_event"
        )
        state.reset()
        assert state.disambiguation_pending is None


# ── factory ──────────────────────────────────────────────────────

class TestFactory:

    def test_create_default(self):
        d = create_disambiguation_dialog()
        assert isinstance(d, DisambiguationDialog)

    def test_create_custom_min_items(self):
        d = create_disambiguation_dialog(min_items=5)
        assert d._min_items == 5


# ── disambiguation intents set ───────────────────────────────────

class TestIntentsSet:

    def test_contains_calendar_delete(self):
        assert "calendar_delete_event" in DISAMBIGUATION_INTENTS

    def test_contains_gmail_reply(self):
        assert "gmail_reply" in DISAMBIGUATION_INTENTS

    def test_not_contains_list(self):
        assert "calendar_list_events" not in DISAMBIGUATION_INTENTS
