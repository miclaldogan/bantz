"""Contract tests for Orchestrator/Router outputs (Issue #139).

These tests validate the JSON schema structure of LLM responses,
ensuring all required fields are present and have correct types.

Contract tests do NOT test LLM logic - they test the data structure.

Run:
    pytest tests/test_contract_orchestrator.py -v
"""

from __future__ import annotations

import pytest
from typing import Any, Dict
import json

from bantz.brain.llm_router import RouterOutput, JarvisLLMOrchestrator


def validate_router_output_schema(data: Dict[str, Any]) -> None:
    """Validate that data conforms to RouterOutput schema."""
    # Required fields
    assert "route" in data, "Missing 'route' field"
    assert "calendar_intent" in data, "Missing 'calendar_intent' field"
    assert "slots" in data, "Missing 'slots' field"
    assert "confidence" in data, "Missing 'confidence' field"
    assert "tool_plan" in data, "Missing 'tool_plan' field"
    assert "assistant_reply" in data, "Missing 'assistant_reply' field"
    
    # Type checks
    assert isinstance(data["route"], str), "route must be string"
    assert isinstance(data["calendar_intent"], str), "calendar_intent must be string"
    assert isinstance(data["slots"], dict), "slots must be dict"
    assert isinstance(data["confidence"], (int, float)), "confidence must be number"
    assert isinstance(data["tool_plan"], list), "tool_plan must be list"
    assert isinstance(data["assistant_reply"], str), "assistant_reply must be string"
    
    # Optional fields type checks
    if "ask_user" in data:
        assert isinstance(data["ask_user"], bool), "ask_user must be bool"
    if "question" in data and data["question"] is not None:
        assert isinstance(data["question"], str), "question must be string (if not None)"
    if "requires_confirmation" in data:
        assert isinstance(data["requires_confirmation"], bool), "requires_confirmation must be bool"
    if "confirmation_prompt" in data:
        assert isinstance(data["confirmation_prompt"], str), "confirmation_prompt must be string"
    if "memory_update" in data:
        assert isinstance(data["memory_update"], str), "memory_update must be string"
    if "reasoning_summary" in data:
        assert isinstance(data["reasoning_summary"], (str, list)), "reasoning_summary must be string or list"


def validate_orchestrator_output_schema(output: Any) -> None:
    """Validate that output conforms to OrchestratorOutput interface."""
    # Required fields
    assert hasattr(output, "route"), "Missing 'route' field"
    assert hasattr(output, "calendar_intent"), "Missing 'calendar_intent' field"
    assert hasattr(output, "slots"), "Missing 'slots' field"
    assert hasattr(output, "confidence"), "Missing 'confidence' field"
    assert hasattr(output, "tool_plan"), "Missing 'tool_plan' field"
    assert hasattr(output, "assistant_reply"), "Missing 'assistant_reply' field"
    
    # Type checks
    assert isinstance(output.route, str), "route must be string"
    assert isinstance(output.calendar_intent, str), "calendar_intent must be string"
    assert isinstance(output.slots, dict), "slots must be dict"
    assert isinstance(output.confidence, (int, float)), "confidence must be number"
    assert isinstance(output.tool_plan, list), "tool_plan must be list"
    assert isinstance(output.assistant_reply, str), "assistant_reply must be string"


# =============================================================================
# RouterOutput Contract Tests
# =============================================================================

