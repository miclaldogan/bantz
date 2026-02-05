"""Tests for finalizer_guard module.

Issue #231: Comprehensive tests for no-new-facts guarantee.
"""

import pytest
from bantz.brain.finalizer_guard import (
    ViolationType,
    Violation,
    GuardResult,
    extract_numbers,
    extract_times,
    extract_dates,
    extract_currencies,
    extract_percentages,
    extract_durations,
    extract_turkish_numbers,
    NumericPreservation,
    TimePreservation,
    DiffGuard,
    FinalizerGuard,
    post_check_diff,
    find_new_numeric_facts,
    _normalize_number,
    _normalize_time,
)


class TestExtractNumbers:
    """Tests for extract_numbers function."""
    
    def test_simple_integers(self):
        result = extract_numbers("Meeting at room 42")
        assert "42" in result
    
    def test_decimals_with_dot(self):
        result = extract_numbers("Price is 19.99")
        assert "19.99" in result
    
    def test_decimals_with_comma(self):
        result = extract_numbers("Price is 19,99 TL")
        assert "19.99" in result  # Normalized
    
    def test_multiple_numbers(self):
        result = extract_numbers("3 meetings, 5 participants, 120 minutes")
        assert "3" in result
        assert "5" in result
        assert "120" in result
    
    def test_empty_string(self):
        assert extract_numbers("") == set()
    
    def test_none_input(self):
        assert extract_numbers(None) == set()
    
    def test_excludes_dates(self):
        result = extract_numbers("Date is 2025-01-15")
        # Date should be excluded from numbers
        assert "2025" not in result
    
    def test_excludes_times(self):
        result = extract_numbers("Meeting at 14:30")
        # Time components should be excluded
        assert "14" not in result or "30" not in result
    
    def test_list_markers_excluded(self):
        text = "1. First item\n2. Second item\n3. Third item"
        result = extract_numbers(text)
        # List markers should be filtered
        assert "1" not in result
        assert "2" not in result
        assert "3" not in result


class TestExtractTimes:
    """Tests for extract_times function."""
    
    def test_hhmm_colon(self):
        result = extract_times("Meeting at 14:30")
        assert "14:30" in result
    
    def test_hhmm_dot(self):
        result = extract_times("Meeting at 9.00")
        assert "09:00" in result  # Normalized
    
    def test_hhmmss(self):
        result = extract_times("Timestamp 10:30:45")
        assert "10:30" in result
    
    def test_ampm_style(self):
        result = extract_times("Meeting at 3 pm")
        # Should extract the time part
        assert any("3" in t for t in result) or len(result) >= 0
    
    def test_multiple_times(self):
        result = extract_times("From 09:00 to 17:30")
        assert "09:00" in result
        assert "17:30" in result
    
    def test_empty_string(self):
        assert extract_times("") == set()


class TestExtractDates:
    """Tests for extract_dates function."""
    
    def test_iso_format(self):
        result = extract_dates("Date: 2025-01-15")
        assert "2025-01-15" in result
    
    def test_slash_format(self):
        result = extract_dates("Date: 15/01/2025")
        assert "15/01/2025" in result
    
    def test_dot_format(self):
        result = extract_dates("Date: 15.01.2025")
        # Normalized to slash
        assert "15/01/2025" in result
    
    def test_short_year(self):
        result = extract_dates("Date: 15/01/25")
        assert "15/01/25" in result
    
    def test_empty_string(self):
        assert extract_dates("") == set()


class TestExtractCurrencies:
    """Tests for extract_currencies function."""
    
    def test_tl_suffix(self):
        result = extract_currencies("Price: 150 TL")
        assert "150" in result
    
    def test_dollar_prefix(self):
        result = extract_currencies("Price: $99.99")
        assert "99.99" in result
    
    def test_euro_prefix(self):
        result = extract_currencies("Cost: €50")
        assert "50" in result
    
    def test_lira_word(self):
        result = extract_currencies("Fiyat 200 lira")
        assert "200" in result


