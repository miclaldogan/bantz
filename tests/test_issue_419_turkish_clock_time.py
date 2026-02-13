"""Tests for Issue #419: Turkish Clock-Time Rule-Based Parsing.

Tests parse_hhmm_turkish() and post_process_slot_time() — deterministic
Turkish word-based clock-time parsing with PM default for hours 1–6.
"""

from __future__ import annotations

import pytest
from bantz.brain.turkish_clock import (
    parse_hhmm_turkish,
    post_process_slot_time,
    _apply_pm_default,
    _extract_hour_from_tokens,
    _TR_HOUR_WORDS,
)


# ============================================================================
# PM Default Rule (_apply_pm_default)
# ============================================================================

class TestApplyPMDefault:
    """Test the PM default logic for hours 1-6."""

    @pytest.mark.parametrize("hour,text,expected", [
        # Hours 1-6 without AM/PM marker → PM (+12)
        (1, "bire gel", 13),
        (2, "ikide buluş", 14),
        (3, "üçe kadar", 15),
        (4, "dörtte gel", 16),
        (5, "beşe toplantı", 17),
        (6, "altıda yemek", 18),
    ])
    def test_pm_default_hours_1_6(self, hour, text, expected):
        assert _apply_pm_default(hour, text) == expected

    @pytest.mark.parametrize("hour,text,expected", [
        # Hours 1-6 with "sabah" → AM (keep as-is)
        (5, "sabah beşte koşu", 5),
        (6, "sabah altıda kalk", 6),
        (3, "sabah üçte", 3),
        (1, "sabah birde", 1),
    ])
    def test_am_explicit_sabah(self, hour, text, expected):
        assert _apply_pm_default(hour, text) == expected

    @pytest.mark.parametrize("hour,text,expected", [
        # Hours 1-6 with "akşam" → PM
        (5, "akşam beşte yemek", 17),
        (6, "akşam altıda", 18),
    ])
    def test_pm_explicit_aksam(self, hour, text, expected):
        assert _apply_pm_default(hour, text) == expected

    @pytest.mark.parametrize("hour,text,expected", [
        # Hours 7-12: no default shift
        (7, "yedide gel", 7),
        (8, "sekizde başla", 8),
        (9, "dokuzda toplantı", 9),
        (10, "onda ara ver", 10),
        (11, "onbirde yemek", 11),
        (12, "onikide öğle", 12),
    ])
    def test_no_shift_hours_7_12(self, hour, text, expected):
        assert _apply_pm_default(hour, text) == expected

    @pytest.mark.parametrize("hour,text,expected", [
        # Already 24h → no shift
        (17, "17:00", 17),
        (23, "23:00", 23),
        (13, "13:00", 13),
    ])
    def test_already_24h(self, hour, text, expected):
        assert _apply_pm_default(hour, text) == expected

    def test_gece_is_pm_marker(self):
        """'gece' should act as PM marker."""
        assert _apply_pm_default(1, "gece birde") == 13
        assert _apply_pm_default(2, "gece ikide") == 14


# ============================================================================
# Token Hour Extraction (_extract_hour_from_tokens)
# ============================================================================

class TestExtractHourFromTokens:
    """Test token scanning for Turkish hour words."""

    @pytest.mark.parametrize("text,expected", [
        ("beşe toplantı", 5),
        ("altıda buluş", 6),
        ("üçte biter", 3),
        ("dörde randevu", 4),
        ("bire gel", 1),
        ("ikide başla", 2),
        ("yedide gel", 7),
        ("sekizde başla", 8),
        ("dokuzda toplantı", 9),
        ("onda ara", 10),
    ])
    def test_suffixed_words(self, text, expected):
        assert _extract_hour_from_tokens(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("on bir", 11),
        ("on iki", 12),
        ("on birde", 11),
        ("on ikide", 12),
    ])
    def test_bigram_hours(self, text, expected):
        assert _extract_hour_from_tokens(text) == expected

    def test_context_words_skipped(self):
        """Context words like 'sabah', 'akşam' should not be matched as hours."""
        # "sabah" alone should NOT return a value
        assert _extract_hour_from_tokens("sabah") is None
        assert _extract_hour_from_tokens("akşam") is None
        assert _extract_hour_from_tokens("saat") is None

    def test_no_match(self):
        assert _extract_hour_from_tokens("bugün hava güzel") is None
        assert _extract_hour_from_tokens("") is None


