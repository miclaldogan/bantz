"""Wake engine abstract base (Issue #291).

Pluggable wake-word detection architecture.
Backends: vosk, porcupine, whisper-tiny, none (PTT fallback).

Config env vars::

    BANTZ_WAKE_WORDS=hey bantz,bantz,jarvis
    BANTZ_AUDIO_INPUT_DEVICE=default
    BANTZ_WAKE_ENGINE=vosk
    BANTZ_WAKE_SENSITIVITY=0.5
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "WakeEngineBase",
    "WakeEngineConfig",
    "create_wake_engine",
]


@dataclass
class WakeEngineConfig:
    """Wake engine configuration.

    Attributes
    ----------
    wake_words:
        Comma-separated wake phrases.
    audio_input_device:
        PyAudio device name/id (``"default"`` for system default).
    engine:
        Backend name: ``vosk``, ``porcupine``, ``whisper-tiny``, ``none``.
    sensitivity:
        Detection threshold 0.0-1.0.
    """

    wake_words: List[str] = field(default_factory=lambda: ["hey bantz", "bantz", "jarvis"])
    audio_input_device: str = "default"
    engine: str = "vosk"
    sensitivity: float = 0.5

    @classmethod
    def from_env(cls) -> "WakeEngineConfig":
        """Load config from environment variables."""
        raw_words = os.getenv("BANTZ_WAKE_WORDS", "hey bantz,bantz,jarvis")
        words = [w.strip() for w in raw_words.split(",") if w.strip()]

        device = os.getenv("BANTZ_AUDIO_INPUT_DEVICE", "default").strip()
        engine = os.getenv("BANTZ_WAKE_ENGINE", "vosk").strip().lower()

        try:
            sensitivity = float(os.getenv("BANTZ_WAKE_SENSITIVITY", "0.5"))
            sensitivity = max(0.0, min(1.0, sensitivity))
        except ValueError:
            sensitivity = 0.5

        return cls(
            wake_words=words,
            audio_input_device=device,
            engine=engine,
            sensitivity=sensitivity,
        )


class WakeEngineBase(ABC):
    """Abstract base class for wake-word engines.

    All engines must implement start/stop, callback registration,
    and CPU usage reporting.
    """

    def __init__(self, config: Optional[WakeEngineConfig] = None) -> None:
        self.config = config or WakeEngineConfig()
        self._callback: Optional[Callable[[str], None]] = None
        self._running = False

    @abstractmethod
    def start(self) -> None:
        """Start listening for wake words."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop listening and release resources."""
        ...

    def on_wake_word(self, callback: Callable[[str], None]) -> None:
        """Register callback for wake word detection.

        Parameters
        ----------
        callback:
            Called with the detected wake phrase string.
        """
        self._callback = callback

    @property
    @abstractmethod
    def cpu_usage_percent(self) -> float:
        """Current CPU usage percentage (0.0-100.0)."""
        ...

    @property
    def is_running(self) -> bool:
        """Whether the engine is currently listening."""
        return self._running

    def _fire_callback(self, phrase: str) -> None:
        """Invoke the registered callback safely."""
        if self._callback is None:
            logger.warning("[wake] wake word detected (%s) but no callback set", phrase)
            return
        try:
            self._callback(phrase)
        except Exception:
            logger.exception("[wake] callback error for phrase '%s'", phrase)


class PTTFallbackEngine(WakeEngineBase):
    """Push-to-talk fallback when no wake engine is available.

    Does not listen for audio — activation is manual (keyboard shortcut).
    """

    def start(self) -> None:
        self._running = True
        logger.info("[wake][ptt] push-to-talk mode active — no audio wake engine")

    def stop(self) -> None:
        self._running = False
        logger.info("[wake][ptt] stopped")

    @property
    def cpu_usage_percent(self) -> float:
        return 0.0

    def simulate_wake(self, phrase: str = "manual") -> None:
        """Simulate a wake event (e.g. from a hotkey)."""
        logger.debug("[wake][ptt] manual activation")
        self._fire_callback(phrase)


def create_wake_engine(config: Optional[WakeEngineConfig] = None) -> WakeEngineBase:
    """Factory: create the appropriate wake engine based on config.

    Returns PTTFallbackEngine when engine is ``"none"`` or the
    requested backend cannot be loaded.
    """
    config = config or WakeEngineConfig.from_env()
    engine_name = config.engine.lower()

    if engine_name == "none":
        logger.info("[wake] engine=none → push-to-talk fallback")
        return PTTFallbackEngine(config)

    if engine_name == "vosk":
        try:
            from bantz.voice.wake_engine_vosk import VoskWakeEngine
            return VoskWakeEngine(config)
        except ImportError:
            logger.warning("[wake] vosk not installed — falling back to PTT")
            return PTTFallbackEngine(config)

    if engine_name == "porcupine":
        logger.warning("[wake] porcupine backend not yet implemented — PTT fallback")
        return PTTFallbackEngine(config)

    if engine_name == "whisper-tiny":
        logger.warning("[wake] whisper-tiny backend not yet implemented — PTT fallback")
        return PTTFallbackEngine(config)

    logger.warning("[wake] unknown engine '%s' — PTT fallback", engine_name)
    return PTTFallbackEngine(config)