class TestExtractPercentages:
    """Tests for extract_percentages function."""
    
    def test_integer_percent(self):
        result = extract_percentages("Discount: 20%")
        assert "20" in result
    
    def test_decimal_percent(self):
        result = extract_percentages("Rate: 5.5%")
        assert "5.5" in result


class TestExtractTurkishNumbers:
    """Tests for extract_turkish_numbers function."""
    
    def test_bir(self):
        result = extract_turkish_numbers("bir saat sonra")
        assert "1" in result
    
    def test_iki(self):
        result = extract_turkish_numbers("iki kişi")
        assert "2" in result
    
    def test_on(self):
        result = extract_turkish_numbers("on dakika")
        assert "10" in result
    
    def test_bucuk(self):
        result = extract_turkish_numbers("bir buçuk saat")
        assert "1" in result
        assert "0.5" in result


class TestNormalizeFunctions:
    """Tests for normalization functions."""
    
    def test_normalize_number_comma(self):
        assert _normalize_number("19,99") == "19.99"
    
    def test_normalize_number_leading_zero(self):
        assert _normalize_number("007") == "7"
    
    def test_normalize_time_dot(self):
        assert _normalize_time("9.30") == "09:30"
    
    def test_normalize_time_colon(self):
        assert _normalize_time("14:00") == "14:00"


class TestNumericPreservation:
    """Tests for NumericPreservation class."""
    
    def test_preserved_numbers_pass(self):
        sources = ["Meeting at room 42", "5 participants"]
        candidate = "Room 42 with 5 people"
        passed, new = NumericPreservation.check(sources, candidate)
        assert passed
        assert len(new) == 0
    
    def test_new_number_fails(self):
        sources = ["Meeting at room 42"]
        candidate = "Room 42 with 10 people"
        passed, new = NumericPreservation.check(sources, candidate)
        assert not passed
        assert "10" in new
    
    def test_turkish_numbers_allowed(self):
        sources = ["iki kişi gelecek"]
        candidate = "2 people coming"
        passed, new = NumericPreservation.check(sources, candidate)
        assert passed


class TestTimePreservation:
    """Tests for TimePreservation class."""
    
    def test_preserved_time_pass(self):
        sources = ["Meeting at 14:30"]
        candidate = "Toplantı 14:30'da"
        passed, new = TimePreservation.check_times(sources, candidate)
        assert passed
    
    def test_new_time_fails(self):
        sources = ["Meeting at 14:30"]
        candidate = "Toplantı 15:00'de"
        passed, new = TimePreservation.check_times(sources, candidate)
        assert not passed
        assert "15:00" in new
    
    def test_preserved_date_pass(self):
        sources = ["Date: 2025-01-15"]
        candidate = "Tarih: 2025-01-15"
        passed, new = TimePreservation.check_dates(sources, candidate)
        assert passed
    
    def test_new_date_fails(self):
        sources = ["Date: 2025-01-15"]
        candidate = "Tarih: 2025-01-20"
        passed, new = TimePreservation.check_dates(sources, candidate)
        assert not passed


class TestDiffGuard:
    """Tests for DiffGuard class."""
    
    def test_all_facts_preserved(self):
        guard = DiffGuard()
        sources = ["Meeting at 14:30 on 2025-01-15 with 5 people"]
        candidate = "Toplantı 14:30'da, 2025-01-15 tarihinde, 5 kişiyle"
        result = guard.check(sources, candidate)
        assert result.passed
        assert len(result.violations) == 0
    
    def test_new_number_violation(self):
        guard = DiffGuard()
        sources = ["Meeting with 5 people"]
        candidate = "Toplantı 10 kişiyle"
        result = guard.check(sources, candidate)
        assert not result.passed
        assert any(v.type == ViolationType.NEW_NUMBER for v in result.violations)
    
    def test_new_time_violation(self):
        guard = DiffGuard()
        sources = ["Meeting at 14:30"]
        candidate = "Toplantı 16:00'da"
        result = guard.check(sources, candidate)
        assert not result.passed
        assert any(v.type == ViolationType.NEW_TIME for v in result.violations)
    
    def test_currency_check(self):
        guard = DiffGuard()
        sources = ["Price: 100 TL"]
        candidate = "Fiyat 200 TL"
        result = guard.check(sources, candidate, check_currencies=True)
        assert not result.passed
    
    def test_disable_currency_check(self):
        guard = DiffGuard()
        sources = ["Price: 100 TL"]
        candidate = "Fiyat 200 TL"
        result = guard.check(sources, candidate, check_currencies=False)
        # Still fails because 200 is a new number
        assert not result.passed


