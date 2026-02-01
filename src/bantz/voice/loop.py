from __future__ import annotations

import re
import threading
import time
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class VoiceLoopConfig:
    session: str = "default"
    piper_model_path: str = ""
    vllm_url: str = "http://127.0.0.1:8001"
    vllm_model: str = "Qwen/Qwen2.5-3B-Instruct"
    whisper_model: str = "base"
    # Default to Turkish - English words like "instagram" still work fine
    language: Optional[str] = "tr"
    sample_rate: int = 16000
    enable_tts: bool = True
    enable_llm_fallback: bool = True
    force_enter_ptt: bool = False


class _Recorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = int(sample_rate)
        self._lock = threading.Lock()
        self._stream = None
        self._frames: List["object"] = []

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ModuleNotFoundError as e:
            raise RuntimeError("sounddevice yüklü değil. Kurulum: pip install 'bantz[voice]'") from e

        with self._lock:
            self._frames = []

            def cb(indata, frames, time_info, status):
                if status:
                    return
                with self._lock:
                    self._frames.append(indata.copy())

            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=cb,
            )
            self._stream.start()

    def stop(self):
        with self._lock:
            stream = self._stream
            self._stream = None

        if stream is not None:
            try:
                stream.stop()
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        try:
            import numpy as np
        except ModuleNotFoundError as e:
            raise RuntimeError("numpy yüklü değil. Kurulum: pip install 'bantz[voice]'") from e

        with self._lock:
            if not self._frames:
                return np.zeros((0,), dtype=np.float32)
            audio = np.concatenate(self._frames, axis=0).reshape(-1).astype(np.float32)
            self._frames = []
            return audio


