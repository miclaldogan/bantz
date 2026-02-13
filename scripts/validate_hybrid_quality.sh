#!/usr/bin/env bash
# Hybrid validation runner: 3B local + optional Gemini quality
# Usage:
#   ./scripts/validate_hybrid_quality.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f scripts/validate_hybrid_quality.py ]]; then
  echo "❌ scripts/validate_hybrid_quality.py not found" >&2
  exit 1
fi

# Minimal sanity checks (do not print the key)
if [[ -z "${BANTZ_VLLM_URL:-}" ]]; then
  export BANTZ_VLLM_URL="http://127.0.0.1:8001"
fi
if [[ -z "${BANTZ_VLLM_MODEL:-}" ]]; then
  export BANTZ_VLLM_MODEL="auto"
fi

export BANTZ_TIERED_MODE="${BANTZ_TIERED_MODE:-1}"
export BANTZ_LLM_TIER="${BANTZ_LLM_TIER:-auto}"
export BANTZ_LLM_METRICS="${BANTZ_LLM_METRICS:-1}"
export BANTZ_TIERED_METRICS="${BANTZ_TIERED_METRICS:-1}"

if [[ "${QUALITY_PROVIDER:-}" == "gemini" || "${BANTZ_QUALITY_PROVIDER:-}" == "gemini" ]]; then
  if [[ "${BANTZ_CLOUD_MODE:-local}" != "cloud" && "${CLOUD_MODE:-local}" != "cloud" ]]; then
    echo "ℹ️ QUALITY_PROVIDER=gemini set, but cloud mode is not enabled. Set BANTZ_CLOUD_MODE=cloud." >&2
  fi
  if [[ -z "${GEMINI_API_KEY:-${GOOGLE_API_KEY:-${BANTZ_GEMINI_API_KEY:-}}}" ]]; then
    echo "ℹ️ Gemini selected but API key is missing. Export GEMINI_API_KEY=..." >&2
  fi
fi

python3 scripts/validate_hybrid_quality.py
