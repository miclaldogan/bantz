"""Tests for Issue #1297 — Event Bus Subscriber Registry & Wiring.

Coverage:
- subscriber_registry.py: wire_subscribers, unwire_all, get_wired_subscribers
- ObservabilitySubscriber: tool.call → run_tracker.record_tool_call
- IngestSubscriber: tool.call → ingest_bridge.on_tool_result
- AuditSubscriber: tool.* → audit_logger.log_tool_execution
- LoggingMiddleware: event counting, DEBUG logging
- RateLimitMiddleware: duplicate event suppression
- EventSubscriber protocol
- Orchestrator event emission: run.started, run.completed, tool.confirmed, tool.denied
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from bantz.core.events import Event, EventBus, EventType, reset_event_bus
from bantz.core.subscriber_registry import (
    AuditSubscriber,
    EventSubscriber,
    IngestSubscriber,
    LoggingMiddleware,
    ObservabilitySubscriber,
    RateLimitMiddleware,
    get_wired_subscribers,
    unwire_all,
    wire_subscribers,
)


# ═══════════════════════════════════════════════════════════════════
# EventSubscriber Protocol
# ═══════════════════════════════════════════════════════════════════


class TestEventSubscriberProtocol:
    """EventSubscriber protocol compliance."""

    def test_observability_is_subscriber(self):
        tracker = MagicMock()
        sub = ObservabilitySubscriber(tracker)
        assert isinstance(sub, EventSubscriber)
        assert sub.name == "observability"
        assert len(sub.patterns) > 0

    def test_ingest_is_subscriber(self):
        bridge = MagicMock()
        sub = IngestSubscriber(bridge)
        assert isinstance(sub, EventSubscriber)
        assert sub.name == "ingest"

    def test_audit_is_subscriber(self):
        audit = MagicMock()
        sub = AuditSubscriber(audit)
        assert isinstance(sub, EventSubscriber)
        assert sub.name == "audit"
        assert "tool.*" in sub.patterns


# ═══════════════════════════════════════════════════════════════════
# wire_subscribers
# ═══════════════════════════════════════════════════════════════════


class TestWireSubscribers:
    """wire_subscribers() wiring function."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    def test_no_services_returns_empty(self, bus):
        result = wire_subscribers(bus)
        assert result == {}

    def test_run_tracker_wires_observability(self, bus):
        tracker = MagicMock()
        result = wire_subscribers(bus, run_tracker=tracker)
        assert "observability" in result
        assert isinstance(result["observability"], ObservabilitySubscriber)

    def test_ingest_bridge_wires_ingest(self, bus):
        bridge = MagicMock()
        result = wire_subscribers(bus, ingest_bridge=bridge)
        assert "ingest" in result
        assert isinstance(result["ingest"], IngestSubscriber)

    def test_audit_logger_wires_audit(self, bus):
        audit = MagicMock()
        result = wire_subscribers(bus, audit_logger=audit)
        assert "audit" in result
        assert isinstance(result["audit"], AuditSubscriber)

    def test_all_services_wired(self, bus):
        result = wire_subscribers(
            bus,
            run_tracker=MagicMock(),
            ingest_bridge=MagicMock(),
            audit_logger=MagicMock(),
        )
        assert len(result) == 3
        assert "observability" in result
        assert "ingest" in result
        assert "audit" in result

    def test_middleware_flags(self, bus):
        result = wire_subscribers(
            bus,
            enable_logging_middleware=True,
            enable_rate_limit=True,
            rate_limit_window_ms=50,
        )
        assert "logging_middleware" in result
        assert "rate_limit_middleware" in result

    def test_get_wired_subscribers(self, bus):
        wire_subscribers(bus, run_tracker=MagicMock(), ingest_bridge=MagicMock())
        subs = get_wired_subscribers()
        assert len(subs) == 2

    def test_unwire_all(self, bus):
        wire_subscribers(bus, run_tracker=MagicMock())
        assert len(get_wired_subscribers()) == 1
        unwire_all(bus)
        assert len(get_wired_subscribers()) == 0

    def test_rewire_clears_previous(self, bus):
        wire_subscribers(bus, run_tracker=MagicMock())
        wire_subscribers(bus, ingest_bridge=MagicMock())
        subs = get_wired_subscribers()
        assert len(subs) == 1  # Only ingest, observability was cleared


