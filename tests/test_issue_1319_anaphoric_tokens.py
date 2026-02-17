"""Tests for issue #1319: _is_anaphoric_followup token expansion.

Covers:
1. Newly added demonstrative pronouns trigger follow-up detection
2. Existing tokens still work
3. Long inputs (>6 words) are rejected
4. Non-anaphoric inputs are not matched
5. Token set completeness
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bantz.brain.llm_router import JarvisLLMOrchestrator


@pytest.fixture
def router():
    """Create a minimal JarvisLLMOrchestrator with a mock LLM."""
    mock_llm = MagicMock()
    mock_llm.health_check.return_value = True
    return JarvisLLMOrchestrator(llm=mock_llm)


# -- 1. Context-reference tokens (Issue #1319) ----------------------------


class TestNewTokensDetected:
    """Verify context-reference tokens are detected."""

    @pytest.mark.parametrize("text", [
        "show it",
        "read those",
        "explain them",
        "details please",
        "same thing",
        "above results",
        "previous one",
    ])
    def test_new_tokens_trigger_followup(self, router, text):
        assert router._is_anaphoric_followup(text) is True


# -- 2. Existing tokens still work ----------------------------------------


class TestExistingTokens:
    """Verify pre-existing tokens still trigger detection."""

    @pytest.mark.parametrize("text", [
        "which one",
        "summarize them",
        "show more",
        "what else",
        "tell me",
        "explain it",
    ])
    def test_existing_tokens_still_work(self, router, text):
        assert router._is_anaphoric_followup(text) is True


# -- 3. Long inputs rejected ----------------------------------------------


class TestLongInputRejected:
    """Inputs with >6 words should not match (avoid false positives)."""

    def test_7_word_input_rejected(self, router):
        long_text = "can you please show me all of those items right now"
        assert router._is_anaphoric_followup(long_text) is False


# -- 4. Non-anaphoric inputs not matched -----------------------------------


class TestNonAnaphoric:
    """Non-anaphoric inputs should not be detected as follow-ups."""

    @pytest.mark.parametrize("text", [
        "add a meeting tomorrow",
        "how is the weather",
        "open spotify",
        "send an email",
        "",
    ])
    def test_non_anaphoric_not_matched(self, router, text):
        assert router._is_anaphoric_followup(text) is False


# -- 5. Token set completeness --------------------------------------------


class TestTokenSetCompleteness:
    """Verify _ANAPHORA_TOKENS contains all required tokens."""

    def test_object_forms_present(self):
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["it", "its", "them"]:
            assert t in tokens, f"Missing object form: {t}"

    def test_demonstrative_forms_present(self):
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["these", "those"]:
            assert t in tokens, f"Missing demonstrative form: {t}"

    def test_context_reference_words_present(self):
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["above", "previous", "same"]:
            assert t in tokens, f"Missing context-reference word: {t}"

    def test_bare_articles_excluded(self):
        """'a', 'the' are intentionally excluded to avoid FP."""
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["a", "the", "an"]:
            assert t not in tokens, (
                f"Article '{t}' should be excluded to avoid false positives"
            )
