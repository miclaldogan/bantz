"""Tests for issue #628: Calendar hallucination when tools fail or return empty data.

Covers:
- _all_tools_failed helper
- _tool_data_is_empty helper
- _empty_data_message helper
- Tool-first guard extended to catch all-tools-failed
- Empty-data guard in FinalizationPipeline.run()
- End-to-end pipeline scenarios (no hallucination leaks)
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import Mock

import pytest

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.brain.finalization_pipeline import (
    FinalizationContext,
    FinalizationPipeline,
    QualityFinalizer,
    FastFinalizer,
    _all_tools_failed,
    _tool_data_is_empty,
    _empty_data_message,
    _apply_tool_first_guard_if_needed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_output(**overrides: Any) -> OrchestratorOutput:
    defaults = dict(
        route="calendar",
        calendar_intent="query",
        slots={},
        confidence=0.9,
        tool_plan=["calendar.list_events"],
        assistant_reply="",
        ask_user=False,
        question="",
        requires_confirmation=False,
        confirmation_prompt="",
    )
    defaults.update(overrides)
    return OrchestratorOutput(**defaults)


def _make_ctx(**overrides: Any) -> FinalizationContext:
    defaults = dict(
        user_input="bugün takvimimde ne var",
        orchestrator_output=_make_output(),
        tool_results=[],
        state=OrchestratorState(),
        planner_decision={"route": "calendar"},
        use_quality=True,
        tier_name="quality",
        tier_reason="test",
    )
    defaults.update(overrides)
    return FinalizationContext(**defaults)


# =============================================================================
# _all_tools_failed
# =============================================================================

class TestAllToolsFailed:

    def test_empty_list_returns_false(self):
        assert _all_tools_failed([]) is False

    def test_all_success_returns_false(self):
        results = [{"tool": "calendar.list_events", "success": True}]
        assert _all_tools_failed(results) is False

    def test_mixed_returns_false(self):
        results = [
            {"tool": "a", "success": True},
            {"tool": "b", "success": False, "error": "fail"},
        ]
        assert _all_tools_failed(results) is False

    def test_all_failed_returns_true(self):
        results = [
            {"tool": "calendar.list_events", "success": False, "error": "Auth error"},
        ]
        assert _all_tools_failed(results) is True

    def test_multiple_failures_returns_true(self):
        results = [
            {"tool": "a", "success": False, "error": "x"},
            {"tool": "b", "success": False, "error": "y"},
        ]
        assert _all_tools_failed(results) is True

    def test_pending_confirmation_not_counted_as_failure(self):
        results = [
            {"tool": "calendar.create_event", "success": False, "pending_confirmation": True},
        ]
        assert _all_tools_failed(results) is False

    def test_confirmation_plus_real_failure(self):
        results = [
            {"tool": "a", "success": False, "pending_confirmation": True},
            {"tool": "b", "success": False, "error": "fail"},
        ]
        # Not "all" failed because the confirmation entry is excluded
        assert _all_tools_failed(results) is False


# =============================================================================
# _tool_data_is_empty
# =============================================================================

class TestToolDataIsEmpty:

    def test_no_results_returns_true(self):
        assert _tool_data_is_empty([]) is True

    def test_success_with_events_returns_false(self):
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {"ok": True, "events": [{"id": "e1", "summary": "Meeting"}]},
        }]
        assert _tool_data_is_empty(results) is False

    def test_success_with_empty_events_returns_true(self):
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {"ok": True, "events": [], "total_count": 0},
        }]
        assert _tool_data_is_empty(results) is True

    def test_success_with_messages_returns_false(self):
        results = [{
            "tool": "gmail.list_messages",
            "success": True,
            "raw_result": {"ok": True, "messages": [{"id": "m1"}]},
        }]
        assert _tool_data_is_empty(results) is False

    def test_success_with_empty_messages_returns_true(self):
        results = [{
            "tool": "gmail.list_messages",
            "success": True,
            "raw_result": {"ok": True, "messages": []},
        }]
        assert _tool_data_is_empty(results) is True

    def test_success_with_nonzero_count_returns_false(self):
        results = [{
            "tool": "gmail.unread_count",
            "success": True,
            "raw_result": {"ok": True, "total_count": 5},
        }]
        assert _tool_data_is_empty(results) is False

    def test_failure_result_ignored(self):
        """Failed results should be ignored — they're handled by _check_hard_failures."""
        results = [{
            "tool": "calendar.list_events",
            "success": False,
            "raw_result": {"ok": False, "error": "auth"},
        }]
        # All results are failures → no successful result with data
        assert _tool_data_is_empty(results) is True

    def test_non_dict_raw_result_returns_false(self):
        """Non-dict results (string, etc.) are assumed to have data."""
        results = [{
            "tool": "time.now",
            "success": True,
            "raw_result": "14:35 TRT",
        }]
        assert _tool_data_is_empty(results) is False

    def test_success_with_slots_returns_false(self):
        results = [{
            "tool": "calendar.find_free_slots",
            "success": True,
            "raw_result": {"ok": True, "slots": [{"start": "10:00", "end": "11:00"}]},
        }]
        assert _tool_data_is_empty(results) is False

    def test_success_without_known_data_keys_returns_true(self):
        """If raw_result is a dict with ok=True but no data keys, it's empty."""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {"ok": True},
        }]
        assert _tool_data_is_empty(results) is True


