"""Bantz UI components - Overlay and visual feedback (Issue #5, #7).

Provides Jarvis-style overlay with:
- Arc reactor circular indicator
- Voice waveform visualization
- Action preview with progress
- Mini terminal output
- Multiple themes (Jarvis, Friday, Ultron)

Live Action Streaming (Issue #7):
- Mini preview window for target apps
- Action highlighting with ripples
- Progress tracking for tasks
- Screen recording with annotations
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

# Issue #19: Jarvis Panel UI
from .jarvis_panel import (
    JarvisPanel,
    JarvisPanelController,
    PanelPosition,
    PanelColors,
    PANEL_POSITION_ALIASES,
    ResultItem,
    SummaryData,
    create_jarvis_panel,
    MockJarvisPanel,
    MockJarvisPanelController,
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

# Issue #7: Live Action Streaming
from .streaming import (
    # Mini Preview
    MiniPreviewWidget,
    PreviewMode,
    CaptureTarget,
    # Highlighter
    ActionHighlighter,
    HighlightBox,
    ClickRipple,
    MouseTrail,
    HighlightStyle,
    # Progress Tracker
    ProgressTracker,
    TaskStep,
    StepStatus,
    ProgressStyle,
    # Recorder
    ActionRecorder,
    RecordingAnnotation,
    RecordingConfig,
    RecordingState,
    # Manager
    StreamingManager,
    StreamingConfig,
    ActionEvent,
    EventType,
)

# Issue #34: Jarvis Panel V2 (animations + cards + images + ticker)
from .jarvis_panel_v2 import (
    JarvisPanelV2,
    PanelState,
    PanelConfig,
)

from .panel_animator import (
    PanelAnimator,
    AnimationType,
)

from .source_card import (
    SourceCard,
    SourceCardData,
    RELIABILITY_COLORS,
    RELIABILITY_LABELS,
)

from .ticker import (
    Ticker,
    TickerMode,
)

from .image_slot import (
    ImageSlot,
    ImageLoader,
)

from .event_binding import (
    PanelEventBinder,
    PanelEventConfig,
    create_panel_binder,
)

# Issue #63: Popup/Bubble System
from .popup import (
    PopupPanel,
    PopupManager,
    PopupContentType,
    PopupPosition,
    PopupAnimation,
    PopupStatus,
    PopupColors,
    PopupConfig,
    PopupAnimationConfig,
    POPUP_POSITION_ALIASES,
    parse_popup_position,
    is_popup_dismiss_intent,
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
    # Panel (Issue #19)
    "JarvisPanel",
    "JarvisPanelController",
    "PanelPosition",
    "PanelColors",
    "PANEL_POSITION_ALIASES",
    "ResultItem",
    "SummaryData",
    "create_jarvis_panel",
    "MockJarvisPanel",
    "MockJarvisPanelController",
    # Components
    "ArcReactorWidget",
    "MiniArcReactor",
    "ReactorState",
    "WaveformWidget",
    "ActionPreviewWidget",
    "MiniTerminalWidget",
    "StatusBarWidget",
    "StatusLevel",
    # Streaming (Issue #7)
    "MiniPreviewWidget",
    "PreviewMode",
    "CaptureTarget",
    "ActionHighlighter",
    "HighlightBox",
    "ClickRipple",
    "MouseTrail",
    "HighlightStyle",
    "ProgressTracker",
    "TaskStep",
    "StepStatus",
    "ProgressStyle",
    "ActionRecorder",
    "RecordingAnnotation",
    "RecordingConfig",
    "RecordingState",
    "StreamingManager",
    "StreamingConfig",
    "ActionEvent",
    "EventType",
    # Panel V2 (Issue #34)
    "JarvisPanelV2",
    "PanelState",
    "PanelConfig",
    "PanelAnimator",
    "AnimationType",
    "SourceCard",
    "SourceCardData",
    "RELIABILITY_COLORS",
    "RELIABILITY_LABELS",
    "Ticker",
    "TickerMode",
    "ImageSlot",
    "ImageLoader",
    "PanelEventBinder",
    "PanelEventConfig",
    "create_panel_binder",
    # Popup/Bubble System (Issue #63)
    "PopupPanel",
    "PopupManager",
    "PopupContentType",
    "PopupPosition",
    "PopupAnimation",
    "PopupStatus",
    "PopupColors",
    "PopupConfig",
    "PopupAnimationConfig",
    "POPUP_POSITION_ALIASES",
    "parse_popup_position",
    "is_popup_dismiss_intent",
]
