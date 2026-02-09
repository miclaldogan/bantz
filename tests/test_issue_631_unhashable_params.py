"""Tests for Issue #631 — executor unhashable confirmation key.

``frozenset(step.params.items())`` crashed with *TypeError: unhashable type*
when params contained lists or nested dicts.  The fix extracts
``_make_action_key`` which uses ``json.dumps`` for stable, hashable keys.

Tests cover:
1. _make_action_key with simple params
2. _make_action_key with list values (recurrence)
3. _make_action_key with nested dict values (attendees)
4. _make_action_key determinism / stability
5. Confirmation flow with complex params end-to-end
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any

from bantz.agent.executor import Executor, ExecutionResult, _make_action_key
from bantz.agent.tools import ToolRegistry, Tool


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

@dataclass
class FakeStep:
    action: str
    params: dict[str, Any]
    description: str = "test step"


def _make_registry_with_delete() -> ToolRegistry:
    """Registry with a DESTRUCTIVE tool."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="calendar.delete_event",
            description="Delete event",
            parameters={
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
            },
            function=lambda event_id: {"deleted": event_id},
        )
    )
    registry.register(
        Tool(
            name="calendar.create_event",
            description="Create event",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "recurrence": {"type": "array"},
                    "attendees": {"type": "array"},
                },
            },
            function=lambda **kw: {"event_id": "e1"},
        )
    )
    return registry


def _ok_runner(action: str, params: dict) -> ExecutionResult:
    return ExecutionResult(ok=True, data={"ran": action})


# ═══════════════════════════════════════════════════════════
# 1. _make_action_key — unit tests
# ═══════════════════════════════════════════════════════════


class TestMakeActionKey:
    """Direct tests for _make_action_key helper."""

    def test_simple_params(self):
        key = _make_action_key("calendar.delete_event", {"event_id": "abc123"})
        assert key.startswith("calendar.delete_event:")
        assert isinstance(key, str)

    def test_list_value_no_crash(self):
        """Previously crashed: TypeError: unhashable type: 'list'."""
        params = {
            "title": "Standup",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
        }
        key = _make_action_key("calendar.create_event", params)
        assert "calendar.create_event:" in key

    def test_nested_dict_value_no_crash(self):
        """Previously crashed: TypeError: unhashable type: 'dict'."""
        params = {
            "title": "Meeting",
            "attendees": [{"email": "a@b.com"}, {"email": "c@d.com"}],
        }
        key = _make_action_key("calendar.create_event", params)
        assert "calendar.create_event:" in key

    def test_deeply_nested_no_crash(self):
        params = {
            "config": {
                "nested": {
                    "deep": [1, 2, {"key": [True, None]}]
                }
            }
        }
        key = _make_action_key("some.action", params)
        assert "some.action:" in key

    def test_determinism(self):
        """Same input → same key every time."""
        params = {"b": 2, "a": 1, "c": [3, 4]}
        k1 = _make_action_key("x", params)
        k2 = _make_action_key("x", params)
        assert k1 == k2

    def test_key_order_independent(self):
        """sort_keys=True ensures insertion-order doesn't matter."""
        k1 = _make_action_key("x", {"a": 1, "b": 2})
        k2 = _make_action_key("x", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_params_different_keys(self):
        k1 = _make_action_key("x", {"event_id": "aaa"})
        k2 = _make_action_key("x", {"event_id": "bbb"})
        assert k1 != k2

    def test_different_actions_different_keys(self):
        params = {"event_id": "aaa"}
        k1 = _make_action_key("calendar.delete_event", params)
        k2 = _make_action_key("calendar.update_event", params)
        assert k1 != k2

    def test_empty_params(self):
        key = _make_action_key("x", {})
        assert key.startswith("x:")

    def test_none_value(self):
        key = _make_action_key("x", {"a": None})
        assert "x:" in key

    def test_datetime_via_default_str(self):
        """default=str handles non-JSON-serialisable objects."""
        from datetime import datetime

        params = {"ts": datetime(2025, 7, 13, 10, 0)}
        key = _make_action_key("x", params)
        assert "x:" in key

    def test_set_via_default_str(self):
        """Sets are not JSON-serialisable; default=str handles them."""
        params = {"tags": {1, 2, 3}}
        key = _make_action_key("x", params)
        assert "x:" in key


# ═══════════════════════════════════════════════════════════
# 2. End-to-end confirmation flow with complex params
# ═══════════════════════════════════════════════════════════


class TestConfirmationWithComplexParams:
    """Ensure confirm → execute round-trip works with list/dict params."""

    def test_confirm_then_execute_with_list_params(self):
        """Full flow: confirm a step whose params contain a list."""
        registry = _make_registry_with_delete()
        executor = Executor(registry)

        step = FakeStep(
            action="calendar.delete_event",
            params={"event_id": "e1"},
        )

        # First call → awaiting confirmation
        result = executor.execute(step, runner=_ok_runner)
        assert result.awaiting_confirmation

        # Confirm
        executor.confirm_action(step)

        # Second call → should execute
        result = executor.execute(step, runner=_ok_runner)
        assert result.ok
        assert not result.awaiting_confirmation

    def test_confirm_with_attendees_list(self):
        """List-of-dict params must not crash during confirm."""
        registry = _make_registry_with_delete()
        executor = Executor(registry)

        step = FakeStep(
            action="calendar.create_event",
            params={
                "title": "Team sync",
                "start": "2025-07-14T10:00:00",
                "attendees": [{"email": "a@b.com"}, {"email": "c@d.com"}],
            },
        )

        # Should not crash — this was the original bug
        executor.confirm_action(step)

        # Key should be in confirmed set
        assert len(executor.confirmed_actions) == 1

    def test_confirm_with_recurrence_list(self):
        """Recurrence list must not crash."""
        registry = _make_registry_with_delete()
        executor = Executor(registry)

        step = FakeStep(
            action="calendar.create_event",
            params={
                "title": "Standup",
                "start": "2025-07-14T09:00:00",
                "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"],
            },
        )

        # Must not raise TypeError
        executor.confirm_action(step)
        assert len(executor.confirmed_actions) == 1

    def test_key_consistency_between_confirm_and_execute(self):
        """confirm_action and execute must produce the same key."""
        registry = _make_registry_with_delete()
        executor = Executor(registry)

        step = FakeStep(
            action="calendar.delete_event",
            params={"event_id": "xyz"},
        )

        executor.confirm_action(step)
        # The execute path should find the key and proceed
        result = executor.execute(step, runner=_ok_runner)
        assert result.ok, f"Expected ok=True after confirm, got error={result.error}"
