"""Test calendar.update_event with partial update support (Issue #163).

Tests verify that update_event now supports partial updates:
- Update only summary
- Update only location  
- Update only description
- Update only start/end (both required together)
- Update multiple fields at once
- Error cases: missing event_id, start without end, empty updates
"""

from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

from bantz.google.calendar import update_event


def test_update_event_summary_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating only the summary/title field."""
    mock_service = MagicMock()
    mock_updated = {
        "id": "evt_123",
        "summary": "Updated Sprint Planning",
        "htmlLink": "https://calendar.google.com/event?eid=evt_123",
        "start": {"dateTime": "2026-02-05T14:00:00+03:00"},
        "end": {"dateTime": "2026-02-05T15:00:00+03:00"},
        "location": "Office 301",
        "description": "Original description",
    }
    
    mock_service.events().patch().execute.return_value = mock_updated
    
    def mock_build(service_name: str, version: str, **kwargs):
        assert service_name == "calendar" and version == "v3"
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    result = update_event(
        event_id="evt_123",
        summary="Updated Sprint Planning",
    )
    
    # Verify only summary was sent in the patch request
    call_args = mock_service.events().patch.call_args
    assert call_args is not None
    assert call_args.kwargs["eventId"] == "evt_123"
    assert call_args.kwargs["body"] == {"summary": "Updated Sprint Planning"}
    
    # Verify response
    assert result["ok"] is True
    assert result["id"] == "evt_123"
    assert result["summary"] == "Updated Sprint Planning"
    assert result["location"] == "Office 301"


def test_update_event_location_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating only the location field."""
    mock_service = MagicMock()
    mock_updated = {
        "id": "evt_456",
        "summary": "Team Meeting",
        "htmlLink": "https://calendar.google.com/event?eid=evt_456",
        "start": {"dateTime": "2026-02-06T10:00:00+03:00"},
        "end": {"dateTime": "2026-02-06T11:00:00+03:00"},
        "location": "Zoom (updated)",
        "description": "Weekly sync",
    }
    
    mock_service.events().patch().execute.return_value = mock_updated
    
    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    result = update_event(
        event_id="evt_456",
        location="Zoom (updated)",
    )
    
    # Verify only location was sent
    call_args = mock_service.events().patch.call_args
    assert call_args.kwargs["body"] == {"location": "Zoom (updated)"}
    
    assert result["ok"] is True
    assert result["location"] == "Zoom (updated)"


def test_update_event_description_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating only the description field."""
    mock_service = MagicMock()
    mock_updated = {
        "id": "evt_789",
        "summary": "Project Review",
        "htmlLink": "https://calendar.google.com/event?eid=evt_789",
        "start": {"dateTime": "2026-02-07T14:00:00+03:00"},
        "end": {"dateTime": "2026-02-07T15:30:00+03:00"},
        "description": "Updated: Please prepare Q1 metrics",
    }
    
    mock_service.events().patch().execute.return_value = mock_updated
    
    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    result = update_event(
        event_id="evt_789",
        description="Updated: Please prepare Q1 metrics",
    )
    
    # Verify only description was sent
    call_args = mock_service.events().patch.call_args
    assert call_args.kwargs["body"] == {"description": "Updated: Please prepare Q1 metrics"}
    
    assert result["ok"] is True
    assert result["description"] == "Updated: Please prepare Q1 metrics"


def test_update_event_time_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating only start/end time (both required together)."""
    mock_service = MagicMock()
    mock_updated = {
        "id": "evt_time",
        "summary": "Dentist Appointment",
        "htmlLink": "https://calendar.google.com/event?eid=evt_time",
        "start": {"dateTime": "2026-02-08T15:00:00+03:00"},
        "end": {"dateTime": "2026-02-08T16:00:00+03:00"},
        "location": "Clinic",
    }
    
    mock_service.events().patch().execute.return_value = mock_updated
    
    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    result = update_event(
        event_id="evt_time",
        start="2026-02-08T15:00:00+03:00",
        end="2026-02-08T16:00:00+03:00",
    )
    
    # Verify only start/end were sent
    call_args = mock_service.events().patch.call_args
    body = call_args.kwargs["body"]
    assert "start" in body
    assert "end" in body
    assert body["start"]["dateTime"] == "2026-02-08T15:00:00+03:00"
    assert body["end"]["dateTime"] == "2026-02-08T16:00:00+03:00"
    assert "summary" not in body
    assert "location" not in body
    
    assert result["ok"] is True
    assert result["start"] == "2026-02-08T15:00:00+03:00"


