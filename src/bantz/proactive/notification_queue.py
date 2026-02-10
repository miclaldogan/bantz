"""Notification queue for the Proactive Intelligence Engine.

Manages queuing, rate-limiting, deduplication, and delivery of
proactive notifications. Integrates with the EventBus for CLI/UI
consumption and optionally sends desktop notifications.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional

from bantz.proactive.models import (
    CheckResult,
    CrossAnalysis,
    Insight,
    InsightSeverity,
    NotificationPolicy,
    ProactiveNotification,
    Suggestion,
)

logger = logging.getLogger(__name__)


class NotificationQueue:
    """Thread-safe notification queue with policy-based filtering.

    Integrates with the EventBus to deliver notifications to CLI/UI,
    and can also send desktop notifications via ``notify-send``.
    """

    def __init__(
        self,
        policy: Optional[NotificationPolicy] = None,
        event_bus: Any = None,
        max_size: int = 200,
    ) -> None:
        self.policy = policy or NotificationPolicy()
        self._event_bus = event_bus
        self._queue: Deque[ProactiveNotification] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._next_id = 1
        self._hourly_count = 0
        self._daily_count = 0
        self._last_hour_reset = datetime.now()
        self._last_day_reset = datetime.now().date()
        self._last_notification_time: Optional[datetime] = None
        self._recent_bodies: Deque[str] = deque(maxlen=20)

    # ── Public API ──────────────────────────────────────────────

    def submit(self, result: CheckResult) -> List[ProactiveNotification]:
        """Submit a check result and create notifications based on policy.

        Returns list of notifications that were actually queued.
        """
        if not result.ok or not result.analysis:
            return []

        return self._process_analysis(result.check_name, result.analysis, result.summary)

    def submit_notification(self, notification: ProactiveNotification) -> bool:
        """Submit a pre-built notification directly.

        Returns True if the notification was queued (passed policy filters).
        """
        if not self._policy_allows(notification.severity):
            return False
        if self._is_duplicate(notification.body):
            return False
        return self._enqueue(notification)

    def get_all(self, *, unread_only: bool = False) -> List[ProactiveNotification]:
        """Get all notifications (newest first)."""
        with self._lock:
            items = list(self._queue)
        if unread_only:
            items = [n for n in items if not n.read]
        items.reverse()
        return items

    def get_unread_count(self) -> int:
        with self._lock:
            return sum(1 for n in self._queue if not n.read)

    def mark_read(self, notification_id: int) -> bool:
        """Mark a notification as read."""
        with self._lock:
            for n in self._queue:
                if n.id == notification_id:
                    n.read = True
                    return True
        return False

    def mark_all_read(self) -> int:
        """Mark all notifications as read. Returns count."""
        count = 0
        with self._lock:
            for n in self._queue:
                if not n.read:
                    n.read = True
                    count += 1
        return count

    def clear(self) -> int:
        """Clear all notifications. Returns count removed."""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def update_policy(self, policy: NotificationPolicy) -> None:
        """Update the notification policy."""
        self.policy = policy

    def set_dnd(self, enabled: bool) -> None:
        """Toggle Do Not Disturb mode."""
        self.policy.dnd = enabled

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    # ── Internal ────────────────────────────────────────────────

    def _process_analysis(
        self,
        check_name: str,
        analysis: CrossAnalysis,
        summary: str,
    ) -> List[ProactiveNotification]:
        """Convert a CrossAnalysis into notifications."""
        queued: List[ProactiveNotification] = []

        if not analysis.insights:
            return queued

        # If there are warnings/critical, create individual notifications
        # Otherwise, create a single summary notification
        has_important = analysis.has_warnings

        if has_important:
            # Individual notification per warning/critical insight
            for insight in analysis.insights:
                if insight.severity in (InsightSeverity.WARNING, InsightSeverity.CRITICAL):
                    # Find related suggestions
                    related_suggestions = [
                        s for s in analysis.suggestions
                        if any(t in s.action for t in insight.source_tools) or not s.action
                    ]
                    notification = ProactiveNotification(
                        check_name=check_name,
                        title=f"[{check_name}] {insight.icon}",
                        body=insight.message,
                        severity=insight.severity,
                        suggestions=related_suggestions[:3],
                    )
                    if self.submit_notification(notification):
                        queued.append(notification)

        # Always create summary notification (may be grouped)
        summary_notification = ProactiveNotification(
            check_name=check_name,
            title=check_name.replace("_", " ").title(),
            body=summary,
            severity=analysis.max_severity,
            suggestions=analysis.suggestions[:3],
        )
        if self.submit_notification(summary_notification):
            queued.append(summary_notification)

        return queued

    def _policy_allows(self, severity: InsightSeverity) -> bool:
        """Check if the notification policy allows this notification."""
        now = datetime.now()

        # DND check
        if self.policy.dnd:
            logger.debug("Notification blocked: DND mode active")
            return False

        # Severity threshold
        if not self.policy.should_notify(severity):
            logger.debug("Notification blocked: severity %s below threshold", severity.value)
            return False

        # Quiet hours (critical always goes through)
        if severity != InsightSeverity.CRITICAL and self.policy.is_quiet_time(now):
            logger.debug("Notification blocked: quiet hours")
            return False

        # Rate limiting
        self._reset_counters_if_needed(now)

        if self._hourly_count >= self.policy.max_notifications_per_hour:
            logger.debug("Notification blocked: hourly limit reached (%d)", self._hourly_count)
            return False

        if self._daily_count >= self.policy.max_notifications_per_day:
            logger.debug("Notification blocked: daily limit reached (%d)", self._daily_count)
            return False

        # Cooldown
        if (
            self._last_notification_time
            and (now - self._last_notification_time).total_seconds() < self.policy.cooldown_seconds
            and severity != InsightSeverity.CRITICAL
        ):
            logger.debug("Notification blocked: cooldown period")
            return False

        return True

    def _is_duplicate(self, body: str) -> bool:
        """Check if a similar notification was recently sent."""
        if not self.policy.group_similar:
            return False
        with self._lock:
            return body in self._recent_bodies

    def _enqueue(self, notification: ProactiveNotification) -> bool:
        """Add notification to queue and deliver."""
        now = datetime.now()
        with self._lock:
            notification.id = self._next_id
            self._next_id += 1
            notification.timestamp = now
            notification.delivered = True
            self._queue.append(notification)
            self._hourly_count += 1
            self._daily_count += 1
            self._last_notification_time = now
            self._recent_bodies.append(notification.body)

        # Deliver via EventBus
        self._publish_to_event_bus(notification)

        # Desktop notification
        if self.policy.desktop_notifications:
            self._send_desktop_notification(notification)

        logger.info(
            "Proactive notification #%d [%s]: %s",
            notification.id,
            notification.severity.value,
            notification.body[:80],
        )
        return True

    def _publish_to_event_bus(self, notification: ProactiveNotification) -> None:
        """Publish notification to EventBus for CLI/UI consumption."""
        if not self._event_bus:
            return
        try:
            self._event_bus.publish(
                event_type="bantz_message",
                data={
                    "text": notification.format_text(),
                    "intent": f"proactive.{notification.check_name}",
                    "proactive": True,
                    "kind": "proactive",
                    "notification_id": notification.id,
                    "severity": notification.severity.value,
                    "check_name": notification.check_name,
                },
                source="proactive",
            )
        except Exception as e:
            logger.warning("Failed to publish proactive event: %s", e)

    def _send_desktop_notification(self, notification: ProactiveNotification) -> None:
        """Send desktop notification via notify-send."""
        urgency = {
            InsightSeverity.INFO: "normal",
            InsightSeverity.WARNING: "normal",
            InsightSeverity.CRITICAL: "critical",
        }.get(notification.severity, "normal")

        try:
            subprocess.run(
                [
                    "notify-send",
                    "-u", urgency,
                    "-i", "dialog-information",
                    f"🧠 Bantz — {notification.title}",
                    notification.body[:200],
                ],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except Exception as e:
            logger.debug("Desktop notification failed (OK if no display): %s", e)

    def _reset_counters_if_needed(self, now: datetime) -> None:
        """Reset hourly/daily counters if time has passed."""
        if (now - self._last_hour_reset).total_seconds() >= 3600:
            self._hourly_count = 0
            self._last_hour_reset = now

        if now.date() != self._last_day_reset:
            self._daily_count = 0
            self._last_day_reset = now.date()
