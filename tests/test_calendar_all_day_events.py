"""
Test all-day event support for Google Calendar (Issue #164).

Tests cover:
- Single-day all-day events
- Multi-day all-day events
- Date boundary validations
- All-day event parsing in list_events
- Busy interval calculation for all-day events
"""

from datetime import date, datetime, timedelta, timezone
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

from bantz.google.calendar import create_event, list_events


def test_create_all_day_event_single_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test creating a single-day all-day event."""
    mock_service = MagicMock()
    mock_created = {
        "id": "evt_all_day_123",
        "summary": "Conference",
        "htmlLink": "https://calendar.google.com/event?eid=evt_all_day_123",
        "start": {"date": "2026-02-03"},
        "end": {"date": "2026-02-04"},  # Next day (exclusive)
    }

    mock_service.events().insert().execute.return_value = mock_created

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
        summary="Conference",
        start="2026-02-03",
        all_day=True,
    )

    # Verify API call
    call_args = mock_service.events().insert.call_args
    assert call_args.kwargs["body"]["summary"] == "Conference"
    assert call_args.kwargs["body"]["start"] == {"date": "2026-02-03"}
    assert call_args.kwargs["body"]["end"] == {"date": "2026-02-04"}  # Auto +1 day

    # Verify response
    assert result["ok"] is True
    assert result["id"] == "evt_all_day_123"
    assert result["summary"] == "Conference"
    assert result["start"] == "2026-02-03"
    assert result["end"] == "2026-02-04"
    assert result["all_day"] is True


def test_create_all_day_event_multi_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test creating a multi-day all-day event."""
    mock_service = MagicMock()
    mock_created = {
        "id": "evt_vacation",
        "summary": "Vacation",
        "htmlLink": "https://calendar.google.com/event?eid=evt_vacation",
        "start": {"date": "2026-02-23"},
        "end": {"date": "2026-02-26"},  # Exclusive: Feb 23-25 (3 days)
    }

    mock_service.events().insert().execute.return_value = mock_created

    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service

    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    result = create_event(
        summary="Vacation",
        start="2026-02-23",
        end="2026-02-26",
        all_day=True,
    )

    # Verify API call
    call_args = mock_service.events().insert.call_args
    assert call_args.kwargs["body"]["start"] == {"date": "2026-02-23"}
    assert call_args.kwargs["body"]["end"] == {"date": "2026-02-26"}

    # Verify response
    assert result["ok"] is True
    assert result["start"] == "2026-02-23"
    assert result["end"] == "2026-02-26"
    assert result["all_day"] is True


