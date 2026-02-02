# Bantz

Bantz is a local-first assistant for Linux (CLI + voice + optional browser extension).

- **LLM backend:** vLLM (OpenAI-compatible API) only
- **Google integrations:** OAuth2 (Calendar is implemented; Gmail token flow supported)

## Quickstart (vLLM)

### 1) Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[llm]"
```

### 2) Start vLLM

Recommended helper scripts:

```bash
./scripts/vllm/start_3b.sh   # port 8001 (fast)
./scripts/vllm/start_7b.sh   # port 8002 (quality)
```

### 3) Point Bantz to vLLM

```bash
export BANTZ_VLLM_URL="http://127.0.0.1:8001"
export BANTZ_VLLM_MODEL="Qwen/Qwen2.5-3B-Instruct-AWQ"
```

### 4) Run

```bash
bantz --once "instagram aç"
# or
bantz --serve
```

Voice mode (PTT):

```bash
bantz --voice --piper-model /path/to/tr.onnx --asr-allow-download
```

More details: docs/setup/vllm.md

## Project docs

- docs/acceptance-tests.md
- docs/jarvis-roadmap-v2.md
- docs/gemini-hybrid-orchestrator.md (Issue #134, #135 - Gemini Hybrid)
- docs/setup/vllm.md
- docs/setup/google-oauth.md
- docs/setup/memory.md
- docs/setup/docker-vllm.md
- docs/setup/google-vision.md

## Hybrid Orchestrator Architecture (Issues #134, #135, #157)

Bantz supports flexible hybrid LLM architectures for optimal quality/latency balance:

### Option 1: Gemini Hybrid (Issue #134, #135)
**3B Router + Gemini Finalizer**
- Phase 1: Local 3B router (fast planning ~40ms)
- Phase 2: Tool execution
- Phase 3: Gemini finalizer (quality responses)
- **Use case**: Best quality, cloud dependency acceptable

```python
from bantz.brain.gemini_hybrid_orchestrator import create_gemini_hybrid_orchestrator
from bantz.llm.vllm_openai_client import VLLMOpenAIClient

router = VLLMOpenAIClient(
    base_url="http://localhost:8001",
    model="Qwen/Qwen2.5-3B-Instruct"
)
orchestrator = create_gemini_hybrid_orchestrator(
    router_client=router,
    gemini_api_key="YOUR_API_KEY"
)
```

### Option 2: Flexible vLLM Hybrid (Issue #157)
**3B Router + 7B vLLM Finalizer (with fallback)**
- Phase 1: 3B router (vLLM port 8001) - fast planning
- Phase 2: Tool execution
- Phase 3: 7B finalizer (vLLM port 8002) - quality responses
- **Fallback**: If 7B down, uses 3B router response
- **Use case**: Fully local, privacy-preserving, graceful degradation

```python
from bantz.brain.flexible_hybrid_orchestrator import create_flexible_hybrid_orchestrator
from bantz.llm.vllm_openai_client import VLLMOpenAIClient

router = VLLMOpenAIClient(base_url="http://localhost:8001", model="Qwen/Qwen2.5-3B-Instruct")
finalizer = VLLMOpenAIClient(base_url="http://localhost:8002", model="Qwen/Qwen2.5-7B-Instruct")

orchestrator = create_flexible_hybrid_orchestrator(
    router_client=router,
    finalizer_client=finalizer,
)
```

### Benchmark (Issue #157)

Compare 3B-only vs 3B+7B hybrid quality:

```bash
# Start both servers
./scripts/vllm/start_3b.sh   # port 8001
./scripts/vllm/start_7b.sh   # port 8002

# Run benchmark
python scripts/bench_hybrid_quality.py --num-tests 30
# Results: artifacts/results/bench_hybrid_quality.json
```

### Architecture Benefits
- **Low latency**: 3B router for fast planning (~40ms)
- **High quality**: 7B/Gemini for natural responses
- **Resilience**: Fallback to 3B if finalizer unavailable
- **Flexible**: Choose Gemini (cloud) or 7B (local)
- **Target TTFT**: <500ms total (planning 40ms + execution + finalize 100ms)

## TTFT Monitoring & Optimization (Issue #158)

### Real-Time TTFT Tracking

Bantz provides comprehensive Time-To-First-Token (TTFT) monitoring for exceptional UX:

```bash
# Interactive demo with real-time TTFT display
python scripts/demo_ttft_realtime.py --mode interactive

