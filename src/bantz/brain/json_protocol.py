from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class JsonParseError(Exception):
    reason: str
    raw_text: str

    def __str__(self) -> str:
        return f"parse_error:{self.reason}"


def extract_first_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from arbitrary text.

    Balanced-braces scan, resilient to leading/trailing chatter and markdown.
    """

    text = (text or "").strip()
    if not text:
        raise JsonParseError("empty_output", raw_text=text)

    start = text.find("{")
    if start < 0:
        raise JsonParseError("no_json_object", raw_text=text)

    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(text)):
        ch = text[idx]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : idx + 1]
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError as e:
                    raise JsonParseError("json_decode_error", raw_text=candidate) from e
                if not isinstance(obj, dict):
                    raise JsonParseError("json_not_object", raw_text=candidate)
                return obj

    raise JsonParseError("unbalanced_json", raw_text=text)


@dataclass(frozen=True)
class ValidationError(Exception):
    error_type: str  # parse_error | schema_error | unknown_tool | invalid_params
    message: str
    details: Optional[dict[str, Any]] = None

    def __str__(self) -> str:
        return f"{self.error_type}:{self.message}"


def validate_tool_action(
    *,
    action: dict[str, Any],
    tool_registry: Any,
) -> None:
    """Validate a CALL_TOOL action against ToolRegistry.

    This covers the taxonomy pieces `unknown_tool` and `invalid_params`.
    """

    typ = str(action.get("type") or "").strip().upper()
    if typ != "CALL_TOOL":
        return

    name = str(action.get("name") or "").strip()
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}

    # ToolRegistry in this repo has validate_call().
    ok, why = tool_registry.validate_call(name, params)
    if not ok:
        if why.startswith("unknown_tool:"):
            raise ValidationError("unknown_tool", why, {"tool": name})
        if why.startswith("missing_param:") or why.startswith("bad_type:"):
            raise ValidationError("invalid_params", why, {"tool": name})
        raise ValidationError("invalid_params", why, {"tool": name})


def validate_action_shape(action: dict[str, Any]) -> None:
    """Validate the minimal control-protocol action shape.

    This is intentionally lightweight; full JSONSchema validation is optional.
    """

    typ = str(action.get("type") or "").strip().upper()
    if typ not in {"SAY", "ASK_USER", "FAIL", "CALL_TOOL"}:
        raise ValidationError("schema_error", f"unknown_type:{typ}")

    if typ == "SAY" and not str(action.get("text") or "").strip():
        raise ValidationError("schema_error", "missing_text")
    if typ == "ASK_USER" and not str(action.get("question") or "").strip():
        raise ValidationError("schema_error", "missing_question")
    if typ == "FAIL" and not str(action.get("error") or "").strip():
        raise ValidationError("schema_error", "missing_error")
    if typ == "CALL_TOOL":
        if not str(action.get("name") or "").strip():
            raise ValidationError("schema_error", "missing_tool_name")
        params = action.get("params")
        if params is not None and not isinstance(params, dict):
            raise ValidationError("schema_error", "params_not_object")


def validate_with_jsonschema_if_available(
    *, schema: dict[str, Any], instance: Any
) -> None:
    """Optionally validate `instance` against JSONSchema if jsonschema is installed."""

    try:
        import jsonschema  # type: ignore
    except Exception:
        return

    try:
        jsonschema.validate(instance=instance, schema=schema)
    except Exception as e:
        raise ValidationError("schema_error", "jsonschema_validation_failed") from e


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"_unserializable": str(value)}, ensure_ascii=False)
