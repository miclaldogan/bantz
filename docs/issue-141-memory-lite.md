# Memory-lite Implementation (Issue #141)

## Goal
Implement rolling dialog summary without storing raw CoT or full conversation history.

## Design

### 1. Compact Summary Format
```python
@dataclass
class CompactSummary:
    """Memory-lite: 1-2 sentence summary per turn."""
    turn_number: int
    user_intent: str  # "asked about calendar" | "greeting" | "task request"
    action_taken: str  # "listed events" | "greeted back" | "created meeting"
    pending_items: list[str]  # ["waiting for confirmation", "need time slot"]
    timestamp: datetime
    
    def to_prompt_block(self) -> str:
        """Convert to prompt injection format (max 500 tokens)."""
        lines = [
            f"Turn {self.turn_number}: User {self.user_intent}, "
            f"I {self.action_taken}."
        ]
        if self.pending_items:
            lines.append(f"Pending: {', '.join(self.pending_items)}")
        return " ".join(lines)
```

### 2. PII Filter
```python
import re

class PIIFilter:
    """Remove sensitive information from summaries."""
    
    PATTERNS = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone": r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "address": r'\b\d+\s+[A-Za-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)\b'
    }
    
    @classmethod
    def filter(cls, text: str) -> str:
        """Replace PII with placeholders."""
        filtered = text
        for pii_type, pattern in cls.PATTERNS.items():
            filtered = re.sub(pattern, f"<{pii_type.upper()}>", filtered)
        return filtered
```

### 3. Rolling Window (Max 500 Tokens)
```python
class DialogSummaryManager:
    """Manage rolling dialog summary with token limit."""
    
    def __init__(self, max_tokens: int = 500):
        self.max_tokens = max_tokens
        self.summaries: list[CompactSummary] = []
    
    def add_turn(self, summary: CompactSummary) -> None:
        """Add new turn summary, evict old if over limit."""
        # Filter PII before storing
        summary.user_intent = PIIFilter.filter(summary.user_intent)
        summary.action_taken = PIIFilter.filter(summary.action_taken)
        
        self.summaries.append(summary)
        
        # Evict oldest turns if over token limit
        while self._estimate_tokens() > self.max_tokens and len(self.summaries) > 1:
            self.summaries.pop(0)  # Remove oldest
    
    def _estimate_tokens(self) -> int:
        """Rough token estimation."""
        text = self.to_prompt_block()
        return len(text.split())  # Rough: 1 token ≈ 1 word
    
    def to_prompt_block(self) -> str:
        """Generate DIALOG_SUMMARY block for prompt injection."""
        if not self.summaries:
            return ""
        
        lines = ["DIALOG_SUMMARY (last few turns):"]
        for s in self.summaries[-5:]:  # Last 5 turns max
            lines.append(f"  {s.to_prompt_block()}")
        
        return "\n".join(lines)
```

### 4. Integration with Orchestrator

**In `orchestrator_loop.py`:**
```python
from bantz.brain.memory_lite import DialogSummaryManager, CompactSummary

class OrchestratorLoop:
    def __init__(self, ...):
        self.summary_manager = DialogSummaryManager(max_tokens=500)
    
    def process_turn(self, user_input: str, state: OrchestratorState) -> tuple[OrchestratorOutput, OrchestratorState]:
        # 1. Inject dialog summary into orchestrator prompt
        dialog_summary = self.summary_manager.to_prompt_block()
        
        # 2. Call orchestrator with summary
        output = self.orchestrator.route(
            user_input=user_input,
            dialog_summary=dialog_summary,  # ← Inject here
            session_context=state.session_context
        )
        
        # 3. Generate compact summary from output
        summary = CompactSummary(
            turn_number=state.turn_count + 1,
            user_intent=self._extract_intent(user_input, output),
            action_taken=self._extract_action(output),
            pending_items=self._extract_pending(output),
            timestamp=datetime.now()
        )
        
        # 4. Add to rolling window
        self.summary_manager.add_turn(summary)
        
        # 5. Update state
        state.turn_count += 1
        state.last_summary = summary
        
        return output, state
    
    def _extract_intent(self, user_input: str, output: OrchestratorOutput) -> str:
        """Extract user intent in 1-2 words."""
        if output.route == "calendar":
            return f"asked about {output.calendar_intent}"
        elif output.route == "smalltalk":
            return "casual chat"
        else:
            return "unclear request"
    
    def _extract_action(self, output: OrchestratorOutput) -> str:
        """Extract action taken in 1-2 words."""
        if output.tool_plan:
            tools = ", ".join([t.split(".")[-1] for t in output.tool_plan])
            return f"called {tools}"
        elif output.assistant_reply:
            return "responded with chat"
        else:
            return "asked for clarification"
    
    def _extract_pending(self, output: OrchestratorOutput) -> list[str]:
        """Extract pending items."""
        pending = []
        if output.requires_confirmation:
            pending.append("waiting for confirmation")
        if output.ask_user:
            pending.append(f"need: {output.question[:30]}")
        return pending
```

