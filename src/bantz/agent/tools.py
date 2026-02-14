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

    def list_tools(self) -> list[Tool]:
        """Return all registered tools sorted by name."""
        return [self._tools[n] for n in self.names()]

    # ------------------------------------------------------------------
    # Issue #1275: Route-based compact tool schema for LLM prompt injection
    # ------------------------------------------------------------------
    def get_schemas_for_route(
        self,
        route: str,
        *,
        valid_tools: frozenset[str] | set[str] | None = None,
    ) -> str:
        """Return compact one-liner schemas for tools matching *route*.

        The route is matched against the tool name prefix (e.g. ``"gmail"``
        matches ``gmail.send``, ``gmail.list_messages``, etc.).  Only tools
        that are also in *valid_tools* (if provided) are included so that
        phantom / unregistered tools never leak into the prompt.

        Returns a newline-separated block like::

            - gmail.send(to*, subject*, body*) — E-posta gönderir [HIGH,confirm]
            - gmail.list_messages(query, max_results, label) — Mailleri listeler [LOW]
        """
        prefix = f"{route}."
        lines: list[str] = []

        for name in self.names():
            if not name.startswith(prefix):
                continue
            if valid_tools is not None and name not in valid_tools:
                continue

            tool = self._tools[name]
            schema = tool.parameters or {}
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])

            # Build compact param list: param* means required
            params: list[str] = []
            for pname in sorted(props.keys()):
                if pname in required:
                    params.append(f"{pname}*")
                else:
                    params.append(pname)

            param_str = ", ".join(params)
            desc = (tool.description or "").split(".")[0].strip()  # first sentence

            risk = tool.risk_level or "LOW"
            tag = f"[{risk}"
            if tool.requires_confirmation:
                tag += ",confirm"
            tag += "]"

            lines.append(f"- {name}({param_str}) — {desc} {tag}")

        return "\n".join(lines)

    def get_schema(self, name: str) -> dict[str, Any] | None:
        """Return the JSON Schema for a single tool, or None if not found."""
        tool = self.get(name)
        if tool is None:
            return None
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "requires_confirmation": bool(tool.requires_confirmation),
            "risk_level": tool.risk_level,
        }

    # ------------------------------------------------------------------
    # Issue #1274: OpenAI-format tool schemas for structured tool calling
    # ------------------------------------------------------------------
    def as_openai_tools(
        self,
        *,
        tool_names: set[str] | frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all tools in OpenAI ``tools`` format for chat completions.

        Each entry is::

            {
              "type": "function",
              "function": {
                "name": "gmail.send",
                "description": "E-posta gönderir",
                "parameters": { ... JSON Schema ... }
              }
            }

        Args:
            tool_names: If provided, only include tools whose name is
                in this set.  Pass ``_VALID_TOOLS`` from the router to
                keep prompt and registry in sync.

        Returns:
            List of OpenAI-compatible tool definitions.
        """
        result: list[dict[str, Any]] = []
        for name in self.names():
            if tool_names is not None and name not in tool_names:
                continue
            tool = self._tools[name]
            # Ensure parameters is a valid object schema
            params = tool.parameters or {"type": "object", "properties": {}}
            if "type" not in params:
                params = {**params, "type": "object"}
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": params,
                },
            })
        return result

    def as_openai_tools_for_route(
        self,
        route: str,
        *,
        valid_tools: frozenset[str] | set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas filtered by route prefix.

        Issue #1274: Used by the router to send only the relevant tools
        for the detected route, keeping the ``tools`` array small (4-19
        entries instead of 76+).

        Args:
            route: Route prefix (e.g. ``"gmail"``, ``"calendar"``).
            valid_tools: Optional set of valid tool names to further
                filter.

        Returns:
            List of OpenAI-compatible tool definitions for the route.
        """
        prefix = f"{route}."
        result: list[dict[str, Any]] = []
        for name in self.names():
            if not name.startswith(prefix):
                continue
            if valid_tools is not None and name not in valid_tools:
                continue
            tool = self._tools[name]
            params = tool.parameters or {"type": "object", "properties": {}}
            if "type" not in params:
                params = {**params, "type": "object"}
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": params,
                },
            })
        return result

    def validate_call(self, name: str, params: dict[str, Any]) -> tuple[bool, str]:
        tool = self.get(name)
        if not tool:
            return False, f"unknown_tool:{name}"

        # Issue #1174: Work on a shallow copy so empty-string → None
        # coercion doesn't mutate the caller's original dict.
        params = dict(params)

        schema = tool.parameters or {}
        required = schema.get("required") or []
        for key in required:
            if key not in params:
                return False, f"missing_param:{key}"

        # Lightweight type checks (avoid extra deps like jsonschema)
        # Issue #656: check bool BEFORE int because bool is a subclass of int.
        props = schema.get("properties") or {}
        for key, value in list(params.items()):
            # Empty-string → None coercion (Issue #663)
            if isinstance(value, str) and not value.strip():
                params[key] = None
                continue

            spec = props.get(key)
            if not spec:
                continue
            expected = spec.get("type")
            # bool must be checked before int (bool ⊂ int in Python)
            if expected == "boolean":
                if not isinstance(value, bool):
                    return False, f"bad_type:{key}:expected_boolean"
            elif expected == "integer":
                if isinstance(value, bool):
                    return False, f"bad_type:{key}:expected_int"
                if isinstance(value, str):
                    try:
                        params[key] = int(value)
                    except (ValueError, TypeError):
                        return False, f"bad_type:{key}:expected_int"
                elif not isinstance(value, int):
                    return False, f"bad_type:{key}:expected_int"
            elif expected == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return False, f"bad_type:{key}:expected_number"
            elif expected == "string":
                if not isinstance(value, str):
                    return False, f"bad_type:{key}:expected_string"

            # Enum validation (Issue #663)
            allowed = spec.get("enum")
            if allowed and value not in allowed:
                return False, f"bad_enum:{key}:expected_one_of:{allowed}"

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
