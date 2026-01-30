"""
Tests for EngagedWindowManager (Issue #35 - Voice-2).

Tests:
- Window start/close
- Timeout behavior
- Extension on speech
- Max timeout limit
- Remaining time tracking

Uses mock time and threading.Timer to avoid real delays in tests.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestEngagedWindowConfig:
    """Tests for EngagedWindowConfig."""
    
    def test_config_defaults(self):
        """Test default configuration values."""
        from bantz.voice.engaged_window import EngagedWindowConfig
        
        config = EngagedWindowConfig()
        
        assert config.min_timeout == 10.0
        assert config.max_timeout == 20.0
        assert config.default_timeout == 15.0
        assert config.extension_amount == 5.0


class TestEngagedWindowManager:
    """Tests for EngagedWindowManager class."""
    
    @pytest.fixture
    def mock_time(self):
        """Mock time module."""
        with patch('bantz.voice.engaged_window.time') as m:
            m.time.return_value = 1000.0
            yield m
    
    @pytest.fixture
    def mock_threading(self):
        """Mock threading.Timer to avoid real timers."""
        with patch('bantz.voice.engaged_window.threading') as m:
            mock_timer = MagicMock()
            m.Timer.return_value = mock_timer
            m.Lock.return_value = MagicMock()
            yield m
    
    @pytest.fixture
    def window(self, mock_time, mock_threading):
        """Create EngagedWindowManager for testing."""
        from bantz.voice.engaged_window import EngagedWindowManager
        
        return EngagedWindowManager(
            min_timeout=10.0,
            max_timeout=20.0,
            default_timeout=15.0
        )
    
    def test_window_starts_with_default(self, window, mock_time):
        """Test window starts with default timeout."""
        window.start_window()
        
        assert window._start_time == 1000.0
        assert window._current_timeout == 15.0
    
    def test_window_is_active_before_timeout(self, window, mock_time):
        """Test window is active before timeout."""
        window.start_window()
        
        # 5 seconds later (before 15s timeout)
        mock_time.time.return_value = 1005.0
        assert window.is_active == True
    
    def test_window_expires_after_timeout(self, window, mock_time):
        """Test window expires after timeout."""
        window.start_window()
        
        # 20 seconds later (after 15s timeout)
        mock_time.time.return_value = 1020.0
        assert window.is_active == False
    
    def test_window_extends_on_speech(self, window, mock_time):
        """Test window extends on user speech."""
        window.start_window()
        
        initial_timeout = window._current_timeout
        window.on_user_speech()
        
        # Should have extended (capped at max 20.0)
        assert window._current_timeout == min(initial_timeout + 5.0, 20.0)
    
    def test_window_respects_max(self, window, mock_time):
        """Test window respects max timeout."""
        window.start_window(timeout=50.0)  # Try to exceed max
        
        assert window._current_timeout <= 20.0
    
    def test_window_respects_min(self, window, mock_time):
        """Test window respects min timeout."""
        window.start_window(timeout=1.0)  # Try below min
        
        assert window._current_timeout >= 10.0
    
    def test_window_close_immediate(self, window, mock_time):
        """Test close_window immediately deactivates."""
        window.start_window()
        assert window._start_time == 1000.0
        
        window.close_window()
        
        assert window._start_time is None
    
    def test_remaining_time_decreases(self, window, mock_time):
        """Test remaining_time decreases over time."""
        window.start_window()
        initial_remaining = window.remaining_time
        
        mock_time.time.return_value = 1005.0
        assert window.remaining_time == initial_remaining - 5.0
    
    def test_remaining_time_zero_when_inactive(self, mock_time, mock_threading):
        """Test remaining_time is 0 when inactive."""
        from bantz.voice.engaged_window import EngagedWindowManager
        
        window = EngagedWindowManager(
            min_timeout=10.0,
            max_timeout=20.0,
            default_timeout=15.0
        )
        assert window.remaining_time == 0.0
    
    def test_elapsed_time_increases(self, window, mock_time):
        """Test elapsed_time increases over time."""
        window.start_window()
        assert window.elapsed_time == 0.0
        
        mock_time.time.return_value = 1007.0
        assert window.elapsed_time == 7.0
    
    def test_get_stats(self, window, mock_time):
        """Test get_stats returns dict."""
        window.start_window()
        stats = window.get_stats()
        
        assert "is_active" in stats
        assert "remaining_time" in stats
        assert "elapsed_time" in stats
        assert "current_timeout" in stats
        assert "min_timeout" in stats
        assert "max_timeout" in stats


class TestEngagedWindowFactory:
    """Tests for create_engaged_window factory."""
    
    @pytest.fixture
    def mock_time(self):
        """Mock time module."""
        with patch('bantz.voice.engaged_window.time') as m:
            m.time.return_value = 1000.0
            yield m
    
    @pytest.fixture
    def mock_threading(self):
        """Mock threading.Timer to avoid real timers."""
        with patch('bantz.voice.engaged_window.threading') as m:
            mock_timer = MagicMock()
            m.Timer.return_value = mock_timer
            m.Lock.return_value = MagicMock()
            yield m
    
    def test_factory_creates_window(self, mock_time, mock_threading):
        """Test factory function creates EngagedWindowManager."""
        from bantz.voice.engaged_window import create_engaged_window, EngagedWindowManager
        
        window = create_engaged_window(
            min_timeout=5.0,
            max_timeout=15.0,
            default_timeout=10.0
        )
        
        assert isinstance(window, EngagedWindowManager)
    
    def test_factory_with_callback(self, mock_time, mock_threading):
        """Test factory with on_expired callback."""
        from bantz.voice.engaged_window import create_engaged_window
        
        callback = Mock()
        window = create_engaged_window(
            min_timeout=10.0,
            max_timeout=20.0,
            default_timeout=15.0,
            on_expired=callback
        )
        
        window.start_window()
        
        # After timeout
        mock_time.time.return_value = 1020.0
        # Window should be inactive
        assert window.is_active == False
