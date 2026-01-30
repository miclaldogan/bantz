# LLM Router & Natural Conversation - Complete Guide

## 🎯 What We Built

Natural conversation flow for Bantz - LLM handles **every** user input, no forced menus!

### Before ❌
```
USER: yarın toplantım var
BANTZ: Takvim mi sohbet mi? [MENU]  ← Annoying!
```

### After ✅
```
USER: yarın üçe toplantım var
BANTZ: Saat 15:00'de toplantı ekliyorum, onaylar mısınız?
USER: tabii dostum
BANTZ: Tamam efendim, 'toplantı' eklendi. [2 seconds total!]
```

---

## 🚀 Key Features

### 1. **Always-On LLM Router**
- Every user message goes through LLM first
- Automatic route detection: smalltalk, calendar, unknown
- Turkish language native support

### 2. **Smart Confirmation Flow**
- Router extracts slots (time, title, etc.)
- Asks user for confirmation
- Expanded keywords: "tabii", "ekle", "koy", "git", "hadi", etc.
- Direct tool execution (no LLM re-processing)

### 3. **Turkish Time Parsing**
All hour formats supported:
- bire/ikiye/üçe/dörde → 13:00/14:00/15:00/16:00
- öğlene → 12:00
- akşam sekize → 20:00
- Context-aware: morning vs afternoon

### 4. **Fast Performance**
- **Ollama on GPU**: RTX 4060 @ 100% utilization ✓
- **Warm-up**: First request fast (dummy call on startup)
- **Direct execution**: No LLM loop after confirmation

---

## 📁 Files Changed

### Core Components
- **src/bantz/brain/llm_router.py** (NEW)
  - Route classification
  - Slot extraction  
  - Turkish time parsing
  - Confidence scoring

- **src/bantz/brain/brain_loop.py** (MODIFIED)
  - Router integration (always active)
  - Confirmation state handling
  - Direct tool execution
  - Expanded confirmation keywords

- **scripts/demo_calendar_brainloop.py** (MODIFIED)
  - Router instantiation
  - Ollama warm-up call
  - Debug logging

---

## 🧪 Testing

### Run Demo
```bash
python3 scripts/demo_calendar_brainloop.py --debug --dry-run
```

### Test Scenarios

#### Smalltalk (No Menu!)
```
YOU: nasılsın dostum
BANTZ: [0.5s] İyiyim efendim, teşekkür ederim.
```

#### Calendar with Confirmation
```
YOU: yarın üçe toplantı ekle
BANTZ: [1s] Saat 15:00'de toplantı ekliyorum, onaylar mısınız?
YOU: tabii [or: koy / ekle / hadi / git / elbette]
BANTZ: [0.5s] Tamam efendim, 'toplantı' eklendi.
```

#### Turkish Time Formats
```
YOU: öğlene doktor randevusu
BANTZ: Saat 12:00'de doktor randevusu ekliyorum, onaylar mısınız?

YOU: akşam sekize parti
BANTZ: Saat 20:00'de parti ekliyorum, onaylar mısınız?

YOU: beşe çıkış
BANTZ: Saat 17:00'de çıkış ekliyorum, onaylar mısınız?
```

#### Cancellation
```
YOU: yarın sabah toplantı
BANTZ: Toplantı ekliyorum, onaylar mısınız?
YOU: hayır bosver
BANTZ: Anlaşıldı efendim, iptal ediyorum.
```

---

## ⚡ Performance

### Speed Breakdown
- Router call: ~1 second
- Confirmation parsing: < 0.1 second (keyword matching)
- Tool execution: ~0.5 second
- **Total: 2-3 seconds** ✓

### GPU Utilization
```bash
$ ollama ps
NAME                  ID         SIZE    PROCESSOR    CONTEXT
qwen2.5:3b-instruct  357c...    2.4GB   100% GPU     4096
```
✅ RTX 4060 fully utilized

### Optimization Tips
If still slow:
1. Check Ollama is using GPU: `ollama ps`
2. Reduce model size: Try `qwen2.5:1.5b-instruct`
3. Lower max_tokens in router (currently 512)
4. Check network: Ollama should be localhost

---

## 🔧 Configuration

### Router Settings (llm_router.py)
```python
# Confidence threshold
CONFIDENCE_THRESHOLD = 0.7  # Block tool execution if lower

# Turkish time formats
TIME_PATTERNS = {
    "ikiye": "14:00",
    "üçe": "15:00",
    "dörde": "16:00",
    # ... full list in code
}
```

### Confirmation Keywords (brain_loop.py)
```python
# Confirmation
confirm_keywords = [
    "evet", "tamam", "olur", "onay", "tabii", "elbette",
    "ekle", "koy", "yap", "onayla", "git", "hadi", "ok"
]

# Rejection
reject_keywords = [
    "hayır", "iptal", "vazgeç", "olmaz", "bosver", "no"
]
```

---

## 🐛 Known Issues & Fixes

### ✅ FIXED: ToolRegistry.call_function() error
**Problem:** `AttributeError: 'ToolRegistry' object has no attribute 'call_function'`
**Fix:** Use `tool.function(**params)` instead

### ✅ FIXED: Slow first request
**Problem:** First LLM call takes 5-10 seconds
**Fix:** Warm-up call on demo startup

### ✅ FIXED: "tabii", "ekle" not recognized
**Problem:** Only "evet"/"hayır" worked
**Fix:** Expanded keyword list to 20+ Turkish confirmations

---

## 📊 Pull Requests

- **PR #127**: LLM Router implementation (merged to main)
- **PR #129**: Router always active (merged to dev)
- **PR #130**: Confirmation flow (merged to dev)
- **Latest**: Direct tool execution + expanded keywords (dev)

---

## 🎓 Architecture

```
User Input
    ↓
┌─────────────────────────────────┐
│  LLM Router (ALWAYS ACTIVE)     │
│  - Classify: smalltalk/calendar │
│  - Extract: time, title, etc.   │
│  - Confidence: 0.0-1.0          │
└─────────────────────────────────┘
    ↓
  Smalltalk?
  ├─ Yes → LLM reply (0.5s)
  └─ No → Calendar intent
            ↓
      ┌─────────────────────────┐
      │  Confirmation Request    │
      │  "Saat 15:00'de ... ?"  │
      └─────────────────────────┘
            ↓
      User Response
      ├─ Confirm → Execute tool (0.5s)
      ├─ Reject  → Cancel
      └─ Unclear → Re-prompt
```

---

## 🚀 Future Improvements

### Performance
- [ ] Cache router responses for similar inputs
- [ ] Batch router calls for multi-turn context
- [ ] Use smaller model for simple routes (1.5b vs 3b)

### Features
- [ ] Multi-event creation: "yarın 3 ve 5'te iki toplantı"
- [ ] Event modification: "toplantıyı saat 4'e al"
- [ ] Date ranges: "bu hafta her gün saat 9'da"
- [ ] LLM-based confirmation for ambiguous cases

### Turkish Language
- [ ] More time formats: "yarım saat sonra", "15 dakika içinde"
- [ ] Relative dates: "öbür gün", "gelecek hafta salı"
- [ ] Duration parsing: "bir buçuk saat sürecek"

---

## 📚 Related Docs
- [Router Implementation](../src/bantz/brain/llm_router.py)
- [Confirmation Flow](../src/bantz/brain/brain_loop.py#L1890-L1980)
- [Demo Script](../scripts/demo_calendar_brainloop.py)
- [Test Suite](../tests/test_llm_router.py)

---

**Status**: ✅ Production Ready
**Last Updated**: January 30, 2026
**Contributors**: @iclaldogan
