"""
Tests for Bantz Orchestrator - Full System Startup Controller.

Tests:
- Configuration
- Component states
- System states
- Startup sequence
- Callbacks
- Shutdown
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import threading
import time


# =============================================================================
# Test Configuration
# =============================================================================

class TestOrchestratorConfig:
    """Tests for OrchestratorConfig."""
    
    def test_default_config(self):
        """Test default configuration values."""
        from bantz.core.orchestrator import OrchestratorConfig
        
        config = OrchestratorConfig()
        
        assert config.session_name == "default"
        assert config.policy_path == "config/policy.json"
        assert config.enable_wake_word is True
        assert config.enable_tts is True
        assert config.enable_overlay is True
        assert config.enable_panel is False
        assert config.enable_browser is True
        assert "hey_jarvis" in config.wake_words
        assert config.whisper_model == "base"
        assert config.language == "tr"
    
    def test_custom_config(self):
        """Test custom configuration."""
        from bantz.core.orchestrator import OrchestratorConfig
        
        config = OrchestratorConfig(
            session_name="test",
            enable_tts=False,
            wake_words=["hey_friday"],
            whisper_model="small",
        )
        
        assert config.session_name == "test"
        assert config.enable_tts is False
        assert config.wake_words == ["hey_friday"]
        assert config.whisper_model == "small"
    
    def test_from_env(self):
        """Test config from environment variables."""
        import os
        from bantz.core.orchestrator import OrchestratorConfig
        
        # Set env vars
        env_backup = {}
        env_vars = {
            "BANTZ_SESSION": "env_test",
            "BANTZ_TTS": "0",
            "BANTZ_OVERLAY": "0",
        }
        
        for key, value in env_vars.items():
            env_backup[key] = os.environ.get(key)
            os.environ[key] = value
        
        try:
            config = OrchestratorConfig.from_env()
            
            assert config.session_name == "env_test"
            assert config.enable_tts is False
            assert config.enable_overlay is False
        finally:
            # Restore env vars
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


# =============================================================================
# Test Component States
# =============================================================================

class TestComponentState:
    """Tests for ComponentState enum."""
    
    def test_states_exist(self):
        """Test all states are defined."""
        from bantz.core.orchestrator import ComponentState
        
        assert ComponentState.STOPPED
        assert ComponentState.STARTING
        assert ComponentState.RUNNING
        assert ComponentState.ERROR
        assert ComponentState.STOPPING
    
    def test_state_comparison(self):
        """Test state comparison."""
        from bantz.core.orchestrator import ComponentState
        
        assert ComponentState.RUNNING != ComponentState.STOPPED
        assert ComponentState.RUNNING == ComponentState.RUNNING


class TestComponentStatus:
    """Tests for ComponentStatus dataclass."""
    
    def test_default_status(self):
        """Test default status values."""
        from bantz.core.orchestrator import ComponentStatus, ComponentState
        
        status = ComponentStatus(name="test")
        
        assert status.name == "test"
        assert status.state == ComponentState.STOPPED
        assert status.error is None
        assert status.started_at is None
        assert status.is_running is False
        assert status.uptime_seconds == 0.0
    
    def test_running_status(self):
        """Test running status."""
        from bantz.core.orchestrator import ComponentStatus, ComponentState
        import time
        
        status = ComponentStatus(name="test")
        status.state = ComponentState.RUNNING
        status.started_at = time.time() - 10  # 10 seconds ago
        
        assert status.is_running is True
        assert status.uptime_seconds >= 9.9  # Allow small timing variance
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        from bantz.core.orchestrator import ComponentStatus, ComponentState
        
        status = ComponentStatus(
            name="test_component",
            state=ComponentState.ERROR,
            error="Test error",
        )
        
        d = status.to_dict()
        
        assert d["name"] == "test_component"
        assert d["state"] == "error"
        assert d["error"] == "Test error"
        assert "uptime" in d


# =============================================================================
# Test System States
# =============================================================================

class TestSystemState:
    """Tests for SystemState enum."""
    
    def test_states_exist(self):
        """Test all states are defined."""
        from bantz.core.orchestrator import SystemState
        
        assert SystemState.OFFLINE
        assert SystemState.BOOTING
        assert SystemState.READY
        assert SystemState.LISTENING
        assert SystemState.PROCESSING
        assert SystemState.SPEAKING
        assert SystemState.ERROR
    
    def test_state_names(self):
        """Test state name values."""
        from bantz.core.orchestrator import SystemState
        
        assert SystemState.OFFLINE.name == "OFFLINE"
        assert SystemState.READY.name == "READY"


# =============================================================================
# Test Orchestrator Initialization
# =============================================================================

class TestOrchestratorInit:
    """Tests for BantzOrchestrator initialization."""
    
    def test_init_default(self):
        """Test default initialization."""
        from bantz.core.orchestrator import BantzOrchestrator, SystemState
        
        orchestrator = BantzOrchestrator()
        
        assert orchestrator.config is not None
        assert orchestrator.state == SystemState.OFFLINE
        assert orchestrator.is_running is False
        assert orchestrator.is_ready is False
    
    def test_init_with_config(self):
        """Test initialization with custom config."""
        from bantz.core.orchestrator import (
            BantzOrchestrator,
            OrchestratorConfig,
        )
        
        config = OrchestratorConfig(
            session_name="custom",
            enable_tts=False,
        )
        
        orchestrator = BantzOrchestrator(config)
        
        assert orchestrator.config.session_name == "custom"
        assert orchestrator.config.enable_tts is False
    
    def test_component_status_initialized(self):
        """Test component status is initialized."""
        from bantz.core.orchestrator import BantzOrchestrator, ComponentState
        
        orchestrator = BantzOrchestrator()
        status = orchestrator.get_status()
        
        assert "components" in status
        assert "server" in status["components"]
        assert "wake_word" in status["components"]
        assert "asr" in status["components"]
        assert "tts" in status["components"]
        assert "overlay" in status["components"]
        assert "browser" in status["components"]


# =============================================================================
# Test Callbacks
# =============================================================================

class TestOrchestratorCallbacks:
    """Tests for orchestrator callbacks."""
    
    def test_on_state_change_callback(self):
        """Test state change callback registration."""
        from bantz.core.orchestrator import BantzOrchestrator, SystemState
        
        orchestrator = BantzOrchestrator()
        
        states_received = []
        orchestrator.on_state_change(lambda s: states_received.append(s))
        
        # Trigger state change
        orchestrator._set_state(SystemState.BOOTING)
        
        assert SystemState.BOOTING in states_received
    
    def test_on_wake_callback(self):
        """Test wake word callback registration."""
        from bantz.core.orchestrator import BantzOrchestrator
        
        orchestrator = BantzOrchestrator()
        
        wake_events = []
        orchestrator.on_wake(lambda w, c: wake_events.append((w, c)))
        
        assert len(orchestrator._on_wake) == 1
    
    def test_on_command_callback(self):
        """Test command callback registration."""
        from bantz.core.orchestrator import BantzOrchestrator
        
        orchestrator = BantzOrchestrator()
        
        commands_received = []
        orchestrator.on_command(lambda c: commands_received.append(c))
        
        assert len(orchestrator._on_command) == 1
    
    def test_on_response_callback(self):
        """Test response callback registration."""
        from bantz.core.orchestrator import BantzOrchestrator
        
        orchestrator = BantzOrchestrator()
        
        responses_received = []
        orchestrator.on_response(lambda r: responses_received.append(r))
        
        assert len(orchestrator._on_response) == 1


# =============================================================================
# Test Get Status
# =============================================================================

class TestOrchestratorStatus:
    """Tests for orchestrator status methods."""
    
    def test_get_status(self):
        """Test get_status returns correct structure."""
        from bantz.core.orchestrator import BantzOrchestrator
        
        orchestrator = BantzOrchestrator()
        status = orchestrator.get_status()
        
        assert "state" in status
        assert "running" in status
        assert "components" in status
        assert "config" in status
        
        assert status["state"] == "offline"
        assert status["running"] is False
    
    def test_status_config_info(self):
        """Test status contains config info."""
        from bantz.core.orchestrator import BantzOrchestrator, OrchestratorConfig
        
        config = OrchestratorConfig(
            session_name="test_session",
            enable_tts=False,
        )
        
        orchestrator = BantzOrchestrator(config)
        status = orchestrator.get_status()
        
        assert status["config"]["session"] == "test_session"
        assert status["config"]["tts_enabled"] is False


# =============================================================================
# Test State Management
# =============================================================================

class TestOrchestratorStateManagement:
    """Tests for orchestrator state management."""
    
    def test_set_state(self):
        """Test setting system state."""
        from bantz.core.orchestrator import BantzOrchestrator, SystemState
        
        orchestrator = BantzOrchestrator()
        
        assert orchestrator.state == SystemState.OFFLINE
        
        orchestrator._set_state(SystemState.BOOTING)
        assert orchestrator.state == SystemState.BOOTING
        
        orchestrator._set_state(SystemState.READY)
        assert orchestrator.state == SystemState.READY
    
    def test_is_ready_property(self):
        """Test is_ready property."""
        from bantz.core.orchestrator import BantzOrchestrator, SystemState
        
        orchestrator = BantzOrchestrator()
        
        assert orchestrator.is_ready is False
        
        orchestrator._set_state(SystemState.READY)
        assert orchestrator.is_ready is True
        
        orchestrator._set_state(SystemState.LISTENING)
        assert orchestrator.is_ready is True
        
        orchestrator._set_state(SystemState.PROCESSING)
        assert orchestrator.is_ready is False
    
    def test_set_component_state(self):
        """Test setting component state."""
        from bantz.core.orchestrator import BantzOrchestrator, ComponentState
        
        orchestrator = BantzOrchestrator()
        
        orchestrator._set_component_state("server", ComponentState.RUNNING)
        
        assert orchestrator._component_status["server"].state == ComponentState.RUNNING
        assert orchestrator._component_status["server"].started_at is not None
    
    def test_set_component_state_with_error(self):
        """Test setting component state with error."""
        from bantz.core.orchestrator import BantzOrchestrator, ComponentState
        
        orchestrator = BantzOrchestrator()
        
        orchestrator._set_component_state("server", ComponentState.ERROR, "Test error")
        
        assert orchestrator._component_status["server"].state == ComponentState.ERROR
        assert orchestrator._component_status["server"].error == "Test error"


# =============================================================================
# Test Shutdown
# =============================================================================

class TestOrchestratorShutdown:
    """Tests for orchestrator shutdown."""
    
    def test_stop_method(self):
        """Test stop method sets flags."""
        from bantz.core.orchestrator import BantzOrchestrator
        
        orchestrator = BantzOrchestrator()
        orchestrator._running = True
        
        orchestrator.stop()
        
        assert orchestrator._running is False
        assert orchestrator._shutdown_event.is_set()


# =============================================================================
# Test Convenience Functions
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_get_orchestrator_none_initially(self):
        """Test get_orchestrator returns None initially."""
        from bantz.core.orchestrator import get_orchestrator
        
        # May or may not be None depending on global state
        # Just test it doesn't raise
        result = get_orchestrator()
        assert result is None or hasattr(result, 'state')
    
    def test_stop_jarvis_no_error_when_none(self):
        """Test stop_jarvis doesn't error when no orchestrator."""
        from bantz.core import orchestrator
        
        # Save and clear global
        saved = orchestrator._orchestrator
        orchestrator._orchestrator = None
        
        try:
            # Should not raise
            orchestrator.stop_jarvis()
        finally:
            # Restore
            orchestrator._orchestrator = saved


