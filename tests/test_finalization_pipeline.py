"""Tests for FinalizationPipeline (Issue #404).

Covers:
- FinalizationContext construction
- NoNewFactsGuard (violation detection, retry, passthrough)
- QualityFinalizer (prompt building, guard integration)
- FastFinalizer (prompt building, error handling)
- FinalizationPipeline (ask_user, hard failures, quality, fast, defaults)
- decide_finalization_tier (smalltalk, tiering, fallback)
- Factory helpers (build_finalization_context, create_pipeline)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Optional
from unittest.mock import Mock, MagicMock, patch

import pytest

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.brain.finalization_pipeline import (
    FinalizationContext,
    NoNewFactsGuard,
    QualityFinalizer,
    FastFinalizer,
    FinalizationPipeline,
    build_finalization_context,
    create_pipeline,
    decide_finalization_tier,
    _check_hard_failures,
    _extract_reason_code,
    _safe_complete,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_output(**overrides: Any) -> OrchestratorOutput:
    """Create an OrchestratorOutput with sensible defaults."""
    defaults = dict(
        route="calendar",
        calendar_intent="query",
        slots={},
        confidence=0.9,
        tool_plan=["calendar.list_events"],
        assistant_reply="",
        ask_user=False,
        question="",
        requires_confirmation=False,
        confirmation_prompt="",
    )
    defaults.update(overrides)
    return OrchestratorOutput(**defaults)


def _make_state(**overrides: Any) -> OrchestratorState:
    """Create an OrchestratorState with sensible defaults."""
    state = OrchestratorState(**overrides)
    return state


def _make_ctx(**overrides: Any) -> FinalizationContext:
    """Create a FinalizationContext with sensible defaults."""
    defaults = dict(
        user_input="yarınki toplantılar ne?",
        orchestrator_output=_make_output(),
        tool_results=[{"tool": "calendar.list_events", "success": True, "result": "2 etkinlik"}],
        state=_make_state(),
        planner_decision={"route": "calendar"},
        dialog_summary="Daha önce takvim sorgusu yapıldı.",
        use_quality=True,
        tier_name="quality",
        tier_reason="finalizer_default",
    )
    defaults.update(overrides)
    return FinalizationContext(**defaults)


@pytest.fixture
def mock_llm():
    """Mock LLM that returns a fixed Turkish reply."""
    llm = Mock()
    llm.complete_text = Mock(return_value="Efendim, yarın 2 toplantınız var.")
    return llm


@pytest.fixture
def mock_planner_llm():
    """Mock planner (3B) LLM."""
    llm = Mock()
    llm.complete_text = Mock(return_value="Yarın 2 toplantı var efendim.")
    return llm


# =============================================================================
# _check_hard_failures
# =============================================================================

class TestCheckHardFailures:
    def test_no_results_returns_none(self):
        assert _check_hard_failures([]) is None

    def test_all_success_returns_none(self):
        results = [{"tool": "x", "success": True}]
        assert _check_hard_failures(results) is None

    def test_pending_confirmation_ignored(self):
        results = [{"tool": "x", "success": False, "pending_confirmation": True}]
        assert _check_hard_failures(results) is None

    def test_hard_failure_returns_error_msg(self):
        results = [{"tool": "calendar.create", "success": False, "error": "Auth fail"}]
        msg = _check_hard_failures(results)
        assert msg is not None
        assert "calendar.create" in msg
        assert "Auth fail" in msg


# =============================================================================
# _extract_reason_code
# =============================================================================

class TestExtractReasonCode:
    def test_extracts_reason(self):
        err = Exception("LLM failed reason=rate_limit bla")
        assert _extract_reason_code(err) == "rate_limit"

    def test_unknown_on_no_match(self):
        err = Exception("generic error")
        assert _extract_reason_code(err) == "unknown_error"


# =============================================================================
# _safe_complete
# =============================================================================

class TestSafeComplete:
    def test_normal_call(self, mock_llm):
        result = _safe_complete(mock_llm, "hello")
        assert result == "Efendim, yarın 2 toplantınız var."

    def test_strips_whitespace(self):
        llm = Mock()
        llm.complete_text = Mock(return_value="  merhaba  ")
        assert _safe_complete(llm, "hi") == "merhaba"

    def test_empty_returns_none(self):
        llm = Mock()
        llm.complete_text = Mock(return_value="")
        assert _safe_complete(llm, "hi") is None

    def test_none_returns_none(self):
        llm = Mock()
        llm.complete_text = Mock(return_value=None)
        assert _safe_complete(llm, "hi") is None

    def test_type_error_fallback(self):
        """If LLM doesn't accept kwargs, falls back to prompt-only."""
        llm = Mock()
        llm.complete_text = Mock(side_effect=[TypeError("no kwargs"), "ok"])
        result = _safe_complete(llm, "hi")
        assert result == "ok"


