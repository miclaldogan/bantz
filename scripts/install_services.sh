#!/usr/bin/env bash
# Install BANTZ systemd user services (Issue #288).
#
# Usage:
#   bash scripts/install_services.sh [BANTZ_ROOT]
#
# If BANTZ_ROOT is omitted, uses the parent directory of this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BANTZ_ROOT="${1:-$(dirname "$SCRIPT_DIR")}"
SERVICE_SRC="$BANTZ_ROOT/systemd/user"
SERVICE_DST="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/bantz"

echo "=== BANTZ Service Installer ==="
echo "BANTZ_ROOT: $BANTZ_ROOT"
echo "Service dest: $SERVICE_DST"
echo ""

# ── Create directories ────────────────────────────────────────────
mkdir -p "$SERVICE_DST" "$CONFIG_DIR"

# ── Copy env template if not exists ───────────────────────────────
if [[ ! -f "$CONFIG_DIR/env" ]]; then
    cp "$BANTZ_ROOT/config/bantz-env.example" "$CONFIG_DIR/env"
    echo "✓ Created $CONFIG_DIR/env (edit with your settings)"
else
    echo "• $CONFIG_DIR/env already exists (skipped)"
fi

# ── Install service files (replace %h placeholders) ──────────────
for f in bantz-core.service bantz-voice.service bantz.target \
         bantz-voice-watchdog.service bantz-vllm-watchdog.service \
         bantz-resume.service; do
    src="$SERVICE_SRC/$f"
    dst="$SERVICE_DST/$f"
    if [[ -f "$src" ]]; then
        sed "s|%h/Desktop/Bantz|$BANTZ_ROOT|g" "$src" > "$dst"
        echo "✓ Installed $f"
    else
        echo "• $f not found (skipped)"
    fi
done

# ── Reload systemd ───────────────────────────────────────────────
systemctl --user daemon-reload
echo ""
echo "✓ systemd reloaded"

# ── Enable services ──────────────────────────────────────────────
echo ""
echo "To enable on boot:"
echo "  systemctl --user enable bantz.target"
echo ""
echo "To start now:"
echo "  systemctl --user start bantz.target"
echo ""
echo "To check status:"
echo "  systemctl --user status bantz-core.service bantz-voice.service"