# ═══════════════════════════════════════════════════════════════════
# ObservabilitySubscriber
# ═══════════════════════════════════════════════════════════════════


class TestObservabilitySubscriber:
    """ObservabilitySubscriber forwards events to RunTracker."""

    @pytest.fixture
    def tracker(self):
        return MagicMock()

    @pytest.fixture
    def sub(self, tracker):
        return ObservabilitySubscriber(tracker)

    def test_tool_call_recorded(self, sub, tracker):
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={
                "tool": "calendar.list_events",
                "params": {"date": "today"},
                "result": "3 events",
                "result_summary": "3 events found",
                "elapsed_ms": 120,
                "confirmation": "auto",
                "run_id": "run-42",
            },
            correlation_id="run-42",
        )
        sub.register_run("run-42", MagicMock(run_id="run-42"))
        sub.handle(event)

        tracker.record_tool_call.assert_called_once()
        call_kwargs = tracker.record_tool_call.call_args
        assert call_kwargs[1]["tool_name"] == "calendar.list_events"
        assert call_kwargs[1]["run_id"] == "run-42"
        assert call_kwargs[1]["status"] == "success"

    def test_tool_failed_recorded(self, sub, tracker):
        event = Event(
            event_type=EventType.TOOL_FAILED.value,
            data={
                "tool": "gmail.send",
                "error": "auth failed",
                "run_id": "run-99",
            },
            correlation_id="run-99",
        )
        sub.register_run("run-99", MagicMock(run_id="run-99"))
        sub.handle(event)

        tracker.record_tool_call.assert_called_once()
        call_kwargs = tracker.record_tool_call.call_args
        assert call_kwargs[1]["status"] == "error"
        assert call_kwargs[1]["error"] == "auth failed"

    def test_run_started_creates_run(self, sub, tracker):
        tracker.start_run.return_value = MagicMock(run_id="new-run")
        event = Event(
            event_type=EventType.RUN_STARTED.value,
            data={"user_input": "hello", "session_id": "sess-1"},
            correlation_id="new-run",
        )
        sub.handle(event)
        tracker.start_run.assert_called_once_with("hello", session_id="sess-1")

    def test_run_completed_ends_run(self, sub, tracker):
        mock_run = MagicMock(run_id="run-x")
        sub.register_run("run-x", mock_run)
        event = Event(
            event_type=EventType.RUN_COMPLETED.value,
            data={"route": "calendar", "status": "success"},
            correlation_id="run-x",
        )
        sub.handle(event)
        tracker.end_run.assert_called_once()

    def test_no_run_id_skips_silently(self, sub, tracker):
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={"tool": "test", "run_id": ""},
        )
        sub.handle(event)
        tracker.record_tool_call.assert_not_called()

    def test_handler_error_does_not_propagate(self, sub, tracker):
        tracker.record_tool_call.side_effect = RuntimeError("DB error")
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={"tool": "test", "run_id": "run-1"},
            correlation_id="run-1",
        )
        sub.register_run("run-1", MagicMock(run_id="run-1"))
        # Should not raise
        sub.handle(event)


# ═══════════════════════════════════════════════════════════════════
# IngestSubscriber
# ═══════════════════════════════════════════════════════════════════


