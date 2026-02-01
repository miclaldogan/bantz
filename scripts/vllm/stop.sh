#!/usr/bin/env bash
# Stop all vLLM servers (ports 8001, 8002)
# Usage: ./scripts/vllm/stop.sh

set -e

echo "🛑 Stopping vLLM servers..."

# Stop 3B server (port 8001)
if pgrep -f "vllm.entrypoints.openai.api_server.*8001" > /dev/null; then
    echo "   Stopping 3B server (port 8001)..."
    pkill -f "vllm.entrypoints.openai.api_server.*8001"
    echo "   ✅ 3B server stopped"
else
    echo "   ℹ️  No 3B server running on port 8001"
fi

# Stop 7B server (port 8002)
if pgrep -f "vllm.entrypoints.openai.api_server.*8002" > /dev/null; then
    echo "   Stopping 7B server (port 8002)..."
    pkill -f "vllm.entrypoints.openai.api_server.*8002"
    echo "   ✅ 7B server stopped"
else
    echo "   ℹ️  No 7B server running on port 8002"
fi

sleep 2
echo "✅ All vLLM servers stopped"
echo ""
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | \
    awk '{printf "   GPU Memory: %d / %d MiB (%.1f%% free)\n", $1, $2, 100*(1-$1/$2)}'
