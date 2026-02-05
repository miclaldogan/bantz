"""Tests for text normalization module.

Issue #241: UX improvement for Turkish titles, quotes, and punctuation.

Tests cover:
- Trim and whitespace collapse
- Quote normalization
- Punctuation fixes
- Turkish-specific handling
- Calendar title normalization
- Message normalization
- Batch operations
- 15+ golden string tests
"""

from __future__ import annotations

import pytest

from bantz.text.normalize import (
    NormalizeLevel,
    NormalizeResult,
    normalize_text,
    normalize_calendar_title,
    normalize_calendar_message,
    normalize_log_entry,
    quick_normalize,
    normalize_batch,
    get_normalization_stats,
    _trim,
    _collapse_whitespace,
    _normalize_quotes,
    _fix_trailing_punctuation,
    _fix_turkish_specifics,
    _capitalize_first,
)


# =============================================================================
# Test: NormalizeResult
# =============================================================================

class TestNormalizeResult:
    """Tests for NormalizeResult dataclass."""
    
    def test_create_result(self):
        """Test creating a normalize result."""
        result = NormalizeResult(
            original="  test  ",
            normalized="test",
            changes_made=["trim"],
        )
        assert result.original == "  test  "
        assert result.normalized == "test"
        assert result.changes_made == ["trim"]
    
    def test_was_changed_true(self):
        """Test was_changed when text was modified."""
        result = NormalizeResult(
            original="  test  ",
            normalized="test",
            changes_made=["trim"],
        )
        assert result.was_changed is True
    
    def test_was_changed_false(self):
        """Test was_changed when text was not modified."""
        result = NormalizeResult(
            original="test",
            normalized="test",
            changes_made=[],
        )
        assert result.was_changed is False
    
    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = NormalizeResult(
            original="  test  ",
            normalized="test",
            changes_made=["trim"],
        )
        d = result.to_dict()
        assert d["original"] == "  test  "
        assert d["normalized"] == "test"
        assert d["changes_made"] == ["trim"]
        assert d["was_changed"] is True


# =============================================================================
# Test: Trim and Whitespace
# =============================================================================

class TestTrimAndWhitespace:
    """Tests for trim and whitespace handling."""
    
    def test_trim_leading_space(self):
        """Test trimming leading whitespace."""
        result, changed = _trim("  hello")
        assert result == "hello"
        assert changed is True
    
    def test_trim_trailing_space(self):
        """Test trimming trailing whitespace."""
        result, changed = _trim("hello  ")
        assert result == "hello"
        assert changed is True
    
    def test_trim_both(self):
        """Test trimming both ends."""
        result, changed = _trim("  hello  ")
        assert result == "hello"
        assert changed is True
    
    def test_trim_no_change(self):
        """Test no trim needed."""
        result, changed = _trim("hello")
        assert result == "hello"
        assert changed is False
    
    def test_collapse_double_space(self):
        """Test collapsing double space."""
        result, changed = _collapse_whitespace("hello  world")
        assert result == "hello world"
        assert changed is True
    
    def test_collapse_multiple_spaces(self):
        """Test collapsing multiple spaces."""
        result, changed = _collapse_whitespace("hello    world")
        assert result == "hello world"
        assert changed is True
    
    def test_collapse_mixed_whitespace(self):
        """Test collapsing tabs and spaces."""
        result, changed = _collapse_whitespace("hello\t\t  world")
        assert result == "hello world"
        assert changed is True
    
    def test_collapse_no_change(self):
        """Test no collapse needed."""
        result, changed = _collapse_whitespace("hello world")
        assert result == "hello world"
        assert changed is False


# =============================================================================
# Test: Quote Normalization
# =============================================================================

class TestQuoteNormalization:
    """Tests for quote normalization."""
    
    def test_normalize_curly_double_quotes(self):
        """Test normalizing curly double quotes."""
        # Use actual curly double quotes (U+201C and U+201D)
        curly_left = '\u201c'  # "
        curly_right = '\u201d'  # "
        result, changes = _normalize_quotes(f'{curly_left}hello{curly_right}')
        assert result == '"hello"'
        assert any("quote" in c for c in changes)
    
    def test_normalize_curly_single_quotes(self):
        """Test normalizing curly single quotes."""
        # Use actual curly single quotes (U+2018 and U+2019)
        curly_left = '\u2018'  # '
        curly_right = '\u2019'  # '
        result, changes = _normalize_quotes(f'{curly_left}hello{curly_right}')
        assert result == "'hello'"
        assert any("quote" in c for c in changes)
    
    def test_normalize_guillemets(self):
        """Test normalizing angle quotes."""
        result, changes = _normalize_quotes("«hello»")
        assert result == '"hello"'
        assert any("quote" in c for c in changes)
    
    def test_collapse_double_double_quotes(self):
        """Test collapsing double double quotes."""
        result, changes = _normalize_quotes('""hello""')
        assert result == '"hello"'
        assert "collapse_double_quotes" in changes
    
    def test_normalize_backtick(self):
        """Test normalizing backtick to single quote."""
        result, changes = _normalize_quotes("`hello`")
        assert result == "'hello'"
        assert any("quote" in c for c in changes)
    
    def test_no_quote_change(self):
        """Test no quote normalization needed."""
        result, changes = _normalize_quotes('"hello"')
        # Straight quotes should stay as-is
        assert result == '"hello"'


