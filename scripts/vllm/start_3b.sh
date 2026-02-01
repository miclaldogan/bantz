#!/usr/bin/env bash
# Start vLLM server with Qwen2.5-3B-Instruct-AWQ on port 8001
# Usage: ./scripts/vllm/start_3b.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT"

LOG_DIR="${BANTZ_VLLM_LOG_DIR:-artifacts/logs/vllm}"
mkdir -p "$LOG_DIR"

# Check if port 8001 is already in use
if ss -ltnp | grep -q ":8001 "; then
    echo "❌ Port 8001 is already in use. Stopping existing vLLM server..."
    pkill -f "vllm.entrypoints.openai.api_server.*8001" || true
    sleep 3
fi

# Activate virtual environment if exists
# DISABLED: Using global vLLM installation due to CUDA compatibility
# if [ -d ".venv" ]; then
#     source .venv/bin/activate
# fi

echo "🚀 Starting vLLM server (3B AWQ) on port 8001..."
echo "   Model: Qwen/Qwen2.5-3B-Instruct-AWQ"
echo "   Quantization: awq_marlin (optimized)"
echo "   Profile: dual-friendly defaults (override via env vars)"
echo "   Max tokens: ${BANTZ_VLLM_3B_MAX_MODEL_LEN:-1024}"
echo "   GPU utilization: ${BANTZ_VLLM_3B_GPU_UTIL:-0.45}"
echo ""

# Use global Python for now (no venv requirement).
PYTHON_BIN="${BANTZ_VLLM_PYTHON:-python3}"
if ! "$PYTHON_BIN" -c "import vllm" >/dev/null 2>&1; then
    echo "❌ vLLM import edilemedi ($PYTHON_BIN). Önce vLLM'i kurun: pip install vllm" >&2
    exit 1
fi

nohup "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
    --model "${BANTZ_VLLM_3B_MODEL:-Qwen/Qwen2.5-3B-Instruct-AWQ}" \
    --quantization "${BANTZ_VLLM_3B_QUANT:-awq_marlin}" \
    --dtype "${BANTZ_VLLM_3B_DTYPE:-half}" \
    --port "${BANTZ_VLLM_3B_PORT:-8001}" \
    --max-model-len "${BANTZ_VLLM_3B_MAX_MODEL_LEN:-1024}" \
    --gpu-memory-utilization "${BANTZ_VLLM_3B_GPU_UTIL:-0.45}" \
    --max-num-seqs "${BANTZ_VLLM_3B_MAX_NUM_SEQS:-32}" \
    --max-num-batched-tokens "${BANTZ_VLLM_3B_MAX_BATCH_TOKENS:-2048}" \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    > "$LOG_DIR/vllm_8001.log" 2>&1 &

SERVER_PID=$!
echo "✅ Server process started (PID: $SERVER_PID)"
echo "📝 Logs: $PROJECT_ROOT/$LOG_DIR/vllm_8001.log"
echo ""
echo "Waiting 40 seconds for model loading..."
sleep 40

# Health check
if curl -s http://localhost:8001/v1/models > /dev/null 2>&1; then
    MODEL_ID=$(curl -s http://localhost:8001/v1/models | python3 -c "import sys, json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "unknown")
    echo "✅ vLLM server is ready!"
    echo "   Model ID: $MODEL_ID"
    echo "   Endpoint: http://localhost:8001"
else
    echo "⚠️  Server may still be loading. Check logs: tail -f vllm_8001.log"
    exit 1
fi
