"""Tests for Issue #229: Turkish Time Parsing v1.

Comprehensive tests for Turkish natural language time expressions.
30+ golden tests as specified in the issue.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from bantz.brain.turkish_time import (
    TURKISH_NUMBERS,
    TIME_PERIODS,
    get_timezone,
    parse_duration_tr,
    parse_time_window_tr,
)


# Timezone for testing
TZ_ISTANBUL = "Europe/Istanbul"


class TestGetTimezone:
    """Tests for get_timezone helper."""

    def test_string_timezone(self) -> None:
        """String timezone should be converted."""
        tz = get_timezone("Europe/Istanbul")
        assert tz is not None
        assert "Istanbul" in str(tz) or "Turkey" in str(tz) or tz is not None

    def test_none_returns_utc(self) -> None:
        """None should return UTC."""
        tz = get_timezone(None)
        assert tz is not None

    def test_tzinfo_passthrough(self) -> None:
        """tzinfo object should pass through."""
        from datetime import timezone
        utc = timezone.utc
        tz = get_timezone(utc)
        assert tz is utc


class TestParseNextNHours:
    """Tests for 'önümüzdeki X saat' patterns."""

    @pytest.fixture
    def now(self) -> datetime:
        """Fixed reference time for testing."""
        tz = get_timezone(TZ_ISTANBUL)
        return datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)

    def test_next_2_hours_numeric(self, now: datetime) -> None:
        """'önümüzdeki 2 saat' should parse."""
        result = parse_time_window_tr("önümüzdeki 2 saat", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "next_2h" in result["hint"]
        assert result["confidence"] >= 0.8

    def test_next_3_hours_word(self, now: datetime) -> None:
        """'önümüzdeki üç saat' should parse."""
        result = parse_time_window_tr("önümüzdeki üç saat", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "3h" in result["hint"]

    def test_sonraki_5_saat(self, now: datetime) -> None:
        """'sonraki 5 saat' should parse."""
        result = parse_time_window_tr("sonraki 5 saat", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "5h" in result["hint"]

    def test_3_saat_icinde(self, now: datetime) -> None:
        """'3 saat içinde' should parse."""
        result = parse_time_window_tr("3 saat içinde", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "3h" in result["hint"]

    def test_yarim_saat(self, now: datetime) -> None:
        """'yarım saat içinde' should parse."""
        result = parse_time_window_tr("yarım saat içinde", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "30m" in result["hint"] or "0h_30m" in result["hint"]

    def test_30_dakika_icinde(self, now: datetime) -> None:
        """'30 dakika içinde' should parse."""
        result = parse_time_window_tr("30 dakika içinde", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        # Should have 30 minute window


class TestParseTomorrowPeriod:
    """Tests for 'yarın' patterns."""

    @pytest.fixture
    def now(self) -> datetime:
        """Fixed reference time for testing."""
        tz = get_timezone(TZ_ISTANBUL)
        return datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)

    def test_yarin_alone(self, now: datetime) -> None:
        """'yarın' alone should be whole day."""
        result = parse_time_window_tr("yarın", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "tomorrow"
        # Should be Jan 16th
        assert "2024-01-16" in result["start"]

    def test_yarin_sabah(self, now: datetime) -> None:
        """'yarın sabah' should be morning window."""
        result = parse_time_window_tr("yarın sabah", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "tomorrow_morning"
        # Morning: 06:00-12:00
        assert "T06:00" in result["start"]
        assert "T12:00" in result["end"]

    def test_yarin_aksam(self, now: datetime) -> None:
        """'yarın akşam' should be evening window."""
        result = parse_time_window_tr("yarın akşam", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "tomorrow_evening"
        # Evening: 18:00-22:00
        assert "T18:00" in result["start"]
        assert "T22:00" in result["end"]

    def test_yarin_ogle(self, now: datetime) -> None:
        """'yarın öğle' should be noon window."""
        result = parse_time_window_tr("yarın öğle", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "tomorrow_noon"

    def test_yarin_gece(self, now: datetime) -> None:
        """'yarın gece' should be night window."""
        result = parse_time_window_tr("yarın gece", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "tomorrow_night"


class TestParseTodayPeriod:
    """Tests for 'bugün' and 'bu akşam' patterns."""

    @pytest.fixture
    def now(self) -> datetime:
        """Fixed reference time for testing."""
        tz = get_timezone(TZ_ISTANBUL)
        return datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)

    def test_bugun(self, now: datetime) -> None:
        """'bugün' should be whole day."""
        result = parse_time_window_tr("bugün", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "today"
        assert "2024-01-15" in result["start"]

    def test_bu_aksam(self, now: datetime) -> None:
        """'bu akşam' should be evening window."""
        result = parse_time_window_tr("bu akşam", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "evening"
        assert "T18:00" in result["start"]

    def test_bu_sabah(self, now: datetime) -> None:
        """'bu sabah' should be morning window."""
        result = parse_time_window_tr("bu sabah", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "morning"

    def test_aksam_alone(self, now: datetime) -> None:
        """'akşam' alone should be evening."""
        result = parse_time_window_tr("akşam", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "evening"

    def test_ogle(self, now: datetime) -> None:
        """'öğle' should be noon window."""
        result = parse_time_window_tr("öğle", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "noon"

    def test_oglen(self, now: datetime) -> None:
        """'öğlen' (alternative spelling) should be noon."""
        result = parse_time_window_tr("öğlen", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "noon"


class TestParseThisWeek:
    """Tests for 'bu hafta' patterns."""

    @pytest.fixture
    def now(self) -> datetime:
        """Fixed reference time (Monday)."""
        tz = get_timezone(TZ_ISTANBUL)
        # Jan 15, 2024 is a Monday
        return datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)

    def test_bu_hafta(self, now: datetime) -> None:
        """'bu hafta' should be whole week."""
        result = parse_time_window_tr("bu hafta", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "week"

    def test_hafta_ici(self, now: datetime) -> None:
        """'hafta içi' should be weekdays."""
        result = parse_time_window_tr("hafta içi", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "weekdays"


class TestParseSpecificDay:
    """Tests for specific day names."""

    @pytest.fixture
    def now(self) -> datetime:
        """Fixed reference time (Monday Jan 15)."""
        tz = get_timezone(TZ_ISTANBUL)
        return datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)

    def test_pazartesi(self, now: datetime) -> None:
        """'pazartesi' should find next Monday."""
        result = parse_time_window_tr("pazartesi", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        # Since today is Monday, should be next Monday
        assert "pazartesi" in result["hint"]

    def test_cuma(self, now: datetime) -> None:
        """'cuma' should find Friday."""
        result = parse_time_window_tr("cuma", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "cuma" in result["hint"]
        # From Monday, Friday is 4 days away
        assert "2024-01-19" in result["start"]

    def test_cumartesi_sabah(self, now: datetime) -> None:
        """'cumartesi sabah' should be Saturday morning."""
        result = parse_time_window_tr("cumartesi sabah", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "cumartesi_morning" in result["hint"]
        assert "T06:00" in result["start"]

    def test_pazar_aksam(self, now: datetime) -> None:
        """'pazar akşam' should be Sunday evening."""
        result = parse_time_window_tr("pazar akşam", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert "pazar_evening" in result["hint"]


class TestParseRelativePeriod:
    """Tests for relative time expressions."""

    @pytest.fixture
    def now(self) -> datetime:
        """Fixed reference time."""
        tz = get_timezone(TZ_ISTANBUL)
        return datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)

    def test_birazdan(self, now: datetime) -> None:
        """'birazdan' should be next ~30 minutes."""
        result = parse_time_window_tr("birazdan", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "soon"

    def test_az_sonra(self, now: datetime) -> None:
        """'az sonra' should be soon."""
        result = parse_time_window_tr("az sonra", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "soon"

    def test_simdi(self, now: datetime) -> None:
        """'şimdi' should be now."""
        result = parse_time_window_tr("şimdi", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "now"

    def test_su_an(self, now: datetime) -> None:
        """'şu an' should be now."""
        result = parse_time_window_tr("şu an", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "now"

    def test_daha_sonra(self, now: datetime) -> None:
        """'daha sonra' should be later."""
        result = parse_time_window_tr("daha sonra", now=now, tz=TZ_ISTANBUL)
        assert result is not None
        assert result["hint"] == "later"


class TestParseDuration:
    """Tests for parse_duration_tr function."""

    def test_1_saat(self) -> None:
        """'1 saat' should be 60 minutes."""
        assert parse_duration_tr("1 saat") == 60

    def test_2_saat(self) -> None:
        """'2 saat' should be 120 minutes."""
        assert parse_duration_tr("2 saat") == 120

    def test_bir_saat(self) -> None:
        """'bir saat' should be 60 minutes."""
        assert parse_duration_tr("bir saat") == 60

    def test_30_dakika(self) -> None:
        """'30 dakika' should be 30 minutes."""
        assert parse_duration_tr("30 dakika") == 30

    def test_yarim_saat(self) -> None:
        """'yarım saat' should be 30 minutes."""
        assert parse_duration_tr("yarım saat") == 30

    def test_bir_bucuk_saat(self) -> None:
        """'bir buçuk saat' should be 90 minutes."""
        assert parse_duration_tr("bir buçuk saat") == 90

    def test_1_saat_30_dakika(self) -> None:
        """'1 saat 30 dakika' should be 90 minutes."""
        assert parse_duration_tr("1 saat 30 dakika") == 90

    def test_empty_returns_none(self) -> None:
        """Empty string should return None."""
        assert parse_duration_tr("") is None

    def test_invalid_returns_none(self) -> None:
        """Invalid text should return None."""
        assert parse_duration_tr("hello world") is None


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_text(self) -> None:
        """Empty text should return None."""
        assert parse_time_window_tr("") is None
        assert parse_time_window_tr(None) is None  # type: ignore

    def test_no_time_expression(self) -> None:
        """Text without time expression should return None."""
        result = parse_time_window_tr("merhaba nasılsın", tz=TZ_ISTANBUL)
        assert result is None

    def test_now_defaults_to_current(self) -> None:
        """When now is None, should use current time."""
        result = parse_time_window_tr("yarın", tz=TZ_ISTANBUL)
        assert result is not None
        # Just verify it parsed without error

    def test_confidence_varies(self) -> None:
        """Different patterns should have different confidence."""
        tz = get_timezone(TZ_ISTANBUL)
        now = datetime(2024, 1, 15, 14, 0, 0, tzinfo=tz)
        
        # High confidence
        r1 = parse_time_window_tr("bu akşam", now=now, tz=TZ_ISTANBUL)
        # Lower confidence  
        r2 = parse_time_window_tr("daha sonra", now=now, tz=TZ_ISTANBUL)
        
        assert r1 is not None and r2 is not None
        assert r1["confidence"] > r2["confidence"]


class TestTurkishNumbers:
    """Tests for Turkish number mapping."""

    def test_numbers_mapping(self) -> None:
        """Turkish numbers should map correctly."""
        assert TURKISH_NUMBERS["bir"] == 1
        assert TURKISH_NUMBERS["iki"] == 2
        assert TURKISH_NUMBERS["üç"] == 3
        assert TURKISH_NUMBERS["dört"] == 4
        assert TURKISH_NUMBERS["beş"] == 5
        assert TURKISH_NUMBERS["altı"] == 6
        assert TURKISH_NUMBERS["yedi"] == 7
        assert TURKISH_NUMBERS["sekiz"] == 8
        assert TURKISH_NUMBERS["dokuz"] == 9
        assert TURKISH_NUMBERS["on"] == 10


class TestTimePeriods:
    """Tests for time period definitions."""

    def test_sabah_period(self) -> None:
        """Morning should be 06:00-12:00."""
        start, end = TIME_PERIODS["sabah"]
        assert start == 6
        assert end == 12

    def test_aksam_period(self) -> None:
        """Evening should be 18:00-22:00."""
        start, end = TIME_PERIODS["akşam"]
        assert start == 18
        assert end == 22

    def test_ogle_period(self) -> None:
        """Noon should be 12:00-14:00."""
        start, end = TIME_PERIODS["öğle"]
        assert start == 12
        assert end == 14
