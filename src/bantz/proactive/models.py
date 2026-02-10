"""Data models for the Proactive Intelligence Engine.

Defines the core data structures for proactive checks, cross-analysis
insights, notification policies, and actionable suggestions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ── Check Schedule ──────────────────────────────────────────────


class ScheduleType(Enum):
    """How a proactive check is scheduled."""

    CRON = "cron"          # Cron-like expression
    INTERVAL = "interval"  # Every N seconds/minutes
    DAILY = "daily"        # Fixed time each day
    EVENT = "event"        # Triggered by EventBus event


@dataclass
class CheckSchedule:
    """When and how often a proactive check should run.

    Examples
    --------
    - ``CheckSchedule(type=ScheduleType.DAILY, time_of_day=time(8, 0))``
    - ``CheckSchedule(type=ScheduleType.INTERVAL, interval_seconds=3600)``
    - ``CheckSchedule(type=ScheduleType.CRON, cron_expr="0 8,20 * * *")``
    - ``CheckSchedule(type=ScheduleType.EVENT, event_type="calendar_changed")``
    """

    type: ScheduleType
    time_of_day: Optional[time] = None     # For DAILY
    interval_seconds: int = 3600           # For INTERVAL (default 1h)
    cron_expr: str = ""                    # For CRON
    event_type: str = ""                   # For EVENT trigger
    enabled: bool = True

    def next_run_after(self, after: datetime) -> Optional[datetime]:
        """Calculate the next run time after a given datetime.

        Returns ``None`` for EVENT-based schedules (they are reactive).
        """
        if self.type == ScheduleType.DAILY and self.time_of_day:
            candidate = after.replace(
                hour=self.time_of_day.hour,
                minute=self.time_of_day.minute,
                second=0,
                microsecond=0,
            )
            if candidate <= after:
                candidate += timedelta(days=1)
            return candidate

        if self.type == ScheduleType.INTERVAL:
            return after + timedelta(seconds=self.interval_seconds)

        if self.type == ScheduleType.CRON and self.cron_expr:
            return _next_cron_run(self.cron_expr, after)

        # EVENT-based → no scheduled time
        return None

    @classmethod
    def daily_at(cls, hour: int, minute: int = 0) -> CheckSchedule:
        """Shortcut: daily at HH:MM."""
        return cls(type=ScheduleType.DAILY, time_of_day=time(hour, minute))

    @classmethod
    def every(cls, minutes: int = 0, hours: int = 0, seconds: int = 0) -> CheckSchedule:
        """Shortcut: every N minutes/hours."""
        total = seconds + minutes * 60 + hours * 3600
        return cls(type=ScheduleType.INTERVAL, interval_seconds=max(total, 60))

    @classmethod
    def on_event(cls, event_type: str) -> CheckSchedule:
        """Shortcut: triggered by an EventBus event."""
        return cls(type=ScheduleType.EVENT, event_type=event_type)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type.value, "enabled": self.enabled}
        if self.time_of_day:
            d["time_of_day"] = self.time_of_day.strftime("%H:%M")
        if self.interval_seconds and self.type == ScheduleType.INTERVAL:
            d["interval_seconds"] = self.interval_seconds
        if self.cron_expr:
            d["cron_expr"] = self.cron_expr
        if self.event_type:
            d["event_type"] = self.event_type
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CheckSchedule:
        schedule_type = ScheduleType(data.get("type", "daily"))
        tod = None
        if "time_of_day" in data:
            parts = data["time_of_day"].split(":")
            tod = time(int(parts[0]), int(parts[1]))
        return cls(
            type=schedule_type,
            time_of_day=tod,
            interval_seconds=data.get("interval_seconds", 3600),
            cron_expr=data.get("cron_expr", ""),
            event_type=data.get("event_type", ""),
            enabled=data.get("enabled", True),
        )


# ── Insight & Suggestion ───────────────────────────────────────


class InsightSeverity(Enum):
    """How important a proactive insight is."""

    INFO = "info"          # FYI
    WARNING = "warning"    # Attention needed
    CRITICAL = "critical"  # Urgent action required


@dataclass
class Insight:
    """A single cross-analysis finding.

    Example: "14:00 toplantınız dışarıda ama yağmur bekleniyor."
    """

    message: str
    severity: InsightSeverity = InsightSeverity.INFO
    source_tools: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def icon(self) -> str:
        return {
            InsightSeverity.INFO: "ℹ️",
            InsightSeverity.WARNING: "⚠️",
            InsightSeverity.CRITICAL: "🚨",
        }.get(self.severity, "ℹ️")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "severity": self.severity.value,
            "source_tools": self.source_tools,
            "data": self.data,
        }


@dataclass
class Suggestion:
    """An actionable suggestion attached to an insight.

    Example: "Toplantıyı online'a çevirebilirim" with action "calendar.update_event"
    """

    text: str
    action: str = ""             # Tool or command to invoke
    action_params: Dict[str, Any] = field(default_factory=dict)
    auto_applicable: bool = False  # Can Bantz do this automatically?

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "action": self.action,
            "action_params": self.action_params,
            "auto_applicable": self.auto_applicable,
        }


# ── Cross-Analysis ─────────────────────────────────────────────


@dataclass
class CrossAnalysis:
    """Result of cross-analyzing multiple tool outputs.

    Combines calendar, weather, mail, etc. results into insights.
    """

    check_name: str
    insights: List[Insight] = field(default_factory=list)
    suggestions: List[Suggestion] = field(default_factory=list)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def has_warnings(self) -> bool:
        return any(
            i.severity in (InsightSeverity.WARNING, InsightSeverity.CRITICAL)
            for i in self.insights
        )

    @property
    def max_severity(self) -> InsightSeverity:
        if not self.insights:
            return InsightSeverity.INFO
        return max(self.insights, key=lambda i: list(InsightSeverity).index(i.severity)).severity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "insights": [i.to_dict() for i in self.insights],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "tool_results": self.tool_results,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Check Result ───────────────────────────────────────────────


@dataclass
class CheckResult:
    """Result of running a single proactive check."""

    check_name: str
    ok: bool = True
    summary: str = ""
    analysis: Optional[CrossAnalysis] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "check_name": self.check_name,
            "ok": self.ok,
            "summary": self.summary,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.analysis:
            d["analysis"] = self.analysis.to_dict()
        return d


# ── Proactive Check Definition ─────────────────────────────────


# Type alias for the callable that executes a proactive check
CheckHandler = Callable[["ProactiveCheck", Dict[str, Any]], CheckResult]


@dataclass
class ProactiveCheck:
    """Definition of a single proactive check.

    Each check has a schedule, a handler function, and metadata.
    """

    name: str
    description: str
    schedule: CheckSchedule
    handler: Optional[CheckHandler] = None
    required_tools: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None

    def is_due(self, now: Optional[datetime] = None) -> bool:
        """Check if this proactive check should run now."""
        if not self.enabled or not self.schedule.enabled:
            return False
        if self.schedule.type == ScheduleType.EVENT:
            return False  # Event-based checks don't have "due" times
        now = now or datetime.now()
        return self.next_run is not None and self.next_run <= now

    def update_next_run(self, now: Optional[datetime] = None) -> None:
        """Calculate and set next run time."""
        now = now or datetime.now()
        self.last_run = now
        self.next_run = self.schedule.next_run_after(now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule.to_dict(),
            "required_tools": self.required_tools,
            "tags": self.tags,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }


# ── Notification Policy ────────────────────────────────────────


@dataclass
class NotificationPolicy:
    """Policy controlling when and how proactive notifications are delivered.

    Configurable thresholds for what counts as "important enough" to notify.
    """

    # Minimum severity to trigger notification
    min_severity: InsightSeverity = InsightSeverity.INFO

    # Quiet hours (no notifications)
    quiet_start: Optional[time] = None   # e.g., 23:00
    quiet_end: Optional[time] = None     # e.g., 07:00

    # Rate limiting
    max_notifications_per_hour: int = 10
    max_notifications_per_day: int = 50
    cooldown_seconds: int = 60  # Min seconds between notifications

    # Desktop notification toggle
    desktop_notifications: bool = True

    # Sound toggle
    sound: bool = False

    # Group similar notifications
    group_similar: bool = True

    # Do Not Disturb mode
    dnd: bool = False

    def is_quiet_time(self, now: Optional[datetime] = None) -> bool:
        """Check if we're in quiet hours."""
        if self.dnd:
            return True
        if not self.quiet_start or not self.quiet_end:
            return False
        now = now or datetime.now()
        current = now.time()
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= current <= self.quiet_end
        # Overnight (e.g., 23:00 - 07:00)
        return current >= self.quiet_start or current <= self.quiet_end

    def should_notify(self, severity: InsightSeverity) -> bool:
        """Check if severity meets the minimum threshold."""
        if self.dnd:
            return False
        severity_order = [InsightSeverity.INFO, InsightSeverity.WARNING, InsightSeverity.CRITICAL]
        return severity_order.index(severity) >= severity_order.index(self.min_severity)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_severity": self.min_severity.value,
            "quiet_start": self.quiet_start.strftime("%H:%M") if self.quiet_start else None,
            "quiet_end": self.quiet_end.strftime("%H:%M") if self.quiet_end else None,
            "max_notifications_per_hour": self.max_notifications_per_hour,
            "max_notifications_per_day": self.max_notifications_per_day,
            "cooldown_seconds": self.cooldown_seconds,
            "desktop_notifications": self.desktop_notifications,
            "dnd": self.dnd,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NotificationPolicy:
        quiet_start = None
        quiet_end = None
        if data.get("quiet_start"):
            parts = data["quiet_start"].split(":")
            quiet_start = time(int(parts[0]), int(parts[1]))
        if data.get("quiet_end"):
            parts = data["quiet_end"].split(":")
            quiet_end = time(int(parts[0]), int(parts[1]))
        return cls(
            min_severity=InsightSeverity(data.get("min_severity", "info")),
            quiet_start=quiet_start,
            quiet_end=quiet_end,
            max_notifications_per_hour=data.get("max_notifications_per_hour", 10),
            max_notifications_per_day=data.get("max_notifications_per_day", 50),
            cooldown_seconds=data.get("cooldown_seconds", 60),
            desktop_notifications=data.get("desktop_notifications", True),
            dnd=data.get("dnd", False),
        )


