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
        
        # Verify finalizer was called
        mock_finalizer_llm.complete_text.assert_called_once()
        
        # Verify result contains finalized text
        assert result.assistant_reply == "Gemini ile finalize edildi efendim."
        
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
        assert state.trace.get("response_tier_reason") == "smalltalk_route_always_quality"
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
