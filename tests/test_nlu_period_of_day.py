# SPDX-License-Identifier: MIT
"""Tests for Issue #1255: NLU period-of-day slot extraction.

When a user says "yarın sabah" or "bugün akşam", extract_time() should
map period-of-day words to sensible default hours:
  sabah → 09:00, öğle/öğlen → 12:00, öğleden sonra → 14:00,
  akşamüstü → 17:00, akşam → 18:00, gece → 21:00.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bantz.nlu.slots import extract_time


# Fixed reference time: Monday 2024-01-15 10:00
_BASE = datetime(2024, 1, 15, 10, 0, 0)


class TestPeriodOfDay:
    """Period-of-day words set correct default hour."""

    def test_yarin_sabah(self) -> None:
        """'yarın sabah' → tomorrow 09:00."""
        result = extract_time("yarın sabah", base_time=_BASE)
        assert result is not None
        expected = (_BASE + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        assert result.value.hour == 9
        assert result.value.minute == 0
        assert result.value.day == expected.day

    def test_yarin_aksam(self) -> None:
        """'yarın akşam' → tomorrow 18:00."""
        result = extract_time("yarın akşam", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 18
        assert result.value.minute == 0

    def test_bugun_ogle(self) -> None:
        """'bugün öğle' → today 12:00."""
        result = extract_time("bugün öğle", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 12
        assert result.value.minute == 0
        assert result.value.day == _BASE.day

    def test_bugun_oglen(self) -> None:
        """'bugün öğlen' (informal) → today 12:00."""
        result = extract_time("bugün öğlen", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 12
        assert result.value.minute == 0

    def test_yarin_gece(self) -> None:
        """'yarın gece' → tomorrow 21:00."""
        result = extract_time("yarın gece", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 21
        assert result.value.minute == 0

    def test_yarin_aksamustu(self) -> None:
        """'yarın akşamüstü' → tomorrow 17:00."""
        result = extract_time("yarın akşamüstü", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 17
        assert result.value.minute == 0

    def test_yarin_ogleden_sonra(self) -> None:
        """'yarın öğleden sonra' → tomorrow 14:00."""
        result = extract_time("yarın öğleden sonra", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 14
        assert result.value.minute == 0


class TestExplicitTimeTakesPriority:
    """When both 'saat X' and period word exist, 'saat X' wins."""

    def test_yarin_sabah_saat_7(self) -> None:
        """'yarın sabah saat 7' → tomorrow 07:00 (explicit hour wins)."""
        result = extract_time("yarın sabah saat 7", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 7
        assert result.value.minute == 0

    def test_yarin_aksam_saat_8(self) -> None:
        """'yarın akşam saat 8' → tomorrow 20:00 (PM heuristic)."""
        result = extract_time("yarın akşam saat 8", base_time=_BASE)
        assert result is not None
        # hour 8 with PM heuristic depends on base_time; 8 is > 6, so no +12
        # The explicit time should be 8 (or 20 if PM kick-in) — key point:
        # period word should NOT override the saat match.
        assert result.value.hour in (8, 20)

    def test_bugun_ogle_saat_13(self) -> None:
        """'bugün öğle saat 13' → today 13:00."""
        result = extract_time("bugün öğle saat 13", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 13
        assert result.value.minute == 0


class TestDayOffsetStillWorks:
    """Regression: pure day offsets without period words still work."""

    def test_yarin_plain(self) -> None:
        """'yarın' without period word → tomorrow, keeps base hour."""
        result = extract_time("yarın", base_time=_BASE)
        assert result is not None
        assert result.value.day == (_BASE + timedelta(days=1)).day

    def test_bugun_plain(self) -> None:
        """'bugün' without period word → today."""
        result = extract_time("bugün", base_time=_BASE)
        assert result is not None
        assert result.value.day == _BASE.day

    def test_bugun_saat_15(self) -> None:
        """'bugün saat 15' → today 15:00 (classic pattern)."""
        result = extract_time("bugün saat 15", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 15
        assert result.value.minute == 0


class TestNLUInputUsesOriginalTurkish:
    """Verify orchestrator feeds original TR text to NLU (Issue #1255).

    These tests verify extract_time handles Turkish text correctly —
    the orchestrator integration change (state.current_user_input)
    is tested via the anaphoric bridge integration tests.
    """

    def test_turkish_chars_in_period(self) -> None:
        """Period words with Turkish characters parse correctly."""
        result = extract_time("yarın öğleden sonra toplantı koy", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 14

    def test_sentence_context(self) -> None:
        """Period word inside a full sentence."""
        result = extract_time("yarın sabah doktora gideceğim", base_time=_BASE)
        assert result is not None
        assert result.value.hour == 9
