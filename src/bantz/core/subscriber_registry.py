"""Centralized Event Bus subscriber registry.

Issue #1297: Event Bus — Async Pub/Sub İç İletişim Altyapısı.

This module replaces scattered imperative calls to run_tracker, ingest_bridge,
and audit_logger with event-driven subscribers.  The orchestrator publishes
events; subscribers react independently.

Usage::

    from bantz.core.subscriber_registry import wire_subscribers

    wire_subscribers(
        event_bus,
        run_tracker=self.run_tracker,
        ingest_bridge=self._ingest_bridge,
        audit_logger=self.audit_logger,
    )
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from bantz.core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Protocol for pluggable subscribers
# ─────────────────────────────────────────────────────────────────


@runtime_checkable
class EventSubscriber(Protocol):
    """Protocol for event subscribers.

    Each subscriber declares which event patterns it listens to
    and provides a handler.
    """

    @property
    def name(self) -> str:
        """Human-readable subscriber name."""
        ...

    @property
    def patterns(self) -> List[str]:
        """Event type patterns to subscribe to (supports wildcards)."""
        ...

    def handle(self, event: Event) -> None:
        """Handle an incoming event.  Must be fire-and-forget safe."""
        ...


# ─────────────────────────────────────────────────────────────────
# Observability subscriber — wraps RunTracker
# ─────────────────────────────────────────────────────────────────


class ObservabilitySubscriber:
    """Subscribes to tool.* and run.* events, forwards to RunTracker.

    Replaces the imperative ``run_tracker.record_tool_call()`` calls
    scattered in orchestrator_loop.py.
    """

    def __init__(self, run_tracker: Any) -> None:
        self._tracker = run_tracker
        # Active run mapping: correlation_id → Run object
        self._active_runs: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "observability"

    @property
    def patterns(self) -> List[str]:
        return [
            EventType.TOOL_CALL.value,        # tool.call
            EventType.TOOL_EXECUTED.value,     # tool.executed
            EventType.TOOL_FAILED.value,       # tool.failed
            EventType.RUN_STARTED.value,       # run.started
            EventType.RUN_COMPLETED.value,     # run.completed
        ]

    def handle(self, event: Event) -> None:
        """Route event to appropriate handler."""
        try:
            if event.event_type in (
                EventType.TOOL_CALL.value,
                EventType.TOOL_EXECUTED.value,
            ):
                self._on_tool_call(event)
            elif event.event_type == EventType.TOOL_FAILED.value:
                self._on_tool_failed(event)
            elif event.event_type == EventType.RUN_STARTED.value:
                self._on_run_started(event)
            elif event.event_type == EventType.RUN_COMPLETED.value:
                self._on_run_completed(event)
        except Exception as exc:
            logger.debug(
                "[ObservabilitySubscriber] %s handler error: %s",
                event.event_type, exc,
            )

    def register_run(self, correlation_id: str, run: Any) -> None:
        """Register an active run for correlation ID tracking."""
        self._active_runs[correlation_id] = run

    def unregister_run(self, correlation_id: str) -> None:
        """Remove a completed run from tracking."""
        self._active_runs.pop(correlation_id, None)

    def _on_tool_call(self, event: Event) -> None:
        """Record a successful tool call."""
        data = event.data
        run_id = data.get("run_id") or self._resolve_run_id(event.correlation_id)
        if not run_id:
            return

        self._tracker.record_tool_call(
            run_id=run_id,
            tool_name=data.get("tool", ""),
            params=data.get("params"),
            result=data.get("result"),
            result_summary=data.get("result_summary"),
            latency_ms=data.get("elapsed_ms", 0),
            confirmation=data.get("confirmation", "auto"),
            status="success",
        )

    def _on_tool_failed(self, event: Event) -> None:
        """Record a failed tool call."""
        data = event.data
        run_id = data.get("run_id") or self._resolve_run_id(event.correlation_id)
        if not run_id:
            return

        self._tracker.record_tool_call(
            run_id=run_id,
            tool_name=data.get("tool", ""),
            params=data.get("params"),
            error=data.get("error", "unknown"),
            latency_ms=data.get("elapsed_ms", 0),
            status="error",
        )

    def _on_run_started(self, event: Event) -> None:
        """Start tracking a new run."""
        data = event.data
        user_input = data.get("user_input", "")
        session_id = data.get("session_id")
        run = self._tracker.start_run(user_input, session_id=session_id)
        if event.correlation_id:
            self._active_runs[event.correlation_id] = run

    def _on_run_completed(self, event: Event) -> None:
        """Complete a tracked run."""
        data = event.data
        run = self._active_runs.pop(event.correlation_id, None) if event.correlation_id else None
        if run is None:
            return
        run.route = data.get("route", run.route)
        run.intent = data.get("intent", run.intent)
        run.final_output = data.get("final_output", run.final_output)
        run.model = data.get("model", run.model)
        status = data.get("status")
        self._tracker.end_run(run, status=status)

    def _resolve_run_id(self, correlation_id: Optional[str]) -> Optional[str]:
        """Resolve a correlation ID to a run_id."""
        if not correlation_id:
            return None
        run = self._active_runs.get(correlation_id)
        return getattr(run, "run_id", None) if run else None


# ─────────────────────────────────────────────────────────────────
# Ingest subscriber — wraps IngestBridge
# ─────────────────────────────────────────────────────────────────


class IngestSubscriber:
    """Subscribes to tool.call / tool.executed events, caches results in IngestStore.

    Replaces the imperative ``_ingest_bridge.on_tool_result()`` calls.
    """

    def __init__(self, ingest_bridge: Any) -> None:
        self._bridge = ingest_bridge

    @property
    def name(self) -> str:
        return "ingest"

    @property
    def patterns(self) -> List[str]:
        return [
            EventType.TOOL_CALL.value,     # tool.call
            EventType.TOOL_EXECUTED.value,  # tool.executed
        ]

    def handle(self, event: Event) -> None:
        """Cache tool results via IngestBridge."""
        try:
            data = event.data
            tool_name = data.get("tool", "")
            if not tool_name:
                return

            # Only cache successful results
            success = data.get("success", True)
            if not success:
                return

            self._bridge.on_tool_result(
                tool_name=tool_name,
                params=data.get("params") or {},
                result=data.get("result"),
                elapsed_ms=data.get("elapsed_ms", 0),
                success=True,
                summary=data.get("result_summary"),
            )
        except Exception as exc:
            logger.debug(
                "[IngestSubscriber] Failed to cache %s: %s",
                event.data.get("tool"), exc,
            )


# ─────────────────────────────────────────────────────────────────
# Audit subscriber — wraps AuditLogger
# ─────────────────────────────────────────────────────────────────


class AuditSubscriber:
    """Subscribes to tool.* events for security audit logging.

    Replaces the imperative ``audit_logger.log_tool_execution()`` calls.
    """

    def __init__(self, audit_logger: Any) -> None:
        self._audit = audit_logger

    @property
    def name(self) -> str:
        return "audit"

    @property
    def patterns(self) -> List[str]:
        return ["tool.*"]  # Wildcard — all tool lifecycle events

    def handle(self, event: Event) -> None:
        """Log tool events to the audit trail."""
        try:
            data = event.data
            tool_name = data.get("tool", "")
            if not tool_name:
                return

            # Determine risk level
            risk_level = data.get("risk_level", "low")

            if event.event_type in (
                EventType.TOOL_CALL.value,
                EventType.TOOL_EXECUTED.value,
            ):
                self._audit.log_tool_execution(
                    tool_name=tool_name,
                    risk_level=risk_level,
                    success=True,
                    confirmed=data.get("confirmed", False),
                    params=data.get("params"),
                    result=data.get("result"),
                )
            elif event.event_type == EventType.TOOL_FAILED.value:
                self._audit.log_tool_execution(
                    tool_name=tool_name,
                    risk_level=risk_level,
                    success=False,
                    confirmed=False,
                    error=data.get("error"),
                    params=data.get("params"),
                )
            elif event.event_type == EventType.TOOL_CONFIRMED.value:
                self._audit.log_tool_execution(
                    tool_name=tool_name,
                    risk_level=risk_level,
                    success=True,
                    confirmed=True,
                    params=data.get("params"),
                )
            elif event.event_type == EventType.TOOL_DENIED.value:
                self._audit.log_tool_execution(
                    tool_name=tool_name,
                    risk_level=risk_level,
                    success=False,
                    confirmed=False,
                    error="User denied",
                    params=data.get("params"),
                )
        except Exception as exc:
            logger.debug(
                "[AuditSubscriber] Failed to audit %s: %s",
                event.data.get("tool"), exc,
            )


# ─────────────────────────────────────────────────────────────────
# Logging middleware — enriches events with metadata
# ─────────────────────────────────────────────────────────────────


class LoggingMiddleware:
    """Middleware that logs all events at DEBUG level.

    Useful for debugging event flow without adding subscribers.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._event_count = 0

    def __call__(self, event: Event) -> Event:
        if self._enabled:
            self._event_count += 1
            logger.debug(
                "[EventBus] #%d %s from=%s corr=%s keys=%s",
                self._event_count,
                event.event_type,
                event.source,
                event.correlation_id,
                list(event.data.keys()),
            )
        return event

    @property
    def event_count(self) -> int:
        return self._event_count


