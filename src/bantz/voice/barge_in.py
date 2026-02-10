"""Barge-in controller — user speaks while TTS is playing (Issue #297).

When TTS is active and the user speaks (barge-in), the controller:
1. Detects speech via audio energy threshold.
2. Stops TTS playback immediately.
3. Signals the voice FSM to start listening.

The controller monitors the microphone in a background thread while
TTS is playing, using simple energy-based speech detection.

Usage::

    controller = BargeInController(tts=my_tts)
    controller.start_monitoring()
    # ... TTS plays ...
    # User speaks → TTS stops automatically
    controller.stop_monitoring()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["BargeInController", "BargeInConfig", "BargeInEvent"]


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


@dataclass
class BargeInConfig:
    """Barge-in detection parameters.

    Attributes
    ----------
    energy_threshold:
        RMS audio energy threshold for speech detection (0.0–1.0).
        Typical: 0.02 for quiet room, 0.05 for noisy.
    min_duration_ms:
        Minimum speech duration to trigger barge-in (avoids
        false triggers from brief noise).
    sample_rate:
        Mic sample rate.
    enabled:
        Master toggle.
    """

    energy_threshold: float = 0.02
    min_duration_ms: int = 200
    sample_rate: int = 16000
    enabled: bool = True


@dataclass
class BargeInEvent:
    """Data about a detected barge-in."""

    timestamp: float = 0.0
    energy: float = 0.0
    duration_ms: float = 0.0


# ─────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────


class BargeInController:
    """Monitor mic audio during TTS playback for user speech.

    Parameters
    ----------
    tts:
        A :class:`~bantz.voice.tts_base.TTSBase` instance.
        ``tts.stop()`` is called when barge-in is detected.
    config:
        Detection parameters.
    on_barge_in:
        Optional callback invoked when barge-in is detected.
    """

    def __init__(
        self,
        tts: Any = None,
        config: Optional[BargeInConfig] = None,
        on_barge_in: Optional[Callable[[BargeInEvent], None]] = None,
    ) -> None:
        self._tts = tts
        self._config = config or BargeInConfig()
        self._on_barge_in = on_barge_in
        self._active = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._barge_in_count = 0
        self._last_event: Optional[BargeInEvent] = None

    @property
    def config(self) -> BargeInConfig:
        return self._config

    @property
    def monitoring(self) -> bool:
        return self._active.is_set()

    @property
    def barge_in_count(self) -> int:
        return self._barge_in_count

    @property
    def last_event(self) -> Optional[BargeInEvent]:
        return self._last_event

    def start_monitoring(self) -> bool:
        """Start monitoring microphone for barge-in.

        Returns ``True`` if monitoring started, ``False`` if disabled
        or TTS doesn't support barge-in.
        """
        if not self._config.enabled:
            logger.debug("Barge-in disabled")
            return False

        if self._tts and hasattr(self._tts, "supports_barge_in"):
            if not self._tts.supports_barge_in:
                logger.debug("TTS backend does not support barge-in")
                return False

        if self._active.is_set():
            logger.debug("Already monitoring for barge-in")
            return True

        self._stop_event.clear()
        self._active.set()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="barge-in-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.debug("Barge-in monitoring started (threshold=%.3f)", self._config.energy_threshold)
        return True

    def stop_monitoring(self) -> None:
        """Stop monitoring."""
        self._active.clear()
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        logger.debug("Barge-in monitoring stopped")

    def _monitor_loop(self) -> None:
        """Background thread: read mic audio and check energy."""
        try:
            import numpy as np

            speech_start: Optional[float] = None

            # Try to open mic stream
            try:
                import sounddevice as sd  # type: ignore[import-untyped]

                chunk_size = int(self._config.sample_rate * 0.05)  # 50ms chunks

                with sd.InputStream(
                    samplerate=self._config.sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=chunk_size,
                ) as stream:
                    while not self._stop_event.is_set():
                        data, overflowed = stream.read(chunk_size)
                        if overflowed:
                            continue

                        rms = float(np.sqrt(np.mean(data ** 2)))

                        if rms >= self._config.energy_threshold:
                            if speech_start is None:
                                speech_start = time.time()
                            duration_ms = (time.time() - speech_start) * 1000

                            if duration_ms >= self._config.min_duration_ms:
                                self._on_speech_detected(rms, duration_ms)
                                return
                        else:
                            speech_start = None

            except ImportError:
                logger.debug("sounddevice not available — barge-in monitoring disabled")
                return

        except Exception as exc:
            logger.warning("Barge-in monitor error: %s", exc)
        finally:
            self._active.clear()

    def _on_speech_detected(self, energy: float, duration_ms: float) -> None:
        """Handle detected user speech during TTS playback."""
        event = BargeInEvent(
            timestamp=time.time(),
            energy=energy,
            duration_ms=duration_ms,
        )
        self._last_event = event
        self._barge_in_count += 1
        self._active.clear()

        logger.info(
            "🎤 Barge-in detected! energy=%.4f, duration=%.0fms (count=%d)",
            energy, duration_ms, self._barge_in_count,
        )

        # Stop TTS
        if self._tts:
            try:
                self._tts.stop()
                logger.debug("TTS stopped due to barge-in")
            except Exception as exc:
                logger.warning("TTS stop failed during barge-in: %s", exc)

        # Notify callback
        if self._on_barge_in:
            try:
                self._on_barge_in(event)
            except Exception as exc:
                logger.warning("Barge-in callback failed: %s", exc)

    def check_energy(self, audio_data: Any) -> bool:
        """Check if an audio buffer exceeds the energy threshold.

        This is a synchronous alternative to the background monitoring —
        useful for integration with existing audio pipelines that already
        have mic data available.

        Parameters
        ----------
        audio_data:
            NumPy float32 array of audio samples.

        Returns
        -------
        bool
            True if energy exceeds threshold.
        """
        try:
            import numpy as np

            rms = float(np.sqrt(np.mean(audio_data ** 2)))
            return rms >= self._config.energy_threshold
        except Exception:
            return False
