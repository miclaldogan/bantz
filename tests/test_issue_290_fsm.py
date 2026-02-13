"""Tests for Issue #290 — Voice session FSM.

Covers all state transitions, timers, config, and edge cases.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest


class TestVoiceState:
    def test_values(self):
        from bantz.voice.session_fsm import VoiceState
        assert VoiceState.ACTIVE_LISTEN.value == "active_listen"
        assert VoiceState.WAKE_ONLY.value == "wake_only"
        assert VoiceState.IDLE_SLEEP.value == "idle_sleep"


class TestFSMConfig:
    def test_defaults(self):
        from bantz.voice.session_fsm import FSMConfig
        c = FSMConfig()
        assert c.active_listen_ttl == 90.0
        assert c.silence_threshold == 30.0
        assert c.idle_sleep_enabled is False

    def test_from_env(self):
        from bantz.voice.session_fsm import FSMConfig
        env = {"BANTZ_ACTIVE_LISTEN_TTL_S": "120", "BANTZ_SILENCE_TO_WAKE_S": "15", "BANTZ_IDLE_SLEEP_ENABLED": "true"}
        with mock.patch.dict(os.environ, env, clear=True):
            c = FSMConfig.from_env()
        assert c.active_listen_ttl == 120.0
        assert c.silence_threshold == 15.0
        assert c.idle_sleep_enabled is True


class TestFSMInitial:
    def test_starts_wake_only(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        assert fsm.state == VoiceState.WAKE_ONLY

    def test_empty_history(self):
        from bantz.voice.session_fsm import VoiceFSM
        fsm = VoiceFSM()
        assert fsm.history == []


class TestBootReady:
    def test_boot_to_active(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_boot_ready()
        assert fsm.state == VoiceState.ACTIVE_LISTEN
        assert len(fsm.history) == 1
        assert fsm.history[0].trigger == "boot_ready"


class TestUserSpeech:
    def test_resets_ttl(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState, FSMConfig

        t = [0.0]
        def clock(): return t[0]

        fsm = VoiceFSM(config=FSMConfig(silence_threshold=30.0), clock=clock)
        fsm.on_boot_ready()
        t[0] = 10.0
        fsm.on_user_speech()
        assert fsm.last_activity == 10.0

    def test_speech_in_wake_only_ignored(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_user_speech()
        assert fsm.state == VoiceState.WAKE_ONLY


class TestSilenceTimeout:
    def test_active_to_wake(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_boot_ready()
        fsm.on_silence_timeout()
        assert fsm.state == VoiceState.WAKE_ONLY

    def test_tick_triggers_timeout(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState, FSMConfig

        t = [0.0]
        def clock(): return t[0]

        fsm = VoiceFSM(config=FSMConfig(silence_threshold=5.0), clock=clock)
        fsm.on_boot_ready()
        t[0] = 6.0
        fsm.tick()
        assert fsm.state == VoiceState.WAKE_ONLY

    def test_no_timeout_if_speech(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState, FSMConfig

        t = [0.0]
        def clock(): return t[0]

        fsm = VoiceFSM(config=FSMConfig(silence_threshold=5.0), clock=clock)
        fsm.on_boot_ready()
        t[0] = 4.0
        fsm.on_user_speech()
        t[0] = 8.0
        fsm.tick()
        assert fsm.state == VoiceState.ACTIVE_LISTEN  # 8-4=4 < 5


class TestDismiss:
    def test_dismiss_to_wake(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_boot_ready()
        fsm.on_dismiss_intent()
        assert fsm.state == VoiceState.WAKE_ONLY
        assert fsm.history[-1].trigger == "dismiss_intent"


class TestWakeWord:
    def test_wake_to_active(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_wake_word()
        assert fsm.state == VoiceState.ACTIVE_LISTEN

    def test_full_cycle(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState
        fsm = VoiceFSM()
        fsm.on_boot_ready()
        assert fsm.state == VoiceState.ACTIVE_LISTEN
        fsm.on_dismiss_intent()
        assert fsm.state == VoiceState.WAKE_ONLY
        fsm.on_wake_word()
        assert fsm.state == VoiceState.ACTIVE_LISTEN
        fsm.on_silence_timeout()
        assert fsm.state == VoiceState.WAKE_ONLY


class TestIdleSleep:
    def test_idle_disabled_by_default(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState, FSMConfig

        t = [0.0]
        def clock(): return t[0]

        fsm = VoiceFSM(config=FSMConfig(idle_sleep_enabled=False), clock=clock)
        fsm.on_boot_ready()
        fsm.on_silence_timeout()
        t[0] = 999.0
        fsm.tick()
        assert fsm.state == VoiceState.WAKE_ONLY  # No idle

    def test_idle_enabled(self):
        from bantz.voice.session_fsm import VoiceFSM, VoiceState, FSMConfig

        t = [0.0]
        def clock(): return t[0]

        cfg = FSMConfig(idle_sleep_enabled=True, idle_sleep_timeout=60.0, silence_threshold=5.0)
        fsm = VoiceFSM(config=cfg, clock=clock)
        fsm.on_boot_ready()
        t[0] = 6.0
        fsm.tick()  # → WAKE_ONLY
        assert fsm.state == VoiceState.WAKE_ONLY
        t[0] = 67.0
        fsm.tick()  # → IDLE_SLEEP
        assert fsm.state == VoiceState.IDLE_SLEEP


class TestTimeUntilTimeout:
    def test_active_listen(self):
        from bantz.voice.session_fsm import VoiceFSM, FSMConfig

        t = [0.0]
        def clock(): return t[0]

        fsm = VoiceFSM(config=FSMConfig(silence_threshold=30.0), clock=clock)
        fsm.on_boot_ready()
        t[0] = 10.0
        remaining = fsm.time_until_timeout()
        assert remaining == 20.0

    def test_wake_only_no_idle(self):
        from bantz.voice.session_fsm import VoiceFSM
        fsm = VoiceFSM()
        assert fsm.time_until_timeout() is None


class TestTransitionCallback:
    def test_callback_called(self):
        from bantz.voice.session_fsm import VoiceFSM, StateTransition
        transitions = []
        fsm = VoiceFSM(on_transition=transitions.append)
        fsm.on_boot_ready()
        assert len(transitions) == 1
        assert transitions[0].trigger == "boot_ready"


class TestFileExistence:
    def test_session_fsm_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "voice" / "session_fsm.py").is_file()
