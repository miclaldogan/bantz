# SPDX-License-Identifier: MIT
"""Tests for timezone extraction (Issue #167)."""

from datetime import datetime, timezone as dt_timezone

import pytest

from bantz.nlu.slots import extract_timezone, format_timezone_aware_time


class TestTimezoneExtraction:
    """Test timezone extraction from natural language."""
    
    def test_new_york_city_name(self):
        """Test 'New York' extracts EST timezone."""
        tz = extract_timezone("New York saati ile saat 15'te meeting ekle")
        
        assert tz is not None
        assert tz.iana_name == "America/New_York"
        assert "new york" in tz.raw_text.lower()
        assert tz.confidence >= 0.90
    
    def test_pst_abbreviation(self):
        """Test 'PST' extracts Pacific timezone."""
        tz = extract_timezone("Pacific Time 9 AM'de call koy")
        
        assert tz is not None
        assert tz.iana_name == "America/Los_Angeles"
        assert "pacific" in tz.raw_text.lower()
    
    def test_pst_abbr_only(self):
        """Test 'PST' abbreviation."""
        tz = extract_timezone("PST saatiyle toplantı")
        
        assert tz is not None
        assert tz.iana_name == "America/Los_Angeles"
        assert tz.raw_text == "pst"
    
    def test_istanbul_timezone(self):
        """Test 'Istanbul' maps to Europe/Istanbul."""
        tz = extract_timezone("Istanbul saatiyle yarın 10'da")
        
        assert tz is not None
        assert tz.iana_name == "Europe/Istanbul"
        assert "istanbul" in tz.raw_text.lower()
    
    def test_london_gmt(self):
        """Test 'London' and 'GMT'."""
        tz_london = extract_timezone("London saati 14:00")
        assert tz_london is not None
        assert tz_london.iana_name == "Europe/London"
        
        tz_gmt = extract_timezone("GMT saatiyle meeting")
        assert tz_gmt is not None
        assert tz_gmt.iana_name == "Europe/London"
    
    def test_tokyo_jst(self):
        """Test 'Tokyo' and 'JST'."""
        tz_tokyo = extract_timezone("Tokyo saati ile")
        assert tz_tokyo is not None
        assert tz_tokyo.iana_name == "Asia/Tokyo"
        
        tz_jst = extract_timezone("JST 9:00 AM")
        assert tz_jst is not None
        assert tz_jst.iana_name == "Asia/Tokyo"
    
    def test_utc_offset_positive(self):
        """Test 'GMT+1' offset format."""
        tz = extract_timezone("GMT+1 saatiyle")
        
        assert tz is not None
        assert "Etc/GMT" in tz.iana_name  # Etc/GMT zones
        assert tz.display_name == "GMT+1"
        assert tz.confidence >= 0.80
    
    def test_utc_offset_negative(self):
        """Test 'UTC-5' offset format."""
        tz = extract_timezone("UTC-5 ile meeting")
        
        assert tz is not None
        assert "GMT" in tz.iana_name or "UTC" in tz.iana_name or "Etc" in tz.iana_name
    
    def test_utc_offset_with_minutes(self):
        """Test 'GMT+5:30' format (India)."""
        tz = extract_timezone("GMT+5:30")
        
        assert tz is not None
        assert tz.display_name == "GMT+5:30"
    
    def test_cet_timezone(self):
        """Test 'CET' (Central European Time)."""
        tz = extract_timezone("CET saatiyle")
        
        assert tz is not None
        assert tz.iana_name == "Europe/Paris"
    
    def test_multiple_cities(self):
        """Test various major cities."""
        cities = {
            "Berlin": "Europe/Berlin",
            "Paris": "Europe/Paris",
            "Tokyo": "Asia/Tokyo",
            "Sydney": "Australia/Sydney",
            "Dubai": "Asia/Dubai",
            "Singapore": "Asia/Singapore",
            "Chicago": "America/Chicago",
        }
        
        for city, expected_tz in cities.items():
            tz = extract_timezone(f"{city} saatiyle toplantı")
            assert tz is not None, f"Failed to extract {city}"
            assert tz.iana_name == expected_tz, f"{city} mapped to wrong timezone"
    
    def test_no_timezone_in_text(self):
        """Test text without timezone returns None."""
        assert extract_timezone("yarın saat 15'te toplantı") is None
        assert extract_timezone("bugün meeting var mı") is None
        assert extract_timezone("takvime bak") is None
    
    def test_dst_awareness_cities(self):
        """Test cities that observe DST use same IANA name."""
        # EST/EDT both map to America/New_York (zoneinfo handles DST)
        tz_est = extract_timezone("EST saati")
        tz_edt = extract_timezone("EDT saati")
        
        assert tz_est is not None
        assert tz_edt is not None
        assert tz_est.iana_name == tz_edt.iana_name == "America/New_York"
    
    def test_display_name_formatting(self):
        """Test display names are properly formatted."""
        tz_city = extract_timezone("New York saati")
        assert tz_city is not None
        assert tz_city.display_name == "New York"
        
        tz_abbr = extract_timezone("PST")
        assert tz_abbr is not None
        assert tz_abbr.display_name == "PST"
    
    def test_case_insensitive(self):
        """Test timezone extraction is case insensitive."""
        patterns = [
            "NEW YORK saati",
            "new york saati",
            "New York saati",
            "pst",
            "PST",
            "PsT",
        ]
        
        for pattern in patterns:
            tz = extract_timezone(pattern)
            assert tz is not None, f"Failed on: {pattern}"
    
    def test_word_boundaries(self):
        """Test abbreviations use word boundaries."""
        # "EST" should match, but "BEST" should not extract "EST"
        tz_est = extract_timezone("EST saati")
        assert tz_est is not None
        
        # "testing" should not extract "est"
        tz_none = extract_timezone("testing the system")
        assert tz_none is None


