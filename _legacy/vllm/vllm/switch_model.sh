#!/usr/bin/env bash
# Quick model switching between 3B and 7B
# Usage: 
#   ./scripts/vllm/switch_model.sh 3b  # Switch to 3B (fast)
#   ./scripts/vllm/switch_model.sh 7b  # Switch to 7B (quality)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

cd "$PROJECT_ROOT"

MODEL="${1:-3b}"

if [ "$MODEL" = "3b" ]; then
    echo "🔄 Switching to 3B model (FAST mode)..."
    echo "   Stopping all vLLM servers..."
    pkill -f "vllm.entrypoints.openai" || true
    sleep 2
    
    echo "   Starting 3B model on port 8001..."
    ./scripts/vllm/start_3b.sh
    
elif [ "$MODEL" = "7b" ]; then
    echo "🔄 Switching to 7B model (QUALITY mode)..."
    echo "   Stopping all vLLM servers..."
    pkill -f "vllm.entrypoints.openai" || true
    sleep 2
    
    echo "   Starting 7B model on port 8002..."
    ./scripts/vllm/start_7b.sh
    
else
    echo "❌ Invalid model. Usage:"
    echo "   ./scripts/vllm/switch_model.sh 3b  # Fast mode"
    echo "   ./scripts/vllm/switch_model.sh 7b  # Quality mode"
    exit 1
fi