def run_voice_loop(cfg: VoiceLoopConfig) -> int:
    """Push-to-talk loop.

    - SPACE basılı tut: kaydet
    - SPACE bırak: transcribe -> daemon'a gönder -> TTS konuş

    Eğer global key hook çalışmazsa (Wayland/X kısıtları), Enter tabanlı fallback var.
    """

    from bantz.server import is_server_running, send_to_server, ensure_server_running
    from bantz.llm import LLMMessage, create_client
    from bantz.voice.asr import ASR, ASRConfig
    from bantz.voice.tts import PiperTTS, PiperTTSConfig

    # Ensure session server is running (auto-start for voice mode)
    policy_path = os.environ.get("BANTZ_POLICY", "config/policy.json")
    log_path = os.environ.get("BANTZ_LOG", "artifacts/logs/bantz.log.jsonl")
    ok, started_here, msg = ensure_server_running(cfg.session, policy_path=policy_path, log_path=log_path)
    if not ok:
        print(f"❌ Session server başlatılamadı (session={cfg.session}): {msg}")
        return 1
    if started_here:
        from bantz.server import get_socket_path
        print(f"ℹ️ Session server otomatik başlatıldı (session={cfg.session}).")
        print(f"   Socket: {get_socket_path(cfg.session)}")
        print(f"   Kapatmak için: bantz --session {cfg.session} --stop")

    tts = None
    if cfg.enable_tts:
        if not cfg.piper_model_path:
            print("❌ Piper model path gerekli. Örn: --piper-model /path/to/tr.onnx  (veya geçici: --no-tts)")
            return 1
        tts = PiperTTS(PiperTTSConfig(model_path=cfg.piper_model_path))

    print("🎤 Voice (PTT): SPACE basılı tut → konuş → bırak.  Çıkış: Ctrl+C")
    if not cfg.enable_tts:
        print("   (TTS kapalı: --no-tts)")
    if not cfg.enable_llm_fallback:
        print("   (LLM fallback kapalı: --no-llm)")

    # Preflight: if LLM is enabled but vLLM isn't reachable, disable it once and continue.
    if cfg.enable_llm_fallback:
        try:
            probe = create_client(
                "vllm",
                base_url=cfg.vllm_url,
                model=cfg.vllm_model,
                timeout=2.0,
            )
            if not probe.is_available(timeout_seconds=1.5):
                raise RuntimeError("unreachable")
        except Exception:
            print("⚠️  vLLM çalışmıyor veya erişilemiyor; LLM rewrite/fallback devre dışı.")
            print(f"   URL: {cfg.vllm_url}")
            print("   Başlat: scripts/vllm/start_3b.sh  (veya docs/setup/vllm.md)")
            cfg.enable_llm_fallback = False

    # Lazily initialize heavy components so the loop feels responsive.
    asr: Optional[ASR] = None
    asr_fatal_error: Optional[str] = None

    def get_asr() -> ASR:
        nonlocal asr, asr_fatal_error
        if asr_fatal_error:
            raise RuntimeError(asr_fatal_error)

        if asr is None:
            cache_dir = os.environ.get("BANTZ_ASR_CACHE_DIR", "").strip()
            allow_download = os.environ.get("BANTZ_ASR_ALLOW_DOWNLOAD", "0").strip() in {"1", "true", "True"}
            try:
                asr = ASR(
                    ASRConfig(
                        whisper_model=cfg.whisper_model,
                        language=cfg.language,
                        sample_rate=cfg.sample_rate,
                        cache_dir=cache_dir,
                        allow_download=allow_download,
                    )
                )
            except Exception as e:
                msg = str(e)
                # If the model isn't cached and downloads are disabled, stop the loop and ask for warmup.
                if "Whisper model cache'te bulunamadı" in msg and "indirme kapalı" in msg:
                    asr_fatal_error = msg
                raise

        return asr

    llm = None
    history: List[LLMMessage] = []
    if cfg.enable_llm_fallback:
        history = [
            LLMMessage(
                "system",
                "Sen Bantz'sın. Türkçe konuş. Kısa, net ve yardımcı ol. "
                "Riskli eylem isteklerinde (sil/gönder/ödeme/kapat vb.) kullanıcıdan onay iste.",
            )
        ]

    recorder = _Recorder(sample_rate=cfg.sample_rate)
    recording = False

    # Autocorrect dictionary: alias -> canonical normalization.
    # Keep this list small and aligned with daemon NLU patterns.
    COMMAND_CANONICAL: dict[str, list[str]] = {
        # Confirmation / cancel
        "evet": ["evet", "yes", "tamam", "ok"],
        "hayır": ["hayır", "hayir", "no"],
        "iptal": ["iptal", "vazgeç", "vazgec", "cancel"],

        # App control
        "uygulamalar": [
            "uygulamalar", "pencereler", "açık pencereler", "windows", "show windows",
            # Common ASR mistakes
            "uyur ulan", "uyu kullanmalar", "uygu wa", "uygulamala", "uygulama",
            "uygulama lar", "uygula malar", "uygulamaları", "uygulamalarım",
        ],
        "discord aç": ["discord", "discord aç", "dis kord", "open discord", "diskort", "diskor"],
        "firefox aç": ["firefox", "firefox aç", "open firefox", "fayır foks", "fayırfoks"],
        "kapat": ["kapat", "close"],
        "gönder": ["gönder", "gonder", "enter bas", "yolla", "send", "submit"],
        "uygulamadan çık": ["uygulamadan çık", "uygulamadan cik", "normal moda dön", "normal moda don"],

        # Prefix commands (keep remainder)
        "yaz:": ["yaz:", "yaz", "type:", "type"],
        "hatırlat": ["hatırlat", "hatırlatma", "reminder", "remind"],

        # Events
        "son olaylar": ["son olaylar", "son olayları göster", "son olaylari goster", "events", "eventler"],

        # Browser agent
        "instagram aç": [
            "instagram", "instagram aç", "instegram", "instgram", "insta", "open instagram",
            "instagram much", "instagram aç", "instagramı aç",
        ],
        "youtube aç": [
            "youtube aç", "youtube'u aç", "you tube aç", "yutup aç",
            "youtube edge", "youtube", "yutup",
        ],
        "sayfayı tara": [
            "sayfayı tara",
            "sayfayi tara",
            "yeniden tara",
            "tekrar tara",
            "linkleri göster",
            "bu sayfada ne var",
            "scan page",
            "tarama yap",
            "tara",
            # Common ASR mistakes
            "sci-fi tarot", "scifi tarot", "sayfayı tarar", "sayfayi tarar",
            "sayfa tara", "sayfa tarar", "sayfada tara",
            "saif-e-tara", "saifah yatara", "sigh for you tara",
            "ta-da-da", "tadada", "sayfayı tarar",
            "sayfayı tırağ", "sayfayi tirag", "sayfayı tırar",
        ],
        "geri dön": ["geri dön", "geri don", "back", "geri gel", "geri git"],
        "aşağı kaydır": ["aşağı kaydır", "asagi kaydir", "scroll down", "aşağı kay"],
        "yukarı kaydır": ["yukarı kaydır", "yukari kaydir", "scroll up", "yukarı kay"],
        # Removed "1'e tıkla" - too generic, causes false matches like "kaydola tıkla" -> "1'e tıkla"
        "bekle 3 saniye": ["bekle 3 saniye", "3 saniye bekle", "wait 3"],
    }

    PHRASE_TO_CANONICAL: dict[str, str] = {}
    COMMAND_PHRASES: list[str] = []
    for canonical, aliases in COMMAND_CANONICAL.items():
        for phrase in [canonical, *aliases]:
            p = (phrase or "").strip()
            if not p:
                continue
            if p not in PHRASE_TO_CANONICAL:
                PHRASE_TO_CANONICAL[p] = canonical
                COMMAND_PHRASES.append(p)

    def _fmt_meta(meta: dict) -> str:
        lang = meta.get("language")
        lp = meta.get("avg_logprob")
        prob = meta.get("language_probability")
        parts = []
        if lang is not None:
            parts.append(f"lang={lang}")
        if isinstance(prob, (int, float)):
            parts.append(f"lang_p={prob:.2f}")
        if isinstance(lp, (int, float)):
            parts.append(f"avg_logprob={lp:.2f}")
        nsp = meta.get("no_speech_prob")
        if isinstance(nsp, (int, float)):
            parts.append(f"no_speech={nsp:.2f}")
        return ("  (" + ", ".join(parts) + ")") if parts else ""

    def _should_correct(meta: dict, text: str) -> bool:
        t = (text or "").strip()
        if len(t) < 4:
            return True
        lp = meta.get("avg_logprob")
        if isinstance(lp, (int, float)) and lp < -0.85:
            return True
        nsp = meta.get("no_speech_prob")
        if isinstance(nsp, (int, float)) and nsp > 0.6:
            return True
        return False

    def _suggest_command(text: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
        try:
            from rapidfuzz import process, fuzz
        except ModuleNotFoundError:
            return None, None, None

        hit = process.extractOne(text, COMMAND_PHRASES, scorer=fuzz.WRatio)
        if not hit:
            return None, None, None

        match, score, _idx = hit
        match_s = str(match)
        canonical = PHRASE_TO_CANONICAL.get(match_s, match_s)
        return canonical, int(score), match_s

    def _apply_canonicalization(text: str, *, canonical: str, matched_phrase: Optional[str]) -> str:
        # For prefix commands (ending with ':' or special keywords), keep the remainder.
        prefix_keywords = {"hatırlat", "hatırlatma", "reminder", "remind"}
        is_prefix = canonical.endswith(":") or canonical.lower() in prefix_keywords
        
        if is_prefix:
            base = (matched_phrase or canonical).rstrip(":").strip()
            if base:
                m = re.match(r"^\s*" + re.escape(base) + r"\s*:?\s*,?\s*(.*)$", text, flags=re.IGNORECASE)
                if m:
                    rest = (m.group(1) or "").strip()
                    if rest:
                        # For hatırlat, don't add ':', just space
                        if canonical.lower() in prefix_keywords:
                            return (canonical + " " + rest).strip()
                        return (canonical + " " + rest).strip()
                    return canonical
        return canonical

    def _asr_bucket(meta: dict, text: str) -> str:
        """Return one of: high | med | low"""
        t = (text or "").strip()
        if len(t) < 2:
            return "low"

        nsp = meta.get("no_speech_prob")
        if isinstance(nsp, (int, float)) and nsp > 0.6:
            return "low"

        lp = meta.get("avg_logprob")
        if isinstance(lp, (int, float)):
            if lp > -0.6:
                return "high"
            if lp < -1.0:
                return "low"
            return "med"

        return "med"

    # LLM rewriter instance (lazy init)
    llm_rewriter = None
    enable_llm_rewrite = cfg.enable_llm_fallback and os.environ.get("BANTZ_LLM_REWRITE", "1") != "0"

    def _get_llm_rewriter():
        nonlocal llm_rewriter
        if llm_rewriter is None and enable_llm_rewrite:
            try:
                from bantz.llm.rewriter import CommandRewriter
                llm_rewriter = CommandRewriter(
                    model=cfg.vllm_model,
                    base_url=cfg.vllm_url,
                    enabled=True,
                )
            except Exception as e:
                print(f"⚠️  LLM rewriter init hatası: {e}")
                llm_rewriter = False  # Mark as unavailable
        return llm_rewriter if llm_rewriter else None

    def _autocorrect(text: str, meta: dict) -> tuple[str, dict]:
        """Silent autocorrect.

        Returns (normalized_text_or_empty, info)
        - empty string means: ask user to re-record
        """
        bucket = _asr_bucket(meta, text)
        suggestion, score, matched_phrase = _suggest_command(text)
        match_score = int(score) if isinstance(score, int) else None

        # LOW confidence => re-record (no questions)
        if bucket == "low":
            return "", {"mode": "re_record", "bucket": bucket, "match": suggestion, "match_score": match_score}

        # If we have a strong match, normalize into command space.
        if suggestion and match_score is not None:
            normalized = _apply_canonicalization(text, canonical=suggestion, matched_phrase=matched_phrase)
            if match_score >= 92:
                return normalized, {"mode": "auto_run", "bucket": bucket, "match": suggestion, "match_score": match_score}
            if match_score >= 88 and bucket in {"high", "med"}:
                return normalized, {"mode": "auto_fix", "bucket": bucket, "match": suggestion, "match_score": match_score}

        # MED bucket with no strong match -> try LLM rewrite
        if bucket == "med" and enable_llm_rewrite:
            rewriter = _get_llm_rewriter()
            if rewriter:
                try:
                    result = rewriter.rewrite(text)
                    if result.changed:
                        print(f"  [LLM] '{text}' → '{result.rewritten}' ({result.latency_ms:.0f}ms)")
                        return result.rewritten, {
                            "mode": "llm_rewrite", 
                            "bucket": bucket, 
                            "original": text,
                            "latency_ms": result.latency_ms,
                        }
                except Exception as e:
                    print(f"  [LLM] Rewrite hatası: {e}")

        # Otherwise keep original text (daemon may still handle it or return unknown).
        return text, {"mode": "pass_through", "bucket": bucket, "match": suggestion, "match_score": match_score}

    def handle_text(text: str, *, low_confidence: bool = False) -> None:
        nonlocal history
        # Strip whitespace and trailing punctuation from ASR output
        text = (text or "").strip().rstrip(".,!?;:")
        if not text:
            return

        # 1) Core/daemon (router+policy+context)
        try:
            resp = send_to_server(text, cfg.session)
        except Exception as e:
            resp = {"ok": False, "text": f"Daemon hata: {e}"}

        reply = (resp.get("text") or "").strip()
        intent = (resp.get("intent") or "").strip()
        ok = bool(resp.get("ok"))

        # Voice UX: unknown => re-record (no debating)
        if intent == "unknown":
            print("🤖 Anlayamadım. Tekrar söyler misin?")
            return

        # If ASR is shaky and policy refused, prefer a retry prompt over repeated denial spam.
        if (not ok) and low_confidence and reply.startswith("Bu isteği güvenlik nedeniyle"):
            print("🤖 Seni yanlış duymuş olabilirim. Tekrar söyler misin?")
            return

        # 2) Eğer daemon cevap veremediyse LLM fallback
        if cfg.enable_llm_fallback and (not reply or not ok):
            try:
                nonlocal llm
                if llm is None:
                    llm = create_client(
                        "vllm",
                        base_url=cfg.vllm_url,
                        model=cfg.vllm_model,
                    )
                history = history[-20:]  # keep it bounded
                history.append(LLMMessage("user", text))
                reply = llm.chat(history, temperature=0.4, max_tokens=512)
                history.append(LLMMessage("assistant", reply))
            except Exception as e:
                reply = reply or f"(LLM hata: {e})"

        print(f"🤖 {reply}")
        if cfg.enable_tts and tts is not None:
            try:
                tts.speak(reply)
            except Exception as e:
                print(f"(TTS hata: {e})")

    def run_enter_fallback() -> int:
        print("⚠️ Fallback: Enter ile 4sn kayıt.")
        try:
            import numpy as np  # noqa: F401
        except Exception:
            pass

        while True:
            line = input("> Enter: kaydet (4sn) | 'çık': çık\n")
            if (line or "").strip().lower() in {"çık", "cik", "exit", "quit", "stop"}:
                return 0
            try:
                recorder.start()
                time.sleep(4.0)
                audio = recorder.stop()
                try:
                    text, meta = get_asr().transcribe(audio)
                except Exception as e:
                    msg = str(e)
                    print(f"(ASR init/transcribe hata: {msg})")
                    if "Whisper model cache'te bulunamadı" in msg and "indirme kapalı" in msg:
                        return 1
                    continue
                print(f"📝 {text}{_fmt_meta(meta)}")
                normalized, info = _autocorrect(text, meta)
                if info.get("mode") == "re_record":
                    print("🤖 Anlayamadım. Tekrar söyler misin?")
                    continue
                if normalized.strip() and normalized.strip() != text.strip() and info.get("mode") in {"auto_run", "auto_fix"}:
                    print(f"(auto) → {normalized}")
                low_conf = info.get("bucket") in {"low", "med"}
                if normalized.strip():
                    handle_text(normalized, low_confidence=low_conf)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"(hata: {e})")

        return 0

    # PTT via pynput (global). Fallback: enter-to-record.
    if cfg.force_enter_ptt:
        return run_enter_fallback()

    try:
        from pynput import keyboard

        def on_press(key):
            nonlocal recording
            if key == keyboard.Key.space and not recording:
                recording = True
                try:
                    recorder.start()
                    print("… REC")
                except Exception as e:
                    recording = False
                    print(f"(REC start hata: {e})")

        def on_release(key):
            nonlocal recording
            if key == keyboard.Key.space and recording:
                recording = False
                try:
                    audio = recorder.stop()
                    if len(audio) == 0:
                        print("(boş kayıt)")
                        return
                    try:
                        text, meta = get_asr().transcribe(audio)
                    except Exception as e:
                        msg = str(e)
                        print(f"(ASR init/transcribe hata: {msg})")
                        if "Whisper model cache'te bulunamadı" in msg and "indirme kapalı" in msg:
                            return False
                        return True
                    print(f"📝 {text}{_fmt_meta(meta)}")
                    normalized, info = _autocorrect(text, meta)
                    if info.get("mode") == "re_record":
                        print("🤖 Anlayamadım. Tekrar söyler misin?")
                        return True
                    if normalized.strip() and normalized.strip() != text.strip() and info.get("mode") in {"auto_run", "auto_fix"}:
                        print(f"(auto) → {normalized}")
                    low_conf = info.get("bucket") in {"low", "med"}
                    if normalized.strip():
                        handle_text(normalized, low_confidence=low_conf)
                except Exception as e:
                    print(f"(ASR hata: {e})")
            return True

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()

        return 0

    except Exception:
        return run_enter_fallback()


