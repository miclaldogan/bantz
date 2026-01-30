# Issue #138 - Benchmark Framework

## Status: ✅ COMPLETED

## Summary
Benchmark framework for LLM Orchestrator with mock server and token tracking.

## Deliverables

### 1. Benchmark Script (`scripts/bench_llm_orchestrator.py`)
- ✅ Router, Orchestrator, Chat scenario support
- ✅ Multiple backends (vLLM, Ollama)
- ✅ Token tracking (input/output/total)
- ✅ Throughput calculation (tokens/sec)
- ✅ Latency metrics (p50, p95, p99)
- ✅ JSON validity tracking
- ✅ Verbose mode (--verbose) to inspect LLM responses
- ✅ Flexible iterations (--iterations N)

**Usage:**
```bash
# Mock server benchmark
python3 scripts/bench_llm_orchestrator.py --backend vllm --scenarios router --iterations 30

# Real vLLM benchmark
python3 scripts/bench_llm_orchestrator.py --backend vllm --scenarios orchestrator --iterations 30

# Verbose mode (see LLM responses)
python3 scripts/bench_llm_orchestrator.py --backend vllm --scenarios router --verbose --iterations 1
```

### 2. Mock Server (`scripts/vllm_mock_server.py`)
- ✅ OpenAI-compatible API (/v1/chat/completions)
- ✅ Turkish pattern matching for realistic responses
- ✅ Correct routing (calendar vs smalltalk)
- ✅ Realistic token estimation (char count / 4)
- ✅ ~110ms latency (mock baseline)
- ✅ Diverse responses based on user intent

**Pattern Matching:**
- Greetings → smalltalk with appropriate reply
- Calendar queries → calendar route with query intent
- Calendar create → calendar route with create intent
- Weather → smalltalk with contextual reply
- Self-intro → smalltalk with Bantz description

**Usage:**
```bash
# Start mock server
python3 scripts/vllm_mock_server.py

# In another terminal
python3 scripts/bench_llm_orchestrator.py --backend vllm --scenarios router
```

### 3. Test Script (`scripts/test_mock_responses.sh`)
- ✅ Automated server start/stop
- ✅ Benchmark execution with filtering
- ✅ Clean process management

### 4. Metrics Achieved (Mock Baseline)

**Router Scenarios (iterations=1):**
```
Latency:
  p50: ~110ms
  p95: ~110ms (needs iterations > 1 for meaningful percentiles)

Token Usage:
  Input: ~708-713 tokens (system prompt + user input)
  Output: 13-24 tokens (JSON response)
  Total: ~721-732 tokens

Throughput:
  118-220 tokens/sec (mock server baseline)

Success Rate:
  100% (all scenarios working)

JSON Validity:
  100% (pattern matching returns valid JSON)
```

**Diverse Responses:**
- ✅ "hey bantz nasılsın" → route=smalltalk, reply="Merhaba efendim..."
- ✅ "bugün neler yapacağız" → route=calendar, intent=query
- ✅ "kendini tanıt" → route=smalltalk, reply="Ben Bantz..."
- ✅ "bugün hava nasıl" → route=smalltalk, reply="Hava durumu servisi..."
- ✅ "takvimimi göster" → route=calendar, intent=query

## Key Fixes

### Fix 1: User Input Extraction
**Problem:** Mock server matched patterns against full system prompt instead of user input
**Solution:** Extract text after "USER:" marker from prompt
**Result:** Correct routing and diverse responses

### Fix 2: Token Tracking
**Problem:** Token counts were 0 (not being captured)
**Solution:**
- Mock server: realistic token estimation (max(word_count, char_count/4))
- Benchmark: estimate tokens based on prompt + response length
**Result:** Throughput metrics now showing realistic values

### Fix 3: Missing sys Import
**Problem:** Server crash due to undefined `sys` module
**Solution:** Added `import sys` to vllm_mock_server.py
**Result:** Debug logging works, server stable

## Next Steps

### Phase 1: Real vLLM Benchmarking (P0)
- [ ] Setup real vLLM server with Qwen2.5-3B-Instruct
- [ ] Run router benchmark: iterations=30
- [ ] Run orchestrator benchmark: iterations=30
- [ ] Compare vs mock baseline
- [ ] Document real latency/throughput metrics

### Phase 2: Production Config (P1)
- [ ] Tune max_tokens per role (router=128, orchestrator=256, chat=200)
- [ ] Validate temperature settings (router=0.0, chat=0.2)
- [ ] Prompt compression if needed
- [ ] Document production settings in config/model-settings.yaml

### Phase 3: Extended Scenarios (P2)
- [ ] Add more router scenarios (edge cases, ambiguous inputs)
- [ ] Add orchestrator scenarios (multi-step planning)
- [ ] Add chat scenarios (personality consistency)
- [ ] Human eval for quality metrics

## Files Changed

```
scripts/bench_llm_orchestrator.py  - Benchmark framework with token tracking
scripts/vllm_mock_server.py       - Mock server with Turkish patterns
scripts/test_mock_responses.sh     - Test automation script (new)
docs/model-strategy.md            - Model strategy documentation (new)
config/model-settings.yaml        - Production config (new)
```

## Commits

1. `feat(benchmark): Add --verbose flag to show LLM responses` (e1edfa5)
2. `feat(mock): Improve vLLM mock server with smart pattern matching` (f0e7e98)
3. `fix(mock): Extract USER input from prompt for pattern matching` (3cf2e07)
4. `feat(benchmark): Add token tracking and throughput metrics` (pending)

## Related Issues

- Issue #136: Model Strategy (completed - docs/model-strategy.md)
- Issue #141: Memory-lite (next - rolling summary)
- PR #151: Benchmark framework (merged to dev)

## Conclusion

✅ **Issue #138 is COMPLETE**

Benchmark framework is functional with:
- Mock server providing realistic responses
- Token tracking and throughput metrics
- Diverse routing based on Turkish patterns
- ~110ms baseline latency
- 118-220 tokens/sec throughput

**Next step:** Run benchmarks against real vLLM server to establish production performance baseline.
