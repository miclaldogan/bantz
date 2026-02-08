"""Controls module — PTT hotkey, mic mute, status indicator (Issue #298).

Provides alternative control mechanisms for the voice pipeline:
- Push-to-talk (PTT) hotkey
- Mic mute/unmute toggle
- Status indicator (terminal / callback)
"""

from bantz.controls.hotkeys import HotkeyConfig, HotkeyManager
from bantz.controls.ptt import PTTController, PTTState
from bantz.controls.mute import MuteController
from bantz.controls.indicator import StatusIndicator, VoiceStatus

__all__ = [
    "HotkeyConfig",
    "HotkeyManager",
    "PTTController",
    "PTTState",
    "MuteController",
    "StatusIndicator",
    "VoiceStatus",
]
