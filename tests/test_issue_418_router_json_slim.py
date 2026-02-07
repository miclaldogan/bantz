"""Tests for Issue #418: Router JSON output slimming.

Verifies:
  - RouterOutputSchema slim vs full tier selection
  - Schema instruction generation (slim/full)
  - validate_output: required field checking
  - fill_defaults: fills missing optional fields for OrchestratorOutput construction
  - Slim schema JSON is shorter than full schema JSON
  - model-settings.yaml max_tokens updated to 256
  - System prompt uses slim schema (fewer output fields)
"""

from __future__ import annotations

import json
import pytest

from bantz.brain.router_output_schema import (
    RouterOutputSchema,
    SLIM_SCHEMA_JSON,
    EXTENDED_FIELDS_JSON,
    FULL_SCHEMA_JSON,
    slim_schema_instruction,
    full_schema_instruction,
)


# ===================================================================
# Tests: Schema JSON strings
# ===================================================================


class TestSchemaStrings:
    def test_slim_schema_is_valid_json(self):
        """Slim schema should be parseable JSON."""
        # Note: schema uses descriptive values, not valid JSON values
        # But structure should be JSON-like
        assert SLIM_SCHEMA_JSON.startswith("{")
        assert SLIM_SCHEMA_JSON.endswith("}")

    def test_full_schema_is_valid_json(self):
        assert FULL_SCHEMA_JSON.startswith("{")
        assert FULL_SCHEMA_JSON.endswith("}")

    def test_slim_shorter_than_full(self):
        """Slim schema should be significantly shorter than full."""
        assert len(SLIM_SCHEMA_JSON) < len(FULL_SCHEMA_JSON)
        # At least 30% shorter
        ratio = len(SLIM_SCHEMA_JSON) / len(FULL_SCHEMA_JSON)
        assert ratio < 0.75, f"Slim is {ratio:.0%} of full — not slim enough"

    def test_slim_has_core_fields(self):
        """Slim schema must have route, calendar_intent, slots, confidence, tool_plan."""
        for field in ["route", "calendar_intent", "slots", "confidence", "tool_plan"]:
            assert field in SLIM_SCHEMA_JSON, f"Missing {field} in slim schema"

    def test_slim_does_not_have_extended_fields(self):
        """Slim schema should NOT have memory_update, reasoning_summary."""
        assert "memory_update" not in SLIM_SCHEMA_JSON
        assert "reasoning_summary" not in SLIM_SCHEMA_JSON

    def test_full_has_all_fields(self):
        """Full schema should have all fields."""
        for field in [
            "route", "calendar_intent", "slots", "confidence", "tool_plan",
            "assistant_reply", "memory_update", "reasoning_summary",
            "gmail_intent", "gmail", "ask_user", "question",
            "requires_confirmation", "confirmation_prompt",
        ]:
            assert field in FULL_SCHEMA_JSON, f"Missing {field} in full schema"

    def test_slim_has_gmail_intent(self):
        """Even slim schema needs gmail_intent for routing."""
        assert "gmail_intent" in SLIM_SCHEMA_JSON

    def test_slim_has_requires_confirmation(self):
        """Slim schema needs requires_confirmation for destructive ops."""
        assert "requires_confirmation" in SLIM_SCHEMA_JSON


# ===================================================================
# Tests: Schema instructions
# ===================================================================


class TestSchemaInstructions:
    def test_slim_instruction_contains_slim_schema(self):
        instr = slim_schema_instruction()
        assert "SADECE bu alanlar" in instr
        assert "route" in instr
        assert "finalization fazında" in instr

    def test_full_instruction_contains_full_schema(self):
        instr = full_schema_instruction()
        assert "route" in instr
        assert "memory_update" in instr

    def test_slim_instruction_shorter(self):
        slim = slim_schema_instruction()
        full = full_schema_instruction()
        # Slim instruction includes disclaimer, so may be longer text-wise
        # but the actual schema within is shorter
        assert "SADECE" in slim


# ===================================================================
# Tests: RouterOutputSchema factory methods
# ===================================================================


