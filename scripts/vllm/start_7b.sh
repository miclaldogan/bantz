#!/usr/bin/env bash
# Start vLLM server with Qwen2.5-7B-Instruct-AWQ on port 8002
# ⚠️  REQUIRES 3B server (port 8001) to be stopped first due to VRAM constraints!
# Usage: ./scripts/vllm/start_7b.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT"

echo "⚠️  7B model requires ~5.6GB VRAM. Stopping 3B server on port 8001..."
pkill -f "vllm.entrypoints.openai.api_server.*8001" || true
sleep 3

# Check if port 8002 is already in use
if ss -ltnp | grep -q ":8002 "; then
    echo "❌ Port 8002 is already in use. Stopping existing vLLM server..."
    pkill -f "vllm.entrypoints.openai.api_server.*8002" || true
    sleep 3
fi

# DISABLED: Using global vLLM installation due to CUDA compatibility
# source .venv/bin/activate

echo "🚀 Starting vLLM server (7B AWQ) on port 8002..."
echo "   Model: Qwen/Qwen2.5-7B-Instruct-AWQ"
echo "   Quantization: awq_marlin (optimized)"
echo "   Max tokens: 2048"
echo "   GPU utilization: 90% (SPEED OPTIMIZED)"
echo "   Speed optimizations: prefix-caching, chunked-prefill"
echo ""

nohup python3 -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct-AWQ \
  --quantization awq_marlin \
  --dtype half \
  --port 8002 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.90 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-num-batched-tokens 4096 \
  --max-num-seqs 256 \
  > vllm_8002.log 2>&1 &

SERVER_PID=$!
echo "✅ Server process started (PID: $SERVER_PID)"
echo "📝 Logs: $PROJECT_ROOT/vllm_8002.log"
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
