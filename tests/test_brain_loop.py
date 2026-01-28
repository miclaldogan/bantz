from __future__ import annotations


from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig


class FakeLLM:
    def __init__(self, outputs: list[dict]):
        self._outputs = list(outputs)
        self.calls: int = 0

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict:
        self.calls += 1
        if not self._outputs:
            return {"type": "FAIL", "error": "no_more_outputs"}
        return self._outputs.pop(0)


def test_brain_loop_tool_then_say():
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

    llm = FakeLLM(
        [
            {"type": "CALL_TOOL", "name": "add", "params": {"a": 2, "b": 3}},
            {"type": "SAY", "text": "Sonuç 5."},
        ]
    )

    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=4))
    result = loop.run(turn_input="2 ile 3 topla")

    assert result.kind == "say"
    assert "5" in result.text
    assert result.steps_used == 2


def test_brain_loop_max_steps_exceeded():
    tools = ToolRegistry()
    llm = FakeLLM([
        {"type": "CALL_TOOL", "name": "missing", "params": {}},
        {"type": "CALL_TOOL", "name": "missing", "params": {}},
        {"type": "CALL_TOOL", "name": "missing", "params": {}},
    ])

    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2))
    result = loop.run(turn_input="hi")
    assert result.kind == "fail"
    assert result.text == "max_steps_exceeded"
