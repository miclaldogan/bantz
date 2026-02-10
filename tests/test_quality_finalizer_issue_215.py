from __future__ import annotations

import json
from typing import Any

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.llm.base import LLMConnectionError
from bantz.llm.gemini_client import GeminiClient


class PlannerMock:
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

        self.fast_finalize_calls += 1
        return "Efendim, taslak hazır."


class ViolatingFinalizerMock:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "mock-gemini"

    @property
    def backend_name(self) -> str:
        return "gemini"

    def complete_text(self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:  # noqa: ARG002
        self.calls += 1
        # Introduce a new date/time not present in user_input or planner_decision.
        return "Efendim, 2030-01-01 saat 10:00 için taslağı hazırladım."


class ErrorFinalizerMock(ViolatingFinalizerMock):
    def complete_text(self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:  # noqa: ARG002
        self.calls += 1
        raise LLMConnectionError("Gemini rate_limited status=429 reason=rate_limited")


def _tools() -> ToolRegistry:
    reg = ToolRegistry()

    def list_events(**_kwargs: Any) -> dict[str, Any]:
        return {"items": [], "count": 0}

    def list_messages(**_kwargs: Any) -> dict[str, Any]:
        return {"messages": [], "count": 0}

    reg.register(
        Tool(
            name="calendar.list_events",
            description="demo",
            parameters={"type": "object", "properties": {}, "required": []},
            function=list_events,
        )
    )
    reg.register(
        Tool(
            name="gmail.list_messages",
            description="List gmail messages",
            parameters={"type": "object", "properties": {}, "required": []},
            function=list_messages,
        )
    )
    return reg


def test_quality_finalizer_no_new_facts_falls_back(monkeypatch: pytest.MonkeyPatch):
    # Keep tiering disabled so the finalizer is selected by default.
    # Issue #647: default is now True, so we must explicitly disable.
    monkeypatch.setenv("BANTZ_TIER_MODE", "0")
    monkeypatch.setenv("BANTZ_TIERED_MODE", "0")
    monkeypatch.delenv("BANTZ_LLM_TIER", raising=False)

    planner = PlannerMock()
    finalizer = ViolatingFinalizerMock()

    orchestrator = JarvisLLMOrchestrator(llm=planner)
    loop = OrchestratorLoop(
        orchestrator,
        _tools(),
        config=OrchestratorConfig(debug=False),
        finalizer_llm=finalizer,
    )

    state = OrchestratorState()
    output, state = loop.process_turn("Ahmet'e nazik bir email taslağı yaz", state)

    assert finalizer.calls >= 1
    assert output.assistant_reply == "Efendim, taslak hazır."
    assert state.trace.get("finalizer_used") is False
    assert state.trace.get("finalizer_guard") == "no_new_facts"
    assert state.trace.get("finalizer_guard_violation") is True


def test_quality_finalizer_error_has_reason_code_and_falls_back(monkeypatch: pytest.MonkeyPatch):
    # Issue #647: default is now True, so we must explicitly disable.
    monkeypatch.setenv("BANTZ_TIER_MODE", "0")
    monkeypatch.setenv("BANTZ_TIERED_MODE", "0")
    monkeypatch.delenv("BANTZ_LLM_TIER", raising=False)

    planner = PlannerMock()
    finalizer = ErrorFinalizerMock()

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
    assert output.assistant_reply == "Efendim, taslak hazır."
    assert state.trace.get("finalizer_used") is False
    assert state.trace.get("finalizer_error_code") == "rate_limited"


def test_gemini_client_emits_metrics_and_reason_codes(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    class _Resp:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "ok"}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 15,
                },
            }

    def _post(*_args, **_kwargs):
        return _Resp()

    monkeypatch.setenv("BANTZ_LLM_METRICS", "1")
    monkeypatch.setattr("requests.post", _post)

    caplog.set_level("INFO", logger="bantz.llm.metrics")

    c = GeminiClient(api_key="x", model="gemini-2.0-flash")
    out = c.complete_text(prompt="hello", temperature=0.0, max_tokens=5)
    assert out == "ok"

    logged = "\n".join([r.getMessage() for r in caplog.records])
    assert "llm_call" in logged
    assert "backend=gemini" in logged
    assert "prompt_tokens=12" in logged

    # Rate-limited reason code
    class _Resp429:
        status_code = 429
        headers = {}

        def json(self):
            return {}

    monkeypatch.setattr("requests.post", lambda *_a, **_k: _Resp429())
    monkeypatch.setattr("bantz.llm.gemini_client.time.sleep", lambda _: None)

    with pytest.raises(LLMConnectionError) as ei:
        c.complete_text(prompt="hello", temperature=0.0, max_tokens=5)

    assert "reason=rate_limited" in str(ei.value)
