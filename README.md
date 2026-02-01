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
- docs/setup/vllm.md
- docs/setup/google-oauth.md
- docs/setup/memory.md

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
