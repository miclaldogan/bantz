"""Tests for Issue #517: Gemini Finalizer Wiring Invariant.

Ensures:
1. OrchestratorOutput has finalizer_model field
2. FinalizationPipeline stamps finalizer_model on every output
3. OrchestratorLoop warns when finalizer_llm is None
4. Quality finalizer path stamps the correct model name
"""

from __future__ import annotations

import warnings
from dataclasses import replace
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.llm_router import OrchestratorOutput


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_output(**overrides) -> OrchestratorOutput:
    """Create a minimal OrchestratorOutput for testing."""
    defaults = dict(
        route="calendar",
        calendar_intent="query",
        slots={"window_hint": "today"},
        confidence=0.9,
        tool_plan=["calendar.list_events"],
        assistant_reply="",
    )
    defaults.update(overrides)
    return OrchestratorOutput(**defaults)


class _FakeLLM:
    """Minimal LLM mock with model_name and complete_text."""

    def __init__(self, model_name: str = "gemini-2.0-flash", reply: str = "Test reply"):
        self.model_name = model_name
        self._reply = reply

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 256) -> str:
        return self._reply


# ---------------------------------------------------------------------------
# Test: OrchestratorOutput has finalizer_model field
# ---------------------------------------------------------------------------

class TestOrchestratorOutputFinalizerModel:

    def test_default_finalizer_model_empty(self):
        """finalizer_model should default to empty string."""
        output = _make_output()
        assert output.finalizer_model == ""

    def test_finalizer_model_can_be_set(self):
        """finalizer_model should be settable via replace."""
        output = _make_output()
        updated = replace(output, finalizer_model="gemini-2.0-flash")
        assert updated.finalizer_model == "gemini-2.0-flash"

    def test_finalizer_model_in_dataclass_fields(self):
        """finalizer_model should be a proper dataclass field."""
        from dataclasses import fields
        field_names = {f.name for f in fields(OrchestratorOutput)}
        assert "finalizer_model" in field_names


# ---------------------------------------------------------------------------
# Test: FinalizationPipeline stamps finalizer_model
# ---------------------------------------------------------------------------

class TestPipelineFinalizerModel:

    def test_ask_user_stamps_model(self):
        """ask_user early exit should stamp finalizer_model."""
        from bantz.brain.finalization_pipeline import FinalizationPipeline, FinalizationContext
        from bantz.brain.orchestrator_state import OrchestratorState

        output = _make_output(ask_user=True, question="Saat kaçta?", assistant_reply="")
        ctx = FinalizationContext(
            user_input="toplantı ekle",
            orchestrator_output=output,
            tool_results=[],
            state=OrchestratorState(),
            planner_decision={},
        )

        pipeline = FinalizationPipeline()
        result = pipeline.run(ctx)
        assert result.finalizer_model == "none(ask_user)"
        assert result.assistant_reply == "Saat kaçta?"

    def test_quality_path_stamps_gemini_model(self):
        """Quality finalizer path should stamp the model name."""
        from bantz.brain.finalization_pipeline import (
            FinalizationPipeline,
            FinalizationContext,
            QualityFinalizer,
            NoNewFactsGuard,
        )
        from bantz.brain.orchestrator_state import OrchestratorState

        gemini = _FakeLLM(model_name="gemini-2.0-flash", reply="İşte takvim sonuçları efendim")
        guard = NoNewFactsGuard(finalizer_llm=gemini)
        quality = QualityFinalizer(finalizer_llm=gemini, guard=guard)

        output = _make_output()
        ctx = FinalizationContext(
            user_input="bugün planım ne",
            orchestrator_output=output,
            tool_results=[{"tool": "calendar.list_events", "success": True, "result": "Toplantı"}],
            state=OrchestratorState(),
            planner_decision={},
            use_quality=True,
        )

        pipeline = FinalizationPipeline(quality=quality)
        result = pipeline.run(ctx)
        assert result.finalizer_model == "gemini-2.0-flash"

    def test_no_tools_stamps_model(self):
        """No tool results should stamp finalizer_model."""
        from bantz.brain.finalization_pipeline import FinalizationPipeline, FinalizationContext
        from bantz.brain.orchestrator_state import OrchestratorState

        output = _make_output(tool_plan=[], assistant_reply="İyiyim efendim")
        ctx = FinalizationContext(
            user_input="nasılsın",
            orchestrator_output=output,
            tool_results=[],
            state=OrchestratorState(),
            planner_decision={},
        )

        pipeline = FinalizationPipeline()
        result = pipeline.run(ctx)
        # Issue #628: tool-first guard now fires for calendar/gmail routes
        # with empty tool_results, providing better anti-hallucination tracing.
        assert result.finalizer_model == "none(tool_first_guard/no_tools_run)"


# ---------------------------------------------------------------------------
# Test: OrchestratorLoop warns when finalizer_llm is None
# ---------------------------------------------------------------------------

class TestOrchestratorLoopFinalizerWarning:

    def test_warns_when_no_finalizer(self):
        """OrchestratorLoop should warn when created without finalizer_llm."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop

        mock_orchestrator = MagicMock()
        mock_tools = MagicMock()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loop = OrchestratorLoop(
                orchestrator=mock_orchestrator,
                tools=mock_tools,
                finalizer_llm=None,
            )
            # Should have at least the finalizer warning (and deprecation warning)
            finalizer_warnings = [
                x for x in w if "finalizer_llm" in str(x.message)
            ]
            assert len(finalizer_warnings) >= 1

    def test_no_warning_with_finalizer(self):
        """OrchestratorLoop should NOT warn when finalizer_llm is provided."""
        from bantz.brain.orchestrator_loop import OrchestratorLoop

        mock_orchestrator = MagicMock()
        mock_tools = MagicMock()
        mock_finalizer = _FakeLLM()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            loop = OrchestratorLoop(
                orchestrator=mock_orchestrator,
                tools=mock_tools,
                finalizer_llm=mock_finalizer,
            )
            finalizer_warnings = [
                x for x in w if "finalizer_llm" in str(x.message)
            ]
            assert len(finalizer_warnings) == 0
