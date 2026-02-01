#!/usr/bin/env bash
# Quick vLLM server test and speed benchmark
# Usage: ./scripts/vllm/test.sh [port]

PORT="${1:-8001}"

echo "🧪 Testing vLLM server on port $PORT..."
echo ""

# Check if server is running
if ! curl -s http://localhost:$PORT/v1/models > /dev/null 2>&1; then
    echo "❌ Server not responding on port $PORT"
    exit 1
fi

# Get model info
echo "✅ Server is running!"
MODEL_INFO=$(curl -s http://localhost:$PORT/v1/models | python3 -c "import sys, json; d=json.load(sys.stdin)['data'][0]; print(f\"Model: {d['id']}\nMax tokens: {d['max_model_len']}\")")
echo "$MODEL_INFO"
echo ""

# Speed test
echo "⚡ Speed test (3 simple prompts)..."
START_TIME=$(date +%s%N)

for i in {1..3}; do
    curl -s http://localhost:$PORT/v1/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "Qwen/Qwen2.5-3B-Instruct-AWQ",
        "prompt": "Hello",
        "max_tokens": 10,
        "temperature": 0
      }' > /dev/null
done

END_TIME=$(date +%s%N)
DURATION=$(( ($END_TIME - $START_TIME) / 1000000 ))
AVG_LATENCY=$(( $DURATION / 3 ))

echo "✅ 3 requests completed in ${DURATION}ms"
echo "   Average latency: ${AVG_LATENCY}ms per request"
echo ""

# Single detailed test
echo "📝 Detailed test with output:"
RESPONSE=$(curl -s http://localhost:$PORT/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-3B-Instruct-AWQ",
    "prompt": "Write a haiku about speed:",
    "max_tokens": 50,
    "temperature": 0.7
  }')

echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['choices'][0]['text'])"
echo ""
echo "✅ Test completed!"
