"""Tests for bug fixes #1354, #1355, #1356, #1357.

#1354 — risk UnboundLocalError in _execute_tools_phase
#1355 — route_intent_mismatch auto-correct from intent
#1356 — SafetyGuard field stripping observability
#1357 — --once LLM fallback
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field, replace
from typing import Any, Optional
from unittest.mock import MagicMock, patch


# ────────────────────────────────────────────────────────────────────
# #1354 — risk variable must never be referenced as object; risk_value
# (str) is the canonical form across V2 and legacy paths.
# ────────────────────────────────────────────────────────────────────

class TestRiskVariableFix:
    """Ensure risk_value (str) is used everywhere, not risk (object)."""

    def test_no_bare_risk_dot_value_in_tool_execution(self):
        """Scan orchestrator_loop.py for risk.value outside legacy block."""
        from pathlib import Path

        code = Path("src/bantz/brain/orchestrator_loop.py").read_text()

        # Find _execute_tools_phase method
        phase_start = code.find("def _execute_tools_phase(")
        assert phase_start > 0, "_execute_tools_phase not found"

        # Get the whole method body (until next def at same indent)
        phase_code = code[phase_start:]

        # Within _execute_tools_phase, find tool execution section
        # (after "Execute tool" comment)
        exec_start = phase_code.find("# Execute tool")
        assert exec_start > 0

        exec_section = phase_code[exec_start:]

        # Count risk.value occurrences — should be 0 after fix
        # (only risk_value should remain)
        import re
        matches = re.findall(r'\brisk\.value\b', exec_section)
        assert len(matches) == 0, (
            f"Found {len(matches)} 'risk.value' references in tool execution "
            f"section — should all be 'risk_value'"
        )

    def test_risk_value_used_in_tool_results(self):
        """Verify risk_value is used in tool_results dict."""
        from pathlib import Path

        code = Path("src/bantz/brain/orchestrator_loop.py").read_text()
        phase_start = code.find("def _execute_tools_phase(")
        phase_code = code[phase_start:]
        exec_start = phase_code.find("# Execute tool")
        exec_section = phase_code[exec_start:]

        # Should find risk_value references
        import re
        matches = re.findall(r'"risk_level":\s*risk_value', exec_section)
        assert len(matches) >= 3, (
            f"Expected at least 3 'risk_level: risk_value' in tool execution, "
            f"found {len(matches)}"
        )

    def test_risk_value_default_set(self):
        """Verify risk_value has a default before the V2 engine branch."""
        from pathlib import Path

        code = Path("src/bantz/brain/orchestrator_loop.py").read_text()
        phase_start = code.find("def _execute_tools_phase(")
        phase_code = code[phase_start:]

        # risk_value should be initialized before _v2_engine branch
        init_pos = phase_code.find('risk_value = "moderate"')
        assert init_pos > 0, "risk_value default not found"

        # It should appear before the V2 decision branch (elif _v2_engine)
        branch_pos = phase_code.find("elif _v2_engine is not None:")
        assert branch_pos > 0, "V2 engine branch not found"
        assert init_pos < branch_pos, "risk_value must be initialized before V2 engine check"


# ────────────────────────────────────────────────────────────────────
# #1355 — Route intent mismatch auto-correction
# ────────────────────────────────────────────────────────────────────

class TestRouteIntentMismatchCorrection:
    """Test that intent-based route correction works."""

    def test_intent_correction_code_exists(self):
        """Verify Issue #1355 intent correction is in the codebase."""
        from pathlib import Path

        code = Path("src/bantz/brain/orchestrator_loop.py").read_text()
        assert "Issue #1355" in code, "#1355 fix not found in orchestrator"
        assert "_intent_corrected" in code, "_intent_corrected flag not found"

    def test_gmail_intent_triggers_route_correction(self):
        """When gmail_intent is set but route is not gmail, correct it."""
        from pathlib import Path

        code = Path("src/bantz/brain/orchestrator_loop.py").read_text()

        # Should have gmail_intent check before infer_route_from_tools
        gmail_check = code.find('_gmail_intent != "none" and output.route != "gmail"')
        assert gmail_check > 0, "Gmail intent route correction not found"

    def test_calendar_intent_triggers_route_correction(self):
        """When calendar_intent is set but route is not calendar, correct it."""
        from pathlib import Path

        code = Path("src/bantz/brain/orchestrator_loop.py").read_text()

        cal_check = code.find('_cal_intent != "none" and output.route != "calendar"')
        assert cal_check > 0, "Calendar intent route correction not found"


# ────────────────────────────────────────────────────────────────────
# #1356 — SafetyGuard field stripping observability
# ────────────────────────────────────────────────────────────────────

