"""
Tests for AttentionGate (Issue #35 - Voice-2).

Tests:
- ListeningMode enum values
- Mode transitions (wake word, job start/complete)
- Engaged timeout behavior
- should_process_speech and should_interrupt
- Event subscriptions
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch


class TestListeningMode:
    """Tests for ListeningMode enum."""
    
    def test_listening_modes_exist(self):
        """Test that all required modes exist."""
        from bantz.voice.attention_gate import ListeningMode
        
        assert hasattr(ListeningMode, 'IDLE')
        assert hasattr(ListeningMode, 'WAKEWORD_ONLY')
        assert hasattr(ListeningMode, 'ENGAGED')
        assert hasattr(ListeningMode, 'TASK_RUNNING')
    
    def test_listening_modes_unique(self):
        """Test mode values are unique."""
        from bantz.voice.attention_gate import ListeningMode
        
        values = [m.value for m in ListeningMode]
        assert len(values) == len(set(values))
    
    def test_wakeword_only_is_default_initial(self):
        """Test default initial mode is WAKEWORD_ONLY."""
        from bantz.voice.attention_gate import AttentionGateConfig, ListeningMode
        
        config = AttentionGateConfig()
        assert config.initial_mode == ListeningMode.WAKEWORD_ONLY


class TestAttentionGateConfig:
    """Tests for AttentionGateConfig."""
    
    def test_config_defaults(self):
        """Test default configuration values."""
        from bantz.voice.attention_gate import AttentionGateConfig
        
        config = AttentionGateConfig()
        
        assert config.engaged_timeout == 15.0
        assert config.auto_engage_on_wake == True
    
    def test_config_custom_values(self):
        """Test custom configuration."""
        from bantz.voice.attention_gate import AttentionGateConfig, ListeningMode
        
        config = AttentionGateConfig(
            engaged_timeout=20.0,
            initial_mode=ListeningMode.IDLE,
            auto_engage_on_wake=False
        )
        
        assert config.engaged_timeout == 20.0
        assert config.initial_mode == ListeningMode.IDLE
        assert config.auto_engage_on_wake == False


class TestAttentionGate:
    """Tests for AttentionGate class."""
    
    @pytest.fixture
    def gate(self):
        """Create AttentionGate for testing."""
        from bantz.voice.attention_gate import AttentionGate, AttentionGateConfig
        
        with patch('bantz.voice.attention_gate.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            config = AttentionGateConfig(engaged_timeout=1.0)  # Short for tests
            return AttentionGate(config=config)
    
    def test_initial_mode_wakeword_only(self, gate):
        """Test initial mode is WAKEWORD_ONLY."""
        from bantz.voice.attention_gate import ListeningMode
        
        assert gate.mode == ListeningMode.WAKEWORD_ONLY
    
    def test_wake_word_transitions_to_engaged(self, gate):
        """Test wake word detection transitions to ENGAGED."""
        from bantz.voice.attention_gate import ListeningMode
        
        gate.on_wake_word_detected()
        
        assert gate.mode == ListeningMode.ENGAGED
    
    def test_engaged_timeout_returns_wakeword(self, gate):
        """Test engaged mode times out to WAKEWORD_ONLY."""
        from bantz.voice.attention_gate import ListeningMode
        
        gate.on_wake_word_detected()
        assert gate.mode == ListeningMode.ENGAGED
        
        # Wait for timeout
        time.sleep(1.2)
        
        assert gate.mode == ListeningMode.WAKEWORD_ONLY
    
    def test_job_started_transitions_task_running(self, gate):
        """Test job start transitions to TASK_RUNNING."""
        from bantz.voice.attention_gate import ListeningMode
        
        gate.on_wake_word_detected()  # First go to ENGAGED
        gate.on_job_started("job-123")
        
        assert gate.mode == ListeningMode.TASK_RUNNING
        assert gate.get_current_job_id() == "job-123"
    
    def test_job_completed_returns_engaged(self, gate):
        """Test job completion returns to ENGAGED."""
        from bantz.voice.attention_gate import ListeningMode
        
        gate.on_wake_word_detected()
        gate.on_job_started("job-123")
        gate.on_job_completed("job-123")
        
        assert gate.mode == ListeningMode.ENGAGED
        assert gate.get_current_job_id() is None
    
    def test_should_process_true_in_engaged(self, gate):
        """Test should_process_speech is True in ENGAGED mode."""
        gate.on_wake_word_detected()
        
        assert gate.should_process_speech() == True
    
    def test_should_process_false_in_task_running(self, gate):
        """Test should_process_speech is False in TASK_RUNNING mode."""
        gate.on_wake_word_detected()
        gate.on_job_started("job-123")
        
        assert gate.should_process_speech() == False
    
    def test_should_interrupt_on_wake_during_task(self, gate):
        """Test interrupt flag set on wake word during TASK_RUNNING."""
        gate.on_wake_word_detected()
        gate.on_job_started("job-123")
        
        # Wake word during task
        gate.on_wake_word_detected()
        
        assert gate.should_interrupt() == True
        # Flag should be cleared after check
        assert gate.should_interrupt() == False


class TestAttentionGateFactory:
    """Tests for create_attention_gate factory."""
    
    def test_factory_creates_gate(self):
        """Test factory function creates AttentionGate."""
        from bantz.voice.attention_gate import create_attention_gate, AttentionGate
        
        with patch('bantz.voice.attention_gate.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            gate = create_attention_gate(engaged_timeout=10.0)
            
            assert isinstance(gate, AttentionGate)