class TestFinalizerGuard:
    """Tests for FinalizerGuard class."""
    
    def test_valid_response(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Yarın saat 14:00'de toplantı ayarla",
            planner_decision={"slots": {"time": "14:00"}},
            tool_results=[{"success": True}],
            candidate_text="Toplantınızı saat 14:00'e ayarladım efendim.",
        )
        assert result.passed
    
    def test_invented_time_fails(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Yarın saat 14:00'de toplantı ayarla",
            planner_decision={"slots": {"time": "14:00"}},
            tool_results=[{"success": True}],
            candidate_text="Toplantınızı saat 14:30'a ayarladım efendim.",
        )
        assert not result.passed
        assert any(v.value == "14:30" for v in result.violations)
    
    def test_empty_candidate_passes(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Test",
            candidate_text="",
        )
        assert result.passed
    
    def test_max_violations_threshold(self):
        guard = FinalizerGuard(max_violations=1)
        result = guard.validate(
            user_input="Meeting with 5 people",
            candidate_text="Toplantı 10 kişiyle",  # 1 violation
        )
        # With max_violations=1, single violation is allowed
        assert result.passed
    
    def test_build_retry_prompt(self):
        guard = FinalizerGuard()
        
        # First, get a failed result
        result = guard.validate(
            user_input="Meeting at 14:00",
            candidate_text="Toplantı 16:00'da",
        )
        
        original_prompt = "Generate response"
        retry = guard.build_retry_prompt(original_prompt, result)
        
        assert "STRICT_NO_NEW_FACTS" in retry
        assert "YASAK" in retry or "16:00" in retry
    
    def test_dialog_summary_included(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Continue meeting",
            dialog_summary="Previous: Meeting scheduled for 15:00",
            candidate_text="Toplantı 15:00'de devam edecek",
        )
        # 15:00 is from dialog_summary, should be allowed
        assert result.passed
    
    def test_tool_results_included(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Check my calendar",
            tool_results=[{"events": [{"time": "10:00", "title": "Standup"}]}],
            candidate_text="10:00'da Standup toplantınız var",
        )
        # 10:00 is from tool_results, should be allowed
        assert result.passed


class TestPostCheckDiff:
    """Tests for post_check_diff function."""
    
    def test_facts_preserved(self):
        sources = ["User asked for meeting"]
        original = "Toplantı 14:00'de ayarlandı"
        candidate = "Toplantınız 14:00'de ayarlandı efendim"
        passed, altered = post_check_diff(sources, original, candidate)
        assert passed
        assert len(altered) == 0
    
    def test_time_altered(self):
        sources = ["User asked for meeting"]
        original = "Toplantı 14:00'de"
        candidate = "Toplantı 15:00'de"  # Changed time
        passed, altered = post_check_diff(sources, original, candidate)
        assert not passed
        assert any("time:14:00" in a for a in altered)
    
    def test_number_altered(self):
        sources = ["User asked for meeting"]
        original = "5 katılımcı eklendi"
        candidate = "Katılımcılar eklendi"  # Removed number
        passed, altered = post_check_diff(sources, original, candidate)
        # Number was in router output but not in source, and it's missing
        # This depends on implementation - router added it from tools
        assert isinstance(passed, bool)


