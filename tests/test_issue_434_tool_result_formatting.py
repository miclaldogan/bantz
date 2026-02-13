"""
Tests for Issue #434 — Tool Result Formatting.

Covers:
- Calendar list_events formatting (Turkish summary)
- Calendar create/delete/update event formatting
- Gmail list_messages / send / get_message formatting
- time.now formatting
- OutputFormat.RAW_JSON passthrough
- Error result handling
- Unknown tool passthrough
- Edge cases: empty events, nested dateTime, long subjects
"""

from __future__ import annotations

import pytest

from bantz.tools.result_formatter import (
    OutputFormat,
    format_calendar_create_event,
    format_calendar_delete_event,
    format_calendar_list_events,
    format_calendar_update_event,
    format_gmail_get_message,
    format_gmail_list_messages,
    format_gmail_send,
    format_time_now,
    format_tool_result,
    get_supported_tools,
)


# ─────────────────────────────────────────────────────────────────
# Calendar list_events
# ─────────────────────────────────────────────────────────────────


class TestCalendarListEvents:

    def test_empty_events(self):
        r = format_calendar_list_events({"events": []})
        assert "bulunamadı" in r

    def test_single_event(self):
        r = format_calendar_list_events({
            "events": [
                {"summary": "Toplantı", "start": "2025-01-15T14:00:00+03:00", "end": "2025-01-15T15:00:00+03:00"}
            ]
        })
        assert "14:00" in r
        assert "Toplantı" in r
        assert "1 saat" in r

    def test_multiple_events(self):
        r = format_calendar_list_events({
            "events": [
                {"summary": "Toplantı", "start": "2025-01-15T14:00:00+03:00", "end": "2025-01-15T15:00:00+03:00"},
                {"summary": "Doktor", "start": "2025-01-15T16:00:00+03:00", "end": "2025-01-15T16:30:00+03:00"},
            ]
        })
        assert "2 etkinlik" in r
        assert "14:00 Toplantı" in r
        assert "16:00 Doktor" in r
        assert "30 dk" in r
        assert "|" in r

    def test_nested_datetime_format(self):
        """Google Calendar sometimes nests dateTime in a dict."""
        r = format_calendar_list_events({
            "events": [
                {"summary": "Test", "start": {"dateTime": "2025-01-15T10:00:00+03:00"}, "end": {"dateTime": "2025-01-15T11:00:00+03:00"}}
            ]
        })
        assert "10:00" in r
        assert "Test" in r

    def test_no_events_key(self):
        r = format_calendar_list_events({})
        assert "bulunamadı" in r

    def test_missing_summary(self):
        r = format_calendar_list_events({
            "events": [{"start": "2025-01-15T14:00:00+03:00"}]
        })
        assert "İsimsiz Etkinlik" in r

    def test_header_count(self):
        events = [
            {"summary": f"Etkinlik {i}", "start": f"2025-01-15T{10+i}:00:00+03:00"}
            for i in range(5)
        ]
        r = format_calendar_list_events({"events": events})
        assert "5 etkinlik" in r


# ─────────────────────────────────────────────────────────────────
# Calendar create/delete/update
# ─────────────────────────────────────────────────────────────────


class TestCalendarMutations:

    def test_create_success(self):
        r = format_calendar_create_event({
            "ok": True, "summary": "Toplantı", "start": "2025-01-15T14:00:00+03:00"
        })
        assert "oluşturuldu" in r
        assert "Toplantı" in r
        assert "14:00" in r
        assert "Ocak" in r

    def test_create_failure(self):
        r = format_calendar_create_event({"ok": False, "error": "API error"})
        assert "oluşturulamadı" in r
        assert "API error" in r

    def test_create_no_start(self):
        r = format_calendar_create_event({"ok": True, "summary": "Test"})
        assert "oluşturuldu" in r

    def test_delete_success(self):
        r = format_calendar_delete_event({"ok": True, "summary": "Toplantı"})
        assert "silindi" in r

    def test_delete_failure(self):
        r = format_calendar_delete_event({"ok": False, "error": "not found"})
        assert "silinemedi" in r

    def test_update_success(self):
        r = format_calendar_update_event({"ok": True, "summary": "Toplantı"})
        assert "güncellendi" in r

    def test_update_failure(self):
        r = format_calendar_update_event({"ok": False, "error": "conflict"})
        assert "güncellenemedi" in r


