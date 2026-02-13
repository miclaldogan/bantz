from __future__ import annotations

from typing import Any

import pytest

from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.json_protocol import JsonParseError


class DummyEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, name: str, payload: dict[str, Any]) -> None:
        self.events.append((name, payload))


class DummyLLM:
    def __init__(self) -> None:
        self.event_bus = DummyEventBus()

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:  # noqa: ARG002
        return "{}"


def test_router_json_parse_failure_emits_event():
    llm = DummyLLM()
    orchestrator = JarvisLLMOrchestrator(llm=llm)

    # Force parse failure
    with pytest.raises(JsonParseError):
        orchestrator._parse_json("this is not json")

    events = [name for name, _payload in llm.event_bus.events]
    assert "router.json.parse_failed" in events


def test_router_json_validation_warning_emits_event():
    llm = DummyLLM()
    orchestrator = JarvisLLMOrchestrator(llm=llm)

    # Valid JSON but invalid schema (missing required fields)
    orchestrator._parse_json('{"route": "calendar"}')

    events = [name for name, _payload in llm.event_bus.events]
    assert "router.json.validation_warning" in events
