"""Tests for Issue #441 — User Preferences Learning Integration.

Covers:
- Correction recording and application
- Choice recording
- Cancellation tracking
- Tool usage frequency
- Prompt context generation
- Adaptive defaults with session overrides
- Session reset
"""

from __future__ import annotations

import pytest

from bantz.learning.preference_integration import (
    PreferenceIntegration,
    SessionPreferences,
    UserPreference,
    _TOOL_DEFAULTS,
)


# ─── UserPreference ─────────────────────────────────────────────


class TestUserPreference:
    def test_to_dict(self):
        p = UserPreference(key="lang", value="tr", confidence=0.9, source="explicit")
        d = p.to_dict()
        assert d["key"] == "lang"
        assert d["value"] == "tr"
        assert d["confidence"] == 0.9

    def test_default_values(self):
        p = UserPreference(key="test", value=42)
        assert p.confidence == 0.5
        assert p.source == "inferred"


# ─── SessionPreferences ─────────────────────────────────────────


class TestSessionPreferences:
    def test_get_set(self):
        sp = SessionPreferences()
        sp.set("color", "blue", confidence=0.7)
        pref = sp.get("color")
        assert pref is not None
        assert pref.value == "blue"
        assert pref.confidence == 0.7

    def test_get_missing(self):
        sp = SessionPreferences()
        assert sp.get("missing") is None

    def test_to_dict(self):
        sp = SessionPreferences()
        sp.set("x", 1)
        sp.turn_count = 5
        d = sp.to_dict()
        assert d["turn_count"] == 5
        assert "x" in d["preferences"]


# ─── Corrections ─────────────────────────────────────────────────


class TestCorrections:
    def test_record_correction(self):
        pi = PreferenceIntegration()
        pi.record_correction("toplantı", "buluşma")
        assert len(pi.session.corrections) == 1
        assert pi.session.corrections[0]["original"] == "toplantı"
        assert pi.session.corrections[0]["corrected"] == "buluşma"

    def test_correction_stored_as_preference(self):
        pi = PreferenceIntegration()
        pi.record_correction("Ali", "Ahmet")
        pref = pi.session.get("correction:Ali")
        assert pref is not None
        assert pref.value == "Ahmet"
        assert pref.source == "explicit"

    def test_apply_corrections(self):
        pi = PreferenceIntegration()
        pi.record_correction("toplantı", "buluşma")
        result = pi.apply_corrections("Yarın toplantı var")
        assert result == "Yarın buluşma var"

    def test_apply_no_corrections(self):
        pi = PreferenceIntegration()
        result = pi.apply_corrections("Merhaba dünya")
        assert result == "Merhaba dünya"

    def test_multiple_corrections(self):
        pi = PreferenceIntegration()
        pi.record_correction("Ali", "Ahmet")
        pi.record_correction("toplantı", "görüşme")
        result = pi.apply_corrections("Ali ile toplantı")
        assert result == "Ahmet ile görüşme"


# ─── Choices ─────────────────────────────────────────────────────


class TestChoices:
    def test_record_choice(self):
        pi = PreferenceIntegration()
        pi.record_choice("email_format", "formal")
        pref = pi.session.get("email_format")
        assert pref is not None
        assert pref.value == "formal"
        assert pref.source == "explicit"

    def test_choice_overrides(self):
        pi = PreferenceIntegration()
        pi.record_choice("theme", "dark")
        pi.record_choice("theme", "light")
        assert pi.session.get("theme").value == "light"


# ─── Cancellations ──────────────────────────────────────────────


class TestCancellations:
    def test_record_cancellation(self):
        pi = PreferenceIntegration()
        pi.record_cancellation("calendar_create_event")
        pref = pi.session.get("cancel:calendar_create_event")
        assert pref is not None
        assert pref.value == 1

    def test_cancellation_count_increases(self):
        pi = PreferenceIntegration()
        pi.record_cancellation("calendar_create_event")
        pi.record_cancellation("calendar_create_event")
        pi.record_cancellation("calendar_create_event")
        pref = pi.session.get("cancel:calendar_create_event")
        assert pref.value == 3
        # Confidence should increase
        assert pref.confidence > 0.5


