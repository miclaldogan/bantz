"""Tests for Issue #1312: _resolve_tool_from_intent system route fix.

Previously the system route always returned ("system", "none") → "time.now",
ignoring the calendar_intent parameter entirely. After the fix, specific
intents like "status" resolve to the correct tool.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from bantz.brain.llm_router import JarvisLLMOrchestrator


# ======================================================================
# Helpers
# ======================================================================

def _make_orchestrator() -> JarvisLLMOrchestrator:
    """Create a minimal orchestrator for unit-testing _resolve_tool_from_intent."""
    with patch.object(JarvisLLMOrchestrator, "__init__", lambda self: None):
        orch = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)
    return orch


# ======================================================================
# System Route Tests (Issue #1312)
# ======================================================================


class TestResolveToolSystemRoute:
    """Verify system route respects the intent parameter."""

    def test_system_status_resolves_correctly(self):
        """'status' intent should return 'system.status', not 'time.now'."""
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("system", "status")
        assert result == "system.status"

    def test_system_time_resolves_correctly(self):
        """'time' intent should return 'time.now'."""
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("system", "time")
        assert result == "time.now"

    def test_system_none_resolves_to_default(self):
        """'none' intent should fall back to default 'time.now'."""
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("system", "none")
        assert result == "time.now"

    def test_system_unknown_intent_falls_back_to_default(self):
        """Unknown intent falls back to ("system", "none") → 'time.now'."""
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("system", "nonexistent_intent")
        assert result == "time.now"


# ======================================================================
# Calendar & Gmail Routes (regression guard)
# ======================================================================


class TestResolveToolOtherRoutes:
    """Ensure calendar and gmail routes still work correctly."""

    def test_calendar_create_event(self):
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("calendar", "create")
        assert result == "calendar.create_event"

    def test_calendar_list_events(self):
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("calendar", "query")
        assert result == "calendar.list_events"

    def test_gmail_read(self):
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("gmail", "none", "read")
        assert result == "gmail.list_messages"

    def test_gmail_send(self):
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("gmail", "none", "send")
        assert result == "gmail.send"

    def test_unknown_route_returns_none(self):
        orch = _make_orchestrator()
        result = orch._resolve_tool_from_intent("unknown", "whatever")
        assert result is None