# =============================================================================
# NoNewFactsGuard
# =============================================================================

class TestNoNewFactsGuard:
    def test_no_violation_passes_through(self, mock_llm):
        guard = NoNewFactsGuard(finalizer_llm=mock_llm)
        state = _make_state()

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(return_value=(False, set()))

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            result = guard.check_and_retry(
                candidate_text="Efendim, 2 toplantınız var.",
                allowed_sources=["yarınki toplantılar"],
                original_prompt="prompt",
                state=state,
            )
        assert result == "Efendim, 2 toplantınız var."

    def test_violation_triggers_retry(self, mock_llm):
        """First call violates, retry doesn't — returns retry text."""
        guard = NoNewFactsGuard(finalizer_llm=mock_llm)
        state = _make_state()

        call_count = [0]

        def fake_guard(allowed_texts, candidate_text):
            call_count[0] += 1
            if call_count[0] == 1:
                return (True, {"99"})
            return (False, set())

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(side_effect=fake_guard)

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            result = guard.check_and_retry(
                candidate_text="Orijinal metin 99 uydurma.",
                allowed_sources=["yarınki toplantılar"],
                original_prompt="prompt",
                state=state,
            )
        # Returns the retry LLM output
        assert result == "Efendim, yarın 2 toplantınız var."
        assert state.trace.get("finalizer_guard_violation") is True

    def test_double_violation_returns_none(self, mock_llm):
        """Both original and retry violate → returns None."""
        guard = NoNewFactsGuard(finalizer_llm=mock_llm)
        state = _make_state()

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(return_value=(True, {"fake_num"}))

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            result = guard.check_and_retry(
                candidate_text="Uydurma 42 sayı.",
                allowed_sources=["kaynak"],
                original_prompt="prompt",
                state=state,
            )
        assert result is None

    def test_import_error_passes_through(self, mock_llm):
        """If no_new_facts module is missing, passes through."""
        guard = NoNewFactsGuard(finalizer_llm=mock_llm)
        state = _make_state()

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": None}):
            result = guard.check_and_retry(
                candidate_text="some text",
                allowed_sources=["source"],
                original_prompt="prompt",
                state=state,
            )
        # ImportError during `from ... import` → returns candidate_text
        assert result == "some text"


# =============================================================================
# QualityFinalizer
# =============================================================================

class TestQualityFinalizer:
    def test_finalize_returns_text(self, mock_llm):
        qf = QualityFinalizer(finalizer_llm=mock_llm, guard=None)
        ctx = _make_ctx()
        result = qf.finalize(ctx)
        assert result is not None
        assert "toplantı" in result

    def test_finalize_with_guard_passes(self, mock_llm):
        guard = NoNewFactsGuard(finalizer_llm=mock_llm)
        qf = QualityFinalizer(finalizer_llm=mock_llm, guard=guard)
        ctx = _make_ctx()

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(return_value=(False, set()))

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            result = qf.finalize(ctx)
        assert result is not None

    def test_finalize_guard_rejects_returns_none(self, mock_llm):
        """If guard rejects both original and retry → None."""
        guard = NoNewFactsGuard(finalizer_llm=mock_llm)
        qf = QualityFinalizer(finalizer_llm=mock_llm, guard=guard)
        ctx = _make_ctx()

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(return_value=(True, {"fake"}))

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            result = qf.finalize(ctx)
        assert result is None

    def test_finalize_empty_llm_returns_none(self):
        llm = Mock()
        llm.complete_text = Mock(return_value="")
        qf = QualityFinalizer(finalizer_llm=llm, guard=None)
        ctx = _make_ctx()
        result = qf.finalize(ctx)
        assert result is None

    def test_fallback_prompt_used_when_builder_fails(self, mock_llm):
        """When PromptBuilder raises, fallback prompt is used."""
        qf = QualityFinalizer(finalizer_llm=mock_llm, guard=None)
        ctx = _make_ctx()

        with patch(
            "bantz.brain.prompt_engineering.PromptBuilder",
            side_effect=Exception("builder broken"),
        ):
            result = qf.finalize(ctx)
        assert result is not None


