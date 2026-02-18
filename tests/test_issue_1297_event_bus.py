"""Tests for Issue #1297 — Event Bus: Async Pub/Sub Enhancement.

Coverage:
- Event dataclass with correlation_id
- New EventType entries (tool.executed, mail.received, etc.)
- Wildcard prefix matching (tool.* → tool.executed, tool.failed)
- Catch-all subscribe (subscribe_all)
- Async publish (apublish)
- Middleware chain (sync + async, suppression)
- Fire-and-forget error handling
- tool_runner.py event bus integration
- History with filtering
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from bantz.core.events import (Event, EventBus, EventType, get_event_bus,
                               reset_event_bus)

# ═══════════════════════════════════════════════════════════════════
# Event Dataclass
# ═══════════════════════════════════════════════════════════════════


class TestEvent:
    """Event dataclass tests."""

    def test_basic_creation(self):
        evt = Event(event_type="test.basic", data={"key": "value"})
        assert evt.event_type == "test.basic"
        assert evt.data == {"key": "value"}
        assert evt.source == "core"
        assert evt.correlation_id is None

    def test_correlation_id(self):
        evt = Event(
            event_type="test.corr",
            data={},
            correlation_id="run-42",
        )
        assert evt.correlation_id == "run-42"

    def test_to_dict_without_correlation(self):
        evt = Event(event_type="test.x", data={"a": 1})
        d = evt.to_dict()
        assert d["type"] == "test.x"
        assert d["data"] == {"a": 1}
        assert "correlation_id" not in d

    def test_to_dict_with_correlation(self):
        evt = Event(
            event_type="test.x",
            data={},
            correlation_id="abc",
        )
        d = evt.to_dict()
        assert d["correlation_id"] == "abc"

    def test_timestamp_auto(self):
        before = datetime.now()
        evt = Event(event_type="test.ts", data={})
        after = datetime.now()
        assert before <= evt.timestamp <= after


# ═══════════════════════════════════════════════════════════════════
# EventType Enum
# ═══════════════════════════════════════════════════════════════════


class TestEventType:
    """Verify new event types from Issue #1297."""

    def test_tool_lifecycle(self):
        assert EventType.TOOL_EXECUTED.value == "tool.executed"
        assert EventType.TOOL_FAILED.value == "tool.failed"
        assert EventType.TOOL_CONFIRMED.value == "tool.confirmed"
        assert EventType.TOOL_DENIED.value == "tool.denied"

    def test_data_events(self):
        assert EventType.MAIL_RECEIVED.value == "mail.received"
        assert EventType.MAIL_SENT.value == "mail.sent"
        assert EventType.CALENDAR_CREATED.value == "calendar.created"
        assert EventType.CALENDAR_UPDATED.value == "calendar.updated"
        assert EventType.TASK_COMPLETED.value == "task.completed"

    def test_run_lifecycle(self):
        assert EventType.RUN_STARTED.value == "run.started"
        assert EventType.RUN_COMPLETED.value == "run.completed"
        assert EventType.SESSION_STARTED.value == "session.started"
        assert EventType.BRIEF_GENERATED.value == "brief.generated"

    def test_legacy_still_exists(self):
        assert EventType.REMINDER_FIRED.value == "reminder_fired"
        assert EventType.BANTZ_MESSAGE.value == "bantz_message"

    def test_existing_types_preserved(self):
        assert EventType.ACK.value == "ack"
        assert EventType.TOOL_CALL.value == "tool.call"
        assert EventType.TOOL_RESULT.value == "tool.result"


# ═══════════════════════════════════════════════════════════════════
# EventBus — Basic Publish/Subscribe
# ═══════════════════════════════════════════════════════════════════


