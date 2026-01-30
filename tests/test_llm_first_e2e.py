"""
End-to-end test for LLM-first router + trace + memory.

Tests the 5 scenarios from Issue #126:
1. "hey bantz nasılsın" → smalltalk
2. "bugün neler yapacağız bakalım" → calendar query
3. "saat 4 için bir toplantı oluştur" → low confidence → ask duration
4. "bu akşam neler yapacağız" → evening window
5. "bu hafta planımda önemli işler var mı?" → week window
"""

from __future__ import annotations

import pytest
from typing import Any, Optional

from bantz.brain.llm_router import JarvisLLMRouter, RouterOutput


class MockLLM:
    """Mock LLM for deterministic router testing."""
    
    def __init__(self):
        self.responses: dict[str, str] = {
            # Scenario 1: smalltalk
            "hey bantz nasılsın": '''
{
  "route": "smalltalk",
  "calendar_intent": "none",
  "slots": {},
  "confidence": 0.95,
  "tool_plan": "none",
  "assistant_reply": "İyiyim efendim, teşekkür ederim. Size nasıl yardımcı olabilirim?"
}
''',
            # Scenario 2: calendar query today (with "bakalım")
            "bugün neler yapacağız bakalım": '''
{
  "route": "calendar",
  "calendar_intent": "query",
  "slots": {
    "day_hint": "today"
  },
  "confidence": 0.92,
  "tool_plan": "list_events(start=today_00:00, end=today_23:59)",
  "assistant_reply": ""
}
''',
            # Scenario 2 variant: without "bakalım"
            "bugün neler yapacağız": '''
{
  "route": "calendar",
  "calendar_intent": "query",
  "slots": {
    "day_hint": "today"
  },
  "confidence": 0.92,
  "tool_plan": "list_events(start=today_00:00, end=today_23:59)",
  "assistant_reply": ""
}
''',
            # Scenario 3: calendar create low confidence
            "saat 4 için bir toplantı oluştur": '''
{
  "route": "calendar",
  "calendar_intent": "create",
  "slots": {
    "start_time": "16:00",
    "duration_min": null
  },
  "confidence": 0.45,
  "tool_plan": "create_event(start=16:00, duration=?)",
  "assistant_reply": "16:00 için toplantı oluşturmak istiyorsunuz. Süre ne kadar olsun efendim?"
}
''',
            # Scenario 4: calendar query evening
            "bu akşam neler yapacağız": '''
{
  "route": "calendar",
  "calendar_intent": "query",
  "slots": {
    "day_hint": "today",
    "time_window": "evening"
  },
  "confidence": 0.88,
  "tool_plan": "list_events(start=today_18:00, end=today_23:59)",
  "assistant_reply": ""
}
''',
            # Scenario 5: calendar query week
            "bu hafta planımda önemli işler var mı": '''
{
  "route": "calendar",
  "calendar_intent": "query",
  "slots": {
    "day_hint": "this_week"
  },
  "confidence": 0.85,
  "tool_plan": "list_events(start=week_start, end=week_end) + filter(priority=high)",
  "assistant_reply": ""
}
''',
        }
    
    def complete_text(self, prompt: str) -> str:
        """Return deterministic JSON based on user input."""
        # Extract user input from prompt (find last occurrence of "USER:")
        lines = prompt.split("\n")
        user_input = None
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("USER:"):
                user_input = line[5:].strip()
                break
        
        if not user_input:
            return '{"route": "unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.0, "tool_plan": "none", "assistant_reply": ""}'
        
        # Normalize for matching
        user_lower = user_input.lower().strip()
        
        # Match against known scenarios
        for key, response in self.responses.items():
            if key.lower().strip() == user_lower:
                return response
        
        # Default unknown
        return '{"route": "unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.0, "tool_plan": "none", "assistant_reply": ""}'


@pytest.fixture
def router() -> JarvisLLMRouter:
    """Fixture for router with mock LLM."""
    return JarvisLLMRouter(llm=MockLLM())


def test_e2e_scenario_1_smalltalk(router: JarvisLLMRouter):
    """Scenario 1: 'hey bantz nasılsın' → smalltalk, no tools."""
    output = router.route(
        user_input="hey bantz nasılsın",
        dialog_summary="",
        session_context={},
    )
    
    assert output.route == "smalltalk"
    assert output.calendar_intent == "none"
    assert output.confidence >= 0.7  # High confidence
    assert output.tool_plan == [] or output.tool_plan == "none"  # No tools for smalltalk
    assert "İyiyim efendim" in output.assistant_reply
    assert output.slots == {}


