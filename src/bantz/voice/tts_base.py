"""TTS base abstraction with barge-in support (Issue #297).

Extends the existing ``AdvancedTTS`` (Issue #10) with a simpler,
pipeline-friendly interface that any TTS backend can implement:

- :class:`TTSBase` — minimal ABC for speak / stop / is_speaking
- :class:`TTSSettings` — unified settings from env vars
- Existing backends (:class:`PiperTTS`, :class:`CoquiTTS`) are
  wrapped via :class:`PiperTTSAdapter` / :class:`CoquiTTSAdapter`.

Usage::

    settings = TTSSettings.from_env()
    tts = create_tts(settings)
    tts.speak("Merhaba efendim")
    if tts.is_speaking():
        tts.stop()  # barge-in
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TTSBase",
    "TTSSettings",
    "PiperTTSAdapter",
    "PrintTTSFallback",
    "create_tts",
]


# ─────────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────────


@dataclass
class TTSSettings:
    """Unified TTS settings — configurable via env vars.

    Env vars::

        BANTZ_TTS_BACKEND=piper          # piper | edge | google | print
        BANTZ_TTS_VOICE=tr-TR-EmelNeural # voice name or piper model path
        BANTZ_TTS_RATE=1.0               # 0.5–2.0
        BANTZ_TTS_PITCH=1.0              # 0.5–2.0
        BANTZ_TTS_VOLUME=1.0             # 0.0–1.0
    """

    backend: str = "piper"
    voice: str = ""
    rate: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0

    @classmethod
    def from_env(cls) -> "TTSSettings":
        """Load settings from environment variables."""
        return cls(
            backend=os.getenv("BANTZ_TTS_BACKEND", "piper").strip().lower(),
            voice=os.getenv("BANTZ_TTS_VOICE", "").strip(),
            rate=_clamp(float(os.getenv("BANTZ_TTS_RATE", "1.0")), 0.5, 2.0),
            pitch=_clamp(float(os.getenv("BANTZ_TTS_PITCH", "1.0")), 0.5, 2.0),
            volume=_clamp(float(os.getenv("BANTZ_TTS_VOLUME", "1.0")), 0.0, 1.0),
        )


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ─────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────


class TTSBase(ABC):
    """Minimal TTS interface with barge-in support.

    Every TTS backend (Piper, Edge, Google, …) must implement:
    - :meth:`speak` — block until speech finishes (or is stopped)
    - :meth:`stop` — immediately interrupt playback
    - :meth:`is_speaking` — True if audio is playing
    - :attr:`supports_barge_in` — True if stop() is effective
    """

    @abstractmethod
    def speak(self, text: str) -> None:
        """Synthesize and play *text*.

        Blocks until playback completes or :meth:`stop` is called.
        """

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop current playback (barge-in)."""

    @abstractmethod
    def is_speaking(self) -> bool:
        """Return True if audio is currently playing."""

    @property
    @abstractmethod
    def supports_barge_in(self) -> bool:
        """Whether this backend supports mid-speech interruption."""

    @property
    def backend_name(self) -> str:
        return self.__class__.__name__


# ─────────────────────────────────────────────────────────────────
# Print fallback (headless / test)
# ─────────────────────────────────────────────────────────────────


class PrintTTSFallback(TTSBase):
    """Fallback TTS that prints text to stdout.

    Used when no real TTS backend is available (headless, CI, test).
    """

    def __init__(self) -> None:
        self._speaking = False

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._speaking = True
            logger.info("[TTS/print] %s", text)
            print(f"🔊 {text}")
            self._speaking = False

    def stop(self) -> None:
        self._speaking = False

    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def supports_barge_in(self) -> bool:
        return False


# ─────────────────────────────────────────────────────────────────
# Piper adapter
# ─────────────────────────────────────────────────────────────────


class PiperTTSAdapter(TTSBase):
    """Wrap the existing :class:`bantz.voice.tts.PiperTTS` as a TTSBase.

    Adds stop/is_speaking tracking and subprocess management for
    barge-in support.
    """

    def __init__(self, model_path: str = "", piper_bin: str = "piper") -> None:
        self._model_path = model_path
        self._piper_bin = piper_bin
        self._speaking = False
        self._play_process: Any = None  # subprocess.Popen or None

    def speak(self, text: str) -> None:
        import shutil
        import subprocess
        import tempfile

        text = (text or "").strip()
        if not text:
            return
        if not self._model_path:
            logger.warning("PiperTTS: model_path empty — falling back to print")
            print(f"🔊 {text}")
            return

        piper_path = shutil.which(self._piper_bin) or self._piper_bin
        self._speaking = True

        try:
            with tempfile.NamedTemporaryFile(prefix="bantz_tts_", suffix=".wav", delete=False) as f:
                out_wav = f.name

            p = subprocess.Popen(
                [piper_path, "-m", self._model_path, "-f", out_wav],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            p.communicate(text)

            if not self._speaking:
                return  # stop() was called during synthesis

            player = shutil.which("paplay") or shutil.which("aplay")
            if player:
                self._play_process = subprocess.Popen(
                    [player, out_wav],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._play_process.wait()
                self._play_process = None
            else:
                logger.warning("Audio player not found (paplay/aplay)")

        except Exception as exc:
            logger.warning("PiperTTS speak failed: %s", exc)
        finally:
            self._speaking = False

    def stop(self) -> None:
        self._speaking = False
        if self._play_process and self._play_process.poll() is None:
            try:
                self._play_process.terminate()
                logger.debug("PiperTTS: playback terminated (barge-in)")
            except OSError:
                pass

    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def supports_barge_in(self) -> bool:
        return True  # Can terminate subprocess


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────


def create_tts(settings: Optional[TTSSettings] = None) -> TTSBase:
    """Create a TTS backend from settings.

    Falls back to :class:`PrintTTSFallback` if the requested
    backend cannot be loaded.
    """
    s = settings or TTSSettings.from_env()

    if s.backend == "print":
        return PrintTTSFallback()

    if s.backend == "piper":
        return PiperTTSAdapter(model_path=s.voice)

    if s.backend in ("edge", "google"):
        # Future: Edge/Google TTS adapters
        logger.warning(
            "TTS backend '%s' not yet supported — using print fallback", s.backend
        )
        return PrintTTSFallback()

    logger.warning("Unknown TTS backend: '%s' — print fallback", s.backend)
    return PrintTTSFallback()
