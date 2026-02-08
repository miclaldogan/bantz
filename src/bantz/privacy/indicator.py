"""Mic indicator — shows user when microphone is active (Issue #299).

Provides visual feedback so the user always knows when they're being
listened to. Supports multiple output modes:
- Terminal (emoji-based)
- Callback (for GUI/tray icon integration)
- Silent (headless/CI)

Usage::

    indicator = MicIndicator()
    indicator.on_state_change(MicState.LISTENING)
    # Terminal: "🔴 DİNLENİYOR"
    indicator.on_state_change(MicState.IDLE)
    # Terminal: "⚪ HAZIR"
"""

from __future__ import annotations

import logging
import sys
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["MicIndicator", "MicState"]


# ─────────────────────────────────────────────────────────────────
# States
# ─────────────────────────────────────────────────────────────────


class MicState(str, Enum):
    """Microphone state for the indicator."""

    IDLE = "idle"                    # Not listening
    LISTENING = "listening"          # Actively listening (ASR)
    PROCESSING = "processing"       # Processing speech
    SPEAKING = "speaking"           # TTS is playing
    ERROR = "error"                 # Mic error

    @property
    def label_tr(self) -> str:
        """Turkish label for the state."""
        labels = {
            MicState.IDLE: "HAZIR",
            MicState.LISTENING: "DİNLENİYOR",
            MicState.PROCESSING: "İŞLENİYOR",
            MicState.SPEAKING: "KONUŞUYOR",
            MicState.ERROR: "HATA",
        }
        return labels.get(self, "BİLİNMİYOR")

    @property
    def icon(self) -> str:
        """Emoji icon for the state."""
        icons = {
            MicState.IDLE: "⚪",
            MicState.LISTENING: "🔴",
            MicState.PROCESSING: "🟡",
            MicState.SPEAKING: "🔵",
            MicState.ERROR: "🟠",
        }
        return icons.get(self, "⚫")


# ─────────────────────────────────────────────────────────────────
# Indicator
# ─────────────────────────────────────────────────────────────────


class MicIndicator:
    """Visual microphone state indicator.

    Parameters
    ----------
    mode:
        Output mode: "terminal", "callback", "silent".
    callback:
        Custom callback ``(state: MicState) -> None`` for GUI integration.
    """

    def __init__(
        self,
        mode: str = "terminal",
        callback: Optional[Callable[["MicState"], None]] = None,
    ) -> None:
        self._mode = mode
        self._callback = callback
        self._state = MicState.IDLE
        self._state_since: float = time.time()
        self._state_history: list[tuple[MicState, float]] = []

    @property
    def state(self) -> MicState:
        """Current mic state."""
        return self._state

    @property
    def state_duration(self) -> float:
        """Seconds since last state change."""
        return time.time() - self._state_since

    @property
    def state_history(self) -> list[tuple[MicState, float]]:
        """History of state changes ``(state, timestamp)``."""
        return list(self._state_history)

    def on_state_change(self, new_state: MicState) -> None:
        """Notify indicator of a microphone state change.

        Parameters
        ----------
        new_state:
            The new microphone state.
        """
        if new_state == self._state:
            return  # No change

        old = self._state
        self._state = new_state
        self._state_since = time.time()
        self._state_history.append((new_state, self._state_since))

        logger.debug("Mic state: %s → %s", old.value, new_state.value)

        if self._mode == "terminal":
            self._show_terminal(new_state)
        elif self._mode == "callback" and self._callback:
            try:
                self._callback(new_state)
            except Exception as exc:
                logger.warning("Mic indicator callback failed: %s", exc)
        # silent mode: do nothing

    def _show_terminal(self, state: MicState) -> None:
        """Show state in terminal with emoji."""
        indicator = f"{state.icon} {state.label_tr}"
        # Overwrite current line for clean display
        if sys.stderr.isatty():
            sys.stderr.write(f"\r{indicator}   ")
            sys.stderr.flush()
        else:
            logger.info("Mic: %s", indicator)

    def reset(self) -> None:
        """Reset to idle state."""
        self.on_state_change(MicState.IDLE)
        self._state_history.clear()
