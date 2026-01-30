"""
DBus Notification Listener.

Listens to system notifications via DBus org.freedesktop.Notifications interface.
Works on GNOME, KDE, XFCE, and other Linux desktop environments.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Any, Set
import asyncio
import logging
import re

logger = logging.getLogger(__name__)


class NotificationUrgency(Enum):
    """Notification urgency levels per freedesktop spec."""
    LOW = 0
    NORMAL = 1
    CRITICAL = 2


@dataclass
class Notification:
    """Represents a system notification."""
    
    app_name: str
    summary: str
    body: str = ""
    app_icon: str = ""
    urgency: NotificationUrgency = NotificationUrgency.NORMAL
    actions: List[str] = field(default_factory=list)
    hints: Dict[str, Any] = field(default_factory=dict)
    expire_timeout: int = -1
    timestamp: datetime = field(default_factory=datetime.now)
    replaces_id: int = 0
    
    def matches_app(self, pattern: str) -> bool:
        """Check if app name matches pattern (case-insensitive)."""
        return bool(re.search(pattern, self.app_name, re.IGNORECASE))
    
    def matches_content(self, pattern: str) -> bool:
        """Check if summary or body matches pattern (case-insensitive)."""
        return bool(
            re.search(pattern, self.summary, re.IGNORECASE) or
            re.search(pattern, self.body, re.IGNORECASE)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "app": self.app_name,
            "title": self.summary,
            "body": self.body,
            "icon": self.app_icon,
            "urgency": self.urgency.name.lower(),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class NotificationFilter:
    """Filter for notifications."""
    
    app_patterns: List[str] = field(default_factory=list)
    content_patterns: List[str] = field(default_factory=list)
    min_urgency: NotificationUrgency = NotificationUrgency.LOW
    exclude_apps: Set[str] = field(default_factory=set)
    include_only_apps: Optional[Set[str]] = None
    
    def matches(self, notification: Notification) -> bool:
        """Check if notification passes filter."""
        # Check urgency
        if notification.urgency.value < self.min_urgency.value:
            return False
        
        # Check app exclusion
        if notification.app_name.lower() in {a.lower() for a in self.exclude_apps}:
            return False
        
        # Check app inclusion (if specified)
        if self.include_only_apps is not None:
            if notification.app_name.lower() not in {a.lower() for a in self.include_only_apps}:
                return False
        
        # Check app patterns
        if self.app_patterns:
            if not any(notification.matches_app(p) for p in self.app_patterns):
                return False
        
        # Check content patterns
        if self.content_patterns:
            if not any(notification.matches_content(p) for p in self.content_patterns):
                return False
        
        return True


class NotificationListener:
    """
    Listen to system notifications via DBus.
    
    Uses org.freedesktop.Notifications interface to monitor
    all notifications sent to the notification daemon.
    
    Example:
        async def on_notification(notif: Notification):
            print(f"{notif.app_name}: {notif.summary}")
        
        listener = NotificationListener(on_notification)
        await listener.start()
    """
    
    SERVICE_NAME = "org.freedesktop.Notifications"
    OBJECT_PATH = "/org/freedesktop/Notifications"
    INTERFACE_NAME = "org.freedesktop.Notifications"
    
    def __init__(
        self,
        callback: Callable[[Notification], None],
        notification_filter: Optional[NotificationFilter] = None,
        async_callback: bool = False,
    ):
        """
        Initialize notification listener.
        
        Args:
            callback: Function to call when notification received
            notification_filter: Optional filter to apply
            async_callback: Whether callback is async
        """
        self.callback = callback
        self.filter = notification_filter or NotificationFilter()
        self.async_callback = async_callback
        
        self._bus = None
        self._running = False
        self._notifications: List[Notification] = []
        self._max_history = 100
    
    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running
    
    @property
    def history(self) -> List[Notification]:
        """Get notification history."""
        return self._notifications.copy()
    
    async def start(self) -> None:
        """Start listening to notifications."""
        if self._running:
            logger.warning("Notification listener already running")
            return
        
        try:
            # Import dbus-next only when needed
            from dbus_next.aio import MessageBus
            from dbus_next import BusType, Message
            
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            logger.info("Connected to session bus")
            
            # Add message handler
            self._bus.add_message_handler(self._on_message)
            
            # Subscribe to Notify method calls
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[
                        f"type='method_call',"
                        f"interface='{self.INTERFACE_NAME}',"
                        f"member='Notify'"
                    ],
                )
            )
            
            self._running = True
            logger.info("Notification listener started")
            
        except ImportError:
            logger.error("dbus-next not installed. Install with: pip install dbus-next")
            raise
        except Exception as e:
            logger.error(f"Failed to start notification listener: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop listening to notifications."""
        if not self._running:
            return
        
        self._running = False
        
        if self._bus:
            self._bus.disconnect()
            self._bus = None
        
        logger.info("Notification listener stopped")
    
    def _on_message(self, message) -> bool:
        """Handle incoming DBus message."""
        try:
            # Check if this is a Notify call
            if message.member != "Notify":
                return False
            
            if not message.body or len(message.body) < 5:
                return False
            
            # Parse notification from message body
            # Notify signature: (susssasa{sv}i)
            # app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout
            app_name = message.body[0] if len(message.body) > 0 else ""
            replaces_id = message.body[1] if len(message.body) > 1 else 0
            app_icon = message.body[2] if len(message.body) > 2 else ""
            summary = message.body[3] if len(message.body) > 3 else ""
            body = message.body[4] if len(message.body) > 4 else ""
            actions = message.body[5] if len(message.body) > 5 else []
            hints = message.body[6] if len(message.body) > 6 else {}
            expire_timeout = message.body[7] if len(message.body) > 7 else -1
            
            # Get urgency from hints
            urgency = NotificationUrgency.NORMAL
            if "urgency" in hints:
                urgency_value = hints["urgency"]
                if hasattr(urgency_value, "value"):
                    urgency_value = urgency_value.value
                try:
                    urgency = NotificationUrgency(int(urgency_value))
                except ValueError:
                    pass
            
            notification = Notification(
                app_name=app_name,
                summary=summary,
                body=body,
                app_icon=app_icon,
                urgency=urgency,
                actions=list(actions) if actions else [],
                hints=dict(hints) if hints else {},
                expire_timeout=expire_timeout,
                replaces_id=replaces_id,
            )
            
            # Apply filter
            if not self.filter.matches(notification):
                logger.debug(f"Notification filtered: {app_name}")
                return False
            
            # Store in history
            self._notifications.append(notification)
            if len(self._notifications) > self._max_history:
                self._notifications.pop(0)
            
            # Call callback
            try:
                if self.async_callback:
                    asyncio.create_task(self.callback(notification))
                else:
                    self.callback(notification)
            except Exception as e:
                logger.error(f"Error in notification callback: {e}")
            
            logger.debug(f"Notification: {app_name} - {summary}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing notification: {e}")
            return False
    
    def clear_history(self) -> None:
        """Clear notification history."""
        self._notifications.clear()
    
    def get_notifications_from_app(self, app_name: str) -> List[Notification]:
        """Get notifications from specific app."""
        return [n for n in self._notifications if n.matches_app(app_name)]
    
    async def wait_for_notification(
        self,
        app_pattern: Optional[str] = None,
        content_pattern: Optional[str] = None,
        timeout: float = 30.0,
    ) -> Optional[Notification]:
        """
        Wait for a specific notification.
        
        Args:
            app_pattern: Regex pattern for app name
            content_pattern: Regex pattern for content
            timeout: Maximum time to wait
            
        Returns:
            Matching notification or None if timeout
        """
        result: List[Optional[Notification]] = [None]
        event = asyncio.Event()
        
        original_callback = self.callback
        
        def check_notification(notif: Notification):
            matches = True
            if app_pattern and not notif.matches_app(app_pattern):
                matches = False
            if content_pattern and not notif.matches_content(content_pattern):
                matches = False
            
            if matches:
                result[0] = notif
                event.set()
            
            # Call original callback
            original_callback(notif)
        
        self.callback = check_notification
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return result[0]
        except asyncio.TimeoutError:
            return None
        finally:
            self.callback = original_callback


class MockNotificationListener(NotificationListener):
    """
    Mock notification listener for testing without DBus.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_notifications: List[Notification] = []
    
    async def start(self) -> None:
        """Start mock listener."""
        self._running = True
        logger.info("Mock notification listener started")
    
    async def stop(self) -> None:
        """Stop mock listener."""
        self._running = False
        logger.info("Mock notification listener stopped")
    
    async def emit_notification(self, notification: Notification) -> None:
        """Emit a mock notification for testing."""
        if not self._running:
            return
        
        # Apply filter
        if not self.filter.matches(notification):
            return
        
        # Store in history
        self._notifications.append(notification)
        if len(self._notifications) > self._max_history:
            self._notifications.pop(0)
        
        # Call callback
        if self.async_callback:
            await self.callback(notification)
        else:
            self.callback(notification)
    
    async def emit(
        self,
        app_name: str,
        summary: str,
        body: str = "",
        urgency: NotificationUrgency = NotificationUrgency.NORMAL,
    ) -> None:
        """Convenience method to emit a notification."""
        await self.emit_notification(Notification(
            app_name=app_name,
            summary=summary,
            body=body,
            urgency=urgency,
        ))
