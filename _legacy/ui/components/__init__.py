"""Jarvis UI Components package (Issue #5).

Components:
- ArcReactorWidget: Circular Jarvis-style indicator
- WaveformWidget: Real-time audio visualization
- ActionPreviewWidget: Action preview with progress
- MiniTerminalWidget: Compact terminal output
- StatusBarWidget: Status indicators
"""
from .arc_reactor import ArcReactorWidget, MiniArcReactor, ReactorState
from .waveform import WaveformWidget, CompactWaveform
from .action_preview import ActionPreviewWidget, ActionStatus, JarvisProgressBar
from .mini_terminal import MiniTerminalWidget, CollapsibleTerminal, OutputType, OutputLine
from .status_bar import StatusBarWidget, StatusIndicator, CompactStatusBar, StatusLevel

__all__ = [
    # Arc Reactor
    "ArcReactorWidget",
    "MiniArcReactor",
    "ReactorState",
    # Waveform
    "WaveformWidget",
    "CompactWaveform",
    # Action Preview
    "ActionPreviewWidget",
    "ActionStatus",
    "JarvisProgressBar",
    # Mini Terminal
    "MiniTerminalWidget",
    "CollapsibleTerminal",
    "OutputType",
    "OutputLine",
    # Status Bar
    "StatusBarWidget",
    "StatusIndicator",
    "CompactStatusBar",
    "StatusLevel",
]
