<p align="center">
  <img src="docs/bantz.png" alt="Bantz" width="750" />
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

| Area | What it does | Tools |
|:-----|:-------------|:------|
| **Calendar** | Create, update, cancel events; find free slots; natural date parsing | Google Calendar API |
| **Email** | List inbox, read, draft, reply, send with confirmation | Gmail API |
| **Browser** | Open URLs, extract page content, tab management | Chromium extension + WebSocket |
| **System** | Screenshot, clipboard, notifications, app launch, disk info | D-Bus + native |
| **Terminal** | Execute commands in a sandboxed environment | Subprocess with guardrails |
| **Code** | Code generation, file operations, project scaffolding | Local filesystem |
| **Contacts** | Lookup, manage Google Contacts | Google People API |

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
# Health check
bantz doctor

# Interactive mode
bantz --serve

# Single command
bantz --once "what meetings do I have today?"
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
┌─────────────────────────────────────────────────────────────┐
│                         BANTZ                               │
│                                                             │
│  ┌─────────┐   ┌─────────┐   ┌──────────┐                 │
│  │  CLI    │   │ Browser │   │  Voice   │                  │
│  │ Client  │   │Extension│   │  (opt.)  │                  │
│  └────┬────┘   └────┬────┘   └────┬─────┘                  │
│       └──────────────┼────────────┘                         │
│                      ▼                                      │
│             ┌────────────────┐                              │
│             │  BantzServer   │  Unix socket daemon           │
│             └───────┬────────┘                              │
│                     ▼                                       │
│  ┌────────────────────────────────────────────────────┐     │
│  │              Brain Pipeline                        │     │
│  │                                                    │     │
│  │  PreRouter ──► LLM Router ──► Tool Executor        │     │
│  │  (keyword     (Ollama,        (75 tools,            │     │
│  │   bypass)      ~50ms)          risk-gated)          │     │
│  │                    │                  │              │     │
│  │                    ▼                  ▼              │     │
│  │              Quality Gate ──► Tiered Finalizer       │     │
│  │              (complexity ×    Fast: local LLM        │     │
│  │               writing ×      Quality: Gemini         │     │
│  │               risk score)    Draft: template          │     │
│  └────────────────────────────────────────────────────┘     │
│                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐         │
│  │Calendar │ │ Gmail   │ │  Web    │ │ System  │         │
│  │ Tools   │ │ Tools   │ │ Tools   │ │ Tools   │         │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘         │
└─────────────────────────────────────────────────────────────┘
        │                                      │
        ▼                                      ▼
  ┌───────────┐                         ┌───────────┐
  │  Ollama   │  qwen2.5-coder:7b      │  Gemini   │  2.0 Flash
  │  (local)  │  router + fast-tier     │  (cloud)  │  quality-tier
  └───────────┘                         └───────────┘
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
├── src/bantz/                 # Main package
│   ├── brain/                 # Orchestrator, router, finalizer, quality gating
│   ├── llm/                   # LLM clients (Ollama, Gemini), tiered scoring
│   ├── router/                # Intent router: schemas, prompts, handlers
│   ├── tools/                 # 75 tools across 13 categories
│   ├── data/                  # Data platform (Ingest Store, evolving)
│   ├── google/                # Calendar, Gmail, OAuth
│   ├── memory/                # Session + persistent memory (SQLite)
│   ├── policy/                # Permission engine, confirmation firewall
│   ├── voice/                 # ASR, TTS, wake word (optional)
│   ├── browser/               # Browser automation bridge
│   ├── i18n/                  # LanguageBridge translation layer
│   ├── privacy/               # PII redaction
│   ├── server.py              # Unix socket daemon
│   └── ...                    # 40+ subsystem modules
├── tests/                     # ~10,000 tests across 370+ test files
├── scripts/                   # CLI tools, benchmarks, demos
├── config/                    # Environment templates, model settings, policies
├── bantz-extension/           # Chromium browser extension
├── skills/                    # Declarative skill definitions
├── docs/                      # Architecture docs, setup guides
├── .github/                   # CI workflows, PR review config
└── pyproject.toml             # Package config (hatchling)
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