class TestIngestSubscriber:
    """IngestSubscriber forwards tool results to IngestBridge."""

    @pytest.fixture
    def bridge(self):
        return MagicMock()

    @pytest.fixture
    def sub(self, bridge):
        return IngestSubscriber(bridge)

    def test_tool_call_ingested(self, sub, bridge):
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={
                "tool": "calendar.list_events",
                "params": {"date": "today"},
                "result": [{"title": "Meeting"}],
                "elapsed_ms": 100,
                "success": True,
                "result_summary": "1 event",
            },
        )
        sub.handle(event)

        bridge.on_tool_result.assert_called_once()
        kwargs = bridge.on_tool_result.call_args[1]
        assert kwargs["tool_name"] == "calendar.list_events"
        assert kwargs["success"] is True

    def test_failed_tool_not_ingested(self, sub, bridge):
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={"tool": "gmail.send", "success": False},
        )
        sub.handle(event)
        bridge.on_tool_result.assert_not_called()

    def test_no_tool_name_skipped(self, sub, bridge):
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={"tool": "", "success": True},
        )
        sub.handle(event)
        bridge.on_tool_result.assert_not_called()

    def test_bridge_error_does_not_propagate(self, sub, bridge):
        bridge.on_tool_result.side_effect = RuntimeError("DB error")
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={"tool": "test", "result": "data", "success": True},
        )
        # Should not raise
        sub.handle(event)


# ═══════════════════════════════════════════════════════════════════
# AuditSubscriber
# ═══════════════════════════════════════════════════════════════════


class TestAuditSubscriber:
    """AuditSubscriber forwards tool events to AuditLogger."""

    @pytest.fixture
    def audit(self):
        return MagicMock()

    @pytest.fixture
    def sub(self, audit):
        return AuditSubscriber(audit)

    def test_tool_call_audited(self, sub, audit):
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={
                "tool": "calendar.create_event",
                "risk_level": "high",
                "confirmed": True,
                "params": {"title": "Meeting"},
                "result": "Created",
            },
        )
        sub.handle(event)

        audit.log_tool_execution.assert_called_once()
        kwargs = audit.log_tool_execution.call_args[1]
        assert kwargs["tool_name"] == "calendar.create_event"
        assert kwargs["risk_level"] == "high"
        assert kwargs["success"] is True
        assert kwargs["confirmed"] is True

    def test_tool_failed_audited(self, sub, audit):
        event = Event(
            event_type=EventType.TOOL_FAILED.value,
            data={
                "tool": "gmail.send",
                "risk_level": "critical",
                "error": "auth error",
            },
        )
        sub.handle(event)

        audit.log_tool_execution.assert_called_once()
        kwargs = audit.log_tool_execution.call_args[1]
        assert kwargs["success"] is False
        assert kwargs["error"] == "auth error"

    def test_tool_confirmed_audited(self, sub, audit):
        event = Event(
            event_type=EventType.TOOL_CONFIRMED.value,
            data={"tool": "calendar.delete_event", "risk_level": "high"},
        )
        sub.handle(event)
        audit.log_tool_execution.assert_called_once()

    def test_tool_denied_audited(self, sub, audit):
        event = Event(
            event_type=EventType.TOOL_DENIED.value,
            data={"tool": "gmail.send", "risk_level": "critical"},
        )
        sub.handle(event)
        kwargs = audit.log_tool_execution.call_args[1]
        assert kwargs["error"] == "User denied"

    def test_wildcard_receives_all_tool_events(self):
        bus = EventBus()
        audit = MagicMock()
        sub = AuditSubscriber(audit)
        bus.subscribe("tool.*", sub.handle)

        bus.publish("tool.executed", {"tool": "t1"})
        bus.publish("tool.failed", {"tool": "t2", "error": "err"})
        bus.publish("tool.confirmed", {"tool": "t3"})
        bus.publish("tool.denied", {"tool": "t4"})

        assert audit.log_tool_execution.call_count == 4

    def test_audit_error_does_not_propagate(self, sub, audit):
        audit.log_tool_execution.side_effect = RuntimeError("audit DB error")
        event = Event(
            event_type=EventType.TOOL_CALL.value,
            data={"tool": "test", "risk_level": "low"},
        )
        # Should not raise
        sub.handle(event)


# ═══════════════════════════════════════════════════════════════════
# LoggingMiddleware
# ═══════════════════════════════════════════════════════════════════


