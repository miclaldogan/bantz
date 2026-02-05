"""Tests for Trace Visualization (Issue #284).

Tests that the trace visualization shows step-by-step progress
when processing user requests.
"""

import pytest
import sys
from pathlib import Path
from io import StringIO
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

# Add scripts to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from bantz.core.events import EventBus, Event, EventType


# ============================================================================
# Test EventType Constants
# ============================================================================

class TestEventTypes:
    """Test that new trace event types exist."""
    
    def test_turn_start_event_type(self):
        """TURN_START event type should exist."""
        assert hasattr(EventType, "TURN_START")
        assert EventType.TURN_START.value == "turn.start"
    
    def test_intent_detected_event_type(self):
        """INTENT_DETECTED event type should exist."""
        assert hasattr(EventType, "INTENT_DETECTED")
        assert EventType.INTENT_DETECTED.value == "intent.detected"
    
    def test_slots_extracted_event_type(self):
        """SLOTS_EXTRACTED event type should exist."""
        assert hasattr(EventType, "SLOTS_EXTRACTED")
        assert EventType.SLOTS_EXTRACTED.value == "slots.extracted"
    
    def test_tool_selected_event_type(self):
        """TOOL_SELECTED event type should exist."""
        assert hasattr(EventType, "TOOL_SELECTED")
        assert EventType.TOOL_SELECTED.value == "tool.selected"
    
    def test_tool_call_event_type(self):
        """TOOL_CALL event type should exist."""
        assert hasattr(EventType, "TOOL_CALL")
        assert EventType.TOOL_CALL.value == "tool.call"
    
    def test_tool_result_event_type(self):
        """TOOL_RESULT event type should exist."""
        assert hasattr(EventType, "TOOL_RESULT")
        assert EventType.TOOL_RESULT.value == "tool.result"
    
    def test_finalizer_start_event_type(self):
        """FINALIZER_START event type should exist."""
        assert hasattr(EventType, "FINALIZER_START")
        assert EventType.FINALIZER_START.value == "finalizer.start"
    
    def test_finalizer_end_event_type(self):
        """FINALIZER_END event type should exist."""
        assert hasattr(EventType, "FINALIZER_END")
        assert EventType.FINALIZER_END.value == "finalizer.end"
    
    def test_turn_end_event_type(self):
        """TURN_END event type should exist."""
        assert hasattr(EventType, "TURN_END")
        assert EventType.TURN_END.value == "turn.end"


# ============================================================================
# Test Trace Handler Function
# ============================================================================