# Demo mode with predefined prompts
python scripts/demo_ttft_realtime.py --mode demo

# Benchmark TTFT performance
python scripts/bench_ttft_monitoring.py --num-tests 30
```

### Features
- **Streaming support**: Token-by-token output with real-time TTFT measurement
- **Statistical tracking**: p50, p95, p99 percentiles
- **Threshold enforcement**: Router p95 < 300ms, Finalizer p95 < 500ms
- **Alert system**: Automatic warnings on threshold violations
- **Color-coded UI**: Green (<300ms), Yellow (300-500ms), Red (>500ms)
- **Export reports**: JSON output with full statistics

### Example

```python
from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm.ttft_monitor import TTFTMonitor

# Create client with TTFT tracking
client = VLLMOpenAIClient(
    base_url="http://localhost:8001",
    track_ttft=True,
    ttft_phase="router",
)

# Stream with TTFT measurement
for chunk in client.chat_stream(messages):
    if chunk.is_first_token:
        print(f"[THINKING] (TTFT: {chunk.ttft_ms}ms)")
    print(chunk.content, end='', flush=True)

# Get statistics
monitor = TTFTMonitor.get_instance()
stats = monitor.get_statistics("router")
print(f"Router p95: {stats.p95_ms}ms")
```

### Performance Targets
- **Router (3B)**: p95 < 300ms (typical: ~40-50ms ✅)
- **Finalizer (7B)**: p95 < 500ms (typical: ~100-150ms ✅)
- **Total latency**: <500ms for "Jarvis feel" UX

## JSON Schema Validation (Issue #156)

Bantz uses strict Pydantic schemas for LLM output validation:

### Key Features
- **Enum enforcement**: route ∈ {calendar, smalltalk, unknown}
- **Type safety**: tool_plan must be list[str] (not string)
- **Turkish validation**: confirmation_prompt must be Turkish
- **Auto-repair**: 99%+ enum conformance with repair layer
- **Statistics**: Track repair rates (<5% target)

### Example

```python
from bantz.router.schemas import validate_router_output
from bantz.llm.json_repair import validate_and_repair_json

# LLM output with mistakes
raw = '{"route": "create_meeting", "tool_plan": "create_event", ...}'

# Automatic repair + validation
schema, error = validate_and_repair_json(raw)
assert schema.route == "calendar"  # Repaired: create_meeting → calendar
assert schema.tool_plan == ["create_event"]  # Repaired: string → list
```

### Files
- `src/bantz/router/schemas.py`: Strict Pydantic schemas
- `src/bantz/llm/json_repair.py`: JSON repair layer with stats
- `src/bantz/router/prompts.py`: Enhanced Turkish prompts with examples
- `tests/test_json_validation.py`: 41 comprehensive tests

### Acceptance Criteria
- ✅ 100% JSON parse success (with repair layer)
- ✅ 99%+ enum conformance (route & intent)
- ✅ <5% repair rate (most outputs already correct)
- ✅ Turkish confirmation prompts enforced

## Confirmation Firewall (Issue #160)

### Security Layer for Destructive Operations

Bantz implements a **confirmation firewall** that prevents accidental execution of dangerous operations:

#### Key Features
- **Risk Classification**: All tools classified as SAFE/MODERATE/DESTRUCTIVE
- **LLM Cannot Override**: Even if LLM forgets, DESTRUCTIVE tools require confirmation
- **Audit Logging**: Complete trail of all tool executions with risk levels
- **User Control**: Destructive operations need explicit user approval

#### Risk Levels

**🟢 SAFE** (Read-only, no side effects)
```
web.search, calendar.list_events, file.read, vision.screenshot
```

**🟡 MODERATE** (Reversible state changes)
```
calendar.create_event, notification.send, browser.open, email.send
```

**🔴 DESTRUCTIVE** (Requires confirmation)
```
calendar.delete_event, file.delete, payment.submit, system.shutdown
```

#### Example: Firewall in Action

```python
from bantz.tools.metadata import requires_confirmation, is_destructive

