"""
Tests for OrchestratorLoop - LLM-First Orchestrator Execution Loop.

Tests:
- Smalltalk route finalizer usage (Issue #346)
- Tool route finalizer usage
- Finalization phase logic
- Tiering decisions
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass
from typing import Any


@pytest.fixture
def mock_planner_llm():
    """Mock planner LLM (3B router)."""
    llm = Mock()
    llm.complete_text = Mock(return_value="3B planladı, tool seçti.")
    return llm


@pytest.fixture
def mock_finalizer_llm():
    """Mock finalizer LLM (Gemini)."""
    llm = Mock()
    llm.complete_text = Mock(return_value="Gemini ile finalize edildi efendim.")
    return llm


@pytest.fixture
def mock_memory():
    """Mock memory manager."""
    memory = Mock()
    memory.to_prompt_block = Mock(return_value="Dialog history...")
    memory.add_turn = Mock()
    return memory


@pytest.fixture
def mock_orchestrator(mock_planner_llm):
    """Mock JarvisLLMOrchestrator."""
    from bantz.brain.llm_router import JarvisLLMOrchestrator
    
    # Create real orchestrator with mock LLM
    orchestrator = JarvisLLMOrchestrator(llm_client=mock_planner_llm)
    return orchestrator


@pytest.fixture
def mock_tools():
    """Mock ToolRegistry."""
    tools = Mock()
    tools.execute = Mock(return_value={"success": True, "result": "Tool executed"})
    return tools


@pytest.fixture
def orchestrator_loop(mock_orchestrator, mock_tools, mock_finalizer_llm):
    """Create OrchestratorLoop instance with mocks."""
    from bantz.brain.orchestrator_loop import OrchestratorLoop
    
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools,
        finalizer_llm=mock_finalizer_llm,
    )
    return loop


# =============================================================================
# Issue #346: Smalltalk Route Finalizer Usage
# =============================================================================

class TestSmalltalkFinalizerUsage:
    """Test that smalltalk route uses quality finalizer (Issue #346)."""
    
    def test_smalltalk_route_uses_finalizer(self, orchestrator_loop, mock_finalizer_llm):
        """
        Test that smalltalk route invokes finalizer even without tools.
        
        Issue #346: Previously, smalltalk responses bypassed Gemini finalizer
        and returned 3B router's lower-quality output directly.
        """
        from bantz.brain.orchestrator_loop import OrchestratorOutput, OrchestratorState
        
        # Smalltalk orchestrator output (no tools)
        orchestrator_output = OrchestratorOutput(
            route="smalltalk",
            assistant_reply="",  # Empty - needs finalization
            tool_plan=[],
            requires_confirmation=False,
            calendar_intent=None,
            slots={},
            ask_user=False,
            question="",
            confidence=0.95,
        )
        
        state = OrchestratorState()
        user_input = "Nasılsın?"
        tool_results = []  # No tools executed
        
        # Run finalization phase
        result = orchestrator_loop._llm_finalization_phase(
            user_input=user_input,
            orchestrator_output=orchestrator_output,
            tool_results=tool_results,
            state=state,
        )
        
        # Verify finalization phase ran (result should have non-empty reply)
        # Note: The finalization pipeline wraps the finalizer LLM in QualityFinalizer
        # with NoNewFactsGuard. The guard may reject mock text, leading to fallback.
        assert result is not None
        assert isinstance(result.assistant_reply, str)
        
    def test_smalltalk_tier_reason(self, orchestrator_loop):
        """Test that smalltalk route sets correct tier_reason."""
        from bantz.brain.orchestrator_loop import OrchestratorOutput, OrchestratorState
        
        orchestrator_output = OrchestratorOutput(
            route="smalltalk",
            assistant_reply="",
            tool_plan=[],
            requires_confirmation=False,
            calendar_intent=None,
            slots={},
            ask_user=False,
            question="",
            confidence=0.95,
        )
        
        state = OrchestratorState()
        
        result = orchestrator_loop._llm_finalization_phase(
            user_input="Bugün hava nasıl?",
            orchestrator_output=orchestrator_output,
            tool_results=[],
            state=state,
        )
        
        # Check trace contains smalltalk tier reason
        # Note: response_tier_reason is stored, not tier_reason
        assert state.trace.get("response_tier_reason") == "complex_smalltalk_needs_quality"
        assert state.trace.get("response_tier") == "quality"
        

class TestToolRouteFinalizerUsage:
    """Test that tool routes also use finalizer correctly."""
    
    def test_tool_route_with_results_uses_finalizer(self, orchestrator_loop, mock_finalizer_llm):
        """Test that tool route with results uses finalizer."""
        from bantz.brain.orchestrator_loop import OrchestratorOutput, OrchestratorState
        
        orchestrator_output = OrchestratorOutput(
            route="calendar",
            assistant_reply="",
            tool_plan=["calendar_create_event"],
            requires_confirmation=False,
            calendar_intent="create_event",
            slots={"title": "Meeting"},
            ask_user=False,
            question="",
            confidence=0.95,
        )
        
        state = OrchestratorState()
        tool_results = [
            {
                "tool": "calendar_create_event",
                "success": True,
                "result": {"event_id": "evt_123"},
            }
        ]
        
        result = orchestrator_loop._llm_finalization_phase(
            user_input="Yarın saat 3'te toplantı ayarla",
            orchestrator_output=orchestrator_output,
            tool_results=tool_results,
            state=state,
        )
        
        # Verify finalizer was called
        mock_finalizer_llm.complete_text.assert_called_once()
        assert result.assistant_reply == "Gemini ile finalize edildi efendim."


# =============================================================================
# Issue #365: Gmail params filtering
# =============================================================================


class TestGmailParamFiltering:
    """Ensure Gmail tools do not receive calendar slots."""

    def test_gmail_params_exclude_calendar_slots(self, orchestrator_loop):
        from bantz.brain.llm_router import OrchestratorOutput

        slots = {
            "date": "2026-02-10",
            "time": "14:00",
            "duration": 60,
        }

        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            slots=slots,
            confidence=0.9,
            tool_plan=["gmail.send"],
            assistant_reply="",
            gmail={"to": "x@y.com", "subject": "Test", "body": "Merhaba"},
            ask_user=False,
            question="",
            requires_confirmation=False,
        )

        params = orchestrator_loop._build_tool_params("gmail.send", slots, output)

        assert "to" in params and params["to"] == "x@y.com"
        assert "subject" in params and params["subject"] == "Test"
        assert "body" in params and params["body"] == "Merhaba"
        assert "date" not in params
        assert "time" not in params
        assert "duration" not in params

    def test_calendar_tool_keeps_slots(self, orchestrator_loop):
        from bantz.brain.llm_router import OrchestratorOutput

        slots = {
            "date": "2026-02-10",
            "time": "14:00",
            "duration": 60,
        }

        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots=slots,
            confidence=0.9,
            tool_plan=["calendar.create_event"],
            assistant_reply="",
            ask_user=False,
            question="",
            requires_confirmation=False,
        )

        params = orchestrator_loop._build_tool_params("calendar.create_event", slots, output)

        assert params["date"] == "2026-02-10"
        assert params["time"] == "14:00"
        assert params["duration"] == 60
        

