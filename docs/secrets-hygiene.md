# Secrets hygiene (Issue #216)

Goal: Prevent accidental leakage of API keys, OAuth tokens, and credential paths into logs, CLI output, and shell history.

## Recommended ways to set secrets

### 1) `.env` (local dev)

Create a local `.env` file that is **not committed** (add to `.gitignore`):

- Put only environment variables (no quotes needed unless your shell requires it):

```
BANTZ_CLOUD_MODE=cloud
QUALITY_PROVIDER=gemini
GEMINI_API_KEY=...your key...
BANTZ_GEMINI_MODEL=gemini-1.5-flash
```

Load it with one of:

- `direnv` (recommended):
  - `.envrc`:
    - `dotenv`
  - Run: `direnv allow`

### 2) `systemd` user service (Linux)

Use an EnvironmentFile so secrets don’t end up in shell history.

- Example: `~/.config/bantz/bantz.env`

```
GEMINI_API_KEY=...your key...
QUALITY_PROVIDER=gemini
BANTZ_CLOUD_MODE=cloud
```

- In your service unit:
  - `EnvironmentFile=%h/.config/bantz/bantz.env`

### 3) Secret Manager (production)

Use your platform’s secret manager to inject env vars at runtime.

- GCP Secret Manager (conceptual example):
  - Store `GEMINI_API_KEY` as a secret
  - Inject it into the service environment at startup (Cloud Run / GCE / Kubernetes)

## What BANTZ does now

- CLI `bantz google env` prints only **presence booleans** for secrets, and masks credential paths.
- Missing-file errors for Google OAuth / service-account credentials mask full paths.
- Use `BANTZ_LLM_METRICS=1` for LLM call metrics; it should not print keys.

## What to avoid

- Don’t run commands like `GEMINI_API_KEY=... bantz ...` (shell history risk)
- Don’t paste tokens/keys into logs/issues
