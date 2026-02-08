"""
Tests for Issue #428 — Barge-in CancellationToken & Turn Isolation.

Covers:
- CancellationToken: cancel / reset / wait
- TurnContext: turn_id isolation, add_tool_result, cancellation
- BargeInHandler turn lifecycle: start_turn, finish_turn, is_turn_valid
- Barge-in cancels active turn's tools
- Stale turn results discarded
- Stats include cancelled_turns
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bantz.conversation.bargein import (
    BargeInAction,
    BargeInEvent,
    BargeInHandler,
    CancellationToken,
    TurnContext,
)


# ─────────────────────────────────────────────────────────────────
# CancellationToken
# ─────────────────────────────────────────────────────────────────


class TestCancellationToken:
    """Test cooperative cancellation token."""

    def test_initial_state(self):
        token = CancellationToken()
        assert not token.is_cancelled

    def test_cancel(self):
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled

    def test_reset(self):
        token = CancellationToken()
        token.cancel()
        token.reset()
        assert not token.is_cancelled

    def test_double_cancel_safe(self):
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled

    @pytest.mark.asyncio
    async def test_wait_returns_true_on_cancel(self):
        token = CancellationToken()

        async def _cancel_soon():
            await asyncio.sleep(0.01)
            token.cancel()

        asyncio.create_task(_cancel_soon())
        result = await token.wait(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_timeout(self):
        token = CancellationToken()
        result = await token.wait(timeout=0.01)
        assert result is False


# ─────────────────────────────────────────────────────────────────
# TurnContext
# ─────────────────────────────────────────────────────────────────


class TestTurnContext:
    """Test per-turn isolation context."""

    def test_unique_turn_id(self):
        ctx1 = TurnContext()
        ctx2 = TurnContext()
        assert ctx1.turn_id != ctx2.turn_id

    def test_add_tool_result_tags_turn_id(self):
        ctx = TurnContext()
        ctx.add_tool_result({"tool": "calendar.list_events", "success": True})
        assert ctx.tool_results[0]["_turn_id"] == ctx.turn_id

    def test_cancel_propagates(self):
        ctx = TurnContext()
        assert not ctx.is_cancelled
        ctx.cancel()
        assert ctx.is_cancelled
        assert ctx.cancellation_token.is_cancelled

    def test_tool_results_are_copies(self):
        ctx = TurnContext()
        ctx.add_tool_result({"tool": "t1"})
        results = ctx.tool_results
        results.append({"tool": "t2"})
        assert len(ctx.tool_results) == 1  # original unchanged


# ─────────────────────────────────────────────────────────────────
# BargeInHandler Turn Lifecycle
# ─────────────────────────────────────────────────────────────────


class TestBargeInTurnLifecycle:
    """Test start_turn / finish_turn / is_turn_valid."""

    def test_start_turn_creates_context(self):
        handler = BargeInHandler()
        ctx = handler.start_turn()
        assert ctx.turn_id
        assert handler.active_turn is ctx

    def test_finish_turn_clears_active(self):
        handler = BargeInHandler()
        handler.start_turn()
        handler.finish_turn()
        assert handler.active_turn is None

    def test_is_turn_valid_active(self):
        handler = BargeInHandler()
        ctx = handler.start_turn()
        assert handler.is_turn_valid(ctx.turn_id)

    def test_is_turn_valid_wrong_id(self):
        handler = BargeInHandler()
        handler.start_turn()
        assert not handler.is_turn_valid("nonexistent")

    def test_is_turn_valid_cancelled(self):
        handler = BargeInHandler()
        ctx = handler.start_turn()
        ctx.cancel()
        assert not handler.is_turn_valid(ctx.turn_id)

    def test_is_turn_valid_no_active(self):
        handler = BargeInHandler()
        assert not handler.is_turn_valid("any")

    def test_start_new_turn_cancels_old(self):
        handler = BargeInHandler()
        old = handler.start_turn()
        new = handler.start_turn()
        assert old.is_cancelled
        assert not new.is_cancelled
        assert handler.active_turn is new


# ─────────────────────────────────────────────────────────────────
# Barge-in Cancellation
# ─────────────────────────────────────────────────────────────────


def _make_tts(playing: bool = True):
    tts = MagicMock()
    tts.is_playing.return_value = playing
    tts.stop = AsyncMock()
    return tts


class TestBargeInCancellation:
    """Test that barge-in cancels the active turn."""

    @pytest.mark.asyncio
    async def test_barge_in_cancels_active_turn(self):
        tts = _make_tts(playing=True)
        handler = BargeInHandler(tts=tts, interrupt_threshold=0.3)
        ctx = handler.start_turn()

        event = BargeInEvent(speech_volume=0.8, speech_duration_ms=500)
        action = await handler.handle(event)

        assert action != BargeInAction.IGNORE
        assert ctx.is_cancelled

    @pytest.mark.asyncio
    async def test_ignored_barge_in_does_not_cancel(self):
        tts = _make_tts(playing=True)
        handler = BargeInHandler(tts=tts, interrupt_threshold=0.9)
        ctx = handler.start_turn()

        event = BargeInEvent(speech_volume=0.3, speech_duration_ms=500)
        action = await handler.handle(event)

        assert action == BargeInAction.IGNORE
        assert not ctx.is_cancelled

    @pytest.mark.asyncio
    async def test_barge_in_no_active_turn_safe(self):
        """No active turn — barge-in should still work without error."""
        tts = _make_tts(playing=True)
        handler = BargeInHandler(tts=tts, interrupt_threshold=0.3)

        event = BargeInEvent(speech_volume=0.8, speech_duration_ms=500)
        action = await handler.handle(event)
        assert action != BargeInAction.IGNORE

    @pytest.mark.asyncio
    async def test_stats_cancelled_turns(self):
        tts = _make_tts(playing=True)
        handler = BargeInHandler(tts=tts, interrupt_threshold=0.3)
        handler.start_turn()

        event = BargeInEvent(speech_volume=0.8, speech_duration_ms=500)
        await handler.handle(event)

        stats = handler.get_stats()
        assert stats["cancelled_turns"] == 1


# ─────────────────────────────────────────────────────────────────
# Stale Result Isolation
# ─────────────────────────────────────────────────────────────────


class TestStaleResultIsolation:
    """Verify that results from a cancelled turn are discardable."""

    def test_cancelled_turn_results_still_accessible(self):
        """Results aren't deleted — caller checks is_turn_valid."""
        ctx = TurnContext()
        ctx.add_tool_result({"tool": "calendar.list_events", "ok": True})
        ctx.cancel()
        assert len(ctx.tool_results) == 1
        assert ctx.is_cancelled

    def test_handler_is_turn_valid_rejects_cancelled(self):
        handler = BargeInHandler()
        ctx = handler.start_turn()
        turn_id = ctx.turn_id
        ctx.cancel()
        assert not handler.is_turn_valid(turn_id)

    def test_new_turn_has_empty_results(self):
        handler = BargeInHandler()
        old = handler.start_turn()
        old.add_tool_result({"tool": "t1"})
        new = handler.start_turn()
        assert new.tool_results == []
        assert old.tool_results[0]["tool"] == "t1"


# ─────────────────────────────────────────────────────────────────
# Edge Cases
# ─────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases for barge-in cancellation."""

    def test_clear_history_resets(self):
        handler = BargeInHandler()
        handler.start_turn()
        count = handler.clear_history()
        assert count == 0  # no events recorded yet

    @pytest.mark.asyncio
    async def test_multiple_barge_ins_only_one_cancel(self):
        """Two rapid barge-ins — second should not crash."""
        tts = _make_tts(playing=True)
        handler = BargeInHandler(tts=tts, interrupt_threshold=0.3)
        handler.start_turn()

        event1 = BargeInEvent(speech_volume=0.8, speech_duration_ms=500)
        event2 = BargeInEvent(speech_volume=0.8, speech_duration_ms=500)
        await handler.handle(event1)
        await handler.handle(event2)
        # Should not raise
        stats = handler.get_stats()
        assert stats["cancelled_turns"] == 1  # already cancelled

    def test_turn_context_tool_result_count(self):
        ctx = TurnContext()
        for i in range(5):
            ctx.add_tool_result({"tool": f"tool_{i}"})
        assert len(ctx.tool_results) == 5
