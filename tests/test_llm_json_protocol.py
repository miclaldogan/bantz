from __future__ import annotations

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.json_protocol import (
    JsonParseError,
    ValidationError,
    extract_first_json_object,
    validate_action_shape,
    validate_tool_action,
)
from bantz.brain.json_repair import (
    RepairResult,
    build_repair_prompt,
    repair_to_json_object,
    validate_or_repair_action,
)


class FakeRepairLLM:
    def __init__(self, outputs: list[str]):
        self._outputs = list(outputs)
        self.calls = 0

    def complete_text(self, *, prompt: str) -> str:
        self.calls += 1
        if not self._outputs:
            return "{}"
        return self._outputs.pop(0)


def test_extract_first_json_object_from_mixed_text():
    text = 'Here is some explanation.\n```json\n{"a": 1}\n```\ntrailing text'
    obj = extract_first_json_object(text)
    assert obj == {"a": 1}


def test_repair_invalid_json_trailing_comma_to_valid_action():
    tools = ToolRegistry()

    raw = """Sure!\n```json\n{\"type\": \"SAY\", \"text\": \"hi\",}\n```\n"""

    llm = FakeRepairLLM(['{"type": "SAY", "text": "hi"}'])
    action = validate_or_repair_action(llm=llm, raw_text=raw, tool_registry=tools)

    assert action["type"] == "SAY"
    assert action["text"] == "hi"
    assert llm.calls == 1


def test_repair_invalid_params_can_be_fixed():
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

    raw = '{"type":"CALL_TOOL","name":"add","params":{"a":"2","b":3}}'
    llm = FakeRepairLLM(
        [
            '{"type":"CALL_TOOL","name":"add","params":{"a":2,"b":3}}',
        ]
    )

    action = validate_or_repair_action(llm=llm, raw_text=raw, tool_registry=tools)
    assert action["type"] == "CALL_TOOL"
    assert action["name"] == "add"
    assert action["params"] == {"a": 2, "b": 3}


def test_unknown_tool_can_fail_deterministically_if_not_fixed():
    tools = ToolRegistry()

    raw = '{"type":"CALL_TOOL","name":"nope","params":{}}'
    llm = FakeRepairLLM([raw])

    with pytest.raises(ValidationError) as exc:
        validate_or_repair_action(llm=llm, raw_text=raw, tool_registry=tools)

    assert exc.value.error_type == "unknown_tool"


# ============================================================================
# Enhanced Tests for Issue #86
# ============================================================================


def test_extract_json_with_strict_mode():
    """Test strict mode rejects markdown-wrapped JSON."""
    text = '```json\n{"type": "SAY", "text": "hello"}\n```'
    
    # Non-strict mode should extract
    obj = extract_first_json_object(text, strict=False)
    assert obj == {"type": "SAY", "text": "hello"}
    
    # Strict mode should reject
    with pytest.raises(JsonParseError) as exc:
        extract_first_json_object(text, strict=True)
    assert "strict" in exc.value.reason.lower() or "violation" in exc.value.reason.lower()


def test_extract_json_with_trailing_text():
    """Test extraction ignores trailing non-JSON text."""
    text = '{"type": "SAY", "text": "hello"}\nThis is extra text that should be ignored.'
    obj = extract_first_json_object(text)
    assert obj == {"type": "SAY", "text": "hello"}


def test_extract_nested_json():
    """Test extraction of nested JSON objects."""
    text = '{"type": "CALL_TOOL", "name": "search", "params": {"query": "test", "count": 5}}'
    obj = extract_first_json_object(text)
    assert obj == {"type": "CALL_TOOL", "name": "search", "params": {"query": "test", "count": 5}}


def test_extract_json_with_unicode():
    """Test extraction handles Unicode correctly."""
    text = '{"type": "SAY", "text": "Merhaba dünya! 🌍"}'
    obj = extract_first_json_object(text)
    assert obj == {"type": "SAY", "text": "Merhaba dünya! 🌍"}


def test_validate_action_shape_invalid_type():
    """Test validation rejects unknown action types."""
    action = {"type": "INVALID", "text": "test"}
    
    with pytest.raises(ValidationError) as exc:
        validate_action_shape(action)
    
    assert exc.value.error_type == "schema_error"
    assert "unknown_type" in exc.value.message
    assert exc.value.field_path == "type"
    assert len(exc.value.suggestions) > 0


def test_validate_action_shape_missing_text():
    """Test SAY action validation requires text field."""
    action = {"type": "SAY"}
    
    with pytest.raises(ValidationError) as exc:
        validate_action_shape(action)
    
    assert exc.value.error_type == "schema_error"
    assert "missing_text" in exc.value.message
    assert exc.value.field_path == "text"


