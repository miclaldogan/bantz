"""Tests for Issue #292 — Boot greeting + immediate active listen.

Covers config, quiet hours, greeting selection, boot_greeting flow,
once-per-boot guarantee, TTS fallback, and FSM activation.
"""

from __future__ import annotations

import asyncio
import datetime
import os
from unittest import mock

import pytest


# ── GreetingConfig ────────────────────────────────────────────

class TestGreetingConfig:
    def test_defaults(self):
        from bantz.voice.greeting import GreetingConfig
        c = GreetingConfig()
        assert c.enabled is True
        assert c.quiet_hours_start == "00:00"
        assert c.quiet_hours_end == "07:00"
        assert "efendim" in c.greeting_text

    def test_from_env(self):
        from bantz.voice.greeting import GreetingConfig
        env = {
            "BANTZ_BOOT_GREETING": "false",
            "BANTZ_QUIET_HOURS_START": "23:00",
            "BANTZ_QUIET_HOURS_END": "06:00",
            "BANTZ_GREETING_TEXT": "Merhaba!",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            c = GreetingConfig.from_env()
        assert c.enabled is False
        assert c.quiet_hours_start == "23:00"
        assert c.greeting_text == "Merhaba!"


# ── Quiet hours ───────────────────────────────────────────────

class TestQuietHours:
    def test_within_quiet(self):
        from bantz.voice.greeting import is_quiet_hours, GreetingConfig
        cfg = GreetingConfig(quiet_hours_start="00:00", quiet_hours_end="07:00")
        at_3am = datetime.datetime(2025, 1, 15, 3, 0, 0)
        assert is_quiet_hours(cfg, at_3am) is True

    def test_outside_quiet(self):
        from bantz.voice.greeting import is_quiet_hours, GreetingConfig
        cfg = GreetingConfig(quiet_hours_start="00:00", quiet_hours_end="07:00")
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        assert is_quiet_hours(cfg, at_noon) is False

    def test_cross_midnight(self):
        from bantz.voice.greeting import is_quiet_hours, GreetingConfig
        cfg = GreetingConfig(quiet_hours_start="23:00", quiet_hours_end="06:00")
        at_2am = datetime.datetime(2025, 1, 15, 2, 0, 0)
        assert is_quiet_hours(cfg, at_2am) is True
        at_midnight = datetime.datetime(2025, 1, 15, 0, 30, 0)
        assert is_quiet_hours(cfg, at_midnight) is True
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        assert is_quiet_hours(cfg, at_noon) is False

    def test_at_boundary(self):
        from bantz.voice.greeting import is_quiet_hours, GreetingConfig
        cfg = GreetingConfig(quiet_hours_start="00:00", quiet_hours_end="07:00")
        at_7am = datetime.datetime(2025, 1, 15, 7, 0, 0)
        assert is_quiet_hours(cfg, at_7am) is False  # end is exclusive


# ── Greeting selection ────────────────────────────────────────

class TestPickGreeting:
    def test_morning(self):
        from bantz.voice.greeting import pick_greeting, GreetingConfig
        cfg = GreetingConfig()
        at_9am = datetime.datetime(2025, 1, 15, 9, 0, 0)
        text = pick_greeting(cfg, at_9am)
        assert "Günaydın" in text

    def test_evening(self):
        from bantz.voice.greeting import pick_greeting, GreetingConfig
        cfg = GreetingConfig()
        at_8pm = datetime.datetime(2025, 1, 15, 20, 0, 0)
        text = pick_greeting(cfg, at_8pm)
        assert "akşam" in text.lower()

    def test_default_midday(self):
        from bantz.voice.greeting import pick_greeting, GreetingConfig
        cfg = GreetingConfig()
        at_2pm = datetime.datetime(2025, 1, 15, 14, 0, 0)
        text = pick_greeting(cfg, at_2pm)
        assert "efendim" in text


# ── Boot greeting flow ────────────────────────────────────────

class TestBootGreeting:
    def setup_method(self):
        from bantz.voice.greeting import reset_greeted
        reset_greeted()

    @pytest.mark.asyncio
    async def test_greeting_spoken_print(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig
        cfg = GreetingConfig(enabled=True)
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        result = await boot_greeting(config=cfg, now=at_noon)
        assert result["greeted"] is True
        assert result["method"] == "print"

    @pytest.mark.asyncio
    async def test_greeting_with_tts(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig
        spoken = []

        async def fake_tts(text):
            spoken.append(text)

        cfg = GreetingConfig(enabled=True)
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        result = await boot_greeting(config=cfg, tts_speak=fake_tts, now=at_noon)
        assert result["method"] == "tts"
        assert len(spoken) == 1

    @pytest.mark.asyncio
    async def test_tts_failure_fallback(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig

        async def failing_tts(text):
            raise RuntimeError("TTS bağlantı hatası")

        cfg = GreetingConfig(enabled=True)
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        result = await boot_greeting(config=cfg, tts_speak=failing_tts, now=at_noon)
        assert result["method"] == "print"
        assert result["greeted"] is True

    @pytest.mark.asyncio
    async def test_once_per_boot(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig
        cfg = GreetingConfig(enabled=True)
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        r1 = await boot_greeting(config=cfg, now=at_noon)
        r2 = await boot_greeting(config=cfg, now=at_noon)
        assert r1["greeted"] is True
        assert r2["greeted"] is False
        assert r2["reason"] == "already_greeted"

    @pytest.mark.asyncio
    async def test_disabled(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig
        cfg = GreetingConfig(enabled=False)
        result = await boot_greeting(config=cfg)
        assert result["greeted"] is False
        assert result["reason"] == "disabled"

    @pytest.mark.asyncio
    async def test_quiet_hours_skip(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig
        cfg = GreetingConfig(enabled=True, quiet_hours_start="00:00", quiet_hours_end="07:00")
        at_3am = datetime.datetime(2025, 1, 15, 3, 0, 0)
        result = await boot_greeting(config=cfg, now=at_3am)
        assert result["greeted"] is False
        assert result["reason"] == "quiet_hours"

    @pytest.mark.asyncio
    async def test_fsm_activated(self):
        from bantz.voice.greeting import boot_greeting, GreetingConfig
        activated = []
        cfg = GreetingConfig(enabled=True)
        at_noon = datetime.datetime(2025, 1, 15, 12, 0, 0)
        result = await boot_greeting(config=cfg, fsm_activate=lambda: activated.append(True), now=at_noon)
        assert result["greeted"] is True
        assert len(activated) == 1


# ── File existence ────────────────────────────────────────────

class TestFileExistence:
    def test_greeting_py_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "voice" / "greeting.py").is_file()
