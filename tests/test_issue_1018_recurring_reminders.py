"""Tests for Issue #1018: Recurring reminder support."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta


class TestComputeNextOccurrence(unittest.TestCase):
    """Test ReminderManager._compute_next_occurrence."""

    @classmethod
    def setUpClass(cls):
        from bantz.scheduler.reminder import ReminderManager
        cls.compute = ReminderManager._compute_next_occurrence

    def _base(self) -> datetime:
        return datetime(2026, 2, 12, 9, 0, 0)

    def test_hourly(self):
        result = self.compute(self._base(), "hourly")
        self.assertEqual(result, self._base() + timedelta(hours=1))

    def test_daily(self):
        result = self.compute(self._base(), "daily")
        self.assertEqual(result, self._base() + timedelta(days=1))

    def test_weekly(self):
        result = self.compute(self._base(), "weekly")
        self.assertEqual(result, self._base() + timedelta(weeks=1))

    def test_monthly(self):
        result = self.compute(self._base(), "monthly")
        self.assertEqual(result, self._base() + timedelta(days=30))

    def test_turkish_gunluk(self):
        result = self.compute(self._base(), "günlük")
        self.assertEqual(result, self._base() + timedelta(days=1))

    def test_turkish_haftalik(self):
        result = self.compute(self._base(), "haftalık")
        self.assertEqual(result, self._base() + timedelta(weeks=1))

    def test_turkish_saatlik(self):
        result = self.compute(self._base(), "saatlik")
        self.assertEqual(result, self._base() + timedelta(hours=1))

    def test_turkish_aylik(self):
        result = self.compute(self._base(), "aylık")
        self.assertEqual(result, self._base() + timedelta(days=30))

    def test_shorthand_2h(self):
        result = self.compute(self._base(), "2h")
        self.assertEqual(result, self._base() + timedelta(hours=2))

    def test_shorthand_30m(self):
        result = self.compute(self._base(), "30m")
        self.assertEqual(result, self._base() + timedelta(minutes=30))

    def test_shorthand_3d(self):
        result = self.compute(self._base(), "3d")
        self.assertEqual(result, self._base() + timedelta(days=3))

    def test_shorthand_1w(self):
        result = self.compute(self._base(), "1w")
        self.assertEqual(result, self._base() + timedelta(weeks=1))

    def test_unknown_interval_returns_none(self):
        result = self.compute(self._base(), "biweekly")
        self.assertIsNone(result)

    def test_empty_interval_returns_none(self):
        result = self.compute(self._base(), "")
        self.assertIsNone(result)

    def test_none_interval_returns_none(self):
        result = self.compute(self._base(), None)
        self.assertIsNone(result)

    def test_case_insensitive(self):
        result = self.compute(self._base(), "DAILY")
        self.assertEqual(result, self._base() + timedelta(days=1))

    def test_no_todo_in_check_reminders(self):
        """The TODO placeholder should be gone from reminder.py."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parent.parent
            / "src" / "bantz" / "scheduler" / "reminder.py"
        ).read_text("utf-8")
        self.assertNotIn("TODO: Implement repeat logic", source)


if __name__ == "__main__":
    unittest.main()
