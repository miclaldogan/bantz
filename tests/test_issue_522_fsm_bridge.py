"""Tests for Issue #522 — ConversationFSM ↔ OrchestratorLoop integration.

Covers:
  - FSMTransitionRecord: trace line format
  - FSMBridge: normal turn lifecycle (IDLE→THINKING→SPEAKING→IDLE)
  - FSMBridge: barge-in (SPEAKING→LISTENING→THINKING)
  - FSMBridge: confirmation flow (THINKING→CONFIRMING)
  - FSMBridge: graceful degradation (no FSM)
  - FSMBridge: EventBus integration (fsm.state_changed)
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from bantz.conversation.fsm import ConversationFSM, ConversationState
from bantz.core.events import EventBus


# ═══════════════════════════════════════════════════════════════
# FSMTransitionRecord
# ═══════════════════════════════════════════════════════════════

class TestFSMTransitionRecord:
    def test_defaults(self):
        from bantz.brain.fsm_bridge import FSMTransitionRecord
        rec = FSMTransitionRecord()
        assert rec.turn_number == 0
        assert rec.old_state == ""
        assert rec.trigger == ""

    def test_to_trace_line(self):
        from bantz.brain.fsm_bridge import FSMTransitionRecord
        rec = FSMTransitionRecord(
            turn_number=3,
            old_state="thinking",
            new_state="speaking",
            trigger="thinking_done",
        )
        line = rec.to_trace_line()
        assert "[fsm]" in line
        assert "thinking → speaking" in line
        assert "trigger=thinking_done" in line
        assert "turn=3" in line


# ═══════════════════════════════════════════════════════════════
# FSMBridge — Normal Turn Lifecycle
# ═══════════════════════════════════════════════════════════════

class TestFSMBridgeNormalTurn:
    """Normal flow: IDLE → LISTENING → THINKING → SPEAKING → IDLE."""

    def test_full_turn_lifecycle(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm, debug=True)

        assert bridge.current_state == "idle"

        # Turn start: IDLE → LISTENING → THINKING
        bridge.on_turn_start(turn_number=1)
        assert bridge.current_state == "thinking"

        # Finalization done: THINKING → SPEAKING
        bridge.on_finalization_done()
        assert bridge.current_state == "speaking"

        # Turn end: SPEAKING → IDLE
        bridge.on_turn_end()
        assert bridge.current_state == "idle"

        # Should have records
        assert len(bridge.records) >= 3

    def test_multi_turn(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        for turn in range(1, 4):
            bridge.on_turn_start(turn_number=turn)
            assert bridge.current_state == "thinking"
            bridge.on_finalization_done()
            assert bridge.current_state == "speaking"
            bridge.on_turn_end()
            assert bridge.current_state == "idle"


# ═══════════════════════════════════════════════════════════════
# FSMBridge — Barge-in
# ═══════════════════════════════════════════════════════════════

class TestFSMBridgeBargeIn:
    """Barge-in: SPEAKING → LISTENING → THINKING (new turn while speaking)."""

    def test_barge_in_during_speaking(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        # Turn 1: normal flow up to SPEAKING
        bridge.on_turn_start(1)
        bridge.on_finalization_done()
        assert bridge.current_state == "speaking"

        # Turn 2: starts while still SPEAKING → barge-in
        bridge.on_turn_start(2)
        assert bridge.current_state == "thinking"
        assert bridge.is_barge_in() is True

    def test_barge_in_records(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        bridge.on_turn_start(1)
        bridge.on_finalization_done()
        # Don't call on_turn_end — simulate barge-in

        bridge.on_turn_start(2)
        # Find barge_in record
        barge_records = [r for r in bridge.records if r.trigger == "barge_in"]
        assert len(barge_records) >= 1
        assert barge_records[0].old_state == "speaking"
        assert barge_records[0].new_state == "listening"


# ═══════════════════════════════════════════════════════════════
# FSMBridge — Confirmation
# ═══════════════════════════════════════════════════════════════

class TestFSMBridgeConfirmation:
    def test_confirmation_flow(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        bridge.on_turn_start(1)
        assert bridge.current_state == "thinking"

        bridge.on_confirmation_needed()
        assert bridge.current_state == "confirming"


# ═══════════════════════════════════════════════════════════════
# FSMBridge — Graceful Degradation (no FSM)
# ═══════════════════════════════════════════════════════════════

class TestFSMBridgeNoFSM:
    """All operations are no-ops when FSM is None."""

    def test_no_fsm_turn_lifecycle(self):
        from bantz.brain.fsm_bridge import FSMBridge

        bridge = FSMBridge(fsm=None)
        assert bridge.current_state == "unknown"

        result = bridge.on_turn_start(1)
        assert result is None
        assert bridge.current_state == "unknown"

        result = bridge.on_finalization_done()
        assert result is None

        result = bridge.on_turn_end()
        assert result is None

        assert len(bridge.records) == 0

    def test_no_fsm_barge_in(self):
        from bantz.brain.fsm_bridge import FSMBridge
        bridge = FSMBridge(fsm=None)
        assert bridge.is_barge_in() is False


# ═══════════════════════════════════════════════════════════════
# FSMBridge — EventBus Integration
# ═══════════════════════════════════════════════════════════════

class TestFSMBridgeEventBus:
    def test_publishes_state_changed(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bus = EventBus()

        captured = []
        bus.subscribe("fsm.state_changed", lambda e: captured.append(e.data))

        bridge = FSMBridge(fsm=fsm, event_bus=bus)
        bridge.on_turn_start(1)
        bridge.on_finalization_done()
        bridge.on_turn_end()

        # Should have multiple state_changed events
        assert len(captured) >= 3

        # Check structure of first event
        first = captured[0]
        assert "old_state" in first
        assert "new_state" in first
        assert "trigger" in first
        assert "turn_number" in first

    def test_no_event_bus_no_crash(self):
        from bantz.brain.fsm_bridge import FSMBridge
        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm, event_bus=None)
        # Should not raise
        bridge.on_turn_start(1)
        bridge.on_finalization_done()
        bridge.on_turn_end()


# ═══════════════════════════════════════════════════════════════
# FSMBridge — Utility
# ═══════════════════════════════════════════════════════════════

class TestFSMBridgeUtility:
    def test_clear_records(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        bridge.on_turn_start(1)
        assert len(bridge.records) > 0

        bridge.clear()
        assert len(bridge.records) == 0
        assert bridge.last is None

    def test_last_record(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        bridge.on_turn_start(1)
        bridge.on_finalization_done()

        last = bridge.last
        assert last is not None
        assert last.new_state == "speaking"

    def test_not_barge_in_on_normal_turn(self):
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        bridge.on_turn_start(1)
        assert bridge.is_barge_in() is False

    def test_finalization_when_not_thinking_is_noop(self):
        """on_finalization_done while not in THINKING is a no-op."""
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        # Still IDLE → finalization should be no-op
        result = bridge.on_finalization_done()
        assert result is None
        assert bridge.current_state == "idle"

    def test_turn_end_when_not_speaking_is_noop(self):
        """on_turn_end while not in SPEAKING is a no-op."""
        from bantz.brain.fsm_bridge import FSMBridge

        fsm = ConversationFSM()
        bridge = FSMBridge(fsm=fsm)

        bridge.on_turn_start(1)
        # In THINKING, not SPEAKING
        result = bridge.on_turn_end()
        assert result is None
        assert bridge.current_state == "thinking"
