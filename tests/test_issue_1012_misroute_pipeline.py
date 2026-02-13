"""Tests for Issue #1012: Misroute dataset pipeline integration.

Tests the misroute_integration module (classification + recording logic)
without requiring a running orchestrator or vLLM.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from bantz.brain.misroute_integration import (
    _classify_misroute,
    _build_notes,
    record_turn_misroute,
    LOW_CONFIDENCE_THRESHOLD,
)


class TestClassifyMisroute:
    """Misroute classification logic."""

    def test_unknown_route_is_fallback(self):
        result = _classify_misroute(
            route="unknown", confidence=0.5,
            tool_results=[], original_route=None,
        )
        assert result == "fallback"

    def test_empty_route_is_fallback(self):
        result = _classify_misroute(
            route="", confidence=0.5,
            tool_results=[], original_route=None,
        )
        assert result == "fallback"

    def test_route_corrected_is_wrong_route(self):
        result = _classify_misroute(
            route="gmail", confidence=0.8,
            tool_results=[], original_route="calendar",
        )
        assert result == "wrong_route"

    def test_low_confidence(self):
        result = _classify_misroute(
            route="calendar", confidence=0.1,
            tool_results=[], original_route=None,
        )
        assert result == "low_confidence"

    def test_tool_failure_is_wrong_route(self):
        result = _classify_misroute(
            route="calendar", confidence=0.9,
            tool_results=[{"tool": "calendar.list_events", "success": False}],
            original_route=None,
        )
        assert result == "wrong_route"

    def test_no_misroute(self):
        result = _classify_misroute(
            route="calendar", confidence=0.9,
            tool_results=[{"tool": "calendar.list_events", "success": True}],
            original_route=None,
        )
        assert result is None

    def test_same_original_route_not_wrong(self):
        """If original_route == route, it's not a correction."""
        result = _classify_misroute(
            route="gmail", confidence=0.9,
            tool_results=[], original_route="gmail",
        )
        assert result is None


class TestBuildNotes:
    """Notes builder for misroute records."""

    def test_route_correction_noted(self):
        notes = _build_notes([], [], "calendar", "gmail")
        assert "calendar → gmail" in notes

    def test_tool_names_listed(self):
        notes = _build_notes(
            [{"name": "calendar.list_events"}, "gmail.send"],
            [], None, "calendar",
        )
        assert "calendar.list_events" in notes
        assert "gmail.send" in notes

    def test_failed_tools_noted(self):
        notes = _build_notes(
            [], [{"tool": "calendar.list_events", "success": False}],
            None, "calendar",
        )
        assert "failed" in notes

    def test_empty_notes(self):
        notes = _build_notes([], [], None, "calendar")
        assert notes == ""


class TestRecordTurnMisroute:
    """Integration test for record_turn_misroute."""

    @patch("bantz.brain.misroute_integration.MISROUTE_COLLECT_ENABLED", False)
    def test_disabled_does_nothing(self):
        """When disabled, no recording happens."""
        with patch("bantz.brain.misroute_integration._get_dataset") as mock_ds:
            record_turn_misroute(
                user_input="test",
                route="unknown",
                intent="none",
                confidence=0.5,
                tool_plan=[],
                tool_results=[],
            )
            mock_ds.assert_not_called()

    @patch("bantz.brain.misroute_integration.MISROUTE_COLLECT_ENABLED", True)
    def test_enabled_records_fallback(self):
        """When enabled, unknown route triggers recording."""
        mock_dataset = MagicMock()
        with patch("bantz.brain.misroute_integration._get_dataset", return_value=mock_dataset):
            record_turn_misroute(
                user_input="merhaba",
                route="unknown",
                intent="none",
                confidence=0.3,
                tool_plan=[],
                tool_results=[],
            )
            mock_dataset.append.assert_called_once()
            record = mock_dataset.append.call_args[0][0]
            assert record.user_text == "merhaba"
            assert record.reason == "fallback"

    @patch("bantz.brain.misroute_integration.MISROUTE_COLLECT_ENABLED", True)
    def test_no_misroute_skips_recording(self):
        """Normal successful turns are not recorded."""
        mock_dataset = MagicMock()
        with patch("bantz.brain.misroute_integration._get_dataset", return_value=mock_dataset):
            record_turn_misroute(
                user_input="bugün ne var?",
                route="calendar",
                intent="query",
                confidence=0.9,
                tool_plan=["calendar.list_events"],
                tool_results=[{"tool": "calendar.list_events", "success": True}],
            )
            mock_dataset.append.assert_not_called()