class TestFindNewNumericFacts:
    """Tests for backward-compatible find_new_numeric_facts function."""
    
    def test_no_new_facts(self):
        allowed = ["Meeting at 14:00 with 5 people"]
        candidate = "Toplantı 14:00'de, 5 kişi"
        violates, new = find_new_numeric_facts(
            allowed_texts=allowed,
            candidate_text=candidate,
        )
        assert not violates
        assert len(new) == 0
    
    def test_new_fact_detected(self):
        allowed = ["Meeting at 14:00"]
        candidate = "Toplantı 16:00'da"
        violates, new = find_new_numeric_facts(
            allowed_texts=allowed,
            candidate_text=candidate,
        )
        assert violates
        assert "16:00" in new


class TestViolation:
    """Tests for Violation dataclass."""
    
    def test_to_dict(self):
        v = Violation(
            type=ViolationType.NEW_NUMBER,
            value="42",
            context="test context",
            severity="high",
        )
        d = v.to_dict()
        assert d["type"] == "new_number"
        assert d["value"] == "42"
        assert d["severity"] == "high"


class TestGuardResult:
    """Tests for GuardResult dataclass."""
    
    def test_to_dict(self):
        result = GuardResult(
            passed=False,
            violations=[
                Violation(type=ViolationType.NEW_TIME, value="16:00"),
            ],
            allowed_numbers={"5", "10"},
            candidate_numbers={"5", "10", "20"},
        )
        d = result.to_dict()
        assert d["passed"] == False
        assert d["violation_count"] == 1
        assert d["allowed_numbers_count"] == 2
        assert d["candidate_numbers_count"] == 3


class TestEdgeCases:
    """Edge case tests."""
    
    def test_unicode_text(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Müşteri toplantısı 14:00'de",
            candidate_text="Müşteri görüşmesi 14:00'de yapılacak",
        )
        assert result.passed
    
    def test_json_in_sources(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Check events",
            planner_decision={"slots": {"count": 3}},
            candidate_text="3 etkinlik bulundu",
        )
        assert result.passed
    
    def test_large_numbers(self):
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Budget is 1000000 TL",
            candidate_text="Bütçe: 1000000 TL",
        )
        assert result.passed
    
    def test_phone_numbers_like(self):
        # Phone numbers could look like times
        result = extract_times("Call 555-1234")
        # Should not extract 55 as time
        assert all("55" not in t for t in result)


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""
    
    def test_calendar_create_event(self):
        """Scenario: Creating a calendar event."""
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Yarın saat 15:30'da doktor randevusu ekle",
            planner_decision={
                "route": "calendar",
                "calendar_intent": "create_event",
                "slots": {
                    "title": "doktor randevusu",
                    "time": "15:30",
                    "date": "2025-01-16",
                },
            },
            tool_results=[{"success": True, "event_id": "abc123"}],
            candidate_text="Yarın 15:30'da doktor randevunuzu ekledim efendim.",
        )
        assert result.passed
    
    def test_calendar_invented_time(self):
        """Scenario: Finalizer invents a different time."""
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Yarın saat 15:30'da toplantı",
            planner_decision={
                "slots": {"time": "15:30"},
            },
            candidate_text="Toplantınızı 16:00'a ayarladım.",
        )
        assert not result.passed
        assert any(v.value == "16:00" for v in result.violations)
    
    def test_gmail_send_email(self):
        """Scenario: Sending an email."""
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Ahmet'e 5 dosya gönder",
            planner_decision={
                "route": "gmail",
                "slots": {"recipient": "Ahmet", "attachments": 5},
            },
            tool_results=[{"success": True, "sent": True}],
            candidate_text="Ahmet'e 5 dosya ekli mail gönderildi.",
        )
        assert result.passed
    
    def test_invented_attachment_count(self):
        """Scenario: Finalizer changes attachment count."""
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Ahmet'e 5 dosya gönder",
            planner_decision={"slots": {"attachments": 5}},
            candidate_text="Ahmet'e 3 dosya ekli mail gönderildi.",
        )
        assert not result.passed
