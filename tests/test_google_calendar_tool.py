from __future__ import annotations

from pathlib import Path

import pytest

from bantz.agent.builtin_tools import build_planner_registry
from bantz.google.calendar import list_events


def test_calendar_list_events_tool_registered():
    reg = build_planner_registry()
    tool = reg.get("calendar.list_events")
    assert tool is not None
    assert tool.risk_level == "LOW"
    assert tool.requires_confirmation is False
    assert isinstance(tool.parameters, dict)


def test_calendar_list_events_missing_client_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BANTZ_GOOGLE_CLIENT_SECRET", str(tmp_path / "missing_client_secret.json"))
    monkeypatch.setenv("BANTZ_GOOGLE_TOKEN_PATH", str(tmp_path / "token.json"))

    with pytest.raises(FileNotFoundError) as exc:
        list_events(max_results=1)

    assert "BANTZ_GOOGLE_CLIENT_SECRET" in str(exc.value)