class TestRouterOutputContract:
    """Contract tests for RouterOutput schema."""
    
    def test_minimal_valid_output(self):
        """Test minimal valid RouterOutput (all required fields)."""
        data = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Merhaba!",
        }
        
        # Should not raise
        validate_router_output_schema(data)
    
    def test_full_valid_output(self):
        """Test full valid RouterOutput (all fields)."""
        data = {
            "route": "calendar",
            "calendar_intent": "create_event",
            "slots": {"time": "14:00", "title": "meeting"},
            "confidence": 0.90,
            "tool_plan": [{"name": "calendar.create_event", "args": {}}],
            "assistant_reply": "Tamam, toplantı oluşturuyorum.",
            "ask_user": False,
            "question": None,
            "requires_confirmation": True,
            "confirmation_prompt": "Saat 14:00 için toplantı oluşturulsun mu?",
            "memory_update": "User wants to create a meeting at 14:00",
            "reasoning_summary": "Create event confirmed by user",
        }
        
        # Should not raise
        validate_router_output_schema(data)
    
    def test_missing_required_field_route(self):
        """Test that missing 'route' raises error."""
        data = {
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Hello",
        }
        
        with pytest.raises(AssertionError, match="Missing 'route' field"):
            validate_router_output_schema(data)
    
    def test_missing_required_field_tool_plan(self):
        """Test that missing 'tool_plan' raises error."""
        data = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "assistant_reply": "Hello",
        }
        
        with pytest.raises(AssertionError, match="Missing 'tool_plan' field"):
            validate_router_output_schema(data)
    
    def test_wrong_type_route(self):
        """Test that wrong type for 'route' raises error."""
        data = {
            "route": 123,  # Should be string
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Hello",
        }
        
        with pytest.raises(AssertionError, match="route must be string"):
            validate_router_output_schema(data)
    
    def test_wrong_type_slots(self):
        """Test that wrong type for 'slots' raises error."""
        data = {
            "route": "calendar",
            "calendar_intent": "list_events",
            "slots": "not a dict",  # Should be dict
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Hello",
        }
        
        with pytest.raises(AssertionError, match="slots must be dict"):
            validate_router_output_schema(data)
    
    def test_wrong_type_confidence(self):
        """Test that wrong type for 'confidence' raises error."""
        data = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": "high",  # Should be number
            "tool_plan": [],
            "assistant_reply": "Hello",
        }
        
        with pytest.raises(AssertionError, match="confidence must be number"):
            validate_router_output_schema(data)
    
    def test_wrong_type_tool_plan(self):
        """Test that wrong type for 'tool_plan' raises error."""
        data = {
            "route": "calendar",
            "calendar_intent": "list_events",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": "not a list",  # Should be list
            "assistant_reply": "Hello",
        }
        
        with pytest.raises(AssertionError, match="tool_plan must be list"):
            validate_router_output_schema(data)
    
    def test_optional_fields_with_wrong_types(self):
        """Test that optional fields with wrong types raise errors."""
        # ask_user must be bool
        data = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Hello",
            "ask_user": "yes",  # Should be bool
        }
        
        with pytest.raises(AssertionError, match="ask_user must be bool"):
            validate_router_output_schema(data)
        
        # requires_confirmation must be bool
        data["ask_user"] = True
        data["requires_confirmation"] = "yes"  # Should be bool
        
        with pytest.raises(AssertionError, match="requires_confirmation must be bool"):
            validate_router_output_schema(data)


# =============================================================================
# OrchestratorOutput Contract Tests
# =============================================================================

class TestOrchestratorOutputContract:
    """Contract tests for OrchestratorOutput dataclass."""
    
    def test_router_output_to_orchestrator_output(self):
        """Test that RouterOutput can be converted to OrchestratorOutput."""
        from bantz.brain.llm_router import RouterOutput
        
        output = RouterOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.95,
            tool_plan=[],
            assistant_reply="Merhaba!",
        )
        
        # Should have all required fields
        validate_orchestrator_output_schema(output)
    
    def test_orchestrator_output_with_all_fields(self):
        """Test OrchestratorOutput with all optional fields."""
        from bantz.brain.llm_router import RouterOutput
        
        output = RouterOutput(
            route="calendar",
            calendar_intent="create_event",
            slots={"time": "14:00", "title": "meeting"},
            confidence=0.90,
            tool_plan=[{"name": "calendar.create_event", "args": {}}],
            assistant_reply="Tamam, toplantı oluşturuyorum.",
            ask_user=False,
            question=None,
            requires_confirmation=True,
            confirmation_prompt="Saat 14:00 için toplantı oluşturulsun mu?",
            memory_update="User wants to create a meeting at 14:00",
            reasoning_summary="Create event confirmed by user",
        )
        
        # Should have all fields
        validate_orchestrator_output_schema(output)
        
        # Check optional fields are accessible
        assert output.requires_confirmation is True
        assert output.confirmation_prompt == "Saat 14:00 için toplantı oluşturulsun mu?"
        assert output.memory_update == "User wants to create a meeting at 14:00"


