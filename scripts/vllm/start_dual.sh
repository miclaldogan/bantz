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
pkill -f "vllm" || true
sleep 3

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment bulunamadı. Önce kurun:"
    echo "   python -m venv .venv"
    echo "   source .venv/bin/activate"
    echo "   pip install -e ."
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Verify vLLM installation
if ! python -c "import vllm" 2>/dev/null; then
    echo "❌ vLLM import edilemedi. Yeniden kuruluyor..."
    pip install --upgrade pip
    pip uninstall -y vllm vllm-flash-attn || true
    pip install vllm==0.6.6 --no-cache-dir
fi

echo ""
echo "🚀 3B Model Başlatılıyor (Port 8001)..."
echo "   Model: Qwen/Qwen2.5-3B-Instruct-AWQ"
echo "   VRAM: ~2.5GB"

# Set LD_LIBRARY_PATH for CUDA libraries
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/home/iclaldogan/Desktop/Bantz/.venv/lib/python3.10/site-packages/nvidia/nvjitlink/lib

nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-3B-Instruct-AWQ \
  --quantization awq_marlin \
  --dtype half \
  --port 8001 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.40 \
  --enable-prefix-caching \
  > vllm_8001.log 2>&1 &

PID_3B=$!
echo "✅ 3B server başlatıldı (PID: $PID_3B)"

echo ""
echo "⏳ 3B model yükleniyor... (30 saniye)"
sleep 30

# Check 3B health
if curl -s http://localhost:8001/v1/models > /dev/null 2>&1; then
    echo "✅ 3B server hazır: http://localhost:8001"
else
    echo "⚠️  3B server henüz hazır değil, log kontrol edin: tail -f vllm_8001.log"
fi

echo ""
echo "🚀 7B Model Başlatılıyor (Port 8002)..."
echo "   Model: Qwen/Qwen2.5-7B-Instruct-AWQ"
echo "   VRAM: ~4.5GB"

nohup python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct-AWQ \
  --quantization awq_marlin \
  --dtype half \
  --port 8002 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.50 \
  --enable-prefix-caching \
  > vllm_8002.log 2>&1 &

PID_7B=$!
echo "✅ 7B server başlatıldı (PID: $PID_7B)"

echo ""
echo "⏳ 7B model yükleniyor... (45 saniye)"
sleep 45

# Check 7B health
if curl -s http://localhost:8002/v1/models > /dev/null 2>&1; then
    echo "✅ 7B server hazır: http://localhost:8002"
else
    echo "⚠️  7B server henüz hazır değil, log kontrol edin: tail -f vllm_8002.log"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Kurulum Tamamlandı!"
echo ""
echo "📝 Loglar:"
echo "   3B: tail -f $PROJECT_ROOT/vllm_8001.log"
echo "   7B: tail -f $PROJECT_ROOT/vllm_8002.log"
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
