#!/bin/bash
# Test vLLM mock server responses

cd "$(dirname "$0")/.."

echo "🚀 Starting vLLM mock server..."
python3 scripts/vllm_mock_server.py > /tmp/vllm_mock.log 2>&1 &
SERVER_PID=$!
sleep 3

echo "📊 Running benchmarks with verbose output..."
python3 scripts/bench_llm_orchestrator.py --backend vllm --scenarios router --verbose --iterations 1 2>&1 | grep -E "(Running:|🤖|route=)"

echo ""
echo "🛑 Stopping mock server..."
kill $SERVER_PID 2>/dev/null

echo "✅ Done!"