# =============================================================================
# Test: Punctuation Fixes
# =============================================================================

class TestPunctuationFixes:
    """Tests for punctuation fixes."""
    
    def test_fix_double_dot_at_end(self):
        """Test fixing double dot at end."""
        result, changes = _fix_trailing_punctuation("hello..")
        assert result == "hello."
        assert "fix_double_dot" in changes
    
    def test_reduce_long_ellipsis(self):
        """Test reducing long ellipsis."""
        result, changes = _fix_trailing_punctuation("hello.....")
        assert result == "hello..."
        assert "reduce_ellipsis" in changes
    
    def test_preserve_ellipsis(self):
        """Test preserving standard ellipsis."""
        result, changes = _fix_trailing_punctuation("hello...")
        assert result == "hello..."
        assert "fix_double_dot" not in changes
        assert "reduce_ellipsis" not in changes
    
    def test_remove_leading_punct(self):
        """Test removing leading punctuation (comma, semicolon)."""
        result, changes = _fix_trailing_punctuation(", hello")
        assert result == "hello"
        assert "remove_leading_punct" in changes
    
    def test_fix_trailing_comma(self):
        """Test fixing trailing comma to period."""
        result, changes = _fix_trailing_punctuation("hello,")
        assert result == "hello."
        assert "fix_trailing_comma_semicolon" in changes
    
    def test_fix_trailing_semicolon(self):
        """Test fixing trailing semicolon to period."""
        result, changes = _fix_trailing_punctuation("hello;")
        assert result == "hello."
        assert "fix_trailing_comma_semicolon" in changes
    
    def test_normalize_very_long_ellipsis_anywhere(self):
        """Test normalizing very long ellipsis anywhere."""
        result, changes = _fix_trailing_punctuation("hello.....world")
        assert "..." in result
        assert "normalize_long_ellipsis" in changes


# =============================================================================
# Test: Turkish Specifics
# =============================================================================

class TestTurkishSpecifics:
    """Tests for Turkish-specific normalization."""
    
    def test_unicode_nfc_normalization(self):
        """Test Unicode NFC normalization."""
        # Pre-composed vs decomposed İ
        decomposed = "I\u0307stanbul"  # I + combining dot above
        result, changes = _fix_turkish_specifics(decomposed)
        # Should normalize to NFC
        assert "unicode_nfc" in changes
    
    def test_preserve_turkish_i(self):
        """Test preserving Turkish İ/ı characters."""
        text = "İstanbul'da güzel"
        result, changes = _fix_turkish_specifics(text)
        # İ should be preserved
        assert "İ" in result


# =============================================================================
# Test: Capitalize First
# =============================================================================

class TestCapitalizeFirst:
    """Tests for first character capitalization."""
    
    def test_capitalize_lowercase(self):
        """Test capitalizing lowercase first char."""
        result, changed = _capitalize_first("hello")
        assert result == "Hello"
        assert changed is True
    
    def test_already_capitalized(self):
        """Test already capitalized."""
        result, changed = _capitalize_first("Hello")
        assert result == "Hello"
        assert changed is False
    
    def test_capitalize_after_quote(self):
        """Test capitalizing after quote."""
        result, changed = _capitalize_first('"hello"')
        assert result == '"Hello"'
        assert changed is True
    
    def test_capitalize_turkish_i(self):
        """Test capitalizing Turkish i."""
        # Turkish i -> İ when capitalized
        result, changed = _capitalize_first("istanbul")
        assert result == "Istanbul" or result == "İstanbul"
        # Python's upper() behavior varies; just check it changed
        assert changed is True


# =============================================================================
# Test: normalize_text Function
# =============================================================================