# =============================================================================
# FastFinalizer
# =============================================================================

class TestFastFinalizer:
    def test_finalize_returns_text(self, mock_planner_llm):
        ff = FastFinalizer(planner_llm=mock_planner_llm)
        ctx = _make_ctx()
        result = ff.finalize(ctx)
        assert result is not None
        assert "toplantı" in result

    def test_finalize_includes_tool_results(self, mock_planner_llm):
        ff = FastFinalizer(planner_llm=mock_planner_llm)
        ctx = _make_ctx(
            tool_results=[{"tool": "calendar.list_events", "success": True, "result": "3 etkinlik"}]
        )
        ff.finalize(ctx)
        # Verify the prompt was built (LLM was called)
        mock_planner_llm.complete_text.assert_called_once()

    def test_finalize_no_tool_results(self, mock_planner_llm):
        ff = FastFinalizer(planner_llm=mock_planner_llm)
        ctx = _make_ctx(tool_results=[])
        result = ff.finalize(ctx)
        assert result is not None

    def test_finalize_error_returns_none(self):
        llm = Mock()
        llm.complete_text = Mock(side_effect=RuntimeError("LLM down"))
        ff = FastFinalizer(planner_llm=llm)
        ctx = _make_ctx()
        result = ff.finalize(ctx)
        assert result is None


# =============================================================================
# decide_finalization_tier
# =============================================================================

class TestDecideFinalizationTier:
    def test_no_finalizer(self):
        use_q, tier, reason = decide_finalization_tier(
            orchestrator_output=_make_output(),
            user_input="merhaba",
            has_finalizer=False,
        )
        assert not use_q
        assert tier == "fast"
        assert reason == "no_finalizer"

    def test_smalltalk_always_quality(self):
        use_q, tier, reason = decide_finalization_tier(
            orchestrator_output=_make_output(route="smalltalk"),
            user_input="nasılsın?",
            has_finalizer=True,
        )
        assert use_q is True
        assert tier == "quality"
        assert "smalltalk" in reason

    def test_tiering_disabled_defaults_to_quality(self):
        """When tiering is disabled, defaults to quality."""

        class FakeTierDecision:
            use_quality = True
            reason = "tiering_disabled"
            complexity = 0
            writing = 0
            risk = 0

        with patch(
            "bantz.llm.tiered.decide_tier",
            return_value=FakeTierDecision(),
        ):
            use_q, tier, reason = decide_finalization_tier(
                orchestrator_output=_make_output(),
                user_input="takvim etkinlikleri",
                has_finalizer=True,
            )
        assert use_q is True
        assert tier == "quality"

    def test_tiering_returns_fast(self):
        """When tiering decides fast tier."""

        class FakeTierDecision:
            use_quality = False
            reason = "simple_tool_query"
            complexity = 1
            writing = 0
            risk = 0

        with patch(
            "bantz.llm.tiered.decide_tier",
            return_value=FakeTierDecision(),
        ):
            use_q, tier, reason = decide_finalization_tier(
                orchestrator_output=_make_output(),
                user_input="saat kaç?",
                has_finalizer=True,
            )
        assert not use_q
        assert tier == "fast"

    def test_tiering_error_defaults_quality(self):
        """If tiered module fails, defaults to quality."""
        with patch(
            "bantz.llm.tiered.decide_tier",
            side_effect=RuntimeError("oops"),
        ):
            use_q, tier, reason = decide_finalization_tier(
                orchestrator_output=_make_output(),
                user_input="takvim",
                has_finalizer=True,
            )
        assert use_q is True
        assert tier == "quality"
        assert "error" in reason


# =============================================================================
# FinalizationPipeline
# =============================================================================

