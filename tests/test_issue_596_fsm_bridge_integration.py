"""Integration tests for Issue #596: FSMBridge wired into OrchestratorLoop.

We verify that OrchestratorLoop calls FSMBridge hooks during a turn:
- on_turn_start() at the beginning
- on_confirmation_needed() when pending confirmations exist
- on_finalization_done() when a response is ready (and not confirming)
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop
from bantz.brain.orchestrator_state import OrchestratorState


@dataclass
class _Rec:
    line: str

    def to_trace_line(self) -> str:
        return self.line


class FakeFSMBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def on_turn_start(self, turn_number: int):
        self.calls.append(("on_turn_start", int(turn_number)))
        return _Rec(f"start turn={turn_number}")

    def on_confirmation_needed(self):
        self.calls.append(("on_confirmation_needed", None))
        return _Rec("confirm")

    def on_finalization_done(self):
        self.calls.append(("on_finalization_done", None))
        return _Rec("finalize")


def _make_loop(*, fsm_bridge: FakeFSMBridge) -> OrchestratorLoop:
    orchestrator = Mock()
    tools = Mock()
    finalizer_llm = Mock()
    return OrchestratorLoop(
        orchestrator=orchestrator,
        tools=tools,
        finalizer_llm=finalizer_llm,
        fsm_bridge=fsm_bridge,
    )


def test_fsm_bridge_turn_start_and_finalization_done_preroute(monkeypatch):
    fsm = FakeFSMBridge()
    loop = _make_loop(fsm_bridge=fsm)

    # Make process_turn take the preroute bypass path (skip tools + finalization)
    def _planning(_user_input: str, _state: OrchestratorState) -> OrchestratorOutput:
        return OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="merhaba",
            raw_output={"preroute_complete": True},
        )

    monkeypatch.setattr(loop, "_llm_planning_phase", _planning)

    state = OrchestratorState()
    out, st = loop.process_turn("merhaba", state)

    assert out.assistant_reply == "merhaba"
    assert fsm.calls[0] == ("on_turn_start", 1)
    assert ("on_finalization_done", None) in fsm.calls
    assert st.turn_count == 1
    assert "fsm_transitions" in st.trace


def test_fsm_bridge_confirmation_needed_skips_finalization_done(monkeypatch):
    fsm = FakeFSMBridge()
    loop = _make_loop(fsm_bridge=fsm)

    def _planning(_user_input: str, _state: OrchestratorState) -> OrchestratorOutput:
        return OrchestratorOutput(
            route="calendar",
            calendar_intent="cancel",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.delete_event"],
            assistant_reply="",
            requires_confirmation=True,
            confirmation_prompt="Silmek istiyor musunuz?",
            raw_output={},
        )

    def _exec(_output: OrchestratorOutput, state: OrchestratorState):
        state.add_pending_confirmation({"tool": "calendar.delete_event"})
        return []

    def _finalize(user_input: str, orchestrator_output: OrchestratorOutput, tool_results, state: OrchestratorState):
        # Minimal final output
        return orchestrator_output

    monkeypatch.setattr(loop, "_llm_planning_phase", _planning)
    monkeypatch.setattr(loop, "_execute_tools_phase", _exec)
    monkeypatch.setattr(loop, "_verify_results_phase", lambda tr, st: tr)
    monkeypatch.setattr(loop, "_llm_finalization_phase", _finalize)

    state = OrchestratorState()
    _out, st = loop.process_turn("etkinliği sil", state)

    assert ("on_turn_start", 1) in fsm.calls
    assert ("on_confirmation_needed", None) in fsm.calls
    assert ("on_finalization_done", None) not in fsm.calls
    assert st.has_pending_confirmation() is True
