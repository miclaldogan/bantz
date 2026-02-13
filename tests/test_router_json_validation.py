"""Tests for Issue #228: Router JSON validation and repair.

Tests the ORCHESTRATOR_OUTPUT_SCHEMA validation and json repair pipeline.
"""

from __future__ import annotations

import pytest

from bantz.brain.json_protocol import (
    ORCHESTRATOR_FALLBACK_DEFAULTS,
    ORCHESTRATOR_OUTPUT_SCHEMA,
    apply_orchestrator_defaults,
    extract_first_json_object,
    repair_common_json_issues,
    validate_orchestrator_output,
)


class TestOrchestratorOutputSchema:
    """Tests for ORCHESTRATOR_OUTPUT_SCHEMA."""

    def test_schema_has_required_fields(self) -> None:
        """Schema should define required fields."""
        assert "required" in ORCHESTRATOR_OUTPUT_SCHEMA
        required = ORCHESTRATOR_OUTPUT_SCHEMA["required"]
        assert "route" in required
        assert "calendar_intent" in required
        assert "confidence" in required
        assert "tool_plan" in required
        assert "assistant_reply" in required

    def test_schema_route_enum(self) -> None:
        """Route should be enum of valid routes."""
        route_prop = ORCHESTRATOR_OUTPUT_SCHEMA["properties"]["route"]
        assert route_prop["enum"] == ["calendar", "gmail", "smalltalk", "system", "unknown"]

    def test_schema_confidence_range(self) -> None:
        """Confidence should be 0.0-1.0."""
        conf_prop = ORCHESTRATOR_OUTPUT_SCHEMA["properties"]["confidence"]
        assert conf_prop["minimum"] == 0.0
        assert conf_prop["maximum"] == 1.0


class TestValidateOrchestratorOutput:
    """Tests for validate_orchestrator_output function."""

    def test_valid_output(self) -> None:
        """Valid output should pass validation."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "14:00"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "",
        }
        is_valid, errors = validate_orchestrator_output(parsed)
        assert is_valid is True
        assert errors == []

    def test_missing_required_field(self) -> None:
        """Missing required field should fail."""
        parsed = {
            "route": "calendar",
            # missing calendar_intent
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "",
        }
        is_valid, errors = validate_orchestrator_output(parsed)
        assert is_valid is False
        assert any("calendar_intent" in e for e in errors)

    def test_invalid_route(self) -> None:
        """Invalid route should fail."""
        parsed = {
            "route": "invalid_route",
            "calendar_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "",
        }
        is_valid, errors = validate_orchestrator_output(parsed)
        assert is_valid is False
        assert any("invalid_route" in e for e in errors)

    def test_confidence_out_of_range(self) -> None:
        """Confidence out of range should fail."""
        parsed = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 1.5,  # Out of range
            "tool_plan": [],
            "assistant_reply": "",
        }
        is_valid, errors = validate_orchestrator_output(parsed)
        assert is_valid is False
        assert any("confidence_out_of_range" in e for e in errors)

    def test_tool_plan_not_array(self) -> None:
        """Tool plan should be array."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.8,
            "tool_plan": "calendar.list_events",  # Should be array
            "assistant_reply": "",
        }
        is_valid, errors = validate_orchestrator_output(parsed)
        assert is_valid is False
        assert any("tool_plan_not_array" in e for e in errors)

    def test_slots_not_dict(self) -> None:
        """Slots should be dict."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": ["time", "14:00"],  # Should be dict
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "",
        }
        is_valid, errors = validate_orchestrator_output(parsed)
        assert is_valid is False
        assert any("slots_not_dict" in e for e in errors)

    def test_not_dict(self) -> None:
        """Non-dict should fail."""
        is_valid, errors = validate_orchestrator_output([1, 2, 3])  # type: ignore
        assert is_valid is False
        assert "output_not_dict" in errors


class TestApplyOrchestratorDefaults:
    """Tests for apply_orchestrator_defaults function."""

    def test_complete_output_unchanged(self) -> None:
        """Complete output should remain unchanged."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"date": "2024-01-15"},
            "confidence": 0.85,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "Takvime bakıyorum.",
        }
        result = apply_orchestrator_defaults(parsed)
        assert result["route"] == "calendar"
        assert result["calendar_intent"] == "query"
        assert result["confidence"] == 0.85
        assert result["tool_plan"] == ["calendar.list_events"]

    def test_missing_fields_filled(self) -> None:
        """Missing fields should be filled with defaults."""
        parsed = {
            "route": "smalltalk",
            "assistant_reply": "Merhaba!",
        }
        result = apply_orchestrator_defaults(parsed)
        assert result["route"] == "smalltalk"
        assert result["calendar_intent"] == "none"
        assert result["confidence"] == 0.0
        assert result["tool_plan"] == []
        assert result["slots"] == {}

    def test_invalid_route_normalized(self) -> None:
        """Invalid route should be normalized to 'unknown'."""
        parsed = {
            "route": "invalid_route_name",
            "calendar_intent": "none",
            "confidence": 0.5,
            "tool_plan": [],
            "assistant_reply": "",
        }
        result = apply_orchestrator_defaults(parsed)
        assert result["route"] == "unknown"

    def test_confidence_clamped(self) -> None:
        """Confidence should be clamped to 0.0-1.0."""
        # Test above 1.0
        result = apply_orchestrator_defaults({"confidence": 1.5})
        assert result["confidence"] == 1.0
        
        # Test below 0.0
        result = apply_orchestrator_defaults({"confidence": -0.5})
        assert result["confidence"] == 0.0

    def test_invalid_confidence_type(self) -> None:
        """Invalid confidence type should default to 0.0."""
        result = apply_orchestrator_defaults({"confidence": "high"})
        assert result["confidence"] == 0.0

    def test_non_dict_input(self) -> None:
        """Non-dict input should return all defaults."""
        result = apply_orchestrator_defaults("not a dict")  # type: ignore
        assert result == ORCHESTRATOR_FALLBACK_DEFAULTS

    def test_tool_plan_not_list_fixed(self) -> None:
        """Non-list tool_plan should be fixed to empty list."""
        result = apply_orchestrator_defaults({"tool_plan": "single_tool"})
        assert result["tool_plan"] == []

    def test_slots_not_dict_fixed(self) -> None:
        """Non-dict slots should be fixed to empty dict."""
        result = apply_orchestrator_defaults({"slots": ["invalid"]})
        assert result["slots"] == {}


