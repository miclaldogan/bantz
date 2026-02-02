# Confirmation Firewall (Issue #160)

**Priority:** P1 (Security/UX)

## Overview

The Confirmation Firewall is a security feature that prevents accidental execution of destructive operations. It ensures that **destructive tools always require user confirmation**, even if the LLM forgets to request it.

## Philosophy

"LLM controls everything" — but with guardrails. The firewall acts as a safety layer that cannot be bypassed by the LLM.

## Risk Classification

All tools are classified into three risk levels:

### SAFE (🟢)
Read-only operations with no side effects:
- `web.search` - Search the web
- `web.open` - Open and read webpage content
- `calendar.list_events` - List calendar events
- `calendar.find_event` - Find specific event
- `file.read` - Read file contents
- `vision.screenshot` - Take screenshot
- `vision.analyze` - Analyze image

### MODERATE (🟡)
State changes that are reversible:
- `calendar.create_event` - Create calendar event
- `calendar.update_event` - Update existing event
- `notification.send` - Send system notification
- `clipboard.set` - Set clipboard content
- `file.write` - Write to file
- `browser.open` - Open browser
- `email.send` - Send email

### DESTRUCTIVE (🔴)
Dangerous operations requiring confirmation:
- `calendar.delete_event` - **Delete calendar event**
- `file.delete` - **Delete file permanently**
- `file.move` - **Move/rename file**
- `browser.submit_form` - **Submit form (payments, etc.)**
- `payment.submit` - **Submit payment**
- `system.shutdown` - **Shutdown computer**
- `system.execute_command` - **Execute shell command**
- `app.close` - **Close application**

## How It Works

### 1. Tool Risk Registry

All tools are registered with their risk level:

```python
from bantz.tools.metadata import ToolRisk, TOOL_REGISTRY

# Check tool risk
risk = get_tool_risk("calendar.delete_event")  # ToolRisk.DESTRUCTIVE
```

### 2. Confirmation Firewall

The executor enforces confirmation for DESTRUCTIVE tools:

```python
from bantz.agent.executor import Executor

executor = Executor(tools)
result = executor.execute(step, runner=runner)

if result.awaiting_confirmation:
    # Show confirmation prompt to user
    print(result.confirmation_prompt)
    # "Delete calendar event 'evt123'? This cannot be undone."
    
    # After user confirms:
    executor.confirm_action(step)
    result = executor.execute(step, runner=runner)
```

### 3. LLM Cannot Override

**Critical Security Feature:** Even if the LLM outputs `requires_confirmation: false`, the firewall enforces confirmation for DESTRUCTIVE tools.

```python
from bantz.tools.metadata import requires_confirmation

# LLM says no confirmation needed
llm_requested = False

# Firewall overrides for DESTRUCTIVE tools
needs_confirmation = requires_confirmation(
    "calendar.delete_event",
    llm_requested=llm_requested
)
# ✅ Returns True (firewall override)
```

### 4. Audit Logging

All tool executions are logged with risk level and confirmation status:

```jsonl
{
  "ts": "2026-02-02T10:30:00+0000",
  "event_type": "tool_execution",
  "tool_name": "calendar.delete_event",
  "risk_level": "destructive",
  "success": true,
  "confirmed": true,
  "params": {"event_id": "evt123"},
  "result": {"deleted": "evt123"}
}
```

## Usage Examples

### Example 1: Safe Tool (No Confirmation)

```python
# User: "search for python tutorials"
# LLM decides: web.search (SAFE)

tool_name = "web.search"
params = {"query": "python tutorials"}

# Execute immediately (no confirmation needed)
result = tool.function(**params)
# ✅ Executes without confirmation
```

### Example 2: Destructive Tool (Confirmation Required)

```python
# User: "delete my 3pm meeting"
# LLM decides: calendar.delete_event (DESTRUCTIVE)

tool_name = "calendar.delete_event"
params = {"event_id": "evt123"}

# First attempt - blocked by firewall
result = executor.execute(step, runner=runner)
assert result.awaiting_confirmation is True
print(result.confirmation_prompt)
# "Delete calendar event 'evt123'? This cannot be undone."

# User confirms (via voice/UI)
executor.confirm_action(step)

# Second attempt - executes
result = executor.execute(step, runner=runner)
assert result.ok is True
# ✅ Event deleted after confirmation
```

### Example 3: LLM Override Prevention

```python
# LLM output:
# {
#   "tool_plan": ["calendar.delete_event"],
#   "requires_confirmation": false,  # ❌ LLM forgot!
#   "slots": {"event_id": "evt123"}
# }

# Firewall catches this:
from bantz.tools.metadata import is_destructive, requires_confirmation

if is_destructive("calendar.delete_event"):
    # Override LLM decision
    needs_confirmation = True
    logger.warning(
        "[FIREWALL] calendar.delete_event is DESTRUCTIVE but LLM didn't "
        "request confirmation. Enforcing confirmation requirement."
    )
# ✅ Confirmation enforced despite LLM forgetting
```

