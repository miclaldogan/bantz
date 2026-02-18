"""Daily Program Manager — multi-source daily briefing & planning (Issue #844).

Answers "What do I need to do today?" by combining Calendar, Gmail,
Reminders and weather data into a comprehensive response.

Features
────────
- Multi-source aggregation (Calendar, Gmail, Reminders)
- Smart prioritization (deadline × importance × urgency)
- Day plan suggestions (time blocks by hour)
- Conflict detection (overlapping events)
- Follow-up action suggestions
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from enum import IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Intent patterns ──────────────────────────────────────────────────

DAILY_INTENTS = [
    r"(?i)bugün\s*(ne|neler)\s*(yapmam|yapmalıyım|yapmak|var)",
    r"(?i)günlük\s*(program|plan|özet|briefing)",
    r"(?i)günüm\s*(nasıl|ne)",
    r"(?i)today.*(plan|schedule|agenda|todo|brief)",
    r"(?i)what.*(do|should).*(today|now)",
    r"(?i)daily\s*(briefing|summary|plan|agenda)",
    r"(?i)gün(ün|üm)\s*(özet|plan)",
]


def is_daily_intent(text: str) -> bool:
    """Check whether *text* is a daily-program request."""
    return any(re.search(p, text) for p in DAILY_INTENTS)


# ── Priority model ──────────────────────────────────────────────────

class Urgency(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class Importance(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class DailyItem:
    """A single item in the daily plan."""
    source: str              # calendar | gmail | reminder | classroom
    title: str
    description: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deadline: Optional[datetime] = None
    urgency: Urgency = Urgency.MEDIUM
    importance: Importance = Importance.MEDIUM
    category: str = "general"  # meeting | homework | email | task | deadline
    action_hint: str = ""      # suggested follow-up
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def priority_score(self) -> float:
        """Combined priority: urgency × importance × deadline proximity."""
        base = self.urgency * self.importance

        # Deadline bonus
        if self.deadline:
            hours_left = (self.deadline - datetime.now()).total_seconds() / 3600
            if hours_left < 2:
                base *= 3.0
            elif hours_left < 6:
                base *= 2.0
            elif hours_left < 24:
                base *= 1.5

        # Time-of-day bonus: items happening within 2 hours get a bump
        if self.start_time:
            hours_until = (self.start_time - datetime.now()).total_seconds() / 3600
            if 0 <= hours_until < 2:
                base *= 1.8

        return float(base)


# ── Source collectors ────────────────────────────────────────────────

def _collect_calendar(target_date: datetime) -> List[DailyItem]:
    """Collect today's calendar events."""
    items: List[DailyItem] = []
    try:
        from bantz.google.calendar import calendar_list_events
        start = target_date.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)
        result = calendar_list_events(
            time_min=start.isoformat() + "Z",
            time_max=end.isoformat() + "Z",
            max_results=20,
        )
        if not result.get("ok"):
            return items

        for event in result.get("events", []):
            start_str = event.get("start", {}).get("dateTime", "")
            end_str = event.get("end", {}).get("dateTime", "")
            start_dt = _parse_dt(start_str)
            end_dt = _parse_dt(end_str)

            items.append(DailyItem(
                source="calendar",
                title=event.get("summary", "Etkinlik"),
                description=event.get("description", ""),
                start_time=start_dt,
                end_time=end_dt,
                category="meeting",
                urgency=Urgency.HIGH if _is_soon(start_dt) else Urgency.MEDIUM,
                importance=Importance.HIGH,
                action_hint="Katıl" if event.get("hangoutLink") else "",
                raw=event,
            ))
    except Exception as e:
        logger.warning(f"[DailyProgram] calendar collect failed: {e}")
    return items


def _collect_gmail(target_date: datetime) -> List[DailyItem]:
    """Collect important unread emails."""
    items: List[DailyItem] = []
    try:
        from bantz.google.gmail import gmail_list_messages
        result = gmail_list_messages(max_results=10, label="UNREAD")
        if not result.get("ok"):
            return items

        for msg in result.get("messages", []):
            sender = msg.get("from", "")
            subject = msg.get("subject", "Mail")
            urgency = _email_urgency(subject, sender)

            items.append(DailyItem(
                source="gmail",
                title=f"📧 {subject}",
                description=f"Kimden: {sender}",
                urgency=urgency,
                importance=Importance.MEDIUM,
                category="email",
                action_hint="Oku ve yanıtla",
                raw=msg,
            ))
    except Exception as e:
        logger.warning(f"[DailyProgram] gmail collect failed: {e}")
    return items


def _collect_reminders() -> List[DailyItem]:
    """Collect today's reminders."""
    items: List[DailyItem] = []
    try:
        from bantz.scheduler.reminder import get_reminder_manager
        mgr = get_reminder_manager()
        upcoming = mgr.get_upcoming(hours=24) if hasattr(mgr, "get_upcoming") else []
        for rem in upcoming:
            items.append(DailyItem(
                source="reminder",
                title=f"⏰ {rem.get('message', 'Hatırlatma')}",
                start_time=_parse_dt(rem.get("time", "")),
                urgency=Urgency.HIGH,
                importance=Importance.MEDIUM,
                category="task",
                action_hint="Tamamla",
                raw=rem,
            ))
    except Exception as e:
        logger.warning(f"[DailyProgram] reminder collect failed: {e}")
    return items


# ── Conflict detection ──────────────────────────────────────────────

@dataclass
class Conflict:
    """An overlapping pair of events."""
    item_a: str
    item_b: str
    overlap_minutes: int
    suggestion: str