def run_wake_word_loop(cfg: VoiceLoopConfig) -> int:
    """
    Wake word + VAD based voice loop.
    
    "Hey Bantz" (veya hey_jarvis) → dinle → işle → yanıtla → tekrar dinle
    
    Push-to-talk yerine sürekli dinleme modu.
    """
    from bantz.server import is_server_running, send_to_server, get_ipc_overlay_hook, ensure_server_running
    from bantz.llm import LLMMessage, create_client
    from bantz.voice.asr import ASR, ASRConfig
    from bantz.voice.tts import PiperTTS, PiperTTSConfig
    from bantz.voice.wakeword import WakeWordDetector, WakeWordConfig, VADRecorder
    
    # Ensure session server is running (auto-start for wake-word mode)
    policy_path = os.environ.get("BANTZ_POLICY", "config/policy.json")
    log_path = os.environ.get("BANTZ_LOG", "artifacts/logs/bantz.log.jsonl")
    ok, started_here, msg = ensure_server_running(cfg.session, policy_path=policy_path, log_path=log_path)
    if not ok:
        print(f"❌ Session server başlatılamadı (session={cfg.session}): {msg}")
        return 1
    if started_here:
        from bantz.server import get_socket_path
        print(f"ℹ️ Session server otomatik başlatıldı (session={cfg.session}).")
        print(f"   Socket: {get_socket_path(cfg.session)}")
        print(f"   Kapatmak için: bantz --session {cfg.session} --stop")
    
    # Setup TTS
    tts = None
    if cfg.enable_tts:
        if not cfg.piper_model_path:
            print("❌ Piper model path gerekli. Örn: --piper-model /path/to/tr.onnx  (veya geçici: --no-tts)")
            return 1

    # Preflight: if LLM is enabled but vLLM isn't reachable, disable it once and continue.
    if cfg.enable_llm_fallback:
        try:
            probe = create_client(
                "vllm",
                base_url=cfg.vllm_url,
                model=cfg.vllm_model,
                timeout=2.0,
            )
            if not probe.is_available(timeout_seconds=1.5):
                raise RuntimeError("unreachable")
        except Exception:
            print("⚠️  vLLM çalışmıyor veya erişilemiyor; LLM rewrite/fallback devre dışı.")
            print(f"   URL: {cfg.vllm_url}")
            print("   Başlat: scripts/vllm/start_3b.sh  (veya docs/setup/vllm.md)")
            cfg.enable_llm_fallback = False
        tts = PiperTTS(PiperTTSConfig(model_path=cfg.piper_model_path))
    
    # Setup ASR (lazy)
    asr: Optional[ASR] = None
    cache_dir = os.environ.get("BANTZ_ASR_CACHE_DIR", "").strip()
    allow_download = os.environ.get("BANTZ_ASR_ALLOW_DOWNLOAD", "0").strip() in {"1", "true", "True"}
    
    def get_asr() -> ASR:
        nonlocal asr
        if asr is None:
            asr = ASR(ASRConfig(
                whisper_model=cfg.whisper_model,
                language=cfg.language,
                sample_rate=cfg.sample_rate,
                cache_dir=cache_dir,
                allow_download=allow_download,
            ))
        return asr
    
    # Setup LLM fallback
    llm = None
    history: List[LLMMessage] = []
    if cfg.enable_llm_fallback:
        history = [
            LLMMessage(
                "system",
                "Sen Bantz'sın. Türkçe konuş. Kısa, net ve yardımcı ol.",
            )
        ]
    
    # Get overlay hook
    overlay = get_ipc_overlay_hook()
    
    # State
    is_listening = False
    should_exit = False
    
    print("🎤 Wake Word Modu: 'Hey Jarvis' veya 'Alexa' de → konuş → otomatik algıla")
    print("   Desteklenen: hey_jarvis, alexa, hey_mycroft, hey_rhasspy")
    print("   Çıkış: Ctrl+C")
    
    def on_wake_word(model_name: str):
        """Called when wake word is detected."""
        nonlocal is_listening
        
        if is_listening:
            return  # Already processing
        
        is_listening = True
        
        print(f"\n🔔 Wake word algılandı: {model_name}")
        
        # Show overlay wake state
        if overlay.is_connected():
            overlay.wake_sync("Sizi dinliyorum efendim.")
        
        try:
            # Start VAD-based recording
            if overlay.is_connected():
                overlay.listening_sync("Dinliyorum...")
            
            recorder = VADRecorder(
                sample_rate=cfg.sample_rate,
                silence_threshold=0.015,  # Adjust based on mic sensitivity
                silence_duration=1.5,
                max_duration=15.0,
                min_speech_duration=0.3,
            )
            recorder.start()
            
            print("… Dinliyorum (konuşmayı bitirince otomatik duracak)")
            
            # Wait for speech to end
            while True:
                should_stop, reason = recorder.should_stop()
                if should_stop:
                    break
                time.sleep(0.05)
            
            audio = recorder.stop()
            
            if reason == "too_short":
                print("(çok kısa konuşma, atlandı)")
                if overlay.is_connected():
                    overlay.speaking_sync("Bir şey duyamadım.")
                is_listening = False
                return
            
            if len(audio) == 0:
                print("(boş kayıt)")
                is_listening = False
                return
            
            # Show thinking state
            if overlay.is_connected():
                overlay.thinking_sync("Anlıyorum...")
            
            # Transcribe
            print("… Anlıyorum")
            try:
                text, meta = get_asr().transcribe(audio)
            except Exception as e:
                print(f"(ASR hata: {e})")
                is_listening = False
                return
            
            print(f"📝 {text}")
            
            if not text.strip():
                print("(boş metin)")
                is_listening = False
                return
            
            # Send to daemon
            resp = send_to_server(text, cfg.session)
            reply = resp.get("text", "")
            ok = resp.get("ok", False)
            
            print(f"{'✓' if ok else '✗'} {reply}")
            
            # Show speaking state
            if overlay.is_connected():
                overlay.speaking_sync(reply[:100] if reply else "Tamam!")
            
            # TTS response
            if tts and reply:
                # Clean reply for TTS
                clean = reply.split("Başka ne yapayım?")[0].strip()
                if clean:
                    try:
                        tts.speak(clean)
                    except Exception as e:
                        print(f"(TTS hata: {e})")
            
            # LLM fallback for unknown commands
            if not ok and cfg.enable_llm_fallback and "anlayamadım" in reply.lower():
                if llm is None:
                    try:
                        llm = create_client(
                            "vllm",
                            base_url=cfg.vllm_url,
                            model=cfg.vllm_model,
                        )
                    except Exception as e:
                        print(f"(LLM init hata: {e})")
                        is_listening = False
                        return
                
                print("🤖 LLM'e soruluyor...")
                history.append(LLMMessage("user", text))
                
                try:
                    llm_reply = llm.chat(history, temperature=0.4, max_tokens=512)
                    history.append(LLMMessage("assistant", llm_reply))
                    print(f"🤖 {llm_reply}")
                    
                    if tts:
                        tts.speak(llm_reply)
                except Exception as e:
                    print(f"(LLM hata: {e})")
            
        except Exception as e:
            print(f"(hata: {e})")
        finally:
            is_listening = False
            # Hide overlay after timeout (handled by overlay)
    
    # Setup wake word detector
    detector = WakeWordDetector(WakeWordConfig(
        threshold=0.5,
        sample_rate=cfg.sample_rate,
        cooldown_seconds=2.0,
    ))
    detector.set_callback(on_wake_word)
    
    try:
        if not detector.start():
            print("❌ Wake word detector başlatılamadı")
            return 1
        
        # Keep running until Ctrl+C
        while not should_exit:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n🛑 Çıkış...")
    finally:
        detector.stop()
    
    return 0


__all__ = ["VoiceLoopConfig", "run_voice_loop", "run_wake_word_loop"]
