"""
Tests for Issue #350: Confirmation pending should block all tool execution.

Security-critical test: ensures that when a confirmation is pending,
NO other tools can be executed until the user confirms or denies.
"""

import pytest
from unittest.mock import Mock, MagicMock
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig, OrchestratorState
from bantz.brain.llm_router import OrchestratorOutput
from bantz.plugins.base import Tool


@pytest.fixture
def orchestrator_loop():
    """Create OrchestratorLoop with mocked tools."""
    mock_orchestrator = Mock()
    mock_event_bus = Mock()
    
    # Create mock tools
    safe_tool = Tool(
        name="time.now",
        description="Get current time",
        parameters={},
        function=Mock(return_value="2024-01-15 10:00:00"),
    )
    
    destructive_tool = Tool(
        name="calendar.delete_event",
        description="Delete calendar event",
        parameters={"event_id": {"type": "string"}},
        function=Mock(return_value={"ok": True, "deleted": "event_123"}),
    )
    
    tools = {
        "time.now": safe_tool,
        "calendar.delete_event": destructive_tool,
    }
    
    return OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=tools,
        event_bus=mock_event_bus,
        config=OrchestratorConfig(enable_safety_guard=False, debug=True),
    )


class TestConfirmationPendingBlocksTools:
    """Test that pending confirmation blocks ALL tool execution (Issue #350)."""
    
    def test_pending_confirmation_blocks_all_tools(self, orchestrator_loop):
        """
        When confirmation is pending, NO tools should execute.
        
        Security-critical: prevents executing unrelated tools while
        waiting for confirmation of a destructive operation.
        """
        state = OrchestratorState()
        
        # Set pending confirmation for calendar.delete_event
        state.set_pending_confirmation({
            "tool": "calendar.delete_event",
            "prompt": "Delete event 'Meeting' on 2024-01-15?",
            "slots": {"event_id": "event_123"},
            "risk_level": "high",
        })
        
        # Try to execute a safe tool (time.now)
        output = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["time.now"],
            assistant_reply="",
        )
        
        # Execute tools phase
        results = orchestrator_loop._execute_tools_phase(output, state)
        
        # Should NOT execute time.now - blocked by pending confirmation
        assert len(results) == 1
        assert results[0]["tool"] == "blocked"
        assert results[0]["success"] is False
        assert "confirmation required" in results[0]["error"].lower()
        assert results[0]["pending_confirmation"] is True
        
        # Verify time.now was NOT called
        time_tool = orchestrator_loop.tools["time.now"]
        assert time_tool.function.call_count == 0
    
    def test_multiple_tools_all_blocked_when_confirmation_pending(self, orchestrator_loop):
        """Multiple tools in tool_plan should ALL be blocked when confirmation pending."""
        state = OrchestratorState()
        
        # Set pending confirmation
        state.set_pending_confirmation({
            "tool": "calendar.delete_event",
            "prompt": "Delete event?",
            "slots": {"event_id": "event_123"},
            "risk_level": "high",
        })
        
        # Try to execute multiple tools
        output = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["time.now", "time.now", "time.now"],
            assistant_reply="",
        )
        
        results = orchestrator_loop._execute_tools_phase(output, state)
        
        # Should return single "blocked" result, not execute any tools
        assert len(results) == 1
        assert results[0]["tool"] == "blocked"
        assert results[0]["success"] is False
        
        # Verify NO tools were executed
        time_tool = orchestrator_loop.tools["time.now"]
        assert time_tool.function.call_count == 0
    
    def test_tools_execute_normally_when_no_pending_confirmation(self, orchestrator_loop):
        """When no confirmation is pending, tools should execute normally."""
        state = OrchestratorState()
        
        # NO pending confirmation
        assert not state.has_pending_confirmation()
        
        output = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["time.now"],
            assistant_reply="",
        )
        
        results = orchestrator_loop._execute_tools_phase(output, state)
        
        # Should execute successfully
        assert len(results) == 1
        assert results[0]["tool"] == "time.now"
        assert results[0]["success"] is True
        
        # Verify tool was called
        time_tool = orchestrator_loop.tools["time.now"]
        assert time_tool.function.call_count == 1
    
    def test_empty_tool_plan_returns_empty_results(self, orchestrator_loop):
        """Empty tool_plan should return empty results (edge case)."""
        state = OrchestratorState()
        
        output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="",
        )
        
        results = orchestrator_loop._execute_tools_phase(output, state)
        
        assert results == []
    
    def test_confirmation_prompt_included_in_blocked_result(self, orchestrator_loop):
        """Blocked result should include the pending confirmation prompt."""
        state = OrchestratorState()
        
        confirmation_prompt = "Delete event 'Important Meeting' on Jan 15, 2024 at 10:00 AM?"
        state.set_pending_confirmation({
            "tool": "calendar.delete_event",
            "prompt": confirmation_prompt,
            "slots": {"event_id": "event_456"},
            "risk_level": "high",
        })
        
        output = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=["time.now"],
            assistant_reply="",
        )
        
        results = orchestrator_loop._execute_tools_phase(output, state)
        
        # Should include confirmation prompt in result
        assert len(results) == 1
        assert results[0]["confirmation_prompt"] == confirmation_prompt
        assert confirmation_prompt in results[0]["error"]


class TestConfirmationClearAfterExecution:
    """Test that confirmation is cleared after tool execution (not part of #350 but related)."""
    
    def test_confirmation_cleared_after_execution(self, orchestrator_loop):
        """
        After confirming and executing a tool, pending confirmation should be cleared.
        
        This test verifies the existing behavior - not part of #350 fix but important
        for understanding the confirmation lifecycle.
        """
        # This test would need to mock the confirmation firewall flow
        # For now, we just document expected behavior
        pass  # TODO: Add integration test for full confirmation flow