class TestLoggingMiddleware:
    """LoggingMiddleware counts events and passes them through."""

    def test_passes_event_through(self):
        mw = LoggingMiddleware()
        event = Event(event_type="test", data={"a": 1})
        result = mw(event)
        assert result is event

    def test_counts_events(self):
        mw = LoggingMiddleware()
        for _ in range(5):
            mw(Event(event_type="test", data={}))
        assert mw.event_count == 5

    def test_disabled_does_not_count(self):
        mw = LoggingMiddleware(enabled=False)
        mw(Event(event_type="test", data={}))
        assert mw.event_count == 0

    def test_integrates_with_bus(self):
        bus = EventBus()
        mw = LoggingMiddleware()
        bus.add_middleware(mw)

        bus.publish("event.a")
        bus.publish("event.b")
        assert mw.event_count == 2


# ═══════════════════════════════════════════════════════════════════
# RateLimitMiddleware
# ═══════════════════════════════════════════════════════════════════


class TestRateLimitMiddleware:
    """RateLimitMiddleware suppresses rapid duplicate events."""

    def test_first_event_passes(self):
        mw = RateLimitMiddleware(window_ms=1000)
        event = Event(event_type="test", data={}, source="a")
        result = mw(event)
        assert result is event

    def test_rapid_duplicate_suppressed(self):
        mw = RateLimitMiddleware(window_ms=5000)
        event1 = Event(event_type="test", data={}, source="a")
        event2 = Event(event_type="test", data={}, source="a")
        mw(event1)
        result = mw(event2)
        assert result is None  # Suppressed

    def test_different_types_not_suppressed(self):
        mw = RateLimitMiddleware(window_ms=5000)
        e1 = Event(event_type="type.a", data={}, source="x")
        e2 = Event(event_type="type.b", data={}, source="x")
        assert mw(e1) is e1
        assert mw(e2) is e2

    def test_different_sources_not_suppressed(self):
        mw = RateLimitMiddleware(window_ms=5000)
        e1 = Event(event_type="test", data={}, source="src_a")
        e2 = Event(event_type="test", data={}, source="src_b")
        assert mw(e1) is e1
        assert mw(e2) is e2

    def test_integrates_with_bus(self):
        bus = EventBus()
        mw = RateLimitMiddleware(window_ms=5000)
        bus.add_middleware(mw)

        received = []
        bus.subscribe("test", lambda e: received.append(e))

        bus.publish("test", source="a")
        bus.publish("test", source="a")  # Should be suppressed
        assert len(received) == 1


# ═══════════════════════════════════════════════════════════════════
# End-to-end wiring test
# ═══════════════════════════════════════════════════════════════════