## Orchestrator Integration

The orchestrator loop automatically enforces the firewall:

```python
from bantz.brain.orchestrator_loop import OrchestratorLoop

loop = OrchestratorLoop(
    orchestrator=orchestrator,
    tools=tools,
    event_bus=event_bus,
    audit_logger=audit_logger,  # Optional: for tool execution auditing
)

# Process user input
output, state = loop.process_turn(user_input, state)

# If destructive tool pending:
if state.has_pending_confirmation():
    confirmation = state.get_pending_confirmation()
    print(confirmation["prompt"])  # Show to user
    
    # After user confirms:
    state.clear_pending_confirmation()
    output, state = loop.process_turn("yes", state)
```

## Adding New Tools

When adding new tools, classify them appropriately:

```python
from bantz.tools.metadata import register_tool_risk, ToolRisk

# Register new destructive tool
register_tool_risk("database.drop_table", ToolRisk.DESTRUCTIVE)

# Register new safe tool
register_tool_risk("api.get_status", ToolRisk.SAFE)

# Register new moderate tool
register_tool_risk("settings.update", ToolRisk.MODERATE)
```

## Testing

```bash
# Run confirmation firewall tests
pytest tests/test_confirmation_firewall.py -v

# Test specific scenario
pytest tests/test_confirmation_firewall.py::test_firewall_prevents_llm_override -v
```

## Audit Log Analysis

Query audit logs for security analysis:

```python
from bantz.logs.logger import JsonlLogger
import json

logger = JsonlLogger(path="artifacts/logs/bantz.log.jsonl")

# Get recent tool executions
logs = logger.tail(100)

# Filter destructive tools
destructive = [
    log for log in logs
    if log.get("risk_level") == "destructive"
]

# Check confirmation compliance
unconfirmed = [
    log for log in destructive
    if not log.get("confirmed")
]

if unconfirmed:
    print(f"⚠️  {len(unconfirmed)} destructive tools executed without confirmation!")
```

## Configuration

Customize firewall behavior:

```python
from bantz.brain.orchestrator_loop import OrchestratorConfig

config = OrchestratorConfig(
    # Override which tools require confirmation
    # (Note: DESTRUCTIVE tools always require it)
    require_confirmation_for=[
        "calendar.delete_event",
        "calendar.update_event",
        "calendar.create_event",  # Even creates need confirmation
    ],
    enable_safety_guard=True,  # Enable safety checks
)
```

## Security Benefits

1. **User Always in Control**
   - Destructive operations cannot happen without explicit confirmation
   - LLM cannot bypass this requirement

2. **Prevents Accidents**
   - Protects against LLM hallucinations
   - Prevents accidental deletions
   - Guards against misinterpreted commands

3. **Audit Trail**
   - Complete log of all tool executions
   - Risk level tracking
   - Confirmation status recording
   - Compliance-ready logging

4. **Layered Security**
   - Firewall (confirmation)
   - Safety Guard (policy checks)
   - Audit Logging (compliance)

## UI/Voice Integration

### Voice Confirmation Flow

```
User: "delete my 3pm meeting"
  ↓
Jarvis: "I found your 3pm meeting 'Team Standup'. 
         Are you sure you want to delete it? This cannot be undone."
  ↓
User: "yes" / "confirm" / "do it"
  ↓
Jarvis: "Meeting deleted successfully."
```

### Overlay UI Confirmation

```
┌─────────────────────────────────────────┐
│  ⚠️  Confirmation Required               │
├─────────────────────────────────────────┤
│  Delete calendar event 'Team Standup'?  │
│  This cannot be undone.                 │
│                                         │
│  [Yes, Delete]    [Cancel]              │
└─────────────────────────────────────────┘
```

## Troubleshooting

### Issue: Tool Blocked Unexpectedly

**Symptom:** Tool execution returns `awaiting_confirmation=True`

**Solution:** Check if tool is DESTRUCTIVE:
```python
from bantz.tools.metadata import get_tool_risk
risk = get_tool_risk("your.tool.name")
print(f"Risk level: {risk.value}")
```

### Issue: Confirmation Not Working

**Symptom:** Tool still blocked after confirmation

**Solution:** Ensure you're calling `confirm_action()`:
```python
executor.confirm_action(step)
result = executor.execute(step, runner=runner)
```

### Issue: Want to Skip Confirmation (Testing)

**Solution:** Use `skip_confirmation=True`:
```python
result = executor.execute(
    step,
    runner=runner,
    skip_confirmation=True  # For testing only!
)
```

## References

- Issue #160: Epic LLM-6: Confirmation Firewall
- Code: `src/bantz/tools/metadata.py`
- Tests: `tests/test_confirmation_firewall.py`
- Integration: `src/bantz/brain/orchestrator_loop.py`
