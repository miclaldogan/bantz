"""Time-of-day context awareness for Bantz.

Provides the assistant with awareness of what part of the day it is,
enabling natural time-appropriate greetings and behavior adjustments.

Time periods::

    dawn       — 05:00–06:59  (early morning)
    morning    — 07:00–11:59
    noon       — 12:00–12:59
    afternoon  — 13:00–16:59
    evening    — 17:00–20:59
    night      — 21:00–23:59
    late_night — 00:00–04:59

Usage::

    from bantz.services.time_context import TimeContext
    ctx = TimeContext()
    ctx.period          # "morning"
    ctx.greeting        # "Good morning, sir."
    ctx.is_work_hours   # True
    ctx.briefing_style  # "full"
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "DayPeriod",
    "TimeContext",
]


class DayPeriod(str, Enum):
    """Named periods of the day."""
    DAWN = "dawn"
    MORNING = "morning"
    NOON = "noon"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"
    LATE_NIGHT = "late_night"


# Period boundaries: (start_hour, end_hour_exclusive)
_PERIOD_RANGES: list[tuple[int, int, DayPeriod]] = [
    (5, 7, DayPeriod.DAWN),
    (7, 12, DayPeriod.MORNING),
    (12, 13, DayPeriod.NOON),
    (13, 17, DayPeriod.AFTERNOON),
    (17, 21, DayPeriod.EVENING),
    (21, 24, DayPeriod.NIGHT),
    (0, 5, DayPeriod.LATE_NIGHT),
]


# Greetings per period (Turkish, for Bantz's personality)
_GREETINGS: dict[DayPeriod, str] = {
    DayPeriod.DAWN: "Günaydın efendim, erken kalkmışsınız.",
    DayPeriod.MORNING: "Günaydın efendim.",
    DayPeriod.NOON: "Afiyet olsun efendim.",
    DayPeriod.AFTERNOON: "İyi günler efendim.",
    DayPeriod.EVENING: "İyi akşamlar efendim.",
    DayPeriod.NIGHT: "İyi geceler efendim.",
    DayPeriod.LATE_NIGHT: "Efendim, bu saatte mi? Sizin için buradayım.",
}


# Briefing styles per period
_BRIEFING_STYLES: dict[DayPeriod, str] = {
    DayPeriod.DAWN: "concise",
    DayPeriod.MORNING: "full",
    DayPeriod.NOON: "concise",
    DayPeriod.AFTERNOON: "concise",
    DayPeriod.EVENING: "summary",
    DayPeriod.NIGHT: "minimal",
    DayPeriod.LATE_NIGHT: "minimal",
}


@dataclass
class TimeContext:
    """Time-of-day context that adapts assistant behavior.

    Parameters
    ----------
    now:
        Override current time (for testing).
    work_start:
        Work hours start (default: 9).
    work_end:
        Work hours end (default: 18).

    Attributes
    ----------
    period:
        Current DayPeriod enum.
    greeting:
        Time-appropriate greeting string.
    is_work_hours:
        Whether current time is within work hours.
    briefing_style:
        Appropriate briefing verbosity level.
    """

    now: Optional[datetime.datetime] = None
    work_start: int = 9
    work_end: int = 18

    @property
    def _dt(self) -> datetime.datetime:
        return self.now or datetime.datetime.now()

    @property
    def hour(self) -> int:
        return self._dt.hour

    @property
    def minute(self) -> int:
        return self._dt.minute

    @property
    def period(self) -> DayPeriod:
        """Current day period."""
        h = self.hour
        for start, end, period in _PERIOD_RANGES:
            if start <= h < end:
                return period
        return DayPeriod.NIGHT  # fallback

    @property
    def greeting(self) -> str:
        """Time-appropriate greeting."""
        return _GREETINGS.get(self.period, "Merhaba efendim.")

    @property
    def is_work_hours(self) -> bool:
        """Whether current time is within configured work hours."""
        return self.work_start <= self.hour < self.work_end

    @property
    def is_quiet_hours(self) -> bool:
        """Whether it's quiet hours (late night / dawn)."""
        return self.period in (DayPeriod.LATE_NIGHT, DayPeriod.DAWN)

    @property
    def briefing_style(self) -> str:
        """Appropriate briefing verbosity: full, concise, summary, minimal."""
        return _BRIEFING_STYLES.get(self.period, "concise")

    @property
    def day_of_week(self) -> str:
        """Current day name (e.g. 'Monday')."""
        return self._dt.strftime("%A")

    @property
    def date_str(self) -> str:
        """Current date as YYYY-MM-DD."""
        return self._dt.strftime("%Y-%m-%d")

    @property
    def time_str(self) -> str:
        """Current time as HH:MM."""
        return self._dt.strftime("%H:%M")

    @property
    def human_time_description(self) -> str:
        """Human-readable time description for the assistant.

        Example: "It's Tuesday morning, 09:45."
        """
        period_name = self.period.value.replace("_", " ")
        return f"It's {self.day_of_week} {period_name}, {self.time_str}."

    def to_dict(self) -> dict:
        """JSON-serializable state for LLM context injection."""
        return {
            "period": self.period.value,
            "hour": self.hour,
            "minute": self.minute,
            "day_of_week": self.day_of_week,
            "date": self.date_str,
            "time": self.time_str,
            "is_work_hours": self.is_work_hours,
            "is_quiet_hours": self.is_quiet_hours,
            "briefing_style": self.briefing_style,
        }

    def elapsed_days_since(self, last_seen: Optional[datetime.datetime]) -> int:
        """Days elapsed since last interaction.

        Returns 0 if last_seen is today, 1 if yesterday, etc.
        Returns -1 if last_seen is None.
        """
        if last_seen is None:
            return -1
        delta = self._dt.date() - last_seen.date()
        return delta.days

    def absence_greeting(self, days_away: int) -> str:
        """Generate an appropriate greeting based on how long the user's been away.

        Parameters
        ----------
        days_away:
            Number of days since last interaction.

        Returns
        -------
        Contextual greeting string.
        """
        base = self.greeting

        if days_away < 0:
            # First time ever
            return f"{base} Tanıştığımıza memnun oldum."
        elif days_away == 0:
            # Same day
            return base
        elif days_away == 1:
            return f"{base} Dün de güzel bir gün geçirdik."
        elif days_away <= 3:
            return f"{base} Sizi tekrardan görmek güzel."
        elif days_away <= 7:
            return f"{base} Sizi tekrardan görmek güzel efendim, {days_away} gündür görüşememiştik."
        elif days_away <= 30:
            weeks = days_away // 7
            return f"{base} Sizi tekrardan görmek güzel efendim, yaklaşık {weeks} haftadır görüşememiştik."
        else:
            return f"{base} Sizi tekrardan görmek güzel efendim, uzun süredir görüşememiştik."