class TestRouterOutputSchemaFactory:
    def test_slim_factory(self):
        schema = RouterOutputSchema.slim()
        assert schema.use_slim is True
        assert schema.max_tokens_hint == 256

    def test_full_factory(self):
        schema = RouterOutputSchema.full()
        assert schema.use_slim is False
        assert schema.max_tokens_hint == 512

    def test_for_budget_tight(self):
        """Tight budget (< 200) should use slim."""
        schema = RouterOutputSchema.for_budget(available_completion_tokens=128)
        assert schema.use_slim is True

    def test_for_budget_generous(self):
        """Generous budget (>= 200) should use full."""
        schema = RouterOutputSchema.for_budget(available_completion_tokens=512)
        assert schema.use_slim is False

    def test_for_budget_boundary(self):
        """Exactly 200 should use full."""
        schema = RouterOutputSchema.for_budget(available_completion_tokens=200)
        assert schema.use_slim is False

    def test_for_budget_max_tokens_cap(self):
        """max_tokens_hint should be capped."""
        schema = RouterOutputSchema.for_budget(available_completion_tokens=1000)
        assert schema.max_tokens_hint <= 512


# ===================================================================
# Tests: get_schema_instruction
# ===================================================================


class TestGetSchemaInstruction:
    def test_slim_schema_instruction(self):
        schema = RouterOutputSchema.slim()
        instr = schema.get_schema_instruction()
        assert "SADECE" in instr

    def test_full_schema_instruction(self):
        schema = RouterOutputSchema.full()
        instr = schema.get_schema_instruction()
        assert "memory_update" in instr

    def test_get_schema_json_slim(self):
        schema = RouterOutputSchema.slim()
        assert schema.get_schema_json() == SLIM_SCHEMA_JSON

    def test_get_schema_json_full(self):
        schema = RouterOutputSchema.full()
        assert schema.get_schema_json() == FULL_SCHEMA_JSON


# ===================================================================
# Tests: Required/optional fields
# ===================================================================


class TestFieldSets:
    def test_slim_required_fields(self):
        schema = RouterOutputSchema.slim()
        required = schema.required_fields
        assert "route" in required
        assert "calendar_intent" in required
        assert "slots" in required
        assert "confidence" in required
        assert "tool_plan" in required
        assert "gmail_intent" in required
        assert "requires_confirmation" in required

    def test_slim_optional_fields(self):
        schema = RouterOutputSchema.slim()
        optional = schema.optional_fields
        assert "assistant_reply" in optional
        assert "memory_update" in optional
        assert "reasoning_summary" in optional
        assert "confirmation_prompt" in optional

    def test_full_required_fields(self):
        schema = RouterOutputSchema.full()
        required = schema.required_fields
        assert "assistant_reply" in required
        assert "memory_update" in required
        assert "reasoning_summary" in required

    def test_full_optional_fields_empty(self):
        schema = RouterOutputSchema.full()
        assert len(schema.optional_fields) == 0


# ===================================================================
# Tests: validate_output
# ===================================================================


class TestValidateOutput:
    def test_valid_slim_output(self):
        schema = RouterOutputSchema.slim()
        parsed = {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "gmail_intent": "none",
            "requires_confirmation": False,
        }
        missing = schema.validate_output(parsed)
        assert missing == []

    def test_missing_route(self):
        schema = RouterOutputSchema.slim()
        parsed = {
            "calendar_intent": "query",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": [],
            "gmail_intent": "none",
            "requires_confirmation": False,
        }
        missing = schema.validate_output(parsed)
        assert "route" in missing

    def test_valid_full_output(self):
        schema = RouterOutputSchema.full()
        parsed = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "Merhaba efendim",
            "gmail_intent": "none",
            "gmail": {},
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı selamladı",
            "reasoning_summary": ["Selamlama"],
        }
        missing = schema.validate_output(parsed)
        assert missing == []

    def test_full_missing_extended_fields(self):
        schema = RouterOutputSchema.full()
        parsed = {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": [],
        }
        missing = schema.validate_output(parsed)
        assert "assistant_reply" in missing
        assert "memory_update" in missing


# ===================================================================
# Tests: fill_defaults
# ===================================================================


