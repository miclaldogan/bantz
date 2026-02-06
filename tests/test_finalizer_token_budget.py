"""Test finalizer token budget control (Issue #354).

Issue #354: Finalizer prompts don't have token budget control for tool results,
causing context overflow when tool results are large (e.g., 100+ events).

Solution: Implement _prepare_tool_results_for_finalizer() that:
1. Tries using full raw_result (best quality)
2. Falls back to result_summary if budget exceeded
3. Further truncates if still too large
4. Returns warning flag for monitoring
"""

import pytest
import json
from unittest.mock import Mock, patch
from bantz.brain.orchestrator_loop import (
    OrchestratorLoop,
    OrchestratorConfig,
    _prepare_tool_results_for_finalizer,
)
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.agent.tools import ToolRegistry, Tool


# Test the _prepare_tool_results_for_finalizer helper

def test_small_results_use_raw_data():
    """Small tool results should use raw_result without truncation."""
    tool_results = [
        {
            "tool": "time.now",
            "success": True,
            "raw_result": {"time": "2024-01-15T10:30:00"},
            "result_summary": "{keys: ['time']} {\"time\": \"2024-01-15T10:30:00\"}",
            "error": None,
        }
    ]
    
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=2000)
    
    # Should use raw_result
    assert not truncated
    assert len(prepared) == 1
    assert prepared[0]["result"] == {"time": "2024-01-15T10:30:00"}


def test_large_results_use_summary():
    """Large tool results (exceeding budget) should use result_summary."""
    # Create a large event list
    large_events = [
        {
            "id": f"event_{i}",
            "title": f"Meeting {i}",
            "description": f"This is a very long description for meeting {i} " * 10,
            "start": f"2024-01-{i:02d}T10:00:00",
            "end": f"2024-01-{i:02d}T11:00:00",
            "attendees": [f"person{j}@example.com" for j in range(5)],
        }
        for i in range(1, 101)  # 100 events with lots of data
    ]
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": large_events,
            "result_summary": "[100 items, showing first 5] [{...}, {...}, ...]",
            "error": None,
        }
    ]
    
    # Raw result would be huge (10,000+ tokens), should use summary
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=500)
    
    # Should use summary instead of raw data
    assert truncated
    assert len(prepared) == 1
    # Result should be the summary, not the full list
    assert prepared[0]["result"] == "[100 items, showing first 5] [{...}, {...}, ...]"
    assert prepared[0]["result"] != large_events


def test_very_large_results_truncate_aggressively():
    """Very large results (even summaries too big) should truncate aggressively."""
    # Create many tools with large summaries
    tool_results = [
        {
            "tool": f"tool_{i}",
            "success": True,
            "raw_result": "x" * 10000,  # Huge raw data
            "result_summary": "x" * 500,  # Even summary is large
            "error": None,
        }
        for i in range(10)  # 10 tools
    ]
    
    # Budget is very small, should truncate to first 3 tools
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=100)
    
    assert truncated
    # Should only keep first 3 tools
    assert len(prepared) <= 3
    # Each result should be truncated
    for p in prepared:
        assert len(p["result"]) <= 203  # 200 + "..."


def test_empty_results():
    """Empty tool results should return empty list."""
    prepared, truncated = _prepare_tool_results_for_finalizer([], max_tokens=2000)
    
    assert prepared == []
    assert not truncated


def test_multiple_small_tools():
    """Multiple small tools should all fit within budget."""
    tool_results = [
        {
            "tool": "time.now",
            "success": True,
            "raw_result": {"time": "2024-01-15T10:30:00"},
            "result_summary": "...",
            "error": None,
        },
        {
            "tool": "calendar.get_free_busy",
            "success": True,
            "raw_result": {"busy": [], "free": [{"start": "09:00", "end": "17:00"}]},
            "result_summary": "...",
            "error": None,
        },
    ]
    
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=2000)
    
    # Should not need truncation
    assert not truncated
    assert len(prepared) == 2
    # Should use raw results
    assert prepared[0]["result"] == {"time": "2024-01-15T10:30:00"}
    assert "busy" in prepared[1]["result"]


# Integration tests with OrchestratorLoop

