from __future__ import annotations

import json

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig


class _CapturingLLM:
    def __init__(self, outputs: list[dict]):
        self.outputs = list(outputs)
        self.seen_messages: list[list[dict[str, str]]] = []

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict:
        self.seen_messages.append(list(messages))
        if not self.outputs:
            return {"type": "FAIL", "error": "no_more_outputs"}
        return self.outputs.pop(0)


def test_tool_observation_is_not_user_role() -> None:
    tools = ToolRegistry()

    def echo_tool(**params):
        return {"ok": True, "echo": dict(params)}

    tools.register(
        Tool(
            name="demo.echo",
            description="echo",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            function=echo_tool,
        )
    )

    llm = _CapturingLLM(
        outputs=[
            {"type": "CALL_TOOL", "name": "demo.echo", "params": {"x": "hi"}},
            {"type": "SAY", "text": "ok"},
        ]
    )

    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=3, debug=False))
    result = loop.run(turn_input="test", session_context={}, policy=None, context={"session_id": "t"})
    assert result.kind == "say"

    # The second LLM call should contain the tool observation.
    assert len(llm.seen_messages) >= 2
    tail = llm.seen_messages[1]
    obs_msgs = [m for m in tail if isinstance(m, dict) and str(m.get("content", "")).startswith("TOOL_OBSERVATION:")]
    assert obs_msgs, "expected TOOL_OBSERVATION marker"
    assert all(m.get("role") != "user" for m in obs_msgs)


def test_ask_user_echo_is_rejected_with_fallback_say() -> None:
    tools = ToolRegistry()
    llm = _CapturingLLM(outputs=[{"type": "ASK_USER", "question": "Bu aksam planim var mi?"}])

    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    result = loop.run(turn_input="Bu akşam planım var mı?", session_context={}, policy=None, context={"session_id": "t"})

    assert result.kind == "say"
    assert "netleştirebilir" in result.text
    assert "(1)" in result.text and "(0)" in result.text

    # Ensure we didn't crash on JSON serialization metadata.
    json.dumps(result.metadata)
