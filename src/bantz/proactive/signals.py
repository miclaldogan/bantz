"""Signal Collectors for the Proactive Secretary Engine.

Each collector gathers ambient context from a specific data source
(calendar, email, weather, tasks, news) and returns a typed signal
dataclass.  ``SignalCollector`` orchestrates all collectors in parallel
via ``asyncio.gather()``.

Issue #1293
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Signal Data Models ──────────────────────────────────────────


@dataclass
class FreeSlot:
    """A gap in the calendar that can be suggested for focused work."""

    start: str  # HH:MM
    end: str    # HH:MM

    @property
    def duration_minutes(self) -> int:
        """Duration in minutes."""
        try:
            sh, sm = map(int, self.start.split(":"))
            eh, em = map(int, self.end.split(":"))
            return (eh * 60 + em) - (sh * 60 + sm)
        except (ValueError, AttributeError):
            return 0

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "duration_minutes": self.duration_minutes}


@dataclass
class CalendarSignal:
    """Signal from Google Calendar."""

    today_events: List[Dict[str, Any]] = field(default_factory=list)
    tomorrow_events: List[Dict[str, Any]] = field(default_factory=list)
    pending_rsvp: List[Dict[str, Any]] = field(default_factory=list)
    free_slots: List[FreeSlot] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "today_count": len(self.today_events),
            "tomorrow_count": len(self.tomorrow_events),
            "pending_rsvp_count": len(self.pending_rsvp),
            "free_slots": [s.to_dict() for s in self.free_slots],
        }


@dataclass
class EmailSignal:
    """Signal from Gmail."""

    unread_count: int = 0
    urgent: List[Dict[str, Any]] = field(default_factory=list)
    needs_follow_up: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unread_count": self.unread_count,
            "urgent_count": len(self.urgent),
            "follow_up_count": len(self.needs_follow_up),
        }


@dataclass
class WeatherSignal:
    """Signal from weather service (refs #838)."""

    temperature: Optional[float] = None
    condition: str = ""
    rain_probability: float = 0.0
    alerts: List[str] = field(default_factory=list)
    tomorrow_condition: str = ""
    tomorrow_temperature: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "condition": self.condition,
            "rain_probability": self.rain_probability,
            "alerts": self.alerts,
        }


@dataclass
class TaskSignal:
    """Signal from Google Tasks."""

    active_tasks: List[Dict[str, Any]] = field(default_factory=list)
    overdue: List[Dict[str, Any]] = field(default_factory=list)
    due_today: List[Dict[str, Any]] = field(default_factory=list)
    due_tomorrow: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def has_pending(self) -> bool:
        return len(self.active_tasks) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_count": len(self.active_tasks),
            "overdue_count": len(self.overdue),
            "due_today_count": len(self.due_today),
            "due_tomorrow_count": len(self.due_tomorrow),
        }


@dataclass
class NewsSignal:
    """Signal from news sources (refs #839)."""

    headlines: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"headline_count": len(self.headlines)}


@dataclass
class DailySignals:
    """Aggregated signals from all collectors."""

    calendar: CalendarSignal = field(default_factory=CalendarSignal)
    emails: EmailSignal = field(default_factory=EmailSignal)
    weather: WeatherSignal = field(default_factory=WeatherSignal)
    tasks: TaskSignal = field(default_factory=TaskSignal)
    news: NewsSignal = field(default_factory=NewsSignal)
    collected_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calendar": self.calendar.to_dict(),
            "emails": self.emails.to_dict(),
            "weather": self.weather.to_dict(),
            "tasks": self.tasks.to_dict(),
            "news": self.news.to_dict(),
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }


# ── Tool Helper ─────────────────────────────────────────────────