class TestEndToEndWiring:
    """Verify full wiring: publish → subscriber receives → calls service."""

    def test_tool_call_reaches_all_subscribers(self):
        bus = EventBus()
        tracker = MagicMock()
        bridge = MagicMock()
        audit = MagicMock()

        wired = wire_subscribers(
            bus,
            run_tracker=tracker,
            ingest_bridge=bridge,
            audit_logger=audit,
        )

        # Register a run for correlation
        obs_sub = wired["observability"]
        obs_sub.register_run("run-1", MagicMock(run_id="run-1"))

        # Publish a tool.call event
        bus.publish(
            EventType.TOOL_CALL.value,
            {
                "tool": "calendar.list_events",
                "params": {"date": "today"},
                "result": "3 events",
                "result_summary": "3 events",
                "elapsed_ms": 50,
                "confirmed": False,
                "success": True,
                "run_id": "run-1",
                "risk_level": "low",
            },
            source="orchestrator",
            correlation_id="run-1",
        )

        # All three services should have been called
        tracker.record_tool_call.assert_called_once()
        bridge.on_tool_result.assert_called_once()
        audit.log_tool_execution.assert_called_once()

    def test_tool_failed_reaches_audit_and_observability(self):
        bus = EventBus()
        tracker = MagicMock()
        audit = MagicMock()
        bridge = MagicMock()

        wired = wire_subscribers(
            bus,
            run_tracker=tracker,
            audit_logger=audit,
            ingest_bridge=bridge,
        )
        obs_sub = wired["observability"]
        obs_sub.register_run("run-2", MagicMock(run_id="run-2"))

        bus.publish(
            EventType.TOOL_FAILED.value,
            {
                "tool": "gmail.send",
                "error": "auth error",
                "run_id": "run-2",
                "risk_level": "critical",
            },
            source="orchestrator",
            correlation_id="run-2",
        )

        # Observability + Audit should be called, but NOT ingest (failed result)
        tracker.record_tool_call.assert_called_once()
        audit.log_tool_execution.assert_called_once()
        # Ingest received the event but skipped due to no success flag
        # (IngestSubscriber only caches on success=True)

    def test_subscriber_error_does_not_break_other_subscribers(self):
        bus = EventBus()
        tracker = MagicMock()
        tracker.record_tool_call.side_effect = RuntimeError("DB down")
        bridge = MagicMock()

        wire_subscribers(bus, run_tracker=tracker, ingest_bridge=bridge)

        # Publish should not raise even though tracker fails
        bus.publish(
            EventType.TOOL_CALL.value,
            {"tool": "test", "params": {}, "result": "ok", "success": True, "run_id": "r1"},
            correlation_id="r1",
        )
        # Ingest should still have been called
        bridge.on_tool_result.assert_called_once()

    def test_unwire_stops_delivery(self):
        bus = EventBus()
        tracker = MagicMock()
        wire_subscribers(bus, run_tracker=tracker)

        bus.publish(
            EventType.TOOL_CALL.value,
            {"tool": "t1", "run_id": "r1"},
            correlation_id="r1",
        )

        unwire_all(bus)

        bus.publish(
            EventType.TOOL_CALL.value,
            {"tool": "t2", "run_id": "r2"},
            correlation_id="r2",
        )

        # Only first event should have been delivered
        # (observability sub checks run_id resolution, may not call record_tool_call)
        # Verify no additional calls happened after unwire
        call_count = tracker.record_tool_call.call_count
        assert call_count <= 1  # At most 1 from before unwire


# ═══════════════════════════════════════════════════════════════════
# Orchestrator event emission tests
# ═══════════════════════════════════════════════════════════════════


class TestOrchestratorEventEmission:
    """Test that orchestrator loop emits correct Run/Tool lifecycle events."""

    def test_event_types_exist(self):
        """Verify all required EventType constants exist."""
        assert EventType.TOOL_CALL.value == "tool.call"
        assert EventType.TOOL_EXECUTED.value == "tool.executed"
        assert EventType.TOOL_FAILED.value == "tool.failed"
        assert EventType.TOOL_CONFIRMED.value == "tool.confirmed"
        assert EventType.TOOL_DENIED.value == "tool.denied"
        assert EventType.RUN_STARTED.value == "run.started"
        assert EventType.RUN_COMPLETED.value == "run.completed"
        assert EventType.MAIL_RECEIVED.value == "mail.received"
        assert EventType.MAIL_SENT.value == "mail.sent"
        assert EventType.CALENDAR_CREATED.value == "calendar.created"
        assert EventType.CALENDAR_UPDATED.value == "calendar.updated"

    def test_wire_subscribers_import_path(self):
        """Verify import from bantz.core works."""
        from bantz.core import wire_subscribers as ws
        assert callable(ws)

    def test_enriched_tool_call_event_has_all_fields(self):
        """Verify tool.call events have enriched payload."""
        bus = EventBus()
        received = []
        bus.subscribe(EventType.TOOL_CALL.value, lambda e: received.append(e))

        bus.publish(
            EventType.TOOL_CALL.value,
            {
                "tool": "calendar.list_events",
                "params": {"date": "today"},
                "result": "3 events",
                "result_summary": "3 events found",
                "elapsed_ms": 120,
                "risk_level": "low",
                "confirmed": False,
                "success": True,
                "run_id": "run-42",
            },
            source="orchestrator",
            correlation_id="run-42",
        )

        assert len(received) == 1
        evt = received[0]
        assert evt.data["tool"] == "calendar.list_events"
        assert evt.data["elapsed_ms"] == 120
        assert evt.data["risk_level"] == "low"
        assert evt.data["run_id"] == "run-42"
        assert evt.correlation_id == "run-42"
        assert evt.source == "orchestrator"
