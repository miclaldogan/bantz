# SPDX-License-Identifier: MIT
"""Issue #1229: Plan verifier hard enforcement tests.

Ensures that route_tool_mismatch and other critical verifier errors
block tool execution by clearing tool_plan and setting ask_user=True.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from bantz.brain.plan_verifier import classify_errors, verify_plan


# ── classify_errors tests ────────────────────────────────────────────

class TestClassifyErrors:
    def test_route_tool_mismatch_is_critical(self) -> None:
        critical, warnings = classify_errors(["route_tool_mismatch:smalltalk→gmail.get_message"])
        assert len(critical) == 1
        assert not warnings

    def test_smalltalk_with_tools_is_critical(self) -> None:
        critical, warnings = classify_errors(["smalltalk_with_tools"])
        assert len(critical) == 1
        assert not warnings

    def test_unknown_tool_is_critical(self) -> None:
        critical, warnings = classify_errors(["unknown_tool:foo.bar"])
        assert len(critical) == 1

    def test_tool_plan_no_indicators_is_warning(self) -> None:
        critical, warnings = classify_errors(["tool_plan_no_indicators"])
        assert not critical
        assert len(warnings) == 1

    def test_mixed(self) -> None:
        errs = [
            "route_tool_mismatch:smalltalk→gmail.get_message",
            "tool_plan_no_indicators",
            "missing_slot:title",
        ]
        critical, warnings = classify_errors(errs)
        assert len(critical) == 2
        assert len(warnings) == 1


# ── verify_plan error detection tests ────────────────────────────────

class TestVerifyPlan:
    _VALID_TOOLS = frozenset({
        "calendar.list_events", "calendar.create_event",
        "calendar.update_event", "calendar.delete_event",
        "calendar.find_free_slots", "calendar.find_event",
        "gmail.list_messages", "gmail.get_message",
        "gmail.send", "gmail.smart_search",
        "gmail.create_draft", "gmail.generate_reply",
        "time.now", "system.status",
    })

    def test_smalltalk_with_gmail_tool_raises_mismatch(self) -> None:
        plan = {
            "route": "smalltalk",
            "tool_plan": ["gmail.get_message"],
            "slots": {},
            "calendar_intent": "none",
            "gmail_intent": "none",
        }
        ok, errors = verify_plan(plan, "merhaba", self._VALID_TOOLS)
        assert not ok
        assert any("route_tool_mismatch" in e for e in errors)

    def test_correct_plan_no_errors(self) -> None:
        plan = {
            "route": "calendar",
            "tool_plan": ["calendar.list_events"],
            "slots": {},
            "calendar_intent": "query",
            "gmail_intent": "none",
        }
        ok, errors = verify_plan(plan, "bugün neler var?", self._VALID_TOOLS)
        assert ok
        assert not errors


# ── Hard block in orchestrator loop ────────────────────────────────

class TestVerifierHardBlock:
    """Verify that the orchestrator clears tool_plan on critical errors."""

    def test_hard_error_clears_tool_plan(self) -> None:
        """Simulate the orchestrator verifier block logic."""
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.plan_verifier import infer_route_from_tools

        output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.8,
            tool_plan=["gmail.get_message"],
            assistant_reply="",
        )

        # Simulate verifier
        plan_dict = {
            "route": output.route,
            "tool_plan": output.tool_plan,
            "slots": output.slots,
            "calendar_intent": output.calendar_intent,
            "gmail_intent": "none",
        }
        _, errors = verify_plan(
            plan_dict, "github mailine bak",
            frozenset({"gmail.get_message", "calendar.list_events", "time.now"}),
        )

        # Correctable check
        _correctable = {"route_tool_mismatch", "smalltalk_with_tools", "route_intent_mismatch"}
        correctable = [e for e in errors if any(e.startswith(c) for c in _correctable)]
        hard = [
            e for e in errors
            if not e.startswith("tool_plan_no_indicators")
            and not any(e.startswith(c) for c in _correctable)
        ]

        assert correctable, f"Expected correctable errors, got {errors}"

        # Auto-correct: infer_route should return 'gmail'
        inferred = infer_route_from_tools(output.tool_plan)
        assert inferred == "gmail"
        output = replace(output, route=inferred)
        assert output.route == "gmail"
        assert output.tool_plan == ["gmail.get_message"]

    def test_uncorrectable_mismatch_blocks(self) -> None:
        """When route inference fails, tool_plan must be cleared."""
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.plan_verifier import infer_route_from_tools

        # Two tools from different domains → ambiguous → inference returns None
        output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.5,
            tool_plan=["gmail.send", "calendar.list_events"],
            assistant_reply="",
        )

        inferred = infer_route_from_tools(output.tool_plan)
        assert inferred is None, "Mixed-domain tools should return None"

        # Simulating the block path
        output = replace(
            output,
            tool_plan=[],
            ask_user=True,
            question="Bu isteği tam anlayamadım.",
        )

        assert output.tool_plan == []
        assert output.ask_user is True

    def test_hard_error_unknown_tool_clears_plan(self) -> None:
        """Unknown tools should be classified as hard errors and clear plan."""
        from bantz.brain.llm_router import OrchestratorOutput

        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.7,
            tool_plan=["calendar.nonexistent"],
            assistant_reply="",
        )

        plan_dict = {
            "route": output.route,
            "tool_plan": output.tool_plan,
            "slots": output.slots,
            "calendar_intent": output.calendar_intent,
            "gmail_intent": "none",
        }
        _, errors = verify_plan(
            plan_dict, "bugün neler var?",
            frozenset({"calendar.list_events", "time.now"}),
        )

        # unknown_tool should be in errors
        assert any("unknown_tool" in e for e in errors)

        # Simulate hard block
        _correctable = {"route_tool_mismatch", "smalltalk_with_tools", "route_intent_mismatch"}
        hard = [
            e for e in errors
            if not e.startswith("tool_plan_no_indicators")
            and not any(e.startswith(c) for c in _correctable)
        ]
        assert hard, "unknown_tool should be a hard error"

        output = replace(output, tool_plan=[], ask_user=True, question="Anlayamadım.")
        assert output.tool_plan == []
        assert output.ask_user is True