def _call_tool_sync(
    tool_registry: Any,
    tool_name: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call a registered tool synchronously (same helper as checks.py)."""
    try:
        tool = tool_registry.get(tool_name)
        if tool is None:
            return {"ok": False, "error": f"Tool '{tool_name}' not found"}
        handler = getattr(tool, "handler", None) or getattr(tool, "function", None)
        if handler is None:
            return {"ok": False, "error": f"Tool '{tool_name}' has no handler"}
        result = handler(**(params or {}))
        return result if isinstance(result, dict) else {"ok": True, "data": result}
    except Exception as exc:
        logger.warning("Signal collector tool call '%s' failed: %s", tool_name, exc)
        return {"ok": False, "error": str(exc)}


# ── Signal Collector ────────────────────────────────────────────


class SignalCollector:
    """Gathers ambient context signals from multiple Bantz tools.

    Uses ``asyncio.gather()`` to collect all signals in parallel,
    with per-source error isolation.

    Parameters
    ----------
    tool_registry:
        The Bantz ToolRegistry for calling tools.
    work_hours:
        Tuple of (start_hour, end_hour) for free-slot calculation.
    """

    def __init__(
        self,
        tool_registry: Any = None,
        *,
        work_hours: tuple[int, int] = (9, 18),
    ) -> None:
        self._tool_registry = tool_registry
        self._work_hours = work_hours

    async def collect_all(self) -> DailySignals:
        """Collect all signals in parallel."""
        results = await asyncio.gather(
            self.collect_calendar(),
            self.collect_emails(),
            self.collect_weather(),
            self.collect_tasks(),
            self.collect_news(),
            return_exceptions=True,
        )

        # Unpack — any exception becomes an empty signal
        signals = DailySignals(collected_at=datetime.now())

        if not isinstance(results[0], BaseException):
            signals.calendar = results[0]
        else:
            logger.warning("Calendar signal failed: %s", results[0])

        if not isinstance(results[1], BaseException):
            signals.emails = results[1]
        else:
            logger.warning("Email signal failed: %s", results[1])

        if not isinstance(results[2], BaseException):
            signals.weather = results[2]
        else:
            logger.warning("Weather signal failed: %s", results[2])

        if not isinstance(results[3], BaseException):
            signals.tasks = results[3]
        else:
            logger.warning("Tasks signal failed: %s", results[3])

        if not isinstance(results[4], BaseException):
            signals.news = results[4]
        else:
            logger.warning("News signal failed: %s", results[4])

        return signals

    # ── Individual Collectors ───────────────────────────────────

    async def collect_calendar(self) -> CalendarSignal:
        """Today + tomorrow events, pending RSVPs, free slots."""
        signal = CalendarSignal()
        if not self._tool_registry:
            return signal

        # Today events
        result = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "calendar.list_events",
        )
        if result.get("ok"):
            events = result.get("events", result.get("data", []))
            if isinstance(events, list):
                signal.today_events = events

        # Tomorrow events
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result2 = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "calendar.list_events",
            {"date": tomorrow},
        )
        if result2.get("ok"):
            events2 = result2.get("events", result2.get("data", []))
            if isinstance(events2, list):
                signal.tomorrow_events = events2
                # Check for pending RSVPs
                for evt in events2:
                    if isinstance(evt, dict):
                        attendees = evt.get("attendees", [])
                        if isinstance(attendees, list):
                            for att in attendees:
                                if isinstance(att, dict):
                                    status = att.get("responseStatus", "")
                                    if status in ("needsAction", "tentative"):
                                        signal.pending_rsvp.append(evt)
                                        break

        # Free slots
        signal.free_slots = self._find_free_slots(
            signal.today_events, self._work_hours,
        )

        return signal

    async def collect_emails(self) -> EmailSignal:
        """Unread count + urgency detection."""
        signal = EmailSignal()
        if not self._tool_registry:
            return signal

        result = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "gmail.unread_count",
        )
        if result.get("ok"):
            signal.unread_count = result.get("unread", result.get("count", 0))

        # Try to get urgent emails (search for important/starred)
        urgent_result = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "gmail.search",
            {"query": "is:unread is:important", "max_results": 5},
        )
        if urgent_result.get("ok"):
            msgs = urgent_result.get("messages", urgent_result.get("data", []))
            if isinstance(msgs, list):
                signal.urgent = msgs

        return signal

    async def collect_weather(self) -> WeatherSignal:
        """Current weather conditions."""
        signal = WeatherSignal()
        if not self._tool_registry:
            return signal

        result = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "weather.get_current",
        )
        if result.get("ok"):
            data = result.get("data", result)
            signal.temperature = data.get("temperature")
            signal.condition = data.get("condition", "")
            signal.rain_probability = data.get("rain_probability", 0.0)
            alerts = data.get("alerts", [])
            if isinstance(alerts, list):
                signal.alerts = [str(a) for a in alerts]

        return signal

    async def collect_tasks(self) -> TaskSignal:
        """Active tasks, overdue, due today/tomorrow."""
        signal = TaskSignal()
        if not self._tool_registry:
            return signal

        result = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "google.tasks.list",
        )
        if result.get("ok"):
            tasks = result.get("tasks", result.get("data", []))
            if isinstance(tasks, list):
                today_str = date.today().isoformat()
                tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    status = task.get("status", "")
                    if status == "completed":
                        continue

                    signal.active_tasks.append(task)
                    due = task.get("due", "")
                    if isinstance(due, str) and len(due) >= 10:
                        due_date = due[:10]
                        if due_date < today_str:
                            signal.overdue.append(task)
                        elif due_date == today_str:
                            signal.due_today.append(task)
                        elif due_date == tomorrow_str:
                            signal.due_tomorrow.append(task)

        return signal

    async def collect_news(self) -> NewsSignal:
        """News headlines (refs #839)."""
        signal = NewsSignal()
        if not self._tool_registry:
            return signal

        result = await asyncio.to_thread(
            _call_tool_sync, self._tool_registry, "news.headlines",
        )
        if result.get("ok"):
            headlines = result.get("headlines", result.get("data", []))
            if isinstance(headlines, list):
                signal.headlines = [
                    h if isinstance(h, dict) else {"title": str(h)}
                    for h in headlines[:5]
                ]

        return signal

    # ── Free Slot Calculator ────────────────────────────────────

    @staticmethod
    def _find_free_slots(
        events: List[Dict[str, Any]],
        work_hours: tuple[int, int],
    ) -> List[FreeSlot]:
        """Find free slots in the calendar based on work hours.

        Parameters
        ----------
        events:
            List of event dicts with 'start'/'end' time strings.
        work_hours:
            ``(start_hour, end_hour)`` tuple.

        Returns
        -------
        list[FreeSlot]
            Gaps of at least 30 minutes.
        """
        start_h, end_h = work_hours
        min_gap_minutes = 30

        # Extract busy intervals as (start_minutes, end_minutes)
        busy: list[tuple[int, int]] = []
        for evt in events:
            if not isinstance(evt, dict):
                continue
            evt_start = evt.get("start", "")
            evt_end = evt.get("end", "")

            s_min = _parse_time_to_minutes(evt_start)
            e_min = _parse_time_to_minutes(evt_end)
            if s_min is not None and e_min is not None and e_min > s_min:
                busy.append((s_min, e_min))

        busy.sort()

        # Merge overlapping intervals
        merged: list[tuple[int, int]] = []
        for s, e in busy:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        # Find gaps
        slots: list[FreeSlot] = []
        current = start_h * 60
        work_end = end_h * 60

        for s, e in merged:
            if s > current and (s - current) >= min_gap_minutes:
                slots.append(FreeSlot(
                    start=f"{current // 60:02d}:{current % 60:02d}",
                    end=f"{s // 60:02d}:{s % 60:02d}",
                ))
            current = max(current, e)

        # Final gap after last event
        if current < work_end and (work_end - current) >= min_gap_minutes:
            slots.append(FreeSlot(
                start=f"{current // 60:02d}:{current % 60:02d}",
                end=f"{work_end // 60:02d}:{work_end % 60:02d}",
            ))

        return slots


# ── Utility ─────────────────────────────────────────────────────


def _parse_time_to_minutes(value: Any) -> Optional[int]:
    """Extract HH:MM from various time formats and return total minutes.

    Supports:
    - ``"10:00"``
    - ``"2025-01-15T10:00:00"``
    - ``{"dateTime": "2025-01-15T10:00:00+03:00"}``
    """
    if isinstance(value, dict):
        value = value.get("dateTime", value.get("date", ""))
    if not isinstance(value, str):
        return None

    # Try to find HH:MM in the string
    if "T" in value:
        time_part = value.split("T")[1][:5]
    elif len(value) == 5 and ":" in value:
        time_part = value
    else:
        return None

    try:
        h, m = map(int, time_part.split(":"))
        return h * 60 + m
    except (ValueError, AttributeError):
        return None
