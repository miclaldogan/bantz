"""
Tests for Issue #433 — Calendar Slot Validation.

Covers:
- SlotRequirement: alternatives, all_names
- TOOL_REQUIRED_SLOTS registry
- validate_tool_slots: valid/invalid/partial/alternatives
- SlotValidationResult: to_dict, ask_user
- calendar.create_event: title + (time|date|window_hint) combinations
- gmail.send: to + body required
- Unknown tools pass through (no requirements)
- Turkish clarification questions
- get_clarification_question convenience
- get_required_slot_names
"""

from __future__ import annotations

import pytest

from bantz.tools.slot_validation import (
    TOOL_REQUIRED_SLOTS,
    SlotRequirement,
    SlotValidationResult,
    get_clarification_question,
    get_required_slot_names,
    validate_tool_slots,
)


# ─────────────────────────────────────────────────────────────────
# SlotRequirement
# ─────────────────────────────────────────────────────────────────


class TestSlotRequirement:

    def test_basic(self):
        r = SlotRequirement(name="title", question_tr="Nedir?")
        assert r.all_names == ("title",)

    def test_with_alternatives(self):
        r = SlotRequirement(name="time", alternatives=("date", "window_hint"))
        assert r.all_names == ("time", "date", "window_hint")

    def test_frozen(self):
        r = SlotRequirement(name="x")
        with pytest.raises(AttributeError):
            r.name = "y"


# ─────────────────────────────────────────────────────────────────
# TOOL_REQUIRED_SLOTS constants
# ─────────────────────────────────────────────────────────────────


class TestToolRequiredSlots:

    def test_create_event_has_title(self):
        reqs = TOOL_REQUIRED_SLOTS["calendar.create_event"]
        names = [r.name for r in reqs]
        assert "title" in names

    def test_create_event_has_time(self):
        reqs = TOOL_REQUIRED_SLOTS["calendar.create_event"]
        names = [r.name for r in reqs]
        assert "time" in names

    def test_gmail_send_has_to(self):
        reqs = TOOL_REQUIRED_SLOTS["gmail.send"]
        names = [r.name for r in reqs]
        assert "to" in names

    def test_gmail_send_has_body(self):
        reqs = TOOL_REQUIRED_SLOTS["gmail.send"]
        names = [r.name for r in reqs]
        assert "body" in names

    def test_all_have_questions(self):
        for tool, reqs in TOOL_REQUIRED_SLOTS.items():
            for r in reqs:
                assert r.question_tr, f"{tool}.{r.name} has no question_tr"


# ─────────────────────────────────────────────────────────────────
# SlotValidationResult
# ─────────────────────────────────────────────────────────────────


class TestSlotValidationResult:

    def test_valid_to_dict(self):
        r = SlotValidationResult(tool_name="calendar.create_event", valid=True)
        d = r.to_dict()
        assert d["valid"] is True
        assert "missing_slots" not in d

    def test_invalid_to_dict(self):
        r = SlotValidationResult(
            tool_name="calendar.create_event",
            valid=False,
            missing_slots=["title"],
            question="Etkinlik adı ne olsun efendim?",
            ask_user=True,
        )
        d = r.to_dict()
        assert d["valid"] is False
        assert "title" in d["missing_slots"]
        assert d["ask_user"] is True
        assert "question" in d


# ─────────────────────────────────────────────────────────────────
# calendar.create_event validation
# ─────────────────────────────────────────────────────────────────


class TestCalendarCreateEvent:

    def test_valid_with_title_and_time(self):
        r = validate_tool_slots("calendar.create_event", {"title": "Toplantı", "time": "14:00"})
        assert r.valid
        assert not r.ask_user

    def test_valid_with_title_and_date(self):
        r = validate_tool_slots("calendar.create_event", {"title": "Toplantı", "date": "2025-01-15"})
        assert r.valid

    def test_valid_with_title_and_window_hint(self):
        r = validate_tool_slots("calendar.create_event", {"title": "Toplantı", "window_hint": "tomorrow"})
        assert r.valid

    def test_missing_title(self):
        r = validate_tool_slots("calendar.create_event", {"time": "14:00"})
        assert not r.valid
        assert "title" in r.missing_slots
        assert r.ask_user

    def test_missing_time_and_alternatives(self):
        r = validate_tool_slots("calendar.create_event", {"title": "Toplantı"})
        assert not r.valid
        assert "time" in r.missing_slots

    def test_missing_both(self):
        r = validate_tool_slots("calendar.create_event", {})
        assert not r.valid
        assert "title" in r.missing_slots
        assert "time" in r.missing_slots

    def test_empty_title_string(self):
        r = validate_tool_slots("calendar.create_event", {"title": "", "time": "14:00"})
        assert not r.valid
        assert "title" in r.missing_slots

    def test_whitespace_title(self):
        r = validate_tool_slots("calendar.create_event", {"title": "  ", "time": "14:00"})
        assert not r.valid
        assert "title" in r.missing_slots

    def test_none_title(self):
        r = validate_tool_slots("calendar.create_event", {"title": None, "time": "14:00"})
        assert not r.valid

    def test_question_is_turkish(self):
        r = validate_tool_slots("calendar.create_event", {})
        assert r.question is not None
        assert "efendim" in r.question.lower()

    def test_first_question_is_title(self):
        """When both title and time missing, first question should be about title."""
        r = validate_tool_slots("calendar.create_event", {})
        assert "adı" in (r.question or "").lower() or "etkinlik" in (r.question or "").lower()


