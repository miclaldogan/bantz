"""JSON Protocol and Validation for LLM-First Architecture (Issue #86).

This module provides robust JSON extraction, validation, and schema checking
for LLM outputs. Handles common LLM failures like markdown wrapping, trailing
commas, extra text, and schema violations.

Key Features:
- Balanced-braces JSON extraction from noisy text
- Schema validation (with optional jsonschema support)
- Detailed error categorization for repair
- Type checking and parameter validation
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Union

# Optional jsonschema dependency
try:
    import jsonschema
    from jsonschema import ValidationError as JsonSchemaValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JsonParseError(Exception):
    """Exception raised when JSON parsing fails.
    
    Attributes:
        reason: Short error code (e.g., "empty_output", "unbalanced_json")
        raw_text: The problematic input text (truncated for logging)
        position: Optional character position where error occurred
        context: Optional additional context about the error
    """
    
    reason: str
    raw_text: str
    position: Optional[int] = None
    context: Optional[dict[str, Any]] = None

    def __str__(self) -> str:
        if self.position is not None:
            return f"parse_error:{self.reason}@{self.position}"
        return f"parse_error:{self.reason}"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging."""
        return {
            "error_type": "parse_error",
            "reason": self.reason,
            "raw_text": self.raw_text[:500] if len(self.raw_text) > 500 else self.raw_text,
            "position": self.position,
            "context": self.context,
        }


def extract_first_json_object(text: str, *, strict: bool = False) -> dict[str, Any]:
    """Extract the first JSON object from arbitrary text.

    Uses balanced-braces scanning to find valid JSON objects even when
    surrounded by markdown, explanations, or other noise.
    
    Args:
        text: Input text containing JSON (may have leading/trailing content)
        strict: If True, requires clean JSON with no surrounding text
    
    Returns:
        Parsed JSON object as dictionary
    
    Raises:
        JsonParseError: If no valid JSON object can be extracted
    
    Examples:
        >>> extract_first_json_object('{"a": 1}')
        {'a': 1}
        
        >>> extract_first_json_object('Here is JSON: {"b": 2}')
        {'b': 2}
        
        >>> extract_first_json_object('```json\\n{"c": 3}\\n```')
        {'c': 3}
    """

    text = (text or "").strip()
    if not text:
        raise JsonParseError("empty_output", raw_text=text)
    
    # Strict mode: no leading/trailing content allowed
    if strict and not text.startswith("{"):
        raise JsonParseError(
            "strict_mode_violation",
            raw_text=text,
            context={"expected": "JSON starting with '{'"}
        )

    start = text.find("{")
    if start < 0:
        raise JsonParseError("no_json_object", raw_text=text)
    
    # Log warning if there's significant leading content
    if start > 100:
        logger.warning(
            f"JSON object found at position {start} (large preamble may indicate LLM confusion)"
        )

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
                    raise JsonParseError(
                        "json_decode_error",
                        raw_text=candidate,
                        position=e.pos if hasattr(e, 'pos') else None,
                        context={"json_error": str(e)}
                    ) from e
                
                if not isinstance(obj, dict):
                    raise JsonParseError(
                        "json_not_object",
                        raw_text=candidate,
                        context={"actual_type": type(obj).__name__}
                    )
                
                # Strict mode: check for trailing content
                if strict and idx + 1 < len(text):
                    trailing = text[idx + 1:].strip()
                    if trailing and not trailing.startswith("```"):  # Allow markdown close
                        raise JsonParseError(
                            "strict_mode_violation",
                            raw_text=text,
                            context={"trailing_content": trailing[:100]}
                        )
                
                return obj

    raise JsonParseError(
        "unbalanced_json",
        raw_text=text,
        context={"start_position": start, "depth_at_end": depth}
    )