# =============================================================================
# Test Signal Handler
# =============================================================================

class TestSignalHandler:
    """Tests for signal handler."""
    
    def test_signal_handler(self):
        """Test signal handler sets shutdown."""
        import signal
        from bantz.core.orchestrator import BantzOrchestrator
        
        orchestrator = BantzOrchestrator()
        orchestrator._running = True
        
        # Call signal handler directly
        orchestrator._signal_handler(signal.SIGTERM, None)
        
        assert orchestrator._running is False
        assert orchestrator._shutdown_event.is_set()


# =============================================================================
# Test Module Exports
# =============================================================================

class TestModuleExports:
    """Tests for module exports."""
    
    def test_core_exports(self):
        """Test core module exports orchestrator components."""
        from bantz.core import (
            BantzOrchestrator,
            OrchestratorConfig,
            SystemState,
            ComponentState,
            ComponentStatus,
            get_orchestrator,
            start_jarvis,
            stop_jarvis,
        )
        
        assert BantzOrchestrator is not None
        assert OrchestratorConfig is not None
        assert SystemState is not None
        assert ComponentState is not None
    
    def test_orchestrator_module_direct_import(self):
        """Test direct import from orchestrator module."""
        from bantz.core.orchestrator import (
            BantzOrchestrator,
            OrchestratorConfig,
            SystemState,
            ComponentState,
            ComponentStatus,
            get_orchestrator,
            start_jarvis,
            stop_jarvis,
            main,
        )
        
        assert main is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