# ─────────────────────────────────────────────────────────────────
# Gmail
# ─────────────────────────────────────────────────────────────────


class TestGmailFormatting:

    def test_list_empty(self):
        r = format_gmail_list_messages({"messages": []})
        assert "bulunamadı" in r

    def test_list_messages(self):
        r = format_gmail_list_messages({
            "messages": [
                {"from": "Ali Yılmaz <ali@test.com>", "subject": "Proje hakkında"},
                {"from": "Mehmet <m@test.com>", "subject": "Toplantı notu"},
            ]
        })
        assert "2 mesaj" in r
        assert "Ali Yılmaz" in r
        assert "Proje hakkında" in r
        assert "|" in r

    def test_list_long_subject_truncated(self):
        long_subject = "Bu çok uzun bir konu başlığıdır ve kırpılması gerekir çünkü çok fazla karakter var"
        r = format_gmail_list_messages({
            "messages": [{"from": "Test", "subject": long_subject}]
        })
        assert "..." in r

    def test_send_success(self):
        r = format_gmail_send({"ok": True, "to": "ali@test.com"})
        assert "gönderildi" in r
        assert "ali@test.com" in r

    def test_send_failure(self):
        r = format_gmail_send({"ok": False, "error": "rate limit"})
        assert "gönderilemedi" in r

    def test_get_message(self):
        r = format_gmail_get_message({
            "from": "Ali <ali@test.com>",
            "subject": "Test konu",
            "snippet": "Merhaba, toplantı hakkında...",
        })
        assert "Ali" in r
        assert "Test konu" in r
        assert "Merhaba" in r


# ─────────────────────────────────────────────────────────────────
# time.now
# ─────────────────────────────────────────────────────────────────


class TestTimeNow:

    def test_time_and_date(self):
        r = format_time_now({"time": "14:30", "date": "2025-01-15"})
        assert "14:30" in r
        assert "2025-01-15" in r

    def test_time_only(self):
        r = format_time_now({"time": "14:30"})
        assert "Saat 14:30" in r


# ─────────────────────────────────────────────────────────────────
# format_tool_result dispatcher
# ─────────────────────────────────────────────────────────────────


class TestFormatToolResult:

    def test_human_readable(self):
        r = format_tool_result("calendar.list_events", {"events": []})
        assert isinstance(r, str)
        assert "bulunamadı" in r

    def test_raw_json_passthrough(self):
        data = {"events": [{"x": 1}]}
        r = format_tool_result("calendar.list_events", data, output_format=OutputFormat.RAW_JSON)
        assert r == data

    def test_unknown_tool_passthrough(self):
        data = {"some": "data"}
        r = format_tool_result("unknown.tool", data)
        assert r == data

    def test_error_result(self):
        r = format_tool_result("calendar.list_events", {"ok": False, "error": "timeout"})
        assert "başarısız" in r

    def test_non_dict_passthrough(self):
        r = format_tool_result("calendar.list_events", "plain string")
        assert r == "plain string"

    def test_none_result(self):
        r = format_tool_result("calendar.list_events", None)
        assert r is None


# ─────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────


class TestUtilities:

    def test_get_supported_tools(self):
        tools = get_supported_tools()
        assert "calendar.list_events" in tools
        assert "gmail.send" in tools
        assert "time.now" in tools

    def test_efendim_in_outputs(self):
        """All formatter outputs should include efendim for Jarvis persona."""
        assert "efendim" in format_calendar_list_events({"events": []})
        assert "efendim" in format_gmail_list_messages({"messages": []})
        assert "efendim" in format_gmail_send({"ok": True})
        assert "efendim" in format_time_now({"time": "14:00"})