class TestRepairCommonJsonIssues:
    """Tests for repair_common_json_issues function."""

    def test_valid_json_unchanged(self) -> None:
        """Valid JSON should remain unchanged."""
        text = '{"route": "calendar", "confidence": 0.9}'
        result = repair_common_json_issues(text)
        assert '"route"' in result
        assert '"confidence"' in result

    def test_remove_markdown_code_block(self) -> None:
        """Markdown code blocks should be removed."""
        text = '```json\n{"route": "calendar"}\n```'
        result = repair_common_json_issues(text)
        assert "```" not in result
        assert '{"route"' in result

    def test_fix_trailing_comma_object(self) -> None:
        """Trailing commas in objects should be fixed."""
        text = '{"route": "calendar", "confidence": 0.9,}'
        result = repair_common_json_issues(text)
        assert ",}" not in result

    def test_fix_trailing_comma_array(self) -> None:
        """Trailing commas in arrays should be fixed."""
        text = '{"tool_plan": ["a", "b",]}'
        result = repair_common_json_issues(text)
        assert ",]" not in result

    def test_extract_json_from_text(self) -> None:
        """JSON should be extracted from surrounding text."""
        text = 'Here is my response: {"route": "calendar"} Thank you!'
        result = repair_common_json_issues(text)
        assert result.startswith("{")
        assert result.endswith("}")

    def test_empty_input(self) -> None:
        """Empty input should return empty."""
        assert repair_common_json_issues("") == ""
        assert repair_common_json_issues(None) is None  # type: ignore


class TestRouterJsonParsing:
    """Integration tests for router JSON parsing."""

    @pytest.fixture
    def mock_llm(self) -> object:
        """Create a mock LLM that returns JSON."""
        class MockLLM:
            def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
                return '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 0.9, "tool_plan": [], "assistant_reply": "Merhaba!"}'
        return MockLLM()

    def test_parse_clean_json(self, mock_llm: object) -> None:
        """Clean JSON should parse correctly."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        router = JarvisLLMOrchestrator(llm=mock_llm)
        result, _repaired = router._parse_json('{"route": "calendar", "calendar_intent": "query", "confidence": 0.8, "tool_plan": [], "assistant_reply": ""}')
        
        assert result["route"] == "calendar"
        assert result["confidence"] == 0.8

    def test_parse_json_with_markdown(self, mock_llm: object) -> None:
        """JSON with markdown wrapper should parse."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        router = JarvisLLMOrchestrator(llm=mock_llm)
        text = '```json\n{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [], "assistant_reply": "Hi"}\n```'
        result, _repaired = router._parse_json(text)
        
        assert result["route"] == "smalltalk"

    def test_parse_json_with_preamble(self, mock_llm: object) -> None:
        """JSON with text preamble should parse."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        router = JarvisLLMOrchestrator(llm=mock_llm)
        text = 'Here is my response:\n{"route": "gmail", "calendar_intent": "none", "confidence": 0.7, "tool_plan": [], "assistant_reply": ""}'
        result, _repaired = router._parse_json(text)
        
        assert result["route"] == "gmail"

    def test_extract_output_with_defaults(self, mock_llm: object) -> None:
        """Extract output should apply defaults for missing fields."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        router = JarvisLLMOrchestrator(llm=mock_llm)
        parsed = {"route": "calendar", "confidence": 0.8}
        result = router._extract_output(parsed, raw_text="")
        
        assert result.route == "calendar"
        assert result.calendar_intent == "none"  # Default
        assert result.confidence == 0.8
        assert result.tool_plan == []  # Default
        assert result.slots == {}  # Default


class TestFallbackDefaults:
    """Tests for ORCHESTRATOR_FALLBACK_DEFAULTS."""

    def test_fallback_has_all_fields(self) -> None:
        """Fallback defaults should have all expected fields."""
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["route"] == "smalltalk"
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["calendar_intent"] == "none"
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["confidence"] == 0.0
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["tool_plan"] == []
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["slots"] == {}
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["assistant_reply"] == ""
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["ask_user"] is False
        assert ORCHESTRATOR_FALLBACK_DEFAULTS["requires_confirmation"] is False
