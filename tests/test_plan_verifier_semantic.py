"""Tests for plan_verifier semantic checks (Issue #1002).

Tests cover:
- Smalltalk route with non-time tools
- Calendar write without temporal slots
- Route↔intent mismatch detection
- Existing syntactic checks still work
"""

import pytest

from bantz.brain.plan_verifier import verify_plan


VALID_TOOLS = frozenset({
    "calendar.list_events",
    "calendar.create_event",
    "calendar.delete_event",
    "calendar.update_event",
    "gmail.list",
    "gmail.send",
    "gmail.read",
    "time.now",
    "system.status",
    "contacts.lookup",
})


class TestSemanticSmalltalkWithTools:
    """Issue #1002: Smalltalk route should not have non-time tools."""

    def test_smalltalk_with_calendar_tool_flagged(self):
        plan = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "İşte etkinlikleriniz",
        }
        ok, errors = verify_plan(plan, "merhaba", VALID_TOOLS)
        assert not ok
        assert any("smalltalk_with_tools" in e for e in errors)

    def test_smalltalk_with_time_tool_ok(self):
        plan = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.9,
            "tool_plan": ["time.now"],
            "assistant_reply": "Saat 14:30",
        }
        ok, errors = verify_plan(plan, "saat kaç", VALID_TOOLS)
        # time.now is allowed for smalltalk
        assert "smalltalk_with_tools" not in errors

    def test_smalltalk_no_tools_ok(self):
        plan = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "Merhaba!",
        }
        ok, errors = verify_plan(plan, "merhaba", VALID_TOOLS)
        assert ok


class TestSemanticCalendarWriteNoTemporal:
    """Issue #1002: Calendar write intents need date/time slots."""

    def test_create_without_date_flagged(self):
        plan = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.8,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "Etkinlik oluşturuldu",
            "slots": {"title": "Toplantı"},
        }
        ok, errors = verify_plan(plan, "toplantı oluştur", VALID_TOOLS)
        assert any("calendar_write_no_temporal" in e for e in errors)

    def test_create_with_date_ok(self):
        plan = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.8,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "Etkinlik oluşturuldu",
            "slots": {"title": "Toplantı", "date": "2026-02-13"},
        }
        ok, errors = verify_plan(plan, "yarın toplantı oluştur", VALID_TOOLS)
        assert "calendar_write_no_temporal" not in errors

    def test_query_without_date_ok(self):
        """Query intent doesn't need date — it can list all."""
        plan = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.8,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "Etkinlikler listeleniyor",
            "slots": {},
        }
        ok, errors = verify_plan(plan, "etkinliklerimi göster", VALID_TOOLS)
        assert "calendar_write_no_temporal" not in errors


class TestSemanticRouteIntentMismatch:
    """Issue #1002: Route and intent should be coherent."""

    def test_gmail_with_calendar_intent_flagged(self):
        plan = {
            "route": "gmail",
            "calendar_intent": "create",
            "confidence": 0.7,
            "tool_plan": ["gmail.send"],
            "assistant_reply": "Mail gönderiliyor",
            "gmail_intent": "send",
            "gmail": {"to": "test@test.com"},
        }
        ok, errors = verify_plan(plan, "mail gönder", VALID_TOOLS)
        assert any("route_intent_mismatch" in e for e in errors)

    def test_calendar_with_gmail_intent_flagged(self):
        plan = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.8,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "Etkinlikler",
            "gmail_intent": "send",
        }
        ok, errors = verify_plan(plan, "takvimimi göster", VALID_TOOLS)
        assert any("route_intent_mismatch" in e for e in errors)

    def test_matching_route_intent_ok(self):
        plan = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "İşte etkinlikleriniz",
        }
        ok, errors = verify_plan(plan, "takvimimi göster", VALID_TOOLS)
        assert "route_intent_mismatch" not in str(errors)


class TestExistingSyntacticChecks:
    """Ensure existing checks still work after semantic additions."""

    def test_unknown_tool_detected(self):
        plan = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.9,
            "tool_plan": ["calendar.nonexistent"],
            "assistant_reply": "test",
        }
        ok, errors = verify_plan(plan, "takvim göster", VALID_TOOLS)
        assert not ok
        assert any("unknown_tool" in e for e in errors)

    def test_valid_plan_passes(self):
        plan = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "İşte etkinlikleriniz",
            "slots": {"window_hint": "today"},
        }
        ok, errors = verify_plan(plan, "bugün takvim göster", VALID_TOOLS)
        assert ok
        assert errors == []
