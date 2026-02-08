<p align="center">
  <img src="docs/bantz.png" alt="Bantz" width="400" />
</p>

<h1 align="center">Bantz</h1>

<p align="center">
  <strong>Local-first AI assistant for Linux — CLI, voice, and browser.</strong>
</p>

<p align="center">
  <a href="#quickstart"><img src="https://img.shields.io/badge/-Quickstart-blue?style=for-the-badge" alt="Quickstart" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/-Architecture-purple?style=for-the-badge" alt="Architecture" /></a>
  <a href="#voice-mode"><img src="https://img.shields.io/badge/-Voice-green?style=for-the-badge" alt="Voice" /></a>
  <a href="#google-integrations"><img src="https://img.shields.io/badge/-Google-red?style=for-the-badge" alt="Google" /></a>
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/-Contributing-orange?style=for-the-badge" alt="Contributing" /></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LLM-Qwen2.5--3B--AWQ-FF6F00" alt="LLM" />
  <img src="https://img.shields.io/badge/inference-vLLM-blueviolet" alt="vLLM" />
  <img src="https://img.shields.io/badge/finalizer-Gemini%202.0%20Flash-4285F4?logo=google&logoColor=white" alt="Gemini" />
  <img src="https://img.shields.io/badge/license-proprietary-lightgrey" alt="License" />
</p>

---

