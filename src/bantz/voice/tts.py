from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class PiperTTSConfig:
    piper_bin: str = "piper"
    model_path: str = ""


class PiperTTS:
    def __init__(self, cfg: PiperTTSConfig):
        self.cfg = cfg

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not self.cfg.model_path:
            raise RuntimeError("Piper model_path boş. Bir .onnx voice modeli ver.")

        piper_path = shutil.which(self.cfg.piper_bin) or self.cfg.piper_bin

        with tempfile.NamedTemporaryFile(prefix="bantz_tts_", suffix=".wav", delete=False) as f:
            out_wav = f.name

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

        subprocess.Popen(
            [player, out_wav],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
