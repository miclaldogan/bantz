"""Tests for Issue #1277: Self-Reflection — Tool Result Verification.

Tests should_reflect trigger heuristic, prompt building,
response parsing, and the full reflect() pipeline.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from bantz.brain.reflection import (
    ReflectionConfig,
    ReflectionResult,
    should_reflect,
    build_reflection_prompt,
    parse_reflection_response,
    reflect,
    _is_empty_result,
    _is_error_result,
)


# ====================================================================
# Helper result factories
# ====================================================================

def _ok_result(tool="calendar.list_events", summary="2 events found"):
    return {
        "tool": tool,
        "success": True,
        "result": '{"ok": true}',
        "result_summary": summary,
        "raw_result": {"ok": True},
    }


def _error_result(tool="gmail.send", error="invalid recipient"):
    return {
        "tool": tool,
        "success": False,
        "result": '{"ok": false}',
        "result_summary": f"Error: {error}",
        "error": error,
        "raw_result": {"ok": False, "error": error},
    }


def _empty_result(tool="calendar.create_event"):
    return {
        "tool": tool,
        "success": True,
        "result": "",
        "result_summary": "",
        "raw_result": None,
    }


# ====================================================================
# _is_empty_result tests
# ====================================================================

class TestIsEmptyResult:
    def test_none_raw_no_summary(self):
        assert _is_empty_result({"result": None, "result_summary": ""})

    def test_empty_string_raw(self):
        assert _is_empty_result({"result": "  ", "result_summary": "x"})

    def test_empty_list_raw(self):
        assert _is_empty_result({"raw_result": [], "result_summary": "x"})

    def test_empty_dict_raw(self):
        assert _is_empty_result({"raw_result": {}, "result_summary": "x"})

    def test_non_empty(self):
        assert not _is_empty_result({"result": '{"ok": true}', "result_summary": "done"})

    def test_list_with_items(self):
        assert not _is_empty_result({"raw_result": [1, 2], "result_summary": ""})


# ====================================================================
# _is_error_result tests
# ====================================================================

class TestIsErrorResult:
    def test_success_false(self):
        assert _is_error_result({"success": False})

    def test_error_key(self):
        assert _is_error_result({"error": "timeout"})

    def test_success_true_no_error(self):
        assert not _is_error_result({"success": True})

    def test_empty_dict(self):
        assert not _is_error_result({})


# ====================================================================
# should_reflect tests
# ====================================================================

class TestShouldReflect:
    def test_no_results(self):
        trigger, cause = should_reflect([], 0.9)
        assert not trigger

    def test_all_ok_high_confidence(self):
        results = [_ok_result()]
        trigger, cause = should_reflect(results, 0.9)
        assert not trigger

    def test_error_result_triggers(self):
        results = [_error_result()]
        trigger, cause = should_reflect(results, 0.9)
        assert trigger
        assert "tool_error" in cause

    def test_empty_non_valid_triggers(self):
        """Empty result from a tool NOT in valid_empty_tools should trigger."""
        results = [_empty_result(tool="calendar.create_event")]
        trigger, cause = should_reflect(results, 0.9)
        assert trigger
        assert "empty_result" in cause

    def test_empty_valid_tool_no_trigger(self):
        """Empty result from a valid_empty_tool should NOT trigger."""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "result": "",
            "result_summary": "",
            "raw_result": [],
        }]
        trigger, cause = should_reflect(results, 0.9)
        assert not trigger

    def test_low_confidence_triggers(self):
        results = [_ok_result()]
        trigger, cause = should_reflect(results, 0.5)
        assert trigger
        assert "low_confidence" in cause

    def test_confidence_at_threshold_no_trigger(self):
        results = [_ok_result()]
        trigger, cause = should_reflect(results, 0.7)
        assert not trigger

    def test_disabled_via_config(self):
        cfg = ReflectionConfig(enabled=False)
        results = [_error_result()]
        trigger, cause = should_reflect(results, 0.3, config=cfg)
        assert not trigger

    def test_custom_threshold(self):
        cfg = ReflectionConfig(confidence_threshold=0.5)
        results = [_ok_result()]
        trigger, _ = should_reflect(results, 0.55, config=cfg)
        assert not trigger
        trigger, _ = should_reflect(results, 0.45, config=cfg)
        assert trigger

    def test_error_takes_priority_over_confidence(self):
        """Error trigger should fire even with high confidence."""
        results = [_error_result()]
        trigger, cause = should_reflect(results, 0.95)
        assert trigger
        assert "tool_error" in cause  # error before confidence check

    def test_multiple_results_one_error(self):
        results = [_ok_result(), _error_result(), _ok_result()]
        trigger, cause = should_reflect(results, 0.9)
        assert trigger
        assert "tool_error" in cause


# ====================================================================
# build_reflection_prompt tests
# ====================================================================

class TestBuildReflectionPrompt:
    def test_contains_user_input(self):
        prompt = build_reflection_prompt(
            "yarınki toplantılarımı göster",
            [_ok_result()],
        )
        assert "yarınki toplantılarımı göster" in prompt

    def test_contains_tool_name(self):
        prompt = build_reflection_prompt(
            "test",
            [_ok_result(tool="calendar.list_events")],
        )
        assert "calendar.list_events" in prompt

    def test_error_result_prioritized(self):
        """Error result should be picked over ok results."""
        results = [_ok_result(), _error_result(tool="gmail.send")]
        prompt = build_reflection_prompt("test", results)
        assert "gmail.send" in prompt

    def test_summary_truncation(self):
        long_summary = "A" * 2000
        results = [_ok_result(summary=long_summary)]
        prompt = build_reflection_prompt("test", results, max_chars=100)
        # The summary portion should be capped
        assert len(prompt) < 2000

    def test_contains_json_format_hint(self):
        prompt = build_reflection_prompt("test", [_ok_result()])
        assert "satisfied" in prompt


# ====================================================================
# parse_reflection_response tests
# ====================================================================

class TestParseReflectionResponse:
    def test_valid_json_satisfied(self):
        raw = '{"satisfied": true, "reason": "all good", "corrective_action": null}'
        result = parse_reflection_response(raw)
        assert result.triggered
        assert result.satisfied
        assert result.reason == "all good"
        assert result.corrective_action == ""

    def test_valid_json_not_satisfied(self):
        raw = '{"satisfied": false, "reason": "wrong date", "corrective_action": "retry with correct date"}'
        result = parse_reflection_response(raw)
        assert result.triggered
        assert not result.satisfied
        assert "wrong date" in result.reason
        assert "retry" in result.corrective_action

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"satisfied": false, "reason": "error"}\n```'
        result = parse_reflection_response(raw)
        assert not result.satisfied
        assert result.reason == "error"

    def test_json_embedded_in_text(self):
        raw = 'Here is my analysis: {"satisfied": true, "reason": "ok"} end'
        result = parse_reflection_response(raw)
        assert result.satisfied

    def test_unparseable_fallback(self):
        raw = "I could not understand the request."
        result = parse_reflection_response(raw)
        assert result.triggered
        assert result.satisfied  # don't block on parse failure
        assert "parse_failed" in result.reason

    def test_string_true_satisfied(self):
        raw = '{"satisfied": "true", "reason": "ok"}'
        result = parse_reflection_response(raw)
        assert result.satisfied

    def test_string_false_satisfied(self):
        raw = '{"satisfied": "false", "reason": "nope"}'
        result = parse_reflection_response(raw)
        assert not result.satisfied

    def test_reason_truncated(self):
        long_reason = "X" * 500
        raw = json.dumps({"satisfied": True, "reason": long_reason})
        result = parse_reflection_response(raw)
        assert len(result.reason) <= 300


# ====================================================================
# reflect() full pipeline tests
# ====================================================================

class TestReflect:
    def _mock_llm(self, response: str):
        llm = MagicMock()
        llm.complete_text.return_value = response
        return llm

    def test_not_triggered_high_confidence_ok_results(self):
        llm = self._mock_llm("")
        result = reflect("test", [_ok_result()], 0.9, llm)
        assert not result.triggered
        llm.complete_text.assert_not_called()

    def test_triggered_on_error(self):
        llm = self._mock_llm('{"satisfied": false, "reason": "invalid email"}')
        result = reflect("mail at", [_error_result()], 0.9, llm)
        assert result.triggered
        assert not result.satisfied
        assert "invalid email" in result.reason
        llm.complete_text.assert_called_once()

    def test_triggered_on_low_confidence(self):
        llm = self._mock_llm('{"satisfied": true, "reason": "looks ok"}')
        result = reflect("test", [_ok_result()], 0.5, llm)
        assert result.triggered
        assert result.satisfied
        assert "low_confidence" in result.trigger_cause

    def test_llm_exception_returns_safe_result(self):
        llm = MagicMock()
        llm.complete_text.side_effect = RuntimeError("LLM down")
        result = reflect("test", [_error_result()], 0.9, llm)
        assert result.triggered
        assert result.satisfied  # don't block on LLM failure
        assert "llm_error" in result.reason

    def test_elapsed_ms_tracked(self):
        llm = self._mock_llm('{"satisfied": true, "reason": "ok"}')
        result = reflect("test", [_error_result()], 0.9, llm)
        assert result.elapsed_ms >= 0

    def test_disabled_via_config(self):
        cfg = ReflectionConfig(enabled=False)
        llm = self._mock_llm("")
        result = reflect("test", [_error_result()], 0.3, llm, config=cfg)
        assert not result.triggered
        llm.complete_text.assert_not_called()

    def test_trigger_cause_recorded(self):
        llm = self._mock_llm('{"satisfied": false, "reason": "bad"}')
        result = reflect("test", [_error_result(tool="gmail.send")], 0.9, llm)
        assert "tool_error:gmail.send" in result.trigger_cause

    def test_empty_non_valid_tool_triggers(self):
        llm = self._mock_llm('{"satisfied": false, "reason": "no result"}')
        result = reflect("test", [_empty_result(tool="system.reboot")], 0.9, llm)
        assert result.triggered
        assert "empty_result" in result.trigger_cause

    def test_empty_valid_tool_no_trigger(self):
        llm = self._mock_llm("")
        results = [{
            "tool": "gmail.list_messages",
            "success": True,
            "result": "",
            "result_summary": "",
            "raw_result": [],
        }]
        result = reflect("test", results, 0.9, llm)
        assert not result.triggered


# ====================================================================
# ReflectionResult tests
# ====================================================================

class TestReflectionResult:
    def test_to_trace_dict_not_triggered(self):
        r = ReflectionResult(triggered=False)
        d = r.to_trace_dict()
        assert d == {"triggered": False}

    def test_to_trace_dict_triggered(self):
        r = ReflectionResult(
            triggered=True,
            satisfied=False,
            reason="wrong date parameter",
            corrective_action="retry with 2026-02-15",
            trigger_cause="tool_error:calendar.list_events",
            elapsed_ms=150,
        )
        d = r.to_trace_dict()
        assert d["triggered"]
        assert not d["satisfied"]
        assert "wrong date" in d["reason"]
        assert "retry" in d["corrective_action"]
        assert d["trigger_cause"] == "tool_error:calendar.list_events"
        assert d["elapsed_ms"] == 150

    def test_to_trace_dict_no_corrective_action(self):
        r = ReflectionResult(
            triggered=True, satisfied=True, reason="ok",
        )
        d = r.to_trace_dict()
        assert "corrective_action" not in d  # empty string excluded


# ====================================================================
# Integration: _reflection_phase in OrchestratorLoop
# ====================================================================

class TestReflectionPhaseIntegration:
    """Tests for _reflection_phase method on OrchestratorLoop."""

    def _make_loop(self, llm_response=None, llm_error=None):
        """Create a minimal OrchestratorLoop with mocked orchestrator."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop

        mock_llm = MagicMock()
        if llm_error:
            mock_llm.complete_text.side_effect = llm_error
        else:
            mock_llm.complete_text.return_value = llm_response or '{"satisfied": true, "reason": "ok"}'

        mock_orchestrator = MagicMock()
        mock_orchestrator._llm = mock_llm

        mock_tools = MagicMock()
        mock_tools.names.return_value = []

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            loop = OrchestratorLoop(
                orchestrator=mock_orchestrator,
                tools=mock_tools,
            )

        return loop, mock_llm

    def _make_output(self, confidence=0.9, route="calendar", tool_plan=None):
        from bantz.brain.llm_router import OrchestratorOutput
        return OrchestratorOutput(
            route=route,
            confidence=confidence,
            tool_plan=tool_plan or ["calendar.list_events"],
            assistant_reply="",
            slots={},
            calendar_intent="query",
        )

    def test_reflection_skipped_on_success(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        loop, llm = self._make_loop()
        state = OrchestratorState()
        output = self._make_output(confidence=0.9)
        tool_results = [_ok_result()]

        result = loop._reflection_phase("test", output, tool_results, state)
        assert not result.triggered
        llm.complete_text.assert_not_called()

    def test_reflection_triggered_on_error(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        loop, llm = self._make_loop(
            llm_response='{"satisfied": false, "reason": "bad recipient"}'
        )
        state = OrchestratorState()
        output = self._make_output(confidence=0.9)
        tool_results = [_error_result()]

        result = loop._reflection_phase("mail at", output, tool_results, state)
        assert result.triggered
        assert not result.satisfied
        llm.complete_text.assert_called_once()

        # Check trace was recorded
        assert "reflection" in state.trace
        assert state.trace["reflection"]["triggered"]

    def test_reflection_annotates_tool_results(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        loop, _ = self._make_loop(
            llm_response='{"satisfied": false, "reason": "wrong params"}'
        )
        state = OrchestratorState()
        output = self._make_output(confidence=0.9)
        tool_results = [_error_result()]

        loop._reflection_phase("test", output, tool_results, state)

        # Should have appended a _reflection entry
        reflection_entries = [r for r in tool_results if r.get("tool") == "_reflection"]
        assert len(reflection_entries) == 1
        assert "wrong params" in reflection_entries[0]["result_summary"]

    def test_reflection_no_llm_returns_not_triggered(self):
        """If orchestrator has no _llm, reflection should be skipped."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        from bantz.brain.orchestrator_state import OrchestratorState

        mock_orchestrator = MagicMock(spec=[])  # no _llm attribute
        mock_tools = MagicMock()
        mock_tools.names.return_value = []

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            loop = OrchestratorLoop(
                orchestrator=mock_orchestrator,
                tools=mock_tools,
            )

        state = OrchestratorState()
        output = self._make_output()
        result = loop._reflection_phase("test", output, [_error_result()], state)
        assert not result.triggered

    def test_reflection_llm_failure_safe(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        loop, _ = self._make_loop(llm_error=RuntimeError("timeout"))
        state = OrchestratorState()
        output = self._make_output(confidence=0.9)

        result = loop._reflection_phase("test", output, [_error_result()], state)
        # Should not crash, should return safe result
        assert result.triggered
        assert result.satisfied  # fail-open


# ====================================================================
# Edge case tests
# ====================================================================

class TestReflectionEdgeCases:
    def test_no_tool_results(self):
        result = reflect("test", [], 0.9, MagicMock())
        assert not result.triggered

    def test_mixed_results_error_in_middle(self):
        results = [_ok_result(), _error_result(), _ok_result()]
        trigger, cause = should_reflect(results, 0.9)
        assert trigger
        assert "tool_error" in cause

    def test_multiple_errors(self):
        results = [_error_result(tool="a"), _error_result(tool="b")]
        trigger, cause = should_reflect(results, 0.9)
        assert trigger
        assert "a" in cause and "b" in cause

    def test_valid_empty_gmail_messages(self):
        """gmail.list_messages returning [] should NOT trigger reflection."""
        results = [{
            "tool": "gmail.list_messages",
            "success": True,
            "result": "[]",
            "result_summary": "No messages",
            "raw_result": [],
        }]
        trigger, _ = should_reflect(results, 0.9)
        assert not trigger

    def test_valid_empty_calendar_list_events(self):
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "result": "[]",
            "result_summary": "No events",
            "raw_result": [],
        }]
        trigger, _ = should_reflect(results, 0.9)
        assert not trigger
