"""Tests for Issue #634 — handler=None tools should not crash execution.

Tools registered with ``function=None`` (schema-only / declaration-only) must
not raise ``ValueError`` or ``TypeError`` during execution.  Instead, they
should produce a graceful error result and continue.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from bantz.agent.tools import Tool, ToolRegistry


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _registry_with_null_handler() -> ToolRegistry:
    """Registry containing one schema-only tool (function=None)."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="browser.open_url",
            description="Open a URL in the browser",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            function=None,
        )
    )
    return reg


def _registry_with_working_tool() -> ToolRegistry:
    """Registry with a tool that has a real handler."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="time.now",
            description="Get current time",
            parameters={"type": "object", "properties": {}, "required": []},
            function=lambda: {"ok": True, "time": "2025-07-13T10:00:00"},
        )
    )
    return reg


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestNullHandlerTool:
    """Verify Tool with function=None doesn't crash."""

    def test_tool_with_none_function_registered(self):
        """Schema-only tool can be registered."""
        reg = _registry_with_null_handler()
        tool = reg.get("browser.open_url")
        assert tool is not None
        assert tool.function is None

    def test_tool_with_none_function_validate_succeeds(self):
        """Schema validation should still work for schema-only tools."""
        reg = _registry_with_null_handler()
        ok, reason = reg.validate_call("browser.open_url", {"url": "https://example.com"})
        assert ok

    def test_null_handler_in_execute_tools_phase(self):
        """Orchestrator's _execute_tools_phase should NOT raise for null-handler tools.

        Instead, it should return a graceful error result in the tool_results list.
        """
        from bantz.brain.orchestrator_loop import (
            OrchestratorLoop,
            OrchestratorOutput,
            OrchestratorState,
        )

        # Build a minimal OrchestratorLoop with a schema-only tool
        reg = ToolRegistry()
        reg.register(
            Tool(
                name="calendar.list_events",
                description="List events (schema-only, no handler)",
                parameters={
                    "type": "object",
                    "properties": {"date": {"type": "string"}},
                    "required": [],
                },
                function=None,  # No handler!
            )
        )
        mock_orchestrator = MagicMock()

        loop = OrchestratorLoop(
            orchestrator=mock_orchestrator,
            tools=reg,
        )
        # Disable safety guard to test the null handler path directly
        loop.safety_guard = None

        output = OrchestratorOutput(
            route="calendar",
            assistant_reply="",
            tool_plan=["calendar.list_events"],
            requires_confirmation=False,
            calendar_intent="list_events",
            slots={"date": "bugün"},
            ask_user=False,
            question="",
            confidence=0.9,
        )

        state = OrchestratorState()

        # Should NOT raise — this was the original bug
        tool_results = loop._execute_tools_phase(output, state)

        assert len(tool_results) == 1
        result = tool_results[0]
        assert result["tool"] == "calendar.list_events"
        assert result["success"] is False
        assert "schema-only" in result.get("error", "").lower() or "kullanılamıyor" in result.get("user_message", "").lower()

    def test_working_tool_still_executes(self):
        """Real tools with handlers should still work normally."""
        reg = _registry_with_working_tool()
        tool = reg.get("time.now")
        assert tool is not None
        assert tool.function is not None
        result = tool.function()
        assert result["ok"] is True
