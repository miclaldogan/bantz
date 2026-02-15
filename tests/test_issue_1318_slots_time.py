"""Tests for issue #1318: NLU slots.py time parsing fixes.

Covers:
1. "30 saat" no longer maps to 30 minutes in free slot extraction
2. TIME_UNITS no longer contains dead "ay"→"months" mapping
3. PM heuristic respects "sabah" qualifier
4. Module-level constants are used (performance — no per-call rebuild)
"""

from __future__ import annotations

from datetime import datetime

from bantz.nlu.slots import (_ABSOLUTE_TIME_PATTERNS, _DAY_OFFSETS,
                             _MORNING_QUALIFIERS, _PERIOD_OF_DAY,
                             _RELATIVE_TIME_RE, _TR_NUM_WORDS_PATTERN,
                             TIME_UNITS, extract_free_slot_request,
                             extract_time)

# ── 1. "30 saat" → 30 dakika bug fix ─────────────────────────────────────


class TestFreeSlotDuration:
    """Verify free-slot duration parsing after #1318 fix."""

    def test_yarim_saat_is_30_minutes(self):
        req = extract_free_slot_request("yarım saatlik boşluk var mı")
        assert req is not None
        assert req.duration_minutes == 30

    def test_30_saat_not_30_minutes(self):
        """'30 saat' must NOT map to 30 minutes (was the bug)."""
        req = extract_free_slot_request("30 saatlik boşluk bul")
        assert req is not None
        # 30 saatlik → captured by (\d+)\s*saatlik → 30 * 60 = 1800
        assert req.duration_minutes == 1800

    def test_1_saat_is_60(self):
        req = extract_free_slot_request("1 saatlik boşluk")
        assert req is not None
        assert req.duration_minutes == 60

    def test_iki_saat_is_120(self):
        req = extract_free_slot_request("iki saatlik boşluk var mı")
        assert req is not None
        assert req.duration_minutes == 120


# ── 2. TIME_UNITS dead "ay" mapping removed ──────────────────────────────


class TestTimeUnitsNoMonths:
    """Verify 'ay' → 'months' is removed from TIME_UNITS."""

    def test_months_not_in_time_units(self):
        values = set(TIME_UNITS.values())
        assert "months" not in values, (
            "TIME_UNITS should not contain 'months' — timedelta does not accept it"
        )

    def test_ay_pattern_not_in_time_units(self):
        keys_joined = " ".join(TIME_UNITS.keys())
        # "ay" should not appear as a standalone pattern
        assert "ay" not in keys_joined


# ── 3. PM heuristic respects "sabah" qualifier ───────────────────────────


class TestPMHeuristicSabah:
    """PM heuristic should NOT apply when 'sabah' qualifier is present."""

    def test_sabah_saat_3_stays_3am(self):
        """'yarın sabah saat 3' at 14:00 → should be 03:00, not 15:00."""
        base = datetime(2026, 2, 15, 14, 0, 0)
        result = extract_time("yarın sabah saat 3", base_time=base)
        assert result is not None
        assert result.value.hour == 3

    def test_saat_3_without_sabah_becomes_15(self):
        """'yarın saat 3' at 14:00 → should be 15:00 (PM heuristic)."""
        base = datetime(2026, 2, 15, 14, 0, 0)
        result = extract_time("yarın saat 3", base_time=base)
        assert result is not None
        assert result.value.hour == 15

    def test_sabah_5_absolute_stays_5am(self):
        """'sabah 5:00' at 14:00 → should stay 05:00."""
        base = datetime(2026, 2, 15, 14, 0, 0)
        result = extract_time("sabah saat 5", base_time=base)
        assert result is not None
        assert result.value.hour == 5

    def test_pm_heuristic_still_works_afternoon(self):
        """Without 'sabah', hour 1-6 at PM should still add 12."""
        base = datetime(2026, 2, 15, 15, 0, 0)
        result = extract_time("saat 4", base_time=base)
        assert result is not None
        assert result.value.hour == 16

    def test_hour_above_6_no_pm_shift(self):
        """Hour > 6 should not trigger PM heuristic."""
        base = datetime(2026, 2, 15, 14, 0, 0)
        result = extract_time("saat 8", base_time=base)
        assert result is not None
        assert result.value.hour == 8


# ── 4. Module-level constants (performance) ──────────────────────────────


class TestModuleLevelConstants:
    """Verify that constants are defined at module level, not rebuilt per call."""

    def test_day_offsets_is_module_level_dict(self):
        assert isinstance(_DAY_OFFSETS, dict)
        assert r"\byarın\b" in _DAY_OFFSETS

    def test_tr_num_words_pattern_is_str(self):
        assert isinstance(_TR_NUM_WORDS_PATTERN, str)
        assert "bir" in _TR_NUM_WORDS_PATTERN

    def test_period_of_day_is_module_level(self):
        assert isinstance(_PERIOD_OF_DAY, dict)
        assert "sabah" in _PERIOD_OF_DAY

    def test_morning_qualifiers_is_frozenset(self):
        assert isinstance(_MORNING_QUALIFIERS, frozenset)
        assert "sabah" in _MORNING_QUALIFIERS

    def test_absolute_time_patterns_precompiled(self):
        assert isinstance(_ABSOLUTE_TIME_PATTERNS, list)
        assert len(_ABSOLUTE_TIME_PATTERNS) == 3
        for pat in _ABSOLUTE_TIME_PATTERNS:
            assert hasattr(pat, "search"), "Should be compiled regex"

    def test_relative_time_re_precompiled(self):
        assert hasattr(_RELATIVE_TIME_RE, "search")
        # Should match "5 dakika sonra"
        m = _RELATIVE_TIME_RE.search("5 dakika sonra")
        assert m is not None


# ── Regression: existing extract_time happy paths still work ─────────────


class TestExtractTimeRegression:
    """Ensure existing functionality is not broken."""

    def test_5_dakika_sonra(self):
        base = datetime(2026, 2, 15, 10, 0, 0)
        result = extract_time("5 dakika sonra", base_time=base)
        assert result is not None
        assert result.value.hour == 10
        assert result.value.minute == 5

    def test_yarim_saat_sonra(self):
        base = datetime(2026, 2, 15, 10, 0, 0)
        result = extract_time("yarım saat sonra", base_time=base)
        assert result is not None
        assert result.value.hour == 10
        assert result.value.minute == 30

    def test_yarin(self):
        base = datetime(2026, 2, 15, 10, 0, 0)
        result = extract_time("yarın", base_time=base)
        assert result is not None
        assert result.value.day == 16

    def test_bugun(self):
        base = datetime(2026, 2, 15, 10, 0, 0)
        result = extract_time("bugün", base_time=base)
        assert result is not None
        assert result.value.day == 15

    def test_30_saat_sonra_relative(self):
        """'30 saat sonra' → 30 hours later (not 30 minutes)."""
        base = datetime(2026, 2, 15, 10, 0, 0)
        result = extract_time("30 saat sonra", base_time=base)
        assert result is not None
        # 30 hours = 1 day + 6 hours → Feb 16 16:00
        assert result.value.day == 16
        assert result.value.hour == 16
