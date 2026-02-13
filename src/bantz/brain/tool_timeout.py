"""
Tool Execution Timeout & Circuit Breaker — Issue #431.

Provides:
- Per-tool timeout enforcement (default 10s, configurable per tool)
- Graceful error + user message on timeout
- Tool metadata timeout_seconds field
- CircuitBreaker: N consecutive timeouts → temporarily disable tool
- execute_with_timeout() wrapper for orchestrator

Usage::

    from bantz.brain.tool_timeout import ToolTimeoutManager, execute_with_timeout
    manager = ToolTimeoutManager()
    result = await execute_with_timeout(manager, "calendar.create_event", coro)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Default Timeouts
# ─────────────────────────────────────────────────────────────────

# Per-tool timeout in seconds (override via config or metadata)
_DEFAULT_TIMEOUT_S = 10.0

_TOOL_TIMEOUTS: Dict[str, float] = {
    # Calendar tools — Google API can be slow
    "calendar.list_events": 10.0,
    "calendar.create_event": 15.0,
    "calendar.update_event": 15.0,
    "calendar.delete_event": 10.0,
    "calendar.find_free_slots": 12.0,
    # Gmail tools
    "gmail.list_messages": 10.0,
    "gmail.get_message": 8.0,
    "gmail.send": 15.0,
    "gmail.smart_search": 12.0,
    "gmail.archive": 8.0,
    "gmail.generate_reply": 20.0,
    # System tools (fast)
    "time.now": 2.0,
    "system.status": 5.0,
    "system.open_app": 10.0,
    "system.shutdown": 5.0,
    # Browser tools
    "browser.open": 10.0,
    "browser.search": 15.0,
}


def get_tool_timeout(tool_name: str) -> float:
    """Get timeout for a tool (seconds)."""
    return _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT_S)


# ─────────────────────────────────────────────────────────────────
# Circuit Breaker
# ─────────────────────────────────────────────────────────────────


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Tool disabled after N failures
    HALF_OPEN = "half_open"  # Allowing one probe request


@dataclass
class CircuitBreaker:
    """
    Per-tool circuit breaker.

    After *failure_threshold* consecutive timeouts, the circuit opens
    and the tool is disabled for *recovery_timeout_s* seconds.
    After that, one probe request is allowed (half-open). If it succeeds
    the circuit closes; if it fails it re-opens.
    """

    failure_threshold: int = 3
    recovery_timeout_s: float = 60.0

    # Internal state
    _consecutive_failures: int = 0
    _state: CircuitState = CircuitState.CLOSED
    _last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        # Auto-transition OPEN → HALF_OPEN after recovery timeout
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def is_available(self) -> bool:
        """Can a request go through?"""
        s = self.state  # triggers auto-transition
        return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful execution."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a timeout/failure."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPEN after %d consecutive failures (recovery in %.0fs)",
                self._consecutive_failures,
                self.recovery_timeout_s,
            )

    def reset(self) -> None:
        """Force reset to CLOSED."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._last_failure_time = 0.0


# ─────────────────────────────────────────────────────────────────
# Timeout Result
# ─────────────────────────────────────────────────────────────────


@dataclass
class ToolExecutionResult:
    """Result of a timeout-guarded tool execution."""
    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0
    timed_out: bool = False
    circuit_open: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "tool": self.tool_name,
            "success": self.success,
        }
        if self.result is not None:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        if self.timed_out:
            d["timed_out"] = True
        if self.circuit_open:
            d["circuit_open"] = True
        d["elapsed_ms"] = round(self.elapsed_ms, 1)
        return d


# ─────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────


class ToolTimeoutManager:
    """
    Manages per-tool timeouts and circuit breakers.

    Usage::

        manager = ToolTimeoutManager()
        result = await manager.execute("calendar.create_event", some_coro())
    """

    def __init__(
        self,
        default_timeout_s: float = _DEFAULT_TIMEOUT_S,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 60.0,
    ):
        self._default_timeout = default_timeout_s
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_s
        self._breakers: Dict[str, CircuitBreaker] = {}

    def _get_breaker(self, tool_name: str) -> CircuitBreaker:
        if tool_name not in self._breakers:
            self._breakers[tool_name] = CircuitBreaker(
                failure_threshold=self._failure_threshold,
                recovery_timeout_s=self._recovery_timeout,
            )
        return self._breakers[tool_name]

    def get_timeout(self, tool_name: str) -> float:
        return _TOOL_TIMEOUTS.get(tool_name, self._default_timeout)

    def is_available(self, tool_name: str) -> bool:
        """Check if a tool is available (circuit not open)."""
        return self._get_breaker(tool_name).is_available

    def get_circuit_state(self, tool_name: str) -> CircuitState:
        return self._get_breaker(tool_name).state

    async def execute(
        self,
        tool_name: str,
        coro: Coroutine[Any, Any, Any],
        timeout_s: Optional[float] = None,
    ) -> ToolExecutionResult:
        """
        Execute a tool coroutine with timeout and circuit breaker.

        Args:
            tool_name: Name of the tool
            coro: The coroutine to execute
            timeout_s: Override timeout (uses per-tool default if None)

        Returns:
            ToolExecutionResult with success/error/timing info
        """
        breaker = self._get_breaker(tool_name)

        # Circuit breaker check
        if not breaker.is_available:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' temporarily disabled (circuit breaker open)",
                circuit_open=True,
            )

        timeout = timeout_s or self.get_timeout(tool_name)
        start = time.monotonic()

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            elapsed_ms = (time.monotonic() - start) * 1000
            breaker.record_success()
            return ToolExecutionResult(
                tool_name=tool_name,
                success=True,
                result=result,
                elapsed_ms=elapsed_ms,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            breaker.record_failure()
            logger.warning(
                "Tool '%s' timed out after %.0fms (limit: %.0fs)",
                tool_name,
                elapsed_ms,
                timeout,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                error=f"İşlem zaman aşımına uğradı ({tool_name}, {timeout:.0f}s)",
                elapsed_ms=elapsed_ms,
                timed_out=True,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            breaker.record_failure()
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                error=str(exc),
                elapsed_ms=elapsed_ms,
            )

    def reset_breaker(self, tool_name: str) -> None:
        """Force reset a tool's circuit breaker."""
        if tool_name in self._breakers:
            self._breakers[tool_name].reset()

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for b in self._breakers.values():
            b.reset()

    def dashboard(self) -> Dict[str, Any]:
        """Export status of all tracked tools."""
        return {
            name: {
                "state": breaker.state.value,
                "consecutive_failures": breaker._consecutive_failures,
                "available": breaker.is_available,
            }
            for name, breaker in self._breakers.items()
        }


# ─────────────────────────────────────────────────────────────────
# Convenience wrapper
# ─────────────────────────────────────────────────────────────────


async def execute_with_timeout(
    manager: ToolTimeoutManager,
    tool_name: str,
    coro: Coroutine[Any, Any, Any],
    timeout_s: Optional[float] = None,
) -> ToolExecutionResult:
    """Convenience function for one-shot timeout execution."""
    return await manager.execute(tool_name, coro, timeout_s=timeout_s)
