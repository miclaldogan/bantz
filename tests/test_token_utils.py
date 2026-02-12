"""Tests for unified token estimation utilities (Issue #406).

Covers:
- estimate_tokens (all 3 methods: chars4, chars3, words)
- estimate_tokens_json
- trim_to_tokens
- Env var override (BANTZ_TOKEN_METHOD)
- Null/empty handling
- Integration: verify existing modules now delegate correctly
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bantz.llm.token_utils import (
    estimate_tokens,
    estimate_tokens_json,
    trim_to_tokens,
)


# =============================================================================
# estimate_tokens
# =============================================================================

class TestEstimateTokens:
    """Test the unified estimate_tokens function."""

    def test_none_returns_zero(self):
        assert estimate_tokens(None) == 0

    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_chars4_default(self):
        # 12 chars → 3 tokens
        assert estimate_tokens("abcdefghijkl") == 3

    def test_chars4_explicit(self):
        assert estimate_tokens("abcdefgh", method="chars4") == 2

    def test_chars3_method(self):
        # 12 chars → 4 tokens
        assert estimate_tokens("abcdefghijkl", method="chars3") == 4

    def test_words_method(self):
        assert estimate_tokens("merhaba dünya nasılsın", method="words") == 3

    def test_single_word(self):
        assert estimate_tokens("merhaba", method="words") == 1

    def test_non_negative(self):
        assert estimate_tokens("ab") >= 0
        assert estimate_tokens("ab", method="chars3") >= 0
        assert estimate_tokens("ab", method="words") >= 0

    def test_turkish_text(self):
        text = "Efendim, yarın saat 10:00'da toplantınız var."
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_env_var_override(self):
        with patch.dict("os.environ", {"BANTZ_TOKEN_METHOD": "words"}):
            # "abc def ghi" → 3 words
            assert estimate_tokens("abc def ghi") == 3

    def test_env_var_invalid_uses_default(self):
        with patch.dict("os.environ", {"BANTZ_TOKEN_METHOD": "invalid_method"}):
            # Falls back to chars4: 12 chars → 3 tokens
            assert estimate_tokens("abcdefghijkl") == 3

    def test_long_text(self):
        text = "a" * 400
        assert estimate_tokens(text, method="chars4") == 100


# =============================================================================
# estimate_tokens_json
# =============================================================================

class TestEstimateTokensJson:
    """Test JSON token estimation."""

    def test_list_of_dicts(self):
        data = [{"tool": "calendar.list_events", "success": True}]
        tokens = estimate_tokens_json(data)
        assert tokens > 0

    def test_empty_list(self):
        assert estimate_tokens_json([]) == 0 or estimate_tokens_json([]) >= 0

    def test_non_serializable_falls_back(self):
        """Non-serializable objects use str() fallback."""

        class Weird:
            def __str__(self):
                return "weird_object"

        tokens = estimate_tokens_json(Weird())
        assert tokens > 0

    def test_none(self):
        tokens = estimate_tokens_json(None)
        assert tokens >= 0

    def test_nested_dict(self):
        data = {"items": [{"summary": "Meeting"}, {"summary": "Review"}], "count": 2}
        tokens = estimate_tokens_json(data)
        assert tokens > 5


# =============================================================================
# trim_to_tokens
# =============================================================================

class TestTrimToTokens:
    """Test text trimming to token budget."""

    def test_short_text_unchanged(self):
        text = "merhaba"
        result = trim_to_tokens(text, 100)
        assert result == text

    def test_long_text_trimmed(self):
        text = "a" * 400  # 100 tokens at chars4
        result = trim_to_tokens(text, 10)
        assert len(result) <= 40 + 1  # 10*4 + ellipsis
        assert result.endswith("…")

    def test_zero_budget(self):
        assert trim_to_tokens("hello", 0) == ""

    def test_negative_budget(self):
        assert trim_to_tokens("hello", -5) == ""

    def test_none_text(self):
        assert trim_to_tokens(None, 10) == ""

    def test_empty_text(self):
        assert trim_to_tokens("", 10) == ""

    def test_words_method_trim(self):
        text = "merhaba dünya nasılsın bugün hava güzel"
        result = trim_to_tokens(text, 3, method="words")
        words = result.split()
        assert len(words) <= 3

    def test_chars3_method_trim(self):
        text = "a" * 300  # 100 tokens at chars3
        result = trim_to_tokens(text, 10, method="chars3")
        assert len(result) <= 30 + 1  # 10*3 + ellipsis

    def test_exact_budget_no_trim(self):
        text = "a" * 40  # exactly 10 tokens at chars4
        result = trim_to_tokens(text, 10)
        assert result == text


# =============================================================================
# Integration: verify existing modules delegate correctly
# =============================================================================

class TestIntegration:
    """Verify that the migrated modules now produce consistent estimates."""

    def test_prompt_engineering_uses_token_utils(self):
        from bantz.brain.prompt_engineering import estimate_tokens as pe_estimate

        text = "Efendim, yarın toplantınız var."
        assert pe_estimate(text) == estimate_tokens(text)

    def test_llm_router_uses_token_utils(self):
        from bantz.brain.llm_router import _estimate_tokens

        text = "Takvim etkinliklerini listele."
        assert _estimate_tokens(text) == estimate_tokens(text)

    def test_finalizer_uses_token_utils(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from bantz.brain.finalizer import _estimate_tokens

        text = "Tool results: calendar query completed."
        assert _estimate_tokens(text) == estimate_tokens(text)

    def test_llm_router_trim_uses_token_utils(self):
        from bantz.brain.llm_router import _trim_to_tokens

        text = "a" * 400
        result = _trim_to_tokens(text, 10)
        expected = trim_to_tokens(text, 10)
        assert result == expected

    def test_memory_lite_consistent(self):
        """memory_lite._estimate_tokens now uses chars4 instead of word-count."""
        from bantz.brain.memory_lite import DialogSummaryManager, CompactSummary

        mgr = DialogSummaryManager(max_turns=10, max_tokens=10000)
        summary = CompactSummary(
            turn_number=1,
            user_intent="Takvim sorgusu",
            action_taken="listed events",
        )
        mgr.summaries = [summary]
        tokens = mgr._estimate_tokens()
        # Should now use chars4 (not word-count)
        text = summary.to_prompt_block()
        assert tokens == estimate_tokens(text)
