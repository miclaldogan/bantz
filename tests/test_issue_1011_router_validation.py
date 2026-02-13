"""Tests for Issue #1011: Complete router_validation repair coverage.

1. repaired.update(parsed) no longer overwrites defaults with invalid values
2. ask_user, question, requires_confirmation, gmail are repaired
3. gmail_intent fuzzy repair works
4. assistant_reply non-string repair
"""

import pytest

from bantz.brain.router_validation import (
    repair_router_output,
    validate_router_output,
    _repair_ask_user,
    _repair_question,
    _repair_requires_confirmation,
    _repair_gmail,
    _repair_assistant_reply,
    _repair_gmail_intent,
)


def _base_valid():
    return {
        "route": "gmail",
        "calendar_intent": "none",
        "confidence": 0.8,
        "tool_plan": [],
        "assistant_reply": "tamam",
    }


class TestRepairUpdateOverwrite:
    """Issue #1011: invalid parsed values must NOT overwrite defaults."""

    def test_invalid_ask_user_not_propagated(self):
        parsed = _base_valid()
        parsed["ask_user"] = "maybe"  # Invalid — should be bool
        repaired, report = repair_router_output(parsed)
        assert isinstance(repaired["ask_user"], bool)

    def test_invalid_question_not_propagated(self):
        parsed = _base_valid()
        parsed["question"] = 12345  # Invalid — should be str
        repaired, report = repair_router_output(parsed)
        assert isinstance(repaired["question"], str)

    def test_invalid_requires_confirmation_not_propagated(self):
        parsed = _base_valid()
        parsed["requires_confirmation"] = "yes"  # Invalid — should be bool
        repaired, report = repair_router_output(parsed)
        assert repaired["requires_confirmation"] is True  # "yes" → True

    def test_invalid_gmail_not_propagated(self):
        parsed = _base_valid()
        parsed["gmail"] = "not a dict"
        repaired, report = repair_router_output(parsed)
        assert isinstance(repaired["gmail"], dict)

    def test_valid_fields_preserved(self):
        parsed = _base_valid()
        parsed["gmail_intent"] = "send"
        repaired, _ = repair_router_output(parsed)
        assert repaired["route"] == "gmail"
        assert repaired["confidence"] == 0.8
        assert repaired["gmail_intent"] == "send"


class TestGmailIntentRepair:
    """gmail_intent fuzzy repair."""

    def test_valid_intent_preserved(self):
        assert _repair_gmail_intent("send") == "send"

    def test_fuzzy_match(self):
        result = _repair_gmail_intent("sned")  # Typo
        assert result == "send"

    def test_invalid_falls_to_none(self):
        assert _repair_gmail_intent("xyz_invalid") == "none"

    def test_non_string_falls_to_none(self):
        assert _repair_gmail_intent(42) == "none"


class TestAssistantReplyRepair:
    """assistant_reply coercion."""

    def test_string_passthrough(self):
        assert _repair_assistant_reply("merhaba") == "merhaba"

    def test_none_to_empty(self):
        assert _repair_assistant_reply(None) == ""

    def test_int_to_string(self):
        assert _repair_assistant_reply(123) == "123"


class TestAskUserRepair:
    def test_bool_passthrough(self):
        assert _repair_ask_user(True) is True

    def test_string_true(self):
        assert _repair_ask_user("true") is True

    def test_string_evet(self):
        assert _repair_ask_user("evet") is True

    def test_string_false(self):
        assert _repair_ask_user("false") is False

    def test_int_one(self):
        assert _repair_ask_user(1) is True


class TestRequiresConfirmationRepair:
    def test_bool_passthrough(self):
        assert _repair_requires_confirmation(False) is False

    def test_string_yes(self):
        assert _repair_requires_confirmation("yes") is True

    def test_none_to_false(self):
        assert _repair_requires_confirmation(None) is False


class TestGmailRepair:
    def test_dict_passthrough(self):
        assert _repair_gmail({"to": "a@b.com"}) == {"to": "a@b.com"}

    def test_non_dict_to_empty(self):
        assert _repair_gmail("not a dict") == {}

    def test_none_to_empty(self):
        assert _repair_gmail(None) == {}


class TestFullRepairPipeline:
    """End-to-end repair with multiple invalid fields."""

    def test_multiple_invalid_fields(self):
        parsed = {
            "route": "calender",       # Typo → "calendar"
            "calendar_intent": "none",
            "confidence": "high",       # Not a number → 0.0
            "tool_plan": "calendar.list",  # String → list
            "assistant_reply": None,    # None → ""
            "gmail_intent": "sned",     # Typo → "send"
            "ask_user": "true",         # String → True
            "question": 42,             # Int → "42"
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["route"] == "calendar"
        assert repaired["confidence"] == 0.0
        assert repaired["tool_plan"] == ["calendar.list"]
        assert repaired["assistant_reply"] == ""
        assert repaired["gmail_intent"] == "send"
        assert repaired["ask_user"] is True
        assert repaired["question"] == "42"
        assert report.needed_repair is True
        assert len(report.fields_repaired) >= 5
