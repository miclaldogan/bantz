# Issue #287 — Boot-to-Jarvis Epic: Closure Summary

**Epic:** EPIC: Boot-to-Jarvis (autostart + always-on wake + proactive briefing + graceful idle)
**Status:** ✅ ALL 19 sub-issues CLOSED
**Date:** 2025-07-14

---

## Vision (achieved)

Bilgisayar açılır açılmaz BANTZ arka planda çalışıyor:
- LLM backend(ler)i hazır (local vLLM + opsiyonel Gemini finalizer)
- Sesli selam: "Sizi tekrardan görmek güzel efendim."
- Wake word beklemeden kısa süre aktif dinleme
- "Şimdilik gerek yok" → "İyi çalışmalar efendim" → WAKE_ONLY
- Wake word dinlemesi sürekli açık

---

## Sub-Issue Tracker

| # | Title | PR | Status |
|---|-------|-----|--------|
| #288 | systemd --user autostart (core + voice) | PR #547 | ✅ |
| #289 | LLM warmup pipeline (vLLM + Gemini preflight) | PR #548 | ✅ |
| #290 | Voice session FSM (ACTIVE_LISTEN / WAKE_ONLY / IDLE_SLEEP) | PR #549 | ✅ |
| #291 | Wake word engine + audio device selection + fallback | PR #550 | ✅ |
| #292 | Boot greeting + immediate active listen | PR #551 | ✅ |
| #293 | Dismiss/stop intent + polite goodbye | PR #552 | ✅ |
| #294 | News briefing skill (AI + tech + turkey) | PR #553 | ✅ |
| #295 | System health check skill (CPU/RAM/Disk/GPU) | PR #533 | ✅ |
| #296 | Voice pipeline: ASR → router → tool → finalize | PR #534 | ✅ |
| #297 | TTS: Consistent voice + barge-in | PR #538 | ✅ |
| #298 | Controls: Push-to-talk + mic mute + status indicator | PR #540 | ✅ |
| #299 | Privacy: Mic indicator + local-only + cloud consent | PR #539 | ✅ |
| #300 | Suspend/Resume handling | PR #537 | ✅ |
| #301 | Voice watchdog + crash recovery | PR #536 | ✅ |
| #302 | Latency budgets + metrics gates | PR #535 | ✅ |
| #303 | Memory: Boot greeting uses profile prefs | PR #541 | ✅ |
| #304 | Proactive morning briefing | PR #542 | ✅ |
| #305 | E2E boot-to-ready smoke script | PR #543 | ✅ |
| #306 | Docs: Boot Jarvis setup guide | PR #544 | ✅ |

**Total: 19/19 complete**

---

## Architecture Delivered

### Boot Sequence
```
systemd user session
  └── bantz.target
       ├── bantz-core.service  (orchestrator, LLM warmup)
       └── bantz-voice.service (wake word + ASR)

Boot flow:
  1. systemd starts bantz-core.service
  2. LLM warmup: vLLM health check → warmup prompt → ready.json
  3. bantz-voice.service starts after core is ready
  4. Wake engine starts (Vosk default, PTT fallback)
  5. boot_greeting(): TTS "Sizi tekrardan görmek güzel efendim."
  6. FSM → ACTIVE_LISTEN (90s TTL, no wake word needed)
  7. User speaks → ASR → router → tool → finalize → TTS
  8. Silence timeout → WAKE_ONLY
  9. User says "teşekkürler şimdilik" → goodbye → WAKE_ONLY
  10. Wake word "hey bantz" → ACTIVE_LISTEN again
```

### Key Modules Created

| Module | Purpose |
|--------|---------|
| `systemd/user/bantz-core.service` | Orchestrator autostart |
| `systemd/user/bantz-voice.service` | Voice service autostart |
| `systemd/user/bantz.target` | Service group target |
| `src/bantz/llm/preflight.py` | vLLM health + warmup + Gemini preflight |
| `src/bantz/voice/session_fsm.py` | VoiceFSM state machine |
| `src/bantz/voice/wake_engine_base.py` | WakeEngineBase ABC + PTT fallback |
| `src/bantz/voice/wake_engine_vosk.py` | Vosk wake engine |
| `src/bantz/voice/audio_devices.py` | Audio device enumeration |
| `src/bantz/voice/greeting.py` | Boot greeting + quiet hours |
| `src/bantz/intents/dismiss.py` | Dismiss intent detector (Turkish) |
| `src/bantz/skills/news_briefing.py` | RSS news + cache + voice formatter |

### Test Coverage
- **Total new tests this epic:** 160+
- All modules have dedicated test files
- Offline-only tests (no network, no hardware)
- Injectable clocks for time-dependent tests

---

## Configuration Summary

### Environment Variables
```bash
# systemd
BANTZ_HOME=/home/$USER/Desktop/Bantz
BANTZ_VENV=$BANTZ_HOME/.venv

# LLM warmup
BANTZ_VLLM_URL=http://localhost:8001
BANTZ_GEMINI_API_KEY=  # optional

# Voice FSM
BANTZ_ACTIVE_LISTEN_TTL_S=90
BANTZ_SILENCE_TO_WAKE_S=30
BANTZ_IDLE_SLEEP_ENABLED=false
BANTZ_IDLE_SLEEP_TIMEOUT_S=300

# Wake engine
BANTZ_WAKE_WORDS=hey bantz,bantz,jarvis
BANTZ_AUDIO_INPUT_DEVICE=default
BANTZ_WAKE_ENGINE=vosk
BANTZ_WAKE_SENSITIVITY=0.5

# Greeting
BANTZ_BOOT_GREETING=true
BANTZ_QUIET_HOURS_START=00:00
BANTZ_QUIET_HOURS_END=07:00
BANTZ_GREETING_TEXT=Sizi tekrardan görmek güzel efendim.

# News
BANTZ_NEWS_CACHE_TTL=1800
BANTZ_NEWS_MAX_ITEMS=3
BANTZ_NEWS_CATEGORIES=ai,tech,turkey
```

---

## Acceptance Criteria (all met)

- [x] Reboot sonrası 30-60sn içinde "ready" state
- [x] Wake word her zaman çalışır
- [x] Session davranışı deterministik ve testli
- [x] "Sizi tekrardan görmek güzel efendim" → kullanıcı cevap verir → asistan işler
- [x] "Teşekkürler şimdilik" → "İyi çalışmalar efendim" → WAKE_ONLY mode
