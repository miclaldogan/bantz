#!/usr/bin/env bash
# Startup script for both vLLM servers with NVIDIA driver fix
# Usage: ./scripts/vllm/start_dual.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT"

echo "🔧 vLLM Dual Server Startup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check GPU
echo ""
echo "📊 GPU Kontrolü:"
if ! command -v nvidia-smi &> /dev/null; then
    echo "❌ nvidia-smi bulunamadı. NVIDIA driver yüklü mü?"
    exit 1
fi

# Try to get GPU info (may fail due to driver mismatch)
GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 || echo "Driver issue")
if [[ "$GPU_INFO" == *"Driver"* ]] || [[ "$GPU_INFO" == *"mismatch"* ]]; then
    echo "⚠️  NVIDIA Driver/Library version mismatch detected"
    echo "   Sunucular çalışabilir ama sistem yeniden başlatma önerilir"
    echo "   Komut: sudo reboot"
else
    echo "✅ $GPU_INFO"
fi

# Kill existing servers
echo ""
echo "🛑 Mevcut vLLM sunucuları kapatılıyor..."
pkill -f "vllm.entrypoints.openai.api_server" || true
sleep 3

LOG_DIR="${BANTZ_VLLM_LOG_DIR:-artifacts/logs/vllm}"
mkdir -p "$LOG_DIR"

PYTHON_BIN="${BANTZ_VLLM_PYTHON:-python3}"
if ! "$PYTHON_BIN" -c "import vllm" >/dev/null 2>&1; then
    echo "❌ vLLM import edilemedi ($PYTHON_BIN). Önce kurun: pip install vllm" >&2
    exit 1
fi

echo ""
echo "🚀 3B Model Başlatılıyor (Port 8001)..."
echo "   Model: ${BANTZ_VLLM_3B_MODEL:-Qwen/Qwen2.5-3B-Instruct-AWQ}"
echo "   (Dual defaults: gpu_util=${BANTZ_VLLM_3B_GPU_UTIL:-0.45}, max_len=${BANTZ_VLLM_3B_MAX_MODEL_LEN:-1024})"

export BANTZ_VLLM_DUAL_MODE=1
./scripts/vllm/start_3b.sh

echo ""
echo "🚀 7B Model Başlatılıyor (Port 8002)..."
echo "   Model: ${BANTZ_VLLM_7B_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
echo "   (Dual defaults: gpu_util=${BANTZ_VLLM_7B_GPU_UTIL:-0.55}, max_len=${BANTZ_VLLM_7B_MAX_MODEL_LEN:-1536})"

./scripts/vllm/start_7b.sh

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Kurulum Tamamlandı!"
echo ""
echo "📝 Loglar:"
echo "   3B: tail -f $PROJECT_ROOT/$LOG_DIR/vllm_8001.log"
echo "   7B: tail -f $PROJECT_ROOT/$LOG_DIR/vllm_8002.log"
echo ""
echo "🔍 Health Check:"
echo "   ./scripts/health_check_vllm.py --all"
echo ""
echo "🛑 Durdurma:"
echo "   ./scripts/vllm/stop.sh"
echo ""
echo "⚠️  NOT: NVIDIA Driver/Library mismatch hatası varsa,"
echo "   sistemi yeniden başlatın: sudo reboot"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
