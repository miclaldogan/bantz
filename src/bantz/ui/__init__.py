"""Bantz UI components - Overlay and visual feedback (Issue #5).

Provides Jarvis-style overlay with:
- Arc reactor circular indicator
- Voice waveform visualization
- Action preview with progress
- Mini terminal output
- Multiple themes (Jarvis, Friday, Ultron)
"""

from .themes import (
    OverlayTheme,
    JARVIS_THEME,
    FRIDAY_THEME,
    ULTRON_THEME,
    VISION_THEME,
    get_theme,
    register_theme,
    list_themes,
)

from .animations import (
    fade_in,
    fade_out,
    slide_in,
    slide_out,
    slide_to,
    PulseAnimation,
    GlowAnimation,
    ColorTransition,
    AnimationManager,
)

from .jarvis_overlay import (
    JarvisOverlay,
    JarvisState,
    GridPosition,
    POSITION_ALIASES,
    create_jarvis_overlay,
)

from .components import (
    ArcReactorWidget,
    MiniArcReactor,
    ReactorState,
    WaveformWidget,
    ActionPreviewWidget,
    MiniTerminalWidget,
    StatusBarWidget,
    StatusLevel,
)

__all__ = [
    # Themes
    "OverlayTheme",
    "JARVIS_THEME",
    "FRIDAY_THEME",
    "ULTRON_THEME",
    "VISION_THEME",
    "get_theme",
    "register_theme",
    "list_themes",
    # Animations
    "fade_in",
    "fade_out",
    "slide_in",
    "slide_out",
    "slide_to",
    "PulseAnimation",
    "GlowAnimation",
    "ColorTransition",
    "AnimationManager",
    # Overlay
    "JarvisOverlay",
    "JarvisState",
    "GridPosition",
    "POSITION_ALIASES",
    "create_jarvis_overlay",
    # Components
    "ArcReactorWidget",
    "MiniArcReactor",
    "ReactorState",
    "WaveformWidget",
    "ActionPreviewWidget",
    "MiniTerminalWidget",
    "StatusBarWidget",
    "StatusLevel",
]
