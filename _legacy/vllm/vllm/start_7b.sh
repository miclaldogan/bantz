#!/usr/bin/env bash
# Start vLLM server with Qwen2.5-7B-Instruct-AWQ on port 8002
# Can run alongside 3B on a single GPU if memory/KV-cache limits are tuned.
# Usage: ./scripts/vllm/start_7b.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT"

LOG_DIR="${BANTZ_VLLM_LOG_DIR:-artifacts/logs/vllm}"
mkdir -p "$LOG_DIR"

if [ "${BANTZ_VLLM_DUAL_MODE:-1}" != "1" ]; then
    echo "⚠️  Dual mode kapalı: 3B server (8001) durduruluyor..."
    pkill -f "vllm.entrypoints.openai.api_server.*8001" || true
    sleep 3
fi

# Check if port 8002 is already in use
if ss -ltnp | grep -q ":8002 "; then
    echo "❌ Port 8002 is already in use. Stopping existing vLLM server..."
    pkill -f "vllm.entrypoints.openai.api_server.*8002" || true
    sleep 3
fi

# DISABLED: Using global vLLM installation due to CUDA compatibility
# source .venv/bin/activate

echo "🚀 Starting vLLM server (7B AWQ) on port 8002..."
echo "   Model: ${BANTZ_VLLM_7B_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
echo "   Quantization: ${BANTZ_VLLM_7B_QUANT:-awq_marlin}"
echo "   Profile: quality / dual-friendly defaults (override via env vars)"
echo "   Max tokens: ${BANTZ_VLLM_7B_MAX_MODEL_LEN:-1536}"
echo "   GPU utilization: ${BANTZ_VLLM_7B_GPU_UTIL:-0.55}"
echo "   Offload: cpu_offload_gb=${BANTZ_VLLM_7B_CPU_OFFLOAD_GB:-6}, swap_space=${BANTZ_VLLM_7B_SWAP_SPACE:-6}"
echo ""

PYTHON_BIN="${BANTZ_VLLM_PYTHON:-python3}"
if ! "$PYTHON_BIN" -c "import vllm" >/dev/null 2>&1; then
    echo "❌ vLLM import edilemedi ($PYTHON_BIN). Önce vLLM'i kurun: pip install vllm" >&2
    exit 1
fi

EXTRA_ARGS=()
if [ "${BANTZ_VLLM_7B_CPU_OFFLOAD_GB:-6}" != "0" ]; then
    EXTRA_ARGS+=("--cpu-offload-gb" "${BANTZ_VLLM_7B_CPU_OFFLOAD_GB:-6}")
fi
if [ "${BANTZ_VLLM_7B_SWAP_SPACE:-6}" != "0" ]; then
    EXTRA_ARGS+=("--swap-space" "${BANTZ_VLLM_7B_SWAP_SPACE:-6}")
fi

nohup "$PYTHON_BIN" -m vllm.entrypoints.openai.api_server \
    --model "${BANTZ_VLLM_7B_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}" \
    --quantization "${BANTZ_VLLM_7B_QUANT:-awq_marlin}" \
    --dtype "${BANTZ_VLLM_7B_DTYPE:-half}" \
    --port "${BANTZ_VLLM_7B_PORT:-8002}" \
    --max-model-len "${BANTZ_VLLM_7B_MAX_MODEL_LEN:-1536}" \
    --gpu-memory-utilization "${BANTZ_VLLM_7B_GPU_UTIL:-0.55}" \
    --max-num-seqs "${BANTZ_VLLM_7B_MAX_NUM_SEQS:-16}" \
    --max-num-batched-tokens "${BANTZ_VLLM_7B_MAX_BATCH_TOKENS:-4096}" \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    "${EXTRA_ARGS[@]}" \
    > "$LOG_DIR/vllm_8002.log" 2>&1 &

SERVER_PID=$!
echo "✅ Server process started (PID: $SERVER_PID)"
echo "📝 Logs: $PROJECT_ROOT/$LOG_DIR/vllm_8002.log"
echo ""
echo "Waiting 60 seconds for model loading (7B is larger)..."
sleep 60

# Health check
if curl -s http://localhost:8002/v1/models > /dev/null 2>&1; then
    MODEL_ID=$(curl -s http://localhost:8002/v1/models | python3 -c "import sys, json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "unknown")
    echo "✅ vLLM server is ready!"
    echo "   Model ID: $MODEL_ID"
    echo "   Endpoint: http://localhost:8002"
else
    echo "⚠️  Server may still be loading. Check logs: tail -f vllm_8002.log"
    exit 1
fi
