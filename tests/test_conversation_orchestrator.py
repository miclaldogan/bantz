"""
Tests for V2-6 Conversation Orchestrator (Issue #38).
"""

import pytest
from unittest.mock import Mock, AsyncMock

from bantz.conversation.orchestrator import (
    ConversationOrchestrator,
    OrchestratorConfig,
    create_orchestrator,
)
from bantz.conversation.fsm import ConversationState


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = OrchestratorConfig()
        
        assert config.thinking_timeout_s == 30.0
        assert config.speak_acknowledgment is True
        assert config.language == "tr"


class TestConversationOrchestrator:
    """Tests for ConversationOrchestrator."""
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping orchestrator."""
        orchestrator = ConversationOrchestrator()
        
        await orchestrator.start()
        assert orchestrator.is_active is True
        
        await orchestrator.stop()
        assert orchestrator.is_active is False
    
    @pytest.mark.asyncio
    async def test_initial_state_idle(self):
        """Test initial state is IDLE."""
        orchestrator = ConversationOrchestrator()
        
        assert orchestrator.current_state == ConversationState.IDLE
    
    @pytest.mark.asyncio
    async def test_process_utterance_basic(self):
        """Test basic utterance processing."""
        orchestrator = ConversationOrchestrator()
        await orchestrator.start()
        
        # No router - should echo back
        response = await orchestrator.process_utterance("Merhaba")
        
        assert "Merhaba" in response
        assert orchestrator.current_state == ConversationState.IDLE
    
    @pytest.mark.asyncio
    async def test_process_utterance_with_router(self):
        """Test utterance processing with router."""
        router = Mock()
        router.route = AsyncMock(return_value="Router response")
        
        orchestrator = ConversationOrchestrator(router=router)
        await orchestrator.start()
        
        response = await orchestrator.process_utterance("Test input")
        
        assert response == "Router response"
        router.route.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_utterance_with_tts(self):
        """Test utterance processing with TTS."""
        tts = Mock()
        tts.speak = AsyncMock()
        tts.is_playing = Mock(return_value=False)
        
        orchestrator = ConversationOrchestrator(tts=tts)
        await orchestrator.start()
        
        await orchestrator.process_utterance("Merhaba")
        
        # TTS should be called
        tts.speak.assert_called()
    
    @pytest.mark.asyncio
    async def test_context_updated(self):
        """Test context is updated after utterance."""
        orchestrator = ConversationOrchestrator()
        await orchestrator.start()
        
        await orchestrator.process_utterance("Hello")
        
        # Should have 2 turns: user + assistant
        assert orchestrator.context.turn_count == 2
        
        last_user = orchestrator.context.get_last_user_turn()
        assert last_user.text == "Hello"
    
    @pytest.mark.asyncio
    async def test_fsm_transitions_during_processing(self):
        """Test FSM transitions during utterance processing."""
        orchestrator = ConversationOrchestrator()
        await orchestrator.start()
        
        # Process utterance
        await orchestrator.process_utterance("Test")
        
        # Check history - should have transitioned through states
        history = orchestrator._fsm.get_history()
        
        # History should have entries (could be state transitions)
        # After processing, should be back at IDLE
        assert orchestrator.current_state == ConversationState.IDLE
    
    @pytest.mark.asyncio
    async def test_handle_router_error(self):
        """Test error handling when router fails."""
        router = Mock()
        router.route = AsyncMock(side_effect=Exception("Router error"))
        
        orchestrator = ConversationOrchestrator(router=router)
        orchestrator._config.speak_error = False  # Don't try to speak error
        await orchestrator.start()
        
        response = await orchestrator.process_utterance("Test")
        
        # Should return empty or error message
        assert orchestrator._errors == 1
    
    @pytest.mark.asyncio
    async def test_speak_feedback(self):
        """Test speaking feedback phrases."""
        tts = Mock()
        tts.speak = AsyncMock()
        tts.is_playing = Mock(return_value=False)
        
        from bantz.conversation.feedback import FeedbackType
        
        orchestrator = ConversationOrchestrator(tts=tts)
        await orchestrator.start()
        
        await orchestrator.speak_feedback(FeedbackType.ACKNOWLEDGMENT, wait=True)
        
        tts.speak.assert_called()
    
    @pytest.mark.asyncio
    async def test_handle_wakeword(self):
        """Test wakeword handling."""
        orchestrator = ConversationOrchestrator()
        await orchestrator.start()
        
        await orchestrator.handle_wakeword()
        
        assert orchestrator.current_state == ConversationState.LISTENING
    
    @pytest.mark.asyncio
    async def test_handle_barge_in(self):
        """Test barge-in handling."""
        tts = Mock()
        tts.is_playing = Mock(return_value=True)
        tts.stop = AsyncMock()
        
        from bantz.conversation.bargein import BargeInHandler
        
        bargein = BargeInHandler(tts=tts)
        
        orchestrator = ConversationOrchestrator(tts=tts, bargein=bargein)
        await orchestrator.start()
        
        result = await orchestrator.handle_barge_in(
            speech_volume=0.8,
            speech_duration_ms=300
        )
        
        assert result is True
    
    def test_get_stats(self):
        """Test getting statistics."""
        orchestrator = ConversationOrchestrator()
        
        stats = orchestrator.get_stats()
        
        assert "active" in stats
        assert "current_state" in stats
        assert "total_utterances" in stats
        assert "success_rate" in stats
    
    def test_reset_context(self):
        """Test resetting context."""
        orchestrator = ConversationOrchestrator()
        orchestrator._context.add_user_turn("Hello")
        
        orchestrator.reset_context()
        
        assert orchestrator._context.turn_count == 0
    
    def test_new_conversation(self):
        """Test starting new conversation."""
        orchestrator = ConversationOrchestrator()
        old_id = orchestrator.context.conversation_id
        
        new_id = orchestrator.new_conversation()
        
        assert new_id != old_id
        assert orchestrator.context.conversation_id == new_id
    
    def test_factory_function(self):
        """Test create_orchestrator factory."""
        orchestrator = create_orchestrator(language="en")
        
        assert isinstance(orchestrator, ConversationOrchestrator)
        assert orchestrator._config.language == "en"
