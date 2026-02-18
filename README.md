<p align="center">
  <img src="docs/bantz.png" alt="Bantz" width="900" />
</p>

<h1 align="center">Bantz</h1>

<p align="center">
  <strong>Local-first AI assistant for Linux — tools, not just chat.</strong>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="#roadmap">Roadmap</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" />
  <img alt="Ollama" src="https://img.shields.io/badge/Ollama-qwen2.5--coder:7b-black?logo=ollama" />
  <img alt="Gemini Flash" src="https://img.shields.io/badge/Gemini-2.0_Flash-4285F4?logo=google&logoColor=white" />
  <img alt="License" src="https://img.shields.io/badge/license-Proprietary-lightgrey" />
  <img alt="Open Issues" src="https://img.shields.io/github/issues/miclaldogan/bantz?color=orange" />
</p>

---

## What is Bantz?

**Bantz is in active early development.** But here what Bantz is -> Bantz is a **local-first AI assistant** that runs on your Linux desktop and actually *does things* — manages your calendar, reads your email, controls your browser, runs system commands, and more. It connects a fast local LLM (Ollama) with 75+ registered tools through a structured brain pipeline.

Unlike cloud-only assistants, Bantz keeps your data local. Unlike chatbots, Bantz executes real actions with a confirmation firewall for anything destructive.

**Current direction:** We're building toward a *smarter* assistant — better reasoning, persistent memory, observable tool execution, and an evolving data platform. The goal is an AI that genuinely understands context across conversations, not just responds to one-off prompts.

### Key Capabilities

| Area | What it does | Backend |
|:-----|:-------------|:--------|
| **Calendar** | Create, update, cancel events; find free slots; natural date parsing | Google Calendar API |
| **Email** | List inbox, read, draft, reply, send with confirmation | Gmail API |
| **Classroom** | List courses, assignments, enrollment via link | Google Classroom API |
| **Contacts** | Lookup, manage Google Contacts | Google People API |
| **Web Search** | Real-time search, page extraction | Chromium extension |
| **Weather** | Current weather & forecast for any city | wttr.in |
| **Browser** | Open URLs, extract page content, tab management | Chromium extension + WebSocket |
| **System** | Screenshot, clipboard, notifications, app launch, disk info | D-Bus + native |
| **Terminal** | Execute commands in a sandboxed environment | Subprocess with guardrails |
| **Phone Calls** | Manage call actions (Linux audio/phone integrations) | system tools |
| **HUD Overlay** | Always-on-top transparent desktop UI with news, calendar, inbox | Electron |
| **Data Store** | Gmail/Calendar/Classroom → local SQLite TTL cache | IngestStore |

### How it works (30-second version)

```
You say something → PreRouter classifies intent → LLM Router picks tools
→ Tools execute (with confirmation if destructive) → Finalizer writes the response
```

The router runs locally via Ollama (~50ms). When the task needs polished writing or complex reasoning, a tiered quality gate escalates to Gemini 2.0 Flash.

---

## Project Status

> **Bantz is in active early development.** The repo was created in January 2026 and is evolving rapidly. Expect breaking changes, incomplete features, and rough edges. We're building in the open — contributions and feedback are welcome.

