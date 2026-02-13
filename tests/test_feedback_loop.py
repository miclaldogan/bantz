"""Tests for FeedbackLoop (Issue #876)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bantz.learning.feedback_loop import (
    CONFIDENCE_AUTO_THRESHOLD,
    DEFAULT_EXPLORATION_EPSILON,
    FeedbackDecision,
    FeedbackEvent,
    FeedbackLoop,
    _CORRECTION_PREFIXES,
    create_feedback_loop,
)


# ── FeedbackEvent ────────────────────────────────────────────────

class TestFeedbackEvent:

    def test_defaults(self):
        e = FeedbackEvent(event_type="turn")
        assert e.event_type == "turn"
        assert e.success is True
        assert e.timestamp > 0


# ── FeedbackDecision ─────────────────────────────────────────────

class TestFeedbackDecision:

    def test_defaults(self):
        d = FeedbackDecision()
        assert d.should_ask is False
        assert d.confidence == 0.0


# ── FeedbackLoop — turn lifecycle ────────────────────────────────

class TestTurnLifecycle:

    def test_turn_increments(self):
        fl = FeedbackLoop()
        fl.on_turn_start("merhaba")
        assert fl._turn_count == 1
        fl.on_turn_start("nasılsın")
        assert fl._turn_count == 2

    def test_on_turn_end_records(self):
        fl = FeedbackLoop()
        fl.on_turn_start("test")
        fl.on_turn_end("test", "cevap", intent="greeting")
        # No crash = pass

    def test_get_prompt_context_no_crash(self):
        fl = FeedbackLoop()
        ctx = fl.get_prompt_context()
        assert isinstance(ctx, str)


# ── FeedbackLoop — tool execution ───────────────────────────────

class TestToolExecution:

    def test_tracks_tool_usage(self):
        fl = FeedbackLoop()
        fl.on_tool_executed("calendar.list_events", {}, [], success=True, elapsed_ms=100)
        assert fl._tool_usage["calendar.list_events"] == 1
        fl.on_tool_executed("calendar.list_events", {}, [], success=True, elapsed_ms=50)
        assert fl._tool_usage["calendar.list_events"] == 2

    def test_returns_reward(self):
        fl = FeedbackLoop()
        reward = fl.on_tool_executed("test_tool", {}, "ok", success=True)
        assert isinstance(reward, (int, float))

    def test_get_tool_defaults_empty(self):
        fl = FeedbackLoop()
        defaults = fl.get_tool_defaults("calendar_create_event")
        assert isinstance(defaults, dict)


# ── FeedbackLoop — confidence evaluation ────────────────────────

class TestConfidenceEvaluation:

    def test_high_confidence_auto(self):
        fl = FeedbackLoop()
        d = fl.evaluate_confidence("greeting", confidence=0.95)
        assert d.should_ask is False
        assert d.confidence == 0.95
        assert d.auto_explanation

    def test_low_confidence_asks(self):
        fl = FeedbackLoop()
        d = fl.evaluate_confidence("complex_task", confidence=0.5)
        assert d.should_ask is True
        assert d.question
        assert "%" in d.question

    def test_threshold_boundary(self):
        fl = FeedbackLoop(confidence_threshold=0.9)
        # Exactly at threshold → auto
        d = fl.evaluate_confidence("test", confidence=0.9)
        assert d.should_ask is False
        # Just below → ask
        d = fl.evaluate_confidence("test", confidence=0.89)
        assert d.should_ask is True


# ── FeedbackLoop — correction handling ──────────────────────────

class TestCorrectionHandling:

    def test_detects_correction(self):
        fl = FeedbackLoop()
        assert fl.is_correction("hayır yanlış anlamışsın") is True
        assert fl.is_correction("aslında ben başka bir şey istedim") is True
        assert fl.is_correction("yanlış anladın") is True
        assert fl.is_correction("düzelt lütfen") is True

    def test_not_correction(self):
        fl = FeedbackLoop()
        assert fl.is_correction("merhaba") is False
        assert fl.is_correction("takvime toplantı ekle") is False

    def test_handle_correction_returns_ack(self):
        fl = FeedbackLoop()
        ack = fl.handle_correction(
            "hayır sabahları severim",
            "Öğlene aldım",
            intent="calendar_create_event",
        )
        assert "hatırlayacağım" in ack.lower() or "anladım" in ack.lower()

    def test_corrections_tracked(self):
        fl = FeedbackLoop()
        fl.handle_correction("hayır", "yanlış", intent="test")
        assert len(fl._corrections) == 1

    def test_handle_cancellation(self):
        fl = FeedbackLoop()
        fl.handle_cancellation("gmail_send", reason="vazgeçtim")
        # No crash = ok


# ── FeedbackLoop — exploration ──────────────────────────────────

class TestExploration:

    def test_suggest_exploration_returns_none_without_bandit(self):
        fl = FeedbackLoop()
        result = fl.suggest_exploration(["tool_a", "tool_b"])
        # May return None if bandit not available, or a tool name
        assert result is None or result in ("tool_a", "tool_b")


# ── FeedbackLoop — session summary ──────────────────────────────

class TestSessionSummary:

    def test_empty_summary(self):
        fl = FeedbackLoop()
        s = fl.get_session_summary()
        assert s["turn_count"] == 0
        assert s["corrections_count"] == 0

    def test_summary_after_activity(self):
        fl = FeedbackLoop()
        fl.on_turn_start("hello")
        fl.on_tool_executed("t1", {}, "ok")
        fl.handle_correction("hayır", "x", intent="y")
        s = fl.get_session_summary()
        assert s["turn_count"] == 1
        assert s["tool_usage"]["t1"] == 1
        assert s["corrections_count"] == 1

    def test_reset_clears_all(self):
        fl = FeedbackLoop()
        fl.on_turn_start("x")
        fl.on_tool_executed("t", {}, "ok")
        fl.reset()
        s = fl.get_session_summary()
        assert s["turn_count"] == 0


# ── Factory ──────────────────────────────────────────────────────

class TestFactory:

    def test_create_default(self):
        fl = create_feedback_loop()
        assert isinstance(fl, FeedbackLoop)
        assert fl._exploration_epsilon == DEFAULT_EXPLORATION_EPSILON

    def test_create_custom(self):
        fl = create_feedback_loop(
            user_id="alice",
            exploration_epsilon=0.2,
            confidence_threshold=0.8,
        )
        assert fl._user_id == "alice"
        assert fl._exploration_epsilon == 0.2
        assert fl._confidence_threshold == 0.8


# ── Correction prefixes ─────────────────────────────────────────

class TestCorrectionPrefixes:

    def test_all_prefixes_are_lowercase(self):
        for p in _CORRECTION_PREFIXES:
            assert p == p.lower()