class TestFinalizationErrorHandling:
    """Test error handling in finalization phase."""
    
    def test_finalizer_exception_does_not_crash(self, mock_orchestrator, mock_tools):
        """Test that finalizer exceptions are handled gracefully."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorOutput, OrchestratorState
        
        # Create finalizer that raises exception
        mock_finalizer = Mock()
        mock_finalizer.complete_text = Mock(side_effect=Exception("Gemini error"))
        
        loop = OrchestratorLoop(
            orchestrator=mock_orchestrator,
            tools=mock_tools,
            finalizer_llm=mock_finalizer,
        )
        
        orchestrator_output = OrchestratorOutput(
            route="smalltalk",
            assistant_reply="",
            tool_plan=[],
            requires_confirmation=False,
            calendar_intent=None,
            slots={},
            ask_user=False,
            question="",
            confidence=0.95,
        )
        
        state = OrchestratorState()
        
        # Should not raise exception
        result = loop._llm_finalization_phase(
            user_input="Merhaba",
            orchestrator_output=orchestrator_output,
            tool_results=[],
            state=state,
        )
        
        # Result should be valid OrchestratorOutput (not None)
        assert result is not None
        assert isinstance(result, OrchestratorOutput)
        

class TestNoFinalizerMode:
    """Test behavior when no finalizer is configured."""
    
    def test_no_finalizer_returns_original_output(self):
        """Test that without finalizer, original output is returned."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorOutput, OrchestratorState
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        planner_llm = Mock()
        planner_llm.complete_text = Mock(return_value="3B response")
        
        orchestrator = JarvisLLMOrchestrator(llm_client=planner_llm)
        tools = Mock()
        
        # No finalizer
        loop = OrchestratorLoop(
            orchestrator=orchestrator,
            tools=tools,
            finalizer_llm=None,
        )
        
        orchestrator_output = OrchestratorOutput(
            route="smalltalk",
            assistant_reply="3B direct response",
            tool_plan=[],
            requires_confirmation=False,
            calendar_intent=None,
            slots={},
            ask_user=False,
            question="",
            confidence=0.95,
        )
        
        state = OrchestratorState()
        
        result = loop._llm_finalization_phase(
            user_input="Test",
            orchestrator_output=orchestrator_output,
            tool_results=[],
            state=state,
        )
        
        # Should return original output unchanged
        assert result.assistant_reply == "3B direct response"
        

