"""Tool-call trace viewer — ring buffer + per-tool debug trace (Issue #524).

Provides:
  - ``ToolCallLog``: Ring buffer (collections.deque, maxlen=20) storing
    per-tool-call metadata.
  - ``ToolCallEntry``: Single tool call record with name, params, result,
    success, elapsed_ms, timestamp.
  - ``format_tools_command()``: Renders ``/tools`` output for terminal.
  - Per-tool trace line: ``[tool] calendar.list_events ok 340ms → 3 events``

Usage::

    log = ToolCallLog()
    log.record("calendar.list_events", {"date": "2025-01-15"}, "3 events", True, 340)
    print(log.format_table())
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ToolCallEntry",
    "ToolCallLog",
    "format_tools_command",
]


# ── Entry ─────────────────────────────────────────────────────

@dataclass
class ToolCallEntry:
    """Single tool call record.

    Attributes
    ----------
    tool_name:
        Fully qualified tool name (e.g. ``calendar.list_events``).
    params:
        Parameters passed to the tool.
    result_summary:
        Short summary of the result (≤100 chars).
    success:
        Whether the tool call succeeded.
    elapsed_ms:
        Execution time in milliseconds.
    timestamp:
        When the call was made.
    turn_number:
        Which conversation turn triggered this call.
    retried:
        Whether this was a retry attempt.
    error:
        Error message if success=False.
    """

    tool_name: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    success: bool = True
    elapsed_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    turn_number: int = 0
    retried: bool = False
    error: str = ""

    def to_trace_line(self) -> str:
        """Format as per-tool debug trace line.

        Example: ``[tool] calendar.list_events ok 340ms → 3 events``
        """
        status = "ok" if self.success else "FAIL"
        summary = self.result_summary[:60] if self.result_summary else ""
        if self.error and not self.success:
            summary = self.error[:60]
        retry_tag = " (retry)" if self.retried else ""
        return f"[tool] {self.tool_name} {status} {self.elapsed_ms}ms → {summary}{retry_tag}"

    def to_table_row(self) -> str:
        """Format as table row for /tools command."""
        status = "✓" if self.success else "✗"
        summary = self.result_summary[:40] if self.result_summary else ""
        if self.error and not self.success:
            summary = self.error[:40]
        return f"  {status} {self.tool_name:<30} {self.elapsed_ms:>5}ms  {summary}"


# ── Ring buffer ───────────────────────────────────────────────

class ToolCallLog:
    """Ring buffer of recent tool calls.

    Parameters
    ----------
    maxlen:
        Maximum entries to keep (default: 20).
    """

    def __init__(self, maxlen: int = 20) -> None:
        self._entries: deque[ToolCallEntry] = deque(maxlen=maxlen)
        self._maxlen = maxlen

    def record(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        result_summary: str = "",
        success: bool = True,
        elapsed_ms: int = 0,
        *,
        turn_number: int = 0,
        retried: bool = False,
        error: str = "",
    ) -> ToolCallEntry:
        """Record a tool call.

        Returns the created entry.
        """
        entry = ToolCallEntry(
            tool_name=tool_name,
            params=params or {},
            result_summary=result_summary,
            success=success,
            elapsed_ms=elapsed_ms,
            turn_number=turn_number,
            retried=retried,
            error=error,
        )
        self._entries.append(entry)

        if success:
            logger.debug(entry.to_trace_line())
        else:
            logger.warning(entry.to_trace_line())

        return entry

    @property
    def entries(self) -> List[ToolCallEntry]:
        """All entries (oldest first)."""
        return list(self._entries)

    @property
    def last(self) -> Optional[ToolCallEntry]:
        """Most recent entry."""
        return self._entries[-1] if self._entries else None

    def for_turn(self, turn_number: int) -> List[ToolCallEntry]:
        """Get entries for a specific turn."""
        return [e for e in self._entries if e.turn_number == turn_number]

    def stats(self) -> Dict[str, Any]:
        """Aggregate stats across all entries."""
        total = len(self._entries)
        ok = sum(1 for e in self._entries if e.success)
        fail = total - ok
        retries = sum(1 for e in self._entries if e.retried)
        avg_ms = (
            sum(e.elapsed_ms for e in self._entries) // total
            if total > 0
            else 0
        )
        return {
            "total": total,
            "ok": ok,
            "fail": fail,
            "retries": retries,
            "avg_ms": avg_ms,
        }

    def format_table(self) -> str:
        """Format entries as a table for /tools command output.

        Returns
        -------
        Formatted table string with header and rows.
        """
        if not self._entries:
            return "  (no tool calls recorded)"

        lines = [
            f"  Tool Call Log (last {len(self._entries)}/{self._maxlen}):",
            f"  {'─' * 60}",
        ]
        for entry in self._entries:
            lines.append(entry.to_table_row())
        lines.append(f"  {'─' * 60}")

        s = self.stats()
        lines.append(
            f"  Total: {s['total']}  OK: {s['ok']}  Fail: {s['fail']}  "
            f"Retries: {s['retries']}  Avg: {s['avg_ms']}ms"
        )
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# ── /tools command formatter ──────────────────────────────────

def format_tools_command(log: ToolCallLog) -> str:
    """Format the output for the ``/tools`` terminal command.

    Returns a user-friendly summary with table + stats.
    """
    header = "🔧 Tool Call Trace Viewer"
    body = log.format_table()
    return f"{header}\n{body}"
