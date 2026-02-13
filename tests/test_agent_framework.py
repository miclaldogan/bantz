from __future__ import annotations

import pytest

from bantz.agent.core import Agent
from bantz.agent.planner import PlannedStep
from bantz.agent.tools import Tool, ToolRegistry


class FakePlanner:
    def __init__(self, steps):
        self._steps = steps

    def plan(self, request: str, tools: ToolRegistry):
        return self._steps


def test_agent_plan_validates_required_params():
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="browser_open",
            description="",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )
    )

    agent = Agent(planner=FakePlanner([PlannedStep(action="browser_open", params={}, description="open")]), tools=reg)

    with pytest.raises(ValueError):
        agent.plan("x", task_id="t")


def test_agent_execute_retries_then_fails():
    from bantz.tools.metadata import register_tool_risk, ToolRisk
    register_tool_risk("browser_open", ToolRisk.SAFE)

    reg = ToolRegistry()
    reg.register(
        Tool(
            name="browser_open",
            description="",
            parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        )
    )

    agent = Agent(
        planner=FakePlanner([PlannedStep(action="browser_open", params={"url": "https://example.com"}, description="open")]),
        tools=reg,
    )

    calls = {"n": 0}

    def runner(action: str, params: dict):
        from bantz.agent.executor import ExecutionResult

        calls["n"] += 1
        return ExecutionResult(ok=False, error="boom")

    task = agent.execute("x", task_id="t", runner=runner, max_retries=1)
    assert task.state.value == "failed"
    assert calls["n"] == 2  # 1 try + 1 retry

    # Cleanup: remove test tool from global registry
    from bantz.tools.metadata import TOOL_REGISTRY
    TOOL_REGISTRY.pop("browser_open", None)


def test_planner_parse_json_object_tolerates_wrapped_output():
    from bantz.agent.planner import Planner

    raw = "here you go\n{\"steps\":[{\"action\":\"browser_open\",\"params\":{\"url\":\"x\"},\"description\":\"d\"}]}\nthanks"
    obj = Planner._parse_json_object(raw)
    assert "steps" in obj