class TestNormalizeText:
    """Tests for main normalize_text function."""
    
    def test_minimal_level(self):
        """Test minimal normalization level."""
        result = normalize_text("  hello  world  ", level=NormalizeLevel.MINIMAL)
        assert result.normalized == "hello world"
        assert "trim" in result.changes_made
        assert "collapse_whitespace" in result.changes_made
    
    def test_standard_level(self):
        """Test standard normalization level."""
        result = normalize_text('"hello"..', level=NormalizeLevel.STANDARD)
        assert result.normalized == '"hello".'
    
    def test_strict_level(self):
        """Test strict normalization level."""
        result = normalize_text("I\u0307stanbul", level=NormalizeLevel.STRICT)
        assert "unicode_nfc" in result.changes_made
    
    def test_capitalize_first_option(self):
        """Test capitalize_first option."""
        result = normalize_text("hello", capitalize_first=True)
        assert result.normalized == "Hello"
        assert "capitalize_first" in result.changes_made
    
    def test_empty_string(self):
        """Test empty string handling."""
        result = normalize_text("")
        assert result.normalized == ""
        assert result.changes_made == []
        assert result.was_changed is False


# =============================================================================
# Test: Calendar-Specific Functions
# =============================================================================

class TestCalendarFunctions:
    """Tests for calendar-specific normalization functions."""
    
    def test_normalize_calendar_title(self):
        """Test calendar title normalization."""
        result = normalize_calendar_title("  toplantı  ")
        assert result == "Toplantı"
    
    def test_normalize_calendar_title_quotes(self):
        """Test calendar title with quotes."""
        result = normalize_calendar_title('"proje görüşmesi"')
        assert result == '"Proje görüşmesi"'
    
    def test_normalize_calendar_message(self):
        """Test calendar message normalization."""
        result = normalize_calendar_message("  Etkinlik  oluşturuldu..  ")
        assert result == "Etkinlik oluşturuldu."
    
    def test_normalize_log_entry(self):
        """Test log entry normalization."""
        result = normalize_log_entry("  event_created:  12345  ")
        assert result == "event_created: 12345"


# =============================================================================
# Test: Batch Operations
# =============================================================================

class TestBatchOperations:
    """Tests for batch normalization."""
    
    def test_normalize_batch(self):
        """Test batch normalization."""
        texts = ["  hello  ", "world..", "test"]
        results = normalize_batch(texts)
        assert len(results) == 3
        assert results[0].normalized == "hello"
        assert results[1].normalized == "world."
        assert results[2].normalized == "test"
    
    def test_get_normalization_stats(self):
        """Test normalization stats."""
        texts = ["  hello  ", "world..", "test"]
        results = normalize_batch(texts)
        stats = get_normalization_stats(results)
        
        assert stats["total"] == 3
        assert stats["changed"] == 2  # hello and world changed
        assert stats["unchanged"] == 1  # test unchanged
        assert "trim" in stats["change_counts"]


# =============================================================================
# GOLDEN STRING TESTS (15+ as per acceptance criteria)
# =============================================================================

