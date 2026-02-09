from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from bantz.agent.builtin_tools import build_planner_registry
from bantz.google.calendar import delete_event, update_event


def test_calendar_delete_event_tool_registered() -> None:
    reg = build_planner_registry()
    tool = reg.get("calendar.delete_event")
    assert tool is not None
    assert tool.risk_level == "MED"
    assert tool.requires_confirmation is True


def test_calendar_update_event_tool_registered() -> None:
    reg = build_planner_registry()
    tool = reg.get("calendar.update_event")
    assert tool is not None
    assert tool.risk_level == "MED"
    assert tool.requires_confirmation is True


def test_calendar_delete_event_builds_delete_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import bantz.google.auth as auth

    monkeypatch.setattr(auth, "get_credentials", lambda *args, **kwargs: object())

    calls: dict[str, Any] = {}

    class _FakeDelete:
        def __init__(self, *, calendarId: str, eventId: str):
            calls["calendarId"] = calendarId
            calls["eventId"] = eventId

        def execute(self):
            return {}

    class _FakeEvents:
        def delete(self, *, calendarId: str, eventId: str):
            return _FakeDelete(calendarId=calendarId, eventId=eventId)

    class _FakeService:
        def events(self):
            return _FakeEvents()

    def _fake_build(api: str, version: str, *, credentials: object, cache_discovery: bool):
        calls["build"] = {"api": api, "version": version, "cache_discovery": cache_discovery, "has_creds": credentials is not None}
        return _FakeService()

    discovery = ModuleType("googleapiclient.discovery")
    discovery.build = _fake_build  # type: ignore[attr-defined]
    googleapiclient = ModuleType("googleapiclient")

    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    out = delete_event(event_id="evt_123", calendar_id="primary")

    assert out["ok"] is True
    assert out["id"] == "evt_123"
    assert out["calendar_id"] == "primary"
    assert calls["build"]["api"] == "calendar"
    assert calls["calendarId"] == "primary"
    assert calls["eventId"] == "evt_123"


def test_calendar_update_event_builds_patch_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import bantz.google.auth as auth

    monkeypatch.setattr(auth, "get_credentials", lambda *args, **kwargs: object())

    calls: dict[str, Any] = {}

    class _FakePatch:
        def __init__(self, *, calendarId: str, eventId: str, body: dict[str, Any]):
            calls["calendarId"] = calendarId
            calls["eventId"] = eventId
            calls["body"] = body

        def execute(self):
            return {
                "id": calls["eventId"],
                "summary": calls["body"].get("summary"),
                "start": calls["body"].get("start"),
                "end": calls["body"].get("end"),
                "htmlLink": "https://example.test/event",
            }

    class _FakeEvents:
        def patch(self, *, calendarId: str, eventId: str, body: dict[str, Any]):
            return _FakePatch(calendarId=calendarId, eventId=eventId, body=body)

    class _FakeService:
        def events(self):
            return _FakeEvents()

    def _fake_build(api: str, version: str, *, credentials: object, cache_discovery: bool):
        calls["build"] = {"api": api, "version": version, "cache_discovery": cache_discovery, "has_creds": credentials is not None}
        return _FakeService()

    discovery = ModuleType("googleapiclient.discovery")
    discovery.build = _fake_build  # type: ignore[attr-defined]
    googleapiclient = ModuleType("googleapiclient")

    monkeypatch.setitem(sys.modules, "googleapiclient", googleapiclient)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    out = update_event(
        event_id="evt_123",
        start="2026-01-28T15:45:00+03:00",
        end="2026-01-28T16:45:00+03:00",
        summary="Koşu",
        calendar_id="primary",
    )

    assert out["ok"] is True
    assert out["id"] == "evt_123"
    assert out["calendar_id"] == "primary"
    assert calls["build"]["api"] == "calendar"
    assert calls["calendarId"] == "primary"
    assert calls["eventId"] == "evt_123"

    body = calls["body"]
    assert body["summary"] == "Koşu"
    assert "dateTime" in body["start"]
    assert "dateTime" in body["end"]
