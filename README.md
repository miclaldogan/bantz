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
