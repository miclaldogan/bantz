"""
Tests for V2-6 Conversation FSM (Issue #38).
"""

import pytest
from unittest.mock import Mock, AsyncMock

from bantz.conversation.fsm import (
    ConversationState,
    StateTransition,
    ConversationFSM,
    TRIGGER_WAKEWORD,
    TRIGGER_SPEECH_START,
    TRIGGER_SPEECH_END,
    TRIGGER_THINKING_DONE,
    TRIGGER_SPEAKING_DONE,
    TRIGGER_BARGE_IN,
    TRIGGER_TIMEOUT,
    create_conversation_fsm,
)


class TestConversationState:
    """Tests for ConversationState enum."""
    
    def test_states_exist(self):
        """Test all states exist."""
        assert ConversationState.IDLE is not None
        assert ConversationState.LISTENING is not None
        assert ConversationState.THINKING is not None
        assert ConversationState.SPEAKING is not None
        assert ConversationState.CONFIRMING is not None
    
    def test_state_values(self):
        """Test state string values."""
        assert ConversationState.IDLE.value == "idle"
        assert ConversationState.LISTENING.value == "listening"
        assert ConversationState.THINKING.value == "thinking"
        assert ConversationState.SPEAKING.value == "speaking"
    
    def test_state_string(self):
        """Test state __str__."""
        assert str(ConversationState.IDLE) == "idle"


class TestStateTransition:
    """Tests for StateTransition."""
    
    def test_create_transition(self):
        """Test creating a transition."""
        t = StateTransition(
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
            trigger=TRIGGER_WAKEWORD
        )
        
        assert t.from_state == ConversationState.IDLE
        assert t.to_state == ConversationState.LISTENING
        assert t.trigger == TRIGGER_WAKEWORD
    
    def test_transition_with_condition(self):
        """Test transition with condition."""
        condition = Mock(return_value=True)
        t = StateTransition(
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
            trigger=TRIGGER_WAKEWORD,
            condition=condition
        )
        
        assert t.is_valid() is True
        condition.assert_called_once()
    
    def test_transition_condition_false(self):
        """Test transition with false condition."""
        condition = Mock(return_value=False)
        t = StateTransition(
            from_state=ConversationState.IDLE,
            to_state=ConversationState.LISTENING,
            trigger=TRIGGER_WAKEWORD,
            condition=condition
        )
        
        assert t.is_valid() is False


class TestConversationFSM:
    """Tests for ConversationFSM."""
    
    def test_initial_state_idle(self):
        """Test initial state is IDLE."""
        fsm = ConversationFSM()
        assert fsm.current_state == ConversationState.IDLE
    
    @pytest.mark.asyncio
    async def test_wakeword_to_listening(self):
        """Test wakeword transitions to LISTENING."""
        fsm = ConversationFSM()
        
        result = await fsm.transition(TRIGGER_WAKEWORD)
        
        assert result is True
        assert fsm.current_state == ConversationState.LISTENING
    
    @pytest.mark.asyncio
    async def test_speech_end_to_thinking(self):
        """Test speech end transitions to THINKING."""
        fsm = ConversationFSM()
        await fsm.transition(TRIGGER_WAKEWORD)  # → LISTENING
        
        result = await fsm.transition(TRIGGER_SPEECH_END)
        
        assert result is True
        assert fsm.current_state == ConversationState.THINKING
    
    @pytest.mark.asyncio
    async def test_thinking_done_to_speaking(self):
        """Test thinking done transitions to SPEAKING."""
        fsm = ConversationFSM()
        await fsm.transition(TRIGGER_WAKEWORD)  # → LISTENING
        await fsm.transition(TRIGGER_SPEECH_END)  # → THINKING
        
        result = await fsm.transition(TRIGGER_THINKING_DONE)
        
        assert result is True
        assert fsm.current_state == ConversationState.SPEAKING
    
    @pytest.mark.asyncio
    async def test_speaking_done_to_idle(self):
        """Test speaking done transitions to IDLE."""
        fsm = ConversationFSM()
        await fsm.transition(TRIGGER_WAKEWORD)  # → LISTENING
        await fsm.transition(TRIGGER_SPEECH_END)  # → THINKING
        await fsm.transition(TRIGGER_THINKING_DONE)  # → SPEAKING
        
        result = await fsm.transition(TRIGGER_SPEAKING_DONE)
        
        assert result is True
        assert fsm.current_state == ConversationState.IDLE
    
    @pytest.mark.asyncio
    async def test_invalid_transition_blocked(self):
        """Test invalid transition is blocked."""
        fsm = ConversationFSM()
        
        # Can't go from IDLE directly to SPEAKING
        result = await fsm.transition(TRIGGER_SPEAKING_DONE)
        
        assert result is False
        assert fsm.current_state == ConversationState.IDLE
    
    @pytest.mark.asyncio
    async def test_barge_in_to_listening(self):
        """Test barge-in transitions from SPEAKING to LISTENING."""
        fsm = ConversationFSM()
        await fsm.transition(TRIGGER_WAKEWORD)  # → LISTENING
        await fsm.transition(TRIGGER_SPEECH_END)  # → THINKING
        await fsm.transition(TRIGGER_THINKING_DONE)  # → SPEAKING
        
        result = await fsm.transition(TRIGGER_BARGE_IN)
        
        assert result is True
        assert fsm.current_state == ConversationState.LISTENING
    
    @pytest.mark.asyncio
    async def test_on_enter_callback(self):
        """Test on_enter callback is called."""
        fsm = ConversationFSM()
        callback = Mock()
        
        fsm.on_enter(ConversationState.LISTENING, callback)
        await fsm.transition(TRIGGER_WAKEWORD)
        
        callback.assert_called_once_with(ConversationState.LISTENING)
    
    @pytest.mark.asyncio
    async def test_on_exit_callback(self):
        """Test on_exit callback is called."""
        fsm = ConversationFSM()
        callback = Mock()
        
        fsm.on_exit(ConversationState.IDLE, callback)
        await fsm.transition(TRIGGER_WAKEWORD)
        
        callback.assert_called_once_with(ConversationState.IDLE)
    
    def test_can_transition(self):
        """Test can_transition check."""
        fsm = ConversationFSM()
        
        assert fsm.can_transition(TRIGGER_WAKEWORD) is True
        assert fsm.can_transition(TRIGGER_SPEAKING_DONE) is False
    
    def test_is_active_property(self):
        """Test is_active property."""
        fsm = ConversationFSM()
        
        assert fsm.is_active is False
        assert fsm.is_idle is True
    
    def test_reset(self):
        """Test reset to IDLE."""
        fsm = ConversationFSM()
        fsm._current_state = ConversationState.SPEAKING
        
        fsm.reset()
        
        assert fsm.current_state == ConversationState.IDLE
    
    def test_get_valid_triggers(self):
        """Test getting valid triggers."""
        fsm = ConversationFSM()
        
        triggers = fsm.get_valid_triggers()
        
        assert TRIGGER_WAKEWORD in triggers
        assert TRIGGER_SPEECH_START in triggers
    
    @pytest.mark.asyncio
    async def test_history_recorded(self):
        """Test transition history is recorded."""
        fsm = ConversationFSM()
        
        await fsm.transition(TRIGGER_WAKEWORD)
        
        history = fsm.get_history()
        assert len(history) == 1
        assert history[0]["from"] == "idle"
        assert history[0]["to"] == "listening"
    
    def test_factory_function(self):
        """Test create_conversation_fsm factory."""
        fsm = create_conversation_fsm()
        assert isinstance(fsm, ConversationFSM)
