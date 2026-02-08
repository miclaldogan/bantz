"""Tests for Issue #304 — Morning briefing (news + calendar + system).

Covers:
  - BriefingConfig: defaults, from_env, custom values
  - is_quiet_hours: boundary tests, wrap-around
  - should_show_briefing: enabled/disabled, quiet hours, hour gate
  - get_calendar_summary: 0/1/N events, time extraction, privacy
  - get_news_summary: cached, none, truncation
  - get_system_summary: disk info
  - build_morning_briefing: full assembly, disabled, quiet hours
  - File existence
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# BriefingConfig
# ─────────────────────────────────────────────────────────────────


class TestBriefingConfig:
    """Briefing configuration."""

    def test_defaults_disabled(self):
        from bantz.voice.morning_briefing import BriefingConfig

        cfg = BriefingConfig()
        assert cfg.enabled is False
        assert cfg.briefing_hour == 8
        assert cfg.quiet_start == (0, 0)
        assert cfg.quiet_end == (7, 0)
        assert cfg.include_news is True
        assert cfg.include_calendar is True
        assert cfg.include_system is False

    def test_from_env(self):
        from bantz.voice.morning_briefing import BriefingConfig

        env = {
            "BANTZ_MORNING_BRIEFING": "true",
            "BANTZ_BRIEFING_HOUR": "9",
            "BANTZ_QUIET_HOURS_START": "23:00",
            "BANTZ_QUIET_HOURS_END": "06:30",
            "BANTZ_BRIEFING_INCLUDE_NEWS": "true",
            "BANTZ_BRIEFING_INCLUDE_CALENDAR": "true",
            "BANTZ_BRIEFING_INCLUDE_SYSTEM": "true",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = BriefingConfig.from_env()
        assert cfg.enabled is True
        assert cfg.briefing_hour == 9
        assert cfg.quiet_start == (23, 0)
        assert cfg.quiet_end == (6, 30)
        assert cfg.include_system is True

    def test_from_env_defaults(self):
        from bantz.voice.morning_briefing import BriefingConfig

        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = BriefingConfig.from_env()
        assert cfg.enabled is False


# ─────────────────────────────────────────────────────────────────
# Quiet hours
# ─────────────────────────────────────────────────────────────────


class TestQuietHours:
    """Quiet hours detection."""

    def test_inside_quiet_hours(self):
        from bantz.voice.morning_briefing import is_quiet_hours, BriefingConfig

        cfg = BriefingConfig(quiet_start=(0, 0), quiet_end=(7, 0))
        dt = datetime.datetime(2024, 1, 15, 3, 0)
        assert is_quiet_hours(dt, cfg) is True

    def test_outside_quiet_hours(self):
        from bantz.voice.morning_briefing import is_quiet_hours, BriefingConfig

        cfg = BriefingConfig(quiet_start=(0, 0), quiet_end=(7, 0))
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        assert is_quiet_hours(dt, cfg) is False

    def test_boundary_start(self):
        from bantz.voice.morning_briefing import is_quiet_hours, BriefingConfig

        cfg = BriefingConfig(quiet_start=(0, 0), quiet_end=(7, 0))
        dt = datetime.datetime(2024, 1, 15, 0, 0)
        assert is_quiet_hours(dt, cfg) is True

    def test_boundary_end(self):
        from bantz.voice.morning_briefing import is_quiet_hours, BriefingConfig

        cfg = BriefingConfig(quiet_start=(0, 0), quiet_end=(7, 0))
        dt = datetime.datetime(2024, 1, 15, 7, 0)
        assert is_quiet_hours(dt, cfg) is False

    def test_wrap_around(self):
        from bantz.voice.morning_briefing import is_quiet_hours, BriefingConfig

        cfg = BriefingConfig(quiet_start=(23, 0), quiet_end=(6, 0))
        # 23:30 → quiet
        assert is_quiet_hours(datetime.datetime(2024, 1, 15, 23, 30), cfg) is True
        # 02:00 → quiet
        assert is_quiet_hours(datetime.datetime(2024, 1, 15, 2, 0), cfg) is True
        # 12:00 → not quiet
        assert is_quiet_hours(datetime.datetime(2024, 1, 15, 12, 0), cfg) is False


# ─────────────────────────────────────────────────────────────────
# should_show_briefing
# ─────────────────────────────────────────────────────────────────


class TestShouldShowBriefing:
    """Briefing display conditions."""

    def test_disabled(self):
        from bantz.voice.morning_briefing import should_show_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=False)
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        assert should_show_briefing(dt, cfg) is False

    def test_enabled_after_briefing_hour(self):
        from bantz.voice.morning_briefing import should_show_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=True, briefing_hour=8)
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        assert should_show_briefing(dt, cfg) is True

    def test_before_briefing_hour(self):
        from bantz.voice.morning_briefing import should_show_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=True, briefing_hour=8)
        dt = datetime.datetime(2024, 1, 15, 7, 30)
        assert should_show_briefing(dt, cfg) is False

    def test_during_quiet_hours(self):
        from bantz.voice.morning_briefing import should_show_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=True, quiet_start=(0, 0), quiet_end=(7, 0))
        dt = datetime.datetime(2024, 1, 15, 3, 0)
        assert should_show_briefing(dt, cfg) is False


# ─────────────────────────────────────────────────────────────────
# Calendar summary
# ─────────────────────────────────────────────────────────────────


class TestCalendarSummary:
    """Privacy-safe calendar summary."""

    def test_no_events(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        result = get_calendar_summary([])
        assert "etkinlik yok" in result

    def test_one_event_with_time(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        events = [{"start_time": "10:00"}]
        result = get_calendar_summary(events)
        assert "1 etkinliğiniz" in result
        assert "10:00" in result

    def test_multiple_events(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        events = [{"start_time": "09:00"}, {"start_time": "14:00"}, {"start_time": "16:00"}]
        result = get_calendar_summary(events)
        assert "3 etkinliğiniz" in result
        assert "09:00" in result

    def test_no_title_in_summary(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        events = [{"start_time": "10:00", "title": "Secret Meeting"}]
        result = get_calendar_summary(events)
        assert "Secret" not in result

    def test_none_events(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        assert get_calendar_summary(None) is None

    def test_iso_time_extraction(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        events = [{"start": "2024-01-15T10:30:00+03:00"}]
        result = get_calendar_summary(events)
        assert "10:30" in result

    def test_event_without_time(self):
        from bantz.voice.morning_briefing import get_calendar_summary

        events = [{"summary": "All day"}]
        result = get_calendar_summary(events)
        assert "1 etkinliğiniz" in result


# ─────────────────────────────────────────────────────────────────
# News summary
# ─────────────────────────────────────────────────────────────────


class TestNewsSummary:
    """News summary from cache."""

    def test_with_cached_news(self):
        from bantz.voice.morning_briefing import get_news_summary

        result = get_news_summary("Yapay zeka gelişmeleri")
        assert result == "Yapay zeka gelişmeleri"

    def test_no_news(self):
        from bantz.voice.morning_briefing import get_news_summary

        assert get_news_summary(None) is None

    def test_truncation(self):
        from bantz.voice.morning_briefing import get_news_summary

        long_news = "A" * 200
        result = get_news_summary(long_news)
        assert len(result) <= 150
        assert result.endswith("...")


# ─────────────────────────────────────────────────────────────────
# System summary
# ─────────────────────────────────────────────────────────────────


class TestSystemSummary:
    """System status summary."""

    def test_returns_string(self):
        from bantz.voice.morning_briefing import get_system_summary

        result = get_system_summary()
        assert isinstance(result, str)
        assert "Sistem" in result or "disk" in result.lower() or "Disk" in result


# ─────────────────────────────────────────────────────────────────
# build_morning_briefing
# ─────────────────────────────────────────────────────────────────


class TestBuildMorningBriefing:
    """Full briefing assembly."""

    def test_disabled_returns_none(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=False)
        assert build_morning_briefing(config=cfg) is None

    def test_quiet_hours_returns_none(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=True, quiet_start=(0, 0), quiet_end=(7, 0))
        dt = datetime.datetime(2024, 1, 15, 3, 0)
        assert build_morning_briefing(config=cfg, now=dt) is None

    def test_enabled_with_calendar(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=True, include_calendar=True, include_news=False)
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        events = [{"start_time": "09:00"}, {"start_time": "14:00"}]
        result = build_morning_briefing(config=cfg, now=dt, calendar_events=events)
        assert result is not None
        assert "Günaydın" in result
        assert "2 etkinliğiniz" in result
        assert "Daha fazla detay" in result

    def test_enabled_with_news(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(enabled=True, include_news=True, include_calendar=False)
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        result = build_morning_briefing(
            config=cfg, now=dt, cached_news="AI gelişmeleri var"
        )
        assert result is not None
        assert "AI gelişmeleri" in result

    def test_no_content_returns_none(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(
            enabled=True, include_news=False, include_calendar=False, include_system=False
        )
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        assert build_morning_briefing(config=cfg, now=dt) is None

    def test_with_system_status(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(
            enabled=True, include_news=False, include_calendar=False, include_system=True
        )
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        result = build_morning_briefing(config=cfg, now=dt)
        assert result is not None
        assert "Sistem" in result or "disk" in result.lower() or "Disk" in result

    def test_full_briefing(self):
        from bantz.voice.morning_briefing import build_morning_briefing, BriefingConfig

        cfg = BriefingConfig(
            enabled=True, include_news=True, include_calendar=True, include_system=True
        )
        dt = datetime.datetime(2024, 1, 15, 10, 0)
        events = [{"start_time": "09:00"}]
        result = build_morning_briefing(
            config=cfg, now=dt,
            calendar_events=events,
            cached_news="Yapay zeka haberleri",
        )
        assert "Günaydın" in result
        assert "Yapay zeka" in result
        assert "etkinliğiniz" in result


# ─────────────────────────────────────────────────────────────────
# File existence
# ─────────────────────────────────────────────────────────────────


class TestFileExistence:
    """Verify Issue #304 file exists."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_morning_briefing_exists(self):
        assert (self.ROOT / "src" / "bantz" / "voice" / "morning_briefing.py").is_file()
