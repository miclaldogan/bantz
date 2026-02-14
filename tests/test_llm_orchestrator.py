"""Test suite for LLM Orchestrator (Issue #134).

Tests 5 scenarios with metadata-based assertions (not text-dependent):
1. "hey bantz nasılsın" - Smalltalk
2. "bugün neler yapacağız bakalım" - Calendar query (today)
3. "saat 4 için bir toplantı oluştur" - Calendar create (requires confirmation)
4. "bu akşam neler yapacağız" - Calendar query (evening window)
5. "bu hafta planımda önemli işler var mı?" - Calendar query (week window)

Run:
    pytest tests/test_llm_orchestrator.py -v
    pytest tests/test_llm_orchestrator.py::test_scenario_1_smalltalk -v
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, MagicMock

from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.agent.tools import ToolRegistry, Tool
from bantz.core.events import EventBus

# Capture pristine class-level state BEFORE any test narrows it
_PRISTINE_VALID_TOOLS = frozenset(JarvisLLMOrchestrator._VALID_TOOLS)
_PRISTINE_SYSTEM_PROMPT = JarvisLLMOrchestrator.SYSTEM_PROMPT


@pytest.fixture(autouse=True)
def _restore_orchestrator_class_state():
    """Restore _VALID_TOOLS and SYSTEM_PROMPT before AND after each test.

    sync_valid_tools() narrows _VALID_TOOLS at class level. Tests that use an
    empty ToolRegistry (e.g. scenario 1) delete calendar tools, breaking
    subsequent tests.
    """
    JarvisLLMOrchestrator._VALID_TOOLS = set(_PRISTINE_VALID_TOOLS)
    JarvisLLMOrchestrator.SYSTEM_PROMPT = _PRISTINE_SYSTEM_PROMPT
    yield
    JarvisLLMOrchestrator._VALID_TOOLS = set(_PRISTINE_VALID_TOOLS)
    JarvisLLMOrchestrator.SYSTEM_PROMPT = _PRISTINE_SYSTEM_PROMPT


# ========================================================================
# Mock Tools
# ========================================================================

def mock_list_events(window_hint: str = "", date: str = "", query: str = "", **kwargs) -> dict:
    """Mock calendar.list_events tool.

    Note: build_tool_params strips time_min/time_max from calendar.list_events
    and only passes: date, window_hint, query, max_results, title.
    """
    return {
        "items": [
            {
                "id": "evt1",
                "summary": "Team Meeting",
                "start": {"dateTime": "2026-01-30T10:00:00+03:00"},
                "end": {"dateTime": "2026-01-30T11:00:00+03:00"},
            }
        ],
        "count": 1,
    }


def mock_create_event(title: str, start_time: str, end_time: str = "", **kwargs) -> dict:
    """Mock calendar.create_event tool."""
    return {
        "id": f"evt_{title.lower().replace(' ', '_')}",
        "summary": title,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time or start_time},
        "status": "confirmed",
    }


def build_mock_tool_registry() -> ToolRegistry:
    """Build mock tool registry for testing."""
    registry = ToolRegistry()
    
    # Calendar list_events
    list_tool = Tool(
        name="calendar.list_events",
        description="List calendar events in time range",
        parameters={
            "type": "object",
            "properties": {
                "window_hint": {"type": "string", "description": "Time window hint (today, evening, week)"},
                "date": {"type": "string", "description": "Date (ISO)"},
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results"},
            },
            "required": [],
        },
        function=mock_list_events,
    )
    registry.register(list_tool)
    
    # Calendar create_event
    create_tool = Tool(
        name="calendar.create_event",
        description="Create calendar event",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time (ISO)"},
                "end_time": {"type": "string", "description": "End time (ISO)"},
            },
            "required": ["title", "start_time"],
        },
        function=mock_create_event,
        requires_confirmation=True,
    )
    registry.register(create_tool)
    
    return registry


# ========================================================================
# Mock LLM Client
# ========================================================================

class MockLLMClient:
    """Mock LLM client for deterministic testing."""
    
    def __init__(self, scenario_responses: dict[str, dict]):
        """scenario_responses: {user_input_keyword: orchestrator_output_dict}"""
        self.scenario_responses = scenario_responses
        self.calls = []
    
    def complete_text(self, *, prompt: str) -> str:
        """Return mock JSON response based on user input in prompt."""
        self.calls.append(prompt)
        
        # Extract LAST user input from prompt (not examples in SYSTEM_PROMPT)
        user_lines = []
        for line in prompt.split("\n"):
            if line.startswith("USER:"):
                user_lines.append(line[5:].strip())
        
        # Take the last USER line (actual input, not examples)
        user_input = user_lines[-1].lower() if user_lines else ""
        
        # Find matching scenario
        for keyword, response_dict in self.scenario_responses.items():
            if keyword.lower() in user_input:
                import json
                return json.dumps(response_dict, ensure_ascii=False)
        
        # Default fallback
        return '{"route": "unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.0, "tool_plan": [], "assistant_reply": "Anlamadım", "memory_update": "Kullanıcı bir şey sordu", "reasoning_summary": ["Belirsiz girdi"]}'


# ========================================================================
# Scenario 1: Smalltalk
# ========================================================================

def test_scenario_1_smalltalk():
    """Scenario 1: 'hey bantz nasılsın' - Smalltalk route."""
    
    # Mock LLM response
    mock_responses = {
        "nasılsın": {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "İyiyim efendim, teşekkür ederim. Size nasıl yardımcı olabilirim?",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı hal hatır sordu, karşılık verdim.",
            "reasoning_summary": ["Smalltalk girdi", "Samimi cevap verildi"],
        }
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = ToolRegistry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True, enable_preroute=False)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    user_input = "hey bantz nasılsın"
    output, state = loop.process_turn(user_input)
    
    # Assertions (metadata-based, not text-dependent)
    assert output.route == "smalltalk"
    assert output.calendar_intent == "none"
    assert output.confidence == 1.0
    assert len(output.tool_plan) == 0
    assert output.ask_user is False
    assert output.requires_confirmation is False
    assert len(output.assistant_reply) > 0  # Has response
    assert output.memory_update != ""  # LLM updated memory
    assert len(output.reasoning_summary) > 0  # Has reasoning
    
    # State checks
    assert state.rolling_summary != ""  # Summary updated
    assert len(state.conversation_history) == 1  # One turn
    assert state.trace.get("route_source") == "llm"  # Everything from LLM
    assert state.trace.get("route") == "smalltalk"


# ========================================================================
# Scenario 2: Calendar Query (today)
# ========================================================================

def test_scenario_2_calendar_query_today():
    """Scenario 2: 'bugün neler yapacağız bakalım' - Calendar query."""
    
    mock_responses = {
        "bugün": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today", "time_min": "2026-01-30T00:00:00+03:00", "time_max": "2026-01-30T23:59:59+03:00"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı bugünün programını sordu.",
            "reasoning_summary": ["Takvim sorgusu", "Bugün window'u", "list_events çağırılacak"],
        }
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_mock_tool_registry()  # Use mock tools
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    user_input = "bugün neler yapacağız bakalım"
    output, state = loop.process_turn(user_input)
    
    # Assertions
    assert output.route == "calendar"
    assert output.calendar_intent == "query"
    assert output.confidence >= 0.8
    assert "calendar.list_events" in output.tool_plan
    assert output.slots.get("window_hint") == "today"
    assert output.requires_confirmation is False  # Query doesn't need confirmation
    
    # State checks
    assert state.trace.get("route") == "calendar"
    assert state.trace.get("intent") == "query"
    assert state.trace.get("tool_plan_len") >= 1
    assert state.trace.get("tools_executed") >= 1  # Tool should have been executed


# ========================================================================
# Scenario 3: Calendar Create (requires confirmation)
# ========================================================================

def test_scenario_3_calendar_create_with_confirmation():
    """Scenario 3: 'saat 4 için bir toplantı oluştur' - Calendar create."""
    
    mock_responses = {
        "toplantı oluştur": {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {
                "time": "16:00",
                "title": "toplantı",
                "duration": None,
            },
            "confidence": 0.5,  # Low confidence due to missing duration
            "tool_plan": [],  # Empty because confidence < 0.7
            "assistant_reply": "",
            "ask_user": True,
            "question": "Toplantı ne kadar sürecek efendim? (örn: 30 dk, 1 saat)",
            "requires_confirmation": True,  # Create requires confirmation
            "confirmation_prompt": "Saat 16:00'da toplantı oluşturayım mı?",
            "memory_update": "Kullanıcı saat 4'e toplantı oluşturmak istedi, süre belirsiz.",
            "reasoning_summary": [
                "Saat belirsiz: 4 → 16:00 varsayıldı",
                "Süre eksik",
                "Önce netleştirme gerekli",
            ],
        }
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = ToolRegistry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    user_input = "saat 4 için bir toplantı oluştur"
    output, state = loop.process_turn(user_input)
    
    # Assertions
    assert output.route == "calendar"
    assert output.calendar_intent == "create"
    assert output.confidence < 0.7  # Low confidence
    assert output.ask_user is True  # Asking for clarification
    assert output.question != ""  # Has clarification question
    assert output.requires_confirmation is True  # Create needs confirmation
    assert output.confirmation_prompt != ""  # LLM generated confirmation text
    assert len(output.tool_plan) == 0  # No tools yet (confidence too low)
    
    # State checks
    assert state.trace.get("route") == "calendar"
    assert state.trace.get("intent") == "create"
    assert state.trace.get("requires_confirmation") is True
    assert state.trace.get("ask_user") is True


# ========================================================================
# Scenario 4: Calendar Query (evening window)
# ========================================================================

def test_scenario_4_calendar_query_evening():
    """Scenario 4: 'bu akşam neler yapacağız' - Evening window query."""
    
    mock_responses = {
        "bu akşam": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "evening"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı bu akşamın programını sordu.",
            "reasoning_summary": ["Evening window sorgusu", "list_events ile bakılacak"],
        }
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_mock_tool_registry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    user_input = "bu akşam neler yapacağız"
    output, state = loop.process_turn(user_input)
    
    # Assertions
    assert output.route == "calendar"
    assert output.calendar_intent == "query"
    assert output.slots.get("window_hint") == "evening"
    assert "calendar.list_events" in output.tool_plan
    assert output.confidence >= 0.8
    
    # State checks
    assert state.trace.get("route") == "calendar"
    assert state.trace.get("intent") == "query"


# ========================================================================
# Scenario 5: Calendar Query (week window)
# ========================================================================

def test_scenario_5_calendar_query_week():
    """Scenario 5: 'bu hafta planımda önemli işler var mı?' - Week window query."""
    
    mock_responses = {
        "bu hafta": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "week"},
            "confidence": 0.85,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "",
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "Kullanıcı bu haftanın önemli işlerini sordu.",
            "reasoning_summary": [
                "Week window sorgusu",
                "list_events ile bakılacak",
                "'Önemli' heuristic yanıtta uygulanacak",
            ],
        }
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_mock_tool_registry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    # Process turn
    user_input = "bu hafta planımda önemli işler var mı?"
    output, state = loop.process_turn(user_input)
    
    # Assertions
    assert output.route == "calendar"
    assert output.calendar_intent == "query"
    assert output.slots.get("window_hint") == "week"
    assert "calendar.list_events" in output.tool_plan
    assert output.confidence >= 0.8
    
    # State checks
    assert state.trace.get("route") == "calendar"
    assert state.trace.get("intent") == "query"


# ========================================================================
# Integration Test: Multi-turn with State Persistence
# ========================================================================

def test_multi_turn_state_persistence():
    """Test that state persists across multiple turns."""
    
    mock_responses = {
        "nasılsın": {
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "İyiyim efendim.",
            "memory_update": "Kullanıcı hal hatır sordu.",
            "reasoning_summary": ["Smalltalk"],
        },
        "bugün": {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": "",
            "memory_update": "Kullanıcı bugünün programını sordu.",
            "reasoning_summary": ["Takvim sorgusu"],
        },
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_mock_tool_registry()
    event_bus = EventBus()
    config = OrchestratorConfig(debug=True, enable_preroute=False)
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    state = OrchestratorState()
    
    # Turn 1: Smalltalk
    output1, state = loop.process_turn("nasılsın", state)
    assert output1.route == "smalltalk"
    assert len(state.conversation_history) == 1
    assert state.rolling_summary != ""
    
    # Turn 2: Calendar query
    output2, state = loop.process_turn("bugün neler yapacağız", state)
    assert output2.route == "calendar"
    assert len(state.conversation_history) == 2  # Both turns preserved
    assert "hal hatır sordu" in state.rolling_summary  # Previous turn remembered
    assert "bugünün programını sordu" in state.rolling_summary  # Current turn added


# ========================================================================
# Confirmation Firewall Test
# ========================================================================

def test_confirmation_firewall():
    """Test that destructive tools require confirmation."""
    
    mock_responses = {
        "etkinlik oluştur": {
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "14:00", "title": "toplantı", "duration": 60},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "",
            "requires_confirmation": True,
            "confirmation_prompt": "Saat 14:00'da toplantı oluşturayım mı?",
            "memory_update": "Kullanıcı toplantı oluşturmak istedi.",
            "reasoning_summary": ["Tüm slotlar dolu", "Onay gerekli"],
        }
    }
    
    mock_llm = MockLLMClient(mock_responses)
    orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
    tools = build_mock_tool_registry()
    event_bus = EventBus()
    config = OrchestratorConfig(
        debug=True,
        require_confirmation_for=["calendar.create_event"],
    )
    
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    state = OrchestratorState()
    
    # Process turn (first time - should NOT execute tool)
    output, state = loop.process_turn("yarın ikide etkinlik oluştur", state)
    
    # Assertions
    assert output.requires_confirmation is True
    assert output.confirmation_prompt != ""
    assert state.has_pending_confirmation()
    assert state.pending_confirmations[0]["tool"] == "calendar.create_event"
    
    # Tool should NOT have been executed yet
    # (In real scenario, user would confirm, then tool executes on next turn)
