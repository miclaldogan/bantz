"""Automation failsafe tests (Issue #853)."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

from bantz.automation.failsafe import (
    FailSafeAction,
    FailSafeChoice,
    FailSafeHandler,
    create_failsafe_handler,
)


# ─── Stub types ──────────────────────────────────────────────────

@dataclass
class _StubPlan:
    id: str = "plan-1"


@dataclass
class _StubStep:
    id: str = "step-1"
    description: str = "Do something"


# ─────────────────────────────────────────────────────────────────
# FailSafeAction enum
# ─────────────────────────────────────────────────────────────────

class TestFailSafeAction:

    def test_values(self):
        assert FailSafeAction.RETRY.value == "retry"
        assert FailSafeAction.SKIP.value == "skip"
        assert FailSafeAction.ABORT.value == "abort"
        assert FailSafeAction.MANUAL.value == "manual"
        assert FailSafeAction.MODIFY.value == "modify"


# ─────────────────────────────────────────────────────────────────
# FailSafeChoice
# ─────────────────────────────────────────────────────────────────

class TestFailSafeChoice:

    def test_create(self):
        c = FailSafeChoice(action=FailSafeAction.RETRY, reason="auto")
        assert c.action == FailSafeAction.RETRY
        assert c.reason == "auto"

    def test_to_dict(self):
        c = FailSafeChoice(action=FailSafeAction.ABORT, reason="user chose")
        d = c.to_dict()
        assert d["action"] == "abort"
        assert d["reason"] == "user chose"
        assert d["modified_step"] is None


# ─────────────────────────────────────────────────────────────────
# FailSafeHandler
# ─────────────────────────────────────────────────────────────────

class TestFailSafeHandler:

    def test_should_ask_user_below_threshold(self):
        h = FailSafeHandler()
        assert h.should_ask_user(1) is False

    def test_should_ask_user_at_threshold(self):
        h = FailSafeHandler()
        assert h.should_ask_user(FailSafeHandler.MAX_CONSECUTIVE_FAILURES) is True

    def test_should_ask_user_above_threshold(self):
        h = FailSafeHandler()
        assert h.should_ask_user(10) is True

    @pytest.mark.asyncio
    async def test_handle_first_failure_auto_retry(self):
        h = FailSafeHandler()
        choice = await h.handle_failure(_StubPlan(), _StubStep(), "error", 1)
        assert choice.action == FailSafeAction.RETRY

    @pytest.mark.asyncio
    async def test_handle_failure_records_history(self):
        h = FailSafeHandler()
        await h.handle_failure(_StubPlan(), _StubStep(), "err1", 1)
        await h.handle_failure(_StubPlan(), _StubStep(), "err2", 1)
        history = h.get_failure_history()
        assert len(history) == 2
        assert history[0]["error"] == "err1"

    def test_clear_history(self):
        h = FailSafeHandler()
        h._failure_history.append({"error": "test"})
        h.clear_history()
        assert h.get_failure_history() == []

    @pytest.mark.asyncio
    async def test_handle_failure_at_threshold_no_asr(self):
        """Without ASR, ask_user_choice defaults to 0 (RETRY)."""
        h = FailSafeHandler()
        choice = await h.handle_failure(
            _StubPlan(), _StubStep(), "repeated error",
            FailSafeHandler.MAX_CONSECUTIVE_FAILURES,
        )
        # With no ASR, ask_user_choice returns 0 → RETRY
        assert choice.action == FailSafeAction.RETRY

    @pytest.mark.asyncio
    async def test_ask_user_choice_no_asr(self):
        h = FailSafeHandler()
        idx = await h.ask_user_choice(["Retry", "Skip", "Abort"])
        assert idx == 0  # default when no ASR

    @pytest.mark.asyncio
    async def test_ask_user_choice_with_asr_number(self):
        mock_asr = AsyncMock()
        mock_asr.listen.return_value = "2"
        h = FailSafeHandler(asr=mock_asr)
        idx = await h.ask_user_choice(["Retry", "Skip", "Abort"])
        assert idx == 1  # "2" → index 1

    @pytest.mark.asyncio
    async def test_ask_user_choice_with_asr_keyword(self):
        mock_asr = AsyncMock()
        mock_asr.listen.return_value = "iptal ediyorum"
        h = FailSafeHandler(asr=mock_asr)
        idx = await h.ask_user_choice(["Retry", "Skip", "Abort", "Manual"])
        assert idx == 2  # "iptal" → ABORT

    @pytest.mark.asyncio
    async def test_ask_user_choice_asr_error_defaults(self):
        mock_asr = AsyncMock()
        mock_asr.listen.side_effect = RuntimeError("mic error")
        h = FailSafeHandler(asr=mock_asr)
        idx = await h.ask_user_choice(["Retry", "Skip"])
        assert idx == 0


# ─────────────────────────────────────────────────────────────────
# wait_for_manual_completion
# ─────────────────────────────────────────────────────────────────

class TestManualCompletion:

    @pytest.mark.asyncio
    async def test_no_asr_returns_true(self):
        h = FailSafeHandler()
        assert await h.wait_for_manual_completion() is True

    @pytest.mark.asyncio
    async def test_completion_word(self):
        mock_asr = AsyncMock()
        mock_asr.listen.return_value = "bitti, tamamlandı"
        h = FailSafeHandler(asr=mock_asr)
        assert await h.wait_for_manual_completion() is True

    @pytest.mark.asyncio
    async def test_non_completion_word(self):
        mock_asr = AsyncMock()
        mock_asr.listen.return_value = "henüz değil"
        h = FailSafeHandler(asr=mock_asr)
        assert await h.wait_for_manual_completion() is False


# ─────────────────────────────────────────────────────────────────
# Language & Factory
# ─────────────────────────────────────────────────────────────────

class TestLanguageAndFactory:

    def test_turkish_messages(self):
        h = FailSafeHandler(language="tr")
        assert "başarısız" in h._messages["failure_notice"]

    def test_english_messages(self):
        h = FailSafeHandler(language="en")
        assert "failed" in h._messages["failure_notice"]

    def test_create_failsafe_handler(self):
        h = create_failsafe_handler(language="en")
        assert isinstance(h, FailSafeHandler)
        assert h._language == "en"

    def test_max_consecutive_failures_constant(self):
        assert FailSafeHandler.MAX_CONSECUTIVE_FAILURES == 2
