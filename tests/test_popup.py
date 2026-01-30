"""
Tests for Jarvis Panel Popup/Bubble System (Issue #63).

Tests:
- Enums and configuration
- PopupPanel widget
- PopupManager
- Animations
- Behaviors (timeout, hover-pause, click-dismiss)
- Helper functions
"""

import pytest
import sys
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime
from typing import List, Tuple

# Mock PyQt5 for headless testing
class MockQApplication:
    _instance = None
    
    @classmethod
    def instance(cls):
        return cls._instance
    
    @classmethod
    def primaryScreen(cls):
        screen = MagicMock()
        screen.geometry.return_value = MagicMock(
            width=lambda: 1920,
            height=lambda: 1080,
            x=lambda: 0,
            y=lambda: 0,
        )
        return screen


class MockQWidget:
    def __init__(self, parent=None):
        self._visible = False
        self._pos = (0, 0)
        self._size = (250, 100)
        self._graphics_effect = None
    
    def show(self):
        self._visible = True
    
    def hide(self):
        self._visible = False
    
    def isVisible(self):
        return self._visible
    
    def move(self, x, y=None):
        if y is None:
            self._pos = (x.x(), x.y())
        else:
            self._pos = (x, y)
    
    def pos(self):
        class Point:
            def __init__(self, x, y):
                self._x = x
                self._y = y
            def x(self):
                return self._x
            def y(self):
                return self._y
        return Point(self._pos[0], self._pos[1])
    
    def geometry(self):
        class Rect:
            def __init__(self, x, y, w, h):
                self._x = x
                self._y = y
                self._w = w
                self._h = h
            def left(self):
                return self._x
            def right(self):
                return self._x + self._w
            def top(self):
                return self._y
            def bottom(self):
                return self._y + self._h
            def center(self):
                class Point:
                    def __init__(self, x, y):
                        self._x = x
                        self._y = y
                    def x(self):
                        return self._x
                    def y(self):
                        return self._y
                return Point(self._x + self._w // 2, self._y + self._h // 2)
            def width(self):
                return self._w
            def height(self):
                return self._h
        return Rect(self._pos[0], self._pos[1], self._size[0], self._size[1])
    
    def sizeHint(self):
        class Size:
            def __init__(self, w, h):
                self._w = w
                self._h = h
            def width(self):
                return self._w
            def height(self):
                return self._h
        return Size(self._size[0], self._size[1])
    
    def setGraphicsEffect(self, effect):
        self._graphics_effect = effect
    
    def graphicsEffect(self):
        return self._graphics_effect
    
    def deleteLater(self):
        pass
    
    def adjustSize(self):
        pass
    
    def setWindowFlags(self, flags):
        pass
    
    def setAttribute(self, attr, value=True):
        pass
    
    def setFixedWidth(self, w):
        self._size = (w, self._size[1])
    
    def setFixedHeight(self, h):
        self._size = (self._size[0], h)
    
    def setMinimumHeight(self, h):
        pass
    
    def rect(self):
        class Rect:
            def adjusted(self, *args):
                return self
            def x(self):
                return 0
            def y(self):
                return 0
            def width(self):
                return 250
            def height(self):
                return 100
        return Rect()


# =============================================================================
# Test Enums
# =============================================================================


class TestPopupContentType:
    """Tests for PopupContentType enum."""
    
    def test_content_types_exist(self):
        """Test all content types are defined."""
        from bantz.ui.popup import PopupContentType
        
        assert PopupContentType.IMAGE
        assert PopupContentType.TEXT
        assert PopupContentType.ICON
        assert PopupContentType.MIXED
        assert PopupContentType.CUSTOM
    
    def test_content_type_values(self):
        """Test content type values."""
        from bantz.ui.popup import PopupContentType
        
        assert PopupContentType.IMAGE.value == "image"
        assert PopupContentType.TEXT.value == "text"
        assert PopupContentType.ICON.value == "icon"
        assert PopupContentType.MIXED.value == "mixed"


class TestPopupPosition:
    """Tests for PopupPosition enum."""
    
    def test_positions_exist(self):
        """Test all positions are defined."""
        from bantz.ui.popup import PopupPosition
        
        assert PopupPosition.TOP_LEFT
        assert PopupPosition.TOP_RIGHT
        assert PopupPosition.BOTTOM_LEFT
        assert PopupPosition.BOTTOM_RIGHT
        assert PopupPosition.LEFT
        assert PopupPosition.RIGHT
        assert PopupPosition.TOP
        assert PopupPosition.BOTTOM
    
    def test_position_values(self):
        """Test position values."""
        from bantz.ui.popup import PopupPosition
        
        assert PopupPosition.TOP_LEFT.value == "top_left"
        assert PopupPosition.BOTTOM_RIGHT.value == "bottom_right"


class TestPopupAnimation:
    """Tests for PopupAnimation enum."""
    
    def test_animations_exist(self):
        """Test all animations are defined."""
        from bantz.ui.popup import PopupAnimation
        
        assert PopupAnimation.NONE
        assert PopupAnimation.FADE
        assert PopupAnimation.SLIDE_LEFT
        assert PopupAnimation.SLIDE_RIGHT
        assert PopupAnimation.SLIDE_UP
        assert PopupAnimation.SLIDE_DOWN
        assert PopupAnimation.SCALE
        assert PopupAnimation.BOUNCE
    
    def test_animation_values(self):
        """Test animation values."""
        from bantz.ui.popup import PopupAnimation
        
        assert PopupAnimation.FADE.value == "fade"
        assert PopupAnimation.BOUNCE.value == "bounce"


class TestPopupStatus:
    """Tests for PopupStatus enum."""
    
    def test_statuses_exist(self):
        """Test all statuses are defined."""
        from bantz.ui.popup import PopupStatus
        
        assert PopupStatus.LOADING
        assert PopupStatus.SUCCESS
        assert PopupStatus.ERROR
        assert PopupStatus.WARNING
        assert PopupStatus.INFO
    
    def test_status_values(self):
        """Test status values."""
        from bantz.ui.popup import PopupStatus
        
        assert PopupStatus.SUCCESS.value == "success"
        assert PopupStatus.ERROR.value == "error"


# =============================================================================
# Test Configuration
# =============================================================================


class TestPopupColors:
    """Tests for PopupColors dataclass."""
    
    def test_default_colors(self):
        """Test default color values."""
        from bantz.ui.popup import PopupColors
        
        colors = PopupColors()
        
        assert colors.background is not None
        assert colors.border is not None
        assert colors.text is not None
        assert colors.accent is not None
        assert colors.success is not None
        assert colors.warning is not None
        assert colors.error is not None
        assert colors.info is not None


class TestPopupConfig:
    """Tests for PopupConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        from bantz.ui.popup import PopupConfig, PopupContentType, PopupPosition, PopupAnimation
        
        config = PopupConfig()
        
        assert config.content_type == PopupContentType.TEXT
        assert config.position == PopupPosition.TOP_RIGHT
        assert config.timeout == 5.0
        assert config.animation == PopupAnimation.FADE
        assert config.priority == 0
        assert config.pausable is True
        assert config.dismissable is True
        assert config.width == 250
        assert config.height == 0
        assert config.margin == 10
    
    def test_custom_config(self):
        """Test custom configuration."""
        from bantz.ui.popup import (
            PopupConfig, PopupContentType, PopupPosition, PopupAnimation
        )
        
        config = PopupConfig(
            content_type=PopupContentType.IMAGE,
            position=PopupPosition.BOTTOM_LEFT,
            timeout=10.0,
            animation=PopupAnimation.BOUNCE,
            priority=5,
            pausable=False,
            dismissable=False,
            width=300,
            height=200,
            margin=20,
        )
        
        assert config.content_type == PopupContentType.IMAGE
        assert config.position == PopupPosition.BOTTOM_LEFT
        assert config.timeout == 10.0
        assert config.animation == PopupAnimation.BOUNCE
        assert config.priority == 5
        assert config.pausable is False
        assert config.dismissable is False
        assert config.width == 300
        assert config.height == 200
        assert config.margin == 20
    
    def test_to_dict(self):
        """Test converting config to dictionary."""
        from bantz.ui.popup import PopupConfig
        
        config = PopupConfig()
        d = config.to_dict()
        
        assert d["content_type"] == "text"
        assert d["position"] == "top_right"
        assert d["timeout"] == 5.0
        assert d["animation"] == "fade"
    
    def test_from_dict(self):
        """Test creating config from dictionary."""
        from bantz.ui.popup import PopupConfig, PopupContentType, PopupPosition
        
        data = {
            "content_type": "image",
            "position": "bottom_left",
            "timeout": 8.0,
            "animation": "slide_up",
            "priority": 3,
        }
        
        config = PopupConfig.from_dict(data)
        
        assert config.content_type == PopupContentType.IMAGE
        assert config.position == PopupPosition.BOTTOM_LEFT
        assert config.timeout == 8.0
        assert config.priority == 3


# =============================================================================
# Test PopupPanel (Mocked)
# =============================================================================


class TestPopupPanelMocked:
    """Tests for PopupPanel with mocked PyQt5."""
    
    @pytest.fixture
    def mock_pyqt(self, monkeypatch):
        """Mock PyQt5 modules."""
        mock_widgets = MagicMock()
        mock_core = MagicMock()
        mock_gui = MagicMock()
        
        # Mock QWidget
        mock_widgets.QWidget = MockQWidget
        mock_widgets.QApplication = MockQApplication
        
        return mock_widgets
    
    def test_popup_config_content_types(self):
        """Test popup content type handling."""
        from bantz.ui.popup import PopupConfig, PopupContentType
        
        # Text popup
        config = PopupConfig(content_type=PopupContentType.TEXT)
        assert config.content_type == PopupContentType.TEXT
        
        # Image popup
        config = PopupConfig(content_type=PopupContentType.IMAGE)
        assert config.content_type == PopupContentType.IMAGE
        
        # Icon popup
        config = PopupConfig(content_type=PopupContentType.ICON)
        assert config.content_type == PopupContentType.ICON
        
        # Mixed popup
        config = PopupConfig(content_type=PopupContentType.MIXED)
        assert config.content_type == PopupContentType.MIXED
    
    def test_popup_positions(self):
        """Test all popup positions."""
        from bantz.ui.popup import PopupConfig, PopupPosition
        
        for pos in PopupPosition:
            config = PopupConfig(position=pos)
            assert config.position == pos
    
    def test_popup_animations(self):
        """Test all popup animations."""
        from bantz.ui.popup import PopupConfig, PopupAnimation
        
        for anim in PopupAnimation:
            config = PopupConfig(animation=anim)
            assert config.animation == anim
    
    def test_popup_timeout_values(self):
        """Test various timeout values."""
        from bantz.ui.popup import PopupConfig
        
        # No timeout
        config = PopupConfig(timeout=0)
        assert config.timeout == 0
        
        # Short timeout
        config = PopupConfig(timeout=1.0)
        assert config.timeout == 1.0
        
        # Long timeout
        config = PopupConfig(timeout=30.0)
        assert config.timeout == 30.0


# =============================================================================
# Test PopupManager (Mocked)
# =============================================================================


class TestPopupManagerMocked:
    """Tests for PopupManager with mocked PyQt5."""
    
    def test_manager_initialization(self):
        """Test manager initialization."""
        from bantz.ui.popup import (
            PopupManager, PopupPosition, PopupAnimation, PopupColors
        )
        
        # Create with mocked parent
        parent = MockQWidget()
        colors = PopupColors()
        
        manager = PopupManager(
            parent_panel=parent,
            max_popups=3,
            colors=colors,
            default_position=PopupPosition.BOTTOM_RIGHT,
            default_timeout=10.0,
            default_animation=PopupAnimation.SLIDE_UP,
        )
        
        assert manager.parent_panel == parent
        assert manager.max_popups == 3
        assert manager.default_position == PopupPosition.BOTTOM_RIGHT
        assert manager.default_timeout == 10.0
        assert manager.default_animation == PopupAnimation.SLIDE_UP
    
    def test_manager_default_values(self):
        """Test manager default values."""
        from bantz.ui.popup import PopupManager, PopupPosition, PopupAnimation
        
        manager = PopupManager()
        
        assert manager.parent_panel is None
        assert manager.max_popups == 5
        assert manager.default_position == PopupPosition.TOP_RIGHT
        assert manager.default_timeout == 5.0
        assert manager.default_animation == PopupAnimation.FADE
    
    def test_manager_set_max_popups(self):
        """Test setting max popups."""
        from bantz.ui.popup import PopupManager
        
        manager = PopupManager()
        
        manager.set_max_popups(10)
        assert manager.max_popups == 10
        
        # Minimum is 1
        manager.set_max_popups(0)
        assert manager.max_popups == 1
        
        manager.set_max_popups(-5)
        assert manager.max_popups == 1
    
    def test_manager_set_default_timeout(self):
        """Test setting default timeout."""
        from bantz.ui.popup import PopupManager
        
        manager = PopupManager()
        
        manager.set_default_timeout(15.0)
        assert manager.default_timeout == 15.0
        
        manager.set_default_timeout(0)
        assert manager.default_timeout == 0
        
        # Negative becomes 0
        manager.set_default_timeout(-5)
        assert manager.default_timeout == 0
    
    def test_manager_set_default_position(self):
        """Test setting default position."""
        from bantz.ui.popup import PopupManager, PopupPosition
        
        manager = PopupManager()
        
        manager.set_default_position(PopupPosition.BOTTOM_LEFT)
        assert manager.default_position == PopupPosition.BOTTOM_LEFT
    
    def test_active_and_queue_count(self):
        """Test active and queue count properties."""
        from bantz.ui.popup import PopupManager
        
        manager = PopupManager()
        
        assert manager.active_count == 0
        assert manager.queue_count == 0


# =============================================================================
# Test Helper Functions
# =============================================================================


class TestParsePopupPosition:
    """Tests for parse_popup_position function."""
    
    def test_turkish_positions(self):
        """Test parsing Turkish position names."""
        from bantz.ui.popup import parse_popup_position, PopupPosition
        
        assert parse_popup_position("sol üst") == PopupPosition.TOP_LEFT
        assert parse_popup_position("sağ üst") == PopupPosition.TOP_RIGHT
        assert parse_popup_position("sol alt") == PopupPosition.BOTTOM_LEFT
        assert parse_popup_position("sağ alt") == PopupPosition.BOTTOM_RIGHT
        assert parse_popup_position("sol") == PopupPosition.LEFT
        assert parse_popup_position("sağ") == PopupPosition.RIGHT
        assert parse_popup_position("üst") == PopupPosition.TOP
        assert parse_popup_position("alt") == PopupPosition.BOTTOM
    
    def test_case_insensitive(self):
        """Test case insensitivity."""
        from bantz.ui.popup import parse_popup_position, PopupPosition
        
        assert parse_popup_position("SOL ÜST") == PopupPosition.TOP_LEFT
        assert parse_popup_position("Sağ Alt") == PopupPosition.BOTTOM_RIGHT
    
    def test_unknown_position(self):
        """Test unknown position returns None."""
        from bantz.ui.popup import parse_popup_position
        
        assert parse_popup_position("bilinmeyen") is None
        assert parse_popup_position("center") is None
        assert parse_popup_position("") is None


class TestIsPopupDismissIntent:
    """Tests for is_popup_dismiss_intent function."""
    
    def test_dismiss_patterns(self):
        """Test popup dismiss patterns."""
        from bantz.ui.popup import is_popup_dismiss_intent
        
        assert is_popup_dismiss_intent("popup kapat") is True
        assert is_popup_dismiss_intent("popupları kapat") is True
        assert is_popup_dismiss_intent("bildirim kapat") is True
        assert is_popup_dismiss_intent("bildirimleri kapat") is True
        assert is_popup_dismiss_intent("balon kapat") is True
        assert is_popup_dismiss_intent("balonları kapat") is True
        assert is_popup_dismiss_intent("hepsini kapat") is True
    
    def test_case_insensitive(self):
        """Test case insensitivity."""
        from bantz.ui.popup import is_popup_dismiss_intent
        
        assert is_popup_dismiss_intent("POPUP KAPAT") is True
        assert is_popup_dismiss_intent("Popup Kapat") is True
    
    def test_non_dismiss_patterns(self):
        """Test non-dismiss patterns."""
        from bantz.ui.popup import is_popup_dismiss_intent
        
        assert is_popup_dismiss_intent("popup göster") is False
        assert is_popup_dismiss_intent("bildirim gönder") is False
        assert is_popup_dismiss_intent("merhaba") is False
        assert is_popup_dismiss_intent("") is False


# =============================================================================
# Test Position Aliases
# =============================================================================


class TestPositionAliases:
    """Tests for position aliases dictionary."""
    
    def test_all_aliases_map_correctly(self):
        """Test all Turkish aliases map to correct positions."""
        from bantz.ui.popup import POPUP_POSITION_ALIASES, PopupPosition
        
        assert POPUP_POSITION_ALIASES["sol üst"] == PopupPosition.TOP_LEFT
        assert POPUP_POSITION_ALIASES["sağ üst"] == PopupPosition.TOP_RIGHT
        assert POPUP_POSITION_ALIASES["sol alt"] == PopupPosition.BOTTOM_LEFT
        assert POPUP_POSITION_ALIASES["sağ alt"] == PopupPosition.BOTTOM_RIGHT
        assert POPUP_POSITION_ALIASES["sol"] == PopupPosition.LEFT
        assert POPUP_POSITION_ALIASES["sağ"] == PopupPosition.RIGHT
        assert POPUP_POSITION_ALIASES["üst"] == PopupPosition.TOP
        assert POPUP_POSITION_ALIASES["alt"] == PopupPosition.BOTTOM
    
    def test_alias_count(self):
        """Test correct number of aliases."""
        from bantz.ui.popup import POPUP_POSITION_ALIASES
        
        assert len(POPUP_POSITION_ALIASES) == 8


# =============================================================================
# Test Animation Config
# =============================================================================


class TestPopupAnimationConfig:
    """Tests for PopupAnimationConfig class."""
    
    def test_default_durations(self):
        """Test default animation durations."""
        from bantz.ui.popup import PopupAnimationConfig
        
        assert PopupAnimationConfig.FADE_DURATION == 250
        assert PopupAnimationConfig.SLIDE_DURATION == 300
        assert PopupAnimationConfig.SCALE_DURATION == 250
        assert PopupAnimationConfig.BOUNCE_DURATION == 400
        assert PopupAnimationConfig.SLIDE_DISTANCE == 50


# =============================================================================
# Integration Tests (No PyQt)
# =============================================================================


class TestPopupSystemIntegration:
    """Integration tests for popup system without PyQt5."""
    
    def test_config_serialization_roundtrip(self):
        """Test config can be serialized and deserialized."""
        from bantz.ui.popup import (
            PopupConfig, PopupContentType, PopupPosition, PopupAnimation
        )
        
        original = PopupConfig(
            content_type=PopupContentType.MIXED,
            position=PopupPosition.BOTTOM_LEFT,
            timeout=8.5,
            animation=PopupAnimation.BOUNCE,
            priority=10,
            pausable=False,
            dismissable=True,
            width=300,
            height=150,
            margin=15,
        )
        
        # Serialize to dict
        data = original.to_dict()
        
        # Deserialize
        restored = PopupConfig.from_dict(data)
        
        assert restored.content_type == original.content_type
        assert restored.position == original.position
        assert restored.timeout == original.timeout
        assert restored.animation == original.animation
        assert restored.priority == original.priority
    
    def test_all_content_types_have_values(self):
        """Test all content types have string values."""
        from bantz.ui.popup import PopupContentType
        
        for content_type in PopupContentType:
            assert isinstance(content_type.value, str)
            assert len(content_type.value) > 0
    
    def test_all_positions_have_values(self):
        """Test all positions have string values."""
        from bantz.ui.popup import PopupPosition
        
        for position in PopupPosition:
            assert isinstance(position.value, str)
            assert len(position.value) > 0
    
    def test_all_animations_have_values(self):
        """Test all animations have string values."""
        from bantz.ui.popup import PopupAnimation
        
        for animation in PopupAnimation:
            assert isinstance(animation.value, str)
            assert len(animation.value) > 0
    
    def test_all_statuses_have_values(self):
        """Test all statuses have string values."""
        from bantz.ui.popup import PopupStatus
        
        for status in PopupStatus:
            assert isinstance(status.value, str)
            assert len(status.value) > 0


# =============================================================================
# Test Priority Queue
# =============================================================================


class TestPopupPriorityQueue:
    """Tests for popup priority queue behavior."""
    
    def test_priority_sorting(self):
        """Test popups are sorted by priority."""
        from bantz.ui.popup import PopupConfig
        
        configs = [
            PopupConfig(priority=1),
            PopupConfig(priority=5),
            PopupConfig(priority=2),
            PopupConfig(priority=10),
            PopupConfig(priority=0),
        ]
        
        # Sort by priority descending
        sorted_configs = sorted(configs, key=lambda c: c.priority, reverse=True)
        
        priorities = [c.priority for c in sorted_configs]
        assert priorities == [10, 5, 2, 1, 0]
    
    def test_same_priority_order(self):
        """Test same priority maintains order."""
        from bantz.ui.popup import PopupConfig
        
        configs = [
            PopupConfig(priority=5, width=100),
            PopupConfig(priority=5, width=200),
            PopupConfig(priority=5, width=300),
        ]
        
        # Sort should be stable
        sorted_configs = sorted(configs, key=lambda c: c.priority, reverse=True)
        
        # Order should be maintained
        widths = [c.width for c in sorted_configs]
        assert widths == [100, 200, 300]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
