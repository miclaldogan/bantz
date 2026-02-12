"""Tests for Force Tool Plan (Issue #282).

Tests that OrchestratorLoop forces mandatory tools when LLM returns empty tool_plan
for routes that require tools (calendar, gmail, system).

Prevents hallucination when LLM doesn't plan proper tools.
"""

from __future__ import annotations

import pytest
from dataclasses import replace
from unittest.mock import Mock, MagicMock

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.agent.tools import ToolRegistry
from bantz.core.events import EventBus


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_orchestrator():
    """Mock LLM orchestrator."""
    return Mock(spec=["route"])


@pytest.fixture
def mock_tools():
    """Mock tool registry."""
    return Mock(spec=ToolRegistry)


@pytest.fixture
def event_bus():
    """Event bus for tests."""
    return EventBus()


@pytest.fixture
def config():
    """Default orchestrator config."""
    return OrchestratorConfig(enable_safety_guard=False, debug=True)


@pytest.fixture
def loop(mock_orchestrator, mock_tools, event_bus, config):
    """OrchestratorLoop instance for testing."""
    return OrchestratorLoop(
        orchestrator=mock_orchestrator,
        tools=mock_tools,
        event_bus=event_bus,
        config=config,
    )


# ============================================================================
# Test Cases: _force_tool_plan
# ============================================================================

class TestForceToolPlanCalendar:
    """Test forced tool plan for calendar routes."""
    
    def test_calendar_query_forces_list_events(self, loop):
        """Calendar + query with empty tool_plan should force list_events."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=[],  # Empty!
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["calendar.list_events"]
        assert result.route == "calendar"
        assert result.calendar_intent == "query"
    
    def test_calendar_create_forces_create_event(self, loop):
        """Calendar + create with empty tool_plan should force create_event."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots={"title": "Meeting", "date": "tomorrow"},
            confidence=0.85,
            tool_plan=[],  # Empty!
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["calendar.create_event"]
    
    def test_calendar_modify_forces_update_event(self, loop):
        """Calendar + modify with empty tool_plan should force update_event."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="modify",
            slots={},
            confidence=0.8,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["calendar.update_event"]
    
    def test_calendar_cancel_forces_delete_event(self, loop):
        """Calendar + cancel with empty tool_plan should force delete_event."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="cancel",
            slots={},
            confidence=0.88,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["calendar.delete_event"]
    
    def test_calendar_with_existing_tool_plan_not_overwritten(self, loop):
        """If LLM already provided tool_plan, don't overwrite."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.95,
            tool_plan=["calendar.list_events", "calendar.get_event"],  # Already populated!
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should not change existing tool_plan
        assert result.tool_plan == ["calendar.list_events", "calendar.get_event"]


class TestForceToolPlanGmail:
    """Test forced tool plan for Gmail routes."""
    
    def test_gmail_query_forces_list_messages(self, loop):
        """Gmail + query with empty tool_plan should force list_messages."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="query",  # Issue #897: use gmail_intent for gmail routes
            slots={},
            confidence=0.87,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["gmail.list_messages"]
    
    def test_gmail_list_forces_list_messages(self, loop):
        """Gmail + list with empty tool_plan should force list_messages."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="list",  # Issue #897
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["gmail.list_messages"]
    
    def test_gmail_read_forces_get_message(self, loop):
        """Gmail + read with empty tool_plan should force get_message."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="read",  # Issue #897
            slots={"message_id": "abc123"},
            confidence=0.92,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["gmail.get_message"]
    
    def test_gmail_send_forces_send_message(self, loop):
        """Gmail + send with empty tool_plan should force gmail.send."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="send",  # Issue #897
            slots={"to": "test@example.com"},
            confidence=0.85,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["gmail.send"]
    
    def test_gmail_unknown_intent_fallback(self, loop):
        """Gmail with unknown intent should fallback to list_messages."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="unknown",  # Issue #897
            slots={},
            confidence=0.7,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        # Fallback to list_messages for any gmail query
        assert result.tool_plan == ["gmail.list_messages"]