# ─── Tool usage ──────────────────────────────────────────────────


class TestToolUsage:
    def test_record_tool_usage(self):
        pi = PreferenceIntegration()
        pi.record_tool_usage("calendar_list_events")
        pi.record_tool_usage("calendar_list_events")
        pi.record_tool_usage("gmail_send")
        assert pi.session.tool_usage_counts["calendar_list_events"] == 2
        assert pi.session.tool_usage_counts["gmail_send"] == 1

    def test_turn_counting(self):
        pi = PreferenceIntegration()
        pi.record_turn()
        pi.record_turn()
        assert pi.session.turn_count == 2


# ─── Prompt context ─────────────────────────────────────────────


class TestPromptContext:
    def test_empty_context(self):
        pi = PreferenceIntegration()
        ctx = pi.get_prompt_context()
        assert ctx == ""

    def test_with_tools(self):
        pi = PreferenceIntegration()
        pi.record_tool_usage("calendar_list_events")
        pi.record_tool_usage("calendar_list_events")
        ctx = pi.get_prompt_context()
        assert "calendar_list_events" in ctx
        assert "Sık kullanılan" in ctx

    def test_with_corrections(self):
        pi = PreferenceIntegration()
        pi.record_correction("Ali", "Ahmet")
        ctx = pi.get_prompt_context()
        assert "Düzeltmeler" in ctx
        assert "Ali→Ahmet" in ctx

    def test_with_explicit_preferences(self):
        pi = PreferenceIntegration()
        pi.record_choice("email_format", "formal")
        ctx = pi.get_prompt_context()
        assert "email_format" in ctx
        assert "formal" in ctx
        assert "Kullanıcı tercihleri" in ctx


# ─── Adaptive defaults ──────────────────────────────────────────


class TestAdaptiveDefaults:
    def test_base_defaults(self):
        pi = PreferenceIntegration()
        defaults = pi.get_tool_defaults("calendar_create_event")
        assert defaults["duration_minutes"] == 60
        assert defaults["reminder_minutes"] == 15

    def test_unknown_tool_empty_defaults(self):
        pi = PreferenceIntegration()
        defaults = pi.get_tool_defaults("unknown_tool")
        assert defaults == {}

    def test_session_override(self):
        pi = PreferenceIntegration()
        pi.session.set("calendar_create_event:duration_minutes", 30, confidence=0.8)
        defaults = pi.get_tool_defaults("calendar_create_event")
        assert defaults["duration_minutes"] == 30

    def test_low_confidence_not_applied(self):
        pi = PreferenceIntegration()
        pi.session.set("calendar_create_event:duration_minutes", 30, confidence=0.3)
        defaults = pi.get_tool_defaults("calendar_create_event")
        assert defaults["duration_minutes"] == 60  # base default kept


# ─── Session management ─────────────────────────────────────────


class TestSessionManagement:
    def test_reset_session(self):
        pi = PreferenceIntegration()
        pi.record_correction("a", "b")
        pi.record_tool_usage("test")
        pi.record_turn()
        pi.reset_session()
        assert pi.session.turn_count == 0
        assert len(pi.session.corrections) == 0
        assert len(pi.session.tool_usage_counts) == 0

    def test_session_summary(self):
        pi = PreferenceIntegration()
        pi.record_turn()
        pi.record_tool_usage("calendar")
        summary = pi.get_session_summary()
        assert summary["turn_count"] == 1
        assert "calendar" in summary["tool_usage"]

    def test_user_id(self):
        pi = PreferenceIntegration(user_id="test_user")
        assert pi.user_id == "test_user"