@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator for testing."""
    orchestrator = Mock(spec=JarvisLLMOrchestrator)
    orchestrator._llm = Mock()
    orchestrator._llm.model_name = "test-model"
    orchestrator._llm.backend_name = "test-backend"
    orchestrator._llm.complete_text = Mock(return_value="Efendim, takvim kontrolünü tamamladım.")
    return orchestrator


@pytest.fixture
def mock_tools_large_events():
    """Mock tool registry that returns 200 calendar events."""
    registry = ToolRegistry()
    
    def list_many_events():
        return [
            {
                "id": f"event_{i}",
                "title": f"Meeting {i}",
                "description": f"Long description for meeting {i} " * 20,  # Make it large
                "start": f"2024-01-{i%28+1:02d}T10:00:00",
                "end": f"2024-01-{i%28+1:02d}T11:00:00",
            }
            for i in range(1, 201)  # 200 events
        ]
    
    registry.register(
        Tool(
            name="calendar.list_events",
            description="List calendar events",
            function=list_many_events,
            parameters={},
        )
    )
    
    return registry


def test_finalizer_handles_large_tool_results(mock_orchestrator, mock_tools_large_events, caplog):
    """Finalizer should handle 200 events by using budget control."""
    config = OrchestratorConfig()
    
    # Create a mock finalizer LLM
    mock_finalizer = Mock()
    mock_finalizer.complete_text = Mock(return_value="Efendim, 200 etkinlik buldum.")
    mock_finalizer.model_name = "test-finalizer"
    mock_finalizer.backend_name = "test-backend"
    
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools_large_events,
        config=config,
        finalizer_llm=mock_finalizer,
    )
    
    # Mock orchestrator output with tool plan
    output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        confidence=0.9,
        tool_plan=["calendar.list_events"],
        assistant_reply="Checking your calendar...",
    )
    
    state = OrchestratorState()
    
    # Execute tools
    tool_results = loop._execute_tools_phase(output, state)
    
    # Verify tool execution succeeded
    assert len(tool_results) == 1
    assert tool_results[0]["success"] is True
    
    # Call finalization
    with caplog.at_level("INFO"):
        final_output = loop._llm_finalization_phase(
            user_input="Önümüzdeki ay ne toplantılarım var?",
            orchestrator_output=output,
            tool_results=tool_results,
            state=state,
        )
    
    # Verify finalizer was called successfully
    assert mock_finalizer.complete_text.called
    
    # Verify budget control triggered (should see truncation warning in logs)
    assert any("Tool results truncated" in record.message for record in caplog.records)
    
    # Get the prompt that was sent to finalizer
    call_args = mock_finalizer.complete_text.call_args
    if call_args.kwargs.get("prompt"):
        prompt = call_args.kwargs["prompt"]
    else:
        prompt = call_args.args[0]
    
    # The prompt should NOT contain all 200 events (truncated)
    # Count how many "event_" appear in the prompt
    event_count = prompt.count("event_")
    
    # Should be significantly less than 200 (budget control working)
    assert event_count < 50, f"Expected < 50 events in prompt, found {event_count}"


def test_fast_finalize_uses_budget_control(mock_orchestrator, mock_tools_large_events, caplog):
    """Fast finalize path should also use budget control."""
    config = OrchestratorConfig()
    
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools_large_events,
        config=config,
        finalizer_llm=None,  # No finalizer, will use fast path
    )
    
    output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        confidence=0.9,
        tool_plan=["calendar.list_events"],
        assistant_reply="Checking...",
    )
    
    state = OrchestratorState()
    
    # Execute tools
    tool_results = loop._execute_tools_phase(output, state)
    
    # Test the fast finalize path directly by checking if tool results would be prepared correctly
    # We can't easily test the full flow, but we can test that the preparation function
    # would truncate the results
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=1500)
    
    # Should have been truncated due to large size
    assert truncated
    
    # Should use summaries instead of raw data
    assert prepared[0]["result"] == tool_results[0]["result_summary"]


def test_budget_control_preserves_tool_metadata():
    """Budget control should preserve tool name, success, error even when truncating."""
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": ["x"] * 10000,  # Huge list
            "result_summary": "[10000 items, showing first 5] [...]",
            "error": None,
        }
    ]
    
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=100)
    
    assert truncated
    # Metadata should be preserved
    assert prepared[0]["tool"] == "calendar.list_events"
    assert prepared[0]["success"] is True
    assert prepared[0]["error"] is None


def test_failed_tool_not_affected_by_budget():
    """Failed tools (with error) should pass through budget control."""
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": False,
            "raw_result": None,
            "result_summary": "",
            "error": "Authentication failed",
        }
    ]
    
    prepared, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=2000)
    
    # Should not be truncated (error message is small)
    assert not truncated
    assert prepared[0]["success"] is False
    assert prepared[0]["error"] == "Authentication failed"
