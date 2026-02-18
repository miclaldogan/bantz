#!/bin/bash
# =============================================================================
# Jarvis Startup Script
# =============================================================================
#
# Tüm Jarvis sistemini tek komutla başlatır:
#   ./scripts/jarvis.sh start
#
# Kullanım:
#   ./scripts/jarvis.sh start      - Sistemi başlat
#   ./scripts/jarvis.sh stop       - Sistemi durdur
#   ./scripts/jarvis.sh status     - Durum göster
#   ./scripts/jarvis.sh restart    - Yeniden başlat
#   ./scripts/jarvis.sh logs       - Logları göster
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${PROJECT_DIR}/.venv"
PID_FILE="/tmp/jarvis.pid"
LOG_FILE="${PROJECT_DIR}/jarvis.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

activate_venv() {
    if [[ -f "${VENV_DIR}/bin/activate" ]]; then
        source "${VENV_DIR}/bin/activate"
    elif [[ -f "${PROJECT_DIR}/venv/bin/activate" ]]; then
        source "${PROJECT_DIR}/venv/bin/activate"
    fi
}

check_running() {
    if [[ -f "$PID_FILE" ]]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        else
            rm -f "$PID_FILE"
            return 1
        fi
    fi
    return 1
}

# =============================================================================
# Commands
# =============================================================================

cmd_start() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                   🚀 Jarvis Başlatılıyor                     ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    if check_running; then
        log_warning "Jarvis zaten çalışıyor (PID: $(cat $PID_FILE))"
        return 0
    fi

    cd "$PROJECT_DIR"
    activate_venv

    # Check dependencies
    log_info "Bağımlılıklar kontrol ediliyor..."

    # Check vLLM (OpenAI-compatible)
    VLLM_URL="${BANTZ_VLLM_BASE_URL:-http://127.0.0.1:8001}"
    if ! curl -s "${VLLM_URL}/v1/models" > /dev/null 2>&1; then
        log_warning "vLLM çalışmıyor veya erişilemiyor: ${VLLM_URL}"
        log_warning "Başlat (örnek): python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-3B-Instruct-AWQ --port 8001"
    else
        log_success "vLLM bağlı (${VLLM_URL})"
    fi

    # Check audio
    if ! python3 -c "import sounddevice" 2>/dev/null; then
        log_warning "sounddevice yüklü değil: pip install sounddevice"
    fi

    # Start Jarvis
    log_info "Jarvis başlatılıyor..."
    
    if [[ "$1" == "--foreground" ]] || [[ "$1" == "-f" ]]; then
        # Foreground mode
        python3 -m bantz.core.orchestrator "$@"
    else
        # Background mode
        nohup python3 -m bantz.core.orchestrator "$@" > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 2
        
        if check_running; then
            log_success "Jarvis başlatıldı (PID: $(cat $PID_FILE))"
            log_info "Log: tail -f $LOG_FILE"
        else
            log_error "Jarvis başlatılamadı! Log: cat $LOG_FILE"
            return 1
        fi
    fi
}

cmd_stop() {
    echo ""
    log_info "Jarvis durduruluyor..."

    if ! check_running; then
        log_warning "Jarvis zaten çalışmıyor"
        return 0
    fi

    pid=$(cat "$PID_FILE")
    
    # Graceful shutdown
    kill -SIGTERM "$pid" 2>/dev/null || true
    
    # Wait for shutdown
    for i in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            log_success "Jarvis durduruldu"
            return 0
        fi
        sleep 0.5
    done

    # Force kill if still running
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    log_warning "Jarvis zorla durduruldu"
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start "$@"
}

cmd_status() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                      📊 Jarvis Durumu                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # Jarvis process
    if check_running; then
        pid=$(cat "$PID_FILE")
        log_success "Jarvis çalışıyor (PID: $pid)"
        
        # Show uptime
        if command -v ps > /dev/null; then
            uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
            echo "         Uptime: $uptime"
        fi
    else
        log_error "Jarvis çalışmıyor"
    fi

    echo ""

    # vLLM
    VLLM_URL="${BANTZ_VLLM_BASE_URL:-http://127.0.0.1:8001}"
    if curl -s "${VLLM_URL}/v1/models" > /dev/null 2>&1; then
        log_success "vLLM bağlı (${VLLM_URL})"
    else
        log_error "vLLM bağlı değil (${VLLM_URL})"
    fi

    # Daemon socket
    if [[ -S "/tmp/bantz_sessions/default.sock" ]]; then
        log_success "Daemon socket var"
    else
        log_warning "Daemon socket yok"
    fi

    # Overlay socket
    if [[ -S "/tmp/bantz/overlay.sock" ]]; then
        log_success "Overlay socket var"
    else
        log_warning "Overlay socket yok"
    fi

    echo ""
}

cmd_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        tail -f "$LOG_FILE"
    else
        log_warning "Log dosyası yok: $LOG_FILE"
    fi
}

cmd_help() {
    echo ""
    echo "Kullanım: $0 <komut> [seçenekler]"
    echo ""
    echo "Komutlar:"
    echo "  start      Jarvis'i başlat"
    echo "  stop       Jarvis'i durdur"
    echo "  restart    Jarvis'i yeniden başlat"
    echo "  status     Sistem durumunu göster"
    echo "  logs       Logları izle"
    echo "  help       Bu yardımı göster"
    echo ""
    echo "Seçenekler:"
    echo "  -f, --foreground   Ön planda çalıştır"
    echo "  --no-tts           TTS'i kapat"
    echo "  --no-overlay       Overlay'i kapat"
    echo "  --no-wake-word     Wake word'ü kapat"
    echo ""
    echo "Örnekler:"
    echo "  $0 start                    # Normal başlat"
    echo "  $0 start -f                 # Ön planda başlat"
    echo "  $0 start --no-tts           # TTS olmadan başlat"
    echo "  $0 status                   # Durumu göster"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

case "${1:-help}" in
    start)
        shift
        cmd_start "$@"
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        shift
        cmd_restart "$@"
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    help|--help|-h)
        cmd_help
        ;;
    *)
        log_error "Bilinmeyen komut: $1"
        cmd_help
        exit 1
        ;;
esac
