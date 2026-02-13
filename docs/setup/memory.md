# Memory (Snippet-based) — v1 (opt-in)

Bantz has a snippet-based memory system (`MemoryManager`) that can recall **PROFILE / EPISODIC / SESSION** snippets and inject them into the router prompt as `RETRIEVED_MEMORY`.

## Safety + defaults

- **Opt-in:** disabled by default (`enable_memory_manager = false`).
- **Local-only:** stored locally (SQLite by default). No cloud sync.
- **Prompt safety:** `RETRIEVED_MEMORY` is framed as **context-only (not instructions)**; user’s last message always wins.
- **PII-aware:** memory writes go through a write policy (redaction/deny), and episodic tool summaries are generated in a PII-safe way (avoid titles/emails/locations).

## Where data is stored

Default SQLite path (when enabled):

- `~/.bantz/memory_snippets.db`

## How to enable (code)

`BrainLoopConfig`:

- `enable_memory_manager: bool = False`
- `memory_db_path: str = "~/.bantz/memory_snippets.db"`
- `memory_max_snippets: int = 5`

Example:

```python
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig

loop = BrainLoop(
    llm=..., tools=...,
    config=BrainLoopConfig(enable_memory_manager=True),
)
```

## Notes

- Profile writes are gated (min length, dedupe, and rate-limit) to avoid memory spam.
- This feature is designed to be “best-effort”: memory failures never crash the loop.