class TestEventBusBasic:
    """Basic synchronous pub/sub."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    def test_exact_subscribe(self, bus):
        received = []
        bus.subscribe("test.event", lambda e: received.append(e))
        bus.publish("test.event", data={"a": 1})
        assert len(received) == 1
        assert received[0].data == {"a": 1}

    def test_no_cross_delivery(self, bus):
        received = []
        bus.subscribe("test.a", lambda e: received.append(e))
        bus.publish("test.b", data={})
        assert len(received) == 0

    def test_subscribe_all(self, bus):
        received = []
        bus.subscribe_all(lambda e: received.append(e))
        bus.publish("test.one")
        bus.publish("test.two")
        assert len(received) == 2

    def test_unsubscribe(self, bus):
        received = []
        handler = lambda e: received.append(e)  # noqa: E731
        bus.subscribe("x", handler)
        bus.publish("x")
        assert len(received) == 1

        bus.unsubscribe("x", handler)
        bus.publish("x")
        assert len(received) == 1  # No new events

    def test_unsubscribe_all(self, bus):
        received = []
        handler = lambda e: received.append(e)  # noqa: E731
        bus.subscribe_all(handler)
        bus.publish("a")
        assert len(received) == 1

        bus.unsubscribe_all(handler)
        bus.publish("b")
        assert len(received) == 1

    def test_publish_returns_event(self, bus):
        event = bus.publish("test.ret", data={"k": "v"})
        assert event is not None
        assert event.event_type == "test.ret"

    def test_correlation_id_in_publish(self, bus):
        event = bus.publish(
            "test.corr", data={}, correlation_id="run-99"
        )
        assert event.correlation_id == "run-99"

    def test_source_passed(self, bus):
        event = bus.publish("test.src", source="my_module")
        assert event.source == "my_module"


# ═══════════════════════════════════════════════════════════════════
# EventBus — Wildcard Prefix Matching
# ═══════════════════════════════════════════════════════════════════


class TestWildcardSubscribe:
    """Wildcard prefix pattern: tool.* → tool.executed, tool.failed."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    def test_wildcard_matches(self, bus):
        received = []
        bus.subscribe("tool.*", lambda e: received.append(e))

        bus.publish("tool.executed")
        bus.publish("tool.failed")
        bus.publish("tool.confirmed")
        assert len(received) == 3

    def test_wildcard_no_false_positive(self, bus):
        received = []
        bus.subscribe("tool.*", lambda e: received.append(e))
        bus.publish("tools.extra")  # "tools." != "tool."
        bus.publish("mail.received")
        assert len(received) == 0

    def test_wildcard_exact_and_prefix(self, bus):
        exact = []
        wild = []
        bus.subscribe("tool.executed", lambda e: exact.append(e))
        bus.subscribe("tool.*", lambda e: wild.append(e))

        bus.publish("tool.executed")
        assert len(exact) == 1
        assert len(wild) == 1

    def test_wildcard_plus_global(self, bus):
        wild = []
        glob = []
        bus.subscribe("tool.*", lambda e: wild.append(e))
        bus.subscribe_all(lambda e: glob.append(e))

        bus.publish("tool.executed")
        assert len(wild) == 1
        assert len(glob) == 1

    def test_nested_wildcard(self, bus):
        received = []
        bus.subscribe("overnight.*", lambda e: received.append(e))
        bus.publish("overnight.task.started")
        # "overnight.*" should match "overnight.task.started"
        # because event_type starts with "overnight."
        assert len(received) == 1

    def test_wildcard_does_not_match_exact(self, bus):
        """'tool.*' should NOT match 'tool' exactly (no dot)."""
        received = []
        bus.subscribe("tool.*", lambda e: received.append(e))
        bus.publish("tool")  # No dot after "tool"
        assert len(received) == 0


# ═══════════════════════════════════════════════════════════════════
# EventBus — Middleware
# ═══════════════════════════════════════════════════════════════════