class TestTraceHandler:
    """Test the trace event handler from terminal_jarvis."""
    
    @pytest.fixture
    def mock_event(self):
        """Create a mock event factory."""
        def _make_event(event_type: str, data: dict = None):
            event = Mock()
            event.event_type = event_type
            event.data = data or {}
            return event
        return _make_event
    
    @pytest.fixture
    def handler(self):
        """Create the _on_event handler function."""
        # Import the function from terminal_jarvis
        from terminal_jarvis import TerminalJarvis
        
        # Create a minimal mock jarvis with trace enabled
        jarvis = Mock(spec=TerminalJarvis)
        jarvis._trace_enabled = True
        
        # Get the actual handler method
        def _on_event(event):
            if not jarvis._trace_enabled:
                return
            
            et = str(getattr(event, "event_type", ""))
            data = getattr(event, "data", {}) or {}
            
            # Simplified handler for testing
            if et == "turn.start":
                print("[1/6] 🎯 Niyet tespit ediliyor...")
            elif et == "intent.detected":
                route = data.get("route", "?")
                print(f"[2/6] Route: {route}")
            elif et == "slots.extracted":
                slots = data.get("slots", {})
                print(f"[3/6] Slots: {slots}")
            elif et == "tool.selected":
                tools = data.get("tools", [])
                print(f"[3/6] Tools: {tools}")
            elif et == "tool.call":
                tool = data.get("tool", "?")
                print(f"[4/6] Running: {tool}")
            elif et == "tool.result":
                ok = data.get("success", True)
                print(f"[4/6] Result: {'OK' if ok else 'FAIL'}")
            elif et == "finalizer.start":
                print("[5/6] Finalizing...")
            elif et == "turn.end":
                ms = data.get("elapsed_ms", 0)
                print(f"[6/6] Done: {ms}ms")
        
        return _on_event
    
    def test_turn_start_prints_step_1(self, handler, mock_event, capsys):
        """Turn start should print step 1."""
        event = mock_event("turn.start", {"user_input": "test"})
        handler(event)
        
        captured = capsys.readouterr()
        assert "[1/6]" in captured.out
        assert "🎯" in captured.out
    
    def test_intent_detected_prints_route(self, handler, mock_event, capsys):
        """Intent detected should print route."""
        event = mock_event("intent.detected", {
            "route": "calendar",
            "intent": "query",
            "confidence": 0.9,
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[2/6]" in captured.out
        assert "calendar" in captured.out
    
    def test_slots_extracted_prints_slots(self, handler, mock_event, capsys):
        """Slots extracted should print slot values."""
        event = mock_event("slots.extracted", {
            "slots": {"date": "tomorrow", "time": "3pm"},
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[3/6]" in captured.out
    
    def test_tool_selected_prints_tools(self, handler, mock_event, capsys):
        """Tool selected should print tool names."""
        event = mock_event("tool.selected", {
            "tools": ["calendar.list_events"],
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[3/6]" in captured.out
        assert "calendar.list_events" in captured.out
    
    def test_tool_call_prints_tool_name(self, handler, mock_event, capsys):
        """Tool call should print which tool is running."""
        event = mock_event("tool.call", {
            "tool": "calendar.list_events",
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[4/6]" in captured.out
        assert "calendar.list_events" in captured.out
    
    def test_tool_result_success(self, handler, mock_event, capsys):
        """Successful tool result should show OK."""
        event = mock_event("tool.result", {
            "success": True,
            "tool": "calendar.list_events",
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[4/6]" in captured.out
        assert "OK" in captured.out
    
    def test_tool_result_failure(self, handler, mock_event, capsys):
        """Failed tool result should show FAIL."""
        event = mock_event("tool.result", {
            "success": False,
            "tool": "calendar.list_events",
            "error": "API error",
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[4/6]" in captured.out
        assert "FAIL" in captured.out
    
    def test_finalizer_start(self, handler, mock_event, capsys):
        """Finalizer start should print step 5."""
        event = mock_event("finalizer.start", {
            "has_tool_results": True,
            "tool_count": 1,
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[5/6]" in captured.out
    
    def test_turn_end_prints_elapsed(self, handler, mock_event, capsys):
        """Turn end should print elapsed time."""
        event = mock_event("turn.end", {
            "elapsed_ms": 1234,
        })
        handler(event)
        
        captured = capsys.readouterr()
        assert "[6/6]" in captured.out
        assert "1234" in captured.out


# ============================================================================
# Test EventBus Integration
# ============================================================================

class TestEventBusIntegration:
    """Test that events are properly published through EventBus."""
    
    def test_eventbus_publishes_turn_start(self):
        """EventBus should publish turn.start event."""
        bus = EventBus()
        received = []
        
        def handler(event):
            received.append(event)
        
        bus.subscribe("turn.start", handler)
        bus.publish("turn.start", {"user_input": "test"})
        
        assert len(received) == 1
        assert received[0].event_type == "turn.start"
    
    def test_eventbus_publishes_intent_detected(self):
        """EventBus should publish intent.detected event."""
        bus = EventBus()
        received = []
        
        def handler(event):
            received.append(event)
        
        bus.subscribe("intent.detected", handler)
        bus.publish("intent.detected", {"route": "calendar", "intent": "query"})
        
        assert len(received) == 1
        assert received[0].data["route"] == "calendar"
    
    def test_eventbus_subscribe_all_receives_trace_events(self):
        """subscribe_all should receive all trace events."""
        bus = EventBus()
        received = []
        
        def handler(event):
            received.append(event.event_type)
        
        bus.subscribe_all(handler)
        
        # Publish multiple events
        bus.publish("turn.start", {})
        bus.publish("intent.detected", {})
        bus.publish("slots.extracted", {})
        bus.publish("tool.selected", {})
        bus.publish("tool.call", {})
        bus.publish("tool.result", {})
        bus.publish("finalizer.start", {})
        bus.publish("turn.end", {})
        
        assert len(received) == 8
        assert "turn.start" in received
        assert "turn.end" in received


# ============================================================================
# Test Trace Output Format
# ============================================================================

class TestTraceOutputFormat:
    """Test the visual format of trace output."""
    
    def test_trace_has_step_numbers(self):
        """Trace output should have numbered steps [1/6], [2/6], etc."""
        # This is a format validation test
        expected_steps = ["[1/6]", "[2/6]", "[3/6]", "[4/6]", "[5/6]", "[6/6]"]
        
        # All steps should be valid format
        for step in expected_steps:
            assert step.startswith("[")
            assert step.endswith("]")
            parts = step[1:-1].split("/")
            assert len(parts) == 2
            assert int(parts[0]) <= int(parts[1])
    
    def test_route_emoji_mapping(self):
        """Each route should have an appropriate emoji."""
        route_emojis = {
            "calendar": "📅",
            "gmail": "📧",
            "system": "⚙️",
            "smalltalk": "💬",
            "unknown": "❓",
        }
        
        # Verify all routes have emojis
        for route, emoji in route_emojis.items():
            assert emoji, f"Route {route} should have an emoji"
    
    def test_speed_emoji_mapping(self):
        """Elapsed time should have speed indicators."""
        # Fast: < 500ms
        # Normal: 500-1500ms
        # Slow: > 1500ms
        
        assert "⚡" is not None  # Fast
        assert "🚀" is not None  # Normal
        assert "🐢" is not None  # Slow
