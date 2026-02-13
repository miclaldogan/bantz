"""Tests for Issue #287 — Boot-to-Jarvis epic closure.

Validates that all sub-issue deliverables exist and are importable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestEpicSummaryDoc:
    def test_summary_exists(self):
        assert (ROOT / "docs" / "issues" / "issue-287-boot-epic-summary.md").is_file()

    def test_summary_content(self):
        text = (ROOT / "docs" / "issues" / "issue-287-boot-epic-summary.md").read_text()
        assert "Boot-to-Jarvis" in text
        assert "19/19" in text


class TestSystemdFiles:
    """#288 deliverables."""

    def test_core_service(self):
        assert (ROOT / "systemd" / "user" / "bantz-core.service").is_file()

    def test_voice_service(self):
        assert (ROOT / "systemd" / "user" / "bantz-voice.service").is_file()

    def test_target(self):
        assert (ROOT / "systemd" / "user" / "bantz.target").is_file()


class TestLLMWarmup:
    """#289 deliverables."""

    def test_preflight_importable(self):
        from bantz.llm.preflight import run_warmup, is_ready, check_vllm_health
        assert callable(run_warmup)
        assert callable(is_ready)


class TestVoiceFSM:
    """#290 deliverables."""

    def test_fsm_importable(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState, FSMConfig
        assert VoiceState.ACTIVE_LISTEN.value == "active_listen"

    def test_fsm_transitions(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_boot_ready()
        assert fsm.state == VoiceState.ACTIVE_LISTEN
        fsm.on_dismiss_intent()
        assert fsm.state == VoiceState.WAKE_ONLY
        fsm.on_wake_word()
        assert fsm.state == VoiceState.ACTIVE_LISTEN


class TestWakeEngine:
    """#291 deliverables."""

    def test_base_importable(self):
        from bantz.voice.wake_engine_base import WakeEngineBase, PTTFallbackEngine, create_wake_engine
        assert callable(create_wake_engine)

    def test_vosk_importable(self):
        from bantz.voice.wake_engine_vosk import VoskWakeEngine
        assert VoskWakeEngine is not None

    def test_audio_devices_importable(self):
        from bantz.voice.audio_devices import list_audio_devices, select_audio_device
        assert callable(list_audio_devices)


class TestGreeting:
    """#292 deliverables."""

    def test_greeting_importable(self):
        from bantz.voice.greeting import boot_greeting, is_quiet_hours, pick_greeting
        assert callable(is_quiet_hours)


class TestDismissIntent:
    """#293 deliverables."""

    def test_dismiss_importable(self):
        from bantz.intents.dismiss import DismissIntentDetector, DISMISS_PHRASES, DISMISS_RESPONSES
        det = DismissIntentDetector()
        result = det.detect("görüşürüz")
        assert result.is_dismiss


class TestNewsBriefing:
    """#294 deliverables."""

    def test_news_importable(self):
        from bantz.skills.news_briefing import (
            NewsItem, RSSNewsProvider, NewsCache, format_news_for_voice, NEWS_CATEGORIES,
        )
        assert "ai" in NEWS_CATEGORIES
        assert callable(format_news_for_voice)