class TestFinalizationPipeline:
    def test_ask_user_early_exit(self):
        """ask_user → question becomes assistant_reply."""
        pipeline = FinalizationPipeline()
        output = _make_output(ask_user=True, question="Hangi saat?", assistant_reply="")
        ctx = _make_ctx(orchestrator_output=output)
        result = pipeline.run(ctx)
        assert result.assistant_reply == "Hangi saat?"

    def test_hard_failure_early_exit(self):
        """Hard failure → deterministic error message."""
        pipeline = FinalizationPipeline()
        ctx = _make_ctx(
            tool_results=[{"tool": "calendar.create", "success": False, "error": "Auth error"}],
        )
        result = pipeline.run(ctx)
        assert "başarısız" in result.assistant_reply
        assert "Auth error" in result.assistant_reply

    def test_pending_confirmation_not_hard_failure(self):
        """Pending confirmation is NOT a hard failure."""
        pipeline = FinalizationPipeline()
        ctx = _make_ctx(
            tool_results=[
                {"tool": "calendar.create", "success": False, "pending_confirmation": True}
            ],
        )
        # This should NOT hit hard-failure path, should reach default fallback
        result = pipeline.run(ctx)
        # Since we have no quality/fast, falls through to default
        assert result is not None

    def test_quality_path_success(self, mock_llm):
        guard = Mock()
        guard.check_and_retry = Mock(return_value="Efendim, 2 toplantınız var.")
        quality = QualityFinalizer(finalizer_llm=mock_llm, guard=guard)
        pipeline = FinalizationPipeline(quality=quality)
        ctx = _make_ctx(use_quality=True)
        result = pipeline.run(ctx)
        assert "toplantı" in result.assistant_reply

    def test_quality_path_failure_fallback_to_fast(self, mock_llm, mock_planner_llm):
        """Quality fails → falls back to fast."""
        bad_llm = Mock()
        bad_llm.complete_text = Mock(return_value="")
        quality = QualityFinalizer(finalizer_llm=bad_llm, guard=None)
        fast = FastFinalizer(planner_llm=mock_planner_llm)
        pipeline = FinalizationPipeline(quality=quality, fast=fast)
        ctx = _make_ctx(use_quality=True)
        result = pipeline.run(ctx)
        assert result.assistant_reply is not None
        assert len(result.assistant_reply) > 0

    def test_fast_path_only(self, mock_planner_llm):
        """Tier decided fast → only fast finalizer used."""
        fast = FastFinalizer(planner_llm=mock_planner_llm)
        pipeline = FinalizationPipeline(fast=fast)
        ctx = _make_ctx(
            use_quality=False,
            tier_name="fast",
            tier_reason="simple_query",
            tool_results=[{"tool": "calendar.list", "success": True, "result": "ok"}],
            orchestrator_output=_make_output(ask_user=False),
        )
        result = pipeline.run(ctx)
        assert "toplantı" in result.assistant_reply

    def test_default_fallback_no_tools(self):
        """No tools, no finalizer → return original output."""
        pipeline = FinalizationPipeline()
        output = _make_output(assistant_reply="Orijinal cevap")
        ctx = _make_ctx(orchestrator_output=output, tool_results=[], use_quality=False)
        result = pipeline.run(ctx)
        assert result.assistant_reply == "Orijinal cevap"

    def test_default_fallback_failed_tools(self):
        """Default fallback with failed tools."""
        pipeline = FinalizationPipeline()
        ctx = _make_ctx(
            tool_results=[{"tool": "x", "success": False, "error": "boom"}],
            use_quality=False,
        )
        result = pipeline.run(ctx)
        assert "başarısız" in result.assistant_reply

    def test_default_fallback_success_with_summary(self):
        """Default fallback with successful tools → tool success summary."""
        pipeline = FinalizationPipeline()
        ctx = _make_ctx(
            orchestrator_output=_make_output(assistant_reply=""),
            tool_results=[{"tool": "calendar.list_events", "success": True, "result": "ok"}],
            use_quality=False,
        )
        result = pipeline.run(ctx)
        assert result.assistant_reply != ""

    def test_event_bus_publish(self, mock_llm):
        """Event bus receives finalizer.start event."""
        bus = Mock()
        pipeline = FinalizationPipeline(event_bus=bus)
        ctx = _make_ctx(use_quality=False, tool_results=[])
        pipeline.run(ctx)
        bus.publish.assert_called_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "finalizer.start"

    def test_quality_exception_fallback_to_fast(self, mock_planner_llm):
        """Quality raises LLMClientError → falls back to fast."""
        bad_llm = Mock()
        bad_llm.complete_text = Mock(side_effect=RuntimeError("reason=rate_limit"))
        quality = QualityFinalizer(finalizer_llm=bad_llm, guard=None)
        fast = FastFinalizer(planner_llm=mock_planner_llm)
        pipeline = FinalizationPipeline(quality=quality, fast=fast)
        ctx = _make_ctx(use_quality=True)
        result = pipeline.run(ctx)
        # Should still get a reply from fast path
        assert result.assistant_reply is not None


# =============================================================================
# build_finalization_context factory
# =============================================================================

