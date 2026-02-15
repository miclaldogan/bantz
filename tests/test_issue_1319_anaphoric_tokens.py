"""Tests for issue #1319: _is_anaphoric_followup token expansion.

Covers:
1. Newly added Turkish demonstrative pronouns trigger follow-up detection
2. Existing tokens still work
3. Long inputs (>6 words) are rejected
4. Non-anaphoric inputs are not matched
5. Integration: _is_anaphoric_followup is callable from orchestrator_loop
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


# ── 1. Newly added tokens (Issue #1319) ──────────────────────────────────


class TestNewTokensDetected:
    """Verify newly added #1319 tokens are detected."""

    @pytest.mark.parametrize("text", [
        "onu aç",
        "bunu sil",
        "şunu göster",
        "bunun detayları",
        "onun içeriği",
        "yukarıdaki ne",
        "önceki sonuçlar",
        "aynı şeyi yap",
    ])
    def test_new_tokens_trigger_followup(self, router, text):
        assert router._is_anaphoric_followup(text) is True


# ── 2. Existing tokens still work ────────────────────────────────────────


class TestExistingTokens:
    """Verify pre-existing tokens still trigger detection."""

    @pytest.mark.parametrize("text", [
        "nelermiş onlar",
        "bunları özetle",
        "devamını göster",
        "hangisi",
        "başka var mı",
        "bana anlat",
    ])
    def test_existing_tokens_still_work(self, router, text):
        assert router._is_anaphoric_followup(text) is True


# ── 3. Long inputs rejected ──────────────────────────────────────────────


class TestLongInputRejected:
    """Inputs with >6 words should not match (avoid false positives)."""

    def test_7_word_input_rejected(self, router):
        long_text = "şu anda onu görmek istiyorum acaba mümkün müdür"
        assert router._is_anaphoric_followup(long_text) is False


# ── 4. Non-anaphoric inputs not matched ──────────────────────────────────


class TestNonAnaphoric:
    """Non-anaphoric inputs should not be detected as follow-ups."""

    @pytest.mark.parametrize("text", [
        "yarın toplantı ekle",
        "hava durumu nasıl",
        "spotify aç",
        "mail gönder",
        "",
    ])
    def test_non_anaphoric_not_matched(self, router, text):
        assert router._is_anaphoric_followup(text) is False


# ── 5. Token set completeness ────────────────────────────────────────────


class TestTokenSetCompleteness:
    """Verify _ANAPHORA_TOKENS contains all required tokens."""

    def test_accusative_singular_forms_present(self):
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["onu", "bunu", "şunu"]:
            assert t in tokens, f"Missing accusative form: {t}"

    def test_genitive_forms_present(self):
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["bunun", "onun"]:
            assert t in tokens, f"Missing genitive form: {t}"

    def test_context_reference_words_present(self):
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["yukarıdaki", "önceki", "aynı"]:
            assert t in tokens, f"Missing context-reference word: {t}"

    def test_bare_pronouns_excluded(self):
        """'bu', 'şu', 'o' are intentionally excluded to avoid FP."""
        tokens = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        for t in ["bu", "şu", "o"]:
            assert t not in tokens, (
                f"Bare pronoun '{t}' should be excluded to avoid false positives"
            )