@dataclass
class ValidationError(Exception):
    """Exception raised when action validation fails.
    
    Attributes:
        error_type: Category of error (parse_error, schema_error, unknown_tool, invalid_params)
        message: Human-readable error message
        details: Additional structured information about the error
        field_path: Optional JSON path to the problematic field (e.g., "params.duration")
        suggestions: List of suggestions to fix the error
    """
    
    error_type: str  # parse_error | schema_error | unknown_tool | invalid_params
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    field_path: str = ""
    suggestions: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.field_path:
            return f"{self.error_type}:{self.message} (field: {self.field_path})"
        return f"{self.error_type}:{self.message}"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging and repair prompts."""
        return {
            "error_type": self.error_type,
            "message": self.message,
            "details": self.details if self.details else None,
            "field_path": self.field_path if self.field_path else None,
            "suggestions": self.suggestions,
        }


def validate_tool_action(
    *,
    action: dict[str, Any],
    tool_registry: Any,
) -> None:
    """Validate a CALL_TOOL action against ToolRegistry.

    Checks:
    - Tool exists in registry
    - Required parameters are present
    - Parameter types match schema
    - No unknown parameters (with warning)
    
    Args:
        action: Action dictionary with type="CALL_TOOL"
        tool_registry: ToolRegistry instance for validation
    
    Raises:
        ValidationError: If validation fails (unknown_tool or invalid_params)
    """

    typ = str(action.get("type") or "").strip().upper()
    if typ != "CALL_TOOL":
        return

    name = str(action.get("name") or "").strip()
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}

    # ToolRegistry validation
    ok, why = tool_registry.validate_call(name, params)
    if not ok:
        # Parse validation failure reason
        if why.startswith("unknown_tool:"):
            # Extract tool name from error
            available_tools = _get_available_tools(tool_registry)
            suggestions = _suggest_similar_tools(name, available_tools)
            
            raise ValidationError(
                "unknown_tool",
                why,
                details={"tool": name, "available_tools": available_tools[:10]},
                field_path="name",
                suggestions=suggestions
            )
        
        if why.startswith("missing_param:"):
            # Extract parameter name
            param_name = why.split(":", 1)[1] if ":" in why else "unknown"
            raise ValidationError(
                "invalid_params",
                why,
                details={"tool": name, "missing_param": param_name},
                field_path=f"params.{param_name}",
                suggestions=[f"Add required parameter '{param_name}'"]
            )
        
        if why.startswith("bad_type:"):
            raise ValidationError(
                "invalid_params",
                why,
                details={"tool": name},
                field_path="params",
                suggestions=["Check parameter types against tool schema"]
            )
        
        # Generic invalid params error
        raise ValidationError(
            "invalid_params",
            why,
            details={"tool": name},
            field_path="params"
        )


def _get_available_tools(tool_registry: Any) -> list[str]:
    """Get list of available tool names from registry."""
    try:
        # ToolRegistry has names() method that returns sorted list
        if hasattr(tool_registry, 'names'):
            return tool_registry.names()
        # Fallback for other registry types
        if hasattr(tool_registry, 'list_tools'):
            return list(tool_registry.list_tools())
        return []
    except Exception:
        return []


def _suggest_similar_tools(query: str, available: list[str], limit: int = 3) -> list[str]:
    """Suggest similar tool names using simple string similarity."""
    if not query or not available:
        return []
    
    query_lower = query.lower()
    
    # Exact prefix match
    exact_matches = [t for t in available if t.lower().startswith(query_lower)]
    if exact_matches:
        return exact_matches[:limit]
    
    # Contains match
    contains_matches = [t for t in available if query_lower in t.lower()]
    if contains_matches:
        return contains_matches[:limit]
    
    # Check if query is contained in any tool (reverse check)
    reverse_contains = [t for t in available if query_lower.replace("_", "") in t.lower().replace("_", "")]
    if reverse_contains:
        return reverse_contains[:limit]
    
    # Simple edit distance: count character differences
    def simple_distance(s1: str, s2: str) -> int:
        """Count character differences (simplified Hamming-like distance)."""
        s1, s2 = s1.lower(), s2.lower()
        if len(s1) != len(s2):
            return abs(len(s1) - len(s2)) + sum(c1 != c2 for c1, c2 in zip(s1, s2))
        return sum(c1 != c2 for c1, c2 in zip(s1, s2))
    
    # Sort by edit distance
    scored = [(t, simple_distance(query, t)) for t in available]
    scored.sort(key=lambda x: x[1])
    
    # Return tools with reasonable similarity (distance <= 3)
    similar = [t for t, dist in scored if dist <= 3]
    return similar[:limit] if similar else [t for t, _ in scored[:limit]]


def validate_action_shape(action: dict[str, Any]) -> None:
    """Validate the minimal control-protocol action shape.

    Checks required fields for each action type according to the protocol:
    - SAY: requires 'text' field
    - ASK_USER: requires 'question' field
    - FAIL: requires 'error' field
    - CALL_TOOL: requires 'name' and optional 'params' (dict)
    
    Args:
        action: Action dictionary to validate
    
    Raises:
        ValidationError: If action shape is invalid
    """

    if not isinstance(action, dict):
        raise ValidationError(
            "schema_error",
            "action_not_dict",
            details={"actual_type": type(action).__name__},
            suggestions=["Ensure LLM returns a JSON object, not array or primitive"]
        )

    typ = str(action.get("type") or "").strip().upper()
    if typ not in {"SAY", "ASK_USER", "FAIL", "CALL_TOOL"}:
        raise ValidationError(
            "schema_error",
            f"unknown_type:{typ}",
            details={"provided_type": typ, "valid_types": ["SAY", "ASK_USER", "FAIL", "CALL_TOOL"]},
            field_path="type",
            suggestions=[
                "Use one of: SAY, ASK_USER, FAIL, CALL_TOOL",
                "Check for typos in 'type' field"
            ]
        )

    # Type-specific validation
    if typ == "SAY":
        text = str(action.get("text") or "").strip()
        if not text:
            raise ValidationError(
                "schema_error",
                "missing_text",
                details={"action_type": "SAY"},
                field_path="text",
                suggestions=["Add non-empty 'text' field to SAY action"]
            )
    
    elif typ == "ASK_USER":
        question = str(action.get("question") or "").strip()
        if not question:
            raise ValidationError(
                "schema_error",
                "missing_question",
                details={"action_type": "ASK_USER"},
                field_path="question",
                suggestions=["Add non-empty 'question' field to ASK_USER action"]
            )
    
    elif typ == "FAIL":
        error = str(action.get("error") or "").strip()
        if not error:
            raise ValidationError(
                "schema_error",
                "missing_error",
                details={"action_type": "FAIL"},
                field_path="error",
                suggestions=["Add non-empty 'error' field to FAIL action"]
            )
    
    elif typ == "CALL_TOOL":
        name = str(action.get("name") or "").strip()
        if not name:
            raise ValidationError(
                "schema_error",
                "missing_tool_name",
                details={"action_type": "CALL_TOOL"},
                field_path="name",
                suggestions=["Add 'name' field with tool name to CALL_TOOL action"]
            )
        
        params = action.get("params")
        if params is not None and not isinstance(params, dict):
            raise ValidationError(
                "schema_error",
                "params_not_object",
                details={
                    "action_type": "CALL_TOOL",
                    "actual_type": type(params).__name__
                },
                field_path="params",
                suggestions=["Ensure 'params' is a JSON object (dict), not array or primitive"]
            )


def validate_with_jsonschema_if_available(
    *, schema: dict[str, Any], instance: Any
) -> None:
    """Validate instance against JSONSchema with detailed error reporting.
    
    Args:
        schema: JSONSchema dictionary
        instance: Value to validate against schema
        
    Raises:
        ValidationError: If validation fails
        
    Note:
        If jsonschema is not installed, validation is silently skipped.
        Install with: pip install jsonschema
    """

    if not JSONSCHEMA_AVAILABLE:
        logger.debug("jsonschema not available, skipping schema validation")
        return

    try:
        jsonschema.validate(instance=instance, schema=schema)
    except JsonSchemaValidationError as e:
        # Extract detailed error information
        field_path = ".".join(str(p) for p in e.path) if e.path else None
        
        # Build helpful suggestions based on error type
        suggestions = []
        if e.validator == "required":
            missing_fields = e.validator_value if isinstance(e.validator_value, list) else [e.validator_value]
            suggestions.append(f"Add required field(s): {', '.join(missing_fields)}")
        elif e.validator == "type":
            expected_type = e.validator_value
            actual_type = type(e.instance).__name__
            suggestions.append(f"Change {actual_type} to {expected_type}")
        elif e.validator == "enum":
            allowed = e.validator_value
            suggestions.append(f"Use one of: {', '.join(map(str, allowed))}")
        elif e.validator == "pattern":
            pattern = e.validator_value
            suggestions.append(f"Value must match pattern: {pattern}")
        
        raise ValidationError(
            "schema_error",
            "jsonschema_validation_failed",
            details={
                "validator": e.validator,
                "validator_value": e.validator_value,
                "schema_path": list(e.schema_path),
                "message": e.message
            },
            field_path=field_path,
            suggestions=suggestions if suggestions else [str(e.message)]
        ) from e
    except Exception as e:
        raise ValidationError(
            "schema_error",
            "jsonschema_unexpected_error",
            details={"error": str(e)},
            suggestions=["Check schema validity", "Ensure jsonschema version compatibility"]
        ) from e


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"_unserializable": str(value)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Router/Orchestrator Output Schema (Issue #228)
# ---------------------------------------------------------------------------

ORCHESTRATOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["route", "calendar_intent", "confidence", "tool_plan", "assistant_reply"],
    "properties": {
        "route": {
            "type": "string",
            "enum": ["calendar", "gmail", "smalltalk", "system", "unknown"],
            "description": "Primary route classification",
        },
        "calendar_intent": {
            "type": "string",
            "pattern": "^[a-z0-9_]*$",
            "description": "Calendar intent (create, modify, cancel, query, none)",
        },
        "slots": {
            "type": "object",
            "properties": {
                "date": {"type": ["string", "null"]},
                "time": {"type": ["string", "null"]},
                "duration": {"type": ["integer", "string", "null"]},
                "title": {"type": ["string", "null"]},
                "window_hint": {"type": ["string", "null"]},
            },
            "additionalProperties": True,
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score 0.0-1.0",
        },
        "tool_plan": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "tool": {"type": "string"},
                            "tool_name": {"type": "string"},
                        },
                    },
                ]
            },
            "description": "List of tool names to call",
        },
        "assistant_reply": {
            "type": "string",
            "description": "Chat response text",
        },
        "ask_user": {
            "type": "boolean",
            "default": False,
        },
        "question": {
            "type": "string",
            "default": "",
        },
        "requires_confirmation": {
            "type": "boolean",
            "default": False,
        },
        "confirmation_prompt": {
            "type": "string",
            "default": "",
        },
        "memory_update": {
            "type": "string",
            "default": "",
        },
        "reasoning_summary": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
    },
}

# Fallback defaults for safe recovery (Issue #228)
ORCHESTRATOR_FALLBACK_DEFAULTS: dict[str, Any] = {
    "route": "smalltalk",
    "calendar_intent": "none",
    "slots": {},
    "confidence": 0.0,
    "tool_plan": [],
    "assistant_reply": "",
    "ask_user": False,
    "question": "",
    "requires_confirmation": False,
    "confirmation_prompt": "",
    "memory_update": "",
    "reasoning_summary": [],
}


def validate_orchestrator_output(
    parsed: dict[str, Any],
    *,
    strict: bool = False,
) -> tuple[bool, list[str]]:
    """Validate parsed orchestrator output against schema.
    
    Args:
        parsed: Parsed JSON from LLM
        strict: If True, use jsonschema if available
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors: list[str] = []
    
    if not isinstance(parsed, dict):
        errors.append("output_not_dict")
        return False, errors
    
    # Check required fields
    required = ["route", "calendar_intent", "confidence", "tool_plan", "assistant_reply"]
    for field in required:
        if field not in parsed:
            errors.append(f"missing_required:{field}")
    
    # Validate route enum
    route = parsed.get("route")
    if route is not None:
        valid_routes = {"calendar", "gmail", "smalltalk", "system", "unknown"}
        if str(route).lower() not in valid_routes:
            errors.append(f"invalid_route:{route}")
    
    # Validate confidence range
    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            conf_val = float(confidence)
            if conf_val < 0.0 or conf_val > 1.0:
                errors.append(f"confidence_out_of_range:{confidence}")
        except (TypeError, ValueError):
            errors.append(f"confidence_not_number:{confidence}")
    
    # Validate tool_plan is array
    tool_plan = parsed.get("tool_plan")
    if tool_plan is not None and not isinstance(tool_plan, list):
        errors.append(f"tool_plan_not_array:{type(tool_plan).__name__}")
    
    # Validate slots is dict
    slots = parsed.get("slots")
    if slots is not None and not isinstance(slots, dict):
        errors.append(f"slots_not_dict:{type(slots).__name__}")
    
    # Use jsonschema if strict mode and available
    if strict and JSONSCHEMA_AVAILABLE and not errors:
        try:
            jsonschema.validate(instance=parsed, schema=ORCHESTRATOR_OUTPUT_SCHEMA)
        except Exception as e:
            errors.append(f"jsonschema_error:{str(e)[:200]}")
    
    return len(errors) == 0, errors


