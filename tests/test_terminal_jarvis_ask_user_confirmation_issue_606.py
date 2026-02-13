from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState


class _EventBusStub:
    def subscribe_all(self, _handler: Any) -> None:
        return


class _LoopStub:
    def __init__(self) -> None:
        self.process_turn_calls: list[str] = []
        self.run_full_cycle_calls: list[dict[str, Any]] = []

    def process_turn(self, text: str, state: OrchestratorState):
        self.process_turn_calls.append(text)

        # Turn 1: user asks to send email, but missing recipient
        if len(self.process_turn_calls) == 1:
            out = OrchestratorOutput(
                route="gmail",
                calendar_intent="none",
                gmail_intent="send",
                slots={},
                gmail={"subject": "Merhaba", "body": "Selam"},
                confidence=0.5,
                tool_plan=[],
                assistant_reply="",
                ask_user=True,
                question="Kime göndermek istiyorsunuz efendim?",
            )
            return out, state

        # Turn 2: combined text should include original + answer
        if len(self.process_turn_calls) == 2:
            assert "—" in text  # combined
            state.set_pending_confirmation(
                {
                    "tool": "gmail.send",
                    "prompt": "Göndereyim mi efendim?",
                }
            )
            out = OrchestratorOutput(
                route="gmail",
                calendar_intent="send",
                gmail_intent="send",
                slots={},
                gmail={"to": "test@example.com"},
                confidence=0.9,
                tool_plan=["gmail.send"],
                assistant_reply="",
                requires_confirmation=True,
                confirmation_prompt="Göndereyim mi efendim?",
            )
            return out, state

        raise AssertionError("unexpected process_turn call")

    def run_full_cycle(self, text: str, confirmation_token: str, state: OrchestratorState):
        self.run_full_cycle_calls.append(
            {"text": text, "confirmation_token": confirmation_token}
        )
        assert confirmation_token == "evet"
        # Ensure we re-run the combined initiating input, not just the last user answer.
        assert "—" in text
        state.clear_pending_confirmation()
        return {
            "final_output": {
                "assistant_reply": "Gönderdim efendim.",
                "route": "gmail",
                "calendar_intent": "send",
                "confidence": 1.0,
                "tool_plan": ["gmail.send"],
                "requires_confirmation": False,
                "confirmation_prompt": "",
                "reasoning_summary": [],
            }
        }


def _runtime_stub(loop: _LoopStub):
    return SimpleNamespace(
        router_model="stub",
        gemini_model="stub",
        finalizer_is_gemini=False,
        router_client=None,
        gemini_client=None,
        tools=SimpleNamespace(names=lambda: []),
        event_bus=_EventBusStub(),
        loop=loop,
    )


def test_terminal_jarvis_ask_user_then_confirmation_replays_combined_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    terminal_jarvis_path = repo_root / "scripts" / "terminal_jarvis.py"
    spec = importlib.util.spec_from_file_location("bantz_scripts_terminal_jarvis", terminal_jarvis_path)
    assert spec and spec.loader
    terminal_jarvis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(terminal_jarvis)

    loop = _LoopStub()

    # Patch runtime factory to avoid real network/LLM.
    monkeypatch.setattr(
        "bantz.brain.runtime_factory.create_runtime",
        lambda **kwargs: _runtime_stub(loop),
    )

    assistant = terminal_jarvis.TerminalJarvis()
    assistant._router_ready.set()  # bypass warmup logic

    # Turn 1: should ask clarification
    r1 = assistant.process("Ali'ye mail at selam de")
    assert r1 and "Kime" in r1

    # Turn 2: answer should be combined with original request
    r2 = assistant.process("test@example.com")
    assert r2 and "Göndereyim" in r2

    # Turn 3: confirmation should re-run combined input
    r3 = assistant.process("evet")
    assert r3 == "Gönderdim efendim."

    assert len(loop.process_turn_calls) == 2
    assert len(loop.run_full_cycle_calls) == 1
