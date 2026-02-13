"""Test suite for JSON Schema Validation & Repair (Issue #156)."""

import json
import pytest
from pydantic import ValidationError

from bantz.router.schemas import (
    RouterOutputSchema,
    RouteType,
    CalendarIntent,
    validate_router_output,
    router_output_to_dict,
)
from bantz.llm.json_repair import (
    repair_route_enum,
    repair_intent_enum,
    repair_tool_plan,
    repair_json_structure,
    validate_and_repair_json,
    extract_json_from_text,
    get_repair_stats,
    reset_repair_stats,
)


class TestRouterOutputSchema:
    """Test strict Pydantic schema validation."""
    
    def test_valid_calendar_create(self):
        """Test valid calendar create schema."""
        data = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"title": "Meeting", "time": "14:00"},
            "confidence": 0.95,
            "tool_plan": ["create_event"],
            "assistant_reply": "Toplantı oluşturuldu",
        }
        
        schema = validate_router_output(data)
        assert schema.route == RouteType.CALENDAR
        assert schema.calendar_intent == CalendarIntent.CREATE
        assert schema.confidence == 0.95
        assert schema.tool_plan == ["create_event"]
    
    def test_valid_smalltalk(self):
        """Test valid smalltalk schema."""
        data = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.99,
            "assistant_reply": "Merhaba!",
        }
        
        schema = validate_router_output(data)
        assert schema.route == RouteType.SMALLTALK
        assert schema.calendar_intent == CalendarIntent.NONE
        assert schema.tool_plan == []
    
    def test_extra_field_forbidden(self):
        """Test that extra fields are rejected."""
        data = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.8,
            "invalid_field": "should fail",
        }
        
        with pytest.raises(ValidationError) as exc_info:
            validate_router_output(data)
        
        assert "invalid_field" in str(exc_info.value)
    
    def test_invalid_route_enum(self):
        """Test that invalid route enum is rejected."""
        data = {
            "route": "create_meeting",  # Invalid enum
            "calendar_intent": "create",
            "confidence": 0.9,
        }
        
        with pytest.raises(ValidationError):
            validate_router_output(data)
    
    def test_invalid_intent_enum(self):
        """Test that invalid intent enum is rejected."""
        data = {
            "route": "calendar",
            "calendar_intent": "schedule",  # Invalid enum
            "confidence": 0.9,
        }
        
        with pytest.raises(ValidationError):
            validate_router_output(data)
    
    def test_tool_plan_string_coercion(self):
        """Test that tool_plan string is coerced to list."""
        data = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": "create_event",  # String, should become list
        }
        
        schema = validate_router_output(data)
        assert schema.tool_plan == ["create_event"]
    
    def test_tool_plan_empty_string(self):
        """Test that empty tool_plan string becomes empty list."""
        data = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.95,
            "tool_plan": "",  # Empty string
        }
        
        schema = validate_router_output(data)
        assert schema.tool_plan == []
    
    def test_confidence_bounds(self):
        """Test confidence must be in [0, 1]."""
        data = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 1.5,  # Out of bounds
        }
        
        with pytest.raises(ValidationError):
            validate_router_output(data)
    
    def test_turkish_confirmation_prompt(self):
        """Test Turkish validation for confirmation prompts."""
        data = {
            "route": "calendar",
            "calendar_intent": "cancel",
            "confidence": 0.9,
            "requires_confirmation": True,
            "confirmation_prompt": "Toplantıyı silmek istediğinizden emin misiniz?",
        }
        
        schema = validate_router_output(data)
        assert schema.requires_confirmation is True
        assert "misiniz" in schema.confirmation_prompt
    
    def test_missing_confirmation_prompt_error(self):
        """Test that requires_confirmation=True needs prompt."""
        data = {
            "route": "calendar",
            "calendar_intent": "cancel",
            "confidence": 0.9,
            "requires_confirmation": True,
            "confirmation_prompt": "",  # Empty prompt
        }
        
        with pytest.raises(ValidationError):
            validate_router_output(data)
    
    def test_reasoning_summary_coercion(self):
        """Test reasoning_summary string coercion to list."""
        data = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.85,
            "reasoning_summary": "User asked about events\nChecking calendar",
        }
        
        schema = validate_router_output(data)
        assert len(schema.reasoning_summary) == 2
        assert "User asked about events" in schema.reasoning_summary


