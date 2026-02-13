"""
Tests for Issue #431 — Tool Execution Timeout & Circuit Breaker.

Covers:
- get_tool_timeout: per-tool defaults
- CircuitBreaker: closed→open after N failures, auto half-open, probe
- ToolTimeoutManager: execute with timeout, circuit integration
- ToolExecutionResult: to_dict
- Timeout enforcement on slow coroutines
- Circuit breaker blocks after threshold
- Recovery / reset
- Dashboard export
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from bantz.brain.tool_timeout import (
    CircuitBreaker,
    CircuitState,
    ToolExecutionResult,
    ToolTimeoutManager,
    execute_with_timeout,
    get_tool_timeout,
)


# ─────────────────────────────────────────────────────────────────
# get_tool_timeout
# ─────────────────────────────────────────────────────────────────


class TestGetToolTimeout:

    def test_known_tool(self):
        assert get_tool_timeout("time.now") == 2.0

    def test_calendar_create(self):
        assert get_tool_timeout("calendar.create_event") == 15.0

    def test_unknown_tool_default(self):
        assert get_tool_timeout("some.unknown.tool") == 10.0

    def test_gmail_send(self):
        assert get_tool_timeout("gmail.send") == 15.0


# ─────────────────────────────────────────────────────────────────
# CircuitBreaker
# ─────────────────────────────────────────────────────────────────


class TestCircuitBreaker:

    def test_initial_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.is_available

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_available

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout_s=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_available


# ─────────────────────────────────────────────────────────────────
# ToolExecutionResult
# ─────────────────────────────────────────────────────────────────


class TestToolExecutionResult:

    def test_success_to_dict(self):
        r = ToolExecutionResult(
            tool_name="time.now", success=True, result={"time": "14:00"}, elapsed_ms=5.3
        )
        d = r.to_dict()
        assert d["tool"] == "time.now"
        assert d["success"] is True
        assert d["result"] == {"time": "14:00"}
        assert d["elapsed_ms"] == 5.3

    def test_timeout_to_dict(self):
        r = ToolExecutionResult(
            tool_name="calendar.list_events",
            success=False,
            error="timeout",
            timed_out=True,
            elapsed_ms=10000,
        )
        d = r.to_dict()
        assert d["timed_out"] is True
        assert "success" in d and d["success"] is False

    def test_circuit_open_to_dict(self):
        r = ToolExecutionResult(
            tool_name="gmail.send", success=False, circuit_open=True
        )
        d = r.to_dict()
        assert d["circuit_open"] is True


# ─────────────────────────────────────────────────────────────────
# ToolTimeoutManager — execute
# ─────────────────────────────────────────────────────────────────


class TestToolTimeoutManager:

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        manager = ToolTimeoutManager()

        async def fast_tool():
            return {"events": []}

        result = await manager.execute("calendar.list_events", fast_tool())
        assert result.success
        assert result.result == {"events": []}
        assert result.elapsed_ms > 0

    @pytest.mark.asyncio
    async def test_timeout_fires(self):
        manager = ToolTimeoutManager()

        async def slow_tool():
            await asyncio.sleep(5)
            return "never"

        result = await manager.execute("time.now", slow_tool(), timeout_s=0.05)
        assert not result.success
        assert result.timed_out

    @pytest.mark.asyncio
    async def test_exception_handled(self):
        manager = ToolTimeoutManager()

        async def broken_tool():
            raise ValueError("API down")

        result = await manager.execute("gmail.send", broken_tool())
        assert not result.success
        assert "API down" in (result.error or "")

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks(self):
        manager = ToolTimeoutManager(failure_threshold=2)

        async def failing():
            raise RuntimeError("fail")

        await manager.execute("test.tool", failing())
        await manager.execute("test.tool", failing())

        # Circuit should be open now
        assert not manager.is_available("test.tool")

        async def should_not_run():
            return "ok"

        result = await manager.execute("test.tool", should_not_run())
        assert result.circuit_open
        assert not result.success

    @pytest.mark.asyncio
    async def test_different_tools_independent(self):
        manager = ToolTimeoutManager(failure_threshold=1)

        async def failing():
            raise RuntimeError("fail")

        await manager.execute("tool.a", failing())
        assert not manager.is_available("tool.a")
        assert manager.is_available("tool.b")  # independent

    def test_get_timeout(self):
        manager = ToolTimeoutManager()
        assert manager.get_timeout("calendar.create_event") == 15.0
        assert manager.get_timeout("unknown") == 10.0

    def test_reset_breaker(self):
        manager = ToolTimeoutManager(failure_threshold=1)
        breaker = manager._get_breaker("test.tool")
        breaker.record_failure()
        assert not manager.is_available("test.tool")
        manager.reset_breaker("test.tool")
        assert manager.is_available("test.tool")

    def test_reset_all(self):
        manager = ToolTimeoutManager(failure_threshold=1)
        for name in ["a", "b", "c"]:
            b = manager._get_breaker(name)
            b.record_failure()
        manager.reset_all()
        for name in ["a", "b", "c"]:
            assert manager.is_available(name)

    def test_dashboard(self):
        manager = ToolTimeoutManager(failure_threshold=2)
        manager._get_breaker("calendar.create_event").record_failure()
        dash = manager.dashboard()
        assert "calendar.create_event" in dash
        assert dash["calendar.create_event"]["state"] == "closed"
        assert dash["calendar.create_event"]["consecutive_failures"] == 1


# ─────────────────────────────────────────────────────────────────
# execute_with_timeout convenience
# ─────────────────────────────────────────────────────────────────


class TestExecuteWithTimeout:

    @pytest.mark.asyncio
    async def test_convenience_wrapper(self):
        manager = ToolTimeoutManager()

        async def quick():
            return 42

        result = await execute_with_timeout(manager, "time.now", quick())
        assert result.success
        assert result.result == 42

    @pytest.mark.asyncio
    async def test_convenience_timeout(self):
        manager = ToolTimeoutManager()

        async def slow():
            await asyncio.sleep(5)

        result = await execute_with_timeout(manager, "time.now", slow(), timeout_s=0.02)
        assert result.timed_out


# ─────────────────────────────────────────────────────────────────
# Turkish error messages
# ─────────────────────────────────────────────────────────────────


class TestTurkishMessages:

    @pytest.mark.asyncio
    async def test_timeout_message_turkish(self):
        manager = ToolTimeoutManager()

        async def slow():
            await asyncio.sleep(5)

        result = await manager.execute("calendar.list_events", slow(), timeout_s=0.02)
        assert "zaman aşımı" in (result.error or "").lower()
