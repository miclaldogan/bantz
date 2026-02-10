from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PiperTTSConfig:
    piper_bin: str = "piper"
    model_path: str = ""


class PiperTTS:
    def __init__(self, cfg: PiperTTSConfig):
        self.cfg = cfg

    def speak(self, text: str) -> None:
        """Synthesize *text* with Piper TTS and play through speakers.

        Issue #693: Temporary WAV files are now cleaned up in a ``finally``
        block, and the player subprocess is awaited so the file is not
        deleted while still being read.
        """
        text = (text or "").strip()
        if not text:
            return
        if not self.cfg.model_path:
            raise RuntimeError("Piper model_path boş. Bir .onnx voice modeli ver.")

        piper_path = shutil.which(self.cfg.piper_bin) or self.cfg.piper_bin

        with tempfile.NamedTemporaryFile(prefix="bantz_tts_", suffix=".wav", delete=False) as f:
            out_wav = f.name

        try:
            # piper reads stdin text; writes wav to -f
            p = subprocess.Popen(
                [piper_path, "-m", self.cfg.model_path, "-f", out_wav],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            p.communicate(text)

            player = shutil.which("paplay") or shutil.which("aplay")
            if not player:
                raise RuntimeError("Ses çalıcı bulunamadı (paplay/aplay).")

            # Play and WAIT for completion before cleanup
            player_proc = subprocess.Popen(
                [player, out_wav],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            player_proc.wait()
        finally:
            # Always clean up the temp WAV file
            try:
                os.unlink(out_wav)
            except OSError:
                logger.debug("Failed to remove temp WAV: %s", out_wav)
