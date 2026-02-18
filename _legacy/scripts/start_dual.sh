#!/usr/bin/env bash
# Convenience wrapper (repo root expects ./scripts/start_dual.sh)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

exec "$PROJECT_ROOT/scripts/vllm/start_dual.sh" "$@"
