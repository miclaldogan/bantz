from __future__ import annotations

from bantz.agent.tools import Tool, ToolRegistry


def test_tool_registry_llm_catalog_deterministic_and_formats():
    tools = ToolRegistry()

    # Register out-of-order to prove deterministic sorting by name.
    tools.register(
        Tool(
            name="b_tool",
            description="B tool",
            parameters={
                "type": "object",
                "properties": {
                    "z": {
                        "type": "string",
                        "description": "should be stripped in short",
                    },
                    "a": {"type": "integer"},
                },
                "required": ["z", "a"],
            },
            returns_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
            },
            examples=[{"call": {"z": "x", "a": 1}, "result": {"ok": True}}],
            requires_confirmation=True,
        )
    )

    tools.register(
        Tool(
            name="a_tool",
            description="A tool",
            parameters={
                "type": "object",
                "properties": {"b": {"type": "number"}, "a": {"type": "number"}},
                "required": ["b", "a"],
            },
            risk_level="MED",
        )
    )

    short = tools.as_llm_catalog(format="short")
    long = tools.as_llm_catalog(format="long")

    # Deterministic ordering
    assert [t["name"] for t in short] == ["a_tool", "b_tool"]

    # Stable required + properties ordering
    assert short[0]["args_schema"]["required"] == ["a", "b"]
    assert list(short[0]["args_schema"]["properties"].keys()) == ["a", "b"]

    # Risk defaults and overrides
    assert short[0]["risk_level"] == "MED"
    assert short[1]["risk_level"] == "HIGH"  # inferred from requires_confirmation

    # Short format strips examples and schema descriptions
    assert "examples" not in short[1]
    assert "description" not in short[1]["args_schema"]["properties"]["z"]

    # Long format includes examples and returns_schema
    assert "examples" in long[1]
    assert "returns_schema" in long[1]

    # Wrapper is stable and contains tools
    envelope = tools.as_json_schema(format="short")
    assert envelope["type"] == "tool_catalog"
    assert envelope["version"] == 1
    assert envelope["format"] == "short"
    assert envelope["tools"] == short
