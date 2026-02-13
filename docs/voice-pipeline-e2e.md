# Voice Pipeline E2E — Architecture & Design (Issue #296)

## Pipeline Overview

```
┌─────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐    ┌─────────┐
│   ASR   │───▶│  Router  │───▶│  Tool    │───▶│ Finalizer │───▶│   TTS   │
│ Whisper │    │  3B vLLM │    │ Executor │    │ Gemini/3B │    │  Piper  │
└─────────┘    └──────────┘    └──────────┘    └───────────┘    └─────────┘
   <500ms        <500ms         <2000ms          <2000ms          <500ms
```

**Total budget:** <4.5s ideal, <6s acceptable.

## Detailed Flow

```
1. ACTIVE_LISTEN state
   └── User speaks

2. ASR Transcription (Whisper, <500ms)
   ├── Hallucination guard (empty/repeat rejection)
   ├── Auto-reranking (TR/EN language detection)
   └── Autocorrect (Turkish diacritics, time suffixes)

3. Router (vLLM 3B, <500ms)
   ├── Pre-route bypass (greetings, time → skip LLM)
   ├── Memory-lite context injection
   ├── Route decision: calendar/gmail/news/system/smalltalk
   └── Tool plan: ["tool.name", ...]

4. Tool Narration (if tool_plan has slow tools)
   ├── "Haberleri kontrol ediyorum efendim..." → TTS
   └── Played BEFORE tool execution (eliminate dead air)

5. Tool Execution (<2000ms)
   ├── Allowlist/denylist validation
   ├── Confirmation firewall (destructive ops)
   ├── Timeout protection (ThreadPoolExecutor)
   └── Smart result summarization

6. Finalization (<2000ms)
   ├── Tier decision: quality (Gemini) vs fast (3B)
   ├── Cloud gating: 3 gates must pass for Gemini
   │   ├── GEMINI_API_KEY is set
   │   ├── BANTZ_CLOUD_MODE != "local"
   │   └── BANTZ_FINALIZE_WITH_GEMINI != "false"
   ├── No-new-facts guard (safety)
   └── Fallback: deterministic tool-success summaries

7. TTS (<500ms)
   ├── PiperTTS (subprocess, Turkish voice)
   └── Emotion-aware (speed, pitch adjustment)

8. Reset ACTIVE_LISTEN TTL
```

## Cloud Mode Gating

Three independent gates control whether Gemini is used for finalization:

| Gate | Env Var | Default | Effect |
|------|---------|---------|--------|
| API Key | `GEMINI_API_KEY` | (unset) | No key → 3B always |
| Cloud Mode | `BANTZ_CLOUD_MODE` | `local` | `local` → 3B always |
| Kill Switch | `BANTZ_FINALIZE_WITH_GEMINI` | `true` | `false` → 3B always |

**All three must pass** for Gemini to be used.

## Tool Narration Map

| Tool | Narration |
|------|-----------|
| `news.briefing` | "Haberleri kontrol ediyorum efendim..." |
| `calendar.list_events` | "Takviminize bakıyorum efendim..." |
| `calendar.create_event` | "Etkinliği oluşturuyorum efendim..." |
| `gmail.list_messages` | "Maillerinizi kontrol ediyorum efendim..." |
| `system.health_check` | "Sistem durumunu kontrol ediyorum efendim..." |
| `web.search` | "İnternette arıyorum efendim..." |
| `time.now` | *(no narration — instant)* |
| `web.open` | *(no narration — instant redirect)* |
| (unknown tool) | "Bir bakayım efendim..." *(generic fallback)* |

## Latency Budget

| Phase | Budget | Degradation Action |
|-------|--------|--------------------|
| ASR | 500ms | Use partial ASR result |
| Router | 500ms | Use pre-route cache |
| Tool | 2000ms | Async + feedback phrase |
| Finalizer | 2000ms | Skip Gemini → use 3B |
| TTS | 500ms | Use cached TTS phrase |

## API

```python
from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

# Headless mode (text only, no ASR/TTS)
pipe = VoicePipeline()
result = pipe.process_text("haber var mı")
print(result.reply, result.timing_summary())

# Full mode (audio → spoken reply)
pipe = VoicePipeline(config=VoicePipelineConfig(
    tts_callback=tts.speak,
    narration_callback=tts.speak,
))
result = pipe.process_utterance(audio_data)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BANTZ_CLOUD_MODE` | `local` | `local` or `cloud` |
| `BANTZ_FINALIZE_WITH_GEMINI` | `true` | Kill-switch for Gemini finalizer |
| `GEMINI_API_KEY` | (unset) | Gemini API key |
| `BANTZ_VLLM_URL` | `http://localhost:8001` | vLLM server URL |
| `BANTZ_VLLM_MODEL` | `Qwen/Qwen2.5-3B-Instruct` | Router model |

## E2E Test

```bash
# Run E2E simulation (requires live vLLM)
python scripts/e2e_voice_pipeline.py --debug

# Run unit tests
python -m pytest tests/test_issue_296_voice_pipeline.py -v
```
