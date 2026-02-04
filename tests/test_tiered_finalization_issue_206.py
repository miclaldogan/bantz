from __future__ import annotations

import json
from typing import Any

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop
from bantz.brain.orchestrator_state import OrchestratorState


class PlannerMock:
    """Mock planner LLM.

    - For router prompts (JSON), returns a deterministic orchestrator decision.
    - For fast-finalization prompts (natural language), returns a short summary.
    """

    def __init__(self) -> None:
        self.router_calls = 0
        self.fast_finalize_calls = 0

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:  # noqa: ARG002
        if "ASSISTANT (sadece JSON):" in prompt:
            self.router_calls += 1
            user_lines = [line[5:].strip() for line in prompt.split("\n") if line.startswith("USER:")]
            user_input = (user_lines[-1] if user_lines else "").lower()

            if "mail" in user_input or "email" in user_input or "e-posta" in user_input:
                return json.dumps(
                    {
                        "route": "gmail",
                        "calendar_intent": "none",
                        "slots": {},
                        "confidence": 0.95,
                        "tool_plan": [],
                        "assistant_reply": "",
                        "ask_user": False,
                        "question": "",
                        "requires_confirmation": False,
                        "confirmation_prompt": "",
                        "memory_update": "Kullanıcı email taslağı istedi.",
                        "reasoning_summary": ["Yazım işi"],
                    },
                    ensure_ascii=False,
                )

            # Default: calendar query with tool
            return json.dumps(
                {
                    "route": "calendar",
                    "calendar_intent": "query",
                    "slots": {"window_hint": "today"},
                    "confidence": 0.9,
                    "tool_plan": ["calendar.list_events"],
                    "assistant_reply": "",
                    "ask_user": False,
                    "question": "",
                    "requires_confirmation": False,
                    "confirmation_prompt": "",
                    "memory_update": "Kullanıcı bugünün programını sordu.",
                    "reasoning_summary": ["Takvim sorgusu"],
                },
                ensure_ascii=False,
            )

        # Fast finalization prompt (no JSON expected)
        self.fast_finalize_calls += 1
        return "Efendim, bugün 2 etkinliğiniz var: Team Meeting ve Code Review."


class FinalizerMock:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "mock-quality"

    @property
    def backend_name(self) -> str:
        return "mock"

    def complete_text(self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:  # noqa: ARG002
        self.calls += 1
        return "[QUALITY] Efendim, işte email taslağı..."


def _tools() -> ToolRegistry:
    reg = ToolRegistry()

    def list_events(**_kwargs: Any) -> dict[str, Any]:
        return {
            "items": [
                {"summary": "Team Meeting", "start": {"dateTime": "2026-02-04T10:00:00+03:00"}},
                {"summary": "Code Review", "start": {"dateTime": "2026-02-04T15:00:00+03:00"}},
            ],
            "count": 2,
        }

    reg.register(
        Tool(
            name="calendar.list_events",
            description="demo",
            parameters={"type": "object", "properties": {}, "required": []},
            function=list_events,
        )
    )
    return reg


@pytest.fixture(autouse=True)
def _tiered_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BANTZ_TIERED_MODE", "1")
    monkeypatch.delenv("BANTZ_LLM_TIER", raising=False)


def test_calendar_stays_fast_no_quality_escalation():
    planner = PlannerMock()
    finalizer = FinalizerMock()

    orchestrator = JarvisLLMOrchestrator(llm=planner)
    loop = OrchestratorLoop(
        orchestrator,
        _tools(),
        config=OrchestratorConfig(debug=False),
        finalizer_llm=finalizer,
    )

    state = OrchestratorState()
    output, state = loop.process_turn("bugün neler var?", state)

    assert finalizer.calls == 0
    assert state.trace.get("response_tier") == "fast"
    assert state.trace.get("finalizer_used") is False
    assert "bugün" in output.assistant_reply.lower()


def test_email_draft_uses_quality_finalizer():
    planner = PlannerMock()
    finalizer = FinalizerMock()

    orchestrator = JarvisLLMOrchestrator(llm=planner)
    loop = OrchestratorLoop(
        orchestrator,
        _tools(),
        config=OrchestratorConfig(debug=False),
        finalizer_llm=finalizer,
    )

    state = OrchestratorState()
    output, state = loop.process_turn("Ahmet'e nazik bir email taslağı yaz", state)

    assert finalizer.calls == 1
    assert state.trace.get("response_tier") == "quality"
    assert state.trace.get("finalizer_used") is True
    assert output.assistant_reply.startswith("[QUALITY]")
