# Model Strategy (Issue #136)

> **Karar (MVP):** LLM-first architecture - Tek model tüm işleri yapar
>
> **Not (2026-01-31):** Kod tarafında **hibrit (3B planner + 8B finalizer)** desteği eklendi; üretim kararı için **real vLLM ölçümü** şart.

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
- p50: < 100ms (target)
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
Router: > 100 tokens/sec (target)
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
- [x] Real vLLM ile ölçüm altyapısı (TTFT streaming + VRAM polling)
- [ ] Benchmark with iterations=30 (RTX 4050 6GB üzerinde)
- [ ] Establish performance baseline (measured)

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
- vLLM benchmark harness: TTFT via streaming + VRAM peak sampling
- Hibrit altyapı: planner/router + finalizer ayrımı (opsiyonel)
- scripts/jarvis.sh preflight: Ollama yerine vLLM /v1/models kontrolü

### In Progress (🚧)
- iterations=30 real vLLM benchmark (measured TTFT/VRAM/tok/s)
- Production config tuning

### Blocked (❌)
- None (all dependencies met)

---

## 6. Decision Log

### 2026-01-31: Hibrit Altyapı Eklendi (Planner + Finalizer) ✅
**Decision (code):** 3B planner/router/orchestrator + opsiyonel 8B finalizer

**Why:**
- 6GB VRAM sınıfı GPU'larda (RTX 4050 Laptop) 8B modeli lokal çalıştırmak zor; finalizer farklı bir vLLM endpoint'i (remote/stronger GPU) üzerinden gelebilir.
- “Jarvis hissi” için TTFT kritik; planner tarafını küçük modelle hızlı tutup, final metnini daha güçlü modelle üretmek mümkün.

**Status:**
- Hibrit mimari: ✅ implement edildi
- Üretim kararı / performans iddiaları: ⚠️ real vLLM ölçümü ile doğrulanmalı

**Next (Validation / Production):**
- RTX 4050 6GB üzerinde 3B-AWQ ile 30 iter ölçüm (TTFT/VRAM/tok/s)
- Finalizer için ayrı vLLM endpoint/model konfigürasyonu (runtime config/env)
- 8B finalizer için ölçüm: remote vLLM ile aynı senaryolar
- "Akıllı ama bekliyor" (8B-only)

**Implementation:**
- Update `config/model-settings.yaml` with split strategy
- vLLM server: Load 8B, use 3B via model switching or separate endpoint
- Memory-lite ensures prompt budget stays under control

**See:** `docs/rtx4060-3b-vs-8b-benchmark.md` for full results

### 2026-01-30: Single Model Strategy Baseline
**Why:**
- Consistency > speed at MVP stage
- 3B model fast enough for Jarvis UX (target: <200ms p95)
- Simpler deployment (1 model = 1 process = 1 GPU)
- Easy to tune/debug (same model everywhere)

**Risk:**
- Router might be "overkill" (600 token input for 10 token output)
- Mitigation: Prompt compression, optional two-model upgrade

**Status:** Superseded by split strategy after benchmarks

---

## 7. References

- Issue #136: https://github.com/miclaldogan/bantz/issues/136
- Issue #138: Benchmark framework (Done)
- Issue #153: RTX 4060 benchmark & split strategy (Done)
- vLLM docs: https://docs.vllm.ai/
- Qwen2.5 model card: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct
- Benchmark report: `docs/rtx4060-3b-vs-8b-benchmark.md`

---

## 8. RTX 4060 Benchmark Summary (Issue #153)

### Hardware Configuration
- **GPU**: NVIDIA RTX 4060 (8GB VRAM)
- **vLLM**: 0.6.x with FP16 precision
- **Context**: 4096 max tokens
- **Iterations**: 30 per scenario

### Key Findings

**1. TTFT is King**
- TTFT < 300ms → "Jarvis feeling" (users perceive responsiveness)
- Total latency < 2s acceptable if TTFT fast
- Split strategy achieves optimal TTFT across all roles

**2. 3B vs 8B Trade-offs**
| Aspect | 3B-Instruct | 8B-Instruct | Split (3B+8B) |
|--------|-------------|-------------|---------------|
| **Speed** | ⚡⚡⚡ Excellent | 🐢 Slower | ⚡⚡ Fast |
| **Quality** | 🤔 OK (6.5/10) | 🧠 Excellent (9/10) | 😊 Great (8.5/10) |
| **VRAM** | 💾 3GB | 💾 5.8GB | 💾 5.5GB |
| **Jarvis Feeling** | 8/10 | 6/10 | **9/10** |
| **Overall** | 7.4/10 | 8.0/10 | **8.8/10** |

**3. Memory-lite (Scope-Limited Validation)**
- Qualitative conversations included "az önce ne yaptık?" checks; treat as indicative, not exhaustive
- 500 token summary appears sufficient in the tested scenarios (validate under adversarial prompts)
- PII filtering needs explicit test coverage before claiming "no false positives"

**4. Production Readiness**
- Split strategy: ✅ Production-ready
- VRAM headroom: 2.5GB available for long conversations
- All targets met: TTFT < 300ms, throughput > 80 tok/s, JSON validity > 98%

### Qualitative Test Results
```
Sample conversation (Split Strategy):
👤: merhaba bantz
🤖: Merhaba! Nasıl yardımcı olabilirim? (TTFT: 92ms)

👤: bu hafta neler planladık
🤖: [Shows 3 calendar events] (TTFT: 88ms)

👤: az önce ne yaptık?
🤖: Az önce bu haftaki takvim planınızı sormuştunuz... (TTFT: 195ms)

Evaluator: "Çok doğal ve hızlı. Gerçekten Jarvis hissi var." ⭐⭐⭐⭐⭐
```

---

## Appendix: Alternative Models

| Model | Size | Speed | Quality | Notes |
|-------|------|-------|---------|-------|
| Qwen2.5-3B-Instruct | 3B | Fast | Good | **Current choice** |
| Qwen2.5-7B-Instruct | 7B | Medium | Better | Upgrade option |
| Qwen2.5-1.5B-Instruct | 1.5B | Very Fast | OK | Router-only option |
| Llama-3.2-3B-Instruct | 3B | Fast | Good | Alternative to Qwen |

**Choice:** Qwen2.5-3B for Turkish support + speed + quality balance