def test_validate_action_shape_missing_question():
    """Test ASK_USER action validation requires question field."""
    action = {"type": "ASK_USER"}
    
    with pytest.raises(ValidationError) as exc:
        validate_action_shape(action)
    
    assert exc.value.error_type == "schema_error"
    assert "missing_question" in exc.value.message
    assert exc.value.field_path == "question"


def test_validate_action_shape_missing_error():
    """Test FAIL action validation requires error field."""
    action = {"type": "FAIL"}
    
    with pytest.raises(ValidationError) as exc:
        validate_action_shape(action)
    
    assert exc.value.error_type == "schema_error"
    assert "missing_error" in exc.value.message
    assert exc.value.field_path == "error"


def test_validate_tool_action_with_suggestions():
    """Test tool validation provides suggestions for typos."""
    tools = ToolRegistry()
    
    def search_web(query: str) -> str:
        return "results"
    
    tools.register(
        Tool(
            name="search_web",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            function=search_web,
        )
    )
    
    action = {"type": "CALL_TOOL", "name": "searc_web", "params": {"query": "test"}}  # typo
    
    with pytest.raises(ValidationError) as exc:
        validate_tool_action(action=action, tool_registry=tools)
    
    assert exc.value.error_type == "unknown_tool"
    assert exc.value.field_path == "name"
    # Should suggest search_web due to similarity (edit distance = 1)
    # Debug: print what suggestions we got
    print(f"Suggestions: {exc.value.suggestions}")
    assert len(exc.value.suggestions) > 0
    assert "search_web" in exc.value.suggestions


def test_repair_prompt_includes_error_context():
    """Test repair prompt includes detailed error information."""
    error = ValidationError(
        "unknown_tool",
        "unknown_tool:searc",
        field_path="name",
        suggestions=["search", "search_web"]
    )
    
    prompt = build_repair_prompt(
        raw_text='{"type": "CALL_TOOL", "name": "searc"}',
        error_summary="unknown tool",
        validation_error=error
    )
    
    assert "TOOL HATASI" in prompt
    assert "search" in prompt or "search_web" in prompt
    assert "name" in prompt


def test_repair_to_json_object_success():
    """Test successful repair of malformed JSON."""
    llm = FakeRepairLLM(['{"type": "SAY", "text": "fixed"}'])
    
    result = repair_to_json_object(
        llm=llm,
        raw_text='```json\n{"type": "SAY", "text": "broken",}\n```',
        max_attempts=2
    )
    
    assert result.ok
    assert result.value == {"type": "SAY", "text": "fixed"}
    assert result.attempts == 1


def test_repair_to_json_object_failure():
    """Test repair failure after max attempts."""
    llm = FakeRepairLLM(['invalid', 'also invalid'])
    
    result = repair_to_json_object(
        llm=llm,
        raw_text='not json at all',
        max_attempts=2
    )
    
    assert not result.ok
    assert result.value is None
    assert result.attempts == 2
    assert result.error is not None
    assert result.error_type == "parse_error"


def test_validation_error_to_dict():
    """Test ValidationError serialization for logging."""
    error = ValidationError(
        "schema_error",
        "missing_field",
        details={"field": "text"},
        field_path="text",
        suggestions=["Add text field"]
    )
    
    error_dict = error.to_dict()
    assert error_dict["error_type"] == "schema_error"
    assert error_dict["message"] == "missing_field"
    assert error_dict["field_path"] == "text"
    assert "Add text field" in error_dict["suggestions"]


def test_json_parse_error_to_dict():
    """Test JsonParseError serialization for logging."""
    error = JsonParseError(
        reason="invalid_json",
        raw_text="...broken...",
        position=42,
        context={"detail": "test"}
    )
    
    error_dict = error.to_dict()
    assert error_dict["reason"] == "invalid_json"
    assert error_dict["position"] == 42
    assert "broken" in error_dict["raw_text"]


def test_params_not_object_error():
    """Test validation rejects non-dict params."""
    action = {"type": "CALL_TOOL", "name": "test", "params": "not a dict"}
    
    with pytest.raises(ValidationError) as exc:
        validate_action_shape(action)
    
    assert exc.value.error_type == "schema_error"
    assert "params_not_object" in exc.value.message
    assert exc.value.field_path == "params"


def test_action_not_dict_error():
    """Test validation rejects non-dict actions."""
    action = "not a dict"
    
    with pytest.raises(ValidationError) as exc:
        validate_action_shape(action)  # type: ignore
    
    assert exc.value.error_type == "schema_error"
    assert "action_not_dict" in exc.value.message

