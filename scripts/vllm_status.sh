#!/usr/bin/env bash
# Convenience wrapper (repo root expects ./scripts/vllm_status.sh)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

exec "$PROJECT_ROOT/scripts/vllm/status.sh" "$@"
