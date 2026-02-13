"""Regression tests for Issue #597: cache FinalizationPipeline in OrchestratorLoop.

We want to avoid rebuilding the pipeline object every turn, since it can create
multiple helper objects and allocations.

Behavior:
- Repeated calls should reuse the same pipeline (create_pipeline called once)
- Changing the planner_llm identity should invalidate the cache
"""

from __future__ import annotations

from unittest.mock import Mock

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop
from bantz.brain.orchestrator_state import OrchestratorState


class _FakePipeline:
    def __init__(self, *, output: OrchestratorOutput) -> None:
        self.output = output
        self.run_calls = 0

    def run(self, _ctx):
        self.run_calls += 1
        return self.output


def _make_output(*, assistant_reply: str = "ok") -> OrchestratorOutput:
    return OrchestratorOutput(
        route="smalltalk",
        calendar_intent="none",
        slots={},
        confidence=1.0,
        tool_plan=[],
        assistant_reply=assistant_reply,
        raw_output={},
    )


def test_finalization_pipeline_cached_across_calls(monkeypatch):
    orchestrator = Mock()
    planner_llm = Mock()
    planner_llm.complete_text = Mock()
    orchestrator._llm = planner_llm

    loop = OrchestratorLoop(
        orchestrator=orchestrator,
        tools=Mock(),
        finalizer_llm=Mock(),
    )

    created: list[_FakePipeline] = []

    import bantz.brain.finalization_pipeline as fp

    def _create_pipeline(*, finalizer_llm=None, planner_llm=None, event_bus=None):
        pipe = _FakePipeline(output=_make_output(assistant_reply="cached"))
        created.append(pipe)
        return pipe

    monkeypatch.setattr(fp, "create_pipeline", _create_pipeline)
    monkeypatch.setattr(fp, "build_finalization_context", lambda **_kwargs: object())

    state = OrchestratorState()
    out1 = loop._llm_finalization_phase("hi", _make_output(), [], state)
    out2 = loop._llm_finalization_phase("hi", _make_output(), [], state)

    assert out1.assistant_reply == "cached"
    assert out2.assistant_reply == "cached"
    assert len(created) == 1
    assert created[0].run_calls == 2


def test_finalization_pipeline_cache_invalidates_on_planner_change(monkeypatch):
    orchestrator = Mock()
    planner_llm_1 = Mock()
    planner_llm_1.complete_text = Mock()
    orchestrator._llm = planner_llm_1

    loop = OrchestratorLoop(
        orchestrator=orchestrator,
        tools=Mock(),
        finalizer_llm=Mock(),
    )

    created: list[_FakePipeline] = []

    import bantz.brain.finalization_pipeline as fp

    def _create_pipeline(*, finalizer_llm=None, planner_llm=None, event_bus=None):
        pipe = _FakePipeline(output=_make_output(assistant_reply=str(id(planner_llm))))
        created.append(pipe)
        return pipe

    monkeypatch.setattr(fp, "create_pipeline", _create_pipeline)
    monkeypatch.setattr(fp, "build_finalization_context", lambda **_kwargs: object())

    state = OrchestratorState()
    out1 = loop._llm_finalization_phase("hi", _make_output(), [], state)

    planner_llm_2 = Mock()
    planner_llm_2.complete_text = Mock()
    orchestrator._llm = planner_llm_2

    out2 = loop._llm_finalization_phase("hi", _make_output(), [], state)

    assert len(created) == 2
    assert out1.assistant_reply != out2.assistant_reply
