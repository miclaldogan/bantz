"""Typed exceptions + correlation ID for the Bantz brain (Issue #525).

Replaces bare ``except Exception: pass`` patterns with structured,
categorized exception types and per-turn correlation logging.

Exception hierarchy::

    BantzError
    ├── RouterParseError       — LLM returned unparseable JSON
    ├── ToolExecutionError     — Tool call failed (timeout, API, etc.)
    ├── FinalizerError         — Finalization phase failed
    ├── MemoryError_           — Memory injection / trim failed
    └── SafetyViolationError   — Policy / safety guard rejection

Correlation ID::

    Every turn gets a unique ``turn_id`` (UUID4 prefix) that appears in
    all log lines emitted during that turn, enabling log correlation
    across router → tools → finalizer → memory.

Usage::

    from bantz.brain.exceptions import (
        RouterParseError,
        ToolExecutionError,
        FinalizerError,
        generate_turn_id,
    )

    turn_id = generate_turn_id()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RouterParseError(
            "LLM returned invalid JSON",
            turn_id=turn_id,
            raw_text=raw[:200],
        ) from e
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "BantzError",
    "RouterParseError",
    "ToolExecutionError",
    "FinalizerError",
    "MemoryError_",
    "SafetyViolationError",
    "generate_turn_id",
    "ErrorContext",
]


# ── Correlation ID ────────────────────────────────────────────

def generate_turn_id() -> str:
    """Generate a short, unique turn correlation ID.

    Format: ``t-<8-hex>`` (e.g. ``t-a1b2c3d4``).
    Short enough for log lines, unique enough for correlation.
    """
    return f"t-{uuid.uuid4().hex[:8]}"


# ── Error context ─────────────────────────────────────────────

@dataclass
class ErrorContext:
    """Structured context attached to every Bantz exception.

    Enables post-mortem debugging without guesswork.
    """

    turn_id: str = ""
    phase: str = ""          # "router" | "tool" | "finalizer" | "memory" | "safety"
    component: str = ""      # e.g. "llm_router._parse_json"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_log_dict(self) -> Dict[str, Any]:
        """Flatten to dict for structured logging."""
        d: Dict[str, Any] = {
            "turn_id": self.turn_id,
            "phase": self.phase,
            "component": self.component,
            "timestamp": self.timestamp,
        }
        d.update(self.metadata)
        return d


# ── Base exception ────────────────────────────────────────────

class BantzError(Exception):
    """Base exception for all Bantz brain errors.

    Every subclass carries an :class:`ErrorContext` for correlation
    and structured logging.
    """

    def __init__(
        self,
        message: str = "",
        *,
        turn_id: str = "",
        phase: str = "",
        component: str = "",
        context: Optional[ErrorContext] = None,
        **metadata: Any,
    ) -> None:
        self.bantz_message = message
        self.context = context or ErrorContext(
            turn_id=turn_id,
            phase=phase,
            component=component,
            metadata=metadata,
        )
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        parts = []
        if self.context.turn_id:
            parts.append(f"[turn:{self.context.turn_id}]")
        if self.context.phase:
            parts.append(f"[{self.context.phase}]")
        parts.append(self.bantz_message)
        return " ".join(parts)

    def log(self, level: int = logging.WARNING) -> None:
        """Emit a structured log line for this error."""
        logger.log(
            level,
            "%s: %s | context=%s",
            type(self).__name__,
            self.bantz_message,
            self.context.to_log_dict(),
            exc_info=(level >= logging.ERROR),
        )


# ── Typed exceptions ─────────────────────────────────────────

class RouterParseError(BantzError):
    """LLM router returned unparseable or invalid JSON.

    Attributes
    ----------
    raw_text:
        The raw LLM output that failed to parse (truncated).
    """

    def __init__(
        self,
        message: str = "Router JSON parse failed",
        *,
        turn_id: str = "",
        raw_text: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            turn_id=turn_id,
            phase="router",
            component="llm_router._parse_json",
            raw_text=raw_text[:200],
            **kwargs,
        )
        self.raw_text = raw_text[:200]


class ToolExecutionError(BantzError):
    """Tool call failed during execution.

    Attributes
    ----------
    tool_name:
        Which tool failed.
    original_error:
        The underlying exception message.
    """

    def __init__(
        self,
        message: str = "Tool execution failed",
        *,
        turn_id: str = "",
        tool_name: str = "",
        original_error: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            turn_id=turn_id,
            phase="tool",
            component=f"tool.{tool_name}",
            tool_name=tool_name,
            original_error=original_error,
            **kwargs,
        )
        self.tool_name = tool_name
        self.original_error = original_error


class FinalizerError(BantzError):
    """Finalization phase failed (Gemini / 3B / deterministic).

    Attributes
    ----------
    finalizer_type:
        Which finalizer was used ("gemini", "3b", "deterministic").
    """

    def __init__(
        self,
        message: str = "Finalization failed",
        *,
        turn_id: str = "",
        finalizer_type: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            turn_id=turn_id,
            phase="finalizer",
            component=f"finalizer.{finalizer_type}",
            finalizer_type=finalizer_type,
            **kwargs,
        )
        self.finalizer_type = finalizer_type


class MemoryError_(BantzError):
    """Memory injection or trim operation failed.

    Named ``MemoryError_`` (trailing underscore) to avoid shadowing
    the built-in ``MemoryError``.

    Attributes
    ----------
    operation:
        What failed: "injection", "trim", "summarize".
    """

    def __init__(
        self,
        message: str = "Memory operation failed",
        *,
        turn_id: str = "",
        operation: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            turn_id=turn_id,
            phase="memory",
            component=f"memory.{operation}",
            operation=operation,
            **kwargs,
        )
        self.operation = operation


class SafetyViolationError(BantzError):
    """Safety guard or policy violation detected.

    Attributes
    ----------
    violation_type:
        Kind of violation: "tool_blocked", "route_mismatch", "denylist".
    tool_name:
        Tool that triggered the violation (if applicable).
    """

    def __init__(
        self,
        message: str = "Safety violation",
        *,
        turn_id: str = "",
        violation_type: str = "",
        tool_name: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            turn_id=turn_id,
            phase="safety",
            component="safety_guard",
            violation_type=violation_type,
            tool_name=tool_name,
            **kwargs,
        )
        self.violation_type = violation_type
        self.tool_name = tool_name