### 5. Testing

**Test Case 1: Memory Continuity**
```python
def test_memory_continuity():
    """User says 'az önce ne yaptık?' - should recall from summary."""
    
    # Turn 1
    loop.process_turn("bugün neler yapacağız")
    # Summary: "User asked about calendar query, I called list_events"
    
    # Turn 2
    loop.process_turn("az önce ne yaptık?")
    # LLM sees DIALOG_SUMMARY and responds with context
    assert "takvim" in response or "etkinlik" in response
```

**Test Case 2: PII Filtering**
```python
def test_pii_filtering():
    """Ensure PII is not stored in summary."""
    
    loop.process_turn("email gönder: test@example.com")
    summary = loop.summary_manager.summaries[-1]
    
    assert "@" not in summary.user_intent
    assert "<EMAIL>" in summary.user_intent
```

**Test Case 3: Token Limit**
```python
def test_token_limit():
    """Ensure summary stays under 500 tokens."""
    
    # Add 20 turns
    for i in range(20):
        loop.process_turn(f"turn {i}")
    
    summary_text = loop.summary_manager.to_prompt_block()
    token_count = len(summary_text.split())
    
    assert token_count <= 500
```

### 6. Prompt Injection Example

**Before (no memory):**
```
Sen BANTZ. Kullanıcı USER. Türkçe konuş.

USER: az önce ne yaptık?
ASSISTANT (sadece JSON):
```

**After (with memory-lite):**
```
Sen BANTZ. Kullanıcı USER. Türkçe konuş.

DIALOG_SUMMARY (last few turns):
  Turn 1: User asked about calendar query, I called list_events.
  Turn 2: User requested calendar create, I called create_event. Pending: waiting for confirmation

USER: az önce ne yaptık?
ASSISTANT (sadece JSON):
```

Now LLM has context to respond: "Az önce takviminde etkinlikleri listeledim ve yeni bir toplantı oluşturdum efendim. Onayınızı bekliyorum."

## Implementation Plan

### Phase 1: Core Components (1 day)
- [x] CompactSummary dataclass
- [x] PIIFilter with common patterns
- [x] DialogSummaryManager with rolling window
- [ ] Unit tests for each component

### Phase 2: Integration (1 day)
- [ ] Modify orchestrator_loop.py to use memory-lite
- [ ] Update JarvisLLMOrchestrator to accept dialog_summary parameter (✅ already done!)
- [ ] Add summary generation helpers (_extract_intent, _extract_action)
- [ ] Integration tests

### Phase 3: Validation (0.5 days)
- [ ] Test "az önce ne yaptık?" continuity
- [ ] Test PII filtering in real scenarios
- [ ] Test token limit enforcement
- [ ] Document usage in README

## Configuration

**In `config/model-settings.yaml`:**
```yaml
memory:
  max_dialog_summary_tokens: 500
  summary_style: "compact"
  pii_filter_enabled: true
  pii_patterns:
    - email
    - phone
    - credit_card
    - ssn
    - address
```

## Files to Create/Modify

```
src/bantz/brain/memory_lite.py          - NEW: Memory-lite implementation
src/bantz/brain/orchestrator_loop.py    - MODIFY: Integrate memory-lite
tests/test_memory_lite.py               - NEW: Unit tests
docs/issue-141-memory-lite.md           - This file
```

## Benefits

1. **No CoT storage:** Raw reasoning traces are discarded after each turn
2. **PII safety:** Sensitive data filtered before storage
3. **Token budget:** Fixed 500 token limit, won't blow up context
4. **Continuity:** "Az önce ne yaptık?" works via compact summaries
5. **Jarvis feel:** "I remember we just talked about X" without verbosity

## Next Steps

1. Implement `memory_lite.py` module
2. Integrate with `orchestrator_loop.py`
3. Write tests
4. Benchmark: Does summary injection increase latency? (Expected: minimal, <10ms)
5. User testing: Does Jarvis feel more "aware" of conversation history?