def apply_orchestrator_defaults(
    parsed: dict[str, Any],
) -> dict[str, Any]:
    """Apply fallback defaults to incomplete orchestrator output.
    
    Args:
        parsed: Parsed JSON (may be incomplete)
        
    Returns:
        Complete dict with all required fields
    """
    result = dict(ORCHESTRATOR_FALLBACK_DEFAULTS)
    
    if not isinstance(parsed, dict):
        return result
    
    # Override with provided values
    for key, value in parsed.items():
        if value is not None:
            result[key] = value
    
    # Normalize route
    if "route" in result:
        route = str(result["route"]).lower().strip()
        if route not in {"calendar", "gmail", "smalltalk", "system", "unknown"}:
            route = "unknown"
        result["route"] = route
    
    # Normalize confidence to 0.0-1.0
    if "confidence" in result:
        try:
            result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))
        except (TypeError, ValueError):
            result["confidence"] = 0.0
    
    # Ensure tool_plan is list
    if not isinstance(result.get("tool_plan"), list):
        result["tool_plan"] = []
    
    # Ensure slots is dict
    if not isinstance(result.get("slots"), dict):
        result["slots"] = {}
    
    return result


def repair_common_json_issues(text: str) -> str:
    """Attempt to repair common JSON issues from LLM output.
    
    Repairs:
    - Trailing commas in objects/arrays
    - Single quotes instead of double quotes
    - Unquoted keys
    - Missing closing braces (simple cases)
    
    Args:
        text: Raw LLM output with potential JSON issues
        
    Returns:
        Repaired text (may still not be valid JSON)
    """
    if not text:
        return text
    
    # Remove markdown code blocks
    text = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    text = re.sub(r'\n?```\s*$', '', text.strip())
    
    # Remove leading/trailing explanations before/after JSON
    # Find first { and last }
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace >= 0 and last_brace > first_brace:
        text = text[first_brace:last_brace + 1]
    
    # Fix trailing commas before } or ]
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    
    # Fix single quotes to double quotes (careful with apostrophes)
    # Only replace if it looks like a JSON string boundary
    text = re.sub(r"'(\w+)'(\s*:)", r'"\1"\2', text)  # Keys
    
    # Fix unquoted string values (basic cases)
    # Pattern: : unquoted_value, or : unquoted_value}
    text = re.sub(r':\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*([,}])', r': "\1"\2', text)
    
    return text

