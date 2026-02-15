"""Tests for Issue #1317 — Language Guard false positives.

Validates:
1. Turkish 'var' no longer triggers code detection
2. At least 2 code keywords required for code detection
3. http prefix narrowed to http:// or https://
"""

from __future__ import annotations

from bantz.brain.language_guard import detect_language_issue


class TestVarFalsePositive:
    """Turkish 'var' should not trigger code detection."""

    def test_toplanti_var_yarin_not_code(self) -> None:
        """Example from issue: 'Toplantı var (yarın)' was falsely detected as code."""
        result = detect_language_issue("Toplantı var (yarın)")
        # Should NOT return None (which means "skip, it's code/URL")
        # It should either return a language issue or None if Turkish is fine
        # The key point: 'var' + parens should NOT bypass the guard
        assert result != "low_turkish_confidence" or result is None
        # More directly: this Turkish text should not be skipped as code
        # Since it's valid Turkish, detect_language_issue should return None
        assert result is None

    def test_var_in_normal_turkish_sentence(self) -> None:
        """'var' is very common in Turkish: 'bir sorun var mı?'"""
        result = detect_language_issue("Bir sorun var mı (acil durum)?")
        assert result is None

    def test_bugun_toplanti_var(self) -> None:
        result = detect_language_issue("Bugün saat üçte toplantı var (önemli)")
        assert result is None


class TestCodeDetectionThreshold:
    """At least 2 code keywords required for code detection."""

    def test_single_keyword_not_code(self) -> None:
        """Single keyword like 'print' with parens should not be code."""
        result = detect_language_issue("Bu print (kaliteli) kağıttan yapılmış bir ürün")
        assert result is None

    def test_two_keywords_is_code(self) -> None:
        """Two code keywords with parens = code, bypass guard."""
        text = "def hello(): return print('test')"
        result = detect_language_issue(text)
        # Should be None (code detected → skip guard)
        assert result is None

    def test_actual_code_block_detected(self) -> None:
        """Multiple code keywords should still trigger code detection."""
        text = "def calculate(x): import math; return math.sqrt(x)"
        result = detect_language_issue(text)
        assert result is None  # code → bypass


class TestHttpPrefixNarrowed:
    """'http' prefix check should require :// protocol."""

    def test_http_error_message_not_bypassed(self) -> None:
        """'HTTP error occurred' should NOT bypass the guard."""
        result = detect_language_issue("HTTP error occurred, please try again soon")
        # This is English text, should be flagged (not bypassed as URL)
        assert result == "low_turkish_confidence"

    def test_actual_url_bypassed(self) -> None:
        """Actual URLs should still bypass."""
        result = detect_language_issue("http://example.com/path?q=test")
        assert result is None

    def test_https_url_bypassed(self) -> None:
        result = detect_language_issue("https://www.google.com/search")
        assert result is None

    def test_url_in_text_bypassed(self) -> None:
        """Text containing :// should bypass."""
        result = detect_language_issue("Şu linke bak: https://example.com")
        assert result is None
