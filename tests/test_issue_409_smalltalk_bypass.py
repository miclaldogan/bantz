"""Tests for Issue #409: Smalltalk bypass — simple greetings skip Gemini."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from bantz.brain.finalization_pipeline import (
    is_simple_greeting,
    decide_finalization_tier,
)
from bantz.brain.llm_router import OrchestratorOutput


# ---------------------------------------------------------------------------
# is_simple_greeting tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "merhaba",
    "Merhaba",
    "MERHABA",
    "selam",
    "hey",
    "günaydın",
    "nasılsın",
    "naber",
    "ne haber",
    "teşekkürler",
    "teşekkür ederim",
    "sağ ol",
    "hoşça kal",
    "görüşürüz",
    "iyi geceler",
    "iyi akşamlar",
    "iyi günler",
    "kolay gelsin",
    "eyvallah",
    "merhaba!",
    "selam?",
    "merhaba dostum",
    "selam Bantz",
    "naber Bantz",
])
def test_simple_greeting_positive(text: str):
    """Simple greetings should be recognized."""
    assert is_simple_greeting(text) is True


@pytest.mark.parametrize("text", [
    "bugün hava nasıl olacak?",
    "bana bir fıkra anlat",
    "yapay zeka hakkında ne düşünüyorsun?",
    "merhaba, bugün toplantılarım neler?",
    "selam, takvimimi kontrol eder misin?",
    "nasılsın, bana yardım etmeni istiyorum",
    "dün gece çok ilginç bir film izledim ne düşünürsün",
    "hayatın anlamı nedir sence",
])
def test_simple_greeting_negative(text: str):
    """Complex inputs should NOT be treated as simple greetings."""
    assert is_simple_greeting(text) is False


def test_empty_input_not_simple():
    """Empty input is not a simple greeting."""
    assert is_simple_greeting("") is False
    assert is_simple_greeting("   ") is False


# ---------------------------------------------------------------------------
# decide_finalization_tier tests
# ---------------------------------------------------------------------------

def _make_output(route: str = "smalltalk", **kwargs) -> OrchestratorOutput:
    defaults = dict(
        route=route,
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=[],
        assistant_reply="Merhaba efendim!",
        raw_output={},
    )
    defaults.update(kwargs)
    return OrchestratorOutput(**defaults)


class TestDecideFinalizationTier:
    """Tests for finalization tier decision."""

    def test_simple_greeting_skips_gemini(self):
        """Simple greeting → fast tier (no Gemini)."""
        output = _make_output(route="smalltalk")
        use_quality, tier, reason = decide_finalization_tier(
            orchestrator_output=output,
            user_input="merhaba",
            has_finalizer=True,
        )
        assert use_quality is False
        assert tier == "fast"
        assert "simple_greeting" in reason

    def test_complex_smalltalk_uses_gemini(self):
        """Complex smalltalk → quality tier (Gemini)."""
        output = _make_output(route="smalltalk")
        use_quality, tier, reason = decide_finalization_tier(
            orchestrator_output=output,
            user_input="hayatın anlamı nedir sence?",
            has_finalizer=True,
        )
        assert use_quality is True
        assert tier == "quality"
        assert "complex_smalltalk" in reason

    def test_no_finalizer_always_fast(self):
        """No finalizer available → always fast."""
        output = _make_output(route="smalltalk")
        use_quality, tier, reason = decide_finalization_tier(
            orchestrator_output=output,
            user_input="merhaba",
            has_finalizer=False,
        )
        assert use_quality is False
        assert tier == "fast"

    def test_calendar_route_unaffected(self):
        """Calendar route is not affected by greeting check."""
        output = _make_output(route="calendar", calendar_intent="query")
        use_quality, tier, reason = decide_finalization_tier(
            orchestrator_output=output,
            user_input="bugün toplantılarım neler?",
            has_finalizer=True,
        )
        # Calendar goes through tiered decision (not the greeting path)
        assert reason != "simple_greeting_skip_gemini"

    def test_gemini_calls_saved_logged(self, caplog):
        """Simple greeting should log gemini_calls_saved metric."""
        import logging
        with caplog.at_level(logging.INFO):
            output = _make_output(route="smalltalk")
            decide_finalization_tier(
                orchestrator_output=output,
                user_input="selam",
                has_finalizer=True,
            )
        assert any("gemini_calls_saved" in r.message for r in caplog.records)

    def test_turkish_greetings_variety(self):
        """Various Turkish greetings all skip Gemini."""
        greetings = ["günaydın", "iyi akşamlar", "iyi geceler", "kolay gelsin"]
        output = _make_output(route="smalltalk")
        for g in greetings:
            use_q, _, reason = decide_finalization_tier(
                orchestrator_output=output,
                user_input=g,
                has_finalizer=True,
            )
            assert use_q is False, f"'{g}' should skip Gemini"
            assert "simple_greeting" in reason
