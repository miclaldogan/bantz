# Bantz Mimarisi

> Bantz'ın iç yapısını, veri akışını ve bileşen etkileşimlerini açıklar.

## Genel Bakış

Bantz, **LLM-first** mimariye sahip bir Türkçe kişisel asistan. Küçük bir router model (3B) hızlı karar verir, kaliteli yanıt gerektiğinde Gemini API'ye yönlendirir.

## Pipeline Diyagramı

```
┌─────────────┐
│  Kullanıcı   │
│  (metin/ses) │
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌───────────────┐
│  PreRouter   │───▶│ Local Reply   │  (selamlama/vedalaşma → statik yanıt)
│  (keyword)   │    │ (bypass LLM)  │
└──────┬───────┘    └───────────────┘
       │ hint
       ▼
┌──────────────┐
│  3B Router   │  Qwen2.5-3B-Instruct-AWQ (vLLM)
│  (LLM)       │  → route, intent, slots, tool_plan, confidence
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Quality     │  Tiered gating: complexity × writing × risk
│  Gating      │  → FAST (3B) | QUALITY (Gemini)
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌───────────────┐
│  Tool Runner │───▶│ Google APIs   │  Calendar, Gmail, Contacts
│              │    │ System Tools  │  time.now, screenshot
│              │    │ Browser Tools │  open, scan, click
└──────┬───────┘    └───────────────┘
       │ tool results
       ▼
┌──────────────┐
│  Finalizer   │  Fast: 3B Qwen  |  Quality: Gemini Flash
│  Pipeline    │  → Türkçe doğal dil yanıtı oluşturur
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌───────────────┐
│  Post-proc   │───▶│ PII Redaction │
│              │    │ Language Val.  │
│              │    │ Secret Mask    │
└──────┬───────┘    └───────────────┘
       │
       ▼
┌─────────────┐
│  Kullanıcı   │
│  (yanıt/TTS) │
└─────────────┘
```

## Bileşenler

### 1. PreRouter (`routing/preroute.py`)
- Keyword tabanlı hızlı sınıflandırma
- Selamlama, vedalaşma, teşekkür → LLM bypass
- Sistem sorguları (saat, tarih) → doğrudan tool
- Düşük güvenilirlik → LLM'e hint olarak iletir

### 2. 3B Router (`brain/llm_router.py`)
- Qwen2.5-3B-Instruct-AWQ modeli (vLLM üzerinde)
- JSON structured output: route, intent, slots, tool_plan
- ~200-400ms latency (RTX 4060)

### 3. Quality Gating (`brain/quality_gating.py`)
- Ağırlıklı skor: 0.35×complexity + 0.45×writing + 0.20×risk
- FAST tier: 3B model ile finalize
- QUALITY tier: Gemini API ile finalize
- Rate limiting: dakikada max 30 Gemini çağrısı

### 4. Tool Runner (`agent/tool_runner.py`)
- Risk-based confirmation: safe / moderate / destructive
- Timeout yönetimi (varsayılan 30s)
- Circuit breaker pattern

### 5. Finalization Pipeline (`brain/finalization_pipeline.py`)
- Tool sonuçlarını Türkçe doğal dile çevirir
- Dil doğrulama guard'ı (Çince/İngilizce karışımını engeller)
- Quality path: Gemini Flash
- Fast path: 3B Qwen

### 6. Memory (`memory/`)
- Session memory: konuşma geçmişi
- Persistent memory: SQLite tabanlı uzun dönem
- PII filtresi: hassas veri redaction

### 7. Voice Pipeline (`voice/`)
- ASR: Whisper (faster-whisper)
- TTS: Piper (Türkçe model)
- Wake word: Vosk tabanlı
- Barge-in desteği

## Veri Akış Sırası

1. **Input** → Metin veya ASR transkripsiyonu
2. **PreRoute** → Keyword match kontrol
3. **LLM Planning** → 3B router JSON çıktısı
4. **Quality Gate** → Tier kararı (fast/quality)
5. **Tool Execution** → API çağrıları
6. **Finalization** → Doğal dil yanıtı
7. **Post-processing** → PII redaction, dil doğrulama
8. **Output** → Metin veya TTS

## Dizin Yapısı

```
src/bantz/
├── brain/          # Orchestrator, router, finalizer, quality gating
├── routing/        # PreRouter, keyword rules
├── agent/          # Tool definitions, runner, controller
├── llm/            # LLM client abstractions (vLLM, Gemini)
├── memory/         # Session + persistent memory
├── voice/          # ASR, TTS, voice loop, wake word
├── google/         # Calendar, Gmail, Auth
├── security/       # Vault, sandbox, policy, audit
├── privacy/        # PII redaction
├── core/           # Events, config, env loader
└── logs/           # JSONL logger
```
