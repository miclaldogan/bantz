from __future__ import annotations

from unittest.mock import Mock

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop
from bantz.brain.orchestrator_state import OrchestratorState


def _make_output() -> OrchestratorOutput:
    return OrchestratorOutput(
        route="smalltalk",
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=[],
        assistant_reply="",
        raw_output={},
    )


def test_memory_injection_publishes_trace_and_redacts_pii(monkeypatch):
    event_bus = Mock()
    orchestrator = Mock()
    orchestrator.route = Mock(return_value=_make_output())

    cfg = OrchestratorConfig(
        enable_preroute=False,
        debug=False,
        memory_max_tokens=200,
        memory_pii_filter=True,
    )

    loop = OrchestratorLoop(
        orchestrator=orchestrator,
        tools=Mock(),
        event_bus=event_bus,
        config=cfg,
        finalizer_llm=Mock(),
    )

    monkeypatch.setattr(
        loop.memory,
        "to_prompt_block",
        lambda: "Beni 05321234567 numarasından ara, mailim a@b.com",
    )

    state = OrchestratorState()
    state.add_conversation_turn("mailim a@b.com", "tamam")

    loop._llm_planning_phase("selam", state)

    # dialog_summary passed to orchestrator should be PII-redacted
    passed_summary = orchestrator.route.call_args.kwargs.get("dialog_summary")
    assert passed_summary is not None
    assert "[TELEFON]" in passed_summary
    assert "[EMAIL]" in passed_summary
    assert "05321234567" not in passed_summary
    assert "a@b.com" not in passed_summary

    # Memory trace record stored on state
    assert "memory_trace" in state.trace
    assert state.trace["memory_trace"]

    # Memory injected event should be published with redacted preview
    injected_calls = [
        c for c in event_bus.publish.call_args_list if c.args and c.args[0] == "memory.injected"
    ]
    assert injected_calls, "expected memory.injected event"
    payload = injected_calls[-1].args[1]
    assert payload["memory_injected"] is True
    assert "[TELEFON]" in payload["memory_preview"]
    assert "[EMAIL]" in payload["memory_preview"]


def test_memory_injection_trims_when_over_budget(monkeypatch):
    event_bus = Mock()
    orchestrator = Mock()
    orchestrator.route = Mock(return_value=_make_output())

    cfg = OrchestratorConfig(
        enable_preroute=False,
        debug=False,
        memory_max_tokens=5,
        memory_pii_filter=False,
    )

    loop = OrchestratorLoop(
        orchestrator=orchestrator,
        tools=Mock(),
        event_bus=event_bus,
        config=cfg,
        finalizer_llm=Mock(),
    )

    monkeypatch.setattr(loop.memory, "to_prompt_block", lambda: "X" * 500)

    state = OrchestratorState()
    loop._llm_planning_phase("selam", state)

    injected_calls = [
        c for c in event_bus.publish.call_args_list if c.args and c.args[0] == "memory.injected"
    ]
    assert injected_calls, "expected memory.injected event"
    payload = injected_calls[-1].args[1]
    assert payload["was_trimmed"] is True
    assert payload["trim_reason"] == "token_budget"
    assert payload["memory_tokens"] <= 5
