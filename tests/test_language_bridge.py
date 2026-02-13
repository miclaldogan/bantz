"""Tests for LanguageBridge — TR↔EN translation layer (Issue #1245).

Tests are structured to work both with and without MarianMT models.
When models are not available, translation tests are skipped (detect
and bypass tests always run).
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch

from bantz.brain.language_bridge import BridgeResult, LanguageBridge, get_bridge


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def bridge():
    """Create a fresh LanguageBridge instance."""
    return LanguageBridge()


@pytest.fixture
def bridge_result_factory():
    """Factory for creating BridgeResult instances."""
    def _make(**kwargs):
        defaults = {
            "canonical": "",
            "detected_lang": "unknown",
            "protected_spans": (),
            "original": "",
        }
        defaults.update(kwargs)
        return BridgeResult(**defaults)
    return _make


# ============================================================================
# Language Detection
# ============================================================================


class TestLanguageDetection:
    """Test detect() — lightweight heuristic language detection."""

    def test_detect_turkish_with_special_chars(self, bridge):
        assert bridge.detect("yarın kahvaltı var mı") == "tr"

    def test_detect_turkish_common_words(self, bridge):
        assert bridge.detect("maillerimi listele") == "tr"

    def test_detect_turkish_greeting(self, bridge):
        assert bridge.detect("nasılsın dostum") == "tr"

    def test_detect_english_sentence(self, bridge):
        assert bridge.detect("check my calendar") == "en"

    def test_detect_english_greeting(self, bridge):
        assert bridge.detect("hey bud how are you") == "en"

    def test_detect_mixed_turkish_context(self, bridge):
        """Turkish chars are a strong signal even with English words."""
        assert bridge.detect("TÜBİTAK'tan gelen mail") == "tr"

    def test_detect_empty_string(self, bridge):
        assert bridge.detect("") == "unknown"

    def test_detect_single_char(self, bridge):
        assert bridge.detect("a") == "unknown"

    def test_detect_affirmative_turkish(self, bridge):
        assert bridge.detect("evet lütfen") == "tr"

    def test_detect_affirmative_english(self, bridge):
        assert bridge.detect("yes please") == "en"


# ============================================================================
# CLI Command Bypass
# ============================================================================


class TestCLIBypass:
    """Test that CLI commands are never translated."""

    @pytest.mark.parametrize("cmd", [
        "exit", "quit", "clear", "help", "status",
        "history", "reset", "config", "version",
    ])
    def test_exact_cli_commands_bypass(self, bridge, cmd):
        result = bridge.to_en(cmd)
        assert result.canonical == cmd
        assert result.original == cmd

    @pytest.mark.parametrize("cmd", [
        "agent: YouTube'a git",
        "agent: Coldplay ara",
        "agent search for hotels",
    ])
    def test_cli_prefixes_bypass(self, bridge, cmd):
        result = bridge.to_en(cmd)
        assert result.canonical == cmd

    def test_empty_string_bypass(self, bridge):
        result = bridge.to_en("")
        assert result.canonical == ""
        assert result.detected_lang == "unknown"

    def test_whitespace_only_bypass(self, bridge):
        result = bridge.to_en("   ")
        assert result.canonical == ""


# ============================================================================
# English Input Passthrough
# ============================================================================


class TestEnglishPassthrough:
    """Test that English input passes through without translation."""

    def test_english_passes_through(self, bridge):
        result = bridge.to_en("check my calendar for tomorrow")
        assert result.detected_lang == "en"
        assert result.canonical == "check my calendar for tomorrow"
        assert result.protected_spans == ()

    def test_english_greeting_passes_through(self, bridge):
        result = bridge.to_en("hello how are you")
        assert result.detected_lang == "en"
        assert result.canonical == "hello how are you"


# ============================================================================
# Protected Spans
# ============================================================================


class TestProtectedSpans:
    """Test entity protection from translation."""

    def test_json_block_protected(self, bridge):
        text = 'process {"route": "gmail"} now'
        clean, protected = bridge._extract_protected_spans(text)
        assert '{"route": "gmail"}' in protected.values()
        assert '{"route": "gmail"}' not in clean

    def test_email_address_protected(self, bridge):
        text = "user@example.com adresine mail at"
        clean, protected = bridge._extract_protected_spans(text)
        assert "user@example.com" in protected.values()

    def test_quoted_string_protected(self, bridge):
        text = 'mail konusu "proje raporu" olan'
        clean, protected = bridge._extract_protected_spans(text)
        assert '"proje raporu"' in protected.values()

    def test_acronym_protected(self, bridge):
        """All-caps acronyms (2+ chars) should be protected."""
        text = "TÜBİTAK programına başvur"
        clean, protected = bridge._extract_protected_spans(text)
        assert "TÜBİTAK" in protected.values()

    def test_restore_protected_spans(self, bridge):
        protected = {"<PROT_0>": "TÜBİTAK", "<PROT_1>": "user@test.com"}
        text = "Check <PROT_0> email from <PROT_1>"
        restored = bridge._restore_protected_spans(text, protected)
        assert "TÜBİTAK" in restored
        assert "user@test.com" in restored
        assert "<PROT_" not in restored


# ============================================================================
# Translation (requires MarianMT models)
# ============================================================================


def _has_translation_models():
    """Check if MarianMT models are available."""
    try:
        b = LanguageBridge()
        return b.available
    except Exception:
        return False


_skip_no_models = pytest.mark.skipif(
    not _has_translation_models(),
    reason="MarianMT models not available (transformers/sentencepiece not installed)",
)


@_skip_no_models
class TestTranslationTRtoEN:
    """Test TR→EN translation quality."""

    def test_calendar_intent(self, bridge):
        result = bridge.to_en("yarın takvimime bak")
        canonical = result.canonical.lower()
        assert any(w in canonical for w in ["calendar", "schedule", "tomorrow", "look"])

    def test_gmail_intent(self, bridge):
        result = bridge.to_en("maillerimi listele")
        canonical = result.canonical.lower()
        assert any(w in canonical for w in ["mail", "email", "list", "inbox"])

    def test_followup_affirmative(self, bridge):
        result = bridge.to_en("evet lütfen")
        canonical = result.canonical.lower()
        assert any(w in canonical for w in ["yes", "please"])

    def test_entity_preserved_after_translation(self, bridge):
        result = bridge.to_en("TÜBİTAK'tan gelen maili aç")
        assert "TÜBİTAK" in result.canonical or "TÜBİTAK" in result.protected_spans

    def test_detected_lang_is_tr(self, bridge):
        result = bridge.to_en("yarın kahvaltı ekle")
        assert result.detected_lang == "tr"

    def test_original_preserved(self, bridge):
        original = "yarın takvimime bak"
        result = bridge.to_en(original)
        assert result.original == original


@_skip_no_models
class TestTranslationENtoTR:
    """Test EN→TR translation quality."""

    def test_calendar_response(self, bridge):
        result = bridge.to_tr("Your calendar has 3 events tomorrow.")
        # Should contain Turkish text
        assert result != "Your calendar has 3 events tomorrow."
        assert len(result) > 5

    def test_already_turkish_passthrough(self, bridge):
        tr_text = "Takviminde 3 etkinlik var."
        result = bridge.to_tr(tr_text)
        assert result == tr_text

    def test_empty_passthrough(self, bridge):
        assert bridge.to_tr("") == ""
        assert bridge.to_tr("  ") == "  "


# ============================================================================
# Cache
# ============================================================================


@_skip_no_models
class TestCache:
    """Test translation cache behavior."""

    def test_cache_hit(self, bridge):
        """Second translation should come from cache."""
        result1 = bridge.to_en("yarın takvimime bak")
        result2 = bridge.to_en("yarın takvimime bak")
        assert result1.canonical == result2.canonical
        # Cache should have one entry
        assert "yarın takvimime bak" in bridge._cache_tr_en


# ============================================================================
# BridgeResult
# ============================================================================


class TestBridgeResult:
    """Test BridgeResult dataclass."""

    def test_frozen(self):
        r = BridgeResult(canonical="hello", detected_lang="en", original="merhaba")
        with pytest.raises(AttributeError):
            r.canonical = "changed"  # type: ignore

    def test_default_protected_spans(self):
        r = BridgeResult(canonical="hello", detected_lang="en")
        assert r.protected_spans == ()

    def test_slots(self):
        r = BridgeResult(
            canonical="hello",
            detected_lang="en",
            protected_spans=("TÜBİTAK",),
            original="merhaba TÜBİTAK",
        )
        assert r.protected_spans == ("TÜBİTAK",)


# ============================================================================
# get_bridge() singleton
# ============================================================================


class TestGetBridge:
    """Test get_bridge() singleton accessor."""

    def test_disabled_returns_none(self):
        import bantz.brain.language_bridge as lb
        lb._bridge_instance = None  # reset singleton
        with patch.dict("os.environ", {"BANTZ_BRIDGE_ENABLED": "0"}):
            result = get_bridge()
            assert result is None
        lb._bridge_instance = None  # cleanup

    def test_enabled_returns_bridge(self):
        import bantz.brain.language_bridge as lb
        lb._bridge_instance = None  # reset singleton
        with patch.dict("os.environ", {"BANTZ_BRIDGE_ENABLED": "1"}):
            result = get_bridge()
            if result is not None:
                assert isinstance(result, LanguageBridge)
        lb._bridge_instance = None  # cleanup


# ============================================================================
# Tool param bridge (Issue #1244)
# ============================================================================


class TestToolParamBridge:
    """Test content param restoration from original TR input."""

    def test_calendar_title_restored_from_tr(self):
        from bantz.brain.tool_param_builder import build_tool_params

        params = build_tool_params(
            "calendar.create_event",
            {"title": "breakfast", "date": "2026-02-14"},
            user_input="add breakfast tomorrow",
            original_user_input="yarın kahvaltı ekle",
        )
        assert params["title"] == "kahvaltı"

    def test_calendar_title_not_touched_without_bridge(self):
        from bantz.brain.tool_param_builder import build_tool_params

        params = build_tool_params(
            "calendar.create_event",
            {"title": "kahvaltı", "date": "2026-02-14"},
            user_input="yarın kahvaltı ekle",
        )
        assert params["title"] == "kahvaltı"

    def test_meeting_title_restored(self):
        from bantz.brain.tool_param_builder import build_tool_params

        params = build_tool_params(
            "calendar.create_event",
            {"title": "meeting", "date": "2026-02-14"},
            user_input="add meeting tomorrow at 3pm",
            original_user_input="yarın saat 15 toplantı ekle",
        )
        assert params["title"] == "toplantı"

    def test_gmail_params_unaffected(self):
        from bantz.brain.tool_param_builder import build_tool_params

        params = build_tool_params(
            "gmail.list_messages",
            {"query": ""},
            user_input="list my emails",
            original_user_input="maillerimi listele",
        )
        # Gmail params should not be affected by bridge
        assert "title" not in params


# ============================================================================
# Input Gate integration (Issue #1242)
# ============================================================================


class TestInputGateState:
    """Test that Input Gate properly sets state fields."""

    def test_state_fields_exist(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        assert hasattr(state, "detected_lang")
        assert hasattr(state, "canonical_input")
        assert state.detected_lang == ""
        assert state.canonical_input == ""

    def test_state_reset_clears_bridge_fields(self):
        from bantz.brain.orchestrator_state import OrchestratorState
        state = OrchestratorState()
        state.detected_lang = "tr"
        state.canonical_input = "look at my calendar"
        state.reset()
        assert state.detected_lang == ""
        assert state.canonical_input == ""
