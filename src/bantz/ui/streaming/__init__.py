"""Live Action Streaming & Visualization package (Issue #7).

Provides real-time visualization of Bantz actions:
- Mini preview window for target apps
- Action highlighting with ripples and trails
- Progress tracking for multi-step tasks
- Screen recording with annotations
"""
from .mini_preview import (
    MiniPreviewWidget,
    PreviewMode,
    CaptureTarget,
    CursorOverlay,
)
from .highlighter import (
    ActionHighlighter,
    HighlightBox,
    ClickRipple,
    MouseTrail,
    HighlightStyle,
)
from .progress_tracker import (
    ProgressTracker,
    TaskStep,
    StepStatus,
    ProgressStyle,
)
from .recorder import (
    ActionRecorder,
    RecordingAnnotation,
    RecordingConfig,
    RecordingState,
)
from .manager import (
    StreamingManager,
    StreamingConfig,
    ActionEvent,
    EventType,
)

__all__ = [
    # Mini Preview
    "MiniPreviewWidget",
    "PreviewMode",
    "CaptureTarget",
    "CursorOverlay",
    # Highlighter
    "ActionHighlighter",
    "HighlightBox",
    "ClickRipple",
    "MouseTrail",
    "HighlightStyle",
    # Progress Tracker
    "ProgressTracker",
    "TaskStep",
    "StepStatus",
    "ProgressStyle",
    # Recorder
    "ActionRecorder",
    "RecordingAnnotation",
    "RecordingConfig",
    "RecordingState",
    # Manager
    "StreamingManager",
    "StreamingConfig",
    "ActionEvent",
    "EventType",
]
