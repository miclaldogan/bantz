#!/usr/bin/env bash
# Install the Bantz vLLM watchdog as a systemd --user service.
# Usage:
#   ./scripts/systemd/install_watchdog_user_service.sh
#   BANTZ_REPO_ROOT=/path/to/Bantz ./scripts/systemd/install_watchdog_user_service.sh

set -euo pipefail

REPO_ROOT="${BANTZ_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
UNIT_SRC="$REPO_ROOT/systemd/user/bantz-vllm-watchdog.service"
UNIT_DST_DIR="$HOME/.config/systemd/user"
UNIT_DST="$UNIT_DST_DIR/bantz-vllm-watchdog.service"

mkdir -p "$UNIT_DST_DIR"

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "❌ Unit template not found: $UNIT_SRC" >&2
  exit 1
fi

# Generate a unit file with the correct WorkingDirectory and PATH.
# Keep everything else the same.
cat "$UNIT_SRC" \
  | sed "s|^WorkingDirectory=.*$|WorkingDirectory=$REPO_ROOT|" \
  | sed "s|^Environment=PATH=.*$|Environment=PATH=$REPO_ROOT/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin|" \
  > "$UNIT_DST"

chmod 644 "$UNIT_DST"

systemctl --user daemon-reload
systemctl --user enable --now bantz-vllm-watchdog.service

echo "✅ Installed: $UNIT_DST"
echo "🔎 Status: systemctl --user status bantz-vllm-watchdog.service"
echo "📜 Logs:   journalctl --user -u bantz-vllm-watchdog.service -f"
