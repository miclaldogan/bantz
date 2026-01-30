"""Tests for Jarvis-style overlay UI (Issue #5).

Tests themes, animations, components, and overlay functionality.
Note: These tests mock Qt widgets since we can't run a real Qt event loop in tests.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────
# Theme Tests
# ─────────────────────────────────────────────────────────────────

class TestThemes:
    """Test theme system."""
    
    def test_jarvis_theme_defaults(self):
        """Jarvis theme has correct default colors."""
        from bantz.ui.themes import JARVIS_THEME
        
        assert JARVIS_THEME.name == "jarvis"
        assert JARVIS_THEME.primary == "#00D4FF"
        assert JARVIS_THEME.background == "#0A0A1A"
        assert len(JARVIS_THEME.glow_gradient) == 4
        assert len(JARVIS_THEME.arc_colors) == 4
    
    def test_friday_theme(self):
        """Friday theme has pink colors."""
        from bantz.ui.themes import FRIDAY_THEME
        
        assert FRIDAY_THEME.name == "friday"
        assert FRIDAY_THEME.primary == "#FF69B4"
    
    def test_ultron_theme(self):
        """Ultron theme has red colors."""
        from bantz.ui.themes import ULTRON_THEME
        
        assert ULTRON_THEME.name == "ultron"
        assert ULTRON_THEME.primary == "#FF0000"
    
    def test_vision_theme(self):
        """Vision theme has gold colors."""
        from bantz.ui.themes import VISION_THEME
        
        assert VISION_THEME.name == "vision"
        assert VISION_THEME.primary == "#FFD700"
    
    def test_get_theme(self):
        """get_theme returns correct theme."""
        from bantz.ui.themes import get_theme, JARVIS_THEME, FRIDAY_THEME
        
        assert get_theme("jarvis") == JARVIS_THEME
        assert get_theme("friday") == FRIDAY_THEME
        assert get_theme("unknown") == JARVIS_THEME  # Defaults to Jarvis
    
    def test_list_themes(self):
        """list_themes returns all theme names."""
        from bantz.ui.themes import list_themes
        
        themes = list_themes()
        assert "jarvis" in themes
        assert "friday" in themes
        assert "ultron" in themes
        assert "vision" in themes
    
    def test_register_custom_theme(self):
        """Can register custom themes."""
        from bantz.ui.themes import register_theme, get_theme, OverlayTheme
        
        custom = OverlayTheme(
            name="custom",
            primary="#00FF00",
            background="#000000",
        )
        register_theme("custom", custom)
        
        retrieved = get_theme("custom")
        assert retrieved.primary == "#00FF00"
    
    def test_theme_stylesheet_generation(self):
        """Theme generates valid stylesheet."""
        from bantz.ui.themes import JARVIS_THEME
        
        stylesheet = JARVIS_THEME.stylesheet
        
        assert "QWidget" in stylesheet
        assert "QLabel" in stylesheet
        assert "QPushButton" in stylesheet
        assert JARVIS_THEME.text in stylesheet
        assert JARVIS_THEME.primary in stylesheet
    
    def test_overlay_theme_dataclass_fields(self):
        """OverlayTheme has all required fields."""
        from bantz.ui.themes import OverlayTheme
        
        theme = OverlayTheme()
        
        assert hasattr(theme, "name")
        assert hasattr(theme, "primary")
        assert hasattr(theme, "secondary")
        assert hasattr(theme, "background")
        assert hasattr(theme, "background_opacity")
        assert hasattr(theme, "text")
        assert hasattr(theme, "text_secondary")
        assert hasattr(theme, "success")
        assert hasattr(theme, "warning")
        assert hasattr(theme, "error")
        assert hasattr(theme, "glow_gradient")
        assert hasattr(theme, "arc_colors")
        assert hasattr(theme, "pulse_duration")
        assert hasattr(theme, "fade_duration")
        assert hasattr(theme, "slide_duration")
    
    def test_state_colors(self):
        """State colors for different states."""
        from bantz.ui.themes import StateColors, DEFAULT_STATE_COLORS
        
        assert DEFAULT_STATE_COLORS.idle == "#666666"
        assert DEFAULT_STATE_COLORS.listening == "#00FF88"
        assert DEFAULT_STATE_COLORS.thinking == "#FFB800"
        assert DEFAULT_STATE_COLORS.error == "#FF4444"
        
        # Test for_state method
        assert DEFAULT_STATE_COLORS.for_state("listening") == "#00FF88"
        assert DEFAULT_STATE_COLORS.for_state("unknown") == "#666666"


# ─────────────────────────────────────────────────────────────────
# Animation Tests (without Qt)
# ─────────────────────────────────────────────────────────────────

class TestAnimationConfig:
    """Test animation configuration."""
    
    def test_animation_config_defaults(self):
        """AnimationConfig has correct defaults."""
        from bantz.ui.animations import AnimationConfig
        
        assert AnimationConfig.FADE_DURATION == 300
        assert AnimationConfig.PULSE_DURATION == 1500
        assert AnimationConfig.SLIDE_DURATION == 400
        assert AnimationConfig.GLOW_DURATION == 2000
    
    def test_slide_direction_enum(self):
        """SlideDirection enum has all directions."""
        from bantz.ui.animations import SlideDirection
        
        assert SlideDirection.LEFT.value == "left"
        assert SlideDirection.RIGHT.value == "right"
        assert SlideDirection.UP.value == "up"
        assert SlideDirection.DOWN.value == "down"


# ─────────────────────────────────────────────────────────────────
# Component Tests (with mocked Qt)
# ─────────────────────────────────────────────────────────────────

class TestArcReactorState:
    """Test ReactorState enum."""
    
    def test_reactor_states(self):
        """ReactorState has all states."""
        from bantz.ui.components.arc_reactor import ReactorState
        
        assert ReactorState.IDLE.value == "idle"
        assert ReactorState.WAKE.value == "wake"
        assert ReactorState.LISTENING.value == "listening"
        assert ReactorState.THINKING.value == "thinking"
        assert ReactorState.SPEAKING.value == "speaking"
        assert ReactorState.ERROR.value == "error"
        assert ReactorState.SUCCESS.value == "success"


class TestActionStatus:
    """Test ActionStatus enum."""
    
    def test_action_statuses(self):
        """ActionStatus has all statuses."""
        from bantz.ui.components.action_preview import ActionStatus
        
        assert ActionStatus.PENDING.value == "pending"
        assert ActionStatus.RUNNING.value == "running"
        assert ActionStatus.COMPLETED.value == "completed"
        assert ActionStatus.FAILED.value == "failed"
        assert ActionStatus.SKIPPED.value == "skipped"


class TestOutputType:
    """Test OutputType enum."""
    
    def test_output_types(self):
        """OutputType has all types."""
        from bantz.ui.components.mini_terminal import OutputType
        
        assert OutputType.STDOUT.value == "stdout"
        assert OutputType.STDERR.value == "stderr"
        assert OutputType.COMMAND.value == "command"
        assert OutputType.INFO.value == "info"
        assert OutputType.SUCCESS.value == "success"
        assert OutputType.ERROR.value == "error"


class TestStatusLevel:
    """Test StatusLevel enum."""
    
    def test_status_levels(self):
        """StatusLevel has all levels."""
        from bantz.ui.components.status_bar import StatusLevel
        
        assert StatusLevel.OK.value == "ok"
        assert StatusLevel.WARNING.value == "warning"
        assert StatusLevel.ERROR.value == "error"
        assert StatusLevel.INACTIVE.value == "inactive"
        assert StatusLevel.PROCESSING.value == "processing"


# ─────────────────────────────────────────────────────────────────
# Jarvis Overlay Tests
# ─────────────────────────────────────────────────────────────────

class TestJarvisState:
    """Test JarvisState enum."""
    
    def test_jarvis_states(self):
        """JarvisState has all states."""
        from bantz.ui.jarvis_overlay import JarvisState
        
        assert JarvisState.HIDDEN.name == "HIDDEN"
        assert JarvisState.IDLE.name == "IDLE"
        assert JarvisState.WAKE.name == "WAKE"
        assert JarvisState.LISTENING.name == "LISTENING"
        assert JarvisState.THINKING.name == "THINKING"
        assert JarvisState.SPEAKING.name == "SPEAKING"
        assert JarvisState.ACTION.name == "ACTION"
        assert JarvisState.ERROR.name == "ERROR"


class TestGridPosition:
    """Test GridPosition enum."""
    
    def test_grid_positions(self):
        """GridPosition has all positions."""
        from bantz.ui.jarvis_overlay import GridPosition
        
        assert GridPosition.TOP_LEFT.value == "top-left"
        assert GridPosition.TOP_CENTER.value == "top-center"
        assert GridPosition.TOP_RIGHT.value == "top-right"
        assert GridPosition.MID_LEFT.value == "mid-left"
        assert GridPosition.CENTER.value == "center"
        assert GridPosition.MID_RIGHT.value == "mid-right"
        assert GridPosition.BOTTOM_LEFT.value == "bottom-left"
        assert GridPosition.BOTTOM_CENTER.value == "bottom-center"
        assert GridPosition.BOTTOM_RIGHT.value == "bottom-right"
    
    def test_position_aliases(self):
        """Turkish position aliases map correctly."""
        from bantz.ui.jarvis_overlay import POSITION_ALIASES, GridPosition
        
        assert POSITION_ALIASES["sol üst"] == GridPosition.TOP_LEFT
        assert POSITION_ALIASES["sağ üst"] == GridPosition.TOP_RIGHT
        assert POSITION_ALIASES["orta"] == GridPosition.CENTER
        assert POSITION_ALIASES["ortaya"] == GridPosition.CENTER
        assert POSITION_ALIASES["sol alt"] == GridPosition.BOTTOM_LEFT
        assert POSITION_ALIASES["sağ alt"] == GridPosition.BOTTOM_RIGHT


class TestPackageExports:
    """Test package exports."""
    
    def test_ui_init_exports(self):
        """bantz.ui exports all required items."""
        import bantz.ui as ui
        
        # Themes
        assert hasattr(ui, "OverlayTheme")
        assert hasattr(ui, "JARVIS_THEME")
        assert hasattr(ui, "FRIDAY_THEME")
        assert hasattr(ui, "ULTRON_THEME")
        assert hasattr(ui, "get_theme")
        assert hasattr(ui, "list_themes")
        
        # Animations
        assert hasattr(ui, "fade_in")
        assert hasattr(ui, "fade_out")
        assert hasattr(ui, "slide_in")
        assert hasattr(ui, "slide_out")
        assert hasattr(ui, "PulseAnimation")
        assert hasattr(ui, "GlowAnimation")
        
        # Overlay
        assert hasattr(ui, "JarvisOverlay")
        assert hasattr(ui, "JarvisState")
        assert hasattr(ui, "GridPosition")
        assert hasattr(ui, "create_jarvis_overlay")
        
        # Components
        assert hasattr(ui, "ArcReactorWidget")
        assert hasattr(ui, "WaveformWidget")
        assert hasattr(ui, "ActionPreviewWidget")
        assert hasattr(ui, "MiniTerminalWidget")
        assert hasattr(ui, "StatusBarWidget")
        assert hasattr(ui, "StatusLevel")
    
    def test_components_init_exports(self):
        """bantz.ui.components exports all components."""
        from bantz.ui import components
        
        assert hasattr(components, "ArcReactorWidget")
        assert hasattr(components, "MiniArcReactor")
        assert hasattr(components, "ReactorState")
        assert hasattr(components, "WaveformWidget")
        assert hasattr(components, "ActionPreviewWidget")
        assert hasattr(components, "MiniTerminalWidget")
        assert hasattr(components, "StatusBarWidget")


# ─────────────────────────────────────────────────────────────────
# Integration Tests (with mocked Qt)
# ─────────────────────────────────────────────────────────────────

class TestOutputLine:
    """Test OutputLine dataclass."""
    
    def test_output_line_creation(self):
        """OutputLine stores text and type."""
        from bantz.ui.components.mini_terminal import OutputLine, OutputType
        
        line = OutputLine(text="Hello", output_type=OutputType.STDOUT)
        
        assert line.text == "Hello"
        assert line.output_type == OutputType.STDOUT
        assert line.timestamp is None
    
    def test_output_line_defaults(self):
        """OutputLine has correct defaults."""
        from bantz.ui.components.mini_terminal import OutputLine, OutputType
        
        line = OutputLine(text="Test")
        
        assert line.output_type == OutputType.STDOUT


class TestThemeQColorMethods:
    """Test theme QColor methods."""
    
    def test_get_qcolor(self):
        """get_qcolor returns QColor."""
        from bantz.ui.themes import JARVIS_THEME
        from PyQt5.QtGui import QColor
        
        color = JARVIS_THEME.get_qcolor("primary")
        
        assert isinstance(color, QColor)
        assert color.name() == "#00d4ff"
    
    def test_get_background_qcolor(self):
        """get_background_qcolor applies opacity."""
        from bantz.ui.themes import JARVIS_THEME
        from PyQt5.QtGui import QColor
        
        color = JARVIS_THEME.get_background_qcolor()
        
        assert isinstance(color, QColor)
        # Use pytest.approx for floating point comparison
        assert color.alphaF() == pytest.approx(JARVIS_THEME.background_opacity, abs=1e-3)
    
    def test_get_arc_qcolors(self):
        """get_arc_qcolors returns list of QColors."""
        from bantz.ui.themes import JARVIS_THEME
        from PyQt5.QtGui import QColor
        
        colors = JARVIS_THEME.get_arc_qcolors()
        
        assert len(colors) == 4
        assert all(isinstance(c, QColor) for c in colors)


class TestStateColorHelper:
    """Test get_state_color helper."""
    
    def test_get_state_color_with_theme(self):
        """get_state_color uses theme colors for wake/listening."""
        from bantz.ui.themes import get_state_color, JARVIS_THEME
        from PyQt5.QtGui import QColor
        
        color = get_state_color("wake", JARVIS_THEME)
        
        assert isinstance(color, QColor)
        assert color.name() == "#00d4ff"  # Theme primary
    
    def test_get_state_color_error(self):
        """get_state_color returns error color for error state."""
        from bantz.ui.themes import get_state_color, JARVIS_THEME
        from PyQt5.QtGui import QColor
        
        color = get_state_color("error", JARVIS_THEME)
        
        assert isinstance(color, QColor)
        assert color.name() == JARVIS_THEME.error.lower()
    
    def test_get_state_color_without_theme(self):
        """get_state_color works without theme."""
        from bantz.ui.themes import get_state_color
        from PyQt5.QtGui import QColor
        
        color = get_state_color("listening")
        
        assert isinstance(color, QColor)
