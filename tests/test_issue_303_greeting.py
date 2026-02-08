"""Tests for Issue #303 — Personalized boot greeting (no PII).

Covers:
  - get_time_greeting: all time-of-day variants
  - SessionSummary: creation, to_dict/from_dict, to_turkish, has_activity
  - save/load session summary: file I/O, missing file, corrupt file
  - build_greeting: default, with session, without session, max chars
  - GreetingConfig: defaults, custom
  - PII safety: no PII in greeting output
  - File existence
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# get_time_greeting
# ─────────────────────────────────────────────────────────────────


class TestTimeGreeting:
    """Time-of-day Turkish greeting."""

    def test_morning(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "Günaydın" in get_time_greeting(8)

    def test_noon(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi günler" in get_time_greeting(14)

    def test_evening(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi akşamlar" in get_time_greeting(20)

    def test_night(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi geceler" in get_time_greeting(2)

    def test_boundary_5am(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "Günaydın" in get_time_greeting(5)

    def test_boundary_12pm(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi günler" in get_time_greeting(12)

    def test_boundary_18pm(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi akşamlar" in get_time_greeting(18)

    def test_boundary_22pm(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi geceler" in get_time_greeting(22)

    def test_midnight(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        assert "İyi geceler" in get_time_greeting(0)

    def test_default_uses_current_hour(self):
        from bantz.voice.personalized_greeting import get_time_greeting

        result = get_time_greeting()
        assert "efendim" in result


# ─────────────────────────────────────────────────────────────────
# SessionSummary
# ─────────────────────────────────────────────────────────────────


class TestSessionSummary:
    """Session summary — safe, PII-free."""

    def test_defaults_no_activity(self):
        from bantz.voice.personalized_greeting import SessionSummary

        s = SessionSummary()
        assert s.has_activity is False
        assert s.to_turkish() is None

    def test_with_calendar(self):
        from bantz.voice.personalized_greeting import SessionSummary

        s = SessionSummary(calendar_events=3, date="2024-01-15")
        assert s.has_activity is True
        text = s.to_turkish()
        assert "3 takvim etkinliği" in text
        assert "Son oturumda" in text

    def test_with_multiple_activities(self):
        from bantz.voice.personalized_greeting import SessionSummary

        s = SessionSummary(calendar_events=2, emails_checked=5, date="2024-01-15")
        text = s.to_turkish()
        assert "2 takvim etkinliği" in text
        assert "5 mail" in text

    def test_today_prefix(self):
        from bantz.voice.personalized_greeting import SessionSummary

        today = datetime.date.today().isoformat()
        s = SessionSummary(tasks_completed=1, date=today)
        text = s.to_turkish()
        assert "Bugün" in text

    def test_no_date_prefix(self):
        from bantz.voice.personalized_greeting import SessionSummary

        s = SessionSummary(web_searches=2, date="")
        text = s.to_turkish()
        assert "Geçen sefer" in text

    def test_to_dict_from_dict_roundtrip(self):
        from bantz.voice.personalized_greeting import SessionSummary

        orig = SessionSummary(
            calendar_events=3, emails_checked=10,
            tasks_completed=2, web_searches=1,
            total_turns=15, date="2024-06-15",
        )
        d = orig.to_dict()
        restored = SessionSummary.from_dict(d)
        assert restored.calendar_events == 3
        assert restored.emails_checked == 10
        assert restored.date == "2024-06-15"

    def test_from_dict_missing_fields(self):
        from bantz.voice.personalized_greeting import SessionSummary

        s = SessionSummary.from_dict({})
        assert s.calendar_events == 0
        assert s.has_activity is False


# ─────────────────────────────────────────────────────────────────
# Save / Load
# ─────────────────────────────────────────────────────────────────


class TestSaveLoadSession:
    """File I/O for session summary."""

    def test_save_and_load(self, tmp_path):
        from bantz.voice.personalized_greeting import (
            SessionSummary, save_session_summary, get_last_session_summary,
        )

        path = tmp_path / "session.json"
        orig = SessionSummary(calendar_events=5, date="2024-01-15")
        assert save_session_summary(orig, path) is True

        loaded = get_last_session_summary(path)
        assert loaded is not None
        assert loaded.calendar_events == 5

    def test_load_missing_file(self, tmp_path):
        from bantz.voice.personalized_greeting import get_last_session_summary

        assert get_last_session_summary(tmp_path / "nope.json") is None

    def test_load_corrupt_file(self, tmp_path):
        from bantz.voice.personalized_greeting import get_last_session_summary

        path = tmp_path / "bad.json"
        path.write_text("not json!", encoding="utf-8")
        assert get_last_session_summary(path) is None

    def test_load_empty_activity(self, tmp_path):
        from bantz.voice.personalized_greeting import (
            SessionSummary, save_session_summary, get_last_session_summary,
        )

        path = tmp_path / "empty.json"
        save_session_summary(SessionSummary(), path)
        assert get_last_session_summary(path) is None  # No activity

    def test_save_creates_dirs(self, tmp_path):
        from bantz.voice.personalized_greeting import SessionSummary, save_session_summary

        path = tmp_path / "deep" / "dir" / "session.json"
        assert save_session_summary(SessionSummary(tasks_completed=1), path) is True


# ─────────────────────────────────────────────────────────────────
# GreetingConfig
# ─────────────────────────────────────────────────────────────────


class TestGreetingConfig:
    """Greeting configuration."""

    def test_defaults(self):
        from bantz.voice.personalized_greeting import GreetingConfig, MAX_GREETING_CHARS

        cfg = GreetingConfig()
        assert cfg.include_session_summary is True
        assert cfg.max_chars == MAX_GREETING_CHARS

    def test_custom(self):
        from bantz.voice.personalized_greeting import GreetingConfig

        cfg = GreetingConfig(include_session_summary=False, max_chars=100)
        assert cfg.include_session_summary is False
        assert cfg.max_chars == 100


# ─────────────────────────────────────────────────────────────────
# build_greeting
# ─────────────────────────────────────────────────────────────────


class TestBuildGreeting:
    """Main greeting builder."""

    def test_basic_morning(self):
        from bantz.voice.personalized_greeting import build_greeting

        g = build_greeting(hour=8)
        assert "Günaydın" in g
        assert len(g) <= 300

    def test_with_session_summary(self):
        from bantz.voice.personalized_greeting import build_greeting, SessionSummary

        summary = SessionSummary(calendar_events=3, date="2024-01-15")
        g = build_greeting(hour=10, session_summary=summary)
        assert "Günaydın" in g
        assert "takvim" in g

    def test_without_session_summary(self):
        from bantz.voice.personalized_greeting import build_greeting, GreetingConfig

        cfg = GreetingConfig(include_session_summary=False)
        g = build_greeting(config=cfg, hour=20)
        assert "İyi akşamlar" in g
        assert "takvim" not in g

    def test_max_chars_enforced(self):
        from bantz.voice.personalized_greeting import build_greeting

        g = build_greeting(hour=10)
        assert len(g) <= 300

    def test_no_pii_in_greeting(self):
        from bantz.voice.personalized_greeting import build_greeting, SessionSummary

        summary = SessionSummary(
            calendar_events=3, emails_checked=5,
            tasks_completed=2, date="2024-01-15",
        )
        g = build_greeting(hour=14, session_summary=summary)
        # Greeting should only have counts, no names/emails/phones
        assert "@" not in g
        assert "05" not in g
        assert len(g) <= 300

    def test_session_summary_none_graceful(self):
        from bantz.voice.personalized_greeting import build_greeting, SessionSummary

        summary = SessionSummary()  # No activity
        g = build_greeting(hour=10, session_summary=summary)
        assert "Günaydın" in g

    def test_greeting_always_has_efendim(self):
        from bantz.voice.personalized_greeting import build_greeting

        for hour in [0, 6, 14, 20]:
            g = build_greeting(hour=hour)
            assert "efendim" in g

    def test_very_short_max_chars(self):
        from bantz.voice.personalized_greeting import build_greeting, GreetingConfig

        cfg = GreetingConfig(max_chars=20)
        g = build_greeting(config=cfg, hour=8)
        assert len(g) <= 20


# ─────────────────────────────────────────────────────────────────
# File existence
# ─────────────────────────────────────────────────────────────────


class TestFileExistence:
    """Verify Issue #303 file exists."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_personalized_greeting_exists(self):
        assert (self.ROOT / "src" / "bantz" / "voice" / "personalized_greeting.py").is_file()
