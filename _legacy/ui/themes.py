"""Jarvis-style theme system for Bantz overlay (Issue #5).

Provides color palettes, gradients, and styling for:
- Jarvis (Arc Reactor Blue)
- Friday (Pink/Magenta)
- Ultron (Red/Crimson)
- Custom themes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from PyQt5.QtGui import QColor, QLinearGradient, QRadialGradient


class ThemeName(Enum):
    """Available theme names."""
    JARVIS = "jarvis"
    FRIDAY = "friday"
    ULTRON = "ultron"
    VISION = "vision"
    CUSTOM = "custom"


@dataclass
class OverlayTheme:
    """Color theme for Jarvis-style overlay.
    
    Attributes:
        name: Theme identifier
        primary: Main accent color (glow, borders)
        secondary: Secondary accent
        background: Background color (semi-transparent)
        background_opacity: Background opacity (0.0-1.0)
        text: Primary text color
        text_secondary: Secondary/muted text color
        success: Success state color
        warning: Warning state color
        error: Error state color
        glow_gradient: Colors for glow effect (inner to outer)
        arc_colors: Colors for arc reactor rings
    """
    name: str = "jarvis"
    
    # Core colors
    primary: str = "#00D4FF"          # Arc reactor cyan
    secondary: str = "#0088FF"        # Deeper blue
    background: str = "#0A0A1A"       # Dark blue-black
    background_opacity: float = 0.92
    
    # Text colors
    text: str = "#FFFFFF"
    text_secondary: str = "#B0B0B0"
    
    # State colors
    success: str = "#00FF88"          # Bright green
    warning: str = "#FFB800"          # Amber
    error: str = "#FF4444"            # Red
    
    # Gradients
    glow_gradient: List[str] = field(default_factory=lambda: [
        "#00D4FF",  # Inner glow (bright)
        "#0088FF",  # Mid glow
        "#004488",  # Outer glow
        "#002244",  # Edge (fades to transparent)
    ])
    
    arc_colors: List[str] = field(default_factory=lambda: [
        "#00D4FF",  # Outer ring
        "#0088FF",  # Middle ring
        "#00CCFF",  # Inner ring
        "#FFFFFF",  # Core (brightest)
    ])
    
    # Animation speeds (ms)
    pulse_duration: int = 1500
    fade_duration: int = 300
    slide_duration: int = 400
    
    def get_qcolor(self, color_name: str) -> QColor:
        """Get a QColor from theme attribute name."""
        color_hex = getattr(self, color_name, self.primary)
        return QColor(color_hex)
    
    def get_background_qcolor(self) -> QColor:
        """Get background color with opacity applied."""
        color = QColor(self.background)
        color.setAlphaF(self.background_opacity)
        return color
    
    def get_glow_gradient(self, center_x: float, center_y: float, radius: float) -> QRadialGradient:
        """Create radial gradient for glow effect."""
        gradient = QRadialGradient(center_x, center_y, radius)
        
        stops = len(self.glow_gradient)
        for i, color_hex in enumerate(self.glow_gradient):
            color = QColor(color_hex)
            if i == stops - 1:
                color.setAlpha(0)  # Fade to transparent
            else:
                color.setAlpha(int(255 * (1 - i / stops)))
            gradient.setColorAt(i / (stops - 1), color)
        
        return gradient
    
    def get_linear_gradient(self, x1: float, y1: float, x2: float, y2: float) -> QLinearGradient:
        """Create linear gradient from glow colors."""
        gradient = QLinearGradient(x1, y1, x2, y2)
        
        stops = len(self.glow_gradient)
        for i, color_hex in enumerate(self.glow_gradient[:3]):  # Use first 3 colors
            gradient.setColorAt(i / 2, QColor(color_hex))
        
        return gradient
    
    def get_arc_qcolors(self) -> List[QColor]:
        """Get arc reactor ring colors as QColors."""
        return [QColor(c) for c in self.arc_colors]
    
    @property
    def stylesheet(self) -> str:
        """Generate base stylesheet for widgets using this theme."""
        return f"""
            QWidget {{
                background: transparent;
                color: {self.text};
                font-family: 'Segoe UI', 'SF Pro Display', -apple-system, sans-serif;
            }}
            QLabel {{
                color: {self.text};
            }}
            QPushButton {{
                background-color: rgba(0, 0, 0, 0.3);
                color: {self.text};
                border: 1px solid {self.primary};
                border-radius: 5px;
                padding: 5px 10px;
            }}
            QPushButton:hover {{
                background-color: {self.primary};
                color: {self.background};
            }}
            QScrollBar:vertical {{
                background: rgba(0, 0, 0, 0.2);
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {self.primary};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """


# ─────────────────────────────────────────────────────────────────
# Predefined Themes
# ─────────────────────────────────────────────────────────────────

JARVIS_THEME = OverlayTheme(
    name="jarvis",
    primary="#00D4FF",
    secondary="#0088FF",
    background="#0A0A1A",
    glow_gradient=["#00D4FF", "#0088FF", "#004488", "#002244"],
    arc_colors=["#00D4FF", "#0088FF", "#00CCFF", "#FFFFFF"],
)

FRIDAY_THEME = OverlayTheme(
    name="friday",
    primary="#FF69B4",          # Hot pink
    secondary="#FF1493",        # Deep pink
    background="#1A0A14",       # Dark magenta
    success="#FF69B4",
    glow_gradient=["#FF69B4", "#FF1493", "#880044", "#440022"],
    arc_colors=["#FF69B4", "#FF1493", "#FFB6C1", "#FFFFFF"],
)

ULTRON_THEME = OverlayTheme(
    name="ultron",
    primary="#FF0000",          # Red
    secondary="#CC0000",        # Dark red
    background="#1A0A0A",       # Dark red-black
    warning="#FF4400",
    error="#FF0000",
    glow_gradient=["#FF0000", "#CC0000", "#880000", "#440000"],
    arc_colors=["#FF0000", "#CC0000", "#FF4444", "#FFFFFF"],
)

VISION_THEME = OverlayTheme(
    name="vision",
    primary="#FFD700",          # Gold
    secondary="#FFA500",        # Orange
    background="#1A1A0A",       # Dark gold
    success="#00FF00",
    glow_gradient=["#FFD700", "#FFA500", "#885500", "#442200"],
    arc_colors=["#FFD700", "#FFA500", "#FFFF00", "#FFFFFF"],
)

# Theme registry
THEMES: Dict[str, OverlayTheme] = {
    "jarvis": JARVIS_THEME,
    "friday": FRIDAY_THEME,
    "ultron": ULTRON_THEME,
    "vision": VISION_THEME,
}


def get_theme(name: str) -> OverlayTheme:
    """Get theme by name, defaults to Jarvis."""
    return THEMES.get(name.lower(), JARVIS_THEME)


def register_theme(name: str, theme: OverlayTheme) -> None:
    """Register a custom theme."""
    theme.name = name
    THEMES[name.lower()] = theme


def list_themes() -> List[str]:
    """List available theme names."""
    return list(THEMES.keys())


# ─────────────────────────────────────────────────────────────────
# State Colors
# ─────────────────────────────────────────────────────────────────

@dataclass
class StateColors:
    """Colors for different assistant states."""
    idle: str = "#666666"       # Gray (dormant)
    wake: str = "#00D4FF"       # Primary (waking up)
    listening: str = "#00FF88"  # Green (active listening)
    thinking: str = "#FFB800"   # Amber (processing)
    speaking: str = "#8B5CF6"   # Purple (responding)
    error: str = "#FF4444"      # Red (error)
    
    def for_state(self, state: str) -> str:
        """Get color for a state name."""
        return getattr(self, state.lower(), self.idle)
    
    def get_qcolor(self, state: str) -> QColor:
        """Get QColor for a state."""
        return QColor(self.for_state(state))


DEFAULT_STATE_COLORS = StateColors()


def get_state_color(state: str, theme: Optional[OverlayTheme] = None) -> QColor:
    """Get the appropriate color for an assistant state.
    
    Uses theme's primary color for wake/listening, 
    and state-specific colors otherwise.
    """
    state_lower = state.lower()
    
    if theme is not None:
        if state_lower in ("wake", "listening"):
            return QColor(theme.primary)
        elif state_lower == "success":
            return QColor(theme.success)
        elif state_lower == "error":
            return QColor(theme.error)
        elif state_lower == "thinking":
            return QColor(theme.warning)
    
    return DEFAULT_STATE_COLORS.get_qcolor(state)