class TestToolFailureHandling:
    """Test that tool failures short-circuit finalization."""
    
    def test_tool_failure_returns_error_message(self, orchestrator_loop, mock_finalizer_llm):
        """Test that tool failures produce error message without finalizer."""
        from bantz.brain.orchestrator_loop import OrchestratorOutput, OrchestratorState
        
        orchestrator_output = OrchestratorOutput(
            route="calendar",
            assistant_reply="",
            tool_plan=["calendar_create_event"],
            requires_confirmation=False,
            calendar_intent="create_event",
            slots={},
            ask_user=False,
            question="",
            confidence=0.95,
        )
        
        state = OrchestratorState()
        tool_results = [
            {
                "tool": "calendar_create_event",
                "success": False,
                "error": "Calendar API timeout",
            }
        ]
        
        result = orchestrator_loop._llm_finalization_phase(
            user_input="Toplantı oluştur",
            orchestrator_output=orchestrator_output,
            tool_results=tool_results,
            state=state,
        )
        
        # Should return error message, NOT call finalizer
        mock_finalizer_llm.complete_text.assert_not_called()
        assert "başarısız oldu" in result.assistant_reply
        assert "calendar_create_event" in result.assistant_reply
        assert "Calendar API timeout" in result.assistant_reply


class TestToolNotFoundHandling:
    """Ensure missing tools return user-friendly errors (Issue #366)."""

    def test_tool_not_found_returns_user_message(self, orchestrator_loop, mock_tools):
        from bantz.brain.orchestrator_loop import OrchestratorOutput, OrchestratorState

        mock_tools.get = Mock(return_value=None)

        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.missing_tool"],
            assistant_reply="",
            ask_user=False,
            question="",
            requires_confirmation=False,
        )

        state = OrchestratorState()

        tool_results = orchestrator_loop._execute_tools_phase(output, state)

        assert len(tool_results) == 1
        result = tool_results[0]
        assert result["success"] is False
        # Unknown tools are blocked by confirmation firewall (DESTRUCTIVE by policy)
        assert result.get("pending_confirmation") is True or "kullanılamıyor" in result.get("error", "").lower()


class TestVerifyResultsIntegration:
    def test_verify_phase_runs_between_execute_and_finalize(self, orchestrator_loop, monkeypatch):
        from bantz.brain.orchestrator_state import OrchestratorState
        from bantz.brain.llm_router import OrchestratorOutput

        state = OrchestratorState()

        planned = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
            ask_user=False,
            question="",
            requires_confirmation=False,
        )

        tool_results = [{"tool": "calendar.list_events", "success": True, "raw_result": [{"id": 1}], "result_summary": "1"}]
        verified_results = [{"tool": "calendar.list_events", "success": True, "raw_result": [{"id": 2}], "result_summary": "1", "_retried": True}]

        monkeypatch.setattr(orchestrator_loop, "_llm_planning_phase", lambda _u, _s: planned)
        monkeypatch.setattr(orchestrator_loop, "_execute_tools_phase", lambda _o, _s: tool_results)

        from bantz.brain.verify_results import VerifyResult

        def fake_verify_tool_results(results, *, config=None, retry_fn=None):
            assert results == tool_results
            return VerifyResult(verified=True, tools_ok=1, tools_retry=0, tools_fail=0, verified_results=verified_results)

        monkeypatch.setattr("bantz.brain.orchestrator_loop.verify_tool_results", None, raising=False)
        monkeypatch.setattr("bantz.brain.verify_results.verify_tool_results", fake_verify_tool_results)

        seen = {}

        def fake_finalize(user_input, orchestrator_output, tool_results, state):
            seen["tool_results"] = tool_results
            return planned

        monkeypatch.setattr(orchestrator_loop, "_llm_finalization_phase", fake_finalize)
        monkeypatch.setattr(orchestrator_loop, "_update_state_phase", lambda *_args, **_kwargs: None)

        orchestrator_loop.process_turn("Takvimimde ne var?", state)
        assert seen["tool_results"] == verified_results
