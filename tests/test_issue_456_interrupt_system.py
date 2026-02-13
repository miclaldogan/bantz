"""Tests for issue #456 — Interrupt system: STOP/CANCEL/PAUSE/RESUME."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call

import pytest

from bantz.core.interrupt_controller import (
    INTERRUPT_KEYWORDS,
    InterruptController,
    InterruptSignal,
    InterruptType,
)


# ── Signal basics ─────────────────────────────────────────────────────

class TestInterruptType:
    def test_enum_values(self):
        assert InterruptType.STOP.value == "stop"
        assert InterruptType.CANCEL.value == "cancel"
        assert InterruptType.PAUSE.value == "pause"
        assert InterruptType.RESUME.value == "resume"

    def test_str(self):
        assert str(InterruptType.STOP) == "stop"


class TestInterruptSignal:
    def test_fields(self):
        sig = InterruptSignal(interrupt_type=InterruptType.CANCEL, source="voice")
        assert sig.interrupt_type == InterruptType.CANCEL
        assert sig.source == "voice"
        assert sig.timestamp is not None


# ── Controller: signal + query ────────────────────────────────────────

class TestControllerSignal:
    def test_signal_sets_pending(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.CANCEL)
        assert ctrl.is_interrupted()

    def test_get_pending_consumes(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.STOP, source="keyboard")
        sig = ctrl.get_pending()
        assert sig is not None
        assert sig.interrupt_type == InterruptType.STOP
        assert sig.source == "keyboard"
        assert not ctrl.is_interrupted()

    def test_get_pending_none_when_empty(self):
        ctrl = InterruptController()
        assert ctrl.get_pending() is None

    def test_signal_string_coercion(self):
        ctrl = InterruptController()
        ctrl.signal("pause", source="api")
        sig = ctrl.get_pending()
        assert sig.interrupt_type == InterruptType.PAUSE

    def test_metadata_stored(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.CANCEL, source="voice", reason="user said dur")
        sig = ctrl.get_pending()
        assert sig.metadata == {"reason": "user said dur"}


# ── PAUSE / RESUME ────────────────────────────────────────────────────

class TestPauseResume:
    def test_pause_sets_flag(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.PAUSE)
        assert ctrl.is_paused()

    def test_resume_clears_flag(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.PAUSE)
        ctrl.get_pending()  # consume
        ctrl.signal(InterruptType.RESUME)
        assert not ctrl.is_paused()

    def test_not_paused_initially(self):
        ctrl = InterruptController()
        assert not ctrl.is_paused()


# ── Handler registry ──────────────────────────────────────────────────

class TestHandlerRegistry:
    def test_handler_called(self):
        ctrl = InterruptController()
        cb = MagicMock()
        ctrl.register_handler(cb)
        ctrl.signal(InterruptType.CANCEL)
        cb.assert_called_once()
        sig: InterruptSignal = cb.call_args[0][0]
        assert sig.interrupt_type == InterruptType.CANCEL

    def test_priority_order(self):
        ctrl = InterruptController()
        order = []
        ctrl.register_handler(lambda s: order.append("low"), priority=1)
        ctrl.register_handler(lambda s: order.append("high"), priority=10)
        ctrl.signal(InterruptType.STOP)
        assert order == ["high", "low"]

    def test_unregister_handler(self):
        ctrl = InterruptController()
        cb = MagicMock()
        ctrl.register_handler(cb)
        assert ctrl.unregister_handler(cb)
        ctrl.signal(InterruptType.CANCEL)
        cb.assert_not_called()

    def test_unregister_missing_returns_false(self):
        ctrl = InterruptController()
        assert not ctrl.unregister_handler(lambda s: None)

    def test_handler_exception_does_not_break(self):
        ctrl = InterruptController()
        ctrl.register_handler(lambda s: 1 / 0, priority=10)
        good = MagicMock()
        ctrl.register_handler(good, priority=1)
        ctrl.signal(InterruptType.CANCEL)
        good.assert_called_once()


# ── History ───────────────────────────────────────────────────────────

class TestHistory:
    def test_history_recorded(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.CANCEL)
        ctrl.signal(InterruptType.STOP)
        assert len(ctrl.history) == 2
        assert ctrl.history[0].interrupt_type == InterruptType.CANCEL
        assert ctrl.history[1].interrupt_type == InterruptType.STOP

    def test_history_max(self):
        ctrl = InterruptController(max_history=3)
        for _ in range(5):
            ctrl.signal(InterruptType.CANCEL)
        assert len(ctrl.history) == 3


# ── Clear / Reset ─────────────────────────────────────────────────────

class TestClearReset:
    def test_clear(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.PAUSE)
        ctrl.clear()
        assert not ctrl.is_interrupted()
        assert not ctrl.is_paused()

    def test_reset(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.CANCEL)
        ctrl.reset()
        assert not ctrl.is_interrupted()
        assert ctrl.history == []


# ── Keyword detection ─────────────────────────────────────────────────

class TestKeywordDetection:
    @pytest.mark.parametrize("word,expected", [
        ("dur", InterruptType.STOP),
        ("stop", InterruptType.STOP),
        ("kapat", InterruptType.STOP),
        ("iptal", InterruptType.CANCEL),
        ("cancel", InterruptType.CANCEL),
        ("vazgeç", InterruptType.CANCEL),
        ("bekle", InterruptType.PAUSE),
        ("pause", InterruptType.PAUSE),
        ("duraklat", InterruptType.PAUSE),
        ("devam et", InterruptType.RESUME),
        ("resume", InterruptType.RESUME),
    ])
    def test_keyword(self, word, expected):
        assert InterruptController.detect_keyword(word) == expected

    def test_devam_et_preferred_over_devam(self):
        """'devam et' (RESUME) should match before 'devam' substring."""
        result = InterruptController.detect_keyword("devam et lütfen")
        assert result == InterruptType.RESUME

    def test_no_keyword(self):
        assert InterruptController.detect_keyword("hava nasıl") is None

    def test_empty_string(self):
        assert InterruptController.detect_keyword("") is None

    def test_case_insensitive(self):
        assert InterruptController.detect_keyword("DUR") == InterruptType.STOP


# ── Ctrl+C ────────────────────────────────────────────────────────────

class TestCtrlC:
    def test_first_ctrl_c_cancel(self):
        ctrl = InterruptController()
        result = ctrl.handle_ctrl_c()
        assert result == "cancel"
        sig = ctrl.get_pending()
        assert sig.interrupt_type == InterruptType.CANCEL

    def test_double_ctrl_c_stop(self):
        ctrl = InterruptController()
        ctrl.handle_ctrl_c()
        ctrl.get_pending()  # consume first
        result = ctrl.handle_ctrl_c()
        assert result == "stop"
        sig = ctrl.get_pending()
        assert sig.interrupt_type == InterruptType.STOP

    def test_ctrl_c_timeout_resets(self):
        """After 2s window expires, next Ctrl+C is treated as first."""
        ctrl = InterruptController()
        ctrl.handle_ctrl_c()
        ctrl.get_pending()
        # Simulate time passing beyond 2s window
        with ctrl._lock:
            ctrl._ctrl_c_ts = time.monotonic() - 3.0
            ctrl._ctrl_c_count = 1
        result = ctrl.handle_ctrl_c()
        assert result == "cancel"  # fresh start


# ── Tool execution check ─────────────────────────────────────────────

class TestCheckBeforeTool:
    def test_returns_none_when_clear(self):
        ctrl = InterruptController()
        assert ctrl.check_before_tool() is None

    def test_returns_signal_when_interrupted(self):
        ctrl = InterruptController()
        ctrl.signal(InterruptType.CANCEL)
        sig = ctrl.check_before_tool()
        assert sig.interrupt_type == InterruptType.CANCEL
        assert not ctrl.is_interrupted()


# ── Wait ──────────────────────────────────────────────────────────────

class TestWait:
    def test_wait_timeout(self):
        ctrl = InterruptController()
        result = ctrl.wait(timeout=0.05)
        assert result is False

    def test_wait_signaled(self):
        ctrl = InterruptController()

        def _fire():
            time.sleep(0.05)
            ctrl.signal(InterruptType.STOP)

        t = threading.Thread(target=_fire)
        t.start()
        result = ctrl.wait(timeout=2.0)
        assert result is True
        t.join()
