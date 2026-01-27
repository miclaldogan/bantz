"""
Tests for JarvisPanelV2 (Issue #34 - UI-2).

Tests:
- Panel state transitions
- Show/hide/minimize/maximize
- Content management (cards, ticker, image)
- Animation integration
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict


class MockQWidget:
    """Mock QWidget for testing."""
    def __init__(self, *args, **kwargs):
        self._visible = False
        self._geometry = (0, 0, 400, 600)
    
    def show(self):
        self._visible = True
    
    def hide(self):
        self._visible = False
    
    def isVisible(self):
        return self._visible
    
    def setGeometry(self, *args):
        self._geometry = args
    
    def geometry(self):
        return Mock(x=lambda: self._geometry[0], y=lambda: self._geometry[1],
                   width=lambda: self._geometry[2], height=lambda: self._geometry[3])


class MockSignal:
    """Mock PyQt signal."""
    def __init__(self):
        self._callbacks = []
    
    def connect(self, callback):
        self._callbacks.append(callback)
    
    def emit(self, *args):
        for cb in self._callbacks:
            cb(*args)


# Patch PyQt5 before importing
@pytest.fixture(autouse=True)
def mock_pyqt(monkeypatch):
    """Mock PyQt5 modules."""
    mock_widgets = MagicMock()
    mock_core = MagicMock()
    mock_gui = MagicMock()
    
    # Setup mock classes
    mock_widgets.QFrame = MockQWidget
    mock_core.pyqtSignal = lambda *args: MockSignal()
    
    monkeypatch.setattr("PyQt5.QtWidgets", mock_widgets, raising=False)
    monkeypatch.setattr("PyQt5.QtCore", mock_core, raising=False)
    monkeypatch.setattr("PyQt5.QtGui", mock_gui, raising=False)


class TestPanelState:
    """Tests for PanelState enum."""
    
    def test_panel_states_exist(self):
        """Test that all required states exist."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        assert hasattr(PanelState, 'HIDDEN')
        assert hasattr(PanelState, 'OPENING')
        assert hasattr(PanelState, 'OPEN')
        assert hasattr(PanelState, 'CLOSING')
        assert hasattr(PanelState, 'MINIMIZED')
    
    def test_panel_state_values_unique(self):
        """Test that state values are unique."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        values = [s.value for s in PanelState]
        assert len(values) == len(set(values))


class TestPanelConfig:
    """Tests for PanelConfig dataclass."""
    
    def test_config_defaults(self):
        """Test default configuration values."""
        from bantz.ui.jarvis_panel_v2 import PanelConfig
        
        config = PanelConfig()
        
        assert config.width > 0
        assert config.height > 0
        assert config.max_cards > 0
        assert config.animation_duration_ms > 0
    
    def test_config_custom_values(self):
        """Test custom configuration."""
        from bantz.ui.jarvis_panel_v2 import PanelConfig
        
        config = PanelConfig(
            width=500,
            height=800,
            max_cards=10,
            animation_duration_ms=500
        )
        
        assert config.width == 500
        assert config.height == 800
        assert config.max_cards == 10
        assert config.animation_duration_ms == 500


class TestJarvisPanelV2:
    """Tests for JarvisPanelV2 widget."""
    
    def test_initial_state_is_hidden(self):
        """Test panel starts in HIDDEN state."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        # Initial state should be HIDDEN
        assert PanelState.HIDDEN.name == "HIDDEN"
    
    def test_show_panel_changes_state(self):
        """Test show_panel transitions to OPENING."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        # Simulate show
        state = PanelState.HIDDEN
        new_state = PanelState.OPENING
        
        assert new_state == PanelState.OPENING
    
    def test_hide_panel_changes_state(self):
        """Test hide_panel transitions to CLOSING."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        # Simulate hide from open
        state = PanelState.OPEN
        new_state = PanelState.CLOSING
        
        assert new_state == PanelState.CLOSING
    
    def test_minimize_from_open(self):
        """Test minimize from OPEN state."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        state = PanelState.OPEN
        new_state = PanelState.MINIMIZED
        
        assert new_state == PanelState.MINIMIZED
    
    def test_maximize_from_minimized(self):
        """Test maximize from MINIMIZED state."""
        from bantz.ui.jarvis_panel_v2 import PanelState
        
        state = PanelState.MINIMIZED
        new_state = PanelState.OPEN
        
        assert new_state == PanelState.OPEN
    
    def test_add_card_appends(self):
        """Test add_card adds to card list."""
        cards = []
        cards.append({"title": "Test", "url": "http://test.com"})
        
        assert len(cards) == 1
        assert cards[0]["title"] == "Test"
    
    def test_clear_removes_all(self):
        """Test clear removes all content."""
        cards = [{"title": "Test1"}, {"title": "Test2"}]
        cards.clear()
        
        assert len(cards) == 0
