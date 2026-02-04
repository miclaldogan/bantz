#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh (GitHub CLI) is not installed or not on PATH." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

echo "Syncing issue bodies from docs/github-issues/..."

issue_178_file="docs/github-issues/178-vllm-production-setup.md"
issue_179_file="docs/github-issues/179-llm-tiering-3b-gemini.md"

if [[ ! -f "$issue_178_file" ]]; then
  echo "ERROR: Missing $issue_178_file" >&2
  exit 1
fi
if [[ ! -f "$issue_179_file" ]]; then
  echo "ERROR: Missing $issue_179_file" >&2
  exit 1
fi

# Keep titles in sync too.
# NOTE: Issue numbers are repo-specific.

gh issue edit 178 \
  --title "vLLM Production Setup & Installation Guide" \
  --body-file "$issue_178_file"

gh issue edit 179 \
  --title "LLM Tiering (3B vLLM + Gemini quality)" \
  --body-file "$issue_179_file"

echo "Done."
