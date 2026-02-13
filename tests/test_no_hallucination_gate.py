# SPDX-License-Identifier: MIT
"""Issue #1228: No-Hallucination Gate tests.

Ensures that when tool-dependent routes (calendar/gmail) have NO successful
tool results, the finalizer is bypassed and a deterministic Turkish error
message is returned instead of hallucinated data.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest

from bantz.brain.finalization_pipeline import (
    FinalizationContext,
    FinalizationPipeline,
    _no_tool_success,
    _no_tool_success_message,
)
from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_output(**kw: Any) -> OrchestratorOutput:
    defaults = {
        "route": "calendar",
        "calendar_intent": "query",
        "gmail_intent": None,
        "gmail": None,
        "slots": {},
        "confidence": 0.9,
        "tool_plan": [],
        "requires_confirmation": False,
        "confirmation_prompt": None,
        "ask_user": False,
        "question": None,
        "assistant_reply": None,
    }
    defaults.update(kw)
    return OrchestratorOutput(**defaults)


def _make_ctx(
    route: str = "calendar",
    tool_results: list[dict[str, Any]] | None = None,
    **kw: Any,
) -> FinalizationContext:
    output = _make_output(route=route)
    state = OrchestratorState()
    return FinalizationContext(
        user_input="bugün neler var?",
        orchestrator_output=output,
        tool_results=tool_results or [],
        state=state,
        planner_decision={"route": route},
        **kw,
    )


def _make_pipeline() -> FinalizationPipeline:
    return FinalizationPipeline(quality=None, fast=None)


# ── Unit tests for _no_tool_success ──────────────────────────────────────────

class TestNoToolSuccess:
    def test_empty_list(self) -> None:
        assert _no_tool_success([]) is True

    def test_none(self) -> None:
        assert _no_tool_success(None) is True  # type: ignore[arg-type]

    def test_all_failed(self) -> None:
        results = [
            {"tool": "calendar.list_events", "success": False, "error": "API error"},
        ]
        assert _no_tool_success(results) is True

    def test_one_success(self) -> None:
        results = [
            {"tool": "calendar.list_events", "success": True, "raw_result": {"ok": True}},
        ]
        assert _no_tool_success(results) is False

    def test_mixed(self) -> None:
        results = [
            {"tool": "calendar.list_events", "success": True, "raw_result": {"ok": True}},
            {"tool": "calendar.create_event", "success": False, "error": "timeout"},
        ]
        assert _no_tool_success(results) is False


# ── Unit tests for _no_tool_success_message ──────────────────────────────────

class TestNoToolSuccessMessage:
    def test_calendar_message(self) -> None:
        msg = _no_tool_success_message("calendar")
        assert "erişemedim" in msg.lower()
        assert "tekrar" in msg.lower()

    def test_gmail_message(self) -> None:
        msg = _no_tool_success_message("gmail")
        assert "erişemedim" in msg.lower()
        assert "tekrar" in msg.lower()

    def test_unknown_route_fallback(self) -> None:
        msg = _no_tool_success_message("system")
        assert "gerçekleştiremedim" in msg.lower()


# ── Integration: Pipeline.run() gate fires correctly ─────────────────────────

class TestNoHallucinationGate:
    """Pipeline.run() must return deterministic error when tools_ok == 0."""

    def test_calendar_no_tools_returns_error(self) -> None:
        """Calendar route with empty tool_results → 'erişemedim'."""
        ctx = _make_ctx(route="calendar", tool_results=[])
        pipeline = _make_pipeline()
        result = pipeline.run(ctx)
        assert "erişemedim" in result.assistant_reply.lower()
        assert result.finalizer_model == "none(no_hallucination_gate)"

    def test_gmail_all_failed_returns_error(self) -> None:
        """Gmail route with all tools failed → deterministic error (either hard_failures or gate)."""
        ctx = _make_ctx(
            route="gmail",
            tool_results=[
                {"tool": "gmail.list_messages", "success": False, "error": "401 auth"},
            ],
        )
        pipeline = _make_pipeline()
        result = pipeline.run(ctx)
        # Either the hard_failures guard or the no-hallucination gate fires
        assert result.finalizer_model in ("none(error)", "none(no_hallucination_gate)")
        # No hallucinated content — reply is an error message
        assert "başarısız" in result.assistant_reply.lower() or "erişemedim" in result.assistant_reply.lower()

    def test_calendar_with_success_passes_through(self) -> None:
        """Calendar route with a successful tool → does NOT fire gate."""
        ctx = _make_ctx(
            route="calendar",
            tool_results=[
                {
                    "tool": "calendar.list_events",
                    "success": True,
                    "raw_result": {"ok": True, "events": [{"id": "e1", "summary": "Test", "start": {"dateTime": "2025-01-15T09:00:00"}, "end": {"dateTime": "2025-01-15T10:00:00"}}]},
                },
            ],
        )
        pipeline = _make_pipeline()
        result = pipeline.run(ctx)
        # Should have taken the deterministic calendar path, not the gate
        assert result.finalizer_model != "none(no_hallucination_gate)"

    def test_pending_confirmation_skips_gate(self) -> None:
        """Pending confirmation results must NOT trigger the gate."""
        ctx = _make_ctx(
            route="calendar",
            tool_results=[
                {
                    "tool": "calendar.delete_event",
                    "success": False,
                    "pending_confirmation": True,
                    "raw_result": {"pending_confirmation": True, "confirmation_prompt": "Delete event?"},
                },
            ],
        )
        pipeline = _make_pipeline()
        result = pipeline.run(ctx)
        assert result.finalizer_model != "none(no_hallucination_gate)"

    def test_smalltalk_route_skips_gate(self) -> None:
        """Non-tool-dependent routes (smalltalk) should never fire the gate."""
        ctx = _make_ctx(route="smalltalk", tool_results=[])
        pipeline = _make_pipeline()
        result = pipeline.run(ctx)
        assert result.finalizer_model != "none(no_hallucination_gate)"

    def test_no_factual_claim_in_gate_response(self) -> None:
        """Gate response must NOT contain any numeric time or event title."""
        import re
        ctx = _make_ctx(route="calendar", tool_results=[])
        pipeline = _make_pipeline()
        result = pipeline.run(ctx)
        reply = result.assistant_reply
        # No HH:MM time pattern
        assert not re.search(r"\d{1,2}:\d{2}", reply), f"Found time in gate reply: {reply}"
        # No "etkinlik" or event title
        assert "etkinlik var" not in reply.lower()

    def test_trace_updated(self) -> None:
        """State trace should record the gate firing."""
        ctx = _make_ctx(route="gmail", tool_results=[])
        pipeline = _make_pipeline()
        pipeline.run(ctx)
        trace = ctx.state.trace
        assert trace.get("finalizer_guard") == "no_hallucination"
        assert trace.get("finalizer_guard_triggered") is True


# ── Defense-in-depth: prompt includes anti-hallucination instruction ─────────

class TestPromptDefenseInDepth:
    """Finalizer prompts must contain explicit anti-hallucination rules."""

    def test_quality_fallback_prompt_has_rule(self) -> None:
        from bantz.brain.finalization_pipeline import QualityFinalizer
        ctx = _make_ctx(route="calendar", tool_results=[])
        prompt = QualityFinalizer._build_fallback_prompt(ctx, [])
        assert "TOOL_RESULTS boşsa" in prompt

    def test_fast_prompt_has_rule(self) -> None:
        from bantz.brain.finalization_pipeline import FastFinalizer
        mock_llm = MagicMock()
        fast = FastFinalizer(planner_llm=mock_llm)
        ctx = _make_ctx(route="calendar", tool_results=[])
        prompt = fast._build_prompt(ctx)
        assert "TOOL_RESULTS boşsa" in prompt
