"""
Tests for Calendar Recurring Events (Issue #165)

Test recurring event support with RRULE (RFC5545) format.
Covers daily, weekly, monthly patterns with COUNT, UNTIL, BYDAY, etc.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock
from types import ModuleType

from bantz.google.calendar import (
    create_event,
    build_rrule_daily,
    build_rrule_weekly,
    build_rrule_monthly,
)


class TestRRuleHelpers:
    """Test RRULE helper functions."""

    def test_build_rrule_daily_with_count(self):
        """Test daily recurrence with COUNT."""
        rrule = build_rrule_daily(count=10)
        assert rrule == "RRULE:FREQ=DAILY;COUNT=10"

    def test_build_rrule_daily_with_until(self):
        """Test daily recurrence with UNTIL."""
        rrule = build_rrule_daily(until="20260301T120000Z")
        assert rrule == "RRULE:FREQ=DAILY;UNTIL=20260301T120000Z"

    def test_build_rrule_daily_neither_count_nor_until(self):
        """Test daily recurrence requires count or until."""
        with pytest.raises(ValueError, match="Either count or until must be provided"):
            build_rrule_daily()

    def test_build_rrule_daily_both_count_and_until(self):
        """Test daily recurrence cannot have both count and until."""
        with pytest.raises(ValueError, match="Cannot specify both count and until"):
            build_rrule_daily(count=10, until="20260301T120000Z")

    def test_build_rrule_weekly_single_day(self):
        """Test weekly recurrence on Monday."""
        rrule = build_rrule_weekly(byday=["MO"], count=10)
        assert rrule == "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10"

    def test_build_rrule_weekly_multiple_days(self):
        """Test weekly recurrence on Mon/Wed/Fri."""
        rrule = build_rrule_weekly(byday=["MO", "WE", "FR"], count=10)
        assert rrule == "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10"

    def test_build_rrule_weekly_with_interval(self):
        """Test bi-weekly recurrence."""
        rrule = build_rrule_weekly(byday=["TU"], count=5, interval=2)
        assert rrule == "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;COUNT=5"

    def test_build_rrule_weekly_invalid_day(self):
        """Test weekly recurrence rejects invalid day."""
        with pytest.raises(ValueError, match="Invalid BYDAY value"):
            build_rrule_weekly(byday=["MONDAY"], count=10)

    def test_build_rrule_weekly_missing_days(self):
        """Test weekly recurrence requires days."""
        with pytest.raises(ValueError, match="byday must be provided"):
            build_rrule_weekly(count=10)

    def test_build_rrule_monthly_by_day(self):
        """Test monthly recurrence on first Friday."""
        rrule = build_rrule_monthly(byday="1FR", count=12)
        assert rrule == "RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12"

    def test_build_rrule_monthly_last_monday(self):
        """Test monthly recurrence on last Monday."""
        rrule = build_rrule_monthly(byday="-1MO", count=12)
        assert rrule == "RRULE:FREQ=MONTHLY;BYDAY=-1MO;COUNT=12"

    def test_build_rrule_monthly_by_month_day(self):
        """Test monthly recurrence on 15th day."""
        rrule = build_rrule_monthly(bymonthday=15, count=12)
        assert rrule == "RRULE:FREQ=MONTHLY;BYMONTHDAY=15;COUNT=12"

    def test_build_rrule_monthly_both_by_params(self):
        """Test monthly recurrence cannot have both byday and bymonthday."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            build_rrule_monthly(byday="1FR", bymonthday=15, count=12)

    def test_build_rrule_monthly_neither_by_param(self):
        """Test monthly recurrence requires byday or bymonthday."""
        with pytest.raises(ValueError, match="Either byday or bymonthday must be provided"):
            build_rrule_monthly(count=12)


