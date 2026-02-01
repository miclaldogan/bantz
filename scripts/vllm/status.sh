#!/usr/bin/env bash
# vLLM server status check
# Usage: ./scripts/vllm/status.sh

echo "═══════════════════════════════════════════════════════════"
echo "  🚀 vLLM Server Status"
echo "═══════════════════════════════════════════════════════════"
echo ""

# GPU Status
echo "📊 GPU Status:"
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits | \
  awk -F', ' '{printf "   GPU: %s\n   VRAM: %s/%s MB (%.1f%%)\n   Util: %s%%\n   Temp: %s°C\n", $1, $2, $3, ($2/$3*100), $4, $5}'
echo ""

# Check 3B (port 8001)
echo "🔵 3B Model (Port 8001):"
if curl -s http://localhost:8001/v1/models > /dev/null 2>&1; then
    MODEL=$(curl -s http://localhost:8001/v1/models | python3 -c "import sys, json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
    PID=$(ps aux | grep "vllm.*8001" | grep -v grep | awk '{print $2}')
    UPTIME=$(ps -p $PID -o etime= 2>/dev/null | xargs)
    echo "   Status: ✅ RUNNING"
    echo "   Model: $MODEL"
    echo "   PID: $PID"
    echo "   Uptime: $UPTIME"
else
    echo "   Status: ❌ NOT RUNNING"
fi
echo ""

# Check 7B (port 8002)
echo "🟢 7B Model (Port 8002):"
if curl -s http://localhost:8002/v1/models > /dev/null 2>&1; then
    MODEL=$(curl -s http://localhost:8002/v1/models | python3 -c "import sys, json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
    PID=$(ps aux | grep "vllm.*8002" | grep -v grep | awk '{print $2}')
    UPTIME=$(ps -p $PID -o etime= 2>/dev/null | xargs)
    echo "   Status: ✅ RUNNING"
    echo "   Model: $MODEL"
    echo "   PID: $PID"
    echo "   Uptime: $UPTIME"
else
    echo "   Status: ❌ NOT RUNNING"
fi
echo ""

# Quick commands
echo "💡 Quick Commands:"
echo "   Start 3B:  ./scripts/vllm/start_3b.sh"
echo "   Start 7B:  ./scripts/vllm/start_7b.sh"
echo "   Switch:    ./scripts/vllm/switch_model.sh [3b|7b]"
echo "   Test:      ./scripts/vllm/test.sh [8001|8002]"
echo "   Stop all:  pkill -f 'vllm.entrypoints.openai'"
echo ""
echo "═══════════════════════════════════════════════════════════"
