"""
Tests for Issue #1273: ReAct Loop (Düşün → Yap → Gözlemle → Tekrar Düşün).

Tests:
- Single-shot backward compat (status="done" → 1 iteration)
- Multi-step loop (status="needs_more_info" → multiple iterations)
- Max iteration guard
- Timeout guard
- Confirmation breaks loop
- ask_user breaks loop
- Empty tool results breaks loop
- OrchestratorState react fields
- OrchestratorOutput status field
- react_replan method
"""

import os
import time
import json
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from dataclasses import dataclass, replace, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_planner_llm():
    """Mock planner LLM that returns valid JSON."""
    llm = Mock()
    llm.complete_text = Mock(return_value=json.dumps({
        "route": "calendar",
        "calendar_intent": "query",
        "gmail_intent": "none",
        "slots": {"window_hint": "today"},
        "gmail": {},
        "confidence": 0.9,
        "tool_plan": ["calendar.list_events"],
        "status": "done",
        "ask_user": False,
        "question": "",
        "requires_confirmation": False,
    }))
    llm.backend_name = "ollama"
    llm.model_name = "qwen2.5-coder:7b"
    return llm


@pytest.fixture
def mock_finalizer_llm():
    """Mock finalizer LLM (Gemini)."""
    llm = Mock()
    llm.complete_text = Mock(return_value="Bugün 2 etkinliğiniz var efendim.")
    return llm


@pytest.fixture
def mock_tools():
    """Mock ToolRegistry."""
    tools = Mock()
    tools.execute = Mock(return_value={"success": True, "result": "Tool executed"})
    # Provide tool names for sync
    tools.list_names = Mock(return_value=["calendar.list_events", "calendar.create_event", "gmail.send"])
    return tools


@pytest.fixture
def orchestrator_loop(mock_planner_llm, mock_tools, mock_finalizer_llm):
    """Create OrchestratorLoop with mocks."""
    from bantz.brain.orchestrator_loop import OrchestratorLoop

    loop = OrchestratorLoop(
        orchestrator=Mock(),
        tools=mock_tools,
        finalizer_llm=mock_finalizer_llm,
    )
    return loop


# ---------------------------------------------------------------------------
# OrchestratorState — react fields
# ---------------------------------------------------------------------------

class TestOrchestratorStateReact:
    """Test OrchestratorState react field management."""

    def test_react_observations_default_empty(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        assert state.react_observations == []
        assert state.react_iteration == 0

    def test_react_observations_in_context(self):
        """react_observations appear in get_context_for_llm when non-empty."""
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        state.react_observations = [
            {"iteration": 1, "tool": "calendar.list_events", "result_summary": "2 events", "success": True}
        ]
        ctx = state.get_context_for_llm()
        assert "react_observations" in ctx
        assert len(ctx["react_observations"]) == 1

    def test_react_observations_absent_when_empty(self):
        """react_observations NOT in context when empty (saves tokens)."""
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        ctx = state.get_context_for_llm()
        assert "react_observations" not in ctx

    def test_reset_clears_react_fields(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        state.react_observations = [{"tool": "x"}]
        state.react_iteration = 2
        state.reset()
        assert state.react_observations == []
        assert state.react_iteration == 0


# ---------------------------------------------------------------------------
# OrchestratorOutput — status field
# ---------------------------------------------------------------------------

class TestOrchestratorOutputStatus:
    """Test OrchestratorOutput status field."""

    def test_default_status_is_done(self):
        from bantz.brain.llm_router import OrchestratorOutput
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
        )
        assert output.status == "done"

    def test_status_needs_more_info(self):
        from bantz.brain.llm_router import OrchestratorOutput
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["gmail.list_messages"],
            assistant_reply="",
            status="needs_more_info",
        )
        assert output.status == "needs_more_info"


# ---------------------------------------------------------------------------
# react_replan method
# ---------------------------------------------------------------------------