# LLM output with missing confirmation
llm_output = {
    "tool_plan": ["calendar.delete_event"],
    "requires_confirmation": False,  # ❌ LLM forgot!
}

# Firewall overrides
if is_destructive("calendar.delete_event"):
    needs_confirmation = True  # ✅ Enforced by firewall
    prompt = "Delete calendar event 'evt123'? This cannot be undone."
```

#### Audit Trail

All tool executions logged to `artifacts/logs/bantz.log.jsonl`:

```jsonl
{
  "event_type": "tool_execution",
  "tool_name": "calendar.delete_event",
  "risk_level": "destructive",
  "success": true,
  "confirmed": true,
  "params": {"event_id": "evt123"}
}
```

**Full docs:** [docs/confirmation-firewall.md](docs/confirmation-firewall.md)

**Tests:** 25 comprehensive tests in `tests/test_confirmation_firewall.py`

## Benchmark Suite (Issue #161)

### Comprehensive Performance & Quality Testing

Bantz includes a full benchmark suite for comparing LLM modes and tracking regression:

#### Test Scenarios
- **50+ real-world test cases** across 3 domains:
  - Calendar (30 cases): create/query/modify/cancel events, Turkish prompts
  - Chat (10 cases): smalltalk, memory, context tracking
  - Browser (10 cases): search, navigation, multi-step flows

#### Benchmark Modes
- **3B-only**: Single Qwen 2.5 3B for all tasks (fast, lower quality)
- **Hybrid**: 3B router + 7B finalizer (balanced quality/latency)
- **Both**: Compare both modes side-by-side

#### Metrics Tracked
- **Accuracy**: Route, intent, tools correctness
- **Performance**: TTFT (Time to First Token) p50/p95/p99, total latency
- **Token usage**: Input/output counts, avg per test case

#### Run Benchmarks

```bash
# Run both modes and compare
python scripts/bench_hybrid_vs_3b_only.py --mode both

# 3B-only mode
python scripts/bench_hybrid_vs_3b_only.py --mode 3b_only

# Hybrid mode (3B router + 7B finalizer)
python scripts/bench_hybrid_vs_3b_only.py --mode hybrid

# Generate markdown report
python scripts/generate_benchmark_report.py
cat artifacts/results/BENCHMARK_REPORT.md
```

#### CI Regression Tests

```bash
# Run regression tests (requires benchmark results)
pytest tests/test_benchmark_regression.py -v

# Only regression tests
pytest -m regression
```

**Thresholds:**
- TTFT p95 < 400ms (router)
- JSON validity > 95%
- Overall accuracy > 85%
- Route accuracy > 90%

**Files:**
- `tests/scenarios/*.json`: Test case definitions
- `scripts/bench_hybrid_vs_3b_only.py`: Benchmark runner
- `scripts/generate_benchmark_report.py`: Report generator
- `tests/test_benchmark_regression.py`: CI regression tests

## Google OAuth (Calendar/Gmail)

### 1) Install Calendar deps

```bash
pip install -e ".[calendar]"
```

### 2) Put your OAuth client secret

Default path:

- `~/.config/bantz/google/client_secret.json`

(Or set `BANTZ_GOOGLE_CLIENT_SECRET`.)

### 3) Mint tokens via CLI

```bash
bantz google env

# Calendar token
bantz google auth calendar --write
bantz google calendar list --max-results 10

# Gmail token (optional)
export BANTZ_GOOGLE_GMAIL_TOKEN_PATH="$HOME/.config/bantz/google/gmail_token.json"
bantz google auth gmail --scope readonly
```

More details: docs/setup/google-oauth.md

## Notes

- If you already have a vLLM server elsewhere, override with `BANTZ_VLLM_URL` or `bantz --vllm-url ...`.
- This repo intentionally has **no Ollama support**.

## License

See LICENSE (proprietary).