def detect_conflicts(items: List[DailyItem]) -> List[Conflict]:
    """Find overlapping time slots."""
    timed = sorted(
        [i for i in items if i.start_time and i.end_time],
        key=lambda x: x.start_time,  # type: ignore[arg-type]
    )
    conflicts: List[Conflict] = []
    for i in range(len(timed) - 1):
        a, b = timed[i], timed[i + 1]
        if a.end_time and b.start_time and a.end_time > b.start_time:
            overlap = int((a.end_time - b.start_time).total_seconds() / 60)
            conflicts.append(Conflict(
                item_a=a.title,
                item_b=b.title,
                overlap_minutes=overlap,
                suggestion=f"'{a.title}' ile '{b.title}' arasında {overlap} dk çakışma var. Birini erteleyin.",
            ))
    return conflicts


# ── Day planner ──────────────────────────────────────────────────────

@dataclass
class TimeBlock:
    """A suggested time block in the day."""
    start: dtime
    end: dtime
    label: str
    items: List[str] = field(default_factory=list)


def suggest_day_plan(items: List[DailyItem]) -> List[TimeBlock]:
    """Suggest time-blocked day plan based on collected items."""
    blocks: List[TimeBlock] = []

    # Morning focus
    morning_items = [
        i.title for i in items
        if i.start_time and 6 <= i.start_time.hour < 12
    ]
    blocks.append(TimeBlock(
        start=dtime(8, 0), end=dtime(12, 0),
        label="Sabah — Odaklanma & Toplantılar",
        items=morning_items or ["Açık görevleri tamamla"],
    ))

    # Midday
    afternoon_items = [
        i.title for i in items
        if i.start_time and 12 <= i.start_time.hour < 17
    ]
    blocks.append(TimeBlock(
        start=dtime(13, 0), end=dtime(17, 0),
        label="Öğleden Sonra — Üretkenlik",
        items=afternoon_items or ["Mail'leri yanıtla", "Devam eden görevlere odaklan"],
    ))

    # Evening
    evening_items = [
        i.title for i in items
        if i.start_time and i.start_time.hour >= 17
    ]
    blocks.append(TimeBlock(
        start=dtime(17, 0), end=dtime(21, 0),
        label="Akşam — İnceleme & Planlama",
        items=evening_items or ["Yarını planla"],
    ))

    return blocks


# ── Main entry point ─────────────────────────────────────────────────

def get_daily_program(target_date: Optional[datetime] = None) -> Dict[str, Any]:
    """Compile the full daily program from all sources.

    Returns a structured dict suitable for LLM summarization or
    direct UI rendering.
    """
    if target_date is None:
        target_date = datetime.now()

    # Collect from all sources
    all_items: List[DailyItem] = []
    all_items.extend(_collect_calendar(target_date))
    all_items.extend(_collect_gmail(target_date))
    all_items.extend(_collect_reminders())

    # Sort by priority
    all_items.sort(key=lambda x: x.priority_score, reverse=True)

    # Detect conflicts
    conflicts = detect_conflicts(all_items)

    # Suggest plan
    plan = suggest_day_plan(all_items)

    # Categorize
    by_source: Dict[str, int] = {}
    for item in all_items:
        by_source[item.source] = by_source.get(item.source, 0) + 1

    # Top priorities
    top_priorities = [
        {
            "title": item.title,
            "source": item.source,
            "urgency": item.urgency.name,
            "importance": item.importance.name,
            "score": round(item.priority_score, 1),
            "action": item.action_hint,
            "time": item.start_time.strftime("%H:%M") if item.start_time else None,
        }
        for item in all_items[:10]
    ]

    return {
        "ok": True,
        "date": target_date.strftime("%Y-%m-%d"),
        "total_items": len(all_items),
        "by_source": by_source,
        "priorities": top_priorities,
        "conflicts": [
            {
                "a": c.item_a, "b": c.item_b,
                "overlap_min": c.overlap_minutes,
                "suggestion": c.suggestion,
            }
            for c in conflicts
        ],
        "plan": [
            {
                "start": b.start.strftime("%H:%M"),
                "end": b.end.strftime("%H:%M"),
                "label": b.label,
                "items": b.items,
            }
            for b in plan
        ],
    }


# ── Tool registration ────────────────────────────────────────────────

def register_daily_program_tools(registry: Any) -> None:
    """Register daily program tool with ToolRegistry."""
    from bantz.agent.tools import Tool

    registry.register(Tool(
        name="daily.program",
        description="Get today's full program from all sources (calendar, email, reminders).",
        parameters={
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Target date (ISO format, default: today)",
                },
            },
        },
        function=lambda **kw: get_daily_program(
            _parse_dt(kw["date"]) if kw.get("date") else None
        ),
    ))
    logger.info("[DailyProgram] Tool registered: daily.program")


# ── Helpers ──────────────────────────────────────────────────────────

def _parse_dt(s: str) -> Optional[datetime]:
    """Best-effort ISO datetime parse."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.rstrip("Z"), fmt.rstrip("%z"))
        except ValueError:
            continue
    return None


def _is_soon(dt: Optional[datetime], minutes: int = 120) -> bool:
    """Return True if *dt* is within *minutes* from now."""
    if dt is None:
        return False
    return 0 <= (dt - datetime.now()).total_seconds() <= minutes * 60


def _email_urgency(subject: str, sender: str) -> Urgency:
    """Heuristic urgency for an email."""
    text = (subject + " " + sender).lower()
    if any(w in text for w in ["acil", "urgent", "asap", "critical", "önemli"]):
        return Urgency.CRITICAL
    if any(w in text for w in ["deadline", "son tarih", "bugün", "today"]):
        return Urgency.HIGH
    return Urgency.MEDIUM
