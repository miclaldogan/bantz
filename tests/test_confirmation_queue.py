"""
Tests for Issue #351: Confirmation queue for multiple destructive tools.

Validates that multiple confirmations are queued and handled sequentially.
"""

import pytest
from unittest.mock import Mock, patch

from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig, OrchestratorState
from bantz.brain.llm_router import OrchestratorOutput
from bantz.plugins.base import Tool


@pytest.fixture
def orchestrator_loop():
    """Create OrchestratorLoop for testing confirmation queue."""
    mock_orchestrator = Mock()
    mock_event_bus = Mock()

    tools = {
        "calendar.create_event": Tool(
            name="calendar.create_event",
            description="Create calendar event",
            parameters={"title": {"type": "string"}},
            function=Mock(return_value={"ok": True}),
        ),
        "calendar.delete_event": Tool(
            name="calendar.delete_event",
            description="Delete calendar event",
            parameters={"event_id": {"type": "string"}},
            function=Mock(return_value={"ok": True}),
        ),
        "gmail.send": Tool(
            name="gmail.send",
            description="Send email",
            parameters={"to": {"type": "string"}},
            function=Mock(return_value={"ok": True}),
        ),
    }

    return OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=tools,
        event_bus=mock_event_bus,
        config=OrchestratorConfig(enable_safety_guard=False, debug=True),
    )


class TestConfirmationQueue:
    """Tests for pending confirmation queue behavior."""

    @patch("bantz.tools.metadata.requires_confirmation", return_value=True)
    @patch("bantz.tools.metadata.get_confirmation_prompt", return_value="Confirm?")
    @patch("bantz.tools.metadata.get_tool_risk")
    def test_multiple_confirmations_are_queued(
        self,
        mock_get_risk,
        _mock_prompt,
        _mock_requires,
        orchestrator_loop,
    ):
        """All destructive tools should be queued in order, only first prompt shown."""
        from bantz.tools.metadata import ToolRisk

        mock_get_risk.return_value = ToolRisk.DESTRUCTIVE

        state = OrchestratorState()
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots={"title": "Toplantı"},
            confidence=0.9,
            tool_plan=["calendar.create_event", "calendar.delete_event", "gmail.send"],
            assistant_reply="",
            requires_confirmation=True,
        )

        results = orchestrator_loop._execute_tools_phase(output, state)

        # Only a pending confirmation placeholder should be returned
        assert len(results) == 1
        assert results[0]["pending_confirmation"] is True
        assert results[0]["tool"] == "calendar.create_event"

        # All confirmations should be queued in order
        assert state.has_pending_confirmation() is True
        assert len(state.pending_confirmations) == 3
        assert state.pending_confirmations[0]["tool"] == "calendar.create_event"
        assert state.pending_confirmations[1]["tool"] == "calendar.delete_event"
        assert state.pending_confirmations[2]["tool"] == "gmail.send"

    @patch("bantz.tools.metadata.requires_confirmation", return_value=True)
    @patch("bantz.tools.metadata.get_confirmation_prompt", return_value="Confirm?")
    @patch("bantz.tools.metadata.get_tool_risk")
    def test_confirmed_tool_executes_and_queue_advances(
        self,
        mock_get_risk,
        _mock_prompt,
        _mock_requires,
        orchestrator_loop,
    ):
        """Confirmed tool executes; remaining confirmations stay in queue."""
        from bantz.tools.metadata import ToolRisk

        mock_get_risk.return_value = ToolRisk.DESTRUCTIVE

        state = OrchestratorState()
        state.pending_confirmations = [
            {"tool": "calendar.create_event", "prompt": "Confirm?", "slots": {}, "risk_level": "destructive"},
            {"tool": "calendar.delete_event", "prompt": "Confirm?", "slots": {}, "risk_level": "destructive"},
        ]
        state.confirmed_tool = "calendar.create_event"

        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots={"title": "Toplantı"},
            confidence=0.9,
            tool_plan=["calendar.create_event", "calendar.delete_event"],
            assistant_reply="",
            requires_confirmation=True,
        )

        results = orchestrator_loop._execute_tools_phase(output, state)

        # Confirmed tool should execute
        assert len(results) == 1
        assert results[0]["tool"] == "calendar.create_event"
        assert results[0]["success"] is True

        # Queue should advance (first removed, second remains)
        assert len(state.pending_confirmations) == 1
        assert state.pending_confirmations[0]["tool"] == "calendar.delete_event"