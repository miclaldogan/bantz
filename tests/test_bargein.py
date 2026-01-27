"""
Tests for V2-6 Barge-in Handler (Issue #38).
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from bantz.conversation.bargein import (
    BargeInAction,
    BargeInEvent,
    BargeInHandler,
    create_barge_in_handler,
)


class TestBargeInAction:
    """Tests for BargeInAction enum."""
    
    def test_actions_exist(self):
        """Test all actions exist."""
        assert BargeInAction.STOP_TTS is not None
        assert BargeInAction.STOP_AND_LISTEN is not None
        assert BargeInAction.QUEUE_RESPONSE is not None
        assert BargeInAction.IGNORE is not None
    
    def test_action_values(self):
        """Test action string values."""
        assert BargeInAction.STOP_TTS.value == "stop_tts"
        assert BargeInAction.STOP_AND_LISTEN.value == "stop_and_listen"


class TestBargeInEvent:
    """Tests for BargeInEvent."""
    
    def test_create_event(self):
        """Test creating an event."""
        event = BargeInEvent(
            speech_volume=0.7,
            speech_duration_ms=300,
            tts_was_playing=True
        )
        
        assert event.speech_volume == 0.7
        assert event.speech_duration_ms == 300
        assert event.tts_was_playing is True
    
    def test_event_to_dict(self):
        """Test event to_dict."""
        event = BargeInEvent(
            speech_volume=0.8,
            speech_duration_ms=500,
            action_taken=BargeInAction.STOP_AND_LISTEN
        )
        
        data = event.to_dict()
        
        assert data["speech_volume"] == 0.8
        assert data["action_taken"] == "stop_and_listen"
        assert "timestamp" in data


class TestBargeInHandler:
    """Tests for BargeInHandler."""
    
    def test_should_interrupt_high_volume(self):
        """Test interrupt with high volume speech."""
        handler = BargeInHandler()
        
        result = handler.should_interrupt(
            speech_volume=0.8,
            speech_duration_ms=300
        )
        
        assert result is True
    
    def test_should_not_interrupt_low_volume(self):
        """Test no interrupt with low volume."""
        handler = BargeInHandler()
        
        result = handler.should_interrupt(
            speech_volume=0.3,
            speech_duration_ms=300
        )
        
        assert result is False
    
    def test_should_not_interrupt_short_speech(self):
        """Test no interrupt with short speech."""
        handler = BargeInHandler()
        
        result = handler.should_interrupt(
            speech_volume=0.8,
            speech_duration_ms=100  # Below MIN_SPEECH_DURATION_MS
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_handle_stops_tts(self):
        """Test barge-in stops TTS."""
        tts = Mock()
        tts.is_playing = Mock(return_value=True)
        tts.stop = AsyncMock()
        
        fsm = Mock()
        fsm.is_speaking = True
        fsm.transition = AsyncMock(return_value=True)
        
        handler = BargeInHandler(tts=tts, fsm=fsm)
        
        event = BargeInEvent(
            speech_volume=0.8,
            speech_duration_ms=300
        )
        
        action = await handler.handle(event)
        
        tts.stop.assert_called_once()
        assert action == BargeInAction.STOP_AND_LISTEN
    
    @pytest.mark.asyncio
    async def test_handle_transitions_to_listening(self):
        """Test barge-in transitions FSM to LISTENING."""
        tts = Mock()
        tts.is_playing = Mock(return_value=True)
        tts.stop = AsyncMock()
        
        fsm = Mock()
        fsm.is_speaking = True
        fsm.transition = AsyncMock(return_value=True)
        
        handler = BargeInHandler(tts=tts, fsm=fsm)
        
        event = BargeInEvent(
            speech_volume=0.8,
            speech_duration_ms=300
        )
        
        await handler.handle(event)
        
        fsm.transition.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_ignores_below_threshold(self):
        """Test low volume is ignored."""
        handler = BargeInHandler()
        
        event = BargeInEvent(
            speech_volume=0.3,
            speech_duration_ms=300
        )
        
        action = await handler.handle(event)
        
        assert action == BargeInAction.IGNORE
    
    @pytest.mark.asyncio
    async def test_handle_ignores_short_speech(self):
        """Test short speech is ignored."""
        handler = BargeInHandler()
        
        event = BargeInEvent(
            speech_volume=0.8,
            speech_duration_ms=100
        )
        
        action = await handler.handle(event)
        
        assert action == BargeInAction.IGNORE
    
    @pytest.mark.asyncio
    async def test_events_logged(self):
        """Test events are logged to history."""
        handler = BargeInHandler()
        
        event = BargeInEvent(
            speech_volume=0.8,
            speech_duration_ms=300
        )
        
        await handler.handle(event)
        
        events = handler.get_events()
        assert len(events) == 1
    
    def test_set_threshold(self):
        """Test setting interrupt threshold."""
        handler = BargeInHandler()
        
        handler.set_threshold(0.7)
        
        # Should now require 0.7 volume
        assert handler.should_interrupt(0.6, 300) is False
        assert handler.should_interrupt(0.8, 300) is True
    
    def test_get_stats(self):
        """Test getting statistics."""
        handler = BargeInHandler()
        
        stats = handler.get_stats()
        
        assert "total_interrupts" in stats
        assert "ignored_interrupts" in stats
        assert "threshold" in stats
    
    def test_factory_function(self):
        """Test create_barge_in_handler factory."""
        handler = create_barge_in_handler()
        assert isinstance(handler, BargeInHandler)
