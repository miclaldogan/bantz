"""Tests for issue #457 — Voice attention gate: FSM-driven listen mode."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from bantz.voice.attention_gate_v0 import (
    AttentionGateV0,
    AttentionMode,
    AudioEvent,
    ModeTransition,
    STATE_ATTENTION_MAP,
)


# ── Mode enum ─────────────────────────────────────────────────────────

class TestAttentionMode:
    def test_values(self):
        assert AttentionMode.FULL_LISTEN.value == "full_listen"
        assert AttentionMode.WAKE_ONLY.value == "wake_only"
        assert AttentionMode.COMMAND_ONLY.value == "command_only"
        assert AttentionMode.MUTED.value == "muted"


# ── State mapping ─────────────────────────────────────────────────────

class TestStateMapping:
    def test_idle_maps_to_full_listen(self):
        assert STATE_ATTENTION_MAP["idle"] == AttentionMode.FULL_LISTEN

    def test_executing_maps_to_command_only(self):
        assert STATE_ATTENTION_MAP["executing"] == AttentionMode.COMMAND_ONLY

    def test_speaking_maps_to_muted(self):
        assert STATE_ATTENTION_MAP["speaking"] == AttentionMode.MUTED

    def test_confirming_maps_to_full_listen(self):
        assert STATE_ATTENTION_MAP["confirming"] == AttentionMode.FULL_LISTEN

    def test_planning_maps_to_wake_only(self):
        assert STATE_ATTENTION_MAP["planning"] == AttentionMode.WAKE_ONLY


# ── should_process per mode ───────────────────────────────────────────

class TestShouldProcess:
    def test_full_listen_accepts_all(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.FULL_LISTEN)
        assert gate.should_process(AudioEvent(is_speech=True))
        assert gate.should_process(AudioEvent(is_wakeword=True))
        assert gate.should_process(AudioEvent())

    def test_muted_rejects_all(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.MUTED)
        assert not gate.should_process(AudioEvent(is_speech=True))
        assert not gate.should_process(AudioEvent(is_wakeword=True))
        assert not gate.should_process(AudioEvent(is_interrupt_keyword=True))

    def test_wake_only_accepts_wakeword(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.WAKE_ONLY)
        assert gate.should_process(AudioEvent(is_wakeword=True))
        assert not gate.should_process(AudioEvent(is_speech=True))
        assert not gate.should_process(AudioEvent(is_interrupt_keyword=True))

    def test_command_only_accepts_interrupt_keyword(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.COMMAND_ONLY)
        assert gate.should_process(AudioEvent(is_interrupt_keyword=True))
        assert not gate.should_process(AudioEvent(is_speech=True))

    def test_command_only_wakeword_opens_gate(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.COMMAND_ONLY)
        assert gate.should_process(AudioEvent(is_wakeword=True))
        # After wakeword, gate opens to FULL_LISTEN temporarily
        assert gate.mode == AttentionMode.FULL_LISTEN


# ── FSM state change ─────────────────────────────────────────────────

class TestFSMStateChange:
    def test_state_change_updates_mode(self):
        gate = AttentionGateV0()
        gate.on_state_change("idle", "executing")
        assert gate.mode == AttentionMode.COMMAND_ONLY

    def test_state_change_to_speaking(self):
        gate = AttentionGateV0()
        gate.on_state_change("executing", "speaking")
        assert gate.mode == AttentionMode.MUTED

    def test_state_change_back_to_idle(self):
        gate = AttentionGateV0()
        gate.on_state_change("idle", "executing")
        gate.on_state_change("executing", "idle")
        assert gate.mode == AttentionMode.FULL_LISTEN

    def test_unknown_state_ignored(self):
        gate = AttentionGateV0()
        gate.on_state_change("idle", "nonexistent_state")
        assert gate.mode == AttentionMode.FULL_LISTEN


# ── TTS mute/unmute ──────────────────────────────────────────────────

class TestTTSMuteUnmute:
    def test_tts_start_mutes(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.COMMAND_ONLY)
        gate.on_tts_start()
        assert gate.mode == AttentionMode.MUTED

    def test_tts_end_restores(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.COMMAND_ONLY)
        gate.on_tts_start()
        gate.on_tts_end()
        assert gate.mode == AttentionMode.COMMAND_ONLY

    def test_tts_end_defaults_to_full_listen(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.MUTED)
        gate.on_tts_end()
        assert gate.mode == AttentionMode.FULL_LISTEN

    def test_double_tts_start_no_crash(self):
        gate = AttentionGateV0()
        gate.on_tts_start()
        gate.on_tts_start()  # idempotent
        assert gate.mode == AttentionMode.MUTED


# ── Wakeword override ────────────────────────────────────────────────

class TestWakewordOverride:
    def test_wakeword_in_command_opens_gate(self):
        gate = AttentionGateV0(
            initial_mode=AttentionMode.COMMAND_ONLY,
            wakeword_override_duration=10.0,
        )
        event = AudioEvent(is_wakeword=True)
        assert gate.should_process(event)
        assert gate.mode == AttentionMode.FULL_LISTEN

    def test_wakeword_override_expires(self):
        gate = AttentionGateV0(
            initial_mode=AttentionMode.COMMAND_ONLY,
            wakeword_override_duration=0.05,
        )
        gate.should_process(AudioEvent(is_wakeword=True))
        assert gate.mode == AttentionMode.FULL_LISTEN
        time.sleep(0.1)
        assert gate.mode == AttentionMode.COMMAND_ONLY

    def test_fsm_change_clears_override(self):
        gate = AttentionGateV0(
            initial_mode=AttentionMode.COMMAND_ONLY,
            wakeword_override_duration=60.0,
        )
        gate.should_process(AudioEvent(is_wakeword=True))
        gate.on_state_change("executing", "idle")
        assert gate.mode == AttentionMode.FULL_LISTEN


# ── Callbacks ─────────────────────────────────────────────────────────

class TestCallbacks:
    def test_mode_change_callback(self):
        gate = AttentionGateV0()
        cb = MagicMock()
        gate.on_mode_change(cb)
        gate.on_state_change("idle", "executing")
        cb.assert_called_once()
        args = cb.call_args[0]
        assert args[0] == AttentionMode.FULL_LISTEN
        assert args[1] == AttentionMode.COMMAND_ONLY

    def test_callback_exception_safe(self):
        gate = AttentionGateV0()
        gate.on_mode_change(lambda *a: 1 / 0)
        gate.on_state_change("idle", "executing")
        assert gate.mode == AttentionMode.COMMAND_ONLY


# ── Transition history ───────────────────────────────────────────────

class TestTransitionHistory:
    def test_transitions_recorded(self):
        gate = AttentionGateV0()
        gate.on_state_change("idle", "executing")
        gate.on_state_change("executing", "idle")
        assert len(gate.transitions) == 2
        assert gate.transitions[0].old_mode == AttentionMode.FULL_LISTEN
        assert gate.transitions[0].new_mode == AttentionMode.COMMAND_ONLY

    def test_tts_transitions_recorded(self):
        gate = AttentionGateV0()
        gate.on_tts_start()
        gate.on_tts_end()
        assert len(gate.transitions) == 2
        assert gate.transitions[0].reason == "tts_start"
        assert gate.transitions[1].reason == "tts_end"


# ── set_mode / get_mode ──────────────────────────────────────────────

class TestSetGetMode:
    def test_set_mode(self):
        gate = AttentionGateV0()
        gate.set_mode(AttentionMode.MUTED, reason="test")
        assert gate.get_mode() == AttentionMode.MUTED

    def test_set_same_mode_no_transition(self):
        gate = AttentionGateV0(initial_mode=AttentionMode.FULL_LISTEN)
        gate.set_mode(AttentionMode.FULL_LISTEN)
        assert len(gate.transitions) == 0
