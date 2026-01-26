from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class Tool:
    """Tool definition for agent planning.

    Note: In Bantz, most tools map 1:1 to existing router intents.
    """

    name: str
    description: str
    parameters: JsonSchema
    function: Optional[Callable[..., Any]] = None
    requires_confirmation: bool = False


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def as_schema(self) -> list[dict[str, Any]]:
        """Return a JSON-serializable schema list for prompting."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "requires_confirmation": bool(t.requires_confirmation),
            }
            for t in self._tools.values()
        ]

    def validate_call(self, name: str, params: dict[str, Any]) -> tuple[bool, str]:
        tool = self.get(name)
        if not tool:
            return False, f"unknown_tool:{name}"

        schema = tool.parameters or {}
        required = schema.get("required") or []
        for key in required:
            if key not in params:
                return False, f"missing_param:{key}"

        # Lightweight type checks (avoid extra deps like jsonschema)
        props = schema.get("properties") or {}
        for key, value in params.items():
            spec = props.get(key)
            if not spec:
                continue
            expected = spec.get("type")
            if expected == "integer" and not isinstance(value, int):
                return False, f"bad_type:{key}:expected_int"
            if expected == "number" and not isinstance(value, (int, float)):
                return False, f"bad_type:{key}:expected_number"
            if expected == "string" and not isinstance(value, str):
                return False, f"bad_type:{key}:expected_string"
            if expected == "boolean" and not isinstance(value, bool):
                return False, f"bad_type:{key}:expected_boolean"

        return True, "ok"