class TestMiddleware:
    """Middleware chain: transform, filter, suppress."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    def test_middleware_can_modify_event(self, bus):
        def add_tag(event: Event) -> Event:
            event.data["tagged"] = True
            return event

        bus.add_middleware(add_tag)

        received = []
        bus.subscribe("test", lambda e: received.append(e))
        bus.publish("test", data={"a": 1})
        assert received[0].data["tagged"] is True
        assert received[0].data["a"] == 1

    def test_middleware_can_suppress(self, bus):
        def block_all(event: Event):
            return None  # Suppress

        bus.add_middleware(block_all)

        received = []
        bus.subscribe("test", lambda e: received.append(e))
        result = bus.publish("test")
        assert result is None
        assert len(received) == 0

    def test_middleware_chain_order(self, bus):
        order = []

        def mw1(event: Event) -> Event:
            order.append("mw1")
            return event

        def mw2(event: Event) -> Event:
            order.append("mw2")
            return event

        bus.add_middleware(mw1)
        bus.add_middleware(mw2)
        bus.publish("test")
        assert order == ["mw1", "mw2"]

    def test_middleware_error_stops_dispatch(self, bus):
        def broken(event: Event) -> Event:
            raise ValueError("boom")

        bus.add_middleware(broken)
        received = []
        bus.subscribe("test", lambda e: received.append(e))
        result = bus.publish("test")
        assert result is None
        assert len(received) == 0

    def test_selective_middleware(self, bus):
        """Middleware that only blocks certain event types."""

        def block_meetings(event: Event):
            if "meeting" in event.event_type:
                return None
            return event

        bus.add_middleware(block_meetings)

        received = []
        bus.subscribe_all(lambda e: received.append(e))
        bus.publish("tool.executed")
        bus.publish("meeting.started")  # Should be blocked
        bus.publish("mail.received")
        assert len(received) == 2


# ═══════════════════════════════════════════════════════════════════
# EventBus — Fire-and-Forget Error Handling
# ═══════════════════════════════════════════════════════════════════


class TestFireAndForget:
    """Subscriber errors never propagate to publisher."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    def test_handler_error_does_not_propagate(self, bus):
        def broken_handler(event):
            raise RuntimeError("handler crash")

        bus.subscribe("test", broken_handler)

        # Should NOT raise
        event = bus.publish("test")
        assert event is not None

    def test_one_bad_handler_doesnt_block_others(self, bus):
        results = []

        def good_handler(event):
            results.append("ok")

        def bad_handler(event):
            raise ValueError("boom")

        bus.subscribe("test", good_handler)
        bus.subscribe("test", bad_handler)

        bus.publish("test")
        assert results == ["ok"]


# ═══════════════════════════════════════════════════════════════════
# EventBus — Async Publish
# ═══════════════════════════════════════════════════════════════════


