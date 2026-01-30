# Model Strategy (Issue #136)

> **Karar:** LLM-first architecture - Tek model tüm işleri yapar

## Executive Summary

Bantz, **tek-model stratejisi** ile başlar:
- **Model:** Qwen/Qwen2.5-3B-Instruct (veya benzer 3B-7B instruct model)
- **Roller:** Router, Orchestrator, Chat - hepsi aynı model
- **Avantaj:** Tutarlı kişilik, basit deployment, hızlı iterasyon
- **Hedef Latency:** p95 < 200ms (3B model, vLLM ile)

İleri aşamada iki-model stratejisine geçiş mümkün (router için küçük model).

---

## 1. Model Rolleri

### 1.1 Router (Route Classification)
**Görev:** Kullanıcı mesajını `calendar | smalltalk | unknown` route'larına ayır

**Prompt Karakteristikleri:**
- System prompt: ~400-500 token (örnekler + kurallar)
- User input: 5-50 token
- **Total input:** ~450-550 token
- **Output:** JSON (~10-20 token)

**Model Ayarları:**
```python
{
  "model": "Qwen/Qwen2.5-3B-Instruct",
  "temperature": 0.0,  # Deterministik routing
  "max_tokens": 128,   # JSON için yeterli
  "stop": ["}"]        # JSON sonrası kes
}
```

**Performans Hedefi:**
- p50 latency: < 100ms
- p95 latency: < 150ms
- JSON validity: > 99%
- Throughput: > 100 tokens/sec

---

### 1.2 Orchestrator (Full Decision Making)
**Görev:** Route + Intent + Slots + Tool Plan + Confirmation + Reasoning

**Prompt Karakteristikleri:**
- System prompt: ~600-700 token (genişletilmiş şema)
- User input: 5-50 token
- Context (dialog summary): 0-200 token
- **Total input:** ~650-950 token
- **Output:** JSON (~30-50 token)

**Model Ayarları:**
```python
{
  "model": "Qwen/Qwen2.5-3B-Instruct",
  "temperature": 0.0,  # Planlama için deterministik
  "max_tokens": 256,   # Genişletilmiş JSON + reasoning
  "stop": ["}"]
}
```

**Performans Hedefi:**
- p50 latency: < 120ms
- p95 latency: < 200ms
- JSON validity: > 98%

---

### 1.3 Chat (Conversational Response)
**Görev:** Smalltalk, açıklama, sohbet

**Prompt Karakteristikleri:**
- System prompt: ~300-400 token (persona + stil)
- Conversation history: 0-500 token
- User input: 5-100 token
- **Total input:** ~350-1000 token
- **Output:** Natural text (~20-150 token)

**Model Ayarları:**
```python
{
  "model": "Qwen/Qwen2.5-3B-Instruct",
  "temperature": 0.2,  # Biraz yaratıcılık
  "max_tokens": 200,   # Kısa cevaplar
  "top_p": 0.9
}
```

**Performans Hedefi:**
- p50 latency: < 200ms
- p95 latency: < 400ms
- Naturalness: Jarvis hissi (subjektif test)

---

## 2. Prompt Budget

### 2.1 Token Limitleri
| Component | Input Limit | Output Limit | Total Budget |
|-----------|-------------|--------------|--------------|
| Router | 600 token | 128 token | 728 token |
| Orchestrator | 1000 token | 256 token | 1256 token |
| Chat | 1200 token | 200 token | 1400 token |

### 2.2 Context Window Management
**Model Context:** 32K tokens (Qwen2.5-3B varsayılan)

**Strategy:**
- **Dialog summary:** Max 500 token (rolling window)
- **Tool results:** Max 300 token (summarize if needed)
- **Session context:** Max 200 token
- **Reserved for future:** 30K token (uzun konuşmalar için)

---

## 3. Benchmarking Kriterleri

### 3.1 Latency Targets (vLLM, single GPU)
```
Router:
- p50: < 100ms ✅ (currently ~110ms with mock)
- p95: < 150ms
- p99: < 200ms

Orchestrator:
- p50: < 120ms
- p95: < 200ms
- p99: < 300ms

Chat:
- p50: < 200ms
- p95: < 400ms
- p99: < 600ms
```

### 3.2 Throughput Targets
```
Router: > 100 tokens/sec ✅ (currently ~120-220 with mock)
Orchestrator: > 80 tokens/sec
Chat: > 50 tokens/sec
```

### 3.3 Quality Metrics
```
JSON Validity (Router/Orchestrator): > 98%
Route Accuracy: > 95% (human eval on test set)
Intent Extraction: > 90%
Jarvis Personality: Subjective A/B test
```

---

## 4. Implementation Plan

### Phase 1: Single Model MVP (Current)
- [x] Mock server ile baseline metrics
- [x] Token tracking ve throughput measurement
- [ ] Real vLLM server setup
- [ ] Benchmark with iterations=30
- [ ] Establish performance baseline

**Deliverables:**
- `scripts/bench_llm_orchestrator.py` (✅ Done)
- `scripts/vllm_mock_server.py` (✅ Done)
- Real vLLM benchmark report

---

### Phase 2: Production Config Tuning
- [ ] Optimal `max_tokens` per role
- [ ] Temperature tuning (router=0.0, chat=0.2)
- [ ] Prompt compression (remove redundant examples)
- [ ] Batch inference for multiple users (optional)

**Deliverables:**
- Production config file: `config/model-settings.yaml`
- Tuning report with A/B results

---

### Phase 3: Two-Model Strategy (Optional Upgrade)
**Trigger:** If router latency > 150ms OR we want to scale to 100+ users

**Approach:**
- Small model (1.5B) for router only
- Keep 3B model for orchestrator + chat
- Router budget: 300 input + 64 output = 364 token

**Expected Gains:**
- Router latency: 100ms → 50ms
- Cost savings: ~40% (router çok sık çağrılıyor)

---

## 5. Current Status

### Completed (✅)
- Mock server with Turkish pattern matching
- Token tracking in benchmark script
- Baseline metrics (mock): ~110ms p50, 120-220 tok/sec
- Diverse responses (calendar vs smalltalk)

### In Progress (🚧)
- Real vLLM server setup
- iterations=30 benchmark
- Production config tuning

### Blocked (❌)
- None (all dependencies met)

---

## 6. Decision Log

### 2026-01-30: Single Model Strategy Confirmed
**Why:**
- Consistency > speed at MVP stage
- 3B model fast enough for Jarvis UX (target: <200ms p95)
- Simpler deployment (1 model = 1 process = 1 GPU)
- Easy to tune/debug (same model everywhere)

**Risk:**
- Router might be "overkill" (600 token input for 10 token output)
- Mitigation: Prompt compression, optional two-model upgrade

**Next Review:** After real vLLM benchmark (expected: 2-3 days)

---

## 7. References

- Issue #136: https://github.com/miclaldogan/bantz/issues/136
- Issue #138: Benchmark framework (Done)
- vLLM docs: https://docs.vllm.ai/
- Qwen2.5 model card: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct

---

## Appendix: Alternative Models

| Model | Size | Speed | Quality | Notes |
|-------|------|-------|---------|-------|
| Qwen2.5-3B-Instruct | 3B | Fast | Good | **Current choice** |
| Qwen2.5-7B-Instruct | 7B | Medium | Better | Upgrade option |
| Qwen2.5-1.5B-Instruct | 1.5B | Very Fast | OK | Router-only option |
| Llama-3.2-3B-Instruct | 3B | Fast | Good | Alternative to Qwen |

**Choice:** Qwen2.5-3B for Turkish support + speed + quality balance
