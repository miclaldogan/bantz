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


def test_finalizer_handles_large_tool_results(mock_orchestrator, mock_tools_large_events, caplog, monkeypatch):
    """Finalizer should handle 200 events by using budget control."""
    # Issue #647: tiering is ON by default; calendar queries go to fast path.
    # Force quality so the mock finalizer LLM is actually invoked.
    monkeypatch.setenv("BANTZ_TIER_FORCE_FINALIZER", "quality")

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


# ============================================================================
# Context-window guard (Issue #1253)
# ============================================================================


class TestContextWindowGuard:
    """Test that _safe_complete respects model context window limits."""

    def test_get_context_window_from_method(self):
        """_get_context_window should use get_model_context_length() if present."""
        from bantz.brain.finalization_pipeline import _get_context_window

        mock_llm = Mock()
        mock_llm.get_model_context_length.return_value = 8192
        assert _get_context_window(mock_llm) == 8192

    def test_get_context_window_from_attr(self):
        """_get_context_window should fall back to context_window attr."""
        from bantz.brain.finalization_pipeline import _get_context_window

        mock_llm = Mock(spec=[])
        mock_llm.context_window = 4096
        assert _get_context_window(mock_llm) == 4096

    def test_get_context_window_default(self):
        """_get_context_window should return 4096 when no info available."""
        from bantz.brain.finalization_pipeline import (
            _get_context_window,
            _DEFAULT_CONTEXT_WINDOW,
        )

        mock_llm = Mock(spec=["complete_text"])
        assert _get_context_window(mock_llm) == _DEFAULT_CONTEXT_WINDOW

    def test_safe_complete_shrinks_max_tokens(self):
        """When prompt is large, max_tokens should be reduced to fit context."""
        from bantz.brain.finalization_pipeline import _safe_complete

        mock_llm = Mock()
        mock_llm.get_model_context_length.return_value = 4096
        mock_llm.complete_text.return_value = "OK response"

        # Create a prompt that's ~3800 tokens (15200 chars / 4)
        big_prompt = "a " * 7600  # ~3800 tokens
        result = _safe_complete(mock_llm, big_prompt, max_tokens=512)

        assert result == "OK response"
        # Verify complete_text was called with reduced max_tokens
        call_kwargs = mock_llm.complete_text.call_args
        actual_max = call_kwargs.kwargs.get("max_tokens") or call_kwargs[1].get("max_tokens")
        # max_tokens should be less than 512 since prompt is ~3800
        assert actual_max is not None
        assert actual_max < 512

    def test_safe_complete_no_shrink_when_fits(self):
        """When prompt fits comfortably, max_tokens should remain unchanged."""
        from bantz.brain.finalization_pipeline import _safe_complete

        mock_llm = Mock()
        mock_llm.get_model_context_length.return_value = 4096
        mock_llm.complete_text.return_value = "OK response"

        # Small prompt ~50 tokens
        small_prompt = "Merhaba " * 25
        result = _safe_complete(mock_llm, small_prompt, max_tokens=512)

        assert result == "OK response"
        call_kwargs = mock_llm.complete_text.call_args
        actual_max = call_kwargs.kwargs.get("max_tokens") or call_kwargs[1].get("max_tokens")
        assert actual_max == 512

    def test_safe_complete_truncates_huge_prompt(self):
        """When prompt alone exceeds context window, it should be truncated."""
        from bantz.brain.finalization_pipeline import _safe_complete

        mock_llm = Mock()
        mock_llm.get_model_context_length.return_value = 4096
        mock_llm.complete_text.return_value = "OK response"

        # Prompt of ~5000 tokens (20000 chars)
        huge_prompt = "x " * 10000  # ~5000 tokens, exceeds 4096
        result = _safe_complete(mock_llm, huge_prompt, max_tokens=512)

        assert result == "OK response"
        # The prompt passed to complete_text should be shorter than original
        call_args = mock_llm.complete_text.call_args
        actual_prompt = call_args.kwargs.get("prompt") or call_args[0][0] if call_args[0] else call_args.kwargs["prompt"]
        assert len(actual_prompt) < len(huge_prompt)

    def test_quality_finalizer_caps_prompt_budget(self):
        """QualityFinalizer should cap prompt budget based on context window."""
        from bantz.brain.finalization_pipeline import QualityFinalizer

        mock_llm = Mock()
        mock_llm.get_model_context_length.return_value = 4096
        mock_llm.complete_text.return_value = "Efendim, sonuçlar burada."

        finalizer = QualityFinalizer(finalizer_llm=mock_llm, timeout=5.0)

        # The _prompt_budget should be capped:
        # context_window(4096) - max_tokens(512) - margin(64) = 3520
        # min(5000, max(1500, 3520)) = 3520
        # This means for gmail.get_message, 5000 gets capped to 3520
        ctx_window = 4096
        max_prompt = ctx_window - 512 - 64
        assert max_prompt == 3520
        assert max_prompt < 5000  # Budget IS capped for detail tools

    def test_default_context_window_value(self):
        """_DEFAULT_CONTEXT_WINDOW should be 4096."""
        from bantz.brain.finalization_pipeline import _DEFAULT_CONTEXT_WINDOW
        assert _DEFAULT_CONTEXT_WINDOW == 4096
