"""Tests for Issue #355: BrainLoop finalizer missing tool results.

Problem: BrainLoop._maybe_finalize_user_reply() was not including tool execution
results in the finalizer prompt, preventing quality responses.

Solution: Add TOOL_RESULTS section to finalizer prompt with smart summarization.
"""

import json
from unittest.mock import Mock, patch, MagicMock
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.agent.tools import ToolRegistry


def _create_test_brain():
    """Create a BrainLoop instance for testing with minimal mocking."""
    # Mock LLM
    mock_llm = Mock()
    mock_llm.complete_text = Mock(return_value='{"route": "smalltalk"}')
    
    # Minimal tools registry
    tools = ToolRegistry()
    
    # Create brain with minimal config
    return BrainLoop(
        llm=mock_llm,
        tools=tools,
        config=BrainLoopConfig(max_steps=1, debug=False)
    )


def test_finalizer_receives_empty_observations():
    """When no tools were executed, finalizer should work without TOOL_RESULTS."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="Tamamlandı efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Mock the mode to always finalize
    with patch.object(brain, '_finalizer_mode', return_value='always'):
        result = brain._maybe_finalize_user_reply(
            user_text="merhaba",
            draft_text="Merhaba efendim!",
            observations=[],
            route="smalltalk",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt doesn't have TOOL_RESULTS section
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" not in user_msg
    assert result == "Tamamlandı efendim."


def test_finalizer_receives_single_tool_result():
    """Finalizer should include tool result in prompt for single tool execution."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="3 etkinlik bulundu efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Single tool observation
    observations = [
        {
            "name": "calendar.list_events",
            "tool": "calendar.list_events",
            "result": [
                {"summary": "Meeting 1", "start": "2024-01-15T10:00:00Z"},
                {"summary": "Meeting 2", "start": "2024-01-15T14:00:00Z"},
                {"summary": "Meeting 3", "start": "2024-01-15T16:00:00Z"},
            ]
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='calendar_only'):
        result = brain._maybe_finalize_user_reply(
            user_text="bugün ne toplantılarım var",
            draft_text="3 toplantınız var efendim.",
            observations=observations,
            route="calendar",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "calendar.list_events:" in user_msg
    # For 3 items, show them all without summary prefix
    assert "Meeting 1" in user_msg
    assert "Meeting 2" in user_msg
    assert "Meeting 3" in user_msg
    
    assert result == "3 etkinlik bulundu efendim."


def test_finalizer_receives_large_list_tool_result():
    """Finalizer should smartly summarize large list results."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="10 etkinlik bulundu efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Large list result (10 events)
    events = [
        {"summary": f"Event {i}", "start": f"2024-01-15T{10+i}:00:00Z"}
        for i in range(10)
    ]
    observations = [
        {
            "name": "calendar.list_events",
            "tool": "calendar.list_events",
            "result": events
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='calendar_only'):
        result = brain._maybe_finalize_user_reply(
            user_text="bugün ne toplantılarım var",
            draft_text="10 toplantınız var efendim.",
            observations=observations,
            route="calendar",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS with summary
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "calendar.list_events:" in user_msg
    assert "[10 items, showing first 3]" in user_msg
    # Should show first 3 events only
    assert "Event 0" in user_msg
    assert "Event 1" in user_msg
    assert "Event 2" in user_msg
    
    assert result == "10 etkinlik bulundu efendim."


def test_finalizer_receives_dict_tool_result():
    """Finalizer should handle dict results properly."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="Toplantı oluşturuldu efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Dict result (created event)
    observations = [
        {
            "name": "calendar.create_event",
            "tool": "calendar.create_event",
            "result": {
                "id": "evt123",
                "summary": "Team Meeting",
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T11:00:00Z",
            }
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='calendar_only'):
        result = brain._maybe_finalize_user_reply(
            user_text="yarın 10da toplantı oluştur",
            draft_text="Toplantı oluşturuldu efendim.",
            observations=observations,
            route="calendar",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "calendar.create_event:" in user_msg
    assert "Team Meeting" in user_msg
    
    assert result == "Toplantı oluşturuldu efendim."


def test_finalizer_receives_multiple_tool_results():
    """Finalizer should include last 3 tool results."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="İşlemler tamamlandı efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Multiple tool observations (5 total, should show last 3)
    observations = [
        {"name": "time.now", "tool": "time.now", "result": "2024-01-15T09:00:00Z"},
        {"name": "calendar.list_events", "tool": "calendar.list_events", "result": []},
        {"name": "calendar.create_event", "tool": "calendar.create_event", "result": {"id": "evt1"}},
        {"name": "calendar.create_event", "tool": "calendar.create_event", "result": {"id": "evt2"}},
        {"name": "calendar.list_events", "tool": "calendar.list_events", "result": [{"id": "evt1"}, {"id": "evt2"}]},
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='calendar_only'):
        result = brain._maybe_finalize_user_reply(
            user_text="iki toplantı oluştur",
            draft_text="2 toplantı oluşturuldu efendim.",
            observations=observations,
            route="calendar",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS with last 3 tools only
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    # Should have last 3 tools
    assert "calendar.create_event" in user_msg
    assert "evt1" in user_msg
    assert "evt2" in user_msg
    # Should NOT have the first tool (time.now)
    assert "time.now" not in user_msg
    
    assert result == "İşlemler tamamlandı efendim."


def test_finalizer_truncates_very_long_string_result():
    """Finalizer should truncate very long string results."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="Tamamlandı efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Very long string result
    long_text = "x" * 500
    observations = [
        {
            "name": "some.tool",
            "tool": "some.tool",
            "result": long_text
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='always'):
        result = brain._maybe_finalize_user_reply(
            user_text="test",
            draft_text="Test efendim.",
            observations=observations,
            route="test",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS with truncation
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "some.tool:" in user_msg
    assert "..." in user_msg  # Should be truncated
    # Should be truncated to 300 chars
    assert len(user_msg.split("some.tool:")[1].split("\n")[0]) <= 310  # ~300 + "..."


def test_finalizer_handles_none_result():
    """Finalizer should handle None results gracefully."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="Tamamlandı efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # None result
    observations = [
        {
            "name": "some.tool",
            "tool": "some.tool",
            "result": None
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='always'):
        result = brain._maybe_finalize_user_reply(
            user_text="test",
            draft_text="Test efendim.",
            observations=observations,
            route="test",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS with None
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "some.tool: None" in user_msg


def test_finalizer_handles_empty_list_result():
    """Finalizer should handle empty list results."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="Hiç etkinlik yok efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    # Empty list result
    observations = [
        {
            "name": "calendar.list_events",
            "tool": "calendar.list_events",
            "result": []
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='calendar_only'):
        result = brain._maybe_finalize_user_reply(
            user_text="bugün ne toplantılarım var",
            draft_text="Hiç toplantınız yok efendim.",
            observations=observations,
            route="calendar",
        )
    
    # Should have called finalizer
    assert mock_llm.chat.called
    
    # Check the prompt includes TOOL_RESULTS with empty list
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "calendar.list_events: []" in user_msg


def test_finalizer_system_prompt_includes_tool_results_instruction():
    """System prompt should instruct LLM to use TOOL_RESULTS."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    mock_llm.chat = Mock(return_value="Tamamlandı efendim.")
    brain._calendar_finalizer_llm = mock_llm
    
    observations = [
        {"name": "test.tool", "tool": "test.tool", "result": "test data"}
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='always'):
        brain._maybe_finalize_user_reply(
            user_text="test",
            draft_text="Test efendim.",
            observations=observations,
            route="test",
        )
    
    # Check system message includes instruction about using TOOL_RESULTS
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    sys_msg = messages[0].content
    
    assert "TOOL_RESULTS" in sys_msg


def test_integration_finalizer_with_10_events():
    """Integration test: 10 events should produce quality response with tool results."""
    brain = _create_test_brain()
    
    # Mock the finalizer LLM to return a quality response using tool results
    mock_llm = Mock()
    mock_llm.backend_name = "gemini"
    # Simulate LLM understanding the 10 events from TOOL_RESULTS
    mock_llm.chat = Mock(return_value="10 toplantınız var efendim. İlk 3 tanesi: Event 0, Event 1, Event 2.")
    brain._calendar_finalizer_llm = mock_llm
    
    # 10 events
    events = [
        {"summary": f"Event {i}", "start": f"2024-01-15T{10+i}:00:00Z"}
        for i in range(10)
    ]
    observations = [
        {
            "name": "calendar.list_events",
            "tool": "calendar.list_events",
            "result": events
        }
    ]
    
    with patch.object(brain, '_finalizer_mode', return_value='calendar_only'):
        result = brain._maybe_finalize_user_reply(
            user_text="bugün ne toplantılarım var",
            draft_text="Bugün 10 toplantınız var efendim.",
            observations=observations,
            route="calendar",
        )
    
    # Should produce quality response using tool results
    assert "10 toplantınız var" in result
    assert "Event 0" in result
    
    # Verify TOOL_RESULTS was in the prompt
    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    user_msg = messages[1].content
    
    assert "TOOL_RESULTS:" in user_msg
    assert "[10 items, showing first 3]" in user_msg
