"""
Tests for Voice Loop AttentionGate Integration (Issue #35 - Voice-2).

Tests:
- AttentionGate integration with voice loop
- Gate check before processing
- Interrupt handling flow
- Engaged window extension on speech
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock


class TestVoiceLoopGateIntegration:
    """Tests for AttentionGate integration with VoiceLoop."""
    
    def test_attention_gate_import(self):
        """Test AttentionGate can be imported from voice module."""
        from bantz.voice import AttentionGate, ListeningMode
        
        assert AttentionGate is not None
        assert ListeningMode is not None
    
    def test_listening_mode_values(self):
        """Test ListeningMode has expected values."""
        from bantz.voice import ListeningMode
        
        assert ListeningMode.IDLE.value == "idle"
        assert ListeningMode.WAKEWORD_ONLY.value == "wakeword_only"
        assert ListeningMode.ENGAGED.value == "engaged"
        assert ListeningMode.TASK_RUNNING.value == "task_running"
    
    def test_gate_respects_wakeword_only_mode(self):
        """Test gate blocks speech in WAKEWORD_ONLY mode."""
        from bantz.voice.attention_gate import AttentionGate
        
        with patch('bantz.voice.attention_gate.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            gate = AttentionGate()
            
            # Default is WAKEWORD_ONLY
            assert gate.should_process_speech() == False
    
    def test_gate_allows_speech_in_engaged_mode(self):
        """Test gate allows speech in ENGAGED mode."""
        from bantz.voice.attention_gate import AttentionGate
        
        with patch('bantz.voice.attention_gate.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            gate = AttentionGate()
            
            gate.on_wake_word_detected()
            
            assert gate.should_process_speech() == True
    
    def test_gate_blocks_speech_in_task_running(self):
        """Test gate blocks normal speech in TASK_RUNNING mode."""
        from bantz.voice.attention_gate import AttentionGate
        
        with patch('bantz.voice.attention_gate.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            gate = AttentionGate()
            
            gate.on_wake_word_detected()
            gate.on_job_started("job-123")
            
            assert gate.should_process_speech() == False
    
    def test_gate_interrupt_during_task(self):
        """Test interrupt detection during TASK_RUNNING."""
        from bantz.voice.attention_gate import AttentionGate
        
        with patch('bantz.voice.attention_gate.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            gate = AttentionGate()
            
            gate.on_wake_word_detected()
            gate.on_job_started("job-123")
            
            # No interrupt yet
            assert gate.should_interrupt() == False
            
            # Wake word during task
            gate.on_wake_word_detected()
            
            # Now should interrupt
            assert gate.should_interrupt() == True


class TestVoiceLoopEngagedWindow:
    """Tests for engaged window behavior in voice loop."""
    
    def test_engaged_window_import(self):
        """Test EngagedWindowManager can be imported."""
        from bantz.voice import EngagedWindowManager
        
        assert EngagedWindowManager is not None
    
    def test_window_extends_on_speech(self):
        """Test window extends when user speaks."""
        from bantz.voice.engaged_window import EngagedWindowManager
        from unittest.mock import MagicMock
        
        with patch('bantz.voice.engaged_window.time') as mock_time, \
             patch('bantz.voice.engaged_window.threading') as mock_threading:
            mock_time.time.return_value = 1000.0
            mock_timer = MagicMock()
            mock_threading.Timer.return_value = mock_timer
            mock_threading.Lock.return_value = MagicMock()
            
            window = EngagedWindowManager(
                min_timeout=1.0,
                max_timeout=3.0,
                default_timeout=1.5
            )
            
            window.start_window()
            initial_timeout = window._current_timeout
            
            window.on_user_speech()
            
            # Should have extended (by 5.0 or capped at max 3.0)
            assert window._current_timeout == min(initial_timeout + 5.0, 3.0)


class TestVoiceLoopInterrupt:
    """Tests for interrupt handling in voice loop."""
    
    def test_interrupt_handler_import(self):
        """Test InterruptHandler can be imported."""
        from bantz.voice import InterruptHandler, InterruptAction
        
        assert InterruptHandler is not None
        assert InterruptAction is not None
    
    @pytest.mark.asyncio
    async def test_interrupt_returns_result(self):
        """Test interrupt handler returns proper result."""
        from bantz.voice.interrupt_handler import InterruptHandler, InterruptAction
        
        mock_job_manager = Mock()
        mock_job_manager.pause_job.return_value = True
        
        mock_tts = Mock()
        mock_tts.stop = AsyncMock()
        mock_tts.speak = AsyncMock()
        
        with patch('bantz.voice.interrupt_handler.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            handler = InterruptHandler(
                job_manager=mock_job_manager,
                tts_controller=mock_tts
            )
            
            result = await handler.handle_interrupt("job-123")
            
            assert result.action == InterruptAction.PAUSE_AND_LISTEN
            assert result.paused_job_id == "job-123"


class TestVoiceLoopTaskPolicy:
    """Tests for task policy in voice loop."""
    
    def test_task_policy_import(self):
        """Test TaskListeningPolicy can be imported."""
        from bantz.voice import TaskListeningPolicy
        
        assert TaskListeningPolicy is not None
    
    def test_policy_filters_commands(self):
        """Test policy filters commands during task."""
        from bantz.voice.task_policy import TaskListeningPolicy
        
        policy = TaskListeningPolicy()
        
        # Job control allowed
        assert policy.should_accept("job_pause") == True
        
        # Other commands blocked
        assert policy.should_accept("open_app") == False
