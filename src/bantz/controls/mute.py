"""Mic mute/unmute toggle controller (Issue #298).

Provides a simple mute toggle for the microphone. When muted,
the voice pipeline should not process any audio input.

Usage::

    mute = MuteController(on_mute=pause_mic, on_unmute=resume_mic)
    mute.toggle()   # Mute
    mute.toggle()   # Unmute
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["MuteController"]


class MuteController:
    """Mic mute/unmute toggle.

    Parameters
    ----------
    on_mute:
        Callback when mic is muted.
    on_unmute:
        Callback when mic is unmuted.
    initially_muted:
        Start in muted state.
    """

    def __init__(
        self,
        on_mute: Optional[Callable[[], None]] = None,
        on_unmute: Optional[Callable[[], None]] = None,
        initially_muted: bool = False,
    ) -> None:
        self._on_mute = on_mute
        self._on_unmute = on_unmute
        self._muted = initially_muted
        self._toggle_count = 0
        self._last_toggle: Optional[float] = None

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def toggle_count(self) -> int:
        return self._toggle_count

    @property
    def last_toggle_time(self) -> Optional[float]:
        return self._last_toggle

    def toggle(self) -> bool:
        """Toggle mute state.

        Returns the new muted state (True = muted, False = unmuted).
        """
        self._muted = not self._muted
        self._toggle_count += 1
        self._last_toggle = time.time()

        if self._muted:
            logger.info("🔇 Mikrofon kapatıldı")
            if self._on_mute:
                try:
                    self._on_mute()
                except Exception as exc:
                    logger.warning("on_mute callback failed: %s", exc)
        else:
            logger.info("🔊 Mikrofon açıldı")
            if self._on_unmute:
                try:
                    self._on_unmute()
                except Exception as exc:
                    logger.warning("on_unmute callback failed: %s", exc)

        return self._muted

    def mute(self) -> None:
        """Force mute (no-op if already muted)."""
        if not self._muted:
            self.toggle()

    def unmute(self) -> None:
        """Force unmute (no-op if already unmuted)."""
        if self._muted:
            self.toggle()

    def reset(self) -> None:
        """Reset to unmuted state with zero count."""
        self._muted = False
        self._toggle_count = 0
        self._last_toggle = None