# =============================================================================
# _empty_data_message
# =============================================================================

class TestEmptyDataMessage:

    def test_calendar_query(self):
        msg = _empty_data_message(route="calendar", calendar_intent="query")
        assert "takvim" in msg.lower()
        assert "etkinlik bulunamadı" in msg.lower()

    def test_calendar_free_slots(self):
        msg = _empty_data_message(route="calendar", calendar_intent="free_slots")
        assert "slot" in msg.lower()

    def test_gmail(self):
        msg = _empty_data_message(route="gmail")
        assert "mesaj bulunamadı" in msg.lower()

    def test_unknown_route(self):
        msg = _empty_data_message(route="system")
        assert "bulunamadı" in msg.lower()


# =============================================================================
# _apply_tool_first_guard_if_needed — extended
# =============================================================================

class TestToolFirstGuardExtended:

    def test_guard_fires_when_no_tool_results(self):
        """Original behavior: guard fires when tool_results is empty."""
        ctx = _make_ctx(
            tool_results=[],
            orchestrator_output=_make_output(route="calendar", calendar_intent="query"),
        )
        result = _apply_tool_first_guard_if_needed(ctx)
        assert result is not None
        assert "takvim" in result.assistant_reply.lower()
        assert "tool_first_guard" in result.finalizer_model

    def test_guard_fires_when_all_tools_failed(self):
        """NEW: guard fires when all tools returned success=False."""
        ctx = _make_ctx(
            tool_results=[
                {"tool": "calendar.list_events", "success": False, "error": "Auth error"},
            ],
            orchestrator_output=_make_output(route="calendar", calendar_intent="query"),
        )
        result = _apply_tool_first_guard_if_needed(ctx)
        assert result is not None
        assert "takvim" in result.assistant_reply.lower()
        assert "all_tools_failed" in result.finalizer_model

    def test_guard_does_not_fire_when_tools_succeed(self):
        """Guard should not fire when at least one tool succeeded."""
        ctx = _make_ctx(
            tool_results=[
                {"tool": "calendar.list_events", "success": True, "raw_result": {"ok": True, "events": []}},
            ],
            orchestrator_output=_make_output(route="calendar", calendar_intent="query"),
        )
        result = _apply_tool_first_guard_if_needed(ctx)
        assert result is None  # guard does NOT fire

    def test_guard_does_not_fire_for_smalltalk(self):
        ctx = _make_ctx(
            tool_results=[],
            orchestrator_output=_make_output(route="smalltalk", calendar_intent=""),
        )
        result = _apply_tool_first_guard_if_needed(ctx)
        assert result is None

    def test_guard_does_not_fire_when_ask_user(self):
        ctx = _make_ctx(
            tool_results=[
                {"tool": "calendar.list_events", "success": False, "error": "fail"},
            ],
            orchestrator_output=_make_output(
                route="calendar", calendar_intent="query",
                ask_user=True, question="Hangi gün?",
            ),
        )
        result = _apply_tool_first_guard_if_needed(ctx)
        assert result is None

    def test_guard_fires_for_gmail_all_failed(self):
        ctx = _make_ctx(
            tool_results=[
                {"tool": "gmail.list_messages", "success": False, "error": "fail"},
            ],
            orchestrator_output=_make_output(route="gmail", calendar_intent="list"),
        )
        # Need gmail_intent attribute
        out = ctx.orchestrator_output
        object.__setattr__(out, "gmail_intent", "list")
        result = _apply_tool_first_guard_if_needed(ctx)
        assert result is not None
        assert "Gmail" in result.assistant_reply


# =============================================================================
# FinalizationPipeline — empty data guard
# =============================================================================

