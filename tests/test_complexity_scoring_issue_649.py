"""Tests for Issue #649: score_complexity() karmaşık planlama isteklerini yakalayamıyor.

Bug:
  1. score_complexity() action verb'leri ("yap", "oluştur", "hazırla") skorlamıyordu.
     "adım adım haftalık bir plan yap bana" sadece complexity=2 alıyordu.
  2. "haftalık bir plan" → "haftalık plan" substring match ile bulunamıyordu
     (arada "bir" kelimesi var).
  3. quality_gating fast_max_threshold erken çıkışı, component-based escalation'ı
     engelliyordu. complexity=4 olan istek total=1.4 < 1.5 → FAST kalıyordu.

Fix:
  - score_complexity: action verb bonus (+1) ve haftalık+plan ayrık match (+1) eklendi.
  - quality_gating: fast_max_threshold kontrolüne component escalation bypass eklendi.
  - complexity ≥ 4 olan istekler artık component_threshold_exceeded ile QUALITY'e gidiyor.
"""

from __future__ import annotations

import os

import pytest

from bantz.llm.tiered import score_complexity, decide_tier


# ─────────────────────────────────────────────────────────────────────────────
# Core fix: action verb bonus
# ─────────────────────────────────────────────────────────────────────────────

class TestActionVerbBonus:
    """Action verb + complexity keyword = +1 bonus."""

    def test_exact_issue_example(self):
        """Exact scenario from issue: was 2, now should be 4."""
        assert score_complexity("adım adım haftalık bir plan yap bana") == 4

    def test_haftalik_plan_yap(self):
        """was 3, now 4."""
        assert score_complexity("haftalık plan yap") == 4

    def test_plan_hazirla(self):
        """'plan' keyword + 'hazırla' action verb → 3."""
        assert score_complexity("bana bir plan hazırla") == 3

    def test_detayli_analiz_yap(self):
        """'detaylı' + 'analiz' keyword, 'yap' action verb → 3."""
        assert score_complexity("detaylı analiz yap") == 3

    def test_roadmap_olustur(self):
        """'roadmap' keyword + 'oluştur' action verb → 3."""
        assert score_complexity("roadmap oluştur") == 3

    def test_strateji_belirle(self):
        """'strateji' keyword + 'belirle' action verb → 3."""
        assert score_complexity("strateji belirle") == 3

    def test_gun_gun_plan_hazirla(self):
        """'gün gün' keyword + 'hazırla' action verb → 3."""
        assert score_complexity("gün gün plan hazırla") == 3

    def test_no_action_verb_no_bonus(self):
        """'kıyasla' is a keyword but no action verb follows → stays at 2."""
        assert score_complexity("kıyasla bana") == 2


# ─────────────────────────────────────────────────────────────────────────────
# Disjoint "haftalık ... plan" match
# ─────────────────────────────────────────────────────────────────────────────

class TestDisjointHaftalikPlan:
    """'haftalık bir plan' should match like 'haftalık plan'."""

    def test_haftalik_bir_plan(self):
        """'haftalık' + 'plan' in text but not adjacent → +1 bonus."""
        assert score_complexity("haftalık bir plan yap bana") >= 4

    def test_haftalik_guzel_plan(self):
        """Any text with both 'haftalık' and 'plan' → bonus."""
        assert score_complexity("haftalık güzel bir plan") >= 3

    def test_adjacent_haftalik_plan_no_double(self):
        """'haftalık plan' (adjacent) → strong_signals match, no extra bonus."""
        s1 = score_complexity("haftalık plan yap")
        # Should be same as before, no double-count
        assert s1 == 4

    def test_only_haftalik_no_plan(self):
        """Just 'haftalık' without 'plan' → no disjoint bonus."""
        s = score_complexity("haftalık özet")
        # 'haftalık' → keyword +2, no strong_signals, no disjoint
        assert s == 2


# ─────────────────────────────────────────────────────────────────────────────
# Regression: simple queries must stay low
# ─────────────────────────────────────────────────────────────────────────────