class TestReactReplan:
    """Test JarvisLLMOrchestrator.react_replan method."""

    def test_replan_returns_new_output(self, mock_planner_llm):
        from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput

        # LLM returns a "done" response for second iteration
        mock_planner_llm.complete_text.return_value = json.dumps({
            "route": "gmail",
            "calendar_intent": "none",
            "gmail_intent": "send",
            "slots": {},
            "gmail": {"to": "test@test.com", "body": "hello"},
            "confidence": 0.85,
            "tool_plan": ["gmail.send"],
            "status": "done",
            "ask_user": False,
            "question": "",
            "requires_confirmation": True,
        })

        orchestrator = JarvisLLMOrchestrator(llm_client=mock_planner_llm)

        prev = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["gmail.list_messages"],
            assistant_reply="",
            status="needs_more_info",
        )

        observations = [
            {"iteration": 1, "tool": "gmail.list_messages", "result_summary": "5 messages found", "success": True},
        ]

        result = orchestrator.react_replan(
            user_input="list my emails and reply to the first one",
            previous_output=prev,
            observations=observations,
            iteration=2,
        )

        assert result.status == "done"
        assert result.route in ("gmail", "calendar", "system", "smalltalk", "unknown")
        # LLM was called
        assert mock_planner_llm.complete_text.called

    def test_replan_fallback_on_llm_error(self, mock_planner_llm):
        """When LLM call fails, replan defaults to status='done'."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput

        mock_planner_llm.complete_text.side_effect = RuntimeError("LLM down")

        orchestrator = JarvisLLMOrchestrator(llm_client=mock_planner_llm)

        prev = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
            status="needs_more_info",
        )

        result = orchestrator.react_replan(
            user_input="test",
            previous_output=prev,
            observations=[],
            iteration=2,
        )

        assert result.status == "done"
        assert result.tool_plan == []

    def test_replan_fallback_on_json_parse_error(self, mock_planner_llm):
        """When JSON parse fails, replan defaults to status='done'."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput

        mock_planner_llm.complete_text.return_value = "not json at all!!!"

        orchestrator = JarvisLLMOrchestrator(llm_client=mock_planner_llm)

        prev = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.8,
            tool_plan=["system.status"],
            assistant_reply="",
            status="needs_more_info",
        )

        result = orchestrator.react_replan(
            user_input="test",
            previous_output=prev,
            observations=[{"tool": "x", "success": True, "result_summary": "ok"}],
            iteration=2,
        )

        assert result.status == "done"


# ---------------------------------------------------------------------------
# _react_execute_loop — integration
# ---------------------------------------------------------------------------

class TestReactExecuteLoop:
    """Test the _react_execute_loop shared method."""

    def test_single_shot_one_iteration(self):
        """status='done' → exactly 1 iteration (backward compat)."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
            status="done",
        )

        # Create a minimal mock loop
        loop = Mock()
        loop._execute_tools_phase = Mock(return_value=[
            {"tool": "calendar.list_events", "success": True, "result_summary": "2 events"},
        ])
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()
        loop.orchestrator = Mock()

        # Import and call the method
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        results = OrchestratorLoop._react_execute_loop(
            loop, output, state, "bugün neler var",
        )

        assert len(results) == 1
        assert state.react_iteration == 1
        assert len(state.react_observations) == 1
        # Should NOT call react_replan
        loop.orchestrator.react_replan.assert_not_called()

    def test_multi_step_needs_more_info(self):
        """status='needs_more_info' → multiple iterations."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()

        # First output: needs_more_info → will trigger re-plan
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["gmail.list_messages"],
            assistant_reply="",
            status="needs_more_info",
        )

        # Re-plan returns "done" on second iteration
        replan_output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.85,
            tool_plan=["gmail.send"],
            assistant_reply="",
            status="done",
        )

        loop = Mock()
        loop._execute_tools_phase = Mock(side_effect=[
            [{"tool": "gmail.list_messages", "success": True, "result_summary": "5 msgs"}],
            [{"tool": "gmail.send", "success": True, "result_summary": "sent"}],
        ])
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()
        loop.orchestrator = Mock()
        loop.orchestrator.react_replan = Mock(return_value=replan_output)

        from bantz.brain.orchestrator_loop import OrchestratorLoop
        results = OrchestratorLoop._react_execute_loop(
            loop, output, state, "mailleri listele ve ilkine cevap ver",
        )

        assert len(results) == 2
        assert state.react_iteration == 2
        assert len(state.react_observations) == 2
        loop.orchestrator.react_replan.assert_called_once()

    def test_confirmation_breaks_loop(self):
        """Confirmation pending → loop breaks immediately."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()
        state.add_pending_confirmation({"tool": "gmail.send", "slots": {}})

        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["gmail.send"],
            assistant_reply="",
            status="needs_more_info",
        )

        loop = Mock()
        loop._execute_tools_phase = Mock(return_value=[
            {"tool": "gmail.send", "success": False, "result_summary": "blocked", "error": "confirmation required"},
        ])
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()
        loop.orchestrator = Mock()

        from bantz.brain.orchestrator_loop import OrchestratorLoop
        results = OrchestratorLoop._react_execute_loop(
            loop, output, state, "mail gönder",
        )

        # Should NOT re-plan because confirmation is pending
        loop.orchestrator.react_replan.assert_not_called()
        assert state.react_iteration == 1

    def test_max_iterations_guard(self):
        """Loop stops at BANTZ_REACT_MAX_ITER."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()

        # Always return needs_more_info
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
            status="needs_more_info",
        )

        loop = Mock()
        loop._execute_tools_phase = Mock(return_value=[
            {"tool": "calendar.list_events", "success": True, "result_summary": "ok"},
        ])
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()
        loop.orchestrator = Mock()
        loop.orchestrator.react_replan = Mock(return_value=output)  # Always needs_more_info

        from bantz.brain.orchestrator_loop import OrchestratorLoop
        with patch.dict(os.environ, {"BANTZ_REACT_MAX_ITER": "2"}):
            results = OrchestratorLoop._react_execute_loop(
                loop, output, state, "test",
            )

        # Should have run exactly 2 iterations
        assert state.react_iteration == 2
        # Re-plan called once (after iter 1, but iter 2 breaks at max check)
        assert loop.orchestrator.react_replan.call_count == 1

    def test_trace_metadata_recorded(self):
        """ReAct trace metadata is recorded in state.trace."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()
        output = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.95,
            tool_plan=["time.now"],
            assistant_reply="",
            status="done",
        )

        loop = Mock()
        loop._execute_tools_phase = Mock(return_value=[
            {"tool": "time.now", "success": True, "result_summary": "14:30"},
        ])
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()

        from bantz.brain.orchestrator_loop import OrchestratorLoop
        OrchestratorLoop._react_execute_loop(loop, output, state, "saat kaç")

        assert "react" in state.trace
        assert state.trace["react"]["iterations"] == 1
        assert state.trace["react"]["observations_count"] == 1
        assert "elapsed_ms" in state.trace["react"]

    def test_empty_tool_results_breaks_loop(self):
        """No tool results → loop breaks (nothing to observe)."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["gmail.list_messages"],
            assistant_reply="",
            status="needs_more_info",
        )

        loop = Mock()
        loop._execute_tools_phase = Mock(return_value=[])  # No results
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()
        loop.orchestrator = Mock()

        from bantz.brain.orchestrator_loop import OrchestratorLoop
        results = OrchestratorLoop._react_execute_loop(
            loop, output, state, "test",
        )

        assert results == []
        loop.orchestrator.react_replan.assert_not_called()

    def test_replan_failure_breaks_loop(self):
        """If react_replan raises, the loop breaks gracefully."""
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["gmail.list_messages"],
            assistant_reply="",
            status="needs_more_info",
        )

        loop = Mock()
        loop._execute_tools_phase = Mock(return_value=[
            {"tool": "gmail.list_messages", "success": True, "result_summary": "5 msgs"},
        ])
        loop._verify_results_phase = Mock(side_effect=lambda r, s: r)
        loop._save_calendar_context = Mock()
        loop.orchestrator = Mock()
        loop.orchestrator.react_replan = Mock(side_effect=RuntimeError("LLM down"))

        from bantz.brain.orchestrator_loop import OrchestratorLoop
        results = OrchestratorLoop._react_execute_loop(
            loop, output, state, "test",
        )

        # Should have 1 result from the first iteration
        assert len(results) == 1
        assert state.react_iteration == 1


