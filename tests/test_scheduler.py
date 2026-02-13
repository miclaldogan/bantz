"""
Tests for bantz.scheduler module — ReminderManager and CheckinManager.
"""

import sqlite3
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from bantz.scheduler.reminder import ReminderManager
from bantz.scheduler.checkin import CheckinManager


# ── ReminderManager ─────────────────────────────────────────────


class TestReminderManager:
    @pytest.fixture
    def manager(self, tmp_path):
        db_path = tmp_path / "test_reminders.db"
        return ReminderManager(db_path=db_path)

    def test_init_creates_db(self, manager):
        assert manager.db_path.exists()

    def test_add_reminder_relative_time(self, manager):
        result = manager.add_reminder("5 dakika sonra", "Test hatırlatma")
        assert result["ok"] is True
        assert "eklendi" in result["text"]

    def test_add_reminder_absolute_time(self, manager):
        # Use a future time today
        future = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")
        result = manager.add_reminder(future, "Toplantı")
        assert result["ok"] is True

    def test_add_reminder_invalid_time(self, manager):
        result = manager.add_reminder("geçen hafta", "Geçersiz")
        assert result["ok"] is False
        assert "anlayamadım" in result["text"]

    def test_list_reminders_empty(self, manager):
        result = manager.list_reminders()
        assert result["ok"] is True
        assert "yok" in result["text"]

    def test_list_reminders_after_add(self, manager):
        manager.add_reminder("10 dakika sonra", "Test mesaj")
        result = manager.list_reminders()
        assert result["ok"] is True
        assert "Test mesaj" in result["text"]

    def test_delete_reminder(self, manager):
        add_result = manager.add_reminder("5 dakika sonra", "Silinecek")
        # Extract reminder ID from the text
        result = manager.delete_reminder(1)
        assert result["ok"] is True
        assert "silindi" in result["text"]

    def test_delete_nonexistent(self, manager):
        result = manager.delete_reminder(9999)
        assert result["ok"] is False
        assert "bulunamadı" in result["text"]

    def test_snooze_reminder(self, manager):
        manager.add_reminder("5 dakika sonra", "Ertelenecek")
        result = manager.snooze_reminder(1, minutes=15)
        assert result["ok"] is True
        assert "ertelendi" in result["text"]

    def test_snooze_nonexistent(self, manager):
        result = manager.snooze_reminder(9999, minutes=10)
        assert result["ok"] is False

    def test_parse_time_dakika_sonra(self, manager):
        dt = manager._parse_time("5 dakika sonra")
        assert dt is not None
        assert dt > datetime.now()

    def test_parse_time_saat_sonra(self, manager):
        dt = manager._parse_time("2 saat sonra")
        assert dt is not None
        diff = (dt - datetime.now()).total_seconds()
        assert 7100 < diff < 7300  # ~2 hours

    def test_parse_time_yarin(self, manager):
        dt = manager._parse_time("yarın 09:00")
        assert dt is not None
        assert dt.hour == 9
        assert dt.minute == 0
        assert dt.date() == (datetime.now() + timedelta(days=1)).date()

    def test_parse_time_invalid(self, manager):
        dt = manager._parse_time("bilinmeyen format")
        assert dt is None

    def test_multiple_reminders(self, manager):
        manager.add_reminder("5 dakika sonra", "Birinci")
        manager.add_reminder("10 dakika sonra", "İkinci")
        manager.add_reminder("15 dakika sonra", "Üçüncü")
        result = manager.list_reminders()
        assert result["ok"] is True
        assert "Birinci" in result["text"]
        assert "İkinci" in result["text"]
        assert "Üçüncü" in result["text"]

    def test_db_schema(self, manager):
        with sqlite3.connect(manager.db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert "reminders" in tables


# ── CheckinManager ──────────────────────────────────────────────


class TestCheckinManager:
    @pytest.fixture
    def manager(self, tmp_path):
        db_path = tmp_path / "test_checkins.db"
        return CheckinManager(db_path=db_path)

    def test_init_creates_db(self, manager):
        assert manager.db_path.exists()

    def test_db_schema(self, manager):
        with sqlite3.connect(manager.db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert "checkins" in tables

    def test_parse_schedule_dakika(self, manager):
        dt, schedule = manager._parse_schedule("5 dakika sonra")
        assert dt is not None
        assert dt > datetime.now()
        assert "once" in schedule

    def test_parse_schedule_saat(self, manager):
        dt, schedule = manager._parse_schedule("2 saat sonra")
        assert dt is not None
        diff = (dt - datetime.now()).total_seconds()
        assert 7100 < diff < 7300

    def test_parse_schedule_in_minutes(self, manager):
        dt, schedule = manager._parse_schedule("in 10 minutes")
        assert dt is not None
        assert "once" in schedule

    def test_parse_schedule_daily(self, manager):
        dt, schedule = manager._parse_schedule("daily 21:00")
        assert dt is not None
        assert dt.hour == 21
        assert dt.minute == 0

    def test_parse_schedule_her_gun(self, manager):
        dt, schedule = manager._parse_schedule("her gün 09:00")
        assert dt is not None
        assert dt.hour == 9

    def test_parse_schedule_invalid(self, manager):
        dt, error = manager._parse_schedule("bilinmeyen format")
        assert dt is None
        assert isinstance(error, str)

    def test_add_checkin(self, manager):
        result = manager.add_checkin("5 dakika sonra", "Nasılsın?")
        assert result["ok"] is True
        assert "eklendi" in result["text"]

    def test_list_checkins_empty(self, manager):
        result = manager.list_checkins()
        assert result["ok"] is True

    def test_list_checkins_after_add(self, manager):
        manager.add_checkin("10 dakika sonra", "Check-in mesajı")
        result = manager.list_checkins()
        assert result["ok"] is True

    def test_delete_checkin(self, manager):
        manager.add_checkin("5 dakika sonra", "Silinecek")
        result = manager.delete_checkin(1)
        assert result["ok"] is True

    def test_delete_nonexistent_checkin(self, manager):
        result = manager.delete_checkin(9999)
        assert result["ok"] is False
