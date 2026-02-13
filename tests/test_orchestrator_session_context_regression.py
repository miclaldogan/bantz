"""Regression tests for Issue #359: session_context from state not build_session_context()

Problem: build_session_context() called every turn, ignoring state.session_context
Solution: Use state.session_context if available, build_session_context() as fallback
"""

import pytest
from unittest.mock import Mock, patch
from bantz.brain.orchestrator_state import OrchestratorState


def test_orchestrator_state_has_session_context_field():
    """OrchestratorState should have session_context field (Issue #359)."""
    state = OrchestratorState()
    
    # Should have session_context field
    assert hasattr(state, 'session_context')
    
    # Should default to None
    assert state.session_context is None
    
    # Should be settable
    state.session_context = {"timezone": "America/New_York"}
    assert state.session_context["timezone"] == "America/New_York"


def test_session_context_preserved_in_state():
    """Session context with timezone/locale should be preserved in state."""
    state = OrchestratorState()
    
    # Set user preferences
    state.session_context = {
        "timezone": "Europe/London",
        "locale": "en_GB",
        "session_id": "test-session-123",
        "user_preferences": {
            "work_hours": "9-17"
        }
    }
    
    # Verify all fields preserved
    assert state.session_context["timezone"] == "Europe/London"
    assert state.session_context["locale"] == "en_GB"
    assert state.session_context["session_id"] == "test-session-123"
    assert state.session_context["user_preferences"]["work_hours"] == "9-17"


def test_session_context_independent_from_conversation_history():
    """session_context should be independent from conversation_history."""
    state = OrchestratorState()
    
    # Set session context
    state.session_context = {"timezone": "Asia/Tokyo"}
    
    # Add conversation turns
    state.add_conversation_turn("hello", "hi there")
    state.add_conversation_turn("what time is it", "It's 3pm")
    
    # Session context should remain unchanged
    assert state.session_context == {"timezone": "Asia/Tokyo"}
    
    # Conversation history should be separate
    assert len(state.conversation_history) == 2


def test_orchestrator_loop_uses_state_session_context():
    """OrchestratorLoop should use state.session_context if available."""
    from bantz.brain.orchestrator_loop import OrchestratorLoop
    from bantz.brain.llm_router import JarvisLLMOrchestrator
    from bantz.agent.tools import ToolRegistry
    
    # Create state with custom session_context
    state = OrchestratorState()
    state.session_context = {
        "timezone": "America/New_York",
        "locale": "en_US",
        "session_id": "custom-123"
    }
    
    # Mock orchestrator
    mock_orch = Mock(spec=JarvisLLMOrchestrator)
    mock_orch.route = Mock(return_value=Mock(
        route="chat",
        calendar_intent="none",
        confidence=0.9,
        tool_plan=[],
        assistant_reply="Test reply",
        slots={},
        requires_confirmation=False,
        ask_user=False,
        question=None,
        confirmation_prompt=None,
        reasoning_summary=None,
        memory_update=None
    ))


def test_orchestrator_loop_fallback_to_build_when_state_none():
    """OrchestratorLoop should call build_session_context() when state.session_context is None."""
    from bantz.brain.orchestrator_loop import OrchestratorLoop
    from bantz.brain.llm_router import JarvisLLMOrchestrator
    from bantz.agent.tools import ToolRegistry
    
    # Create state WITHOUT session_context
    state = OrchestratorState()
    assert state.session_context is None
    
    # Mock orchestrator
    mock_orch = Mock(spec=JarvisLLMOrchestrator)
    mock_orch.route = Mock(return_value=Mock(
        route="chat",
        calendar_intent="none",
        confidence=0.9,
        tool_plan=[],
        assistant_reply="Test reply",
        slots={},
        requires_confirmation=False,
        ask_user=False,
        question=None,
        confirmation_prompt=None,
        reasoning_summary=None,
        memory_update=None
    ))
    
    # Mock tools
    mock_tools = Mock(spec=ToolRegistry)
    
    from bantz.brain.orchestrator_loop import OrchestratorConfig
    loop = OrchestratorLoop(
        orchestrator=mock_orch,
        tools=mock_tools,
        config=OrchestratorConfig(debug=False, enable_safety_guard=False),
        event_bus=Mock()
    )

    # Patch the session context cache's get_or_build method
    with patch.object(loop._session_ctx_cache, 'get_or_build') as mock_build:
        built_context = {"timezone": "UTC", "locale": "en_GB"}
        mock_build.return_value = built_context
        
        # Execute turn
        loop.run_full_cycle(user_input="test", state=state)
        
        # get_or_build SHOULD be called (state has no session_context)
        mock_build.assert_called_once()
        
        # Router should receive built session_context (may have extra keys added by loop)
        call_kwargs = mock_orch.route.call_args[1]
        assert call_kwargs['session_context']['timezone'] == "UTC"


def test_timezone_preserved_across_multiple_turns():
    """User timezone should be preserved across multiple turns."""
    from bantz.brain.orchestrator_loop import OrchestratorLoop
    from bantz.brain.llm_router import JarvisLLMOrchestrator
    from bantz.agent.tools import ToolRegistry
    
    state = OrchestratorState()
    state.session_context = {"timezone": "Asia/Tokyo", "locale": "ja_JP"}
    
    mock_orch = Mock(spec=JarvisLLMOrchestrator)
    mock_orch.route = Mock(return_value=Mock(
        route="chat",
        calendar_intent="none",
        confidence=0.9,
        tool_plan=[],
        assistant_reply="Test",
        slots={},
        requires_confirmation=False,
        ask_user=False,
        question=None,
        confirmation_prompt=None,
        reasoning_summary=None,
        memory_update=None
    ))
    
    mock_tools = Mock(spec=ToolRegistry)
    
    from bantz.brain.orchestrator_loop import OrchestratorConfig
    loop = OrchestratorLoop(
        orchestrator=mock_orch,
        tools=mock_tools,
        config=OrchestratorConfig(debug=False, enable_safety_guard=False),
        event_bus=Mock()
    )

    with patch.object(loop._session_ctx_cache, 'get_or_build') as mock_build:
        mock_build.return_value = {"timezone": "UTC"}  # Should never be used
        
        # Turn 1
        loop.run_full_cycle(user_input="first", state=state)
        assert mock_orch.route.call_args[1]['session_context']['timezone'] == "Asia/Tokyo"
        
        # Turn 2 - same state
        loop.run_full_cycle(user_input="second", state=state)
        assert mock_orch.route.call_args[1]['session_context']['timezone'] == "Asia/Tokyo"
        
        # build_session_context should never be called
        mock_build.assert_not_called()

