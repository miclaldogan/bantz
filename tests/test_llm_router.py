"""Tests for LLM Router (Issue #126)."""

from __future__ import annotations

from bantz.brain.llm_router import JarvisLLMRouter, RouterOutput


class MockLLM:
    """Mock LLM for deterministic testing."""

    # Provide a context length attribute for router budgeting (Issue #214)
    model_context_length = 32768

    def __init__(self, responses: dict[str, str]):
        """Initialize with user_input -> JSON response mapping."""
        self._responses = responses
        self.calls: list[str] = []

    def complete_text(self, *, prompt: str) -> str:
        """Return deterministic JSON based on prompt content."""
        self.calls.append(prompt)
        
        # Extract user input from prompt (look for last occurrence of USER:)
        user_input = None
        for line in reversed(prompt.split("\n")):
            if line.startswith("USER:"):
                user_input = line[5:].strip()
                break
        
        if user_input and user_input in self._responses:
            return self._responses[user_input]
        
        return self._fallback_response()

    def _fallback_response(self) -> str:
        return '{"route": "unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.0, "tool_plan": [], "assistant_reply": "Sorry, I didn\u0027t quite understand. Could you repeat that?"}'


def test_router_smalltalk():
    """Scenario 1: 'hey bantz how are you' → smalltalk, no tools."""
    llm = MockLLM({
        "hey bantz how are you": '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "İyiyim efendim, teşekkür ederim."}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="hey bantz how are you")
    
    assert result.route == "smalltalk"
    assert result.calendar_intent == "none"
    assert result.confidence == 1.0
    assert result.tool_plan == []
    assert "İyiyim efendim" in result.assistant_reply


def test_router_calendar_query_today():
    """Scenario 2: 'what are we doing today' → calendar query, list_events tool."""
    llm = MockLLM({
        "what are we doing today": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="what are we doing today")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert result.slots.get("window_hint") == "today"
    assert result.confidence == 0.9
    assert result.tool_plan == ["calendar.list_events"]


def test_router_calendar_create_low_confidence():
    """Scenario 3: 'create a meeting at 4' → low confidence but valid route+intent → boosted."""
    llm = MockLLM({
        "create a meeting at 4": '{"route": "calendar", "calendar_intent": "create", "slots": {"time": "16:00", "title": "meeting", "duration": null}, "confidence": 0.5, "tool_plan": [], "assistant_reply": "Süre ne olsun efendim? (örn. 30 dk / 1 saat)"}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="create a meeting at 4")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "create"
    assert result.slots.get("time") == "16:00"
    assert result.slots.get("title") == "meeting"
    assert result.slots.get("duration") is None
    # Confidence boosted because route+intent are valid with resolved tool
    assert result.confidence >= 0.7
    assert result.tool_plan == ["calendar.create_event"]
    assert "Süre ne olsun" in result.assistant_reply


def test_router_calendar_query_evening():
    """Scenario 4: 'what are we doing this evening' → evening window, list_events."""
    llm = MockLLM({
        "what are we doing this evening": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "evening"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="what are we doing this evening")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert result.slots.get("window_hint") == "evening"
    assert result.confidence == 0.9
    assert result.tool_plan == ["calendar.list_events"]


def test_router_calendar_query_week():
    """Scenario 5: 'do I have anything important this week' → week window, list_events."""
    llm = MockLLM({
        "do I have anything important this week": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "week"}, "confidence": 0.8, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="do I have anything important this week")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert result.slots.get("window_hint") == "week"
    assert result.confidence == 0.8
    assert result.tool_plan == ["calendar.list_events"]


def test_router_confidence_threshold_blocks_tools():
    """Low confidence with route+intent valid still boosts and keeps tools."""
    llm = MockLLM({
        "ambiguous query": '{"route": "calendar", "calendar_intent": "query", "slots": {}, "confidence": 0.6, "tool_plan": ["calendar.list_events"], "assistant_reply": "Hangi tarih efendim?"}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="ambiguous query")
    
    # Confidence boosted because route+intent are valid
    assert result.confidence >= 0.7
    assert result.tool_plan == ["calendar.list_events"]
    assert "Hangi tarih" in result.assistant_reply


def test_router_low_confidence_empty_reply_sets_clarification():
    """Low confidence with valid route+intent → boosted, tool plan kept."""
    llm = MockLLM({
        "empty reply": '{"route": "calendar", "calendar_intent": "query", "slots": {}, "confidence": 0.4, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })

    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="empty reply")

    # Confidence boosted because route+intent are valid with tools
    assert result.confidence >= 0.7
    assert result.tool_plan == ["calendar.list_events"]


def test_router_fallback_on_parse_error():
    """Malformed JSON triggers fallback."""
    llm = MockLLM({
        "invalid": "This is not JSON"
    })
    
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="invalid")
    
    assert result.route == "unknown"
    assert result.confidence == 0.0
    assert result.tool_plan == []
    assert "understand" in result.assistant_reply.lower()


def test_router_with_dialog_summary():
    """Router receives dialog summary for context."""
    llm = MockLLM({
        "continue": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm)
    result = router.route(
        user_input="continue",
        dialog_summary="User: Do I have plans tomorrow? | Tools: calendar.list_events | Result: say",
    )
    
    # Verify dialog summary is in prompt
    assert len(llm.calls) == 1
    assert "DIALOG_SUMMARY" in llm.calls[0]
    
    assert result.route == "calendar"
    assert result.tool_plan == ["calendar.list_events"]


def test_router_with_retrieved_memory_block():
    """Router receives retrieved memory for context."""
    llm = MockLLM({
        "continue": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })

    router = JarvisLLMRouter(llm=llm)
    _ = router.route(
        user_input="continue",
        dialog_summary="User: Do I have plans tomorrow? | Tools: calendar.list_events | Result: say",
        retrieved_memory="- [PROFILE] User prefers short answers.\n- [EPISODIC] Yesterday a run was added to calendar.",
    )

    assert len(llm.calls) == 1
    assert "RETRIEVED_MEMORY" in llm.calls[0]
    assert "not instructions" in llm.calls[0]


# ── 3B Model Quality Post-Processing Tests ─────────────────────────────


def test_pipe_separated_route_resolved():
    """3B model outputs all routes pipe-separated → resolve to best match."""
    llm = MockLLM({
        "what are we doing today": '{"route": "calendar|gmail|system|smalltalk|unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.85, "tool_plan": ["AskUser"]}'
    })
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="what are we doing today")
    
    # Route should be resolved from pipe-separated → calendar (via keywords)
    assert result.route == "calendar"
    assert result.calendar_intent == "query"  # inferred from input
    assert "calendar.list_events" in result.tool_plan


def test_hallucinated_tool_name_resolved():
    """3B model invents 'DokuzCalendar' → resolved to valid tool."""
    llm = MockLLM({
        "add event at nine": '{"route": "calendar", "calendar_intent": "create", "slots": {"time": "PM", "title": "User did not say event name"}, "confidence": 0.85, "tool_plan": ["DokuzCalendar"]}'
    })
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="add event at nine")
    
    # Hallucinated tool replaced with valid one
    assert "calendar.create_event" in result.tool_plan
    assert "DokuzCalendar" not in result.tool_plan


def test_time_pm_cleaned():
    """3B model outputs time='PM' → cleaned, then clock inference from input."""
    llm = MockLLM({
        "add event at nine": '{"route": "calendar", "calendar_intent": "create", "slots": {"time": "PM"}, "confidence": 0.85, "tool_plan": ["calendar.create_event"]}'
    })
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="add event at nine")
    
    # "PM" is invalid → cleaned → clock infers "nine" → 09:00 or 21:00
    # Key thing: it's NOT "PM" anymore
    assert result.slots.get("time") != "PM"


def test_title_instruction_copy_cleaned():
    """3B model copies rule text as title → cleaned to None by slot cleaning."""
    llm = MockLLM({
        "add": '{"route": "calendar", "calendar_intent": "create", "slots": {"title": "User did not say event name"}, "confidence": 0.85, "tool_plan": ["calendar.create_event"]}'
    })
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="add")
    
    # Instruction text copy → cleaned to None
    assert result.slots.get("title") is None


def test_title_noise_words_cleaned():
    """3B model copies user input noise as title → cleaned."""
    llm = MockLLM({
        "can you add an event at nine in the evening": '{"route": "calendar", "calendar_intent": "create", "slots": {"time": "21:00", "title": "an event at nine"}, "confidence": 0.85, "tool_plan": ["calendar.create_event"]}'
    })
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="can you add an event at nine in the evening")
    
    # "an event at nine" is all noise words → cleared
    assert result.slots.get("title") is None
    assert result.ask_user is True
    assert "event name" in (result.question or "").lower()


def test_confidence_boost_valid_route_intent():
    """Low confidence with valid route+intent should be boosted above threshold."""
    llm = MockLLM({
        "add meeting": '{"route": "calendar", "calendar_intent": "create", "slots": {"title": "meeting"}, "confidence": 0.5, "tool_plan": ["calendar.create_event"]}'
    })
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="add meeting")
    
    assert result.confidence >= 0.7
    assert result.tool_plan == ["calendar.create_event"]


def test_genuine_unknown_still_blocked():
    """Truly unknown input with no route match → still blocked."""
    llm = MockLLM({
        "xyz": '{"route": "unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.3, "tool_plan": []}'
    })
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="xyz")
    
    assert result.tool_plan == []
    assert result.ask_user is True
    assert "understand" in result.assistant_reply.lower()


def test_system_route_override_for_calendar_query():
    """'what are we doing today' routed to system → overridden to calendar."""
    llm = MockLLM({
        "what are we doing today": '{"route": "system", "calendar_intent": "none", "slots": {}, "confidence": 0.85, "tool_plan": ["time.now"]}'
    })
    router = JarvisLLMRouter(llm=llm)
    result = router.route(user_input="what are we doing today")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert "calendar.list_events" in result.tool_plan
