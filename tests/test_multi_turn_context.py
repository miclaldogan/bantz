"""
Tests for Multi-Turn Context Memory (Issue #339).

Tests that conversation history is preserved across turns to enable
anaphora resolution (e.g., "saat kaçta" referring to previously mentioned event).
"""

import pytest
from unittest.mock import Mock, MagicMock
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig, OrchestratorState
from bantz.brain.llm_router import OrchestratorOutput


@pytest.fixture
def orchestrator_loop():
    """Create OrchestratorLoop for testing."""
    mock_orchestrator = Mock()
    mock_tools = Mock()
    mock_event_bus = Mock()
    
    return OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools,
        event_bus=mock_event_bus,
        config=OrchestratorConfig(enable_safety_guard=False, debug=True),
    )


class TestMultiTurnContextMemory:
    """Test multi-turn context memory (Issue #339)."""
    
    def test_recent_conversation_added_to_session_context(self, orchestrator_loop):
        """
        Test that recent conversation is added to session_context.
        
        Issue #339: Router needs conversation history to resolve anaphoric
        references like "saat kaçta" (what time).
        """
        # Setup state with conversation history
        state = OrchestratorState()
        state.add_conversation_turn(
            user_input="bugün için planımız var mı",
            assistant_reply="Efendim, bugün saat 14:00'te toplantınız var."
        )
        state.add_conversation_turn(
            user_input="kimle",
            assistant_reply="John Smith ile toplantınız var."
        )
        
        # Mock orchestrator to capture session_context
        captured_session_context = None
        def capture_route(**kwargs):
            nonlocal captured_session_context
            captured_session_context = kwargs.get("session_context")
            return OrchestratorOutput(
                route="calendar",
                calendar_intent="query",
                slots={},
                confidence=0.9,
                tool_plan=["calendar.list_events"],
                assistant_reply="",
            )
        
        orchestrator_loop.orchestrator.route = capture_route
        
        # Process new turn
        result, new_state = orchestrator_loop.process_turn("saat kaçta", state)
        
        # Verify session_context contains recent_conversation
        assert captured_session_context is not None
        assert "recent_conversation" in captured_session_context
        
        recent = captured_session_context["recent_conversation"]
        assert len(recent) == 2  # Last 3 turns (we had 2)
        assert recent[0]["user"] == "bugün için planımız var mı"
        assert recent[0]["assistant"] == "Efendim, bugün saat 14:00'te toplantınız var."
        assert recent[1]["user"] == "kimle"
        assert recent[1]["assistant"] == "John Smith ile toplantınız var."
    
    def test_recent_conversation_limited_to_last_3_turns(self, orchestrator_loop):
        """Test that only last 3 turns are included."""
        state = OrchestratorState()
        state.max_history_turns = 10  # Increase limit to test our own limiting
        
        # Add 5 turns
        for i in range(5):
            state.add_conversation_turn(
                user_input=f"user message {i}",
                assistant_reply=f"assistant reply {i}"
            )
        
        captured_session_context = None
        def capture_route(**kwargs):
            nonlocal captured_session_context
            captured_session_context = kwargs.get("session_context")
            return OrchestratorOutput(
                route="smalltalk",
                calendar_intent="none",
                slots={},
                confidence=0.9,
                tool_plan=[],
                assistant_reply="",
            )
        
        orchestrator_loop.orchestrator.route = capture_route
        
        result, new_state = orchestrator_loop.process_turn("test", state)
        
        # Only last 3 turns should be in session_context
        recent = captured_session_context.get("recent_conversation", [])
        assert len(recent) == 3
        
        # Should be last 3: turns 2, 3, 4
        assert recent[0]["user"] == "user message 2"
        assert recent[1]["user"] == "user message 3"
        assert recent[2]["user"] == "user message 4"
    
    def test_empty_conversation_history(self, orchestrator_loop):
        """Test that empty conversation doesn't break session_context."""
        state = OrchestratorState()  # Empty state
        
        captured_session_context = None
        def capture_route(**kwargs):
            nonlocal captured_session_context
            captured_session_context = kwargs.get("session_context")
            return OrchestratorOutput(
                route="smalltalk",
                calendar_intent="none",
                slots={},
                confidence=0.9,
                tool_plan=[],
                assistant_reply="",
            )
        
        orchestrator_loop.orchestrator.route = capture_route
        
        result, new_state = orchestrator_loop.process_turn("merhaba", state)
        
        # session_context should still exist (from build_session_context)
        assert captured_session_context is not None
        
        # recent_conversation should NOT be added if history is empty
        # (conditional check: if conversation_history)
        assert "recent_conversation" not in captured_session_context
    
    def test_anaphora_resolution_example(self, orchestrator_loop):
        """
        Test the exact scenario from Issue #339:
        
        Turn 1: "bugün için planımız var mı" → "bugün için toplantı var"
        Turn 2: "saat kaçta var" → Should resolve "saat kaçta" to meeting time
        """
        state = OrchestratorState()
        state.add_conversation_turn(
            user_input="bugün için planımız var mı",
            assistant_reply="Efendim, bugün saat 14:00'te toplantınız var."
        )
        
        # Mock to verify context is passed
        captured_session_context = None
        def capture_route(**kwargs):
            nonlocal captured_session_context
            captured_session_context = kwargs.get("session_context")
            # Router should be able to see previous turn and understand
            # "saat kaçta" refers to the meeting mentioned before
            return OrchestratorOutput(
                route="calendar",
                calendar_intent="query",
                slots={"event_ref": "toplantı"},  # Resolved from context
                confidence=0.9,
                tool_plan=["calendar.list_events"],
                assistant_reply="",
            )
        
        orchestrator_loop.orchestrator.route = capture_route
        
        result, new_state = orchestrator_loop.process_turn("saat kaçta var", state)
        
        # Verify previous turn is available in session_context
        recent = captured_session_context.get("recent_conversation", [])
        assert len(recent) == 1
        assert "toplantı" in recent[0]["assistant"]
        assert "14:00" in recent[0]["assistant"]
        
        # With this context, router can resolve "saat kaçta" to meeting time query


class TestConversationHistoryPersistence:
    """Test that conversation history is maintained across turns."""
    
    def test_new_turn_added_to_history(self, orchestrator_loop):
        """Test that each turn is added to conversation history."""
        state = OrchestratorState()
        
        mock_output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="Merhaba efendim!",
        )
        orchestrator_loop.orchestrator.route = Mock(return_value=mock_output)
        
        # Process first turn
        result1, state1 = orchestrator_loop.process_turn("merhaba", state)
        
        # Verify turn was added
        assert len(state1.conversation_history) == 1
        assert state1.conversation_history[0]["user"] == "merhaba"
        assert state1.conversation_history[0]["assistant"] == "Merhaba efendim!"
        
        # Process second turn
        mock_output2 = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="İyiyim, teşekkürler!",
        )
        orchestrator_loop.orchestrator.route = Mock(return_value=mock_output2)
        
        result2, state2 = orchestrator_loop.process_turn("nasılsın", state1)
        
        # Verify both turns are in history
        assert len(state2.conversation_history) == 2
        assert state2.conversation_history[0]["user"] == "merhaba"
        assert state2.conversation_history[1]["user"] == "nasılsın"