def test_update_event_multiple_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test updating multiple fields at once."""
    mock_service = MagicMock()
    mock_updated = {
        "id": "evt_multi",
        "summary": "Updated Meeting Title",
        "htmlLink": "https://calendar.google.com/event?eid=evt_multi",
        "start": {"dateTime": "2026-02-09T10:00:00+03:00"},
        "end": {"dateTime": "2026-02-09T11:30:00+03:00"},
        "location": "Conference Room B",
        "description": "New agenda items",
    }
    
    mock_service.events().patch().execute.return_value = mock_updated
    
    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    result = update_event(
        event_id="evt_multi",
        summary="Updated Meeting Title",
        start="2026-02-09T10:00:00+03:00",
        end="2026-02-09T11:30:00+03:00",
        location="Conference Room B",
        description="New agenda items",
    )
    
    # Verify all fields were sent
    call_args = mock_service.events().patch.call_args
    body = call_args.kwargs["body"]
    assert body["summary"] == "Updated Meeting Title"
    assert body["start"]["dateTime"] == "2026-02-09T10:00:00+03:00"
    assert body["end"]["dateTime"] == "2026-02-09T11:30:00+03:00"
    assert body["location"] == "Conference Room B"
    assert body["description"] == "New agenda items"
    
    assert result["ok"] is True


def test_update_event_error_missing_event_id() -> None:
    """Test error when event_id is missing."""
    with pytest.raises(ValueError, match="event_id_required"):
        update_event(event_id="", summary="New Title")
    
    with pytest.raises(ValueError, match="event_id_required"):
        update_event(event_id="   ", location="Zoom")


def test_update_event_error_start_without_end() -> None:
    """Test error when start is provided but end is not."""
    with pytest.raises(ValueError, match="start_and_end_must_be_provided_together"):
        update_event(
            event_id="evt_123",
            start="2026-02-10T14:00:00+03:00",
        )


def test_update_event_error_end_without_start() -> None:
    """Test error when end is provided but start is not."""
    with pytest.raises(ValueError, match="start_and_end_must_be_provided_together"):
        update_event(
            event_id="evt_123",
            end="2026-02-10T15:00:00+03:00",
        )


def test_update_event_error_no_fields_to_update() -> None:
    """Test error when no fields are provided for update."""
    with pytest.raises(ValueError, match="at_least_one_field_must_be_updated"):
        update_event(event_id="evt_123")


def test_update_event_error_invalid_time_range() -> None:
    """Test error when end is before or equal to start."""
    with pytest.raises(ValueError, match="end_must_be_after_start"):
        update_event(
            event_id="evt_123",
            start="2026-02-10T15:00:00+03:00",
            end="2026-02-10T14:00:00+03:00",  # Before start
        )
    
    with pytest.raises(ValueError, match="end_must_be_after_start"):
        update_event(
            event_id="evt_123",
            start="2026-02-10T15:00:00+03:00",
            end="2026-02-10T15:00:00+03:00",  # Equal to start
        )


def test_update_event_error_empty_summary() -> None:
    """Test error when summary is empty string."""
    with pytest.raises(ValueError, match="summary_cannot_be_empty"):
        update_event(event_id="evt_123", summary="")
    
    with pytest.raises(ValueError, match="summary_cannot_be_empty"):
        update_event(event_id="evt_123", summary="   ")


def test_update_event_error_event_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test error handling when event is not found."""
    mock_service = MagicMock()
    
    # Simulate 404 error from Google API
    mock_service.events().patch().execute.side_effect = Exception("Not found (404)")
    
    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    with pytest.raises(ValueError, match="event_not_found: nonexistent_123"):
        update_event(
            event_id="nonexistent_123",
            summary="New Title",
        )


def test_update_event_preserves_unchanged_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that unchanged fields are preserved in the response."""
    mock_service = MagicMock()
    
    # API returns the full event with both changed and unchanged fields
    mock_updated = {
        "id": "evt_preserve",
        "summary": "Original Title",  # Unchanged
        "htmlLink": "https://calendar.google.com/event?eid=evt_preserve",
        "start": {"dateTime": "2026-02-11T09:00:00+03:00"},  # Unchanged
        "end": {"dateTime": "2026-02-11T10:00:00+03:00"},  # Unchanged
        "location": "New Office 404",  # Changed
        "description": "Original description",  # Unchanged
    }
    
    mock_service.events().patch().execute.return_value = mock_updated
    
    def mock_build(service_name: str, version: str, **kwargs):
        return mock_service
    
    mock_discovery = ModuleType("googleapiclient.discovery")
    mock_discovery.build = mock_build
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", mock_discovery)
    
    def mock_creds(scopes):
        return MagicMock()
    
    monkeypatch.setattr("bantz.google.auth.get_credentials", mock_creds)
    
    result = update_event(
        event_id="evt_preserve",
        location="New Office 404",  # Only updating location
    )
    
    # Verify only location was sent in patch
    call_args = mock_service.events().patch.call_args
    assert call_args.kwargs["body"] == {"location": "New Office 404"}
    
    # Verify response includes all fields (both changed and unchanged)
    assert result["summary"] == "Original Title"
    assert result["location"] == "New Office 404"
    assert result["description"] == "Original description"
    assert result["start"] == "2026-02-11T09:00:00+03:00"
    assert result["end"] == "2026-02-11T10:00:00+03:00"


def test_update_event_tool_registered() -> None:
    """Test that calendar.update_event tool is properly registered."""
    from bantz.agent.builtin_tools import build_planner_registry
    
    registry = build_planner_registry()
    tool = registry.get("calendar.update_event")
    
    assert tool is not None
    assert tool.name == "calendar.update_event"
    assert tool.risk_level == "MED"
    assert tool.requires_confirmation is True
    
    # Verify parameters
    params = tool.parameters
    assert params["required"] == ["event_id"]  # Only event_id is required now
    assert "event_id" in params["properties"]
    assert "summary" in params["properties"]
    assert "start" in params["properties"]
    assert "end" in params["properties"]
    assert "location" in params["properties"]
    assert "description" in params["properties"]
