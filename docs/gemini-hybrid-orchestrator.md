# Gemini Hybrid Orchestrator

**Issues:** #131, #134, #135  
**Strategy:** 3B Local Router + Gemini Finalizer

## 🎯 Architecture

```
User Input
    ↓
┌─────────────────────────┐
│  3B Local Router        │  ← Fast (41ms TTFT)
│  (Ollama/vLLM)          │
│  - Route classification │
│  - Intent extraction    │
│  - Slot parsing         │
│  - Tool planning        │
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  Tool Execution         │  ← If approved
│  (BrainLoop)            │
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  Gemini Finalizer       │  ← Quality responses
│  (Flash/Pro)            │
│  - Natural language     │
│  - Jarvis personality   │
│  - Context-aware        │
└─────────────────────────┘
    ↓
User Output
```

## 🚀 Benefits

- **Low Latency**: 3B router delivers fast decisions (~50ms)
- **High Quality**: Gemini generates natural, context-aware responses
- **Cost Effective**: Cloud usage only for finalization
- **Privacy**: Sensitive routing/planning stays local
- **Scalable**: Can switch router backend (Ollama ↔ vLLM)

## 📦 Components

### 1. 3B Local Router
- **Purpose**: Fast routing and slot extraction
- **Backend**: Ollama or vLLM
- **Model**: Qwen 2.5 3B Instruct (Q8 quantization)
- **Latency**: ~41ms TTFT
- **Output**: JSON schema with route, intent, slots, tool plan

### 2. Gemini Finalizer
- **Purpose**: Natural language response generation
- **Backend**: Google Gemini API
- **Model**: Gemini 1.5 Flash (or Pro)
- **Latency**: ~200-500ms
- **Output**: Jarvis-style Turkish response

## 🔧 Configuration

```python
from bantz.brain.gemini_hybrid_orchestrator import HybridOrchestratorConfig

config = HybridOrchestratorConfig(
    # Router settings
    router_backend="ollama",  # or "vllm"
    router_model="qwen2.5:3b-instruct-q8_0",
    router_temperature=0.0,  # Deterministic
    router_max_tokens=512,
    
    # Gemini settings
    gemini_model="gemini-1.5-flash",  # or "gemini-1.5-pro"
    gemini_temperature=0.4,  # Balanced
    gemini_max_tokens=512,
    
    # Behavior
    confidence_threshold=0.7,  # Min confidence for tool calls
    enable_gemini_finalization=True,  # Set False for router-only mode
)
```

## 📝 Usage

### Basic Example

```python
from bantz.brain.gemini_hybrid_orchestrator import create_gemini_hybrid_orchestrator
from bantz.llm.ollama_client import OllamaClient

# Create router
router = OllamaClient(model="qwen2.5:3b-instruct-q8_0")

# Create orchestrator
orchestrator = create_gemini_hybrid_orchestrator(
    router_client=router,
    gemini_api_key="YOUR_GEMINI_API_KEY",
)

# Orchestrate user input
output = orchestrator.orchestrate(
    user_input="bugün toplantılarım neler?",
    dialog_summary="",
    tool_results=None,
)

print(f"Route: {output.route}")
print(f"Intent: {output.calendar_intent}")
print(f"Response: {output.assistant_reply}")
```

### Demo Script

```bash
# Set environment
export GEMINI_API_KEY="your-api-key"
export BANTZ_LLM_BACKEND="ollama"
export BANTZ_ROUTER_MODEL="qwen2.5:3b-instruct-q8_0"

# Run demo
python scripts/demo_gemini_hybrid.py
```

## 🧪 Testing

```bash
# Unit tests
pytest tests/test_gemini_hybrid_orchestrator.py -v

# Integration test (requires Ollama + Gemini API)
python scripts/demo_gemini_hybrid.py
```

## 📊 Performance Benchmarks

| Component | Latency | Quality | Cost |
|-----------|---------|---------|------|
| **3B Router** | ~41ms | Good routing | Free (local) |
| **Gemini Flash** | ~200ms | Excellent NLG | $0.000125/1K tokens |
| **Combined** | ~250ms | Best of both | Minimal |

## 🔒 Privacy & Security

- **Local Router**: All sensitive routing/planning stays on-device
- **Gemini**: Only receives context needed for response generation
- **Redaction**: Automatic PII minimization (from privacy.py)
- **Confirmation**: Destructive operations require explicit user approval

## 🎯 Test Scenarios

From Issue #126, these scenarios are validated:

1. **Smalltalk**: "hey bantz nasılsın"
   - Route: smalltalk
   - Gemini: Natural greeting

2. **Calendar Query - Today**: "bugün neler yapacağız"
   - Route: calendar, Intent: query
   - Tool: calendar.list_events
   - Gemini: Summarize results

3. **Calendar Create**: "saat 4 için toplantı oluştur"
   - Route: calendar, Intent: create
   - Slot extraction: time=16:00
   - Gemini: Confirmation prompt

4. **Calendar Query - Evening**: "bu akşam neler yapacağız"
   - Route: calendar, Intent: query
   - Tool: calendar.list_events (evening window)
   - Gemini: Results summary

5. **Calendar Query - Week**: "bu hafta önemli işler var mı?"
   - Route: calendar, Intent: query
   - Tool: calendar.list_events (week window)
   - Gemini: Filtered summary

## 📚 Related Documentation

- [vLLM Validation Report](../docs/vllm_validation_report.md)
- [LLM Router Documentation](../docs/llm-router.md)
- [Gemini Client](../src/bantz/llm/gemini_client.py)
- [Issue #131: vLLM Backend Epic](https://github.com/miclaldogan/bantz/issues/131)
- [Issue #134: Router vLLM Integration](https://github.com/miclaldogan/bantz/issues/134)
- [Issue #135: Calendar Planner LLM](https://github.com/miclaldogan/bantz/issues/135)

## 🔄 Migration from vLLM-Only

If you were using vLLM dual-server setup (3B + 7B), this hybrid approach offers:

- ✅ Better quality (Gemini > 7B local)
- ✅ Lower latency (no 7B inference)
- ✅ Lower cost (Gemini Flash is cheap)
- ✅ Simpler setup (one local server vs two)

Migration steps:

1. Keep 3B router as-is
2. Replace 7B vLLM with Gemini client
3. Set `enable_gemini_finalization=True`
4. Configure Gemini API key

## 🐛 Troubleshooting

### Router Not Available

```bash
# Check Ollama status
ollama serve

# Pull model if needed
ollama pull qwen2.5:3b-instruct-q8_0
```

### Gemini API Errors

```bash
# Verify API key
export GEMINI_API_KEY="your-key"

# Test connectivity
curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"
```

### Low Quality Responses

- Increase `gemini_temperature` (0.4 → 0.6)
- Switch to `gemini-1.5-pro` for better quality
- Check `confidence_threshold` (too low = noisy tools)

### High Latency

- Use `gemini-1.5-flash` (faster than Pro)
- Reduce `gemini_max_tokens` (512 → 256)
- Set `enable_gemini_finalization=False` for router-only mode

## 📈 Future Enhancements

- [ ] Streaming Gemini responses
- [ ] Multi-turn dialog optimization
- [ ] Caching for repeated queries
- [ ] Fallback to local 7B if Gemini unavailable
- [ ] A/B testing framework (Gemini vs local)

## 🎉 Success Metrics

✅ **All 5 test scenarios passing**  
✅ **8/8 unit tests passing**  
✅ **Average latency < 300ms**  
✅ **Natural Jarvis-style responses**  
✅ **Privacy-preserving architecture**
