# SPDX-License-Identifier: MIT
"""Tests for Issue #1256: Fuzzy mail keyword matching.

_match_mail_by_keyword should fall back to fuzzy matching (SequenceMatcher
≥ 0.75) when the exact substring check finds no hit, catching common typos
like "tübirak" → "tübitak" or "hackaton" → "hackathon".
"""

from __future__ import annotations

import pytest

from bantz.brain.orchestrator_loop import _match_mail_by_keyword, _fuzzy_token_match, _turkish_lower


# Shared test messages -------------------------------------------------------

_MESSAGES = [
    {"id": "m1", "subject": "TÜBİTAK Proje Onayı", "from": "bilgi@tubitak.gov.tr"},
    {"id": "m2", "subject": "GitHub Actions CI failure", "from": "noreply@github.com"},
    {"id": "m3", "subject": "Hackathon davetiyesi", "from": "info@hackathon.io"},
    {"id": "m4", "subject": "Toplantı notu", "from": "ahmet@company.com"},
]


# ============================================================================
# Exact matching (regression)
# ============================================================================
class TestExactMatchRegression:
    """Existing exact substring matching should still work."""

    def test_exact_github(self) -> None:
        result = _match_mail_by_keyword("github mailinin içeriğini özetle", _MESSAGES)
        assert result == "m2"

    def test_exact_tubitak(self) -> None:
        result = _match_mail_by_keyword("tübitak maili", _MESSAGES)
        assert result == "m1"

    def test_exact_toplanti(self) -> None:
        result = _match_mail_by_keyword("toplantı mailini göster", _MESSAGES)
        assert result == "m4"

    def test_no_match_returns_none(self) -> None:
        result = _match_mail_by_keyword("spotify maili", _MESSAGES)
        assert result is None

    def test_empty_input(self) -> None:
        assert _match_mail_by_keyword("", _MESSAGES) is None
        assert _match_mail_by_keyword(None, _MESSAGES) is None

    def test_empty_messages(self) -> None:
        assert _match_mail_by_keyword("github maili", []) is None


# ============================================================================
# Fuzzy matching (Issue #1256)
# ============================================================================
class TestFuzzyMatch:
    """Fuzzy fallback catches common typos."""

    def test_tubirak_matches_tubitak(self) -> None:
        """'tübirak' should fuzzy-match 'tübitak' (1 char diff)."""
        result = _match_mail_by_keyword("tübirak mailini özetle", _MESSAGES)
        assert result == "m1"

    def test_hackaton_matches_hackathon(self) -> None:
        """'hackaton' should fuzzy-match 'hackathon' (missing 'h')."""
        result = _match_mail_by_keyword("hackaton davetiyesi", _MESSAGES)
        assert result == "m3"

    def test_githup_matches_github(self) -> None:
        """'githup' should fuzzy-match 'github' (b→p)."""
        result = _match_mail_by_keyword("githup mailini oku", _MESSAGES)
        assert result == "m2"

    def test_toplantu_matches_toplanti(self) -> None:
        """'toplantu' should fuzzy-match 'toplantı' (ı→u)."""
        result = _match_mail_by_keyword("toplantu notunu göster", _MESSAGES)
        assert result == "m4"

    def test_very_different_no_match(self) -> None:
        """Completely unrelated keyword should NOT fuzzy-match."""
        result = _match_mail_by_keyword("xyz maili", _MESSAGES)
        assert result is None

    def test_short_keyword_no_fuzzy(self) -> None:
        """Keywords < 3 chars should not trigger fuzzy matching."""
        result = _match_mail_by_keyword("ab maili", _MESSAGES)
        assert result is None


# ============================================================================
# _fuzzy_token_match helper
# ============================================================================
class TestFuzzyTokenMatch:
    """Unit tests for the fuzzy matching helper."""

    def test_exact_word_matches(self) -> None:
        assert _fuzzy_token_match("github", "github actions ci failure") is True

    def test_one_char_diff(self) -> None:
        assert _fuzzy_token_match("tübirak", "tübitak proje onayı") is True

    def test_missing_char(self) -> None:
        assert _fuzzy_token_match("hackaton", "hackathon davetiyesi") is True

    def test_completely_different(self) -> None:
        assert _fuzzy_token_match("spotify", "tübitak proje onayı") is False

    def test_short_keyword_rejected(self) -> None:
        """Keywords < 3 chars should always return False."""
        assert _fuzzy_token_match("ab", "abcdef") is False

    def test_threshold_boundary(self) -> None:
        """Custom threshold should be respected."""
        # "gixxub" vs "github" — ratio ~0.67, below 0.75 default
        assert _fuzzy_token_match("gixxub", "github actions") is False
        # With lower threshold it should match
        assert _fuzzy_token_match("gixxub", "github actions", threshold=0.60) is True

    def test_exact_match_score_higher_than_fuzzy(self) -> None:
        """When both exact and fuzzy candidates exist, exact wins."""
        messages = [
            {"id": "exact", "subject": "github notification", "from": "a@b.com"},
            {"id": "fuzzy", "subject": "githup notification", "from": "c@d.com"},
        ]
        result = _match_mail_by_keyword("github mailini göster", messages)
        assert result == "exact"


# ============================================================================
# Turkish İ lowering
# ============================================================================
class TestTurkishLower:
    """_turkish_lower strips combining dot from İ→i̇ lowering."""

    def test_tubitak(self) -> None:
        assert _turkish_lower("TÜBİTAK") == "tübitak"

    def test_istanbul(self) -> None:
        assert _turkish_lower("İSTANBUL") == "istanbul"

    def test_ascii_unchanged(self) -> None:
        assert _turkish_lower("GitHub") == "github"

    def test_combined_text(self) -> None:
        result = _turkish_lower("TÜBİTAK Proje İnceleme")
        assert "tübitak" in result
        assert "inceleme" in result
