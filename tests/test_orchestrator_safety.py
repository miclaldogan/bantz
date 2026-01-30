"""Integration tests for Safety Guard in Orchestrator (Issue #140).

Tests orchestrator with safety guards enabled:
- Tool execution blocked by denylist
- Invalid args rejected
- Route-tool mismatch filtered
- Ambiguous confirmation rejected
"""

from __future__ import annotations

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.brain.safety_guard import ToolSecurityPolicy
from bantz.core.events import EventBus


# ============================================================================
# Mock LLM
# ============================================================================

class MockLLMForSafety:
    """Mock LLM with canned responses for safety tests."""
    
    def __init__(self, response: dict):
        self.response = response
    
    def complete_text(self, *, prompt: str) -> str:
        import json
        return json.dumps(self.response, ensure_ascii=False)


# ============================================================================
# Mock Tools
# ============================================================================

def mock_list_events(**kwargs) -> dict:
    return {"items": [], "count": 0}


def mock_delete_event(**kwargs) -> dict:
    return {"deleted": True}


def build_test_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    
    list_tool = Tool(
        name="calendar.list_events",
        description="List events",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
            },
            "required": ["time_min", "time_max"],
        },
        function=mock_list_events,
    )
    registry.register(list_tool)
    
    delete_tool = Tool(
        name="calendar.delete_event",
        description="Delete event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
            },
            "required": ["event_id"],
        },
        function=mock_delete_event,
        requires_confirmation=True,
    )
    registry.register(delete_tool)
    
    return registry


# ============================================================================
# Safety Guard Integration Tests
# ============================================================================

def test_orchestrator_denylist_blocks_tool():
    """Test tool execution is blocked by denylist."""
    # LLM wants to delete event
    mock_response = {
        "route": "calendar",
        "calendar_intent": "cancel",
        "slots": {"event_id": "evt123"},
        "confidence": 0.9,
        "tool_plan": ["calendar.delete_event"],
        "assistant_reply": "",
        "ask_user": False,
        "question": "",
        "requires_confirmation": True,
        "confirmation_prompt": "Delete event?",
        "memory_update": "User wants to delete event",
        "reasoning_summary": ["Delete requested"],
    }
    
    mock_llm = MockLLMForSafety(mock_response)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_test_tool_registry()
    event_bus = EventBus()
    
    # Security policy: deny delete_event
    policy = ToolSecurityPolicy(
        denylist={"calendar.delete_event"}
    )
    config = OrchestratorConfig(
        debug=True,
        enable_safety_guard=True,
        security_policy=policy,
    )
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    output, state = loop.process_turn("sil o etkinliği")
    
    # Tool should be blocked
    assert state.trace.get("tools_executed") == 0
    # No tool results should be added to state
    assert len(state.last_tool_results) == 0


def test_orchestrator_invalid_args_rejected():
    """Test tool execution fails on invalid arguments."""
    # LLM provides invalid args (missing required field)
    mock_response = {
        "route": "calendar",
        "calendar_intent": "query",
        "slots": {"time_min": "2026-01-30T00:00:00"},  # Missing time_max!
        "confidence": 0.9,
        "tool_plan": ["calendar.list_events"],
        "assistant_reply": "",
        "ask_user": False,
        "question": "",
        "requires_confirmation": False,
        "confirmation_prompt": "",
        "memory_update": "User wants to list events",
        "reasoning_summary": ["Query requested"],
    }
    
    mock_llm = MockLLMForSafety(mock_response)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_test_tool_registry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True, enable_safety_guard=True)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    output, state = loop.process_turn("bugün neler var")
    
    # Tool should fail validation
    assert state.trace.get("tools_executed") == 0


def test_orchestrator_route_tool_mismatch():
    """Test tool plan is dropped for smalltalk route."""
    # LLM returns smalltalk but somehow includes tools (LLM hallucination)
    mock_response = {
        "route": "smalltalk",
        "calendar_intent": "none",
        "slots": {},
        "confidence": 1.0,
        "tool_plan": ["calendar.list_events"],  # Shouldn't have tools!
        "assistant_reply": "İyiyim efendim",
        "ask_user": False,
        "question": "",
        "requires_confirmation": False,
        "confirmation_prompt": "",
        "memory_update": "Smalltalk",
        "reasoning_summary": ["Greeting"],
    }
    
    mock_llm = MockLLMForSafety(mock_response)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_test_tool_registry()
    event_bus = EventBus()
    
    # Enable route-tool match enforcement
    policy = ToolSecurityPolicy(enforce_route_tool_match=True)
    config = OrchestratorConfig(
        debug=True,
        enable_safety_guard=True,
        security_policy=policy,
    )
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    output, state = loop.process_turn("nasılsın")
    
    # Tool plan should be filtered (dropped)
    assert state.trace.get("tools_executed") == 0
    # But response should still be delivered
    assert "İyiyim" in output.assistant_reply


def test_orchestrator_safety_guard_disabled():
    """Test orchestrator works without safety guard."""
    mock_response = {
        "route": "calendar",
        "calendar_intent": "query",
        "slots": {"time_min": "2026-01-30T00:00:00", "time_max": "2026-01-30T23:59:59"},
        "confidence": 0.9,
        "tool_plan": ["calendar.list_events"],
        "assistant_reply": "",
        "ask_user": False,
        "question": "",
        "requires_confirmation": False,
        "confirmation_prompt": "",
        "memory_update": "Query",
        "reasoning_summary": ["List events"],
    }
    
    mock_llm = MockLLMForSafety(mock_response)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_test_tool_registry()
    event_bus = EventBus()
    
    # Disable safety guard
    config = OrchestratorConfig(debug=True, enable_safety_guard=False)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    output, state = loop.process_turn("bugün neler var")
    
    # Tool should execute (no safety checks)
    assert state.trace.get("tools_executed") >= 1