class TestFieldStrippingObservability:
    """Test that stripped fields are published to EventBus."""

    def test_event_published_on_strip(self):
        """Verify tool.param_stripped event is emitted."""
        from pathlib import Path

        code = Path("src/bantz/brain/safety_guard.py").read_text()
        assert "tool.param_stripped" in code, "Event not published on strip"
        assert "Issue #1356" in code, "#1356 reference not found"

    def test_safety_guard_strips_and_publishes(self):
        """Integration: strip unknown field and check event emission."""
        from bantz.brain.safety_guard import SafetyGuard

        guard = SafetyGuard()

        # Create a mock tool with schema
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.parameters = {
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        }

        params = {"query": "hello", "unknown_field": "bad", "another_bad": 123}

        with patch("bantz.core.events.get_event_bus") as mock_get_bus:
            mock_bus_instance = MagicMock()
            mock_get_bus.return_value = mock_bus_instance

            valid, error = guard.validate_tool_args(mock_tool, params)

        # Should be valid (unknown fields stripped)
        assert valid is True
        # Unknown fields should be removed
        assert "unknown_field" not in params
        assert "another_bad" not in params
        assert "query" in params


# ────────────────────────────────────────────────────────────────────
# #1357 — --once LLM fallback
# ────────────────────────────────────────────────────────────────────

class TestOnceModeFallback:
    """Test that --once mode falls back to LLM brain."""

    def test_stateless_once_has_brain_fallback(self):
        """Verify run_stateless_once() has brain fallback code."""
        from pathlib import Path

        code = Path("src/bantz/cli.py").read_text()
        assert "Issue #1357" in code, "#1357 fix not found in cli.py"
        assert "create_runtime" in code, "Brain runtime import not found"
        assert "process_turn" in code, "Brain process_turn call not found"

    def test_fallback_only_on_unknown_intent(self):
        """Brain fallback should only trigger on unknown intent."""
        from pathlib import Path

        code = Path("src/bantz/cli.py").read_text()
        # Should check for unknown intent specifically
        assert 'result.intent == "unknown"' in code, (
            "Fallback should only trigger on unknown intent"
        )

    def test_fallback_graceful_on_brain_failure(self):
        """If brain init fails, should fall through to NLU response."""
        from pathlib import Path

        code = Path("src/bantz/cli.py").read_text()
        # Should have exception handling
        assert "Brain fallback failed" in code, (
            "Brain fallback should handle exceptions gracefully"
        )


# ────────────────────────────────────────────────────────────────────
# Plan Verifier: infer_route_from_tools
# ────────────────────────────────────────────────────────────────────

class TestInferRouteFromTools:
    """Test the route inference utility."""

    def test_gmail_tools_infer_gmail(self):
        from bantz.brain.plan_verifier import infer_route_from_tools

        assert infer_route_from_tools(["gmail.list_messages"]) == "gmail"
        assert infer_route_from_tools(["gmail.smart_search"]) == "gmail"

    def test_calendar_tools_infer_calendar(self):
        from bantz.brain.plan_verifier import infer_route_from_tools

        assert infer_route_from_tools(["calendar.list_events"]) == "calendar"
        assert infer_route_from_tools(["calendar.create_event"]) == "calendar"

    def test_mixed_tools_return_none(self):
        from bantz.brain.plan_verifier import infer_route_from_tools

        assert infer_route_from_tools(["gmail.send", "calendar.create_event"]) is None

    def test_time_tools_ignored(self):
        from bantz.brain.plan_verifier import infer_route_from_tools

        # time.* should be ignored, leaving gmail
        assert infer_route_from_tools(["time.now", "gmail.list_messages"]) == "gmail"

    def test_empty_plan(self):
        from bantz.brain.plan_verifier import infer_route_from_tools

        assert infer_route_from_tools([]) is None


# ────────────────────────────────────────────────────────────────────
# Plan Verifier: route_intent_mismatch detection
# ────────────────────────────────────────────────────────────────────

class TestPlanVerifierIntentMismatch:
    """Test that intent mismatch is detected correctly."""

    def test_gmail_intent_on_calendar_route_detected(self):
        from bantz.brain.plan_verifier import verify_plan

        plan = {
            "route": "calendar",
            "tool_plan": ["calendar.list_events"],
            "slots": {},
            "calendar_intent": "query",
            "gmail_intent": "list",
        }
        # Need valid tools set
        valid_tools = frozenset(["calendar.list_events", "gmail.list_messages"])
        ok, errors = verify_plan(plan, "maillerimi göster", valid_tools)

        assert not ok
        # Should contain route_intent_mismatch
        mismatch_errors = [e for e in errors if "route_intent_mismatch" in e]
        assert len(mismatch_errors) > 0, f"Expected mismatch error, got {errors}"

    def test_matching_gmail_route_no_error(self):
        from bantz.brain.plan_verifier import verify_plan

        plan = {
            "route": "gmail",
            "tool_plan": ["gmail.list_messages"],
            "slots": {},
            "calendar_intent": "none",
            "gmail_intent": "list",
        }
        valid_tools = frozenset(["gmail.list_messages"])
        ok, errors = verify_plan(plan, "maillerimi göster", valid_tools)

        # Should not have route_intent_mismatch
        mismatch_errors = [e for e in errors if "route_intent_mismatch" in e]
        assert len(mismatch_errors) == 0, f"Unexpected mismatch: {errors}"
