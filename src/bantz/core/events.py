"""Bantz Event Bus - Pub/sub system for proactive messaging.

Events flow:
- Reminder fires → publish("reminder_fired", {...})
- Check-in triggers → publish("checkin_triggered", {...})
- Bantz wants to speak → publish("bantz_message", {...})

Subscribers:
- CLI: prints proactive messages
- Browser panel: shows in chat (future)
- Logger: records event history
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any


@dataclass
class Event:
    """Single event in the bus."""
    event_type: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "core"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }


# Type alias for event handlers
EventHandler = Callable[[Event], None]


class EventBus:
    """Simple pub/sub event bus with history."""
    
    def __init__(self, history_size: int = 100):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._global_subscribers: List[EventHandler] = []
        self._history: deque[Event] = deque(maxlen=history_size)
        self._lock = threading.Lock()
    
    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)
    
    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events."""
        with self._lock:
            self._global_subscribers.append(handler)
    
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
    
    def publish(self, event_type: str, data: Optional[Dict[str, Any]] = None, source: str = "core") -> Event:
        """Publish an event to all subscribers."""
        event = Event(
            event_type=event_type,
            data=data or {},
            source=source,
        )
        
        with self._lock:
            # Add to history
            self._history.append(event)
            
            # Get handlers (copy to avoid lock during execution)
            handlers = list(self._subscribers.get(event_type, []))
            global_handlers = list(self._global_subscribers)
        
        # Execute handlers outside lock
        for handler in handlers + global_handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[EventBus] Handler error: {e}")
        
        return event
    
    def get_history(self, event_type: Optional[str] = None, limit: int = 20) -> List[Event]:
        """Get recent events from history."""
        with self._lock:
            if event_type:
                events = [e for e in self._history if e.event_type == event_type]
            else:
                events = list(self._history)
        
        return events[-limit:]
    
    def clear_history(self) -> None:
        """Clear event history."""
        with self._lock:
            self._history.clear()


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


# ─────────────────────────────────────────────────────────────────
# Standard event types (for documentation)
# ─────────────────────────────────────────────────────────────────
"""
Standard events:

reminder_fired:
    data: {id, message, time}
    source: scheduler
    
checkin_triggered:
    data: {id, prompt}
    source: scheduler
    
bantz_message:
    data: {text, intent, proactive: True}
    source: core
    
command_result:
    data: {command, result, ok}
    source: router
"""