class TestBuildFinalizationContext:
    def test_builds_context_with_memory(self):
        memory = Mock()
        memory.to_prompt_block = Mock(return_value="Summary text")

        output = _make_output()
        state = _make_state()
        state.get_context_for_llm = Mock(return_value={"recent_conversation": [{"user": "hi"}]})

        finalizer_llm = Mock()
        finalizer_llm.complete_text = Mock()

        with patch(
            "bantz.brain.finalization_pipeline.decide_finalization_tier",
            return_value=(True, "quality", "default"),
        ):
            ctx = build_finalization_context(
                user_input="merhaba",
                orchestrator_output=output,
                tool_results=[],
                state=state,
                memory=memory,
                finalizer_llm=finalizer_llm,
            )

        assert ctx.user_input == "merhaba"
        assert ctx.dialog_summary == "Summary text"
        assert ctx.recent_turns == [{"user": "hi"}]
        assert ctx.use_quality is True
        assert ctx.planner_decision["route"] == "calendar"

    def test_builds_context_without_memory(self):
        memory = Mock(spec=[])  # no to_prompt_block
        output = _make_output()
        state = _make_state()
        state.get_context_for_llm = Mock(return_value={})

        with patch(
            "bantz.brain.finalization_pipeline.decide_finalization_tier",
            return_value=(False, "fast", "no_finalizer"),
        ):
            ctx = build_finalization_context(
                user_input="test",
                orchestrator_output=output,
                tool_results=[],
                state=state,
                memory=memory,
                finalizer_llm=None,
            )

        assert ctx.dialog_summary is None
        assert ctx.use_quality is False


# =============================================================================
# create_pipeline factory
# =============================================================================

class TestCreatePipeline:
    def test_creates_full_pipeline(self, mock_llm, mock_planner_llm):
        pipeline = create_pipeline(
            finalizer_llm=mock_llm,
            planner_llm=mock_planner_llm,
        )
        assert pipeline._quality is not None
        assert pipeline._fast is not None

    def test_creates_fast_only_pipeline(self, mock_planner_llm):
        pipeline = create_pipeline(
            finalizer_llm=None,
            planner_llm=mock_planner_llm,
        )
        assert pipeline._quality is None
        assert pipeline._fast is not None

    def test_creates_empty_pipeline(self):
        pipeline = create_pipeline()
        assert pipeline._quality is None
        assert pipeline._fast is None


# =============================================================================
# Integration: Pipeline end-to-end
# =============================================================================

class TestPipelineIntegration:
    """End-to-end tests simulating OrchestratorLoop delegation."""

    def test_full_quality_flow(self, mock_llm, mock_planner_llm):
        """Full quality finalization path."""
        pipeline = create_pipeline(
            finalizer_llm=mock_llm,
            planner_llm=mock_planner_llm,
        )
        output = _make_output(route="calendar", assistant_reply="")
        state = _make_state()

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(return_value=(False, set()))

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            ctx = _make_ctx(
                orchestrator_output=output,
                state=state,
                use_quality=True,
                tier_name="quality",
            )
            result = pipeline.run(ctx)

        assert "toplantı" in result.assistant_reply
        assert state.trace.get("finalizer_used") is True

    def test_full_fast_flow(self, mock_planner_llm):
        """Full fast finalization path (no quality LLM)."""
        pipeline = create_pipeline(
            finalizer_llm=None,
            planner_llm=mock_planner_llm,
        )
        output = _make_output(route="calendar", assistant_reply="")
        ctx = _make_ctx(
            orchestrator_output=output,
            use_quality=False,
            tier_name="fast",
            tool_results=[{"tool": "cal", "success": True, "result": "ok"}],
        )
        result = pipeline.run(ctx)
        assert "toplantı" in result.assistant_reply

    def test_guard_violation_fallback_to_fast(self, mock_planner_llm):
        """Quality guard rejects → falls back to fast finalizer."""
        bad_llm = Mock()
        bad_llm.complete_text = Mock(return_value="Uydurma 999 rakam.")

        pipeline = create_pipeline(
            finalizer_llm=bad_llm,
            planner_llm=mock_planner_llm,
        )

        fake_mod = Mock()
        fake_mod.find_new_numeric_facts = Mock(return_value=(True, {"999"}))

        with patch.dict("sys.modules", {"bantz.llm.no_new_facts": fake_mod}):
            ctx = _make_ctx(use_quality=True)
            result = pipeline.run(ctx)

        # Should have fallen back — either fast output or default
        assert result.assistant_reply is not None