Bantz is a privacy-focused, local-first AI assistant that runs entirely on your machine. It routes requests through a fast 3B parameter model via [vLLM](https://github.com/vllm-project/vllm), executes tools (calendar, email, browser, system), and optionally polishes responses with Gemini for quality writing — all with sub-500ms time-to-first-token.

## Table of Contents

- [Highlights](#highlights)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Voice Mode](#voice-mode)
- [Google Integrations](#google-integrations)
- [Browser Extension](#browser-extension)
- [Configuration](#configuration)
- [Testing](#testing)
- [Benchmarks](#benchmarks)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Highlights

| Feature | Description |
|:--------|:------------|
| 🧠 **Brain Pipeline** | Plan → Execute → Finalize loop with tool orchestration and JSON repair |
| ⚡ **Sub-500ms TTFT** | 3B router at ~40ms, streaming responses, real-time latency monitoring |
| 🎙️ **Voice Control** | Push-to-talk with Faster Whisper ASR, wake-word detection, Piper TTS |
| 📅 **Google Calendar** | Create, query, modify, cancel events via OAuth2 — Turkish natural language |
| 📧 **Gmail** | Read, search, and draft emails with quality finalization |
| 🌐 **Browser Extension** | Chromium extension for web interaction and page context |
| 🔒 **Privacy First** | Everything local by default; cloud (Gemini) is opt-in |
| 🛡️ **Confirmation Firewall** | Destructive operations require explicit user approval |
| 🔧 **Extensible Tools** | Plug-in architecture — calendar, email, web search, system info, and more |
| 📊 **Observability** | Structured JSON logging, repair metrics, TTFT percentiles |

---

## Quickstart

### Prerequisites

- Linux (Ubuntu 20.04+ recommended)
- Python ≥ 3.10
- NVIDIA GPU with ≥ 6 GB VRAM (for local vLLM inference)

### 1. Clone & Install

```bash
git clone https://github.com/miclaldogan/bantz.git
cd bantz
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[llm]"
```

### 2. Start vLLM

```bash
# Recommended: 3B AWQ model on port 8001
./scripts/vllm/start_3b.sh
```

<details>
<summary>Or via Docker</summary>

```bash
docker compose up -d
curl http://127.0.0.1:8001/v1/models
```

</details>

### 3. Configure

```bash
cp config/bantz-env.example ~/.config/bantz/env
```

Minimum required variables:

```bash
export BANTZ_VLLM_URL="http://127.0.0.1:8001"
export BANTZ_VLLM_MODEL="Qwen/Qwen2.5-3B-Instruct-AWQ"
```

### 4. Run

```bash
# Single command
bantz --once "yarın saat 3'te toplantı kur"

# Interactive daemon
bantz --serve

# Voice mode (push-to-talk)
bantz --voice --piper-model /path/to/tr.onnx --asr-allow-download
```

<details>
<summary>💡 Enable Gemini for quality writing (optional)</summary>

For polished email drafts, long summaries, and better Turkish prose — add a Gemini API key:

```bash
# Add to ~/.config/bantz/env (never paste keys in shell history)
BANTZ_CLOUD_ENABLED=true
GEMINI_API_KEY=your_key_here
BANTZ_GEMINI_MODEL=gemini-2.0-flash
```

See [docs/secrets-hygiene.md](docs/secrets-hygiene.md) for best practices.

</details>

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                          BANTZ                                 │
│                                                                │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                 │
│  │  Voice    │    │  CLI     │    │  Browser │                 │
│  │  Loop     │    │  Client  │    │Extension │                 │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                 │
│       │               │               │                        │
│       └───────────────┼───────────────┘                        │
│                       ▼                                        │
│              ┌────────────────┐                                │
│              │  BantzServer   │  Unix socket daemon             │
│              └───────┬────────┘                                │
│                      ▼                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Brain Pipeline                        │   │
│  │                                                         │   │
│  │  ┌───────────┐   ┌──────────────┐   ┌──────────────┐   │   │
│  │  │ PreRouter  │──▶│  LLM Router  │──▶│  Tool        │   │   │
│  │  │ (intent)   │   │  (3B, ~40ms) │   │  Executor    │   │   │
│  │  └───────────┘   └──────────────┘   └──────┬───────┘   │   │
│  │                                             │           │   │
│  │                                             ▼           │   │
│  │                                     ┌──────────────┐    │   │
│  │                                     │  Finalizer   │    │   │
│  │                                     │  (tiered)    │    │   │
│  │                                     └──────────────┘    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Calendar │  │  Gmail   │  │  Web     │  │  System  │      │
│  │  Tools   │  │  Tools   │  │  Tools   │  │  Tools   │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└────────────────────────────────────────────────────────────────┘
         │                                       │
         ▼                                       ▼
   ┌───────────┐                          ┌───────────┐
   │   vLLM    │  Qwen2.5-3B-AWQ         │  Gemini   │  2.0 Flash
   │  (local)  │  port 8001              │  (cloud)  │  (optional)
   └───────────┘                          └───────────┘
```

### Pipeline Flow

1. **Input** arrives from CLI, voice, or browser extension
2. **BantzServer** routes through the brain pipeline (default) or legacy router (`BANTZ_USE_LEGACY=1`)
3. **PreRouter** classifies intent (smalltalk → fast path, tool-needed → planner)
4. **LLM Router** (Qwen 3B via vLLM) generates a structured JSON plan: route, tools, slots
5. **JSON Repair** fixes common 3B mistakes — wrong enums, string-instead-of-list, markdown wrapping
6. **Tool Executor** runs the planned tools (calendar, email, web, system)
7. **Tiered Finalizer** decides quality vs. fast response:
   - **Quality tier** → Gemini 2.0 Flash (polished Turkish prose)
   - **Fast tier** → local 3B (sub-200ms, good enough for simple replies)
   - **Draft tier** → deterministic template (no LLM call)

### Key Design Decisions

- **Brain is the default path** — all entry points (CLI, voice, browser) flow through the unified brain pipeline
- **Tiered finalization** — complexity, writing need, and risk scores determine whether to use cloud or local
- **Confirmation firewall** — destructive tools (delete, shutdown) require explicit user approval regardless of LLM output
- **JSON repair at every layer** — deterministic repair for enums/types, LLM-based repair for structural failures

---

## Voice Mode

Bantz supports full voice interaction with push-to-talk:

```bash
pip install -e ".[voice]"
bantz --voice --piper-model /path/to/tr.onnx --asr-allow-download
```

| Component | Engine | Details |
|:----------|:-------|:--------|
| ASR | [Faster Whisper](https://github.com/SYSTRAN/faster-whisper) | Local, Turkish-optimized |
| TTS | [Piper](https://github.com/rhasspy/piper) | Local, ONNX models |
| Wake Word | Vosk / OpenWakeWord | Configurable via `BANTZ_WAKE_ENGINE` |
| Autocorrect | RapidFuzz | Fixes common ASR transcription errors |
| VAD | Energy + Silero | Voice activity detection for clean segmentation |

<details>
<summary>Voice environment variables</summary>

```bash
BANTZ_WAKE_WORDS=hey bantz,bantz,jarvis
BANTZ_WAKE_ENGINE=vosk
BANTZ_WAKE_SENSITIVITY=0.5
BANTZ_ACTIVE_LISTEN_TTL_S=90
BANTZ_SILENCE_TO_WAKE_S=30
```

</details>

---

## Google Integrations

### Calendar

```bash
pip install -e ".[calendar]"

# Setup OAuth
bantz google auth calendar --write

# Use naturally
bantz --once "yarın saat 5'te toplantı kur"
bantz --once "bugün neler var?"
bantz --once "cuma günkü toplantıyı iptal et"
```

### Gmail

```bash
# Authenticate
bantz google auth gmail --scope readonly

# Use naturally
bantz --once "okunmamış maillerimi göster"
bantz --once "Ahmet'e nazik bir mail yaz"
```

<details>
<summary>OAuth setup details</summary>

1. Place your Google Cloud OAuth client secret at:
   ```
   ~/.config/bantz/google/client_secret.json
   ```
   Or set `BANTZ_GOOGLE_CLIENT_SECRET` to a custom path.

2. Mint tokens via CLI:
   ```bash
   bantz google env                          # show config paths
   bantz google auth calendar --write        # calendar read+write
   bantz google auth gmail --scope readonly  # gmail read-only
   ```

Full guide: [docs/setup/google-oauth.md](docs/setup/google-oauth.md)

</details>

---

## Browser Extension

A Chromium-based extension that connects Bantz to your browser:

```bash
pip install -e ".[browser]"
```

- Page context extraction for better answers
- Tab management and navigation
- Web search integration

See [bantz-extension/](bantz-extension/) for the extension source.

---

## Configuration

All configuration is via environment variables. Copy the example and customize:

```bash
cp config/bantz-env.example ~/.config/bantz/env
```

### Core Variables

| Variable | Default | Description |
|:---------|:--------|:------------|
| `BANTZ_VLLM_URL` | `http://localhost:8001` | vLLM endpoint |
| `BANTZ_VLLM_MODEL` | `Qwen/Qwen2.5-3B-Instruct-AWQ` | Router model |
| `BANTZ_GEMINI_MODEL` | `gemini-2.0-flash` | Finalizer model (when cloud enabled) |
| `BANTZ_CLOUD_ENABLED` | `false` | Enable Gemini cloud finalization |
| `GEMINI_API_KEY` | — | Gemini API key (required if cloud enabled) |
| `BANTZ_USE_LEGACY` | — | Set to `1` to bypass brain and use legacy router |

### Tiered Finalization

| Variable | Default | Description |
|:---------|:--------|:------------|
| `BANTZ_TIERED_MODE` | `1` | Enable tiered quality/fast finalization |
| `BANTZ_FORCE_FINALIZER_TIER` | — | Force `quality` or `fast` tier (debug/testing) |
| `BANTZ_QOS_QUALITY_TIMEOUT_S` | `90` | Timeout for quality (Gemini) calls |
| `BANTZ_QOS_FAST_TIMEOUT_S` | `20` | Timeout for fast (3B) calls |

### Privacy & Security

| Variable | Default | Description |
|:---------|:--------|:------------|
| `BANTZ_REDACT_PII` | `true` | Redact personally identifiable information |
| `BANTZ_METRICS_ENABLED` | `true` | Enable structured metrics logging |
| `BANTZ_LATENCY_BUDGET_MS` | `3000` | Max acceptable end-to-end latency |

<details>
<summary>All optional dependency groups</summary>

```bash
pip install -e ".[llm]"        # vLLM + torch + transformers
pip install -e ".[calendar]"   # Google Calendar
pip install -e ".[voice]"      # ASR + TTS + wake word
pip install -e ".[browser]"    # WebSocket browser bridge
pip install -e ".[vision]"     # Screenshot + OCR + PDF
pip install -e ".[system]"     # D-Bus + system tray
pip install -e ".[ui]"         # PyQt5 overlay UI
pip install -e ".[security]"   # Cryptography
pip install -e ".[dev]"        # pytest + dev tools
pip install -e ".[all]"        # Everything
```

</details>

---

## Testing

Bantz has a comprehensive test suite:

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all unit tests
pytest tests/ -v

# Run specific test categories
pytest tests/test_json_repair_golden.py -v     # JSON repair golden tests
pytest tests/test_tiered_*.py -v               # Tiered scoring tests
pytest tests/test_issue_520_banner.py -v       # Runtime banner tests

# Integration tests (requires running vLLM)
pytest tests/ -v --run-integration

# Regression tests (requires benchmark results)
pytest tests/ -v -m regression
```

### Test Coverage Highlights

| Area | Tests | What's covered |
|:-----|:------|:---------------|
| JSON Repair | 58 golden tests | Markdown fencing, truncated output, wrong types/enums, Turkish unicode |
| Tiered Scoring | Complexity, writing, risk | Turkish query scoring with read/write disambiguation |
| Orchestrator | Multi-turn, tool execution | Error recovery, context carry, fallback paths |
| Confirmation Firewall | Risk classification | Destructive operation blocking |
| Gemini Client | Rate limiting, circuit breaker | Streaming, quota management |
| Router Schemas | Pydantic validation | Enum repair, type coercion |

---

## Benchmarks

```bash
# Run performance benchmarks
python scripts/bench_ttft_monitoring.py --num-tests 30

# Compare 3B-only vs hybrid mode
python scripts/bench_hybrid_vs_3b_only.py --mode both

# Generate report
python scripts/generate_benchmark_report.py
```

### Performance Targets

| Metric | Target | Typical |
|:-------|:-------|:--------|
| Router TTFT (3B) | p95 < 300ms | ~40–50ms ✅ |
| Finalizer TTFT (Gemini) | p95 < 500ms | Varies by network |
| JSON validity | > 95% | ~99% with repair ✅ |
| Route accuracy | > 90% | ~95% ✅ |
| End-to-end latency | < 3000ms | ~500–1500ms ✅ |

---

## Project Structure

```
bantz/
├── src/bantz/                 # Main package (378 modules)
│   ├── brain/                 # Brain pipeline: orchestrator, finalization, JSON repair
│   ├── llm/                   # LLM clients: vLLM, Gemini, tiered scoring
│   ├── router/                # Intent router: schemas, prompts, handlers
│   ├── tools/                 # Tool registry: calendar, gmail, web, system
│   ├── voice/                 # Voice loop: ASR, TTS, wake word, VAD
│   ├── server.py              # Unix socket daemon (brain default)
│   └── ...                    # 30+ subsystem modules
├── tests/                     # 7,500+ tests across 277 test files
│   ├── fixtures/              # Mock responses, golden traces
│   └── scenarios/             # Benchmark test cases (50+ scenarios)
├── scripts/                   # CLI tools, benchmarks, demos
├── config/                    # Environment templates, model settings
├── bantz-extension/           # Chromium browser extension
├── docker/                    # vLLM Docker deployment
├── docs/                      # Architecture docs, setup guides
├── pyproject.toml             # Package config (hatchling)
└── docker-compose.yml         # One-command vLLM deployment
```

---

## Documentation

| Document | Description |
|:---------|:------------|
| [docs/setup/vllm.md](docs/setup/vllm.md) | vLLM installation and configuration |
| [docs/setup/google-oauth.md](docs/setup/google-oauth.md) | Google Calendar & Gmail OAuth setup |
| [docs/setup/boot-jarvis.md](docs/setup/boot-jarvis.md) | Systemd service and boot configuration |
| [docs/setup/docker-vllm.md](docs/setup/docker-vllm.md) | Docker-based vLLM deployment |
| [docs/setup/memory.md](docs/setup/memory.md) | Conversation memory configuration |
| [docs/setup/google-vision.md](docs/setup/google-vision.md) | Vision and OCR setup |
| [docs/gemini-hybrid-orchestrator.md](docs/gemini-hybrid-orchestrator.md) | Hybrid architecture deep-dive |
| [docs/confirmation-firewall.md](docs/confirmation-firewall.md) | Security firewall documentation |
| [docs/voice-pipeline-e2e.md](docs/voice-pipeline-e2e.md) | Voice pipeline end-to-end flow |
| [docs/acceptance-tests.md](docs/acceptance-tests.md) | Acceptance test criteria |
| [docs/secrets-hygiene.md](docs/secrets-hygiene.md) | API key and secrets best practices |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](SECURITY.md) | Security policy |

---

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

```bash
# Development setup
git clone https://github.com/miclaldogan/bantz.git
cd bantz
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"

# Run tests
pytest tests/ -v

# Create a feature branch
git checkout -b feature/your-feature dev
```

---

## License

Proprietary. Copyright © 2024–2026 Mıcıl Aldoğan. All Rights Reserved.

See [LICENSE](LICENSE) for details.