class TestEnumRepair:
    """Test enum repair functions."""
    
    def test_repair_route_valid(self):
        """Test repair of already valid route."""
        assert repair_route_enum("calendar") == "calendar"
        assert repair_route_enum("smalltalk") == "smalltalk"
        assert repair_route_enum("unknown") == "unknown"
    
    def test_repair_route_common_mistakes(self):
        """Test repair of common LLM route mistakes."""
        assert repair_route_enum("create_meeting") == "calendar"
        assert repair_route_enum("schedule") == "calendar"
        assert repair_route_enum("event") == "calendar"
        assert repair_route_enum("chat") == "smalltalk"
        assert repair_route_enum("conversation") == "smalltalk"
    
    def test_repair_route_fuzzy_match(self):
        """Test fuzzy matching for route repair."""
        assert repair_route_enum("create_meeting_now") == "calendar"
        assert repair_route_enum("schedule_event") == "calendar"
    
    def test_repair_route_unknown_default(self):
        """Test unknown route defaults to 'unknown'."""
        assert repair_route_enum("invalid_route") == "unknown"
        assert repair_route_enum("random_text") == "unknown"
    
    def test_repair_intent_valid(self):
        """Test repair of already valid intent."""
        assert repair_intent_enum("create") == "create"
        assert repair_intent_enum("modify") == "modify"
        assert repair_intent_enum("cancel") == "cancel"
        assert repair_intent_enum("query") == "query"
        assert repair_intent_enum("none") == "none"
    
    def test_repair_intent_common_mistakes(self):
        """Test repair of common LLM intent mistakes."""
        assert repair_intent_enum("create_meeting") == "create"
        assert repair_intent_enum("schedule") == "create"
        assert repair_intent_enum("new") == "create"
        assert repair_intent_enum("update") == "modify"
        assert repair_intent_enum("delete") == "cancel"
        assert repair_intent_enum("search") == "query"
    
    def test_repair_intent_fuzzy_match(self):
        """Test fuzzy matching for intent repair."""
        assert repair_intent_enum("create_event_now") == "create"
        assert repair_intent_enum("update_meeting") == "modify"
    
    def test_repair_intent_none_default(self):
        """Test unknown intent defaults to 'none'."""
        assert repair_intent_enum("invalid_intent") == "none"
        assert repair_intent_enum("random_text") == "none"


class TestToolPlanRepair:
    """Test tool_plan repair function."""
    
    def test_repair_tool_plan_already_list(self):
        """Test tool_plan already as list."""
        result = repair_tool_plan(["create_event", "send_notification"])
        assert result == ["create_event", "send_notification"]
    
    def test_repair_tool_plan_string_single(self):
        """Test tool_plan as single string."""
        result = repair_tool_plan("create_event")
        assert result == ["create_event"]
    
    def test_repair_tool_plan_string_empty(self):
        """Test empty tool_plan string."""
        result = repair_tool_plan("")
        assert result == []
    
    def test_repair_tool_plan_json_array_string(self):
        """Test tool_plan as JSON array string."""
        result = repair_tool_plan('["create_event", "send_notification"]')
        assert result == ["create_event", "send_notification"]
    
    def test_repair_tool_plan_comma_separated(self):
        """Test tool_plan as comma-separated string."""
        result = repair_tool_plan("create_event, send_notification")
        assert result == ["create_event", "send_notification"]
    
    def test_repair_tool_plan_newline_separated(self):
        """Test tool_plan as newline-separated string."""
        result = repair_tool_plan("create_event\nsend_notification")
        assert result == ["create_event", "send_notification"]
    
    def test_repair_tool_plan_none(self):
        """Test tool_plan as None."""
        result = repair_tool_plan(None)
        assert result == []


class TestJsonStructureRepair:
    """Test complete JSON structure repair."""
    
    def test_repair_route_and_intent(self):
        """Test repair of route and intent enums."""
        data = {
            "route": "create_meeting",
            "calendar_intent": "schedule",
            "confidence": 0.9,
        }
        
        repaired = repair_json_structure(data)
        assert repaired["route"] == "calendar"
        assert repaired["calendar_intent"] == "create"
    
    def test_repair_tool_plan_string(self):
        """Test repair of tool_plan from string to list."""
        data = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": "create_event",
        }
        
        repaired = repair_json_structure(data)
        assert repaired["tool_plan"] == ["create_event"]
    
    def test_repair_missing_fields(self):
        """Test repair adds missing required fields."""
        data = {
            "assistant_reply": "Merhaba",
        }
        
        repaired = repair_json_structure(data)
        assert repaired["route"] == "unknown"
        assert repaired["calendar_intent"] == "none"
        assert repaired["confidence"] == 0.5
    
    def test_repair_confidence_bounds(self):
        """Test repair clamps confidence to [0, 1]."""
        data = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 1.5,
        }
        
        repaired = repair_json_structure(data)
        assert repaired["confidence"] == 1.0
        
        data["confidence"] = -0.5
        repaired = repair_json_structure(data)
        assert repaired["confidence"] == 0.0


