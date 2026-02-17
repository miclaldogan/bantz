#!/usr/bin/env bash
# Install BANTZ Overlay systemd user service and XDG autostart entry.
#
# Usage:
#   bash scripts/install_overlay.sh [BANTZ_ROOT]
#
# If BANTZ_ROOT is omitted, uses the parent directory of this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BANTZ_ROOT="${1:-$(dirname "$SCRIPT_DIR")}"
SERVICE_SRC="$BANTZ_ROOT/systemd/user"
SERVICE_DST="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"
OVERLAY_DIR="$BANTZ_ROOT/bantz-overlay"

echo "=== BANTZ Overlay Installer ==="
echo "BANTZ_ROOT : $BANTZ_ROOT"
echo "Overlay dir: $OVERLAY_DIR"
echo ""

# ── Preflight checks ─────────────────────────────────────────────
if ! command -v electron &>/dev/null; then
    echo "⚠  electron not found in PATH."
    echo "   Install with: npm install -g electron"
    echo "   Or: sudo apt install electron (Debian/Ubuntu)"
    echo ""
fi

if [[ ! -f "$OVERLAY_DIR/src/main/main.js" ]]; then
    echo "✗ Overlay entry point not found: $OVERLAY_DIR/src/main/main.js"
    exit 1
fi

# ── Create directories ───────────────────────────────────────────
mkdir -p "$SERVICE_DST" "$AUTOSTART_DIR"

# ── Install systemd user service ─────────────────────────────────
SVC_FILE="bantz-overlay.service"
SVC_SRC="$SERVICE_SRC/$SVC_FILE"
SVC_DST="$SERVICE_DST/$SVC_FILE"

if [[ -f "$SVC_SRC" ]]; then
    sed "s|%h/Desktop/Bantz|$BANTZ_ROOT|g" "$SVC_SRC" > "$SVC_DST"
    echo "✓ Installed $SVC_FILE → $SVC_DST"
else
    echo "✗ Service file not found: $SVC_SRC"
    exit 1
fi

# ── Update bantz.target to include overlay ────────────────────────
TARGET_DST="$SERVICE_DST/bantz.target"
if [[ -f "$TARGET_DST" ]]; then
    if ! grep -q "bantz-overlay.service" "$TARGET_DST"; then
        sed -i 's/^Wants=\(.*\)/Wants=\1 bantz-overlay.service/' "$TARGET_DST"
        echo "✓ Added bantz-overlay.service to bantz.target"
    else
        echo "• bantz.target already includes overlay (skipped)"
    fi
else
    echo "• bantz.target not found (run install_services.sh first)"
fi

# ── Install XDG autostart desktop entry ──────────────────────────
DESKTOP_SRC="$BANTZ_ROOT/config/bantz-overlay.desktop"
DESKTOP_DST="$AUTOSTART_DIR/bantz-overlay.desktop"

if [[ -f "$DESKTOP_SRC" ]]; then
    # Replace /opt/bantz/overlay with actual path
    sed "s|/opt/bantz/overlay/main.js|$OVERLAY_DIR/src/main/main.js|g" \
        "$DESKTOP_SRC" > "$DESKTOP_DST"
    echo "✓ Installed autostart → $DESKTOP_DST"
else
    echo "⚠ Desktop file not found: $DESKTOP_SRC (skipped)"
fi

# ── Reload systemd ───────────────────────────────────────────────
systemctl --user daemon-reload
echo ""
echo "✓ systemd reloaded"

# ── Usage instructions ───────────────────────────────────────────
echo ""
echo "Usage:"
echo "  # Enable overlay to start with daemon:"
echo "  systemctl --user enable bantz-overlay.service"
echo ""
echo "  # Start overlay now:"
echo "  systemctl --user start bantz-overlay.service"
echo ""
echo "  # Or start the full stack (includes overlay):"
echo "  systemctl --user start bantz.target"
echo ""
echo "  # Check status:"
echo "  systemctl --user status bantz-overlay.service"
echo ""
echo "  # View logs:"
echo "  journalctl --user -u bantz-overlay.service -f"
echo ""
echo "For non-systemd setups, the XDG autostart entry at"
echo "  $DESKTOP_DST"
echo "will start the overlay on login."