# ---------------------------------------------------------------------------
# JSON parse — status field extraction
# ---------------------------------------------------------------------------

class TestStatusFieldExtraction:
    """Test that the status field is extracted from LLM JSON."""

    def test_status_done_extracted(self, mock_planner_llm):
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_planner_llm.complete_text.return_value = json.dumps({
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "status": "done",
        })

        orch = JarvisLLMOrchestrator(llm_client=mock_planner_llm)
        result = orch.route(user_input="bugün neler var")
        assert result.status == "done"

    def test_status_needs_more_info_extracted(self, mock_planner_llm):
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_planner_llm.complete_text.return_value = json.dumps({
            "route": "gmail",
            "gmail_intent": "list",
            "calendar_intent": "none",
            "slots": {},
            "gmail": {},
            "confidence": 0.9,
            "tool_plan": ["gmail.list_messages"],
            "status": "needs_more_info",
        })

        orch = JarvisLLMOrchestrator(llm_client=mock_planner_llm)
        result = orch.route(user_input="list my emails and reply to the first")
        assert result.status == "needs_more_info"

    def test_status_defaults_to_done(self, mock_planner_llm):
        """When status is missing from JSON, default to 'done'."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_planner_llm.complete_text.return_value = json.dumps({
            "route": "system",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": ["time.now"],
        })

        orch = JarvisLLMOrchestrator(llm_client=mock_planner_llm)
        result = orch.route(user_input="saat kaç")
        assert result.status == "done"

    def test_invalid_status_defaults_to_done(self, mock_planner_llm):
        """Invalid status values default to 'done'."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_planner_llm.complete_text.return_value = json.dumps({
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "status": "invalid_nonsense",
        })

        orch = JarvisLLMOrchestrator(llm_client=mock_planner_llm)
        result = orch.route(user_input="bugün neler var")
        assert result.status == "done"