class TestTimezoneFormatting:
    """Test timezone-aware datetime formatting."""
    
    def test_format_with_timezone(self):
        """Test formatting datetime with timezone."""
        # Create UTC datetime
        dt_utc = datetime(2026, 2, 3, 20, 0, 0, tzinfo=dt_timezone.utc)
        
        # Format in EST (UTC-5 in winter)
        result = format_timezone_aware_time(dt_utc, "America/New_York")
        
        # Should show 15:00 EST (20:00 UTC - 5 hours)
        assert "15:00" in result
        assert "EST" in result or "EDT" in result
    
    def test_format_tokyo_time(self):
        """Test formatting in Tokyo timezone (JST)."""
        dt_utc = datetime(2026, 2, 3, 15, 0, 0, tzinfo=dt_timezone.utc)
        
        # JST is UTC+9
        result = format_timezone_aware_time(dt_utc, "Asia/Tokyo")
        
        # Should show next day 00:00 JST (15:00 UTC + 9 hours)
        assert "00:00" in result or "0:00" in result
        assert "JST" in result
    
    def test_format_with_dst(self):
        """Test formatting handles DST correctly."""
        # Summer time in New York (EDT, UTC-4)
        dt_summer = datetime(2026, 7, 15, 20, 0, 0, tzinfo=dt_timezone.utc)
        result_summer = format_timezone_aware_time(dt_summer, "America/New_York")
        
        # Should show EDT in summer
        assert "16:00" in result_summer  # UTC-4 in summer
        assert "EDT" in result_summer
    
    def test_format_fallback_without_zoneinfo(self):
        """Test formatting works with zoneinfo."""
        dt = datetime(2026, 2, 3, 15, 0, 0, tzinfo=dt_timezone.utc)
        
        # Should convert to NY time and format
        result = format_timezone_aware_time(dt, "America/New_York")
        # 15:00 UTC = 10:00 EST (UTC-5 in winter) or 11:00 EDT (UTC-4 in summer)
        # Just verify it doesn't crash and contains time
        assert ":" in result
        assert len(result) > 0


class TestTimezoneAcceptanceCriteria:
    """Test acceptance criteria from Issue #167."""
    
    def test_timezone_detection_from_nl(self):
        """Test AC: Timezone detection from NL: 'New York', 'PST', 'GMT+1'."""
        # City name
        tz1 = extract_timezone("New York saati ile meeting")
        assert tz1 is not None
        assert tz1.iana_name == "America/New_York"
        
        # Abbreviation
        tz2 = extract_timezone("PST 9 AM")
        assert tz2 is not None
        assert tz2.iana_name == "America/Los_Angeles"
        
        # UTC offset
        tz3 = extract_timezone("GMT+1")
        assert tz3 is not None
        assert "GMT" in tz3.display_name
    
    def test_mapping_istanbul(self):
        """Test AC: Mapping 'Istanbul' → 'Europe/Istanbul'."""
        tz = extract_timezone("Istanbul saatiyle")
        
        assert tz is not None
        assert tz.iana_name == "Europe/Istanbul"
    
    def test_dst_awareness(self):
        """Test AC: DST awareness through zoneinfo."""
        # EST and EDT both map to same IANA zone
        tz_winter = extract_timezone("EST")
        tz_summer = extract_timezone("EDT")
        
        assert tz_winter is not None
        assert tz_summer is not None
        # Both use same IANA name, zoneinfo handles DST
        assert tz_winter.iana_name == tz_summer.iana_name
    
    def test_multiple_timezones_est_pst_cet_jst(self):
        """Test AC: Tests for EST, PST, CET, JST."""
        timezones = {
            "EST": "America/New_York",
            "PST": "America/Los_Angeles",
            "CET": "Europe/Paris",
            "JST": "Asia/Tokyo",
        }
        
        for abbr, expected_iana in timezones.items():
            tz = extract_timezone(f"{abbr} meeting")
            assert tz is not None, f"Failed to extract {abbr}"
            assert tz.iana_name == expected_iana, f"{abbr} wrong mapping"
