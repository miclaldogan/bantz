from __future__ import annotations

import pytest

from bantz.llm.tiered import decide_tier


@pytest.fixture(autouse=True)
def _tiered_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BANTZ_TIERED_MODE", "1")
    monkeypatch.delenv("BANTZ_LLM_TIER", raising=False)


def test_smalltalk_simple_greeting_uses_fast():
    decision = decide_tier(
        "Merhaba efendim",
        route="smalltalk",
        tool_names=[],
        requires_confirmation=False,
    )

    assert decision.use_quality is False
    assert decision.reason == "smalltalk_simple"


def test_smalltalk_complex_question_uses_quality():
    decision = decide_tier(
        "Yapay zeka nedir, açıkla",
        route="smalltalk",
        tool_names=[],
        requires_confirmation=False,
    )

    assert decision.use_quality is True
    assert decision.reason == "smalltalk_complex"
