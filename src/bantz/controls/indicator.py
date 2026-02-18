"""Status indicator for voice pipeline state (Issue #298).

Displays the current voice state in the terminal or via a callback.
Supports multiple output modes: terminal, callback, silent.

Usage::

    indicator = StatusIndicator()
    indicator.update(VoiceStatus.LISTENING)
    # Terminal: "[BANTZ] 🎤 DİNLİYOR"
"""

from __future__ import annotations

import logging
import sys
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["StatusIndicator", "VoiceStatus"]


class VoiceStatus(str, Enum):
    """Voice pipeline status."""

    WAKE_ONLY = "wake_only"      # Waiting for wake word
    LISTENING = "listening"       # Actively listening
    PROCESSING = "processing"    # Processing speech
    SPEAKING = "speaking"        # TTS playing
    IDLE_SLEEP = "idle_sleep"    # Idle / sleeping
    MUTED = "muted"              # Mic muted
    ERROR = "error"              # Error state

    @property
    def label_tr(self) -> str:
        """Turkish label."""
        labels = {
            VoiceStatus.WAKE_ONLY: "BEKLEMEDE",
            VoiceStatus.LISTENING: "DİNLİYOR",
            VoiceStatus.PROCESSING: "PROCESSING",
            VoiceStatus.SPEAKING: "SPEAKING",
            VoiceStatus.IDLE_SLEEP: "UYUYOR",
            VoiceStatus.MUTED: "SESSİZ",
            VoiceStatus.ERROR: "ERROR",
        }
        return labels.get(self, "UNKNOWN")

    @property
    def icon(self) -> str:
        """Emoji icon."""
        icons = {
            VoiceStatus.WAKE_ONLY: "💤",
            VoiceStatus.LISTENING: "🎤",
            VoiceStatus.PROCESSING: "🟡",
            VoiceStatus.SPEAKING: "🔊",
            VoiceStatus.IDLE_SLEEP: "😴",
            VoiceStatus.MUTED: "🔇",
            VoiceStatus.ERROR: "🟠",
        }
        return icons.get(self, "❓")


class StatusIndicator:
    """Voice status display.

    Parameters
    ----------
    mode:
        Output mode: "terminal", "callback", "silent".
    callback:
        Custom callback ``(status: VoiceStatus) -> None``.
    """

    def __init__(
        self,
        mode: str = "terminal",
        callback: Optional[Callable[["VoiceStatus"], None]] = None,
    ) -> None:
        self._mode = mode
        self._callback = callback
        self._status = VoiceStatus.IDLE_SLEEP
        self._status_since: float = time.time()
        self._update_count = 0

    @property
    def status(self) -> VoiceStatus:
        return self._status

    @property
    def status_duration(self) -> float:
        """Seconds since last status change."""
        return time.time() - self._status_since

    @property
    def update_count(self) -> int:
        return self._update_count

    def update(self, new_status: VoiceStatus) -> None:
        """Update the displayed status.

        Parameters
        ----------
        new_status:
            New voice pipeline status.
        """
        if new_status == self._status:
            return

        old = self._status
        self._status = new_status
        self._status_since = time.time()
        self._update_count += 1

        logger.debug("Status: %s → %s", old.value, new_status.value)

        if self._mode == "terminal":
            self._display_terminal(new_status)
        elif self._mode == "callback" and self._callback:
            try:
                self._callback(new_status)
            except Exception as exc:
                logger.warning("Status callback failed: %s", exc)
        # silent: do nothing

    def _display_terminal(self, status: VoiceStatus) -> None:
        """Show status in terminal."""
        text = f"[BANTZ] {status.icon} {status.label_tr}"
        if sys.stderr.isatty():
            sys.stderr.write(f"\r{text}   ")
            sys.stderr.flush()
        else:
            logger.info("Status: %s", text)

    def get_status_line(self) -> str:
        """Return a formatted status line string."""
        return f"{self._status.icon} {self._status.label_tr}"

    def reset(self) -> None:
        """Reset to idle/sleep state."""
        self._status = VoiceStatus.IDLE_SLEEP
        self._status_since = time.time()
        self._update_count = 0