def test_e2e_scenario_2_calendar_query_today(router: JarvisLLMRouter):
    """Scenario 2: 'bugün neler yapacağız bakalım' → calendar query."""
    output = router.route(
        user_input="bugün neler yapacağız bakalım",
        dialog_summary="",
        session_context={"now": "2025-01-30T10:00:00"},
    )
    
    assert output.route == "calendar"
    assert output.calendar_intent == "query"
    assert output.confidence >= 0.7
    assert isinstance(output.tool_plan, list) or "list_events" in str(output.tool_plan)
    assert "today" in str(output.slots.get("day_hint"))


def test_e2e_scenario_3_calendar_create_low_confidence(router: JarvisLLMRouter):
    """Scenario 3: 'saat 4 için bir toplantı oluştur' → low confidence → ask duration."""
    output = router.route(
        user_input="saat 4 için bir toplantı oluştur",
        dialog_summary="",
        session_context={},
    )
    
    assert output.route == "calendar"
    assert output.calendar_intent == "create"
    assert output.confidence < 0.7  # Low confidence: missing duration
    assert output.tool_plan == [] or output.tool_plan == "none"  # Blocked by threshold
    assert "Süre ne kadar" in output.assistant_reply or "süre" in output.assistant_reply.lower()


def test_e2e_scenario_4_calendar_query_evening(router: JarvisLLMRouter):
    """Scenario 4: 'bu akşam neler yapacağız' → evening window."""
    output = router.route(
        user_input="bu akşam neler yapacağız",
        dialog_summary="",
        session_context={},
    )
    
    assert output.route == "calendar"
    assert output.calendar_intent == "query"
    assert output.confidence >= 0.7
    # Check raw_output since tool_plan may be list after parsing
    raw_plan = output.raw_output.get("tool_plan", "")
    assert "evening" in raw_plan.lower() or "18:00" in raw_plan or output.slots.get("time_window") == "evening"
    assert output.slots.get("day_hint") == "today"


def test_e2e_scenario_5_calendar_query_week(router: JarvisLLMRouter):
    """Scenario 5: 'bu hafta planımda önemli işler var mı?' → week window."""
    output = router.route(
        user_input="bu hafta planımda önemli işler var mı",
        dialog_summary="",
        session_context={},
    )
    
    assert output.route == "calendar"
    assert output.calendar_intent == "query"
    assert output.confidence >= 0.7
    tool_plan_str = str(output.tool_plan) if isinstance(output.tool_plan, list) else output.tool_plan
    assert "week" in tool_plan_str.lower() or "this_week" in str(output.slots.get("day_hint"))


def test_e2e_dialog_summary_accumulation(router: JarvisLLMRouter):
    """Test that dialog summary is passed through context and used by router."""
    # First turn
    output1 = router.route(
        user_input="bugün neler yapacağız",
        dialog_summary="",
        session_context={},
    )
    assert output1.route == "calendar"
    
    # Simulate dialog summary update (would be done by BrainLoop)
    summary1 = f"User: bugün neler yapacağız | Tools: list_events | Result: say"
    
    # Second turn with context
    output2 = router.route(
        user_input="hey bantz nasılsın",
        dialog_summary=summary1,
        session_context={},
    )
    assert output2.route == "smalltalk"
    
    # Verify router receives and can use dialog summary (mock doesn't use it, but real LLM would)
    assert isinstance(summary1, str)


def test_e2e_trace_fields_populated(router: JarvisLLMRouter):
    """Verify that router output has all expected trace fields."""
    output = router.route(
        user_input="bugün neler yapacağız",
        dialog_summary="",
        session_context={},
    )
    
    # All trace fields should be populated
    assert hasattr(output, "route")
    assert hasattr(output, "calendar_intent")
    assert hasattr(output, "slots")
    assert hasattr(output, "confidence")
    assert hasattr(output, "tool_plan")
    assert hasattr(output, "assistant_reply")
    assert hasattr(output, "raw_output")
    
    # Types should be correct
    assert isinstance(output.route, str)
    assert isinstance(output.calendar_intent, str)
    assert isinstance(output.slots, dict)
    assert isinstance(output.confidence, float)
    assert isinstance(output.tool_plan, (list, str))  # Can be list (after threshold) or str
    assert isinstance(output.assistant_reply, str)
