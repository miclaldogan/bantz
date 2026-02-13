"""Tests for issue #455 — Conversation FSM v0."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from bantz.conversation.fsm_v0 import (
    ConversationFSMv0,
    FSMEvent,
    FSMState,
    TransitionRecord,
)


# ── TestHappyPath ─────────────────────────────────────────────────────

class TestHappyPath:
    """Full IDLE → ... → IDLE cycle."""

    def test_full_cycle_with_tools(self):
        fsm = ConversationFSMv0()
        assert fsm.state == FSMState.IDLE

        fsm.transition(FSMEvent.USER_INPUT)
        assert fsm.state == FSMState.LISTENING

        fsm.transition(FSMEvent.INPUT_COMPLETE)
        assert fsm.state == FSMState.PLANNING

        fsm.transition(FSMEvent.PLAN_READY)
        assert fsm.state == FSMState.EXECUTING

        fsm.transition(FSMEvent.TOOLS_COMPLETE)
        assert fsm.state == FSMState.RESPONDING

        fsm.transition(FSMEvent.RESPONSE_DELIVERED)
        assert fsm.state == FSMState.IDLE

    def test_no_tools_shortcut(self):
        """PLANNING → RESPONDING when no tools needed (smalltalk)."""
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.NO_TOOLS)
        assert fsm.state == FSMState.RESPONDING
        fsm.transition(FSMEvent.RESPONSE_DELIVERED)
        assert fsm.state == FSMState.IDLE

    def test_history_recorded(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        assert len(fsm.history) == 2
        assert fsm.history[0].from_state == FSMState.IDLE
        assert fsm.history[0].to_state == FSMState.LISTENING
        assert fsm.history[0].event == FSMEvent.USER_INPUT


# ── TestConfirmationFlow ──────────────────────────────────────────────

class TestConfirmationFlow:
    """EXECUTING → CONFIRMING → EXECUTING / CANCELLED."""

    def test_confirm_and_continue(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        fsm.transition(FSMEvent.CONFIRMATION_REQUIRED)
        assert fsm.state == FSMState.CONFIRMING

        fsm.transition(FSMEvent.USER_CONFIRMED)
        assert fsm.state == FSMState.EXECUTING

        fsm.transition(FSMEvent.TOOLS_COMPLETE)
        assert fsm.state == FSMState.RESPONDING

    def test_deny_leads_to_cancelled(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        fsm.transition(FSMEvent.CONFIRMATION_REQUIRED)
        fsm.transition(FSMEvent.USER_DENIED)
        assert fsm.state == FSMState.CANCELLED

    def test_cancelled_to_idle(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        fsm.transition(FSMEvent.CONFIRMATION_REQUIRED)
        fsm.transition(FSMEvent.USER_DENIED)
        fsm.transition(FSMEvent.RESET)
        assert fsm.state == FSMState.IDLE


# ── TestErrorRecovery ─────────────────────────────────────────────────

class TestErrorRecovery:
    def test_error_from_executing(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        fsm.transition(FSMEvent.ERROR)
        assert fsm.state == FSMState.ERROR

    def test_error_handled_to_idle(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.ERROR)
        assert fsm.state == FSMState.ERROR
        fsm.transition(FSMEvent.ERROR_HANDLED)
        assert fsm.state == FSMState.IDLE

    def test_error_from_any_state(self):
        for state in (FSMState.IDLE, FSMState.LISTENING, FSMState.PLANNING,
                      FSMState.EXECUTING, FSMState.CONFIRMING, FSMState.RESPONDING):
            fsm = ConversationFSMv0(initial_state=state)
            fsm.transition(FSMEvent.ERROR)
            assert fsm.state == FSMState.ERROR


# ── TestCancel ────────────────────────────────────────────────────────

class TestCancel:
    def test_cancel_from_listening(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.USER_CANCEL)
        assert fsm.state == FSMState.CANCELLED

    def test_cancel_from_executing(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        fsm.transition(FSMEvent.USER_CANCEL)
        assert fsm.state == FSMState.CANCELLED


# ── TestInvalidTransitions ────────────────────────────────────────────

class TestInvalidTransitions:
    def test_invalid_returns_same_state(self):
        fsm = ConversationFSMv0()
        result = fsm.transition(FSMEvent.TOOLS_COMPLETE)
        assert result == FSMState.IDLE  # unchanged

    def test_invalid_not_in_history(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.TOOLS_COMPLETE)
        assert len(fsm.history) == 0

    def test_responding_to_executing_invalid(self):
        fsm = ConversationFSMv0(initial_state=FSMState.RESPONDING)
        result = fsm.transition(FSMEvent.PLAN_READY)
        assert result == FSMState.RESPONDING


# ── TestCanTransition / GetAllowedEvents ──────────────────────────────

class TestStateQuery:
    def test_can_transition_true(self):
        fsm = ConversationFSMv0()
        assert fsm.can_transition(FSMEvent.USER_INPUT)

    def test_can_transition_false(self):
        fsm = ConversationFSMv0()
        assert not fsm.can_transition(FSMEvent.TOOLS_COMPLETE)

    def test_can_transition_string_event(self):
        fsm = ConversationFSMv0()
        assert fsm.can_transition("user_input")

    def test_get_allowed_events(self):
        fsm = ConversationFSMv0()
        allowed = fsm.get_allowed_events()
        assert FSMEvent.USER_INPUT in allowed
        assert FSMEvent.ERROR in allowed
        assert FSMEvent.USER_CANCEL in allowed
        assert FSMEvent.TOOLS_COMPLETE not in allowed


# ── TestTimeout ───────────────────────────────────────────────────────

class TestTimeout:
    def test_executing_timeout(self):
        fsm = ConversationFSMv0(executing_timeout=0.05)
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        assert fsm.state == FSMState.EXECUTING

        time.sleep(0.1)
        # Accessing .state triggers timeout check
        assert fsm.state == FSMState.ERROR

    def test_no_timeout_when_fast(self):
        fsm = ConversationFSMv0(executing_timeout=10.0)
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        fsm.transition(FSMEvent.PLAN_READY)
        assert fsm.state == FSMState.EXECUTING  # no timeout yet


# ── TestCallbacks ─────────────────────────────────────────────────────

class TestCallbacks:
    def test_on_enter_callback(self):
        fsm = ConversationFSMv0()
        cb = MagicMock()
        fsm.on_enter(FSMState.LISTENING, cb)

        fsm.transition(FSMEvent.USER_INPUT)
        cb.assert_called_once()
        args = cb.call_args[0]
        assert args[0] == FSMState.IDLE       # from_state
        assert args[1] == FSMState.LISTENING   # to_state
        assert args[2] == FSMEvent.USER_INPUT  # event

    def test_on_exit_callback(self):
        fsm = ConversationFSMv0()
        cb = MagicMock()
        fsm.on_exit(FSMState.IDLE, cb)

        fsm.transition(FSMEvent.USER_INPUT)
        cb.assert_called_once()

    def test_callback_exception_does_not_break_transition(self):
        fsm = ConversationFSMv0()
        fsm.on_enter(FSMState.LISTENING, lambda *a: 1 / 0)
        # Should not raise
        fsm.transition(FSMEvent.USER_INPUT)
        assert fsm.state == FSMState.LISTENING


# ── TestReset ─────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_state_and_history(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT)
        fsm.transition(FSMEvent.INPUT_COMPLETE)
        assert len(fsm.history) == 2
        fsm.reset()
        assert fsm.state == FSMState.IDLE
        assert fsm.history == []


# ── TestStringEvent ───────────────────────────────────────────────────

class TestStringEvent:
    def test_string_event_accepted(self):
        fsm = ConversationFSMv0()
        fsm.transition("user_input")
        assert fsm.state == FSMState.LISTENING

    def test_metadata_in_history(self):
        fsm = ConversationFSMv0()
        fsm.transition(FSMEvent.USER_INPUT, source="microphone")
        assert fsm.history[0].metadata == {"source": "microphone"}


# ── TestTransitionRecord ──────────────────────────────────────────────

class TestTransitionRecord:
    def test_fields(self):
        rec = TransitionRecord(
            from_state=FSMState.IDLE,
            to_state=FSMState.LISTENING,
            event=FSMEvent.USER_INPUT,
        )
        assert rec.from_state == FSMState.IDLE
        assert rec.to_state == FSMState.LISTENING
        assert rec.event == FSMEvent.USER_INPUT
        assert isinstance(rec.timestamp, type(rec.timestamp))
