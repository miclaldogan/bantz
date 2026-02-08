"""Integration tests for Issue #594: router_validation wired into routing.

These tests verify that schema-level repair (field-by-field) is applied after
JSON parsing, without requiring an LLM re-prompt.

Key regression: tool_plan returned as a string should be repaired to a list so
routing can still execute tools.
"""

from __future__ import annotations

from bantz.brain.llm_router import JarvisLLMOrchestrator


class MockLLM:
    def __init__(self, response: str):
        self.response = response

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        return self.response


def test_router_repairs_tool_plan_string_to_list():
    mock_llm = MockLLM(
        response=(
            '{"route": "calendar", "calendar_intent": "query", '
            '"confidence": 0.9, "tool_plan": "calendar.list_events", '
            '"assistant_reply": ""}'
        )
    )

    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="toplantılarımı göster")

    assert output.tool_plan == ["calendar.list_events"]
    assert output.tool_plan_with_args == [{"name": "calendar.list_events", "args": {}}]
