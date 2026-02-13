"""Push-to-talk controller (Issue #298).

PTT mode: user holds a key to speak, releases to stop.
While held → voice pipeline enters ACTIVE_LISTEN.
On release → process what was said, return to WAKE_ONLY.

Usage::

    ptt = PTTController(on_start=start_listening, on_stop=stop_listening)
    ptt.press()   # Start listening
    ptt.release() # Stop listening, process audio
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["PTTController", "PTTState"]


class PTTState(str, Enum):
    """Push-to-talk state."""

    IDLE = "idle"          # Not pressed
    HELD = "held"          # Key held — listening
    PROCESSING = "processing"  # Released — processing captured audio


class PTTController:
    """Push-to-talk controller.

    Parameters
    ----------
    on_start:
        Callback when PTT key is pressed (start listening).
    on_stop:
        Callback when PTT key is released (stop listening, process).
    min_hold_ms:
        Minimum hold time to consider valid speech (avoids accidental taps).
    """

    def __init__(
        self,
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        min_hold_ms: int = 200,
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._min_hold_ms = min_hold_ms
        self._state = PTTState.IDLE
        self._press_time: Optional[float] = None
        self._press_count = 0
        self._total_hold_ms = 0.0

    @property
    def state(self) -> PTTState:
        return self._state

    @property
    def press_count(self) -> int:
        """Total number of valid PTT activations."""
        return self._press_count

    @property
    def total_hold_ms(self) -> float:
        """Total accumulated hold time in ms."""
        return self._total_hold_ms

    @property
    def is_held(self) -> bool:
        return self._state == PTTState.HELD

    def press(self) -> bool:
        """PTT key pressed — start listening.

        Returns True if state changed to HELD.
        """
        if self._state != PTTState.IDLE:
            return False

        self._state = PTTState.HELD
        self._press_time = time.time()
        logger.info("🎤 PTT basıldı — dinleniyor...")

        if self._on_start:
            try:
                self._on_start()
            except Exception as exc:
                logger.warning("PTT on_start callback failed: %s", exc)

        return True

    def release(self) -> bool:
        """PTT key released — stop listening and process.

        Returns True if valid hold (>= min_hold_ms), False if too short.
        """
        if self._state != PTTState.HELD:
            return False

        hold_ms = 0.0
        if self._press_time:
            hold_ms = (time.time() - self._press_time) * 1000

        if hold_ms < self._min_hold_ms:
            logger.debug(
                "PTT too short: %.0fms < %dms — ignoring",
                hold_ms, self._min_hold_ms,
            )
            self._state = PTTState.IDLE
            self._press_time = None
            return False

        self._state = PTTState.PROCESSING
        self._press_count += 1
        self._total_hold_ms += hold_ms
        logger.info("🎤 PTT bırakıldı — işleniyor (%.0fms)", hold_ms)

        if self._on_stop:
            try:
                self._on_stop()
            except Exception as exc:
                logger.warning("PTT on_stop callback failed: %s", exc)

        self._state = PTTState.IDLE
        self._press_time = None
        return True

    def cancel(self) -> None:
        """Cancel current PTT without processing."""
        if self._state == PTTState.HELD:
            logger.debug("PTT cancelled")
        self._state = PTTState.IDLE
        self._press_time = None

    def reset(self) -> None:
        """Reset all stats."""
        self._state = PTTState.IDLE
        self._press_time = None
        self._press_count = 0
        self._total_hold_ms = 0.0