| Milestone | Status |
|:----------|:-------|
| Core brain pipeline (route → execute → finalize) | **Shipped** (v0.2.0) |
| 75 tools across 13 categories | **Shipped** |
| Google Calendar + Gmail golden paths | **Shipped** |
| Confirmation firewall for destructive ops | **Shipped** |
| LanguageBridge (TR↔EN translation layer) | **Shipped** |
| Data platform — Ingest Store + TTL cache | **In Progress** (PR #1301) |
| Observability — structured run/tool/artifact DB | **Planned** (#1290) |
| Graph memory — persistent cross-session context | **Planned** (#1289) |
| Voice mode (ASR + TTS) | **Available** but deprioritized |

---

## Quickstart

### Prerequisites

- **Linux** (Ubuntu 22.04+ recommended)
- **Python 3.10+**
- **Ollama** installed and running ([install guide](https://ollama.com/download))

### 1. Install Ollama & pull the router model

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh

# Pull the router model
ollama pull qwen2.5-coder:7b
```

### 2. Clone & install Bantz

```bash
git clone https://github.com/miclaldogan/bantz.git
cd bantz
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
```

### 3. Configure

```bash
cp config/bantz-env.example ~/.config/bantz/env
```

Edit `~/.config/bantz/env` with your settings. The minimum required:

```bash
# Local LLM (Ollama)
BANTZ_OLLAMA_MODEL="qwen2.5-coder:7b"

# Optional: Enable Gemini for quality-tier finalization
BANTZ_CLOUD_ENABLED=true
GEMINI_API_KEY=your_key_here
BANTZ_GEMINI_MODEL=gemini-2.0-flash
```

### 4. Run

```bash
# System health check
python3 -m bantz doctor

# Interactive assistant
python3 -m bantz --serve

# Single command
python3 -m bantz --once "what meetings do I have today?"
```

<details>
<summary>Google OAuth setup (for Calendar & Gmail)</summary>

1. Place your Google Cloud OAuth client secret at `~/.config/bantz/google/client_secret.json`
2. Authenticate:
   ```bash
   bantz google auth calendar --write
   bantz google auth gmail --scope readonly
   ```

Full guide: [docs/setup/google-oauth.md](docs/setup/google-oauth.md)

</details>

<details>
<summary>Optional: Enable Gemini for polished responses</summary>

For high-quality email drafts, long summaries, and better prose — add a Gemini API key:

```bash
BANTZ_CLOUD_ENABLED=true
GEMINI_API_KEY=your_key_here
BANTZ_GEMINI_MODEL=gemini-2.0-flash
```

See [docs/secrets-hygiene.md](docs/secrets-hygiene.md) for key management best practices.

</details>

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                            BANTZ                                   │
│                                                                    │
│  ┌─────────────┐   ┌───────────────┐   ┌──────────────────────┐  │
│  │  Electron   │   │   CLI /        │   │  Chromium Extension  │  │
│  │  HUD Overlay│   │ python3 -m bantz│   │  (bantz-extension)   │  │
│  └──────┬──────┘   └───────┬────────┘   └──────────┬───────────┘  │
│         │   Unix IPC       │                        │              │
│         └──────────────────┼────────────────────────┘              │
│                            ▼                                       │
│                  ┌─────────────────┐                               │
│                  │   BantzServer   │  Unix socket + FastAPI :8088   │
│                  └────────┬────────┘                               │
│                           ▼                                        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Brain Pipeline                            │  │
│  │                                                              │  │
│  │  PreRouter ──► LLM Router ──► Tool Executor                 │  │
│  │  (fast bypass)  (Ollama,       (75+ tools,                  │  │
│  │                  ~50ms)         confirmation firewall)        │  │
│  │                      │                   │                   │  │
│  │                      ▼                   ▼                   │  │
│  │               Quality Gate ──► Tiered Finalizer              │  │
│  │               (complexity ×    Fast: local Ollama            │  │
│  │                writing ×       Quality: Gemini Flash          │  │
│  │                risk score)     Draft: template               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │ Calendar │ │  Gmail   │ │ Classroom│ │  Browser │ │System  │  │
│  │  Tools   │ │  Tools   │ │  OAuth   │ │  Tools   │ │ Tools  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │       Data Layer — SQLite (IngestStore TTL cache)            │  │
│  │  Gmail ──► EPHEMERAL (24h)  │  Calendar ──► EPHEMERAL (24h) │  │
│  │  Classroom ──► SESSION (7d) │  Contacts ──► PERSISTENT       │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
        │                                         │
        ▼                                         ▼
  ┌───────────┐                           ┌───────────┐
  │  Ollama   │  qwen2.5-coder:7b         │  Gemini   │  2.0 Flash
  │  (local)  │  router + fast-tier        │  (cloud)  │  quality-tier
  └───────────┘                           └───────────┘
```

### Pipeline Flow

1. **Input** arrives from CLI, browser extension, or (optionally) voice
2. **PreRouter** classifies intent — greetings and simple queries bypass the LLM entirely
3. **LLM Router** (qwen2.5-coder:7b via Ollama) generates a structured JSON plan: route, intent, slots, tool_plan
4. **JSON Repair** fixes common small-model mistakes — wrong enums, type mismatches, truncated output
5. **Tool Executor** runs planned tools through the confirmation firewall (destructive ops require approval)
6. **Quality Gate** scores the response need: `0.35×complexity + 0.45×writing + 0.20×risk`
7. **Tiered Finalizer** picks the right backend:
   - **Quality tier** → Gemini 2.0 Flash (polished prose, complex reasoning)
   - **Fast tier** → local LLM (sub-200ms, good enough for simple replies)
   - **Draft tier** → deterministic template (no LLM call needed)

### Key Design Decisions

| Decision | Rationale |
|:---------|:----------|
| **Local-first** | Your data stays on your machine. Cloud (Gemini) is opt-in for quality. |
| **Tool-centric** | The assistant's value comes from *doing things*, not generating text. |
| **Tiered finalization** | Not every response needs a cloud call. Smart routing saves latency and cost. |
| **Confirmation firewall** | Destructive operations (delete, shutdown, send) always require explicit approval. |
| **LanguageBridge** | Transparent TR↔EN translation so the English-trained model works natively with any language input. |
| **JSON repair at every layer** | Small models produce imperfect JSON. Deterministic + LLM-based repair catches it. |

### LLM Router Benchmarks

Benchmarked on **RTX 4050 Laptop GPU (6 GB VRAM)**. Each model receives the same enriched English system prompt with explicit RULES block and must return a structured JSON routing decision across 10 test queries (calendar, gmail, system, smalltalk, news intents). Input is always English — LanguageBridge translates TR→EN before the model sees it.

> ⚠️ **Note on accuracy figures:** Results are from a 10-query micro-benchmark on the specific prompt/intent set used, not a broad held-out evaluation. Real-world accuracy varies with prompt diversity. "10/10 on this set" is more precise than "100%."

#### Current Setup — Enriched Prompt, Ollama Only (full GPU)

| Model | Params | Quant | Cold Start | Warm Latency | Throughput | Routing (10 q) | Thinking |
|:------|:-------|:------|:-----------|:-------------|:-----------|:---------------|:---------|
| **qwen2.5-coder:7b** ⭐ | 7B | Q4_K_M | 3.6s | **0.34s** | **35.5 t/s** | 10/10 | — |
| **qwen2.5:7b** | 7B | Q4_K_M | 3.1s | **0.36s** | **35.0 t/s** | 10/10 | — |
| **nanbeige4.1-3B** 🧠 | 3.9B | Q8_0 | 4.2s | **0.46s** | **40.6 t/s** | 10/10 | ✅ |
| **gpt-oss:20b** | 20B | Q4_K_M | 6.9s | 4.71s | 10.9 t/s | 10/10 | — |

#### Previous Baseline — Old Prompt, Ollama + vLLM (GPU shared)

| Model | Params | Quant | Cold Start | Warm Latency | Throughput | Routing (10 q) |
|:------|:-------|:------|:-----------|:-------------|:-----------|:---------------|
| **vLLM Qwen2.5-3B-AWQ** | 3B | AWQ 4-bit | <1s | ~250ms | ~130 t/s | 7/10 |
| **qwen2.5-coder:7b** | 7B | Q4_K_M | 4.4s | 3.0s | 11.1 t/s | 6/10 |
| **qwen2.5:7b** | 7B | Q4_K_M | 6.3s | 2.8s | 10.9 t/s | 7/10 |
| **gpt-oss:20b** | 20B | Q4_K_M | 14.7s | 7.9s | 12.0 t/s | 8/10 |
| **nanbeige4.1-3B** 🧠 | 3.9B | Q8_0 | 295s | ~290s | 14 t/s | 0/10 |

> **Key Findings:**
> - **Enriched RULES prompt** was the main differentiator — models went from 6-8/10 to 10/10 on this test set.
> - **Freeing vLLM's 2.75 GB VRAM → 3× throughput boost** for all Ollama models (e.g., qwen2.5-coder: 11 → 35 t/s).
> - **qwen2.5-coder:7b** ⭐ chosen as production router: best warm latency (0.34s) + good throughput.
> - **nanbeige4.1-3B** 🧠 went from failing (290s cold start) to fast (0.46s) via `think=false` + `format=json` + full GPU access.
> - **gpt-oss:20b** is too slow (4.71s/query) for responsive interactive routing.
> - Accuracy = exact route-label match on the 10-query test set (calendar, gmail, system, smalltalk, news).

---

## Roadmap

Bantz is evolving toward a **GAIA-inspired intelligent platform** — not just a tool executor, but an assistant with persistent memory, observable behavior, and proactive capabilities.

### Master Plan → [#1300](https://github.com/miclaldogan/bantz/issues/1300)

**Phase A — Data Platform (current focus)**

| EPIC | What | Status |
|:-----|:-----|:-------|
| [#1288](https://github.com/miclaldogan/bantz/issues/1288) | Ingest Store — TTL cache + fingerprint dedup | Done |
| [#1290](https://github.com/miclaldogan/bantz/issues/1290) | Observability — runs, tool calls, artifacts DB | Next |
| [#1291](https://github.com/miclaldogan/bantz/issues/1291) | Policy Engine v2 — risk tiers, param editing, redaction | Planned |
| [#1297](https://github.com/miclaldogan/bantz/issues/1297) | Event Bus — async pub/sub internal messaging | Planned |
| [#1298](https://github.com/miclaldogan/bantz/issues/1298) | Graceful Degradation — circuit breaker + fallback | Planned |
| [#1289](https://github.com/miclaldogan/bantz/issues/1289) | Graph Memory — persistent cross-session context | Planned |

**Phase B — Intelligence Layer**

| EPIC | What |
|:-----|:-----|
| [#1293](https://github.com/miclaldogan/bantz/issues/1293) | Proactive Secretary — daily briefs, signals, suggestions |
| [#1295](https://github.com/miclaldogan/bantz/issues/1295) | PC Agent + Coding Agent — sandbox execution |
| [#1292](https://github.com/miclaldogan/bantz/issues/1292) | Google Suite Super-Connector — unified OAuth, Contacts/Tasks/Keep |
| [#1294](https://github.com/miclaldogan/bantz/issues/1294) | Controlled Messaging — read → draft → confirm → send |

**Phase C — Extended Capabilities**

| EPIC | What |
|:-----|:-----|
| [#1296](https://github.com/miclaldogan/bantz/issues/1296) | Music Control — Spotify/local player integration |
| [#1299](https://github.com/miclaldogan/bantz/issues/1299) | Future Skills — finance, file search, travel, health |

---

## Project Structure

```
bantz/
├── src/bantz/               # Main Python package (python3 -m bantz)
│   ├── __main__.py          # Entry point → cli.py
│   ├── cli.py               # Interactive & single-shot CLI
│   ├── server.py            # Unix socket daemon (BantzServer)
│   ├── daemon.py            # Systemd-friendly daemon wrapper
│   ├── api/                 # FastAPI REST server (port 8088)
│   │
│   ├── brain/               # Orchestrator, router, finalizer, quality gating
│   ├── llm/                 # LLM clients: Ollama + Gemini, tiered scoring
│   ├── router/              # Intent router: schemas, prompts, handlers
│   ├── tools/               # 75+ tools (calendar, gmail, browser, system…)
│   ├── data/                # Data platform: IngestStore (SQLite TTL cache)
│   │
│   ├── google/              # Google APIs: Calendar, Gmail, OAuth, Contacts
│   ├── connectors/google/   # Unified Google auth manager + Classroom
│   │
│   ├── memory/              # Session + persistent memory (SQLite)
│   ├── policy/              # Permission engine, confirmation firewall
│   ├── voice/               # ASR, TTS, wake word (optional)
│   ├── browser/             # Browser automation bridge
│   ├── i18n/                # LanguageBridge: transparent TR↔EN translation
│   └── privacy/             # PII redaction
│
├── bantz-overlay/           # Electron HUD overlay (always-on-top transparent UI)
├── bantz-extension/         # Chromium browser extension
├── bantz-browser/           # Browser companion app
│
├── skills/                  # Declarative skill definitions
├── tests/                   # Test suite (pytest + pytest-asyncio)
├── scripts/                 # Utility scripts: smoke tests, e2e, install helpers
├── config/                  # Env templates, model settings, policies
├── docs/                    # Architecture docs, setup guides
│
├── _legacy/                 # Archived: vLLM backend, old demo/bench scripts
│                            # (kept for reference, not part of active runtime)
│
└── pyproject.toml           # Package config (hatchling)
```

### How to Start

```bash
# Start the daemon (Unix socket + FastAPI on :8088)
python3 -m bantz --serve

# Single command
python3 -m bantz --once "bugün hangi toplantılarım var?"

# System check
python3 -m bantz doctor
```

---

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all unit tests
pytest tests/ -v

# Golden path E2E tests (calendar + inbox flows)
pytest tests/ -v --run-golden-path

# Regression tests (top recurring bugs)
pytest tests/ -v --run-regression

# Integration tests (requires running Ollama)
pytest tests/ -v --run-integration
```

### Test Coverage

| Area | Description |
|:-----|:------------|
| Golden Path E2E | Calendar + inbox end-to-end flows, failure modes |
| Regression Suite | Turkish anaphora, context overflow, unicode edge cases |
| JSON Repair | 58 golden tests for markdown fencing, truncation, type errors |
| Tiered Scoring | Quality gating with complexity/writing/risk scoring |
| Orchestrator | Multi-turn conversation, tool execution, error recovery |
| Confirmation Firewall | Destructive operation blocking and risk classification |
| Router Schemas | Pydantic validation, enum repair, type coercion |

---

## Contributing

We're building Bantz in the open and welcome contributions. The project is young — there's plenty of room to make an impact.

### Getting Started

```bash
git clone https://github.com/miclaldogan/bantz.git
cd bantz
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
pytest tests/ -v --tb=short
```

### Development Workflow

- All PRs target the `dev` branch
- Branch naming: `feat/123-description`, `fix/123-description`, `chore/123-description`
- Commit format: `type(scope): description` ([Conventional Commits](https://www.conventionalcommits.org/))
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide

### PR Quality Gates

Every pull request goes through automated checks:

| Check | What it does |
|:------|:-------------|
| **Ruff lint** | Style + import order (diff-based, only changed files) |
| **pytest** | Full test suite must pass |
| **Bandit SAST** | Security scan for common vulnerabilities |
| **Safety** | Dependency CVE check |
| **CodeRabbit** | AI-powered code review with project-aware context |
| **Copilot Review** | Automated review following project conventions |

---

## Documentation

| Document | Description |
|:---------|:------------|
| [docs/architecture.md](docs/architecture.md) | System architecture and pipeline flow |
| [docs/setup/google-oauth.md](docs/setup/google-oauth.md) | Google Calendar & Gmail OAuth setup |
| [docs/confirmation-firewall.md](docs/confirmation-firewall.md) | Security firewall for destructive operations |
| [docs/gemini-hybrid-orchestrator.md](docs/gemini-hybrid-orchestrator.md) | Hybrid local/cloud architecture |
| [docs/secrets-hygiene.md](docs/secrets-hygiene.md) | API key and secrets best practices |
| [docs/tool-catalog.md](docs/tool-catalog.md) | Complete tool reference (75 tools) |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](SECURITY.md) | Security policy |

---

## License

Proprietary. Copyright © 2024–2026 Mıcıl Aldoğan. All Rights Reserved.

See [LICENSE](LICENSE) for details.
