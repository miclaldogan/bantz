# Ortam Değişkenleri Referansı

> Bantz'ın tüm yapılandırma değişkenleri ve varsayılan değerleri.

Env dosyası: `~/.config/bantz/env` (veya `BANTZ_ENV_FILE` ile override)

## LLM & Model

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_VLLM_URL` | `http://localhost:8001` | vLLM API endpoint |
| `BANTZ_VLLM_MODEL` | `Qwen/Qwen2.5-3B-Instruct-AWQ` | Router modeli. 7B upgrade için: `Qwen/Qwen2.5-7B-Instruct-AWQ` (bkz. `config/model-settings.yaml` → `router_7b`) |
| `BANTZ_ROUTER_CONTEXT_LEN` | (otomatik algılama, fallback 8192) | Router context window boyutu |
| `GEMINI_API_KEY` | — | Gemini API anahtarı (quality tier için) |
| `BANTZ_GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model adı |
| `BANTZ_CLOUD_MODE` | `local` | `local`: sadece 3B, `cloud`: Gemini aktif |

## Tiering & Quality Gating

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_TIER_MODE` | `1` | `1`: tiering açık, `0`: kapalı |
| `BANTZ_TIER_FORCE` | `auto` | `fast` / `quality` / `auto` |
| `BANTZ_TIER_FORCE_FINALIZER` | `auto` | Finalizer tier override |
| `BANTZ_TIER_QUALITY_THRESHOLD` | `1.8` | Quality tier eşiği (toplam skor) |
| `BANTZ_TIER_FAST_MAX_THRESHOLD` | `0.8` | Fast tier üst sınırı |
| `BANTZ_TIER_MIN_COMPLEXITY_FOR_QUALITY` | `3` | Karmaşıklık eşiği |
| `BANTZ_TIER_MIN_WRITING_FOR_QUALITY` | `3` | Yazı kalitesi eşiği |
| `BANTZ_TIER_QUALITY_RATE_LIMIT` | `30` | Dakikada max Gemini çağrısı |
| `BANTZ_TIER_DEBUG` | `0` | Tiering debug log |
| `BANTZ_TIER_METRICS` | `0` | Tiering metrik log |

## Voice & Audio

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_MIC_DEVICE` | `default` | Mikrofon cihazı |
| `BANTZ_SPEAKER_DEVICE` | `default` | Hoparlör cihazı |
| `BANTZ_ACTIVE_LISTEN_TTL_S` | `90` | Aktif dinleme süresi (saniye) |
| `BANTZ_SILENCE_TO_WAKE_S` | `30` | Sessizlikten wake moduna geçiş |
| `BANTZ_WAKE_WORDS` | `hey bantz,bantz,jarvis` | Wake word listesi |
| `BANTZ_WAKE_ENGINE` | `vosk` | Wake word motoru |
| `BANTZ_WAKE_SENSITIVITY` | `0.5` | Wake word hassasiyeti (0.0–1.0) |

## Privacy & Security

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_REDACT_PII` | `true` | PII redaction aktif/pasif |
| `BANTZ_VAULT_PASSPHRASE` | (machine-key) | Vault şifreleme parolası |
| `BANTZ_SANDBOX_ENABLED` | `true` | Komut sandbox koruması |

## Google Entegrasyonu

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_GOOGLE_CREDENTIALS_PATH` | `~/.config/bantz/google/credentials.json` | OAuth credentials |
| `BANTZ_GMAIL_TOKEN_PATH` | `~/.config/bantz/google/gmail_token.json` | Gmail token dosyası |
| `BANTZ_CALENDAR_TOKEN_PATH` | `~/.config/bantz/google/calendar_token.json` | Calendar token |

## Metrics & Logging

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_METRICS_ENABLED` | `true` | Metrik toplama |
| `BANTZ_LATENCY_BUDGET_MS` | `3000` | Hedef latency bütçesi (ms) |
| `BANTZ_LOG_LEVEL` | `INFO` | Log seviyesi |

## Morning Briefing

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `BANTZ_MORNING_BRIEFING` | `false` | Sabah brifing aktif/pasif |
| `BANTZ_BRIEFING_HOUR` | `08` | Brifing saati (0–23) |
