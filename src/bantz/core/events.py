"""Bantz Event Bus — Async pub/sub system for internal communication.

Issue #1297: Event Bus — Async Pub/Sub İç İletişim Altyapısı.

Features:
- Synchronous and async publish
- Wildcard prefix subscribe: ``tool.*`` matches ``tool.executed``, ``tool.failed``
- Catch-all subscribe: ``*``
- Middleware chain for logging, filtering, rate limiting
- Correlation ID for run tracking
- Fire-and-forget error handling
- Thread-safe history

Events flow:
- tool_runner → publish("tool.executed", {...})
- Reminder fires → publish("reminder_fired", {...})
- Mail received → publish("mail.received", {...})
- Bantz wants to speak → publish("bantz_message", {...})
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventType(Enum):
    """
    Standard event types for the Bantz system.
    
    Categories:
    - Acknowledgment: Initial response events
    - Progress: Task progress updates
    - Interaction: User interaction events
    - Errors: Error and retry events
    - Control: Job control events
    - Legacy: Existing event types for compatibility
    """
    
    # === Acknowledgment ===
    ACK = "ack"  # "Anladım efendim, başlıyorum"
    
    # === Progress ===
    PROGRESS = "progress"  # {"current": 3, "total": 5, "message": "..."}
    FOUND = "found"  # {"source": "url", "title": "..."}
    SUMMARIZING = "summarizing"  # {"status": "started/complete"}
    
    # === Interaction ===
    QUESTION = "question"  # {"question": "...", "options": [...]}
    RESULT = "result"  # {"summary": "...", "confidence": 0.85}
    
    # === Errors ===
    ERROR = "error"  # {"code": "...", "message": "..."}
    RETRY = "retry"  # {"attempt": 2, "reason": "timeout"}
    
    # === Control ===
    PAUSE = "pause"  # Job duraklatıldı
    RESUME = "resume"  # Job devam ediyor
    CANCEL = "cancel"  # Job iptal edildi
    
    # === Job Lifecycle ===
    JOB_CREATED = "job.created"  # New job created
    JOB_STARTED = "job.started"  # Job started running
    JOB_COMPLETED = "job.completed"  # Job completed successfully
    JOB_FAILED = "job.failed"  # Job failed
    JOB_PAUSED = "job.paused"  # Job paused
    JOB_RESUMED = "job.resumed"  # Job resumed
    JOB_CANCELLED = "job.cancelled"  # Job cancelled
    
    # === Orchestrator Trace Events (Issue #284) ===
    TURN_START = "turn.start"  # Turn başladı
    INTENT_DETECTED = "intent.detected"  # Niyet tespit edildi
    SLOTS_EXTRACTED = "slots.extracted"  # Slot'lar çıkarıldı  
    TOOL_SELECTED = "tool.selected"  # Tool seçildi
    TOOL_CALL = "tool.call"  # Tool çağrılıyor
    TOOL_RESULT = "tool.result"  # Tool sonucu geldi
    FINALIZER_START = "finalizer.start"  # Yanıt son haline getiriliyor
    FINALIZER_END = "finalizer.end"  # Yanıt tamamlandı
    TURN_END = "turn.end"  # Turn bitti

    # === Overnight Mode (Issue #836) ===
    OVERNIGHT_STARTED = "overnight.started"  # Gece modu başladı
    OVERNIGHT_TASK_STARTED = "overnight.task.started"  # Bir görev başladı
    OVERNIGHT_TASK_COMPLETED = "overnight.task.completed"  # Görev tamamlandı
    OVERNIGHT_TASK_FAILED = "overnight.task.failed"  # Görev başarısız
    OVERNIGHT_CHECKPOINT = "overnight.checkpoint"  # Checkpoint kaydedildi
    OVERNIGHT_WAITING_HUMAN = "overnight.waiting_human"  # İnsan kararı bekleniyor
    OVERNIGHT_RESUMED = "overnight.resumed"  # Checkpoint'tan devam
    OVERNIGHT_MORNING_REPORT = "overnight.morning_report"  # Sabah raporu hazır
    OVERNIGHT_COMPLETED = "overnight.completed"  # Tüm görevler tamamlandı

    # === Tool Execution (Issue #1297) ===
    TOOL_EXECUTED = "tool.executed"      # Tool başarıyla çalıştı
    TOOL_FAILED = "tool.failed"          # Tool hata aldı
    TOOL_CONFIRMED = "tool.confirmed"    # Kullanıcı onayladı
    TOOL_DENIED = "tool.denied"          # Kullanıcı reddetti

    # === Data Events (Issue #1297) ===
    MAIL_RECEIVED = "mail.received"      # Yeni mail geldi
    MAIL_SENT = "mail.sent"              # Mail gönderildi
    CALENDAR_CREATED = "calendar.created"  # Etkinlik oluşturuldu
    CALENDAR_UPDATED = "calendar.updated"  # Etkinlik güncellendi
    TASK_COMPLETED = "task.completed"     # Görev tamamlandı

    # === Run Lifecycle (Issue #1297) ===
    RUN_STARTED = "run.started"          # Yeni kullanıcı isteği
    RUN_COMPLETED = "run.completed"      # İstek tamamlandı
    SESSION_STARTED = "session.started"  # Yeni oturum
    BRIEF_GENERATED = "brief.generated"  # Daily brief oluşturuldu

    # === Legacy (for backward compatibility) ===
    REMINDER_FIRED = "reminder_fired"
    CHECKIN_TRIGGERED = "checkin_triggered"
    BANTZ_MESSAGE = "bantz_message"
    COMMAND_RESULT = "command_result"

    # === Health & Degradation (Issue #1298) ===
    HEALTH_CHECK = "system.health_check"          # Sağlık kontrolü yapıldı
    HEALTH_DEGRADED = "system.health_degraded"    # Servis bozuldu
    HEALTH_RECOVERED = "system.health_recovered"  # Servis düzeldi
    CIRCUIT_OPENED = "system.circuit_opened"      # Circuit breaker açıldı
    CIRCUIT_CLOSED = "system.circuit_closed"      # Circuit breaker kapandı
    FALLBACK_EXECUTED = "system.fallback_executed" # Fallback çalıştırıldı


@dataclass
class Event:
    """Single event in the bus."""
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "core"
    correlation_id: Optional[str] = None  # Run/job tracking ID

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }
        if self.correlation_id:
            d["correlation_id"] = self.correlation_id
        return d


# Type aliases for event handlers and middleware
EventHandler = Callable[[Event], None]
AsyncEventHandler = Callable[[Event], Any]  # Coroutine-returning handler
Middleware = Callable[[Event], Optional[Event]]  # Sync middleware
AsyncMiddleware = Callable[[Event], Any]  # Async middleware (returns Event|None)


class EventBus:
    """Pub/sub event bus with wildcard matching, middleware, and async support.

    Features:
    - Exact-match subscribe: ``subscribe("tool.executed", handler)``
    - Wildcard prefix subscribe: ``subscribe("tool.*", handler)``
      matches any event whose type starts with ``tool.``
    - Catch-all: ``subscribe_all(handler)``
    - Middleware chain: transform/filter events before dispatch
    - Async publish: ``apublish()`` for coroutine handlers
    - Fire-and-forget: subscriber errors never block the publisher
    """

    def __init__(self, history_size: int = 100) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._async_subscribers: Dict[str, List[AsyncEventHandler]] = {}
        self._global_subscribers: List[EventHandler] = []
        self._async_global_subscribers: List[AsyncEventHandler] = []
        self._middleware: List[Middleware] = []
        self._async_middleware: List[AsyncMiddleware] = []
        self._history: deque[Event] = deque(maxlen=history_size)
        self._lock = threading.Lock()

    # ── Subscribe ────────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to a specific event type.

        Supports wildcard prefix patterns:
        - ``"tool.executed"`` — exact match
        - ``"tool.*"`` — matches any event starting with ``tool.``
        - Use ``subscribe_all()`` for catch-all.
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)

    def subscribe_async(
        self, event_type: str, handler: AsyncEventHandler
    ) -> None:
        """Subscribe an async handler to a specific event type.

        Supports the same wildcard patterns as ``subscribe()``.
        """
        with self._lock:
            if event_type not in self._async_subscribers:
                self._async_subscribers[event_type] = []
            self._async_subscribers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (catch-all)."""
        with self._lock:
            self._global_subscribers.append(handler)

    def subscribe_all_async(self, handler: AsyncEventHandler) -> None:
        """Subscribe an async handler to ALL events."""
        with self._lock:
            self._async_global_subscribers.append(handler)

    # ── Unsubscribe ──────────────────────────────────────────────

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe from an event type."""
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                except ValueError:
                    pass

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Unsubscribe from global subscription."""
        with self._lock:
            try:
                self._global_subscribers.remove(handler)
            except ValueError:
                pass

    # ── Middleware ────────────────────────────────────────────────

    def add_middleware(self, middleware: Middleware) -> None:
        """Add a sync middleware to the processing chain.

        Middleware receives an Event and returns an Event (possibly modified)
        or None to suppress the event entirely.
        """
        self._middleware.append(middleware)

    def add_async_middleware(self, middleware: AsyncMiddleware) -> None:
        """Add an async middleware to the processing chain."""
        self._async_middleware.append(middleware)

    # ── Publish ──────────────────────────────────────────────────

    def publish(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        source: str = "core",
        correlation_id: Optional[str] = None,
    ) -> Optional[Event]:
        """Publish an event synchronously.

        Runs all sync middleware first, then dispatches to sync handlers.
        Async handlers are NOT called — use ``apublish()`` for full dispatch.

        Returns:
            The Event, or None if a middleware suppressed it.
        """
        event = Event(
            event_type=event_type,
            data=data or {},
            source=source,
            correlation_id=correlation_id,
        )

        # Run sync middleware
        for mw in self._middleware:
            try:
                event = mw(event)
            except Exception as exc:
                logger.error("[EventBus] Middleware error: %s", exc)
                return None
            if event is None:
                return None  # Middleware suppressed the event

        with self._lock:
            self._history.append(event)
            handlers = self._collect_sync_handlers(event.event_type)

        # Fire-and-forget: handler errors never propagate
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.error(
                    "[EventBus] Handler %s error on %s: %s",
                    getattr(handler, "__name__", repr(handler)),
                    event.event_type,
                    exc,
                )

        return event

    async def apublish(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        source: str = "core",
        correlation_id: Optional[str] = None,
    ) -> Optional[Event]:
        """Publish an event asynchronously.

        Runs all middleware (sync + async), then dispatches to all handlers
        (sync + async) concurrently. Fire-and-forget: errors are logged.

        Returns:
            The Event, or None if a middleware suppressed it.
        """
        event = Event(
            event_type=event_type,
            data=data or {},
            source=source,
            correlation_id=correlation_id,
        )

        # Run sync middleware
        for mw in self._middleware:
            try:
                event = mw(event)
            except Exception as exc:
                logger.error("[EventBus] Middleware error: %s", exc)
                return None
            if event is None:
                return None

        # Run async middleware
        for mw in self._async_middleware:
            try:
                event = await mw(event)
            except Exception as exc:
                logger.error("[EventBus] Async middleware error: %s", exc)
                return None
            if event is None:
                return None

        with self._lock:
            self._history.append(event)
            sync_handlers = self._collect_sync_handlers(event.event_type)
            async_handlers = self._collect_async_handlers(event.event_type)

        # Dispatch sync handlers
        for handler in sync_handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.error(
                    "[EventBus] Handler %s error: %s",
                    getattr(handler, "__name__", repr(handler)),
                    exc,
                )

        # Dispatch async handlers (fire-and-forget)
        if async_handlers:
            tasks = [
                asyncio.create_task(self._safe_async_call(h, event))
                for h in async_handlers
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

        return event

    # ── History ──────────────────────────────────────────────────

    def get_history(
        self, event_type: Optional[str] = None, limit: int = 20
    ) -> List[Event]:
        """Get recent events from history."""
        with self._lock:
            if event_type:
                events = [
                    e for e in self._history
                    if e.event_type == event_type
                ]
            else:
                events = list(self._history)

        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        with self._lock:
            self._history.clear()

    # ── Internal ─────────────────────────────────────────────────

    def _collect_sync_handlers(self, event_type: str) -> List[EventHandler]:
        """Collect matching sync handlers: exact + wildcard + global."""
        handlers: List[EventHandler] = []

        # Exact match
        handlers.extend(self._subscribers.get(event_type, []))

        # Wildcard prefix match: "tool.*" matches "tool.executed"
        for pattern, subs in self._subscribers.items():
            if pattern.endswith(".*") and event_type.startswith(pattern[:-2] + "."):
                handlers.extend(subs)

        # Global catch-all
        handlers.extend(self._global_subscribers)

        return handlers

    def _collect_async_handlers(
        self, event_type: str
    ) -> List[AsyncEventHandler]:
        """Collect matching async handlers: exact + wildcard + global."""
        handlers: List[AsyncEventHandler] = []

        # Exact match
        handlers.extend(self._async_subscribers.get(event_type, []))

        # Wildcard prefix match
        for pattern, subs in self._async_subscribers.items():
            if pattern.endswith(".*") and event_type.startswith(pattern[:-2] + "."):
                handlers.extend(subs)

        # Global catch-all
        handlers.extend(self._async_global_subscribers)

        return handlers

    @staticmethod
    async def _safe_async_call(
        handler: AsyncEventHandler, event: Event
    ) -> None:
        """Call an async handler with error logging."""
        try:
            await handler(event)
        except Exception as exc:
            logger.error(
                "[EventBus] Async handler %s error: %s",
                getattr(handler, "__name__", repr(handler)),
                exc,
            )


# ─────────────────────────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────────────────────────
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create singleton event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset singleton (for tests)."""
    global _event_bus
    _event_bus = None
