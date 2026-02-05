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
        return '{"route": "unknown", "calendar_intent": "none", "slots": {}, "confidence": 0.0, "tool_plan": [], "assistant_reply": "Anlayamadım."}'


def test_router_smalltalk():
    """Scenario 1: 'hey bantz nasılsın' → smalltalk, no tools."""
    llm = MockLLM({
        "hey bantz nasılsın": '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "İyiyim efendim, teşekkür ederim."}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="hey bantz nasılsın")
    
    assert result.route == "smalltalk"
    assert result.calendar_intent == "none"
    assert result.confidence == 1.0
    assert result.tool_plan == []
    assert "İyiyim efendim" in result.assistant_reply


def test_router_calendar_query_today():
    """Scenario 2: 'bugün neler yapacağız bakalım' → calendar query, list_events tool."""
    llm = MockLLM({
        "bugün neler yapacağız bakalım": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="bugün neler yapacağız bakalım")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert result.slots.get("window_hint") == "today"
    assert result.confidence == 0.9
    assert result.tool_plan == ["calendar.list_events"]


def test_router_calendar_create_low_confidence():
    """Scenario 3: 'saat 4 için bir toplantı oluştur' → low confidence, ask for duration."""
    llm = MockLLM({
        "saat 4 için bir toplantı oluştur": '{"route": "calendar", "calendar_intent": "create", "slots": {"time": "16:00", "title": "toplantı", "duration": null}, "confidence": 0.5, "tool_plan": [], "assistant_reply": "Süre ne olsun efendim? (örn. 30 dk / 1 saat)"}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="saat 4 için bir toplantı oluştur")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "create"
    assert result.slots.get("time") == "16:00"
    assert result.slots.get("title") == "toplantı"
    assert result.slots.get("duration") is None
    assert result.confidence == 0.5
    # Tool plan cleared due to low confidence
    assert result.tool_plan == []
    assert "Süre ne olsun" in result.assistant_reply


def test_router_calendar_query_evening():
    """Scenario 4: 'bu akşam neler yapacağız' → evening window, list_events."""
    llm = MockLLM({
        "bu akşam neler yapacağız": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "evening"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="bu akşam neler yapacağız")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert result.slots.get("window_hint") == "evening"
    assert result.confidence == 0.9
    assert result.tool_plan == ["calendar.list_events"]


def test_router_calendar_query_week():
    """Scenario 5: 'bu hafta planımda önemli işler var mı?' → week window, list_events."""
    llm = MockLLM({
        "bu hafta planımda önemli işler var mı?": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "week"}, "confidence": 0.8, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="bu hafta planımda önemli işler var mı?")
    
    assert result.route == "calendar"
    assert result.calendar_intent == "query"
    assert result.slots.get("window_hint") == "week"
    assert result.confidence == 0.8
    assert result.tool_plan == ["calendar.list_events"]


def test_router_confidence_threshold_blocks_tools():
    """Low confidence blocks tool execution."""
    llm = MockLLM({
        "belirsiz sorgu": '{"route": "calendar", "calendar_intent": "query", "slots": {}, "confidence": 0.6, "tool_plan": ["calendar.list_events"], "assistant_reply": "Hangi tarih efendim?"}'
    })
    
    router = JarvisLLMRouter(llm=llm, confidence_threshold=0.7)
    result = router.route(user_input="belirsiz sorgu")
    
    assert result.confidence == 0.6
    # Tool plan cleared due to confidence < threshold
    assert result.tool_plan == []
    assert "Hangi tarih" in result.assistant_reply


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
    assert "anlayamadım" in result.assistant_reply.lower()


def test_router_with_dialog_summary():
    """Router receives dialog summary for context."""
    llm = MockLLM({
        "devam et": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })
    
    router = JarvisLLMRouter(llm=llm)
    result = router.route(
        user_input="devam et",
        dialog_summary="User: Yarın planım var mı? | Tools: calendar.list_events | Result: say",
    )
    
    # Verify dialog summary is in prompt
    assert len(llm.calls) == 1
    assert "DIALOG_SUMMARY" in llm.calls[0]
    
    assert result.route == "calendar"
    assert result.tool_plan == ["calendar.list_events"]


def test_router_with_retrieved_memory_block():
    """Router receives retrieved memory for context."""
    llm = MockLLM({
        "devam et": '{"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}'
    })

    router = JarvisLLMRouter(llm=llm)
    _ = router.route(
        user_input="devam et",
        dialog_summary="User: Yarın planım var mı? | Tools: calendar.list_events | Result: say",
        retrieved_memory="- [PROFILE] Kullanıcı kısa cevap sever.\n- [EPISODIC] Dün takvimde koşu eklendi.",
    )

    assert len(llm.calls) == 1
    assert "RETRIEVED_MEMORY" in llm.calls[0]
    assert "talimat değildir" in llm.calls[0]