# ─────────────────────────────────────────────────────────────────
# Rate-limiting middleware
# ─────────────────────────────────────────────────────────────────


class RateLimitMiddleware:
    """Middleware that suppresses duplicate events within a time window.

    Prevents event storms (e.g., rapid retry loops flooding subscribers).
    """

    def __init__(self, window_ms: int = 100) -> None:
        self._window_ms = window_ms
        self._last_seen: Dict[str, float] = {}

    def __call__(self, event: Event) -> Optional[Event]:
        import time

        now = time.monotonic() * 1000
        key = f"{event.event_type}:{event.source}"
        last = self._last_seen.get(key, 0)

        if (now - last) < self._window_ms:
            logger.debug(
                "[RateLimit] Suppressed duplicate %s (within %dms)",
                event.event_type, self._window_ms,
            )
            return None

        self._last_seen[key] = now
        return event


# ─────────────────────────────────────────────────────────────────
# Main wiring function
# ─────────────────────────────────────────────────────────────────

_wired_subscribers: List[Any] = []


def wire_subscribers(
    bus: EventBus,
    *,
    run_tracker: Any = None,
    ingest_bridge: Any = None,
    audit_logger: Any = None,
    enable_logging_middleware: bool = False,
    enable_rate_limit: bool = False,
    rate_limit_window_ms: int = 100,
) -> Dict[str, Any]:
    """Register all available subscribers with the event bus.

    Call this once during orchestrator initialization.  Returns a dict
    of subscriber name → subscriber instance for inspection/testing.

    Args:
        bus: The EventBus instance to wire subscribers to.
        run_tracker: RunTracker instance for observability.
        ingest_bridge: IngestBridge instance for result caching.
        audit_logger: AuditLogger instance for security audit.
        enable_logging_middleware: Add DEBUG-level event logging.
        enable_rate_limit: Add rate-limiting middleware.
        rate_limit_window_ms: Rate limit window in milliseconds.

    Returns:
        Dict mapping subscriber names to their instances.
    """
    global _wired_subscribers
    _wired_subscribers.clear()

    wired: Dict[str, Any] = {}

    # Middleware (applied before handlers)
    if enable_logging_middleware:
        mw = LoggingMiddleware()
        bus.add_middleware(mw)
        wired["logging_middleware"] = mw
        logger.info("[EventBus] Logging middleware enabled")

    if enable_rate_limit:
        rl = RateLimitMiddleware(window_ms=rate_limit_window_ms)
        bus.add_middleware(rl)
        wired["rate_limit_middleware"] = rl
        logger.info("[EventBus] Rate-limit middleware enabled (window=%dms)", rate_limit_window_ms)

    # Subscribers
    subscribers: List[Any] = []

    if run_tracker is not None:
        sub = ObservabilitySubscriber(run_tracker)
        subscribers.append(sub)
        wired["observability"] = sub

    if ingest_bridge is not None:
        sub = IngestSubscriber(ingest_bridge)
        subscribers.append(sub)
        wired["ingest"] = sub

    if audit_logger is not None:
        sub = AuditSubscriber(audit_logger)
        subscribers.append(sub)
        wired["audit"] = sub

    # Register each subscriber for its declared patterns
    for sub in subscribers:
        for pattern in sub.patterns:
            bus.subscribe(pattern, sub.handle)
        _wired_subscribers.append(sub)
        logger.info(
            "[EventBus] Subscriber '%s' wired → %s",
            sub.name, sub.patterns,
        )

    logger.info(
        "[EventBus] %d subscriber(s) wired, %d middleware(s) active",
        len(subscribers),
        len(bus._middleware),
    )

    return wired


def get_wired_subscribers() -> List[Any]:
    """Return the list of currently wired subscribers."""
    return list(_wired_subscribers)


def unwire_all(bus: EventBus) -> None:
    """Remove all wired subscribers (for testing)."""
    global _wired_subscribers
    for sub in _wired_subscribers:
        for pattern in sub.patterns:
            bus.unsubscribe(pattern, sub.handle)
    _wired_subscribers.clear()
