"""Test tool results structure preservation (Issue #353).

Issue #353: Tool results were losing structure when stringified with 
json.dumps() + [:2000] truncation. This broke nested objects and lost data.

Solution: Store both raw_result (original structured data) and result_summary 
(smart summary). Finalizer uses raw_result for full context.
"""

import pytest
from unittest.mock import Mock, patch
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig, _summarize_tool_result
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.agent.tools import ToolRegistry, Tool


# Test the _summarize_tool_result helper function

def test_summarize_empty_list():
    """Empty list should return '[]'."""
    result = _summarize_tool_result([])
    assert result == "[]"


def test_summarize_short_list():
    """Short list should return full JSON."""
    data = [1, 2, 3]
    result = _summarize_tool_result(data, max_items=5)
    assert result == "[1, 2, 3]"


def test_summarize_long_list():
    """Long list should show count + first N items."""
    data = list(range(50))  # [0, 1, 2, ..., 49]
    result = _summarize_tool_result(data, max_items=5)
    assert "[50 items, showing first 5]" in result
    assert "[0, 1, 2, 3, 4]" in result


def test_summarize_list_of_dicts():
    """List of event dicts should preserve structure for first N items."""
    events = [
        {"id": f"event_{i}", "title": f"Meeting {i}", "start": f"2024-01-{i:02d}"}
        for i in range(1, 51)
    ]
    result = _summarize_tool_result(events, max_items=3)
    
    assert "[50 items, showing first 3]" in result
    # First 3 events should be in the preview
    assert "event_1" in result
    assert "event_2" in result
    assert "event_3" in result
    # Later events should NOT be in preview
    assert "event_50" not in result


def test_summarize_empty_dict():
    """Empty dict should return '{}'."""
    result = _summarize_tool_result({})
    assert result == "{}"


def test_summarize_small_dict():
    """Small dict should show keys + full JSON."""
    data = {"name": "John", "age": 30}
    result = _summarize_tool_result(data)
    assert "{keys: ['name', 'age']}" in result
    assert '"name": "John"' in result
    assert '"age": 30' in result


def test_summarize_large_dict():
    """Large dict should truncate JSON but preserve keys."""
    # Create a dict with very long values
    data = {
        "key1": "x" * 1000,
        "key2": "y" * 1000,
    }
    result = _summarize_tool_result(data, max_chars=100)
    
    assert "{keys: ['key1', 'key2']}" in result
    assert "..." in result  # Truncation marker
    assert len(result) <= 150  # Should be reasonably short


def test_summarize_short_string():
    """Short string should return as-is."""
    result = _summarize_tool_result("Hello world")
    assert result == "Hello world"


def test_summarize_long_string():
    """Long string should truncate with char count."""
    long_str = "x" * 1000
    result = _summarize_tool_result(long_str, max_chars=100)
    
    assert result.startswith("x" * 100)
    assert "... (1000 chars total)" in result


def test_summarize_none():
    """None should return 'None'."""
    result = _summarize_tool_result(None)
    assert result == "None"


def test_summarize_number():
    """Numbers should convert to string."""
    assert _summarize_tool_result(42) == "42"
    assert _summarize_tool_result(3.14) == "3.14"


def test_summarize_nested_structure():
    """Nested dict/list should preserve structure in summary."""
    data = {
        "events": [
            {"title": "Event 1", "attendees": ["Alice", "Bob"]},
            {"title": "Event 2", "attendees": ["Charlie", "David"]},
        ],
        "count": 2,
    }
    result = _summarize_tool_result(data, max_chars=500)
    
    assert "{keys: ['events', 'count']}" in result
    assert "Event 1" in result
    assert "Alice" in result


# Test tool execution preserves structure

@pytest.fixture
def mock_orchestrator():
    """Mock orchestrator for testing."""
    orchestrator = Mock(spec=JarvisLLMOrchestrator)
    orchestrator._llm = Mock()
    orchestrator._llm.model_name = "test-model"
    orchestrator._llm.backend_name = "test-backend"
    return orchestrator


@pytest.fixture
def mock_tools():
    """Mock tool registry with a calendar.list_events tool."""
    registry = ToolRegistry()
    
    # Mock calendar.list_events that returns a large list
    def list_events():
        return [
            {
                "id": f"event_{i}",
                "title": f"Meeting {i}",
                "start": f"2024-01-{i:02d}T10:00:00",
                "end": f"2024-01-{i:02d}T11:00:00",
            }
            for i in range(1, 51)  # 50 events
        ]
    
    registry.register(
        Tool(
            name="calendar.list_events",
            description="List calendar events",
            function=list_events,
            parameters={},
        )
    )
    
    return registry