# ── Proactive Notification ─────────────────────────────────────


@dataclass
class ProactiveNotification:
    """A formatted notification ready for delivery."""

    id: int = 0
    check_name: str = ""
    title: str = ""
    body: str = ""
    severity: InsightSeverity = InsightSeverity.INFO
    suggestions: List[Suggestion] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    delivered: bool = False
    read: bool = False

    @property
    def icon(self) -> str:
        return {
            InsightSeverity.INFO: "ℹ️",
            InsightSeverity.WARNING: "⚠️",
            InsightSeverity.CRITICAL: "🚨",
        }.get(self.severity, "ℹ️")

    def format_text(self) -> str:
        """Format for terminal display."""
        lines = [f"{self.icon} {self.title}"]
        if self.body:
            lines.append(f"  {self.body}")
        for s in self.suggestions:
            lines.append(f"  💡 {s.text}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "check_name": self.check_name,
            "title": self.title,
            "body": self.body,
            "severity": self.severity.value,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "timestamp": self.timestamp.isoformat(),
            "delivered": self.delivered,
            "read": self.read,
        }


# ── Cron Helper ─────────────────────────────────────────────────


def _next_cron_run(cron_expr: str, after: datetime) -> Optional[datetime]:
    """Simple cron expression parser for common patterns.

    Supports: ``"M H * * *"`` (minute hour) daily patterns.
    Full cron is complex; we support the subset Bantz actually needs.
    """
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return None

    minute_str, hour_str = parts[0], parts[1]

    # Parse minute(s)
    minutes: List[int] = _parse_cron_field(minute_str, 0, 59)
    hours: List[int] = _parse_cron_field(hour_str, 0, 23)

    if not minutes or not hours:
        return None

    # Find next matching time
    candidate = after.replace(second=0, microsecond=0)
    # Try up to 48 hours ahead
    for _ in range(2880):
        candidate += timedelta(minutes=1)
        if candidate.hour in hours and candidate.minute in minutes:
            return candidate

    return None


def _parse_cron_field(field_str: str, min_val: int, max_val: int) -> List[int]:
    """Parse a single cron field into a list of values.

    Supports: ``*``, ``5``, ``0,30``, ``*/15``, ``8-17``.
    """
    if field_str == "*":
        return list(range(min_val, max_val + 1))

    # */N step
    step_match = re.match(r"\*/(\d+)", field_str)
    if step_match:
        step = int(step_match.group(1))
        return list(range(min_val, max_val + 1, step))

    # Range N-M
    range_match = re.match(r"(\d+)-(\d+)", field_str)
    if range_match:
        start, end = int(range_match.group(1)), int(range_match.group(2))
        return list(range(max(start, min_val), min(end, max_val) + 1))

    # Comma-separated
    if "," in field_str:
        values = []
        for v in field_str.split(","):
            v = v.strip()
            if v.isdigit():
                val = int(v)
                if min_val <= val <= max_val:
                    values.append(val)
        return values

    # Single value
    if field_str.isdigit():
        val = int(field_str)
        if min_val <= val <= max_val:
            return [val]

    return []