class TestSimpleQueryRegression:
    """Simple/short queries should not escalate."""

    def test_hava_nasil(self):
        assert score_complexity("hava nasıl") == 0

    def test_saat_kac(self):
        assert score_complexity("saat kaç") == 0

    def test_merhaba(self):
        assert score_complexity("merhaba") == 0

    def test_maillerimi_listele(self):
        assert score_complexity("maillerimi listele") == 0

    def test_empty(self):
        assert score_complexity("") == 0

    def test_none(self):
        assert score_complexity(None) == 0

    def test_whitespace(self):
        assert score_complexity("   ") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Strong signals still work
# ─────────────────────────────────────────────────────────────────────────────

class TestStrongSignals:
    """Existing strong_signals ("3 adım", "5 adım", "haftalık plan") still work."""

    def test_5_adimlik_plan_yap(self):
        assert score_complexity("5 adımlık bir plan yap") == 4

    def test_3_adim_strateji_hazirla(self):
        assert score_complexity("3 adım adım strateji hazırla") == 4

    def test_haftalik_plan_adjacent(self):
        assert score_complexity("haftalık plan") >= 3

    def test_4_adim(self):
        assert score_complexity("4 adım planla") >= 3


# ─────────────────────────────────────────────────────────────────────────────
# Score cap at 5
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreCap:
    """Score must never exceed 5."""

    def test_max_signals(self):
        text = "çok detaylı kapsamlı adım adım haftalık bir plan yap bana"
        assert score_complexity(text) == 5

    def test_extremely_long_complex(self):
        text = "a " * 250 + "adım adım haftalık plan yap detaylı kapsamlı"
        assert score_complexity(text) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# E2E: decide_tier integration (quality_gating component escalation fix)
# ─────────────────────────────────────────────────────────────────────────────

class TestDecideTierIntegration:
    """Component-based escalation should override fast_max_threshold."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch):
        """Remove all tier-related env vars."""
        for var in (
            "BANTZ_TIER_MODE",
            "BANTZ_TIERED_MODE",
            "BANTZ_TIER_FORCE",
            "BANTZ_LLM_TIER",
            "BANTZ_TIER_FORCE_FINALIZER",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_complex_planning_uses_quality(self):
        """'adım adım haftalık bir plan yap bana' → QUALITY."""
        d = decide_tier("adım adım haftalık bir plan yap bana")
        assert d.use_quality is True
        assert d.complexity >= 4
        assert d.reason == "component_threshold_exceeded"

    def test_haftalik_plan_yap_uses_quality(self):
        d = decide_tier("haftalık plan yap")
        assert d.use_quality is True
        assert d.complexity >= 4

    def test_5_adim_plan_yap_uses_quality(self):
        d = decide_tier("5 adımlık bir plan yap")
        assert d.use_quality is True
        assert d.complexity >= 4

    def test_simple_query_stays_fast(self):
        d = decide_tier("hava nasıl")
        assert d.use_quality is False
        assert d.complexity == 0

    def test_moderate_complexity_stays_fast(self):
        """complexity=3 < min_complexity_for_quality(4) → FAST."""
        d = decide_tier("detaylı analiz yap")
        assert d.use_quality is False
        assert d.complexity == 3

    def test_forced_fast_overrides(self, monkeypatch: pytest.MonkeyPatch):
        """BANTZ_TIER_FORCE=fast still overrides everything."""
        monkeypatch.setenv("BANTZ_TIER_FORCE", "fast")
        d = decide_tier("adım adım haftalık bir plan yap bana")
        assert d.use_quality is False
        assert d.reason == "forced_fast"


# ─────────────────────────────────────────────────────────────────────────────
# Parametrized: action verbs × complexity keywords
# ─────────────────────────────────────────────────────────────────────────────

ACTION_VERBS = ["yap", "oluştur", "hazırla", "çıkar", "üret", "belirle"]
COMPLEXITY_KEYWORDS = [
    "plan", "strateji", "roadmap", "analiz", "detaylı",
    "adım adım", "derinlemesine", "kıyasla",
]


@pytest.mark.parametrize("verb", ACTION_VERBS)
@pytest.mark.parametrize("keyword", COMPLEXITY_KEYWORDS)
def test_action_verb_with_complexity_keyword_bonus(keyword: str, verb: str):
    """Every action verb + complexity keyword should score ≥ 3."""
    text = f"{keyword} {verb}"
    score = score_complexity(text)
    assert score >= 3, f"score_complexity('{text}') = {score}, expected ≥ 3"