# ============================================================================
# Main Parser (parse_hhmm_turkish)
# ============================================================================

class TestParseHhmmTurkish:
    """Test the main parse_hhmm_turkish function."""

    # ── PM Default cases (hours 1-6 without sabah) ────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("beşe toplantı", "17:00"),
        ("beşte buluşalım", "17:00"),
        ("altıya kadar", "18:00"),
        ("altıda buluş", "18:00"),
        ("dörde randevu", "16:00"),
        ("dörtte gel", "16:00"),
        ("üçe kadar", "15:00"),
        ("üçte biter", "15:00"),
        ("ikiye hazır ol", "14:00"),
        ("ikide başla", "14:00"),
        ("bire gel", "13:00"),
        ("birde toplantı", "13:00"),
    ])
    def test_pm_default_word(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── "saat X" prefix ───────────────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("saat beş", "17:00"),
        ("saat altı", "18:00"),
        ("saat dört", "16:00"),
        ("saat üç", "15:00"),
        ("saat iki", "14:00"),
        ("saat bir", "13:00"),
    ])
    def test_saat_word_pm_default(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── "saat <digit>" ────────────────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("saat 5", "17:00"),
        ("saat 6", "18:00"),
        ("saat 4", "16:00"),
        ("saat 3", "15:00"),
        ("saat 2", "14:00"),
        ("saat 1", "13:00"),
    ])
    def test_saat_digit_pm_default(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── AM explicit (sabah) ───────────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("sabah beşte koşu", "05:00"),
        ("sabah beş", "05:00"),
        ("sabah altıda kalk", "06:00"),
        ("sabah dörtte", "04:00"),
        ("sabah üçte", "03:00"),
        ("sabah ikide", "02:00"),
        ("sabah birde", "01:00"),
        ("sabah saat 5", "05:00"),
    ])
    def test_am_explicit(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── PM explicit (akşam) ───────────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("akşam beşte yemek", "17:00"),
        ("akşam altıda", "18:00"),
        ("akşam yedide", "19:00"),
        ("akşam sekizde", "20:00"),
        ("akşam dokuzda", "21:00"),
    ])
    def test_pm_explicit_aksam(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── Hours 7-12 (no default shift) ─────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("yedide gel", "07:00"),
        ("sekizde başla", "08:00"),
        ("dokuzda toplantı", "09:00"),
        ("onda ara ver", "10:00"),
        ("saat 9", "09:00"),
        ("saat 10", "10:00"),
        ("saat 11", "11:00"),
        ("saat 12", "12:00"),
    ])
    def test_hours_7_12_as_is(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── Half past (buçuk) ─────────────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("beş buçuk", "17:30"),
        ("beş buçukta gel", "17:30"),
        ("saat beş buçuk", "17:30"),
        ("sabah beş buçuk", "05:30"),
        ("altı buçuk", "18:30"),
        ("dokuz buçuk", "09:30"),
        ("saat 5 buçuk", "17:30"),
    ])
    def test_half_past(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── Quarter past/to (çeyrek) ──────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("üçü çeyrek geçe", "15:15"),
        ("beşi çeyrek geçe", "17:15"),
    ])
    def test_quarter_past(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("beşe çeyrek kala", "16:45"),
        ("üçe çeyrek kala", "14:45"),
    ])
    def test_quarter_to(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── Already 24h digits ────────────────────────────────────────────

    @pytest.mark.parametrize("text,expected", [
        ("saat 17", "17:00"),
        ("saat 23", "23:00"),
        ("saat 0", "00:00"),
        ("saat 13", "13:00"),
    ])
    def test_24h_digits(self, text, expected):
        assert parse_hhmm_turkish(text) == expected

    # ── Edge cases ────────────────────────────────────────────────────

    def test_empty_string(self):
        assert parse_hhmm_turkish("") is None

    def test_none(self):
        assert parse_hhmm_turkish(None) is None

    def test_no_time_expression(self):
        assert parse_hhmm_turkish("bugün hava güzel") is None
        assert parse_hhmm_turkish("nasılsın dostum") is None

    def test_on_bir(self):
        assert parse_hhmm_turkish("on birde gel") == "11:00"
        assert parse_hhmm_turkish("on ikide öğle") == "12:00"

    def test_ascii_fallbacks(self):
        """Test ASCII-only variants (no İ/ı/ü/ö/ç/ş)."""
        assert parse_hhmm_turkish("bes") is not None  # "bes" → beş
        assert parse_hhmm_turkish("dort") is not None  # "dort" → dört
        assert parse_hhmm_turkish("uc") is not None    # "uc" → üç
        assert parse_hhmm_turkish("alti") is not None  # "alti" → altı


# ============================================================================
# Post-process slot time (post_process_slot_time)
# ============================================================================

class TestPostProcessSlotTime:
    """Test LLM slot time correction logic."""

    def test_llm_correct_no_change(self):
        """If LLM returns 17:00 for 'beşe', no change needed."""
        assert post_process_slot_time("17:00", "beşe toplantı") == "17:00"

    def test_llm_wrong_am_pm_flip(self):
        """If LLM returns 05:00 for 'beşe' (no sabah), correct to 17:00."""
        result = post_process_slot_time("05:00", "beşe toplantı")
        assert result == "17:00"

    def test_llm_correct_am_with_sabah(self):
        """If LLM returns 05:00 for 'sabah beşte', keep it."""
        assert post_process_slot_time("05:00", "sabah beşte koşu") == "05:00"

    def test_llm_wrong_pm_with_sabah(self):
        """If LLM returns 17:00 for 'sabah beşte', correct to 05:00."""
        result = post_process_slot_time("17:00", "sabah beşte koşu")
        assert result == "05:00"

    def test_llm_none_fallback(self):
        """If LLM returns None, use rule-based."""
        result = post_process_slot_time(None, "beşe toplantı")
        assert result == "17:00"

    def test_llm_empty_fallback(self):
        """If LLM returns empty, use rule-based."""
        result = post_process_slot_time("", "altıda buluş")
        assert result == "18:00"

    def test_no_rule_based_trust_llm(self):
        """If rule-based finds nothing, trust LLM."""
        result = post_process_slot_time("14:30", "bugün bir toplantı var")
        assert result == "14:30"

    def test_both_none(self):
        """If both LLM and rule-based find nothing, return None."""
        result = post_process_slot_time(None, "nasılsın")
        assert result is None

    def test_close_hours_keep_llm(self):
        """If LLM and rule-based differ by ≤1h, keep LLM (edge case)."""
        # LLM says 16:00, rule-based says 17:00 for "beşe" → they differ by 1
        # Actually "beşe" → rule-based=17:00. If LLM says 16:00, diff=1, keep LLM
        result = post_process_slot_time("16:00", "beşe toplantı")
        # They differ by exactly 1 hour. Rule: abs(16-17)=1 ≤ 1 → keep LLM
        assert result == "16:00"

    @pytest.mark.parametrize("llm_time,user_text,expected", [
        ("05:00", "beşe toplantı", "17:00"),       # AM/PM flip
        ("06:00", "altıda buluş", "18:00"),         # AM/PM flip
        ("03:00", "üçe kadar", "15:00"),            # AM/PM flip
        ("17:00", "sabah beşte", "05:00"),          # reverse flip
        ("18:00", "sabah altıda", "06:00"),         # reverse flip
    ])
    def test_am_pm_correction_matrix(self, llm_time, user_text, expected):
        assert post_process_slot_time(llm_time, user_text) == expected


# ============================================================================
# Integration: calendar_intent.parse_hhmm_with_turkish
# ============================================================================

class TestCalendarIntentIntegration:
    """Test that calendar_intent.build_intent uses Turkish clock parsing."""

    def test_build_intent_turkish_time_creates_event(self):
        """build_intent should extract time from 'beşe toplantı koy'."""
        from bantz.brain.calendar_intent import build_intent

        intent = build_intent("bugün beşe toplantı koy")
        assert intent.type == "create_event"
        assert intent.params.get("start_hhmm") == "17:00"

    def test_build_intent_sabah_am(self):
        """build_intent should extract AM time from 'sabah beşte koşu ekle'."""
        from bantz.brain.calendar_intent import build_intent

        intent = build_intent("yarın sabah beşte koşu ekle")
        assert intent.type == "create_event"
        assert intent.params.get("start_hhmm") == "05:00"

    def test_build_intent_numeric_still_works(self):
        """build_intent should still parse numeric times."""
        from bantz.brain.calendar_intent import build_intent

        intent = build_intent("yarın 14:30 toplantı ekle")
        assert intent.type == "create_event"
        assert intent.params.get("start_hhmm") == "14:30"

    def test_build_intent_no_time(self):
        """build_intent without time should have 'start_time' in missing."""
        from bantz.brain.calendar_intent import build_intent

        intent = build_intent("yarın toplantı ekle")
        assert intent.type == "create_event"
        assert "start_time" in intent.missing

    def test_parse_hhmm_with_turkish_numeric_first(self):
        """Numeric should take priority over word-based."""
        from bantz.brain.calendar_intent import parse_hhmm_with_turkish

        # Has both numeric and word — numeric wins
        assert parse_hhmm_with_turkish("14:30 beşe toplantı") == "14:30"

    def test_parse_hhmm_with_turkish_word_fallback(self):
        """When no numeric, should use Turkish word."""
        from bantz.brain.calendar_intent import parse_hhmm_with_turkish

        assert parse_hhmm_with_turkish("beşe toplantı") == "17:00"
        assert parse_hhmm_with_turkish("sabah altıda") == "06:00"


# ============================================================================
# Integration: llm_router._extract_output post-processing
# ============================================================================

class TestLLMRouterPostProcessing:
    """Test that _extract_output applies Turkish time post-processing."""

    def _make_router(self):
        from unittest.mock import MagicMock
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_llm = MagicMock()
        router = JarvisLLMOrchestrator(llm=mock_llm)
        return router

    def test_extract_output_corrects_am_pm(self):
        """_extract_output should correct 05:00 → 17:00 for 'beşe toplantı'."""
        router = self._make_router()
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "05:00", "title": "toplantı"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
        }
        result = router._extract_output(parsed, raw_text="{}", user_input="bugün beşe toplantı koy")
        assert result.slots.get("time") == "17:00"

    def test_extract_output_keeps_correct_time(self):
        """_extract_output should keep correct 17:00 unchanged."""
        router = self._make_router()
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "17:00", "title": "toplantı"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
        }
        result = router._extract_output(parsed, raw_text="{}", user_input="bugün beşe toplantı koy")
        assert result.slots.get("time") == "17:00"

    def test_extract_output_fills_missing_time(self):
        """_extract_output should fill missing time from user text."""
        router = self._make_router()
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"title": "toplantı"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
        }
        result = router._extract_output(parsed, raw_text="{}", user_input="bugün beşe toplantı koy")
        assert result.slots.get("time") == "17:00"

    def test_extract_output_no_change_for_non_calendar(self):
        """_extract_output should not touch slots for non-calendar routes (genuine smalltalk)."""
        router = self._make_router()
        parsed = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "İyiyim efendim",
        }
        # Use a genuine smalltalk input — not a calendar request
        result = router._extract_output(parsed, raw_text="{}", user_input="nasılsın")
        # Route stays smalltalk for genuine smalltalk input
        assert result.route == "smalltalk"

    def test_extract_output_no_user_input(self):
        """_extract_output with empty user_input should not crash."""
        router = self._make_router()
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "05:00"},
            "confidence": 0.9,
            "tool_plan": [],
        }
        result = router._extract_output(parsed, raw_text="{}", user_input="")
        assert result.slots.get("time") == "05:00"  # no change — no user text to parse


# ============================================================================
# Vocabulary coverage
# ============================================================================

class TestVocabularyCoverage:
    """Ensure all 12 clock hours are handled."""

    @pytest.mark.parametrize("word,expected_hour", [
        ("bir", 1), ("iki", 2), ("üç", 3), ("dört", 4),
        ("beş", 5), ("altı", 6), ("yedi", 7), ("sekiz", 8),
        ("dokuz", 9), ("on", 10), ("on bir", 11), ("on iki", 12),
    ])
    def test_all_12_hours_in_vocab(self, word, expected_hour):
        assert _TR_HOUR_WORDS[word] == expected_hour

    def test_vocab_has_ascii_fallbacks(self):
        """ASCII-only versions should be in vocab."""
        for key in ("uc", "dort", "bes", "alti"):
            assert key in _TR_HOUR_WORDS, f"{key} should be in _TR_HOUR_WORDS"