class TestAsyncPublish:
    """Async publish with async handlers."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_apublish_sync_handler(self, bus):
        received = []
        bus.subscribe("test.async", lambda e: received.append(e))
        event = await bus.apublish("test.async", data={"x": 1})
        assert event is not None
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_apublish_async_handler(self, bus):
        received = []

        async def async_handler(event):
            received.append(event)

        bus.subscribe_async("test.async", async_handler)
        await bus.apublish("test.async", data={"y": 2})
        assert len(received) == 1
        assert received[0].data == {"y": 2}

    @pytest.mark.asyncio
    async def test_apublish_both_sync_and_async(self, bus):
        sync_received = []
        async_received = []

        bus.subscribe("test.both", lambda e: sync_received.append(e))

        async def async_handler(event):
            async_received.append(event)

        bus.subscribe_async("test.both", async_handler)

        await bus.apublish("test.both")
        assert len(sync_received) == 1
        assert len(async_received) == 1

    @pytest.mark.asyncio
    async def test_apublish_wildcard_async(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe_async("tool.*", handler)
        await bus.apublish("tool.executed")
        await bus.apublish("tool.failed")
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_apublish_correlation_id(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe_async("test.corr", handler)
        await bus.apublish(
            "test.corr", correlation_id="job-123"
        )
        assert received[0].correlation_id == "job-123"

    @pytest.mark.asyncio
    async def test_apublish_async_middleware(self, bus):
        async def async_mw(event):
            event.data["enriched"] = True
            return event

        bus.add_async_middleware(async_mw)

        received = []
        bus.subscribe("test.mw", lambda e: received.append(e))
        await bus.apublish("test.mw", data={"a": 1})
        assert received[0].data["enriched"] is True

    @pytest.mark.asyncio
    async def test_apublish_async_middleware_suppresses(self, bus):
        async def blocker(event):
            return None

        bus.add_async_middleware(blocker)
        received = []
        bus.subscribe("test.block", lambda e: received.append(e))
        result = await bus.apublish("test.block")
        assert result is None
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_apublish_async_handler_error_safe(self, bus):
        async def broken(event):
            raise RuntimeError("async handler crash")

        bus.subscribe_async("test.err", broken)
        # Should NOT raise
        event = await bus.apublish("test.err")
        assert event is not None

    @pytest.mark.asyncio
    async def test_subscribe_all_async(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe_all_async(handler)
        await bus.apublish("any.event")
        assert len(received) == 1


# ═══════════════════════════════════════════════════════════════════
# EventBus — History
# ═══════════════════════════════════════════════════════════════════


class TestHistory:
    """Event history tracking."""

    @pytest.fixture
    def bus(self):
        return EventBus(history_size=5)

    def test_history_records(self, bus):
        bus.publish("a")
        bus.publish("b")
        history = bus.get_history()
        assert len(history) == 2

    def test_history_filter_by_type(self, bus):
        bus.publish("x")
        bus.publish("y")
        bus.publish("x")
        history = bus.get_history(event_type="x")
        assert len(history) == 2

    def test_history_respects_limit(self, bus):
        for i in range(10):
            bus.publish("e")
        history = bus.get_history(limit=3)
        assert len(history) == 3

    def test_history_evicts_old(self, bus):
        for i in range(10):
            bus.publish("e", data={"i": i})
        history = bus.get_history()
        # history_size=5, so only last 5
        assert len(history) == 5
        assert history[0].data["i"] == 5

    def test_clear_history(self, bus):
        bus.publish("x")
        bus.clear_history()
        assert bus.get_history() == []


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════


class TestSingleton:
    """Singleton pattern for EventBus."""

    def test_get_event_bus_singleton(self):
        reset_event_bus()
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
        reset_event_bus()

    def test_reset_event_bus(self):
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2
        reset_event_bus()


# ═══════════════════════════════════════════════════════════════════
# tool_runner.py Event Bus Integration
# ═══════════════════════════════════════════════════════════════════


class TestToolRunnerEventIntegration:
    """Verify tool_runner publishes tool.executed / tool.failed events."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_successful_run_publishes_tool_executed(self, bus):
        from bantz.agent.tool_base import (ToolBase, ToolContext, ToolResult,
                                           ToolSpec)
        from bantz.agent.tool_runner import ToolRunner

        received = []
        bus.subscribe("tool.executed", lambda e: received.append(e))

        class FakeTool(ToolBase):
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="fake_tool",
                    description="Test",
                    parameters={}, timeout=10.0,
                    max_retries=0,
                )

            def validate_input(self, input: dict):
                return True, None

            async def run(self, input: dict, context: ToolContext) -> ToolResult:
                return ToolResult.ok(data={"result": "done"})

        runner = ToolRunner(event_bus=bus)
        ctx = ToolContext(job_id="job-42", event_bus=bus)
        result = await runner.run(FakeTool(), {"q": "test"}, ctx)

        assert result.success is True
        assert len(received) == 1
        evt = received[0]
        assert evt.event_type == "tool.executed"
        assert evt.data["tool"] == "fake_tool"
        assert evt.data["job_id"] == "job-42"
        assert evt.source == "tool_runner"
        assert evt.correlation_id == "job-42"

    @pytest.mark.asyncio
    async def test_failed_run_publishes_tool_failed(self, bus):
        from bantz.agent.tool_base import (ErrorType, ToolBase, ToolContext,
                                           ToolResult, ToolSpec)
        from bantz.agent.tool_runner import ToolRunner

        received = []
        bus.subscribe("tool.failed", lambda e: received.append(e))

        class FailTool(ToolBase):
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="fail_tool",
                    description="Always fails",
                    parameters={}, timeout=10.0,
                    max_retries=0,
                )

            def validate_input(self, input: dict):
                return True, None

            async def run(self, input: dict, context: ToolContext) -> ToolResult:
                return ToolResult.fail(
                    error="simulated error",
                    error_type=ErrorType.UNKNOWN,
                )

        runner = ToolRunner(event_bus=bus)
        ctx = ToolContext(job_id="job-99", event_bus=bus)
        result = await runner.run(FailTool(), {}, ctx)

        assert result.success is False
        assert len(received) == 1
        evt = received[0]
        assert evt.event_type == "tool.failed"
        assert evt.data["tool"] == "fail_tool"
        assert evt.data["error"] == "simulated error"
        assert evt.correlation_id == "job-99"

    @pytest.mark.asyncio
    async def test_wildcard_catches_tool_events(self, bus):
        from bantz.agent.tool_base import (ToolBase, ToolContext, ToolResult,
                                           ToolSpec)
        from bantz.agent.tool_runner import ToolRunner

        all_tool_events = []
        bus.subscribe("tool.*", lambda e: all_tool_events.append(e))

        class OkTool(ToolBase):
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="ok_tool",
                    description="OK",
                    parameters={}, timeout=10.0,
                    max_retries=0,
                )

            def validate_input(self, input: dict):
                return True, None

            async def run(self, input: dict, context: ToolContext) -> ToolResult:
                return ToolResult.ok(data={})

        runner = ToolRunner(event_bus=bus)
        ctx = ToolContext(job_id="j1", event_bus=bus)
        await runner.run(OkTool(), {}, ctx)

        assert len(all_tool_events) == 1
        assert all_tool_events[0].event_type == "tool.executed"

    @pytest.mark.asyncio
    async def test_no_event_bus_does_not_crash(self):
        from bantz.agent.tool_base import (ToolBase, ToolContext, ToolResult,
                                           ToolSpec)
        from bantz.agent.tool_runner import ToolRunner

        class SafeTool(ToolBase):
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="safe_tool",
                    description="No bus",
                    parameters={}, timeout=10.0,
                    max_retries=0,
                )

            def validate_input(self, input: dict):
                return True, None

            async def run(self, input: dict, context: ToolContext) -> ToolResult:
                return ToolResult.ok(data={})

        runner = ToolRunner(event_bus=None)
        ctx = ToolContext(job_id="j0", event_bus=None)
        result = await runner.run(SafeTool(), {}, ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_retry_event_has_correlation_id(self, bus):
        from bantz.agent.tool_base import (ToolBase, ToolContext, ToolResult,
                                           ToolSpec)
        from bantz.agent.tool_runner import ToolRunner

        retry_events = []
        bus.subscribe(EventType.RETRY.value, lambda e: retry_events.append(e))

        call_count = 0

        class RetryTool(ToolBase):
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="retry_tool",
                    description="Fails then succeeds",
                    parameters={}, timeout=10.0,
                    max_retries=1,
                )

            def validate_input(self, input: dict):
                return True, None

            async def run(self, input: dict, context: ToolContext) -> ToolResult:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return ToolResult.fail(error="first fail")
                return ToolResult.ok(data={})

        runner = ToolRunner(event_bus=bus)
        ctx = ToolContext(job_id="retry-job", event_bus=bus)

        with patch("bantz.agent.tool_runner.RETRY_DELAYS", [0.01]):
            result = await runner.run(RetryTool(), {}, ctx)

        assert result.success is True
        assert len(retry_events) >= 1
        assert retry_events[0].correlation_id == "retry-job"
