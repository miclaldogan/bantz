from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Literal


JsonSchema = dict[str, Any]

RiskLevel = Literal["LOW", "MED", "HIGH"]


@dataclass(frozen=True)
class ToolSpec:
    """Standard tool spec for LLM prompting (Issue #85)."""

    name: str
    description: str
    args_schema: JsonSchema
    returns_schema: Optional[JsonSchema] = None
    risk_level: RiskLevel = "LOW"
    requires_confirmation: bool = False
    examples: Optional[list[dict[str, Any]]] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema,
            "risk_level": self.risk_level,
            "requires_confirmation": bool(self.requires_confirmation),
        }
        if self.returns_schema is not None:
            out["returns_schema"] = self.returns_schema
        if self.examples is not None:
            out["examples"] = self.examples
        return out


@dataclass(frozen=True)
class Tool:
    """Tool definition for agent planning.

    Note: In Bantz, most tools map 1:1 to existing router intents.
    """

    name: str
    description: str
    parameters: JsonSchema
    returns_schema: Optional[JsonSchema] = None
    risk_level: Optional[RiskLevel] = None
    examples: Optional[list[dict[str, Any]]] = None
    function: Optional[Callable[..., Any]] = None
    # Back-compat alias used by older tests/callers.
    handler: Optional[Callable[..., Any]] = None
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        if self.function is None and self.handler is not None:
            object.__setattr__(self, "function", self.handler)


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
        # Backward-compatible legacy schema (kept for existing prompts/callers).
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "requires_confirmation": bool(tool.requires_confirmation),
            }
            for tool in (self._tools[name] for name in self.names())
        ]

    def as_llm_catalog(
        self, *, format: Literal["short", "long"] = "short"
    ) -> list[dict[str, Any]]:
        """Export a deterministic tool catalog for LLM use (Issue #85).

        - `format="short"`: token-budget friendly, minimized schemas.
        - `format="long"`: full schemas + optional examples/returns.
        """

        catalog: list[dict[str, Any]] = []
        for name in self.names():
            tool = self._tools[name]

            risk_level: RiskLevel
            if tool.risk_level is not None:
                risk_level = tool.risk_level
            else:
                risk_level = "HIGH" if tool.requires_confirmation else "LOW"

            args_schema = _normalize_schema(tool.parameters or {})
            returns_schema = (
                _normalize_schema(tool.returns_schema) if tool.returns_schema else None
            )

            if format == "short":
                args_schema = _minimize_schema(args_schema)
                if returns_schema is not None:
                    returns_schema = _minimize_schema(returns_schema)

            spec = ToolSpec(
                name=tool.name,
                description=tool.description,
                args_schema=args_schema,
                returns_schema=returns_schema,
                risk_level=risk_level,
                requires_confirmation=bool(tool.requires_confirmation),
                examples=tool.examples if (format == "long") else None,
            )
            catalog.append(_normalize_schema(spec.to_dict()))

        return catalog

    def as_json_schema(
        self, *, format: Literal["short", "long"] = "short"
    ) -> dict[str, Any]:
        """Return a JSON-serializable catalog envelope.

        Note: This is not a JSONSchema meta-schema; it's a stable JSON object
        containing `tools` with per-tool JSON Schemas.
        """

        return {
            "type": "tool_catalog",
            "version": 1,
            "format": format,
            "tools": self.as_llm_catalog(format=format),
        }

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
            if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
                return False, f"bad_type:{key}:expected_int"
            if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                return False, f"bad_type:{key}:expected_number"
            if expected == "string" and not isinstance(value, str):
                return False, f"bad_type:{key}:expected_string"
            if expected == "boolean" and not isinstance(value, bool):
                return False, f"bad_type:{key}:expected_boolean"

        return True, "ok"


def _normalize_schema(schema: Any) -> Any:
    """Normalize JSON-ish objects for deterministic output.

    - Sort dict keys recursively.
    - For common schema lists like `required`, sort items.
    """

    if schema is None:
        return None

    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key in sorted(schema.keys(), key=lambda k: str(k)):
            value = schema[key]
            if key == "required" and isinstance(value, list):
                out[key] = sorted([str(v) for v in value])
                continue
            out[str(key)] = _normalize_schema(value)
        return out

    if isinstance(schema, list):
        return [_normalize_schema(v) for v in schema]

    return schema


def _minimize_schema(schema: Any) -> Any:
    """Minimize a JSON Schema object for token budget.

    Keeps structural fields needed for reliable tool calling.
    """

    if not isinstance(schema, dict):
        return schema

    keep_keys = {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "oneOf",
        "anyOf",
        "allOf",
        "additionalProperties",
    }
    minimized: dict[str, Any] = {k: v for k, v in schema.items() if k in keep_keys}

    if "properties" in minimized and isinstance(minimized["properties"], dict):
        props = minimized["properties"]
        new_props: dict[str, Any] = {}
        for k in sorted(props.keys(), key=lambda x: str(x)):
            new_props[str(k)] = _minimize_schema(props[k])
        minimized["properties"] = new_props

    if "items" in minimized:
        minimized["items"] = _minimize_schema(minimized["items"])

    for key in ("oneOf", "anyOf", "allOf"):
        if key in minimized and isinstance(minimized[key], list):
            minimized[key] = [_minimize_schema(v) for v in minimized[key]]

    return _normalize_schema(minimized)
