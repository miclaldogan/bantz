"""Tests for TimeContext — day-period awareness and absence greetings.

Covers:
- All 7 day periods (dawn, morning, noon, afternoon, evening, night, late_night)
- Greetings per period
- Work hours detection
- Quiet hours detection
- Briefing style per period
- Human time description
- Days elapsed since last interaction
- Absence greetings (same day, yesterday, 3+ days, weeks, months)
- to_dict serialization
"""

from __future__ import annotations

import datetime

import pytest

from bantz.services.time_context import DayPeriod, TimeContext


# ─────────────────────────────────────────────────────────────────
# Day Period Detection
# ─────────────────────────────────────────────────────────────────


class TestDayPeriod:
    @pytest.mark.parametrize("hour,expected", [
        (0, DayPeriod.LATE_NIGHT),
        (3, DayPeriod.LATE_NIGHT),
        (4, DayPeriod.LATE_NIGHT),
        (5, DayPeriod.DAWN),
        (6, DayPeriod.DAWN),
        (7, DayPeriod.MORNING),
        (10, DayPeriod.MORNING),
        (11, DayPeriod.MORNING),
        (12, DayPeriod.NOON),
        (13, DayPeriod.AFTERNOON),
        (15, DayPeriod.AFTERNOON),
        (16, DayPeriod.AFTERNOON),
        (17, DayPeriod.EVENING),
        (19, DayPeriod.EVENING),
        (20, DayPeriod.EVENING),
        (21, DayPeriod.NIGHT),
        (23, DayPeriod.NIGHT),
    ])
    def test_period_at_hour(self, hour, expected):
        dt = datetime.datetime(2026, 2, 17, hour, 30)
        ctx = TimeContext(now=dt)
        assert ctx.period == expected, f"hour={hour}: got {ctx.period}, expected {expected}"


# ─────────────────────────────────────────────────────────────────
# Greetings
# ─────────────────────────────────────────────────────────────────


class TestGreetings:
    def test_morning_greeting(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert "Günaydın" in ctx.greeting

    def test_evening_greeting(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 19, 0))
        assert "akşam" in ctx.greeting

    def test_night_greeting(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 22, 0))
        assert "gece" in ctx.greeting

    def test_dawn_greeting(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 5, 30))
        assert "erken" in ctx.greeting

    def test_noon_greeting(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 12, 15))
        assert "Afiyet" in ctx.greeting

    def test_late_night_greeting(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 2, 0))
        assert "saatte" in ctx.greeting

    def test_all_greetings_contain_efendim(self):
        for hour in [2, 5, 9, 12, 14, 19, 22]:
            ctx = TimeContext(now=datetime.datetime(2026, 2, 17, hour, 0))
            assert "efendim" in ctx.greeting.lower(), f"hour={hour} missing efendim"


# ─────────────────────────────────────────────────────────────────
# Work Hours
# ─────────────────────────────────────────────────────────────────


class TestWorkHours:
    def test_within_work_hours(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 10, 0))
        assert ctx.is_work_hours is True

    def test_outside_work_hours_early(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 7, 0))
        assert ctx.is_work_hours is False

    def test_outside_work_hours_late(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 20, 0))
        assert ctx.is_work_hours is False

    def test_boundary_start(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert ctx.is_work_hours is True

    def test_boundary_end(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 18, 0))
        assert ctx.is_work_hours is False

    def test_custom_work_hours(self):
        ctx = TimeContext(
            now=datetime.datetime(2026, 2, 17, 7, 0),
            work_start=7,
            work_end=15,
        )
        assert ctx.is_work_hours is True


# ─────────────────────────────────────────────────────────────────
# Quiet Hours
# ─────────────────────────────────────────────────────────────────


class TestQuietHours:
    def test_quiet_at_dawn(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 5, 30))
        assert ctx.is_quiet_hours is True

    def test_quiet_at_late_night(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 2, 0))
        assert ctx.is_quiet_hours is True

    def test_not_quiet_at_morning(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert ctx.is_quiet_hours is False


# ─────────────────────────────────────────────────────────────────
# Briefing Style
# ─────────────────────────────────────────────────────────────────


class TestBriefingStyle:
    def test_morning_full(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert ctx.briefing_style == "full"

    def test_afternoon_concise(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 14, 0))
        assert ctx.briefing_style == "concise"

    def test_evening_summary(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 19, 0))
        assert ctx.briefing_style == "summary"

    def test_night_minimal(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 23, 0))
        assert ctx.briefing_style == "minimal"


# ─────────────────────────────────────────────────────────────────
# Date/Time Properties
# ─────────────────────────────────────────────────────────────────


class TestDateTimeProperties:
    def test_day_of_week(self):
        # 2026-02-17 is a Tuesday
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert ctx.day_of_week == "Tuesday"

    def test_date_str(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert ctx.date_str == "2026-02-17"

    def test_time_str(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 45))
        assert ctx.time_str == "09:45"

    def test_human_time_description(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 45))
        desc = ctx.human_time_description
        assert "Tuesday" in desc
        assert "morning" in desc
        assert "09:45" in desc


# ─────────────────────────────────────────────────────────────────
# Absence Detection
# ─────────────────────────────────────────────────────────────────


class TestAbsence:
    def test_elapsed_same_day(self):
        now = datetime.datetime(2026, 2, 17, 15, 0)
        last = datetime.datetime(2026, 2, 17, 9, 0)
        ctx = TimeContext(now=now)
        assert ctx.elapsed_days_since(last) == 0

    def test_elapsed_yesterday(self):
        now = datetime.datetime(2026, 2, 17, 9, 0)
        last = datetime.datetime(2026, 2, 16, 22, 0)
        ctx = TimeContext(now=now)
        assert ctx.elapsed_days_since(last) == 1

    def test_elapsed_3_days(self):
        now = datetime.datetime(2026, 2, 17, 9, 0)
        last = datetime.datetime(2026, 2, 14, 9, 0)
        ctx = TimeContext(now=now)
        assert ctx.elapsed_days_since(last) == 3

    def test_elapsed_none(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        assert ctx.elapsed_days_since(None) == -1


# ─────────────────────────────────────────────────────────────────
# Absence Greeting
# ─────────────────────────────────────────────────────────────────


class TestAbsenceGreeting:
    def test_first_time(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        greeting = ctx.absence_greeting(-1)
        assert "memnun" in greeting.lower()

    def test_same_day(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        greeting = ctx.absence_greeting(0)
        assert "Günaydın" in greeting

    def test_yesterday(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        greeting = ctx.absence_greeting(1)
        assert "Dün" in greeting

    def test_3_days(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        greeting = ctx.absence_greeting(3)
        assert "tekrardan" in greeting.lower()

    def test_week(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        greeting = ctx.absence_greeting(7)
        assert "7 gündür" in greeting

    def test_month_plus(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 0))
        greeting = ctx.absence_greeting(40)
        assert "uzun süredir" in greeting


# ─────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────


class TestSerialization:
    def test_to_dict(self):
        ctx = TimeContext(now=datetime.datetime(2026, 2, 17, 9, 45))
        d = ctx.to_dict()
        assert d["period"] == "morning"
        assert d["hour"] == 9
        assert d["minute"] == 45
        assert d["day_of_week"] == "Tuesday"
        assert d["date"] == "2026-02-17"
        assert d["time"] == "09:45"
        assert d["is_work_hours"] is True
        assert d["is_quiet_hours"] is False
        assert d["briefing_style"] == "full"
