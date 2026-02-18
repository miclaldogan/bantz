"""Tests for Voice → Overlay IPC Bridge — Issue #1440.

Covers:
- ContinuousListener state → overlay IPC mapping
- Wake word detection → transient "wake" flash
- VoiceFSM transitions → overlay state
- Debounce / cooldown logic
- Speaking state notifications
- Unbind cleanup
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum, auto
from dataclasses import dataclass
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Mock types matching voice pipeline interfaces
# ─────────────────────────────────────────────────────────────────


class MockListenerState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()


@dataclass
class MockStateTransition:
    from_state: Any
    to_state: Any
    trigger: str
    timestamp: float = 0.0


class MockVoiceState(Enum):
    ACTIVE_LISTEN = "active_listen"
    WAKE_ONLY = "wake_only"
    IDLE_SLEEP = "idle_sleep"


class MockContinuousListener:
    """Minimal ContinuousListener mock with callback registration."""

    def __init__(self):
        self._on_state_change: List = []
        self._on_wake_word: List = []

    def on_state_change(self, callback):
        self._on_state_change.append(callback)

    def on_wake_word(self, callback):
        self._on_wake_word.append(callback)

    def fire_state_change(self, state):
        for cb in self._on_state_change:
            cb(state)

    def fire_wake_word(self, word, confidence):
        for cb in self._on_wake_word:
            cb(word, confidence)


class MockVoiceFSM:
    """Minimal VoiceFSM mock with transition callback."""

    def __init__(self):
        self._on_transition = None

    def set_on_transition(self, callback):
        self._on_transition = callback

    def clear_on_transition(self):
        self._on_transition = None

    def fire_transition(self, from_state, to_state, trigger):
        if self._on_transition:
            self._on_transition(MockStateTransition(
                from_state=from_state,
                to_state=to_state,
                trigger=trigger,
                timestamp=time.monotonic(),
            ))


class MockOverlayClient:
    """Minimal OverlayClient mock capturing sent messages."""

    def __init__(self):
        self.messages: List[dict] = []

    async def send_raw(self, msg: dict) -> bool:
        self.messages.append(msg)
        return True

    def last_message(self) -> Optional[dict]:
        return self.messages[-1] if self.messages else None


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _make_bridge():
    """Create bridge with mock overlay client."""
    client = MockOverlayClient()
    # Patch asyncio to make send_raw synchronous in tests
    from bantz.voice.voice_overlay_bridge import VoiceOverlayBridge
    bridge = VoiceOverlayBridge(client)
    return bridge, client


def _run_bridge_send(bridge, client, setup_fn):
    """Run bridge in an event loop context for async sends."""
    loop = asyncio.new_event_loop()
    bridge._loop = loop

    async def _run():
        setup_fn()
        # Give time for any scheduled tasks
        await asyncio.sleep(0.01)

    loop.run_until_complete(_run())
    loop.close()
    return client.messages


# ─────────────────────────────────────────────────────────────────
# Listener State Mapping
# ─────────────────────────────────────────────────────────────────


class TestListenerStateMapping:
    def test_idle_maps_to_idle(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        msgs = _run_bridge_send(bridge, client,
            lambda: listener.fire_state_change(MockListenerState.IDLE))
        # Initial state is already idle, so no message sent
        assert len(msgs) == 0

    def test_listening_maps_to_listening(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        msgs = _run_bridge_send(bridge, client,
            lambda: listener.fire_state_change(MockListenerState.LISTENING))
        assert len(msgs) == 1
        assert msgs[0]["state"] == "listening"
        assert msgs[0]["type"] == "voice_state"

    def test_processing_maps_to_thinking(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        msgs = _run_bridge_send(bridge, client,
            lambda: listener.fire_state_change(MockListenerState.PROCESSING))
        assert len(msgs) == 1
        assert msgs[0]["state"] == "thinking"

    def test_state_transitions_sequence(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        def _sequence():
            listener.fire_state_change(MockListenerState.LISTENING)
            listener.fire_state_change(MockListenerState.PROCESSING)
            listener.fire_state_change(MockListenerState.IDLE)

        msgs = _run_bridge_send(bridge, client, _sequence)
        states = [m["state"] for m in msgs]
        assert states == ["listening", "thinking", "idle"]

    def test_duplicate_state_not_sent(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        def _dupes():
            listener.fire_state_change(MockListenerState.LISTENING)
            listener.fire_state_change(MockListenerState.LISTENING)

        msgs = _run_bridge_send(bridge, client, _dupes)
        assert len(msgs) == 1


# ─────────────────────────────────────────────────────────────────
# Wake Word
# ─────────────────────────────────────────────────────────────────


class TestWakeWord:
    def test_wake_word_sends_wake_state(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        msgs = _run_bridge_send(bridge, client,
            lambda: listener.fire_wake_word("hey bantz", 0.95))
        assert len(msgs) == 1
        assert msgs[0]["state"] == "wake"
        assert msgs[0]["data"]["wake_word"] == "hey bantz"
        assert msgs[0]["data"]["confidence"] == 0.95

    def test_wake_word_cooldown(self):
        bridge, client = _make_bridge()
        bridge._wake_cooldown = 100.0  # very long cooldown
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        def _rapid_wakes():
            listener.fire_wake_word("hey bantz", 0.9)
            listener.fire_wake_word("hey bantz", 0.85)
            listener.fire_wake_word("bantz", 0.92)

        msgs = _run_bridge_send(bridge, client, _rapid_wakes)
        wake_msgs = [m for m in msgs if m["state"] == "wake"]
        assert len(wake_msgs) == 1  # only first, others debounced


# ─────────────────────────────────────────────────────────────────
# VoiceFSM Transitions
# ─────────────────────────────────────────────────────────────────


class TestFSMTransitions:
    def test_active_listen_maps_to_listening(self):
        bridge, client = _make_bridge()
        fsm = MockVoiceFSM()
        bridge.bind_fsm(fsm)

        msgs = _run_bridge_send(bridge, client,
            lambda: fsm.fire_transition(
                MockVoiceState.WAKE_ONLY,
                MockVoiceState.ACTIVE_LISTEN,
                "wake_word"))
        assert len(msgs) == 1
        assert msgs[0]["state"] == "listening"

    def test_wake_only_maps_to_idle(self):
        bridge, client = _make_bridge()
        bridge._last_state = "listening"  # simulate active state
        fsm = MockVoiceFSM()
        bridge.bind_fsm(fsm)

        msgs = _run_bridge_send(bridge, client,
            lambda: fsm.fire_transition(
                MockVoiceState.ACTIVE_LISTEN,
                MockVoiceState.WAKE_ONLY,
                "silence_timeout"))
        assert len(msgs) == 1
        assert msgs[0]["state"] == "idle"

    def test_thinking_not_downgraded_by_fsm(self):
        """When listener is in PROCESSING (thinking), FSM's active_listen
        should not downgrade to listening."""
        bridge, client = _make_bridge()
        bridge._last_state = "thinking"  # listener in PROCESSING
        fsm = MockVoiceFSM()
        bridge.bind_fsm(fsm)

        msgs = _run_bridge_send(bridge, client,
            lambda: fsm.fire_transition(
                MockVoiceState.WAKE_ONLY,
                MockVoiceState.ACTIVE_LISTEN,
                "speech"))
        assert len(msgs) == 0  # should NOT downgrade from thinking


# ─────────────────────────────────────────────────────────────────
# Speaking State
# ─────────────────────────────────────────────────────────────────


class TestSpeakingState:
    def test_speaking_start(self):
        bridge, client = _make_bridge()

        msgs = _run_bridge_send(bridge, client, bridge.on_speaking_start)
        assert len(msgs) == 1
        assert msgs[0]["state"] == "speaking"
        assert bridge._last_state == "speaking"

    def test_speaking_end(self):
        bridge, client = _make_bridge()
        bridge._last_state = "speaking"

        msgs = _run_bridge_send(bridge, client, bridge.on_speaking_end)
        assert len(msgs) == 1
        assert msgs[0]["state"] == "idle"


# ─────────────────────────────────────────────────────────────────
# Bind / Unbind
# ─────────────────────────────────────────────────────────────────


class TestBindUnbind:
    def test_bind_listener(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)
        assert len(listener._on_state_change) == 1
        assert len(listener._on_wake_word) == 1

    def test_bind_fsm(self):
        bridge, client = _make_bridge()
        fsm = MockVoiceFSM()
        bridge.bind_fsm(fsm)
        assert fsm._on_transition is not None

    def test_unbind_all(self):
        bridge, client = _make_bridge()
        fsm = MockVoiceFSM()
        bridge.bind_fsm(fsm)
        bridge.unbind_all()
        assert fsm._on_transition is None
        assert bridge._bound_fsm is None
        assert bridge._bound_listener is None


# ─────────────────────────────────────────────────────────────────
# Message Format
# ─────────────────────────────────────────────────────────────────


class TestMessageFormat:
    def test_message_has_required_fields(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        msgs = _run_bridge_send(bridge, client,
            lambda: listener.fire_state_change(MockListenerState.LISTENING))
        msg = msgs[0]
        assert "type" in msg
        assert "state" in msg
        assert "trigger" in msg
        assert "ts" in msg
        assert msg["type"] == "voice_state"
        assert isinstance(msg["ts"], int)

    def test_trigger_includes_source(self):
        bridge, client = _make_bridge()
        listener = MockContinuousListener()
        bridge.bind_listener(listener)

        msgs = _run_bridge_send(bridge, client,
            lambda: listener.fire_state_change(MockListenerState.LISTENING))
        assert msgs[0]["trigger"].startswith("listener:")

    def test_fsm_trigger_includes_source(self):
        bridge, client = _make_bridge()
        bridge._last_state = "listening"
        fsm = MockVoiceFSM()
        bridge.bind_fsm(fsm)

        msgs = _run_bridge_send(bridge, client,
            lambda: fsm.fire_transition(
                MockVoiceState.ACTIVE_LISTEN,
                MockVoiceState.WAKE_ONLY,
                "silence_timeout"))
        assert msgs[0]["trigger"].startswith("fsm:")


# ─────────────────────────────────────────────────────────────────
# Import & Registration
# ─────────────────────────────────────────────────────────────────


class TestImport:
    def test_bridge_importable(self):
        from bantz.voice.voice_overlay_bridge import VoiceOverlayBridge
        assert callable(VoiceOverlayBridge)

    def test_state_maps_exist(self):
        from bantz.voice.voice_overlay_bridge import (
            _LISTENER_STATE_MAP,
            _FSM_STATE_MAP,
        )
        assert "IDLE" in _LISTENER_STATE_MAP
        assert "LISTENING" in _LISTENER_STATE_MAP
        assert "PROCESSING" in _LISTENER_STATE_MAP
        assert "active_listen" in _FSM_STATE_MAP
        assert "wake_only" in _FSM_STATE_MAP