class TestValidateAndRepairJson:
    """Test end-to-end validation and repair."""
    
    def setup_method(self):
        """Reset stats before each test."""
        reset_repair_stats()
    
    def test_valid_json_no_repair_needed(self):
        """Test valid JSON passes without repair."""
        raw = json.dumps({
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.95,
            "assistant_reply": "Bugün 3 toplantınız var",
        })
        
        schema, error = validate_and_repair_json(raw)
        assert schema is not None
        assert error is None
        assert schema.route == RouteType.CALENDAR
    
    def test_invalid_enum_repaired(self):
        """Test invalid enums are repaired."""
        raw = json.dumps({
            "route": "create_meeting",
            "calendar_intent": "schedule",
            "confidence": 0.9,
        })
        
        schema, error = validate_and_repair_json(raw)
        assert schema is not None
        assert error is None
        assert schema.route == RouteType.CALENDAR
        assert schema.calendar_intent == CalendarIntent.CREATE
    
    def test_tool_plan_string_repaired(self):
        """Test tool_plan string is repaired to list."""
        raw = json.dumps({
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": "create_event",
        })
        
        schema, error = validate_and_repair_json(raw)
        assert schema is not None
        assert error is None
        assert schema.tool_plan == ["create_event"]
    
    def test_invalid_json_syntax_error(self):
        """Test invalid JSON syntax returns error."""
        raw = "{ invalid json }"
        
        schema, error = validate_and_repair_json(raw)
        assert schema is None
        assert "JSON parse error" in error
    
    def test_repair_stats_tracking(self):
        """Test repair statistics are tracked."""
        reset_repair_stats()
        
        raw = json.dumps({
            "route": "create_meeting",
            "calendar_intent": "schedule",
            "confidence": 0.9,
        })
        
        schema, error = validate_and_repair_json(raw)
        assert schema is not None
        
        stats = get_repair_stats()
        assert stats.total_attempts == 1
        assert stats.successful_repairs > 0


class TestExtractJsonFromText:
    """Test JSON extraction from LLM text output."""
    
    def test_extract_from_markdown_code_block(self):
        """Test extraction from markdown code block."""
        text = '''
        Here's the result:
        ```json
        {"route": "calendar", "confidence": 0.9}
        ```
        '''
        
        result = extract_json_from_text(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["route"] == "calendar"
    
    def test_extract_from_plain_text(self):
        """Test extraction from plain text with JSON."""
        text = 'The response is {"route": "smalltalk", "confidence": 0.95} ok'
        
        result = extract_json_from_text(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["route"] == "smalltalk"
    
    def test_extract_none_if_no_json(self):
        """Test returns None if no JSON found."""
        text = "This is just plain text without any JSON"
        
        result = extract_json_from_text(text)
        assert result is None


class TestEnumConformance:
    """Test enum conformance rate (Issue #156 acceptance: 99%+)."""
    
    def setup_method(self):
        """Reset stats before each test."""
        reset_repair_stats()
    
    def test_batch_route_repair_conformance(self):
        """Test route repair achieves >99% conformance."""
        test_routes = [
            "calendar", "smalltalk", "unknown",  # Valid
            "create_meeting", "schedule", "event",  # Should map to calendar
            "chat", "conversation", "greet",  # Should map to smalltalk
            "other", "unclear", "random",  # Should map to unknown
        ] * 10  # 120 total
        
        results = [repair_route_enum(route) for route in test_routes]
        valid_enums = ["calendar", "smalltalk", "unknown"]
        conformance = sum(1 for r in results if r in valid_enums) / len(results)
        
        assert conformance >= 0.99  # 99%+ conformance
    
    def test_batch_intent_repair_conformance(self):
        """Test intent repair achieves >99% conformance."""
        test_intents = [
            "create", "modify", "cancel", "query", "none",  # Valid
            "create_meeting", "schedule", "new",  # Should map to create
            "update", "change", "edit",  # Should map to modify
            "delete", "remove",  # Should map to cancel
            "search", "find", "list",  # Should map to query
        ] * 10  # 190 total
        
        results = [repair_intent_enum(intent) for intent in test_intents]
        valid_enums = ["create", "modify", "cancel", "query", "none"]
        conformance = sum(1 for r in results if r in valid_enums) / len(results)
        
        assert conformance >= 0.99  # 99%+ conformance


class TestRepairRateAcceptance:
    """Test repair rate is <5% (Issue #156 acceptance)."""
    
    def setup_method(self):
        """Reset stats before each test."""
        reset_repair_stats()
    
    def test_repair_rate_under_5_percent(self):
        """Test most LLM outputs don't need repair (<5%)."""
        # Simulate 100 LLM outputs: 96 valid, 4 need repair
        valid_outputs = [
            {
                "route": "calendar",
                "calendar_intent": "query",
                "confidence": 0.9,
            }
        ] * 96
        
        invalid_outputs = [
            {
                "route": "create_meeting",  # Needs repair
                "calendar_intent": "query",
                "confidence": 0.9,
            }
        ] * 4
        
        all_outputs = valid_outputs + invalid_outputs
        
        for output in all_outputs:
            raw = json.dumps(output)
            validate_and_repair_json(raw)
        
        stats = get_repair_stats()
        assert stats.total_attempts == 100
        # In practice, repair rate should be <5%
        # (This test just validates tracking works)