class TestPipelineEmptyDataGuard:
    """Pipeline.run() should return deterministic msg for empty tool data."""

    def test_calendar_empty_events_returns_deterministic(self):
        """The exact hallucination scenario: calendar query returns empty events."""
        mock_llm = Mock()
        mock_llm.complete_text.return_value = "Bugün 3 toplantınız var efendim."  # hallucination!
        pipeline = FinalizationPipeline(
            quality=QualityFinalizer(finalizer_llm=mock_llm),
        )

        ctx = _make_ctx(
            tool_results=[{
                "tool": "calendar.list_events",
                "success": True,
                "raw_result": {"ok": True, "events": [], "total_count": 0},
                "result_summary": "0 events",
            }],
            orchestrator_output=_make_output(route="calendar", calendar_intent="query"),
        )

        result = pipeline.run(ctx)
        # Must NOT contain the hallucinated response
        assert "3 toplantı" not in result.assistant_reply
        # Must contain the deterministic empty-data message
        assert "etkinlik bulunamadı" in result.assistant_reply.lower()
        assert result.finalizer_model == "none(empty_data_guard)"
        # Quality LLM should NOT have been called
        mock_llm.complete_text.assert_not_called()

    def test_gmail_empty_messages_returns_deterministic(self):
        pipeline = FinalizationPipeline(
            quality=QualityFinalizer(finalizer_llm=Mock()),
        )

        ctx = _make_ctx(
            tool_results=[{
                "tool": "gmail.list_messages",
                "success": True,
                "raw_result": {"ok": True, "messages": []},
                "result_summary": "0 messages",
            }],
            orchestrator_output=_make_output(route="gmail", calendar_intent="list"),
        )

        result = pipeline.run(ctx)
        assert "mesaj bulunamadı" in result.assistant_reply.lower()
        assert result.finalizer_model == "none(empty_data_guard)"

    def test_nonempty_events_passes_to_quality_finalizer(self):
        """When tool data has real events, deterministic calendar guard handles it.

        Issue #1215: All calendar reads now use the deterministic path to
        prevent hallucinated times/titles, even when data is non-empty.
        """
        mock_llm = Mock()
        mock_llm.complete_text.return_value = "Bugün 2 toplantınız var efendim."
        pipeline = FinalizationPipeline(
            quality=QualityFinalizer(finalizer_llm=mock_llm),
        )

        ctx = _make_ctx(
            tool_results=[{
                "tool": "calendar.list_events",
                "success": True,
                "raw_result": {
                    "ok": True,
                    "events": [
                        {"id": "e1", "summary": "Standup", "start": "09:00"},
                        {"id": "e2", "summary": "1on1", "start": "14:00"},
                    ],
                    "total_count": 2,
                },
                "result_summary": "2 events",
            }],
            orchestrator_output=_make_output(route="calendar", calendar_intent="query"),
        )

        result = pipeline.run(ctx)
        # Issue #1215: deterministic_calendar guard intercepts before quality
        mock_llm.complete_text.assert_not_called()
        assert result.finalizer_model == "none(deterministic_calendar)"

    def test_smalltalk_not_affected_by_empty_data_guard(self):
        """Smalltalk route should never trigger the empty-data guard."""
        mock_llm = Mock()
        mock_llm.complete_text.return_value = "İyiyim efendim, siz nasılsınız?"
        pipeline = FinalizationPipeline(
            quality=QualityFinalizer(finalizer_llm=mock_llm),
        )

        ctx = _make_ctx(
            tool_results=[],
            orchestrator_output=_make_output(
                route="smalltalk", calendar_intent="",
                assistant_reply="İyiyim efendim.",
                tool_plan=[],
            ),
        )

        result = pipeline.run(ctx)
        # Should NOT get "bulunamadı" message
        assert "bulunamadı" not in result.assistant_reply.lower()


class TestPipelineAllToolsFailedGuard:
    """Pipeline.run() should handle all-tools-failed via _default_fallback."""

    def test_all_tools_failed_gets_error_via_hard_failure_check(self):
        """When all tools fail with success=False, _check_hard_failures catches it."""
        pipeline = FinalizationPipeline()

        ctx = _make_ctx(
            tool_results=[{
                "tool": "calendar.list_events",
                "success": False,
                "error": "Google Calendar auth failed",
            }],
            orchestrator_output=_make_output(route="calendar", calendar_intent="query"),
        )

        result = pipeline.run(ctx)
        assert "başarısız" in result.assistant_reply.lower()
        assert result.finalizer_model == "none(error)"
