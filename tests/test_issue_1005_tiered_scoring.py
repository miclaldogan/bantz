"""Tests for Issue #1005: Tiered Scoring double-count fix.

Verifies:
1. score_complexity no longer double-counts keywords
2. 'haftalık bir plan yap' scores reasonably (not inflated)
3. score_risk checks Turkish verbs in tool names
4. Simple requests stay in fast tier
"""

import pytest

from bantz.llm.tiered import score_complexity, score_risk


class TestDoubleCountFix:
    """score_complexity should not inflate scores via duplicate keyword scans."""

    def test_haftalik_plan_yap_not_inflated(self):
        """'haftalık bir plan yap' was scoring 4+ due to double counting.
        Now: +2 (keyword group) + +1 (action verb bonus) = 3 max.
        """
        score = score_complexity("haftalık bir plan yap")
        assert score <= 3, f"Score {score} is inflated (expected <=3)"

    def test_simple_plan_keyword(self):
        """Just 'plan' should score +2 from keyword group only."""
        score = score_complexity("plan")
        assert score == 2

    def test_plan_with_action_verb(self):
        """'plan yap' → +2 (keyword) + +1 (action verb bonus) = 3."""
        score = score_complexity("plan yap")
        assert score == 3

    def test_haftalik_plan_exact_phrase(self):
        """'haftalık plan' → +2 (keyword) + +1 (strong signal) = 3."""
        score = score_complexity("haftalık plan")
        assert score == 3

    def test_simple_greeting_zero(self):
        score = score_complexity("merhaba")
        assert score == 0

    def test_simple_question_zero(self):
        score = score_complexity("hava nasıl")
        assert score == 0

    def test_empty_zero(self):
        score = score_complexity("")
        assert score == 0

    def test_maillerimi_listele_zero(self):
        score = score_complexity("maillerimi listele")
        assert score == 0

    def test_adim_adim_strong_signal(self):
        """'adım adım plan yap' → +2 (keyword) + +1 (action verb) = 3."""
        score = score_complexity("adım adım plan yap")
        # "adım adım" matches keyword group, "yap" is action verb
        assert score <= 4  # should not inflate to 5

    def test_detayli_analiz_yap(self):
        """Should get keyword + action verb but not more."""
        score = score_complexity("detaylı analiz yap")
        assert score == 3  # +2 keyword + +1 verb


class TestScoreRiskTurkishVerbs:
    """score_risk should detect Turkish verbs in tool names."""

    def test_gonder_in_tool_name(self):
        risk = score_risk("mail gönder", tool_names=["gmail.gönder"])
        assert risk >= 3

    def test_guncelle_in_tool_name(self):
        risk = score_risk("etkinliği güncelle", tool_names=["calendar.güncelle"])
        assert risk >= 4

    def test_olustur_in_tool_name(self):
        risk = score_risk("etkinlik oluştur", tool_names=["calendar.oluştur"])
        assert risk >= 3

    def test_iptal_in_tool_name(self):
        risk = score_risk("toplantıyı iptal et", tool_names=["calendar.iptal"])
        assert risk >= 3

    def test_no_risk_for_read_tools(self):
        risk = score_risk("listele", tool_names=["calendar.list"])
        assert risk == 0

    def test_sil_still_max_risk(self):
        risk = score_risk("sil", tool_names=["calendar.sil"])
        assert risk == 5