# ─────────────────────────────────────────────────────────────────
# gmail.send validation
# ─────────────────────────────────────────────────────────────────


class TestGmailSend:

    def test_valid(self):
        r = validate_tool_slots("gmail.send", {"to": "ali@test.com", "body": "Merhaba"})
        assert r.valid

    def test_valid_with_recipient_alt(self):
        r = validate_tool_slots("gmail.send", {"recipient": "ali@test.com", "body": "Merhaba"})
        assert r.valid

    def test_valid_with_message_alt(self):
        r = validate_tool_slots("gmail.send", {"to": "ali@test.com", "message": "Merhaba"})
        assert r.valid

    def test_valid_with_content_alt(self):
        r = validate_tool_slots("gmail.send", {"to": "ali@test.com", "content": "Merhaba"})
        assert r.valid

    def test_missing_to(self):
        r = validate_tool_slots("gmail.send", {"body": "Merhaba"})
        assert not r.valid
        assert "to" in r.missing_slots

    def test_missing_body(self):
        r = validate_tool_slots("gmail.send", {"to": "ali@test.com"})
        assert not r.valid
        assert "body" in r.missing_slots

    def test_missing_both(self):
        r = validate_tool_slots("gmail.send", {})
        assert not r.valid
        assert len(r.missing_slots) == 2


# ─────────────────────────────────────────────────────────────────
# Unknown / no-requirement tools
# ─────────────────────────────────────────────────────────────────


class TestUnknownTools:

    def test_unknown_tool_always_valid(self):
        r = validate_tool_slots("some.unknown.tool", {})
        assert r.valid

    def test_list_events_no_requirements(self):
        r = validate_tool_slots("calendar.list_events", {})
        assert r.valid

    def test_time_now_no_requirements(self):
        r = validate_tool_slots("time.now", {})
        assert r.valid


# ─────────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────────


class TestConvenience:

    def test_get_clarification_question_missing(self):
        q = get_clarification_question("calendar.create_event", {})
        assert q is not None
        assert "efendim" in q.lower()

    def test_get_clarification_question_valid(self):
        q = get_clarification_question("calendar.create_event", {"title": "X", "time": "14:00"})
        assert q is None

    def test_get_clarification_question_unknown_tool(self):
        q = get_clarification_question("unknown.tool", {})
        assert q is None

    def test_get_required_slot_names(self):
        names = get_required_slot_names("calendar.create_event")
        assert "title" in names
        assert "time" in names

    def test_get_required_slot_names_unknown(self):
        names = get_required_slot_names("unknown.tool")
        assert names == []


# ─────────────────────────────────────────────────────────────────
# Custom required_slots override
# ─────────────────────────────────────────────────────────────────


class TestCustomSlots:

    def test_custom_required(self):
        custom = [SlotRequirement(name="custom_field", question_tr="Lütfen custom alanı giriniz?")]
        r = validate_tool_slots("any.tool", {}, required_slots=custom)
        assert not r.valid
        assert "custom_field" in r.missing_slots

    def test_custom_satisfied(self):
        custom = [SlotRequirement(name="custom_field", question_tr="?")]
        r = validate_tool_slots("any.tool", {"custom_field": "value"}, required_slots=custom)
        assert r.valid


# ─────────────────────────────────────────────────────────────────
# calendar.delete_event / update_event
# ─────────────────────────────────────────────────────────────────


class TestOtherCalendarTools:

    def test_delete_event_needs_identifier(self):
        r = validate_tool_slots("calendar.delete_event", {})
        assert not r.valid
        assert "title" in r.missing_slots

    def test_delete_event_with_title(self):
        r = validate_tool_slots("calendar.delete_event", {"title": "Toplantı"})
        assert r.valid

    def test_delete_event_with_event_id(self):
        r = validate_tool_slots("calendar.delete_event", {"event_id": "abc123"})
        assert r.valid

    def test_delete_event_with_query(self):
        r = validate_tool_slots("calendar.delete_event", {"query": "toplantı"})
        assert r.valid

    def test_update_event_needs_identifier(self):
        r = validate_tool_slots("calendar.update_event", {})
        assert not r.valid

    def test_update_event_with_title(self):
        r = validate_tool_slots("calendar.update_event", {"title": "Toplantı"})
        assert r.valid
