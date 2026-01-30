from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ASRConfig:
    whisper_model: str = "base"
    # Default to Turkish since most commands will be in Turkish
    # English words like "instagram", "youtube" still work fine with TR forced
    language: Optional[str] = "tr"
    device: str = "cpu"
    compute_type: str = "int8"
    sample_rate: int = 16000
    task: str = "transcribe"
    beam_size: int = 5
    vad_filter: bool = True
    condition_on_previous_text: bool = False
    temperature: float = 0.0
    cache_dir: str = ""
    allow_download: bool = False


class ASR:
    def __init__(self, cfg: ASRConfig):
        self.cfg = cfg
        try:
            from faster_whisper import WhisperModel
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "faster-whisper yüklü değil. Kurulum: pip install 'bantz[voice]'"
            ) from e

        cache_dir = cfg.cache_dir or os.environ.get("BANTZ_ASR_CACHE_DIR", "").strip()
        download_root = cache_dir or None
        local_only = not bool(cfg.allow_download)

        # If downloads are allowed but we can't reach HuggingFace quickly, fail fast.
        # (Otherwise it can look like the app is frozen.)
        if not local_only and isinstance(cfg.whisper_model, str) and not os.path.exists(cfg.whisper_model):
            try:
                sock = socket.create_connection(("huggingface.co", 443), timeout=3.0)
            except OSError:
                raise RuntimeError(
                    "ASR modeli indirilemiyor: HuggingFace'e (443) erişemiyorum. "
                    "İnternet/engelleme/VPN kontrol et ya da önce warmup çalıştır."
                )
            else:
                try:
                    sock.close()
                except Exception:
                    pass
        try:
            self._model = WhisperModel(
                cfg.whisper_model,
                device=cfg.device,
                compute_type=cfg.compute_type,
                download_root=download_root,
                local_files_only=local_only,
            )
        except Exception as e:
            if local_only:
                hint = (
                    "Whisper model cache'te bulunamadı ve indirme kapalı. "
                    "Önce warmup çalıştır: bantz --voice-warmup --whisper-model base --asr-allow-download\n"
                    "Ya da tek seferlik indirmeye izin ver: --asr-allow-download"
                )
            else:
                hint = (
                    "Whisper model indirilemedi. İnternet/HuggingFace erişimini kontrol et. "
                    "İstersen önce warmup çalıştırıp sonra voice'a geçebilirsin."
                )
            raise RuntimeError(f"ASR modeli yüklenemedi: {e}\n{hint}") from e

    def transcribe(self, audio_float32) -> tuple[str, dict[str, Any]]:
        # audio_float32: 1D numpy float32 array at cfg.sample_rate
        import numpy as np
        
        # Check audio level - if too quiet, return empty
        max_amplitude = np.max(np.abs(audio_float32))
        if max_amplitude < 0.005:  # Minimum threshold
            return "", {"language": self.cfg.language, "no_speech": True, "max_amplitude": float(max_amplitude)}
        
        # Normalize audio if needed (but not too aggressively to avoid noise amplification)
        if max_amplitude < 0.1 and max_amplitude > 0.01:
            # Gentle normalization
            audio_float32 = audio_float32 * (0.3 / max_amplitude)
            audio_float32 = np.clip(audio_float32, -1.0, 1.0)

        def once(lang: Optional[str]) -> tuple[str, dict[str, Any]]:
            segments_iter, info = self._model.transcribe(
                audio_float32,
                language=lang,
                task=self.cfg.task,
                beam_size=self.cfg.beam_size,
                vad_filter=self.cfg.vad_filter,
                condition_on_previous_text=self.cfg.condition_on_previous_text,
                temperature=self.cfg.temperature,
            )
            segments = list(segments_iter)
            text = " ".join((getattr(s, "text", "") or "").strip() for s in segments).strip()

            meta: dict[str, Any] = {
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
            }

            # Confidence proxies (best-effort; varies by faster-whisper version)
            avg_logprob = getattr(info, "avg_logprob", None)
            if avg_logprob is None:
                vals = [getattr(s, "avg_logprob", None) for s in segments]
                vals = [v for v in vals if isinstance(v, (int, float))]
                if vals:
                    avg_logprob = float(sum(vals) / len(vals))
            meta["avg_logprob"] = avg_logprob

            no_speech_prob = getattr(info, "no_speech_prob", None)
            if no_speech_prob is None:
                vals2 = [getattr(s, "no_speech_prob", None) for s in segments]
                vals2 = [v for v in vals2 if isinstance(v, (int, float))]
                if vals2:
                    no_speech_prob = float(sum(vals2) / len(vals2))
            meta["no_speech_prob"] = no_speech_prob

            if lang is not None:
                meta["forced_language"] = lang
            return text, meta

        text, meta = once(self.cfg.language)

        # If auto-detect is used and it looks wrong, retry forcing TR/EN and pick best.
        # We only allow TR and EN languages for this assistant.
        if self.cfg.language is None:
            detected = (meta.get("language") or "").lower()
            lp = meta.get("avg_logprob")
            # If detected language is not TR/EN, force rerank
            looks_off = detected and detected not in {"tr", "en"}
            low_conf = isinstance(lp, (int, float)) and lp < -0.85
            if looks_off or low_conf:
                candidates: list[tuple[str, dict[str, Any]]] = []
                # Don't include original if it's not TR/EN
                if detected in {"tr", "en"}:
                    candidates.append((text, meta))
                for forced in ("tr", "en"):
                    try:
                        candidates.append(once(forced))
                    except Exception:
                        pass

                def score(item: tuple[str, dict[str, Any]]) -> tuple[float, int]:
                    t, m = item
                    lp2 = m.get("avg_logprob")
                    # Higher avg_logprob is better (closer to 0)
                    lp_val = float(lp2) if isinstance(lp2, (int, float)) else -999.0
                    return (lp_val, len(t.strip()))

                if candidates:
                    best = max(candidates, key=score)
                    text, meta = best
                    meta["reranked"] = True

        # Hallucination prevention - reject if no_speech_prob is too high
        no_speech = meta.get("no_speech_prob")
        if isinstance(no_speech, (int, float)) and no_speech > 0.6:
            return "", {"language": self.cfg.language, "no_speech": True, "no_speech_prob": no_speech}
        
        # Detect repetitive hallucinations (e.g., "beğenmeyi beğenmeyi beğenmeyi...")
        words = text.split()
        if len(words) > 3:
            unique_words = set(words)
            if len(unique_words) <= 2 and len(words) > 5:
                # Highly repetitive - likely hallucination
                return "", {"language": self.cfg.language, "hallucination_detected": True}

        return text, meta