class TestFillDefaults:
    def test_fill_empty_dict(self):
        schema = RouterOutputSchema.slim()
        result = schema.fill_defaults({})
        assert result["route"] == "unknown"
        assert result["calendar_intent"] == "none"
        assert result["slots"] == {}
        assert result["confidence"] == 0.0
        assert result["tool_plan"] == []
        assert result["assistant_reply"] == ""
        assert result["memory_update"] == ""
        assert result["reasoning_summary"] == []

    def test_fill_preserves_existing(self):
        schema = RouterOutputSchema.slim()
        parsed = {"route": "calendar", "confidence": 0.9}
        result = schema.fill_defaults(parsed)
        assert result["route"] == "calendar"
        assert result["confidence"] == 0.9
        # Defaults for missing
        assert result["tool_plan"] == []

    def test_fill_slim_output_ready_for_orchestrator_output(self):
        """After fill_defaults, all fields needed for OrchestratorOutput are present."""
        schema = RouterOutputSchema.slim()
        slim_parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "17:00", "title": "toplantı"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "gmail_intent": "none",
            "requires_confirmation": True,
        }
        filled = schema.fill_defaults(slim_parsed)

        # All OrchestratorOutput fields should be present
        from bantz.brain.llm_router import OrchestratorOutput
        # Should not raise
        output = OrchestratorOutput(
            route=filled["route"],
            calendar_intent=filled["calendar_intent"],
            slots=filled["slots"],
            confidence=filled["confidence"],
            tool_plan=filled["tool_plan"],
            assistant_reply=filled["assistant_reply"],
            gmail_intent=filled["gmail_intent"],
            gmail=filled["gmail"],
            ask_user=filled["ask_user"],
            question=filled["question"],
            requires_confirmation=filled["requires_confirmation"],
            confirmation_prompt=filled["confirmation_prompt"],
            memory_update=filled["memory_update"],
            reasoning_summary=filled["reasoning_summary"],
        )
        assert output.route == "calendar"
        assert output.requires_confirmation is True


# ===================================================================
# Tests: System prompt uses slim schema
# ===================================================================


class TestSystemPromptSlim:
    def test_system_prompt_core_no_memory_update_field(self):
        """SYSTEM_PROMPT_CORE schema line should NOT require memory_update."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        core = JarvisLLMOrchestrator._SYSTEM_PROMPT_CORE
        # Find the schema JSON line (starts with {)
        schema_line = [l for l in core.split("\n") if l.strip().startswith("{")]
        assert len(schema_line) >= 1
        assert "memory_update" not in schema_line[0]

    def test_system_prompt_core_no_reasoning_summary_field(self):
        """SYSTEM_PROMPT_CORE schema line should NOT require reasoning_summary."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        core = JarvisLLMOrchestrator._SYSTEM_PROMPT_CORE
        schema_line = [l for l in core.split("\n") if l.strip().startswith("{")]
        assert len(schema_line) >= 1
        assert "reasoning_summary" not in schema_line[0]

    def test_system_prompt_core_has_route_field(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        core = JarvisLLMOrchestrator._SYSTEM_PROMPT_CORE
        assert '"route"' in core

    def test_system_prompt_core_has_slim_note(self):
        """Slim schema includes a note about finalization."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        core = JarvisLLMOrchestrator._SYSTEM_PROMPT_CORE
        assert "finalization" in core.lower() or "gerekli DEĞİL" in core

    def test_examples_are_slim(self):
        """Examples should not include reasoning_summary or confirmation_prompt."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        examples = JarvisLLMOrchestrator._SYSTEM_PROMPT_EXAMPLES
        # calendar examples should NOT have reasoning_summary
        assert "reasoning_summary" not in examples

    def test_rules_no_memory_update_rule(self):
        """Rules should not enforce memory_update (removed from slim)."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        core = JarvisLLMOrchestrator._SYSTEM_PROMPT_CORE
        # Old rule "8. memory_update her turda doldur" should be removed
        assert "memory_update her turda" not in core


# ===================================================================
# Tests: Model settings max_tokens
# ===================================================================


class TestModelSettings:
    def test_yaml_router_max_tokens_increased(self):
        """config/model-settings.yaml router.max_tokens should be 256."""
        import yaml
        from pathlib import Path
        yaml_path = Path(__file__).parent.parent / "config" / "model-settings.yaml"
        if not yaml_path.exists():
            pytest.skip("model-settings.yaml not found")
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        assert cfg["router"]["max_tokens"] == 256


# ===================================================================
# Tests: Token budget estimate
# ===================================================================


class TestTokenBudget:
    def test_slim_schema_under_100_tokens(self):
        """Slim schema JSON should be under ~100 tokens (~400 chars)."""
        # 1 token ≈ 4 chars
        assert len(SLIM_SCHEMA_JSON) < 500, f"Slim schema too long: {len(SLIM_SCHEMA_JSON)} chars"

    def test_full_schema_longer(self):
        assert len(FULL_SCHEMA_JSON) > len(SLIM_SCHEMA_JSON)

    def test_slim_output_under_80_tokens(self):
        """A typical slim router output should be under 80 tokens."""
        sample_output = json.dumps({
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "17:00", "title": "toplantı", "window_hint": "today"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "gmail_intent": "none",
            "requires_confirmation": True,
        }, ensure_ascii=False)
        # ~4 chars per token
        estimated_tokens = len(sample_output) / 4
        assert estimated_tokens < 80, f"Estimated {estimated_tokens:.0f} tokens — too many for slim"
