# Migration Guide: Ollama → vLLM

**Issue #159**: Ollama Deprecation & Cleanup

## Why vLLM?

Bantz has fully migrated to vLLM for local LLM inference. Here's why:

### Performance Advantages

| Metric | Ollama | vLLM | Improvement |
|--------|--------|------|-------------|
| **TTFT** | ~280ms | ~41ms | **7x faster** ⚡ |
| **Throughput** | 15 tok/s | 50+ tok/s | **3.3x faster** 🚀 |
| **GPU Utilization** | 60-70% | 90-95% | **Better efficiency** 💪 |
| **Memory** | Higher | Optimized | **Lower footprint** 📉 |

### Technical Benefits

✅ **PagedAttention**: Efficient KV cache management  
✅ **Continuous Batching**: Better multi-request handling  
✅ **OpenAI-compatible API**: Standard interface  
✅ **Streaming Support**: Real-time token delivery  
✅ **TTFT Monitoring**: Built-in performance tracking (Issue #158)  
✅ **Tiered Quality**: Keep local 3B fast; use Gemini for writing-heavy quality (Issue #179)  

### Production-Ready

- ✅ Proven at scale (used by major companies)
- ✅ Active development & community
- ✅ Extensive documentation
- ✅ Better error handling
- ✅ Comprehensive benchmarking tools

## Migration Steps

### 1. Install vLLM

```bash
# Install vLLM with CUDA support
pip install vllm

# Or with requirements
pip install -e ".[llm]"
```

### 2. Stop Ollama (if running)

```bash
# Stop Ollama service
sudo systemctl stop ollama

# (Optional) Remove Ollama
# brew uninstall ollama  # macOS
# sudo apt remove ollama # Linux
```

### 3. Start vLLM Server

**3B Router (Fast)**
```bash
./scripts/vllm/start_3b.sh
# Runs on http://localhost:8001
```

**Quality (Writing-heavy tasks)**

Use Gemini API (cloud) instead of running a local 7B/8B model:
```bash
export BANTZ_CLOUD_MODE=cloud
export QUALITY_PROVIDER=gemini
export GEMINI_API_KEY="your-key"
```

**Manual Start**
```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-3B-Instruct \
    --port 8001 \
    --dtype auto \
    --max-model-len 4096
```

### 4. Update Configuration

**Before (Ollama):**
```python
from bantz.llm.ollama_client import OllamaClient

router = OllamaClient(model="qwen2.5:3b-instruct-q8_0")
```

**After (vLLM):**
```python
from bantz.llm.vllm_openai_client import VLLMOpenAIClient

router = VLLMOpenAIClient(
    base_url="http://localhost:8001",
    model="Qwen/Qwen2.5-3B-Instruct"
)
```

### 5. Update Environment Variables

**Before:**
```bash
export BANTZ_LLM_BACKEND=ollama
export BANTZ_ROUTER_MODEL=qwen2.5:3b-instruct-q8_0
```

**After:**
```bash
export BANTZ_VLLM_URL=http://localhost:8001
export BANTZ_VLLM_MODEL=Qwen/Qwen2.5-3B-Instruct
```

### 6. Update Hybrid Orchestrator Config

**Before:**
```python
config = HybridOrchestratorConfig(
    router_backend="ollama",
    router_model="qwen2.5:3b-instruct-q8_0",
)
```

**After:**
```python
config = HybridOrchestratorConfig(
    router_backend="vllm",
    router_model="Qwen/Qwen2.5-3B-Instruct",
)
```

## Model Naming Changes

Ollama and vLLM use different model naming conventions:

| Component | Ollama | vLLM |
|-----------|--------|------|
| **3B Router** | `qwen2.5:3b-instruct-q8_0` | `Qwen/Qwen2.5-3B-Instruct` |
| **7B Finalizer** | `qwen2.5:7b-instruct-q8_0` | `Qwen/Qwen2.5-7B-Instruct` |

**Note**: vLLM uses HuggingFace model IDs, Ollama uses custom tags.

## Testing Migration

### 1. Verify vLLM Server

```bash
# Check if vLLM is running
curl http://localhost:8001/v1/models

# Expected output:
{
  "object": "list",
  "data": [
    {
      "id": "Qwen/Qwen2.5-3B-Instruct",
      "object": "model",
      ...
    }
  ]
}
```

### 2. Run Benchmarks

```bash
# TTFT benchmark (Issue #158)
python scripts/bench_ttft_monitoring.py --num-tests 30

# Hybrid quality benchmark (Issue #157)
python scripts/bench_hybrid_quality.py --num-tests 30
```

### 3. Run Tests

```bash
# Unit tests
pytest tests/test_gemini_hybrid_orchestrator.py -v
pytest tests/test_flexible_hybrid_orchestrator.py -v
pytest tests/test_ttft_monitoring.py -v

# Demo scripts
python scripts/demo_gemini_hybrid.py
python scripts/demo_ttft_realtime.py --mode interactive
```

## Troubleshooting

### Issue: vLLM server not starting

**Solution:**
```bash
# Check GPU availability
nvidia-smi

# Check CUDA version
nvcc --version

# Install correct CUDA toolkit if needed
conda install cuda-toolkit -c nvidia
```

### Issue: Model not found

**Solution:**
```bash
# vLLM auto-downloads from HuggingFace
# Ensure internet connection
# Or pre-download:
huggingface-cli download Qwen/Qwen2.5-3B-Instruct
```

### Issue: Out of memory

**Solution:**
```bash
# Use smaller max-model-len
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-3B-Instruct \
    --max-model-len 2048  # Reduced from 4096

# Or use quantization
    --quantization awq
```

### Issue: Slow performance

**Solution:**
```bash
# Check GPU utilization
nvidia-smi -l 1

# Enable tensor parallelism for multi-GPU
python -m vllm.entrypoints.openai.api_server \
    --tensor-parallel-size 2
```

## Performance Comparison

### Before (Ollama)
```
TTFT (3B router): ~280ms
Throughput: 15 tok/s
GPU Utilization: 60-70%
```

### After (vLLM)
```
TTFT (3B router): ~41ms ✅ 7x faster
Throughput: 50+ tok/s ✅ 3x faster
GPU Utilization: 90-95% ✅ Better efficiency
```

## What Changed in Code

### Removed Files
- `src/bantz/llm/ollama_client.py` ❌ (deleted)

### Updated Files
- `src/bantz/brain/gemini_hybrid_orchestrator.py`
  - Default backend: `vllm`
  - Default model: `Qwen/Qwen2.5-3B-Instruct`
  - Removed `OllamaClient` import
  
- `src/bantz/brain/flexible_hybrid_orchestrator.py`
  - Documentation updated to vLLM only
  
- `scripts/demo_gemini_hybrid.py`
  - Uses `VLLMOpenAIClient`
  - Updated configuration
  
- `tests/test_gemini_hybrid_orchestrator.py`
  - Updated default config assertions
  
- `README.md`
  - All examples use vLLM
  
- `docs/gemini-hybrid-orchestrator.md`
  - Architecture diagrams updated
  - Configuration examples updated

## Benefits After Migration

✅ **7x faster TTFT** (280ms → 41ms)  
✅ **3x higher throughput** (15 tok/s → 50+ tok/s)  
✅ **Better GPU utilization** (60% → 95%)  
✅ **Streaming support** with TTFT monitoring  
✅ **Tiered quality** (3B local + Gemini cloud)  
✅ **Production-ready** infrastructure  
✅ **OpenAI-compatible** API  
✅ **Better error handling**  
✅ **Comprehensive benchmarks**  

## Support

If you encounter issues during migration:

1. Check [vLLM documentation](https://docs.vllm.ai/)
2. Run diagnostic script: `python scripts/health_check_vllm.py`
3. Check logs: `artifacts/logs/vllm.log`
4. Open an issue: [GitHub Issues](https://github.com/miclaldogan/bantz/issues)

## Timeline

- **Phase 1 (✅ Completed)**: vLLM integration (Issue #131)
- **Phase 2 (✅ Completed)**: Hybrid orchestrators (Issues #157, #158)
- **Phase 3 (✅ Completed)**: Ollama deprecation (Issue #159)
- **Phase 4 (Upcoming)**: Tiered quality (3B local + Gemini cloud) (Issue #179)

---

**Migration completed! Welcome to vLLM! 🚀**
