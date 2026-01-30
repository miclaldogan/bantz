from __future__ import annotations

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.json_protocol import ValidationError, extract_first_json_object
from bantz.brain.json_repair import validate_or_repair_action


class FakeRepairLLM:
    def __init__(self, outputs: list[str]):
        self._outputs = list(outputs)
        self.calls = 0

    def complete_text(self, *, prompt: str) -> str:
        self.calls += 1
        if not self._outputs:
            return "{}"
        return self._outputs.pop(0)


def test_extract_first_json_object_from_mixed_text():
    text = 'Here is some explanation.\n```json\n{"a": 1}\n```\ntrailing text'
    obj = extract_first_json_object(text)
    assert obj == {"a": 1}


def test_repair_invalid_json_trailing_comma_to_valid_action():
    tools = ToolRegistry()

    raw = """Sure!\n```json\n{\"type\": \"SAY\", \"text\": \"hi\",}\n```\n"""

    llm = FakeRepairLLM(['{"type": "SAY", "text": "hi"}'])
    action = validate_or_repair_action(llm=llm, raw_text=raw, tool_registry=tools)

    assert action["type"] == "SAY"
    assert action["text"] == "hi"
    assert llm.calls == 1


def test_repair_invalid_params_can_be_fixed():
    tools = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    tools.register(
        Tool(
            name="add",
            description="Add two integers",
            parameters={
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
            function=add,
        )
    )

    raw = '{"type":"CALL_TOOL","name":"add","params":{"a":"2","b":3}}'
    llm = FakeRepairLLM(
        [
            '{"type":"CALL_TOOL","name":"add","params":{"a":2,"b":3}}',
        ]
    )

    action = validate_or_repair_action(llm=llm, raw_text=raw, tool_registry=tools)
    assert action["type"] == "CALL_TOOL"
    assert action["name"] == "add"
    assert action["params"] == {"a": 2, "b": 3}


def test_unknown_tool_can_fail_deterministically_if_not_fixed():
    tools = ToolRegistry()

    raw = '{"type":"CALL_TOOL","name":"nope","params":{}}'
    llm = FakeRepairLLM([raw])

    with pytest.raises(ValidationError) as exc:
        validate_or_repair_action(llm=llm, raw_text=raw, tool_registry=tools)

    assert exc.value.error_type == "unknown_tool"
