"""Memory trace + enhanced retrieval (Issue #521).

Adds trace/debug visibility to memory injection, trim warnings,
configurable token budget, and enriched summary format.

Improvements over base memory_lite:
  - ``MemoryTracer``: tracks injection & trim events per turn
  - Configurable budget via env: ``BANTZ_MEMORY_MAX_TOKENS`` (default: 800)
  - Enhanced summary: preserves key data (names, dates, counts)
  - Golden test support: 2-turn anaphora resolution
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryTracer",
    "MemoryTraceRecord",
    "EnhancedSummary",
    "MemoryBudgetConfig",
]


# ── Budget config ─────────────────────────────────────────────

@dataclass
class MemoryBudgetConfig:
    """Configurable memory token budget.

    Env vars::

        BANTZ_MEMORY_MAX_TOKENS=800   (was 500, increased for better recall)
        BANTZ_MEMORY_MAX_TURNS=10
        BANTZ_MEMORY_PII_FILTER=true
    """

    max_tokens: int = 800
    max_turns: int = 10
    pii_filter: bool = True

    @classmethod
    def from_env(cls) -> "MemoryBudgetConfig":
        try:
            max_tokens = int(os.getenv("BANTZ_MEMORY_MAX_TOKENS", "800"))
        except ValueError:
            max_tokens = 800
        try:
            max_turns = int(os.getenv("BANTZ_MEMORY_MAX_TURNS", "10"))
        except ValueError:
            max_turns = 10
        pii = os.getenv("BANTZ_MEMORY_PII_FILTER", "true").strip().lower() not in {"0", "false", "no"}
        return cls(max_tokens=max_tokens, max_turns=max_turns, pii_filter=pii)


# ── Trace record ──────────────────────────────────────────────

@dataclass
class MemoryTraceRecord:
    """Record of memory injection for a single turn."""

    turn_number: int = 0
    memory_injected: bool = False
    memory_tokens: int = 0
    memory_turns_count: int = 0
    was_trimmed: bool = False
    original_tokens: int = 0
    after_trim_tokens: int = 0
    trim_reason: str = ""  # "token_budget" | "max_turns" | ""

    def to_trace_line(self) -> str:
        parts = [f"[memory] injected={self.memory_injected}"]
        parts.append(f"tokens={self.memory_tokens}")
        parts.append(f"turns={self.memory_turns_count}")
        if self.was_trimmed:
            parts.append(f"TRIMMED original={self.original_tokens} after={self.after_trim_tokens}")
            if self.trim_reason:
                parts.append(f"reason={self.trim_reason}")
        return " ".join(parts)


# ── Enhanced summary ──────────────────────────────────────────

@dataclass
class EnhancedSummary:
    """Enhanced summary that preserves key data for anaphora resolution.

    Unlike basic CompactSummary which only stores "user asked about X",
    this preserves names, dates, counts, and references.
    """

    turn_number: int = 0
    user_intent: str = ""
    action_taken: str = ""
    key_entities: List[str] = field(default_factory=list)  # ["Ali", "toplantı", "14:00"]
    result_count: Optional[int] = None  # e.g. 3 events found
    tool_used: str = ""
    pending_items: List[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Format for prompt injection with entity preservation."""
        line = f"Turn {self.turn_number}: User {self.user_intent}, I {self.action_taken}."
        if self.key_entities:
            line += f" Key data: {', '.join(self.key_entities)}."
        if self.result_count is not None:
            line += f" ({self.result_count} results)"
        if self.tool_used:
            line += f" [tool: {self.tool_used}]"
        if self.pending_items:
            line += f" Pending: {', '.join(self.pending_items)}"
        return line


# ── Memory tracer ─────────────────────────────────────────────

class MemoryTracer:
    """Tracks memory injection and trim events.

    Use before and after prompt injection to record what happened
    to the memory block during a turn.

    Parameters
    ----------
    budget:
        Memory budget config (for threshold checks).
    """

    def __init__(self, budget: Optional[MemoryBudgetConfig] = None) -> None:
        self.budget = budget or MemoryBudgetConfig()
        self._records: List[MemoryTraceRecord] = []
        self._current: Optional[MemoryTraceRecord] = None

    def begin_turn(self, turn_number: int) -> None:
        """Start tracing a new turn."""
        self._current = MemoryTraceRecord(turn_number=turn_number)

    def record_injection(
        self,
        memory_text: str,
        turns_count: int,
        *,
        token_estimator=None,
    ) -> None:
        """Record memory injection into prompt.

        Parameters
        ----------
        memory_text:
            The actual text injected into the prompt.
        turns_count:
            Number of turns in the memory block.
        token_estimator:
            Callable(str) → int for token counting. Defaults to len//4.
        """
        if self._current is None:
            return

        estimator = token_estimator or (lambda s: len(s) // 4)
        tokens = estimator(memory_text) if memory_text else 0

        self._current.memory_injected = bool(memory_text.strip())
        self._current.memory_tokens = tokens
        self._current.memory_turns_count = turns_count

        if self._current.memory_injected:
            logger.debug(
                "[memory] injected=%s tokens=%d turns=%d",
                self._current.memory_injected,
                tokens,
                turns_count,
            )

    def record_trim(
        self,
        original_tokens: int,
        after_tokens: int,
        reason: str = "token_budget",
    ) -> None:
        """Record that memory was trimmed.

        Parameters
        ----------
        original_tokens:
            Token count before trim.
        after_tokens:
            Token count after trim.
        reason:
            Why trimmed: "token_budget" or "max_turns".
        """
        if self._current is None:
            return

        self._current.was_trimmed = True
        self._current.original_tokens = original_tokens
        self._current.after_trim_tokens = after_tokens
        self._current.trim_reason = reason

        logger.warning(
            "[memory] TRIMMED: original=%d after=%d reason=%s",
            original_tokens,
            after_tokens,
            reason,
        )

    def end_turn(self) -> Optional[MemoryTraceRecord]:
        """Finalize current turn and return the record."""
        rec = self._current
        if rec is not None:
            self._records.append(rec)
        self._current = None
        return rec

    @property
    def records(self) -> List[MemoryTraceRecord]:
        """All recorded trace entries."""
        return list(self._records)

    @property
    def last(self) -> Optional[MemoryTraceRecord]:
        """Most recent trace record."""
        return self._records[-1] if self._records else None

    def clear(self) -> None:
        """Reset all trace records."""
        self._records.clear()
        self._current = None
