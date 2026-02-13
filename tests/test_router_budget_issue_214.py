from __future__ import annotations

import json
from typing import Any

import pytest

from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.llm.vllm_openai_client import VLLMOpenAIClient


def _estimate_tokens(text: str) -> int:
    return max(0, len(str(text or "")) // 4)


class TinyContextLLM:
    """Fake LLM that enforces a very small context window.

    Used to ensure router prompt trimming + dynamic max_tokens never exceed
    the model context length (Issue #214).
    """

    backend_name = "mock"
    model_name = "tiny"
    model_context_length = 256

    def __init__(self) -> None:
        self.last_prompt: str = ""
        self.last_max_tokens: int = 0

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:  # noqa: ARG002
        self.last_prompt = str(prompt)
        self.last_max_tokens = int(max_tokens)

        safety_margin = 32
        prompt_tokens = _estimate_tokens(self.last_prompt)
        assert prompt_tokens + self.last_max_tokens + safety_margin <= int(self.model_context_length)

        return json.dumps(
            {
                "route": "calendar",
                "calendar_intent": "query",
                "slots": {"window_hint": "today"},
                "confidence": 0.95,
                "tool_plan": ["calendar.list_events"],
                "assistant_reply": "",
                "ask_user": False,
                "question": "",
                "requires_confirmation": False,
                "confirmation_prompt": "",
                "memory_update": "Kullanıcı takvimi sordu.",
                "reasoning_summary": ["Takvim sorgusu"],
            },
            ensure_ascii=False,
        )


def test_router_prompt_never_exceeds_budget_tiny_context():
    llm = TinyContextLLM()
    router = JarvisLLMOrchestrator(llm=llm)

    huge = "X" * 50_000
    out = router.route(
        user_input="bugün neler yapacağız bakalım",
        dialog_summary=huge,
        retrieved_memory=huge,
        session_context={"now": "2026-02-04T12:00:00+03:00", "blob": huge},
    )

    assert out.route == "calendar"
    assert llm.last_prompt
    assert llm.last_max_tokens > 0


def test_vllm_models_context_len_parsing(monkeypatch: pytest.MonkeyPatch):
    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "data": [
                    {"id": "Qwen/Qwen2.5-3B-Instruct", "max_model_len": 1024},
                ]
            }

    def fake_get(*_args: Any, **_kwargs: Any) -> _Resp:
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "get", fake_get)

    c = VLLMOpenAIClient(base_url="http://localhost:8001", model="Qwen/Qwen2.5-3B-Instruct")
    assert c.get_model_context_length() == 1024