# =============================================================================
# JSON Parsing Contract Tests
# =============================================================================

class TestJSONParsingContract:
    """Contract tests for JSON parsing (LLM output → Python objects)."""
    
    def test_parse_valid_json_string(self):
        """Test parsing valid JSON string into RouterOutput."""
        json_str = json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Merhaba!",
        })
        
        # Parse as dict
        data = json.loads(json_str)
        
        # Validate schema
        validate_router_output_schema(data)
    
    def test_parse_json_with_unicode(self):
        """Test parsing JSON with Turkish characters."""
        json_str = json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Merhaba! Nasılsın?",
        }, ensure_ascii=False)
        
        data = json.loads(json_str)
        validate_router_output_schema(data)
        assert "Nasılsın" in data["assistant_reply"]
    
    def test_parse_json_with_nested_slots(self):
        """Test parsing JSON with nested slot structures."""
        json_str = json.dumps({
            "route": "calendar",
            "calendar_intent": "list_events",
            "slots": {
                "time_range": {
                    "start": "2026-01-30T00:00:00",
                    "end": "2026-01-30T23:59:59",
                },
            },
            "confidence": 0.90,
            "tool_plan": [{"name": "calendar.list_events", "args": {}}],
            "assistant_reply": "Bugünkü etkinlikler...",
        }, ensure_ascii=False)
        
        data = json.loads(json_str)
        validate_router_output_schema(data)
        assert "time_range" in data["slots"]
        assert isinstance(data["slots"]["time_range"], dict)
    
    def test_parse_malformed_json(self):
        """Test that malformed JSON raises error."""
        malformed_json = '{"route": "smalltalk", "calendar_intent": "none"'  # Missing closing }
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(malformed_json)
    
    def test_parse_json_with_extra_fields(self):
        """Test that extra fields don't break parsing (forward compatibility)."""
        json_str = json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.95,
            "tool_plan": [],
            "assistant_reply": "Hello",
            "extra_field": "This is not in schema",  # Extra field
            "another_extra": 123,
        })
        
        data = json.loads(json_str)
        
        # Should still pass validation (extra fields ignored)
        validate_router_output_schema(data)


# =============================================================================
# Rate Limit / Timeout Contract Tests
# =============================================================================

class TestErrorResponseContract:
    """Contract tests for error responses (timeouts, rate limits)."""
    
    def test_connection_error_structure(self):
        """Test that connection errors have expected structure."""
        from bantz.llm.base import LLMConnectionError
        
        # Simulate connection error
        try:
            raise LLMConnectionError("Connection failed to http://localhost:8000")
        except LLMConnectionError as e:
            assert "Connection failed" in str(e)
    
    def test_timeout_error_structure(self):
        """Test that timeout errors have expected structure."""
        from bantz.llm.base import LLMTimeoutError
        
        try:
            raise LLMTimeoutError("Request timeout after 30s")
        except LLMTimeoutError as e:
            assert "timeout" in str(e).lower()
    
    def test_rate_limit_error_structure(self):
        """Test that rate limit errors have expected structure."""
        # Note: We don't have a specific RateLimitError yet
        # This test documents the expected structure
        
        error_response = {
            "error": {
                "type": "rate_limit_error",
                "message": "Rate limit exceeded",
                "retry_after": 60,
            }
        }
        
        assert error_response["error"]["type"] == "rate_limit_error"
        assert "retry_after" in error_response["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