def test_create_all_day_event_with_location_description(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test all-day event with location and description."""
    mock_service = MagicMock()
    mock_created = {
        "id": "evt_home_office",
        "summary": "Home Office",
        "htmlLink": "https://calendar.google.com/event?eid=evt_home_office",
        "start": {"date": "2026-02-05"},
        "end": {"date": "2026-02-06"},
        "location": "Home",
        "description": "Working from home today",
    }

    mock_service.events().insert().execute.return_value = mock_created

    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service

    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    result = create_event(
        summary="Home Office",
        start="2026-02-05",
        all_day=True,
        location="Home",
        description="Working from home today",
    )

    # Verify body includes location and description
    call_args = mock_service.events().insert.call_args
    assert call_args.kwargs["body"]["location"] == "Home"
    assert call_args.kwargs["body"]["description"] == "Working from home today"

    assert result["ok"] is True
    assert result["all_day"] is True


def test_create_all_day_event_error_invalid_start_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error when all_day=True but start is not a date format."""
    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    with pytest.raises(ValueError, match="all_day_start_must_be_date_format"):
        create_event(
            summary="Conference",
            start="2026-02-03T14:00:00+03:00",  # RFC3339, not date
            all_day=True,
        )


def test_create_all_day_event_error_invalid_end_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error when all_day=True but end is not a date format."""
    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    with pytest.raises(ValueError, match="all_day_end_must_be_date_format"):
        create_event(
            summary="Conference",
            start="2026-02-03",
            end="2026-02-05T18:00:00+03:00",  # RFC3339, not date
            all_day=True,
        )


def test_create_all_day_event_error_end_before_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error when end date is before or equal to start date."""
    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    with pytest.raises(ValueError, match="end_date_must_be_after_start_date"):
        create_event(
            summary="Invalid Event",
            start="2026-02-05",
            end="2026-02-03",  # Before start
            all_day=True,
        )


def test_create_all_day_event_error_end_equal_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error when end date equals start date."""
    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    with pytest.raises(ValueError, match="end_date_must_be_after_start_date"):
        create_event(
            summary="Invalid Event",
            start="2026-02-05",
            end="2026-02-05",  # Same as start
            all_day=True,
        )


def test_create_time_based_event_not_affected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that time-based events still work (all_day=False)."""
    mock_service = MagicMock()
    mock_created = {
        "id": "evt_meeting",
        "summary": "Meeting",
        "htmlLink": "https://calendar.google.com/event?eid=evt_meeting",
        "start": {"dateTime": "2026-02-03T14:00:00+03:00"},
        "end": {"dateTime": "2026-02-03T15:00:00+03:00"},
    }

    mock_service.events().insert().execute.return_value = mock_created

    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service

    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    result = create_event(
        summary="Meeting",
        start="2026-02-03T14:00:00+03:00",
        duration_minutes=60,
    )

    # Verify time-based event uses dateTime
    call_args = mock_service.events().insert.call_args
    assert "dateTime" in call_args.kwargs["body"]["start"]
    assert "date" not in call_args.kwargs["body"]["start"]

    assert result["ok"] is True
    assert result["all_day"] is False


def test_list_events_parses_all_day_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that list_events correctly parses all-day events."""
    from bantz.google.calendar_cache import reset_calendar_cache
    reset_calendar_cache()

    mock_service = MagicMock()
    mock_resp = {
        "items": [
            {
                "id": "evt_1",
                "summary": "Conference",
                "start": {"date": "2026-02-03"},
                "end": {"date": "2026-02-04"},
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/event?eid=evt_1",
            },
            {
                "id": "evt_2",
                "summary": "Meeting",
                "start": {"dateTime": "2026-02-03T14:00:00+03:00"},
                "end": {"dateTime": "2026-02-03T15:00:00+03:00"},
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/event?eid=evt_2",
            },
        ]
    }

    mock_service.events().list().execute.return_value = mock_resp

    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service

    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)

    def mock_creds(scopes, **kwargs):
        return MagicMock()

    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)

    result = list_events(
        time_min="2026-02-03T00:00:00+03:00",
        max_results=10,
    )

    assert result["ok"] is True
    assert result["count"] == 2

    # Check all-day event
    all_day_event = result["events"][0]
    assert all_day_event["id"] == "evt_1"
    assert all_day_event["summary"] == "Conference"
    assert all_day_event["start"] == "2026-02-03"  # Date format
    assert all_day_event["end"] == "2026-02-04"

    # Check time-based event
    time_event = result["events"][1]
    assert time_event["id"] == "evt_2"
    assert time_event["summary"] == "Meeting"
    assert "T" in time_event["start"]  # RFC3339 format


def test_all_day_event_in_busy_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that all-day events are included in busy interval calculation."""
    from bantz.google.calendar import _extract_busy_intervals

    events = [
        {
            "start": "2026-02-03",  # All-day event (date format)
            "end": "2026-02-04",
        },
        {
            "start": "2026-02-04T10:00:00+03:00",  # Time-based event
            "end": "2026-02-04T11:00:00+03:00",
        },
    ]

    tz = timezone(timedelta(hours=3))
    intervals = _extract_busy_intervals(events, tz=tz)

    assert len(intervals) == 2

    # All-day event should span 00:00 to 00:00 next day
    all_day_start, all_day_end = intervals[0]
    assert all_day_start.date() == date(2026, 2, 3)
    assert all_day_start.hour == 0
    assert all_day_start.minute == 0
    assert all_day_end.date() == date(2026, 2, 4)
    assert all_day_end.hour == 0
    assert all_day_end.minute == 0

    # Time-based event
    time_start, time_end = intervals[1]
    assert time_start.hour == 10
    assert time_end.hour == 11


def test_tool_registration_includes_all_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that calendar.create_event tool is registered with all_day parameter."""
    from bantz.agent.builtin_tools import build_default_registry

    # Mock google calendar import
    def mock_import_error(*args, **kwargs):
        raise ImportError("test")

    # Allow the tool registration to work with mock
    import bantz.google.calendar
    monkeypatch.setattr(bantz.google.calendar, "create_event", lambda **kwargs: {})

    registry = build_default_registry()
    tool = registry.get("calendar.create_event")

    assert tool is not None
    assert "all_day" in tool.parameters["properties"]
    assert tool.parameters["properties"]["all_day"]["type"] == "boolean"
    assert "all_day" in tool.returns_schema["properties"]