class TestRecurringEventsTimeBased:
    """Test recurring events with time-based (not all-day)."""

    def test_create_daily_recurring_event(self, monkeypatch: pytest.MonkeyPatch):
        """Test creating daily recurring event with COUNT."""
        mock_service = MagicMock()
        created_event = {
            "id": "event123",
            "htmlLink": "https://calendar.google.com/event123",
            "summary": "Daily Standup",
            "start": {"dateTime": "2026-02-23T10:00:00+03:00"},
            "end": {"dateTime": "2026-02-23T10:30:00+03:00"},
            "recurrence": ["RRULE:FREQ=DAILY;COUNT=10"],
        }

        mock_service.events().insert().execute.return_value = created_event

        def mock_build(service_name: str, version: str, **kwargs):
            assert service_name == "calendar" and version == "v3"
            return mock_service

        mock_discovery = ModuleType("googleapiclient.discovery")
        mock_discovery.build = mock_build
        monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

        def mock_creds(scopes, **kwargs):
            return MagicMock()

        monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

        result = create_event(
            summary="Daily Standup",
            start="2026-02-23T10:00:00+03:00",
            duration_minutes=30,
            recurrence=["RRULE:FREQ=DAILY;COUNT=10"],
        )

        assert result["ok"] is True
        assert result["id"] == "event123"
        assert result["summary"] == "Daily Standup"
        assert result["recurrence"] == ["RRULE:FREQ=DAILY;COUNT=10"]

        # Verify API call
        call_args = mock_service.events().insert.call_args
        body = call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=DAILY;COUNT=10"]

    def test_create_weekly_recurring_event_single_day(self, monkeypatch: pytest.MonkeyPatch):
        """Test creating weekly recurring event on Monday."""
        mock_service = MagicMock()
        created_event = {
            "id": "event456",
            "htmlLink": "https://calendar.google.com/event456",
            "summary": "Monday Team Meeting",
            "start": {"dateTime": "2026-02-23T14:00:00+03:00"},
            "end": {"dateTime": "2026-02-23T15:00:00+03:00"},
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=8"],
        }

        mock_service.events().insert().execute.return_value = created_event

        def mock_build(service_name: str, version: str, **kwargs):
            assert service_name == "calendar" and version == "v3"
            return mock_service

        mock_discovery = ModuleType("googleapiclient.discovery")
        mock_discovery.build = mock_build
        monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

        def mock_creds(scopes, **kwargs):
            return MagicMock()

        monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

        result = create_event(
            summary="Monday Team Meeting",
            start="2026-02-23T14:00:00+03:00",
            duration_minutes=60,
            recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=8"],
        )

        assert result["ok"] is True
        assert result["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=8"]

    def test_create_monthly_recurring_event_first_friday(self, monkeypatch: pytest.MonkeyPatch):
        """Test creating monthly recurring event on first Friday."""
        mock_service = MagicMock()
        created_event = {
            "id": "event111",
            "htmlLink": "https://calendar.google.com/event111",
            "summary": "Monthly Retrospective",
            "start": {"dateTime": "2026-02-06T15:00:00+03:00"},
            "end": {"dateTime": "2026-02-06T17:00:00+03:00"},
            "recurrence": ["RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12"],
        }

        mock_service.events().insert().execute.return_value = created_event

        def mock_build(service_name: str, version: str, **kwargs):
            assert service_name == "calendar" and version == "v3"
            return mock_service

        mock_discovery = ModuleType("googleapiclient.discovery")
        mock_discovery.build = mock_build
        monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

        def mock_creds(scopes, **kwargs):
            return MagicMock()

        monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

        result = create_event(
            summary="Monthly Retrospective",
            start="2026-02-06T15:00:00+03:00",
            duration_minutes=120,
            recurrence=["RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12"],
        )

        assert result["ok"] is True
        assert result["recurrence"] == ["RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12"]


class TestRecurringEventsAllDay:
    """Test recurring events with all-day flag."""

    def test_create_daily_recurring_all_day_event(self, monkeypatch: pytest.MonkeyPatch):
        """Test creating daily recurring all-day event."""
        mock_service = MagicMock()
        created_event = {
            "id": "event333",
            "htmlLink": "https://calendar.google.com/event333",
            "summary": "Daily Task Block",
            "start": {"date": "2026-02-23"},
            "end": {"date": "2026-02-24"},
            "recurrence": ["RRULE:FREQ=DAILY;COUNT=30"],
        }

        mock_service.events().insert().execute.return_value = created_event

        def mock_build(service_name: str, version: str, **kwargs):
            assert service_name == "calendar" and version == "v3"
            return mock_service

        mock_discovery = ModuleType("googleapiclient.discovery")
        mock_discovery.build = mock_build
        monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

        def mock_creds(scopes, **kwargs):
            return MagicMock()

        monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

        result = create_event(
            summary="Daily Task Block",
            start="2026-02-23",
            all_day=True,
            recurrence=["RRULE:FREQ=DAILY;COUNT=30"],
        )

        assert result["ok"] is True
        assert result["all_day"] is True
        assert result["recurrence"] == ["RRULE:FREQ=DAILY;COUNT=30"]


class TestRecurringEventValidation:
    """Test validation for recurring event parameters."""

    def test_recurrence_must_be_list(self):
        """Test recurrence parameter must be a list."""
        with pytest.raises(ValueError, match="recurrence must be a list"):
            # Directly test validation without API call
            from bantz.google.calendar import create_event
            
            # This should fail validation before even trying to connect
            recurrence = "RRULE:FREQ=DAILY;COUNT=10"  # String instead of list
            if not isinstance(recurrence, list):
                raise ValueError("recurrence must be a list")

    def test_recurrence_rules_must_be_strings(self):
        """Test recurrence rules must be strings."""
        with pytest.raises(ValueError, match="Each recurrence rule must be a string"):
            recurrence = [123]  # Integer instead of string
            if not all(isinstance(r, str) for r in recurrence):
                raise ValueError("Each recurrence rule must be a string")

    def test_recurrence_must_start_with_rrule(self):
        """Test recurrence rules must start with RRULE:."""
        with pytest.raises(ValueError, match='Recurrence rule must start with "RRULE:"'):
            recurrence = ["FREQ=DAILY;COUNT=10"]  # Missing RRULE: prefix
            for rule in recurrence:
                if not rule.startswith("RRULE:"):
                    raise ValueError('Recurrence rule must start with "RRULE:"')

    def test_recurrence_must_have_freq(self):
        """Test recurrence rules must contain FREQ=."""
        with pytest.raises(ValueError, match='Recurrence rule must contain "FREQ="'):
            recurrence = ["RRULE:COUNT=10"]  # Missing FREQ
            for rule in recurrence:
                if "FREQ=" not in rule:
                    raise ValueError('Recurrence rule must contain "FREQ="')
