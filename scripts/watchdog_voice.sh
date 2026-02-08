#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Voice Watchdog — Issue #301
#
# Monitors the voice pipeline heartbeat file and restarts the
# bantz-voice systemd service when the heartbeat goes stale.
#
# Features:
#   - Heartbeat staleness detection (default 30s)
#   - Cooldown between restarts (default 60s)
#   - Exponential back-off on repeated restarts
#   - Log output for troubleshooting
#
# Usage:
#   ./scripts/watchdog_voice.sh                  # defaults
#   MAX_AGE=60 COOLDOWN=120 ./scripts/watchdog_voice.sh
#   BANTZ_VOICE_SERVICE=bantz-voice-dev ./scripts/watchdog_voice.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
HEARTBEAT="${BANTZ_HEARTBEAT_FILE:-$HOME/.cache/bantz/voice_heartbeat}"
MAX_AGE="${MAX_AGE:-30}"
COOLDOWN="${COOLDOWN:-60}"
CHECK_INTERVAL="${CHECK_INTERVAL:-10}"
SERVICE="${BANTZ_VOICE_SERVICE:-bantz-voice}"
MAX_BACKOFF="${MAX_BACKOFF:-600}"  # 10 min cap

# ── State ──────────────────────────────────────────────────────
LAST_RESTART=0
CONSECUTIVE_RESTARTS=0
CURRENT_COOLDOWN="$COOLDOWN"

log() {
    echo "[watchdog][$(date +%Y-%m-%dT%H:%M:%S)] $*"
}

restart_service() {
    local now
    now=$(date +%s)
    local elapsed=$((now - LAST_RESTART))

    if [ "$elapsed" -lt "$CURRENT_COOLDOWN" ]; then
        log "Cooldown active (${elapsed}s/${CURRENT_COOLDOWN}s) — skipping restart"
        return 1
    fi

    log "⚠ Voice service stale — restarting $SERVICE (consecutive=$CONSECUTIVE_RESTARTS)"
    if systemctl --user restart "$SERVICE" 2>/dev/null; then
        log "✅ Service $SERVICE restarted successfully"
    else
        log "❌ Service restart failed — is $SERVICE installed?"
    fi

    LAST_RESTART="$now"
    CONSECUTIVE_RESTARTS=$((CONSECUTIVE_RESTARTS + 1))

    # Exponential back-off: cooldown doubles on each consecutive restart
    CURRENT_COOLDOWN=$((COOLDOWN * (2 ** (CONSECUTIVE_RESTARTS - 1))))
    if [ "$CURRENT_COOLDOWN" -gt "$MAX_BACKOFF" ]; then
        CURRENT_COOLDOWN="$MAX_BACKOFF"
    fi
    log "Next cooldown: ${CURRENT_COOLDOWN}s"
    return 0
}

check_heartbeat() {
    if [ ! -f "$HEARTBEAT" ]; then
        log "Heartbeat file not found: $HEARTBEAT"
        return 1  # stale
    fi

    local hb_time
    hb_time=$(cat "$HEARTBEAT" 2>/dev/null || echo "0")
    # Handle floating point timestamps by truncating
    hb_time="${hb_time%%.*}"

    local now
    now=$(date +%s)
    local age=$((now - hb_time))

    if [ "$age" -gt "$MAX_AGE" ]; then
        log "Heartbeat stale: age=${age}s > max=${MAX_AGE}s"
        return 1  # stale
    fi

    # Heartbeat alive — reset consecutive counter
    if [ "$CONSECUTIVE_RESTARTS" -gt 0 ]; then
        log "Heartbeat alive — resetting back-off (was $CONSECUTIVE_RESTARTS consecutive restarts)"
        CONSECUTIVE_RESTARTS=0
        CURRENT_COOLDOWN="$COOLDOWN"
    fi

    return 0  # alive
}

# ── Main loop ──────────────────────────────────────────────────
log "Voice watchdog started"
log "  heartbeat: $HEARTBEAT"
log "  max_age:   ${MAX_AGE}s"
log "  cooldown:  ${COOLDOWN}s"
log "  service:   $SERVICE"
log "  interval:  ${CHECK_INTERVAL}s"

while true; do
    if ! check_heartbeat; then
        restart_service || true
    fi
    sleep "$CHECK_INTERVAL"
done
