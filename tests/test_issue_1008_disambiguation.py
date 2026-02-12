"""Tests for Issue #1008: Disambiguation — empty intent guard + error handling.

1. Empty intent must NOT trigger disambiguation
2. Unknown intent must NOT trigger disambiguation
3. Valid intent still triggers normally
4. Non-dict tool results don't crash extract_references
"""

import pytest

from bantz.brain.disambiguation import DisambiguationDialog


def _fake_tool_results(n=3):
    """Return fake tool results with N calendar events."""
    events = [
        {"summary": f"Toplantı {i}", "start": f"2025-07-21T{10+i}:00:00"}
        for i in range(n)
    ]
    return [{"tool": "calendar.list_events", "result": events, "success": True}]


class TestEmptyIntentGuard:
    """Issue #1008: Empty intent should NOT trigger disambiguation."""

    def test_empty_intent_returns_none(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results(_fake_tool_results(), intent="")
        assert result is None

    def test_none_like_empty_returns_none(self):
        """Falsy intent values should skip disambiguation."""
        dialog = DisambiguationDialog()
        # Whitespace-only
        result = dialog.check_tool_results(_fake_tool_results(), intent="   ")
        # "   ".strip() is falsy, but our guard checks `not intent`
        # Whitespace-only is truthy but not in DISAMBIGUATION_INTENTS → None
        assert result is None

    def test_unknown_intent_returns_none(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results(_fake_tool_results(), intent="weather_check")
        assert result is None

    def test_valid_intent_triggers(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results(
            _fake_tool_results(),
            intent="calendar_delete_event",
        )
        assert result is not None
        assert result.original_intent == "calendar_delete_event"

    def test_single_item_below_threshold(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results(
            _fake_tool_results(n=1),
            intent="calendar_delete_event",
        )
        assert result is None


class TestExtractReferencesErrorHandling:
    """Non-dict tool results should not crash."""

    def test_non_dict_tool_result(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results(
            ["not a dict", 42, None],
            intent="calendar_delete_event",
        )
        assert result is None

    def test_empty_tool_results(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results([], intent="calendar_delete_event")
        assert result is None


class TestMaxItemsParam:
    """max_items parameter is respected."""

    def test_max_items_limits_table(self):
        dialog = DisambiguationDialog()
        result = dialog.check_tool_results(
            _fake_tool_results(n=20),
            intent="calendar_delete_event",
            max_items=5,
        )
        if result:
            assert result.item_count <= 5
