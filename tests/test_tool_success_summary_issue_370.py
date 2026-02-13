"""Tests for Issue #370: Tool-aware success summary instead of generic 'Tamamlandı'.

Verifies that _build_tool_success_summary generates informative messages
based on tool results rather than generic 'Tamamlandı efendim'.
"""

import pytest
from bantz.brain.orchestrator_loop import (
    _build_tool_success_summary,
    _count_items,
    _extract_count,
    _extract_field,
)


class TestBuildToolSuccessSummary:
    """Test _build_tool_success_summary with various tool results."""

    def test_calendar_list_events_with_items(self):
        """list_events returning 5 events → '5 etkinlik bulundu efendim.'"""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": [
                {"summary": "Toplantı", "start": "10:00"},
                {"summary": "Öğle yemeği", "start": "12:00"},
                {"summary": "Demo", "start": "14:00"},
                {"summary": "Sprint", "start": "15:00"},
                {"summary": "Retrospektif", "start": "16:00"},
            ],
        }]
        msg = _build_tool_success_summary(results)
        assert "5 etkinlik bulundu" in msg

    def test_calendar_list_events_empty(self):
        """list_events returning 0 events → bulunamadı."""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": [],
        }]
        msg = _build_tool_success_summary(results)
        assert "bulunamadı" in msg

    def test_calendar_list_events_single(self):
        """list_events returning 1 event → '1 etkinlik bulundu'."""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": [{"summary": "Toplantı"}],
        }]
        msg = _build_tool_success_summary(results)
        assert "1 etkinlik bulundu" in msg

    def test_calendar_create_event_with_title(self):
        """create_event with title → includes title in message."""
        results = [{
            "tool": "calendar.create_event",
            "success": True,
            "raw_result": {"title": "Doktor randevusu", "ok": True},
        }]
        msg = _build_tool_success_summary(results)
        assert "Doktor randevusu" in msg
        assert "oluşturuldu" in msg

    def test_gmail_list_messages(self):
        """gmail.list_messages → N mesaj bulundu."""
        results = [{
            "tool": "gmail.list_messages",
            "success": True,
            "raw_result": {"messages": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        }]
        msg = _build_tool_success_summary(results)
        assert "3 mesaj bulundu" in msg

    def test_gmail_unread_count(self):
        """gmail.unread_count → okunmamış mesaj."""
        results = [{
            "tool": "gmail.unread_count",
            "success": True,
            "raw_result": {"count": 7},
        }]
        msg = _build_tool_success_summary(results)
        assert "7 okunmamış" in msg

    def test_gmail_unread_zero(self):
        """gmail.unread_count with 0 → yok."""
        results = [{
            "tool": "gmail.unread_count",
            "success": True,
            "raw_result": {"count": 0},
        }]
        msg = _build_tool_success_summary(results)
        assert "yok" in msg

    def test_gmail_send(self):
        """gmail.send → gönderildi."""
        results = [{
            "tool": "gmail.send",
            "success": True,
            "raw_result": {"ok": True},
        }]
        msg = _build_tool_success_summary(results)
        assert "gönderildi" in msg

    def test_empty_results_generic(self):
        """Empty tool_results → generic 'Tamamlandı efendim.'"""
        msg = _build_tool_success_summary([])
        assert msg == "Tamamlandı efendim."

    def test_multiple_tools(self):
        """Multiple tools → multi-line summary."""
        results = [
            {
                "tool": "calendar.list_events",
                "success": True,
                "raw_result": [{"summary": "A"}, {"summary": "B"}],
            },
            {
                "tool": "gmail.unread_count",
                "success": True,
                "raw_result": {"count": 3},
            },
        ]
        msg = _build_tool_success_summary(results)
        assert "2 etkinlik bulundu" in msg
        assert "3 okunmamış" in msg

    def test_unknown_tool_fallback(self):
        """Unknown tool → uses short tool name."""
        results = [{
            "tool": "system.check_status",
            "success": True,
            "raw_result": {"ok": True},
        }]
        msg = _build_tool_success_summary(results)
        assert "check_status" in msg
        assert "tamamlandı" in msg

    def test_dict_with_events_key(self):
        """Result dict with 'events' key → count events."""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {
                "events": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}],
            },
        }]
        msg = _build_tool_success_summary(results)
        assert "5 etkinlik bulundu" in msg

    def test_find_free_slots(self):
        """calendar.find_free_slots → zaman dilimi."""
        results = [{
            "tool": "calendar.find_free_slots",
            "success": True,
            "raw_result": {"slots": [{"start": "10:00"}, {"start": "14:00"}]},
        }]
        msg = _build_tool_success_summary(results)
        assert "2 uygun zaman dilimi" in msg


class TestHelpers:
    """Test helper functions."""

    def test_count_items_list(self):
        assert _count_items([1, 2, 3]) == 3

    def test_count_items_dict_with_items(self):
        assert _count_items({"items": [1, 2]}) == 2

    def test_count_items_dict_with_count(self):
        assert _count_items({"count": 42}) == 42

    def test_count_items_empty(self):
        assert _count_items({}) == 0

    def test_extract_count_int(self):
        assert _extract_count(5) == 5

    def test_extract_count_dict(self):
        assert _extract_count({"count": 10}) == 10

    def test_extract_count_none(self):
        assert _extract_count("abc") is None

    def test_extract_field(self):
        assert _extract_field({"title": "Test"}, "title") == "Test"

    def test_extract_field_fallback(self):
        assert _extract_field({"summary": "Test"}, "title", "summary") == "Test"

    def test_extract_field_none(self):
        assert _extract_field({"other": "val"}, "title") is None
