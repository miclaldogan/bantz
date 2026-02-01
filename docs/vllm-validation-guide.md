# vLLM Validation Guide - Real GPU Testing (Issue #153)

**Status**: P0 - Critical for production readiness  
**Goal**: Validate mock estimates with real vLLM measurements on RTX 4060

---

## 🎯 Objective

Replace **ESTIMATED** values in `rtx4060-3b-vs-8b-benchmark.md` with **MEASURED** values from real vLLM server.

**Critical metrics**:
- TTFT p50/p95 (Time-To-First-Token)
- Total latency p50/p95
- Throughput (tokens/sec from vLLM usage)
- VRAM peak (nvidia-smi)
- JSON validity rate

---

## 📋 Prerequisites

### 1. Hardware
- NVIDIA RTX 4060 (8GB VRAM)
- CUDA 12.x installed
- nvidia-smi accessible

### 2. Software
```bash
# Install vLLM
pip install vllm

# Verify installation
python -c "import vllm; print(vllm.__version__)"

# Check CUDA
nvidia-smi
```

### 3. Models
Download models (will be cached):
```bash
# 3B model (~6GB disk)
huggingface-cli download Qwen/Qwen2.5-3B-Instruct

# 8B model (~16GB disk)
huggingface-cli download Qwen/Qwen2.5-8B-Instruct
```

---

## 🚀 Test Procedure

### Phase 1: 3B Baseline (30-45 minutes)

**Step 1: Start vLLM server with 3B model**
```bash
cd ~/Desktop/Bantz

# (Önerilen) Helper script:
./scripts/vllm/start_3b.sh

# (Alternatif) Manuel:

# Start vLLM server
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-3B-Instruct \
  --port 8001 \
  --dtype auto \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 16 \
  --enable-prefix-caching
```

**Expected output**:
```
INFO: Waiting for application startup.
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8001
```

**Step 2: Verify server is running**
```bash
# In new terminal
curl http://127.0.0.1:8001/v1/models | jq

# Expected response:
# {
#   "object": "list",
#   "data": [
#     {
#       "id": "Qwen/Qwen2.5-3B-Instruct",
#       ...
#     }
#   ]
# }
```

**Step 3: Check baseline VRAM**
```bash
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
# Expected: ~3000-3500 MB (model loaded)
```

**Step 4: Run benchmark (30 iterations)**
```bash
cd ~/Desktop/Bantz

# Full benchmark (router + orchestrator + chat)
python scripts/bench_llm_orchestrator.py \
  --iterations 30 \
  --scenarios all \
  --output-json results_3b_real.json \
  --output-md results_3b_real.md

# This will take ~15-20 minutes for 30 iterations × 3 scenarios
```

**Step 5: Check VRAM during benchmark**
```bash
# In separate terminal, monitor VRAM
watch -n 1 'nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader'
```

**Step 6: Record results**
- Save `results_3b_real.json`
- Note VRAM peak from nvidia-smi
- Check for any errors/warnings in benchmark output

---

### Phase 2: 8B Benchmark (30-45 minutes)

**Step 1: Stop 3B server**
```bash
# Find and kill vLLM process
pkill -f "vllm.entrypoints.openai.api_server"

# Verify stopped
curl http://127.0.0.1:8001/v1/models 2>&1 | grep -q "Failed to connect" && echo "Stopped"
```

**Step 2: Start vLLM server with 8B model**
```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-8B-Instruct \
  --port 8001 \
  --dtype auto \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 16 \
  --enable-prefix-caching
```

**Step 3: Check baseline VRAM**
```bash
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
# Expected: ~5500-6000 MB (larger model)
```

**Step 4: Run benchmark (30 iterations)**
```bash
python scripts/bench_llm_orchestrator.py \
  --iterations 30 \
  --scenarios all \
  --output-json results_8b_real.json \
  --output-md results_8b_real.md
```

**Step 5: Record results**
- Save `results_8b_real.json`
- Note VRAM peak
- Compare with 3B results

---

### Phase 3: Qualitative Tests (15-30 minutes)

**Step 1: Test with 3B (restart server if needed)**
```bash
python scripts/bench_llm_orchestrator.py \
  --qualitative
```

**Expected**: 5 multi-turn conversations with:
- Router responses
- Orchestrator plans
- Chat replies
- Memory continuity ("az önce ne yaptık?")

**Step 2: Manual evaluation**
- Rate naturalness (1-10)
- Check memory continuity
- Note any "anlamadı" moments
- Assess Jarvis feeling

**Step 3: Repeat with 8B**
```bash
# Switch to 8B server (same as Phase 2 Step 1-2)
python scripts/bench_llm_orchestrator.py \
  --qualitative
```

**Step 4: Compare**
- Which model feels more natural?
- Which has better TTFT perception?
- Overall preference?

