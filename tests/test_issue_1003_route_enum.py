"""Tests for Issue #1003: Route Enum Mismatch fix.

Verifies:
1. VALID_ROUTES includes wiki, chat (sync with prompt_engineering.py)
2. VALID_CALENDAR_INTENTS includes 'delete'
3. VALID_GMAIL_INTENTS includes reply, forward, delete, mark_read
4. gmail_intent is repaired in repair_router_output()
5. json_protocol route enum is synced
"""

import pytest

from bantz.brain.router_validation import (
    VALID_ROUTES,
    VALID_CALENDAR_INTENTS,
    VALID_GMAIL_INTENTS,
    validate_router_output,
    repair_router_output,
)
from bantz.brain.json_protocol import validate_orchestrator_output


class TestExpandedRouteEnum:
    """VALID_ROUTES now includes wiki and chat."""

    def test_wiki_is_valid_route(self):
        assert "wiki" in VALID_ROUTES

    def test_chat_is_valid_route(self):
        assert "chat" in VALID_ROUTES

    def test_wiki_passes_validation(self):
        data = {
            "route": "wiki",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, _ = validate_router_output(data)
        assert is_valid

    def test_chat_passes_validation(self):
        data = {
            "route": "chat",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, _ = validate_router_output(data)
        assert is_valid

    def test_wiki_not_repaired_to_unknown(self):
        """wiki should NOT be fuzzy-corrected to unknown anymore."""
        data = {
            "route": "wiki",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(data)
        assert repaired["route"] == "wiki"
        assert report.is_valid_before is True


class TestExpandedCalendarIntents:
    """VALID_CALENDAR_INTENTS now includes 'delete'."""

    def test_delete_is_valid(self):
        assert "delete" in VALID_CALENDAR_INTENTS

    def test_delete_passes_validation(self):
        data = {
            "route": "calendar",
            "calendar_intent": "delete",
            "confidence": 0.9,
            "tool_plan": ["calendar.delete_event"],
            "assistant_reply": "Siliniyor.",
        }
        is_valid, _ = validate_router_output(data)
        assert is_valid


class TestExpandedGmailIntents:
    """VALID_GMAIL_INTENTS now includes reply, forward, delete, mark_read."""

    @pytest.mark.parametrize("intent", ["reply", "forward", "delete", "mark_read"])
    def test_new_intent_valid(self, intent):
        assert intent in VALID_GMAIL_INTENTS

    def test_reply_passes_validation(self):
        data = {
            "route": "gmail",
            "calendar_intent": "none",
            "confidence": 0.9,
            "tool_plan": ["gmail.reply"],
            "assistant_reply": "Yanıtlanıyor.",
            "gmail_intent": "reply",
        }
        is_valid, _ = validate_router_output(data)
        assert is_valid


class TestGmailIntentRepair:
    """gmail_intent is now repaired (was silently ignored before)."""

    def test_typo_repaired(self):
        data = {
            "route": "gmail",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "",
            "gmail_intent": "replly",  # typo
        }
        repaired, report = repair_router_output(data)
        assert repaired["gmail_intent"] == "reply"
        assert "gmail_intent" in report.fields_repaired

    def test_unknown_gmail_intent_falls_to_none(self):
        data = {
            "route": "gmail",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "",
            "gmail_intent": "xyz_unknown",
        }
        repaired, report = repair_router_output(data)
        assert repaired["gmail_intent"] == "none"

    def test_valid_gmail_intent_not_touched(self):
        data = {
            "route": "gmail",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "",
            "gmail_intent": "send",
        }
        repaired, report = repair_router_output(data)
        assert repaired["gmail_intent"] == "send"
        assert report.is_valid_before is True


class TestJsonProtocolSync:
    """json_protocol route validation is also synced."""

    def test_wiki_route_valid_in_orchestrator(self):
        data = {
            "route": "wiki",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, errors = validate_orchestrator_output(data)
        assert is_valid, f"Errors: {errors}"

    def test_chat_route_valid_in_orchestrator(self):
        data = {
            "route": "chat",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, errors = validate_orchestrator_output(data)
        assert is_valid, f"Errors: {errors}"
