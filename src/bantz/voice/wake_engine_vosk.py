"""Vosk wake-word engine backend (Issue #291).

Offline wake-word detection using Vosk speech recognition.
Transcribes audio continuously and matches against configured wake phrases.

Requires:
    pip install vosk sounddevice

Config:
    BANTZ_WAKE_WORDS=hey bantz,bantz,jarvis
    BANTZ_WAKE_SENSITIVITY=0.5
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["VoskWakeEngine"]


class VoskWakeEngine:
    """Vosk-based wake-word engine.

    Runs Vosk partial recognition in a background thread and fires
    callback when any configured wake phrase is detected.
    """

    def __init__(self, config=None) -> None:
        from bantz.voice.wake_engine_base import WakeEngineConfig

        self.config = config or WakeEngineConfig()
        self._callback: Optional[Callable[[str], None]] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._model = None
        self._cpu_usage = 0.0
        self._last_detection = 0.0
        self._cooldown = 2.0  # seconds between detections

    def on_wake_word(self, callback: Callable[[str], None]) -> None:
        """Register callback for wake word detection."""
        self._callback = callback

    def start(self) -> None:
        """Start the Vosk recognition loop in a background thread."""
        if self._running:
            return

        try:
            import vosk
            import sounddevice  # noqa: F401 — verify availability
        except ImportError as exc:
            raise ImportError(
                "vosk and sounddevice are required for VoskWakeEngine. "
                "Install with: pip install vosk sounddevice"
            ) from exc

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="vosk-wake",
        )
        self._thread.start()
        logger.info("[wake][vosk] started — phrases: %s", self.config.wake_words)

    def stop(self) -> None:
        """Stop the recognition loop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        logger.info("[wake][vosk] stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cpu_usage_percent(self) -> float:
        return self._cpu_usage

    def _listen_loop(self) -> None:
        """Background recognition loop."""
        try:
            import vosk
            import sounddevice as sd

            vosk.SetLogLevel(-1)  # suppress vosk internal logs

            if self._model is None:
                self._model = vosk.Model(lang="tr")

            sample_rate = 16000
            rec = vosk.KaldiRecognizer(self._model, sample_rate)
            rec.SetWords(True)

            with sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=4000,
                dtype="int16",
                channels=1,
                device=self._resolve_device(),
            ) as stream:
                logger.debug("[wake][vosk] audio stream open")
                while self._running:
                    data = stream.read(4000)[0]
                    t0 = time.monotonic()

                    if rec.AcceptWaveform(bytes(data)):
                        result = json.loads(rec.Result())
                        text = result.get("text", "").lower().strip()
                        self._check_wake(text)
                    else:
                        partial = json.loads(rec.PartialResult())
                        text = partial.get("partial", "").lower().strip()
                        self._check_wake(text)

                    elapsed = time.monotonic() - t0
                    # estimate CPU % for 250ms of audio
                    self._cpu_usage = min(100.0, (elapsed / 0.25) * 100.0)

        except Exception:
            logger.exception("[wake][vosk] listen loop error")
            self._running = False

    def _check_wake(self, text: str) -> None:
        """Check transcribed text against wake phrases."""
        if not text:
            return

        now = time.monotonic()
        if now - self._last_detection < self._cooldown:
            return

        for phrase in self.config.wake_words:
            if phrase.lower() in text:
                logger.info("[wake][vosk] detected: '%s' in '%s'", phrase, text)
                self._last_detection = now
                self._fire_callback(phrase)
                return

    def _fire_callback(self, phrase: str) -> None:
        """Invoke callback safely."""
        if self._callback is None:
            return
        try:
            self._callback(phrase)
        except Exception:
            logger.exception("[wake][vosk] callback error for '%s'", phrase)

    def _resolve_device(self):
        """Resolve audio device from config."""
        dev = self.config.audio_input_device
        if dev == "default" or not dev:
            return None  # sounddevice default

        # Try numeric id
        try:
            return int(dev)
        except ValueError:
            pass

        # Try name match
        try:
            import sounddevice as sd
            for info in sd.query_devices():
                if dev.lower() in info["name"].lower() and info["max_input_channels"] > 0:
                    return info["index"]
        except Exception:
            pass

        logger.warning("[wake][vosk] device '%s' not found — using default", dev)
        return None
