# SPDX-License-Identifier: MIT
"""Issue #658: Quality degradation telemetry + status visibility."""

from bantz.brain.finalization_pipeline import FinalizationContext, FinalizationPipeline
from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.core.events import EventBus
from bantz.llm import create_quality_client
from bantz.tools.system_tools import system_status


class _DummyQuality:
    def finalize(self, ctx):
        return None


class _DummyFast:
    def finalize(self, ctx):
        return "Hızlı fallback yanıtı."


def _ctx() -> FinalizationContext:
    output = OrchestratorOutput(
        route="smalltalk",
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=[],
        assistant_reply="",
    )
    return FinalizationContext(
        user_input="merhaba",
        orchestrator_output=output,
        tool_results=[],
        state=OrchestratorState(),
        planner_decision={},
        tier_name="quality",
        tier_reason="test",
        use_quality=True,
    )


def test_quality_fallback_publishes_event_and_trace():
    bus = EventBus(history_size=10)
    pipeline = FinalizationPipeline(quality=_DummyQuality(), fast=_DummyFast(), event_bus=bus)

    ctx = _ctx()
    result = pipeline.run(ctx)

    assert result.assistant_reply == "Hızlı fallback yanıtı."
    assert ctx.state.trace.get("finalizer_strategy") == "fast_fallback"

    events = bus.get_history("quality.degraded", limit=5)
    assert events, "quality.degraded event not published"
    assert events[-1].data.get("reason") == "quality_failed_fallback"


def test_create_quality_client_missing_key_publishes_event(monkeypatch):
    bus = EventBus(history_size=10)

    monkeypatch.setenv("QUALITY_PROVIDER", "gemini")
    monkeypatch.setenv("BANTZ_CLOUD_MODE", "cloud")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("BANTZ_GEMINI_API_KEY", raising=False)

    client = create_quality_client(event_bus=bus)
    assert client.backend_name == "vllm"

    events = bus.get_history("quality.degraded", limit=5)
    assert events, "quality.degraded event not published"
    assert events[-1].data.get("reason") == "missing_api_key"


def test_system_status_includes_quality_info():
    status = system_status()
    assert "gemini" in status
    assert "quality_degradation" in status