---

## 📊 Data Collection Template

### 3B Results (MEASURED)

| Metric | Router | Orchestrator | Chat | Notes |
|--------|--------|--------------|------|-------|
| **TTFT p50** | ___ ms | ___ ms | ___ ms | From JSON |
| **TTFT p95** | ___ ms | ___ ms | ___ ms | From JSON |
| **Latency p50** | ___ ms | ___ ms | ___ ms | From JSON |
| **Latency p95** | ___ ms | ___ ms | ___ ms | From JSON |
| **Throughput** | ___ tok/s | ___ tok/s | ___ tok/s | From JSON |
| **JSON valid** | ___% | ___% | N/A | From JSON |
| **VRAM peak** | ___ MB | ___ MB | ___ MB | nvidia-smi |
| **Errors** | ___ | ___ | ___ | Any failures |

### 8B Results (MEASURED)

| Metric | Router | Orchestrator | Chat | Notes |
|--------|--------|--------------|------|-------|
| **TTFT p50** | ___ ms | ___ ms | ___ ms | From JSON |
| **TTFT p95** | ___ ms | ___ ms | ___ ms | From JSON |
| **Latency p50** | ___ ms | ___ ms | ___ ms | From JSON |
| **Latency p95** | ___ ms | ___ ms | ___ ms | From JSON |
| **Throughput** | ___ tok/s | ___ tok/s | ___ tok/s | From JSON |
| **JSON valid** | ___% | ___% | N/A | From JSON |
| **VRAM peak** | ___ MB | ___ MB | ___ MB | nvidia-smi |
| **Errors** | ___ | ___ | ___ | Any failures |

### Qualitative (MEASURED)

| Aspect | 3B | 8B | Winner |
|--------|----|----|--------|
| **Naturalness** | __/10 | __/10 | ___ |
| **Memory** | Pass/Fail | Pass/Fail | ___ |
| **Tool accuracy** | ___% | ___% | ___ |
| **Jarvis feeling** | __/10 | __/10 | ___ |
| **Overall** | __/10 | __/10 | ___ |

---

## 🔄 Update Benchmark Report

After collecting real measurements:

**Step 1: Update tables in `docs/rtx4060-3b-vs-8b-benchmark.md`**
- Replace "ESTIMATED" with "MEASURED"
- Add comparison: Estimated vs Measured
- Note any significant deviations (>20%)

**Step 2: Validate or revise strategy**
- If TTFT p95 > 300ms → reconsider split strategy
- If VRAM > 7.5GB → consider quantization
- If throughput < 80 tok/s → investigate bottlenecks

**Step 3: Update recommendation section**
- Change "Preliminary" to "Validated" (if targets met)
- Document any adjustments needed
- Update production config if necessary

**Step 4: Commit changes**
```bash
git add docs/rtx4060-3b-vs-8b-benchmark.md
git commit -m "feat: Real vLLM validation for Issue #153 (3B+8B measured)"
```

---

## ⚠️ Troubleshooting

### vLLM server won't start
```bash
# Check CUDA
nvidia-smi

# Check GPU availability
python -c "import torch; print(torch.cuda.is_available())"

# Try with smaller context
--max-model-len 2048
```

### OOM (Out of Memory)
```bash
# Reduce memory utilization
--gpu-memory-utilization 0.75

# Or use quantization
--quantization awq  # Requires AWQ model variant
```

### Benchmark script errors
```bash
# Check imports
cd ~/Desktop/Bantz
python -c "from bantz.llm.base import create_client; print('OK')"

# Run with verbose
python scripts/bench_llm_orchestrator.py --verbose --quick
```

### TTFT not measured
- Current script estimates TTFT as ~8% of total latency
- For real TTFT: need streaming callbacks (TODO)
- Workaround: Use total latency as proxy for now

---

## 📝 Success Criteria

**Must achieve**:
- ✅ Router TTFT p95 < 200ms (3B)
- ✅ Orchestrator TTFT p95 < 200ms (3B)
- ✅ Chat TTFT p95 < 300ms (8B)
- ✅ VRAM peak < 7.5GB (both models)
- ✅ Throughput > 80 tok/s
- ✅ JSON validity > 95%

**If targets not met**:
- Analyze bottlenecks
- Consider quantization (AWQ)
- Adjust prompt budgets
- Reconsider model selection

---

## 🎉 Completion

When all measurements collected and report updated:

1. Close validation checklist in `rtx4060-3b-vs-8b-benchmark.md`
2. Update Issue #153 with real results
3. Proceed to P1: Implement split strategy in code
4. Production deployment ready!

---

**Estimated Time**: 2-3 hours total (including model downloads)
**Priority**: P0 - Required before production
**Owner**: TBD
