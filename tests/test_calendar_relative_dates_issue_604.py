from __future__ import annotations

from datetime import timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

import bantz.tools.calendar_tools as calendar_tools


@pytest.fixture(autouse=True)
def _freeze_calendar_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make tests deterministic.
    monkeypatch.setattr(calendar_tools, "_local_tz", lambda: timezone.utc)
    monkeypatch.setattr(calendar_tools, "_date_today", lambda: "2026-02-09")
    monkeypatch.setattr(calendar_tools, "_date_tomorrow", lambda: "2026-02-10")
    monkeypatch.setattr(calendar_tools, "_date_yesterday", lambda: "2026-02-08")
    # Prevent past-time guard from shifting dates (Issue #1212)
    monkeypatch.setattr(calendar_tools, "_is_past", lambda d, t: False)


def _mock_list_events(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value={"ok": True, "events": []})
    monkeypatch.setattr(calendar_tools, "list_events", mock)
    return mock


@pytest.mark.parametrize(
    "date,window_hint,expected_date",
    [
        ("today", "today", "2026-02-09"),
        (None, "today", "2026-02-09"),
        ("2026-02-09", "today", "2026-02-09"),  # explicit date wins
    ],
)
def test_calendar_list_events_resolves_relative_dates(
    monkeypatch: pytest.MonkeyPatch,
    date: str | None,
    window_hint: str | None,
    expected_date: str,
) -> None:
    mock_list = _mock_list_events(monkeypatch)

    resp = calendar_tools.calendar_list_events_tool(
        date=date,
        window_hint=window_hint,
        max_results=3,
    )

    assert resp["ok"] is True
    assert mock_list.call_count == 1

    kwargs: dict[str, Any] = mock_list.call_args.kwargs
    assert kwargs["time_min"].startswith(f"{expected_date}T00:00")
    assert kwargs["time_max"].startswith(f"{expected_date}T23:59")


@pytest.mark.parametrize(
    "date,window_hint,expected_date",
    [
        ("yesterday", "yesterday", "2026-02-08"),
        (None, "yesterday", "2026-02-08"),
    ],
)
def test_calendar_list_events_supports_yesterday_window_hint(
    monkeypatch: pytest.MonkeyPatch,
    date: str | None,
    window_hint: str | None,
    expected_date: str,
) -> None:
    mock_list = _mock_list_events(monkeypatch)

    resp = calendar_tools.calendar_list_events_tool(
        date=date,
        window_hint=window_hint,
        max_results=3,
    )

    assert resp["ok"] is True
    kwargs: dict[str, Any] = mock_list.call_args.kwargs
    assert kwargs["time_min"].startswith(f"{expected_date}T00:00")


def test_calendar_create_event_resolves_relative_date_token(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_create = MagicMock(return_value={"ok": True, "id": "evt1"})
    monkeypatch.setattr(calendar_tools, "create_event_with_idempotency", mock_create)

    resp = calendar_tools.calendar_create_event_tool(
        title="Test",
        date="today",
        time="10:00",
        duration=30,
    )

    assert resp["ok"] is True
    assert mock_create.call_count == 1
    kwargs: dict[str, Any] = mock_create.call_args.kwargs
    assert kwargs["start"].startswith("2026-02-09T10:00")


def test_calendar_find_free_slots_resolves_relative_date_token(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_free = MagicMock(return_value={"ok": True, "slots": []})
    monkeypatch.setattr(calendar_tools, "find_free_slots", mock_free)

    resp = calendar_tools.calendar_find_free_slots_tool(
        date="today",
        window_hint=None,
        duration=30,
        suggestions=1,
    )

    assert resp["ok"] is True
    assert mock_free.call_count == 1
    kwargs: dict[str, Any] = mock_free.call_args.kwargs
    assert kwargs["time_min"].startswith("2026-02-09T09:00")
    assert kwargs["time_max"].startswith("2026-02-09T18:00")
