# Example: Feature Planning Template

This is a filled-in example for a Jarvis-Calendar planning feature.

---

## Goal

Enable Jarvis to create structured daily plans via natural language and apply them safely to Google Calendar with deterministic confirmation flow.

## Background

Current calendar features (#115, #116) can generate plan drafts and confirm edits, but lack the ability to actually write events to the calendar. Users need a safe, transparent way to:
- See a dry-run preview of what will be created
- Explicitly confirm before any calendar writes happen
- Know if something fails mid-apply (stop-on-first-failure)

## Scope

### In Scope
- Add `calendar.apply_plan_draft` tool with dry-run mode
- Implement 2-turn state machine:
  - Turn A: "Onayla" → dry-run preview + queue pending confirmation
  - Turn B: "1" → real apply + created_count summary
- Stop-on-first-failure: if one event fails, report failed_index + created_count
- Deterministic renderer for apply results
- Unit tests: executor + BrainLoop 2-turn E2E

### Out of Scope
- Retry/rollback on failure (future: #119)
- Bulk update/delete existing events
- Multi-calendar support (always "primary" for now)

## Acceptance Criteria

- [x] `plan_events_from_draft(draft, time_min, time_max)` returns deterministic event list
- [x] `apply_plan_draft(..., dry_run=True)` never calls create_event_fn
- [x] `apply_plan_draft(..., dry_run=False)` stops on first failure and returns failed_index
- [x] Turn A ("onayla") queues pending confirmation with real apply payload
- [x] Turn B ("1") executes the tool and clears pending state
- [x] BrainResult.text includes preview + prompt (UI visibility)
- [x] Trace evidence: queued/seen confirmation in metadata

## How to Test

### Unit Tests
```bash
pytest tests/test_plan_executor.py -v
pytest tests/test_plan_confirmation.py::test_plandraft_apply_state_machine_two_turns -v
```

### Manual / CLI
```bash
python -m bantz.cli --brainloop-demo

# Say: "bugün plan yap"
# System: shows draft preview + confirmation menu
# Say: "onayla"
# System: shows dry-run preview + "1/0" prompt
# Say: "1"
# System: creates events and reports created_count
```

## Dependencies

- Depends on #115 (PlanDraft model)
- Depends on #116 (PlanDraft confirmation/edit loop)
- Requires Google Calendar backend (`src/bantz/google/calendar.py`)
- Requires tool registry (`src/bantz/agent/builtin_tools.py`)

## Notes

- Policy gate: dry-run is LOW risk (no confirmation), real apply is MED risk (requires confirmation)
- Time window persistence: pending_plan stores time_min/time_max so follow-up turns don't need session_context
- EventBus: preview published as RESULT, prompt as QUESTION; BrainResult.text combines both for UI fallback