class TestForceToolPlanSystem:
    """Test forced tool plan for system routes."""
    
    def test_system_time_forces_time_now(self, loop):
        """System + time with empty tool_plan should force time.now."""
        output = OrchestratorOutput(
            route="system",
            calendar_intent="time",
            slots={},
            confidence=0.95,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["time.now"]
    
    def test_system_status_forces_system_status(self, loop):
        """System + status with empty tool_plan should force system.status."""
        output = OrchestratorOutput(
            route="system",
            calendar_intent="status",
            slots={},
            confidence=0.88,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["system.status"]
    
    def test_system_query_fallback(self, loop):
        """System + query should fallback to time.now."""
        output = OrchestratorOutput(
            route="system",
            calendar_intent="query",
            slots={},
            confidence=0.8,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["time.now"]
    
    def test_system_unknown_intent_fallback(self, loop):
        """System with unknown intent should fallback to time.now."""
        output = OrchestratorOutput(
            route="system",
            calendar_intent="unknown",
            slots={},
            confidence=0.75,
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == ["time.now"]


class TestForceToolPlanSmalltalk:
    """Test that smalltalk/unknown routes don't get forced tools."""
    
    def test_smalltalk_no_forced_tools(self, loop):
        """Smalltalk route should NOT get forced tools."""
        output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.92,
            tool_plan=[],  # Empty is OK for smalltalk
            assistant_reply="Hi! How can I help?",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == []  # Should stay empty
    
    def test_unknown_route_no_forced_tools(self, loop):
        """Unknown route should NOT get forced tools."""
        output = OrchestratorOutput(
            route="unknown",
            calendar_intent="none",
            slots={},
            confidence=0.5,
            tool_plan=[],
            assistant_reply="I'm not sure what you mean.",
        )
        
        result = loop._force_tool_plan(output)
        
        assert result.tool_plan == []  # Should stay empty
    
    def test_ask_user_no_forced_tools(self, loop):
        """When LLM is asking for clarification, don't force tools."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots={"title": "meeting"},
            confidence=0.5,  # Low confidence
            tool_plan=[],
            assistant_reply="How long should the meeting be?",
            ask_user=True,  # LLM is asking for clarification
            question="How long should the meeting be?",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should NOT force tools when asking user for clarification
        assert result.tool_plan == []
    
    def test_none_intent_no_forced_tools(self, loop):
        """When intent is 'none' on gmail route, gmail.list_messages is forced as fallback."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",  # No action needed, just drafting
            slots={},
            confidence=0.95,
            tool_plan=[],
            assistant_reply="I'll draft that email for you.",
        )
        
        result = loop._force_tool_plan(output)
        
        # Gmail route with none intent forces gmail.list_messages as fallback
        assert result.tool_plan == ["gmail.list_messages"]
    
    def test_empty_intent_no_forced_tools(self, loop):
        """When intent is empty on gmail route, gmail.list_messages is forced as fallback."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="",  # Empty intent
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="Working on it.",
        )
        
        result = loop._force_tool_plan(output)
        
        # Gmail route with empty intent forces gmail.list_messages as fallback
        assert result.tool_plan == ["gmail.list_messages"]


class TestForceToolPlanPreservesOtherFields:
    """Test that _force_tool_plan preserves all other OrchestratorOutput fields."""
    
    def test_preserves_all_fields(self, loop):
        """Forcing tool_plan should not modify other fields."""
        original = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={"date": "tomorrow", "time": "3pm"},
            confidence=0.87,
            tool_plan=[],
            assistant_reply="Let me check your calendar.",
            ask_user=False,  # Not asking, so tools should be forced
            question="",
            requires_confirmation=False,
            confirmation_prompt="",
            memory_update="User asked about calendar",
            reasoning_summary=["Checking calendar", "Query intent detected"],
        )
        
        result = loop._force_tool_plan(original)
        
        # Tool plan should be forced
        assert result.tool_plan == ["calendar.list_events"]
        
        # All other fields should be preserved
        assert result.route == "calendar"
        assert result.calendar_intent == "query"
        assert result.slots == {"date": "tomorrow", "time": "3pm"}
        assert result.confidence == 0.87
        assert result.assistant_reply == "Let me check your calendar."
        assert result.ask_user is False
        assert result.question == ""
        assert result.requires_confirmation is False
        assert result.memory_update == "User asked about calendar"
        assert result.reasoning_summary == ["Checking calendar", "Query intent detected"]


class TestMandatoryToolMapCoverage:
    """Test that the mandatory tool map is complete and correct."""
    
    def test_mandatory_tool_map_exists(self, loop):
        """Verify mandatory tool map is initialized."""
        assert hasattr(loop, "_mandatory_tool_map")
        assert isinstance(loop._mandatory_tool_map, dict)
    
    def test_calendar_mappings_exist(self, loop):
        """Verify all calendar intent mappings."""
        assert ("calendar", "query") in loop._mandatory_tool_map
        assert ("calendar", "create") in loop._mandatory_tool_map
        assert ("calendar", "modify") in loop._mandatory_tool_map
        assert ("calendar", "cancel") in loop._mandatory_tool_map
    
    def test_gmail_mappings_exist(self, loop):
        """Verify all gmail intent mappings (Issue #897: moved to _gmail_intent_map)."""
        assert "list" in loop._gmail_intent_map
        assert "search" in loop._gmail_intent_map
        assert "read" in loop._gmail_intent_map
        assert "send" in loop._gmail_intent_map
    
    def test_system_mappings_exist(self, loop):
        """Verify all system intent mappings."""
        assert ("system", "time") in loop._mandatory_tool_map
        assert ("system", "status") in loop._mandatory_tool_map
        assert ("system", "query") in loop._mandatory_tool_map


# ============================================================================
# Issue #347: Low Confidence Tool Forcing
# ============================================================================

class TestLowConfidenceToolForcing:
    """Test that low confidence outputs are not forced (Issue #347)."""
    
    def test_low_confidence_calendar_query_not_forced(self, loop):
        """
        Calendar query with confidence < 0.4 should NOT force tools.
        Issue #682: Threshold lowered from 0.7 to 0.4 for 3B models.
        """
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.3,  # ❌ Low confidence (below 0.4 threshold)
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should NOT force tools - confidence too low
        assert result.tool_plan == []
        assert result.confidence == 0.3
    
    def test_low_confidence_gmail_list_not_forced(self, loop):
        """Gmail list with confidence < 0.4 should NOT force tools."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent="list",  # Issue #897
            slots={},
            confidence=0.3,  # ❌ Low confidence (below 0.4 threshold)
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should NOT force tools
        assert result.tool_plan == []
    
    def test_borderline_confidence_not_forced(self, loop):
        """Confidence exactly at threshold (0.7) should be forced."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.7,  # ✅ At threshold
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should force tools - at threshold
        assert result.tool_plan == ["calendar.list_events"]
    
    def test_high_confidence_forces_tools(self, loop):
        """High confidence should force tools as expected."""
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.95,  # ✅ High confidence
            tool_plan=[],
            assistant_reply="",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should force tools
        assert result.tool_plan == ["calendar.list_events"]
    
    def test_ask_user_not_forced_even_high_confidence(self, loop):
        """
        Even with high confidence, if ask_user=True, don't force tools.
        Router wants clarification from user.
        """
        output = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.95,
            tool_plan=[],
            assistant_reply="",
            ask_user=True,  # ❌ Asking for clarification
            question="Hangi tarihi kontrol etmemi istersiniz?",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should NOT force tools - asking user
        assert result.tool_plan == []
        assert result.ask_user is True
    
    def test_low_confidence_with_ask_user_not_forced(self, loop):
        """Low confidence + ask_user should definitely not force tools."""
        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="query",
            slots={},
            confidence=0.4,  # ❌ Very low
            tool_plan=[],
            assistant_reply="",
            ask_user=True,  # ❌ Asking
            question="Ne aramak istersiniz?",
        )
        
        result = loop._force_tool_plan(output)
        
        # Should NOT force tools
        assert result.tool_plan == []
    
    def test_confidence_threshold_documentation(self, loop):
        """
        Document the confidence threshold value used.
        Issue #682: Threshold lowered from 0.7 to 0.4 for 3B models.
        """
        # Threshold is 0.4 (lowered from 0.7 in Issue #682)
        
        # Below threshold
        output_low = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.39,
            tool_plan=[],
            assistant_reply="",
        )
        result_low = loop._force_tool_plan(output_low)
        assert result_low.tool_plan == []
        
        # At threshold
        output_exact = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.4,
            tool_plan=[],
            assistant_reply="",
        )
        result_exact = loop._force_tool_plan(output_exact)
        assert result_exact.tool_plan == ["calendar.list_events"]
        
        # Above threshold
        output_high = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.5,
            tool_plan=[],
            assistant_reply="",
        )
        result_high = loop._force_tool_plan(output_high)
        assert result_high.tool_plan == ["calendar.list_events"]
