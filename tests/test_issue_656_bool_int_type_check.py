# SPDX-License-Identifier: MIT
"""Issue #656: bool must not pass integer/number validation."""

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.safety_guard import SafetyGuard
from bantz.agent.tool_base import ToolBase, ToolSpec, ToolResult


class _TestTool(ToolBase):
    def spec(self):
        return ToolSpec(
            name="test.integer_tool",
            description="Test tool",
            parameters={
                "count": {"type": "integer", "required": True},
                "ratio": {"type": "number", "required": False},
            },
        )

    async def run(self, input, context):
        return ToolResult.ok(data=None)


def test_tool_base_rejects_bool_for_integer_and_number():
    tool = _TestTool()

    ok, err = tool.validate_input({"count": True})
    assert ok is False
    assert "integer" in err.lower()

    ok, err = tool.validate_input({"count": 1, "ratio": False})
    assert ok is False
    assert "number" in err.lower()


def test_tool_registry_validate_call_rejects_bool_int_number():
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="test.registry",
            description="Test",
            parameters={
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "ratio": {"type": "number"},
                },
                "required": [],
            },
            function=lambda **_: None,
        )
    )

    valid, err = reg.validate_call("test.registry", {"count": True})
    assert valid is False
    assert "expected_int" in err

    valid, err = reg.validate_call("test.registry", {"ratio": False})
    assert valid is False
    assert "expected_number" in err


def test_safety_guard_rejects_bool_for_integer_number():
    guard = SafetyGuard()
    tool = Tool(
        name="test.guard",
        description="Test",
        parameters={
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
            },
            "required": [],
        },
        function=lambda **_: None,
    )

    valid, err = guard.validate_tool_args(tool, {"count": True})
    assert valid is False
    assert "integer" in (err or "").lower()

    valid, err = guard.validate_tool_args(tool, {"ratio": False})
    assert valid is False
    assert "number" in (err or "").lower()