def test_tool_execution_preserves_raw_result(mock_orchestrator, mock_tools):
    """Tool execution should preserve raw_result AND create result_summary."""
    config = OrchestratorConfig()
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools,
        config=config,
    )
    
    # Mock orchestrator output with tool plan
    output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        confidence=0.9,
        tool_plan=["calendar.list_events"],  # List of tool names, not dicts
        assistant_reply="Checking your calendar...",
    )
    
    state = OrchestratorState()
    
    # Execute tools
    tool_results = loop._execute_tools_phase(output, state)
    
    # Verify structure
    assert len(tool_results) == 1
    result = tool_results[0]
    
    # Should have raw_result (original list)
    assert "raw_result" in result
    assert isinstance(result["raw_result"], list)
    assert len(result["raw_result"]) == 50
    assert result["raw_result"][0]["id"] == "event_1"
    assert result["raw_result"][49]["id"] == "event_50"
    
    # Should have result_summary (smart summary)
    assert "result_summary" in result
    assert "[50 items, showing first 5]" in result["result_summary"]
    
    # Summary should NOT contain all events (truncated)
    assert "event_50" not in result["result_summary"]
    
    # Should have other fields
    assert result["tool"] == "calendar.list_events"
    assert result["success"] is True


def test_finalizer_uses_raw_result(mock_orchestrator, mock_tools):
    """Finalizer should use raw_result for structured data, not truncated summary."""
    config = OrchestratorConfig()
    
    # Create a mock finalizer LLM that will be called
    mock_finalizer = Mock()
    mock_finalizer.complete_text = Mock(return_value="Efendim, 50 etkinlik buldum.")
    mock_finalizer.model_name = "test-finalizer"
    mock_finalizer.backend_name = "test-backend"
    
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools,
        config=config,
        finalizer_llm=mock_finalizer,  # ✅ Provide finalizer LLM
    )
    
    # Mock orchestrator output
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
    
    # Call finalization
    final_output = loop._llm_finalization_phase(
        user_input="Bugün ne toplantılarım var?",
        orchestrator_output=output,
        tool_results=tool_results,
        state=state,
    )
    
    # Check that the finalizer LLM was called
    assert mock_finalizer.complete_text.called
    call_args = mock_finalizer.complete_text.call_args
    
    # Get the prompt that was passed to the LLM
    # The prompt could be passed as keyword arg or positional arg
    if call_args.kwargs.get("prompt"):
        prompt = call_args.kwargs["prompt"]
    else:
        prompt = call_args.args[0]
    
    # Prompt should contain TOOL_RESULTS with raw data
    assert "TOOL_RESULTS" in prompt or "tool_results" in prompt
    
    # The prompt should have the full event list (from raw_result), not truncated summary
    # This means event_50 should be in the prompt
    assert "event_50" in prompt
    
    # Summary should NOT be in the finalizer prompt (we use raw_result)
    assert "[50 items, showing first 5]" not in prompt


def test_dict_result_preserves_structure(mock_orchestrator):
    """Tool returning a dict should preserve structure."""
    from bantz.tools.metadata import register_tool_risk, ToolRisk, TOOL_REGISTRY
    register_tool_risk("user.get_profile", ToolRisk.SAFE)

    registry = ToolRegistry()
    
    def get_user_profile():
        return {
            "name": "John Doe",
            "email": "john@example.com",
            "preferences": {
                "language": "tr",
                "timezone": "Europe/Istanbul",
            },
            "last_login": "2024-01-15T10:30:00",
        }
    
    registry.register(
        Tool(
            name="user.get_profile",
            description="Get user profile",
            function=get_user_profile,
            parameters={},
        )
    )
    
    config = OrchestratorConfig()
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=registry,
        config=config,
    )
    
    output = OrchestratorOutput(
        route="system",
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=["user.get_profile"],
        assistant_reply="Getting profile...",
    )
    
    state = OrchestratorState()
    tool_results = loop._execute_tools_phase(output, state)
    
    assert len(tool_results) == 1
    result = tool_results[0]
    
    # raw_result should be the original dict
    assert isinstance(result["raw_result"], dict)
    assert result["raw_result"]["name"] == "John Doe"
    assert result["raw_result"]["preferences"]["language"] == "tr"
    
    # result_summary should show keys
    assert "{keys:" in result["result_summary"]
    assert "name" in result["result_summary"]
    assert "John Doe" in result["result_summary"]

    # Cleanup: remove test tool from global registry
    TOOL_REGISTRY.pop("user.get_profile", None)


def test_failed_tool_preserves_error(mock_orchestrator):
    """Failed tool should preserve error message."""
    from bantz.tools.metadata import register_tool_risk, ToolRisk, TOOL_REGISTRY
    register_tool_risk("db.query", ToolRisk.SAFE)

    registry = ToolRegistry()
    
    def failing_tool():
        raise ValueError("Database connection failed")
    
    registry.register(
        Tool(
            name="db.query",
            description="Query database",
            function=failing_tool,
            parameters={},
        )
    )
    
    config = OrchestratorConfig()
    loop = OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=registry,
        config=config,
    )
    
    output = OrchestratorOutput(
        route="system",
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=["db.query"],
        assistant_reply="Querying...",
    )
    
    state = OrchestratorState()
    tool_results = loop._execute_tools_phase(output, state)
    
    assert len(tool_results) == 1
    result = tool_results[0]
    
    assert result["success"] is False
    assert "error" in result
    assert "Database connection failed" in result["error"]

    # Cleanup: remove test tool from global registry
    TOOL_REGISTRY.pop("db.query", None)