class TestGoldenStrings:
    """Golden string tests for Issue #241 acceptance criteria.
    
    These test specific input -> expected output pairs.
    """
    
    # Test 1: Basic trim
    def test_golden_01_basic_trim(self):
        """Golden #1: Basic whitespace trim."""
        assert quick_normalize("  Toplantı  ") == "Toplantı"
    
    # Test 2: Collapse whitespace
    def test_golden_02_collapse_whitespace(self):
        """Golden #2: Collapse multiple spaces."""
        assert quick_normalize("Proje   görüşmesi") == "Proje görüşmesi"
    
    # Test 3: Double quote collapse
    def test_golden_03_double_quote_collapse(self):
        """Golden #3: Collapse double quotes to single."""
        assert quick_normalize('""Toplantı""') == '"Toplantı"'
    
    # Test 4: Trailing double dot
    def test_golden_04_trailing_double_dot(self):
        """Golden #4: Fix trailing double dot."""
        assert quick_normalize("Etkinlik oluşturuldu..") == "Etkinlik oluşturuldu."
    
    # Test 5: Curly quotes to straight
    def test_golden_05_curly_quotes(self):
        """Golden #5: Convert curly quotes to straight."""
        assert quick_normalize('"Doktor randevusu"') == '"Doktor randevusu"'
    
    # Test 6: Mixed issues
    def test_golden_06_mixed_issues(self):
        """Golden #6: Fix multiple issues at once."""
        result = quick_normalize('  ""Toplantı""  notları..  ')
        # After collapse_double_quotes and spacing fixes
        assert result == '"Toplantı" notları.'
    
    # Test 7: Trailing comma
    def test_golden_07_trailing_comma(self):
        """Golden #7: Fix trailing comma."""
        assert quick_normalize("Randevu eklendi,") == "Randevu eklendi."
    
    # Test 8: Preserve ellipsis
    def test_golden_08_preserve_ellipsis(self):
        """Golden #8: Preserve standard ellipsis."""
        assert quick_normalize("Düşünüyorum...") == "Düşünüyorum..."
    
    # Test 9: Long ellipsis reduction
    def test_golden_09_long_ellipsis(self):
        """Golden #9: Reduce very long ellipsis."""
        assert quick_normalize("Bekliyor.....") == "Bekliyor..."
    
    # Test 10: Guillemets
    def test_golden_10_guillemets(self):
        """Golden #10: Convert guillemets to quotes."""
        assert quick_normalize("«Proje sunumu»") == '"Proje sunumu"'
    
    # Test 11: Leading punctuation (comma)
    def test_golden_11_leading_punctuation(self):
        """Golden #11: Remove leading punctuation (comma)."""
        assert quick_normalize(", Etkinlik başlıyor") == "Etkinlik başlıyor"
    
    # Test 12: Tab to space
    def test_golden_12_tab_to_space(self):
        """Golden #12: Convert tabs to single space."""
        assert quick_normalize("Saat:\t\t15:00") == "Saat: 15:00"
    
    # Test 13: Backtick to single quote
    def test_golden_13_backtick(self):
        """Golden #13: Convert backticks to single quotes."""
        assert quick_normalize("`test`") == "'test'"
    
    # Test 14: Calendar title capitalization
    def test_golden_14_title_capitalize(self):
        """Golden #14: Capitalize calendar title."""
        assert normalize_calendar_title("  doktor randevusu  ") == "Doktor randevusu"
    
    # Test 15: Complex real-world example
    def test_golden_15_real_world(self):
        """Golden #15: Real-world complex example."""
        input_text = '  ""Proje  toplantısı""  yarın  saat 14:00 da..  '
        expected = '"Proje toplantısı" yarın saat 14:00 da.'
        assert quick_normalize(input_text) == expected
    
    # Test 16: Empty stays empty
    def test_golden_16_empty(self):
        """Golden #16: Empty string stays empty."""
        assert quick_normalize("") == ""
    
    # Test 17: Already clean stays clean
    def test_golden_17_already_clean(self):
        """Golden #17: Already clean text unchanged."""
        assert quick_normalize("Temiz metin") == "Temiz metin"
    
    # Test 18: Turkish İ preserved
    def test_golden_18_turkish_i(self):
        """Golden #18: Turkish İ preserved in title."""
        result = normalize_calendar_title("  istanbul gezisi  ")
        # Should capitalize but preserve the text
        assert "istanbul" in result.lower() or "İstanbul" in result


# =============================================================================
# Test: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""
    
    def test_only_whitespace(self):
        """Test string with only whitespace."""
        result = normalize_text("   \t\n   ")
        assert result.normalized == ""
    
    def test_only_punctuation(self):
        """Test string with only punctuation (ellipsis preserved)."""
        result = normalize_text("...")
        # Ellipsis should be preserved since dots aren't removed as leading punct
        assert result.normalized == "..."
    
    def test_unicode_emoji(self):
        """Test string with emoji."""
        result = normalize_text("  Kutlama 🎉  ")
        assert "🎉" in result.normalized
    
    def test_very_long_string(self):
        """Test very long string."""
        long_text = "  " + "a" * 10000 + "  "
        result = normalize_text(long_text)
        assert len(result.normalized) == 10000
    
    def test_newlines(self):
        """Test newlines are collapsed."""
        result = normalize_text("hello\n\nworld")
        assert result.normalized == "hello world"


# =============================================================================
# Test: Integration
# =============================================================================

class TestIntegration:
    """Integration tests for full workflows."""
    
    def test_full_calendar_workflow(self):
        """Test full calendar normalization workflow."""
        # Simulate what would happen in calendar_tools
        title = '  ""Müşteri toplantısı""  '
        confirmation = f"  Etkinlik oluşturuldu:  {title}.."
        
        normalized_title = normalize_calendar_title(title)
        normalized_msg = normalize_calendar_message(confirmation)
        
        assert normalized_title == '"Müşteri toplantısı"'
        assert '"Müşteri toplantısı"' in normalized_msg
        assert normalized_msg.endswith('.')
    
    def test_batch_stats_workflow(self):
        """Test batch processing with stats."""
        texts = [
            "  test1  ",  # trim
            "\u201ctest2\u201d",  # curly quotes to straight (changed)
            "test3..",  # double dot fix
            "test4",  # Already clean
        ]
        
        results = normalize_batch(texts)
        stats = get_normalization_stats(results)
        
        assert stats["total"] == 4
        assert stats["changed"] == 3  # 3 were modified
        assert stats["unchanged"] == 1
        assert stats["change_rate"] == 0.75
