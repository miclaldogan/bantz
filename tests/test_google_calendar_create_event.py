from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from bantz.agent.builtin_tools import build_planner_registry
from bantz.google.calendar import create_event


def test_calendar_create_event_tool_registered():
    reg = build_planner_registry()
    tool = reg.get("calendar.create_event")
    assert tool is not None
    assert tool.risk_level == "MED"
    assert tool.requires_confirmation is True


def test_calendar_create_event_missing_client_secret(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BANTZ_GOOGLE_CLIENT_SECRET", str(tmp_path / "missing_client_secret.json"))
    monkeypatch.setenv("BANTZ_GOOGLE_TOKEN_PATH", str(tmp_path / "token.json"))

    with pytest.raises(FileNotFoundError) as exc:
        create_event(
            summary="Test",
            start="2026-01-28T15:45:00+03:00",
            duration_minutes=30,
        )

    assert "BANTZ_GOOGLE_CLIENT_SECRET" in str(exc.value)


def test_calendar_create_event_builds_insert_payload(monkeypatch: pytest.MonkeyPatch):
    # Avoid importing real google libs.
    import bantz.google.auth as auth

    monkeypatch.setattr(auth, "get_credentials", lambda *args, **kwargs: object())

    calls: dict[str, Any] = {}

    class _FakeInsert:
        def __init__(self, *, calendarId: str, body: dict[str, Any]):
            calls["calendarId"] = calendarId
            calls["body"] = body

        def execute(self):
            return {
                "id": "evt_123",
                "htmlLink": "https://example.test/event",
                "summary": calls["body"].get("summary"),
                "start": calls["body"].get("start"),
                "end": calls["body"].get("end"),
            }

    class _FakeEvents:
        def insert(self, *, calendarId: str, body: dict[str, Any]):
            return _FakeInsert(calendarId=calendarId, body=body)

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

    out = create_event(
        summary="Koşu",
        start="2026-01-28T15:45:00+03:00",
        duration_minutes=120,
        calendar_id="primary",
        description="test",
        location="park",
    )

    assert out["ok"] is True
    assert out["id"] == "evt_123"
    assert calls["build"]["api"] == "calendar"
    assert calls["build"]["version"] == "v3"
    assert calls["calendarId"] == "primary"

    body = calls["body"]
    assert body["summary"] == "Koşu"
    assert body["description"] == "test"
    assert body["location"] == "park"
    assert "dateTime" in body["start"]
    assert "dateTime" in body["end"]
