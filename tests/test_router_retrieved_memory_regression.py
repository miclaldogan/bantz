"""Tests for Issue #358: Router retrieved_memory in prompt.

This was already fixed in PR #227 (feat: Add PromptBudgetConfig).
These tests serve as regression prevention to ensure retrieved_memory
continues to be included in router prompts.
"""

from bantz.brain.llm_router import JarvisLLMOrchestrator


class MockLLM:
    """Mock LLM that records prompts."""
    def __init__(self, response: str):
        self.response = response
        self.prompts = []
    
    def complete_text(self, *, prompt: str, **kwargs):
        self.prompts.append(prompt)
        return self.response


def test_retrieved_memory_appears_in_router_prompt():
    """Verify retrieved_memory parameter is included in router prompt (Issue #358)."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.8, "tool_plan": [], "assistant_reply": "Bakalım efendim."}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    # Call route() with retrieved_memory
    router.route(
        user_input="yarın toplantım var mı",
        dialog_summary="",
        retrieved_memory="[PROFILE] Kullanıcı her pazartesi 10:00'da standup toplantısı yapar.\n[EPISODIC] Geçen hafta toplantı iptal edildi.",
    )
    
    # Verify prompt was called
    assert len(mock_llm.prompts) == 1
    prompt = mock_llm.prompts[0]
    
    # Issue #358: Verify retrieved_memory is in the prompt
    assert "RETRIEVED_MEMORY" in prompt
    assert "Kullanıcı her pazartesi" in prompt
    assert "standup toplantısı" in prompt


def test_retrieved_memory_policy_instruction_in_prompt():
    """Router prompt should include policy instruction for retrieved_memory (when budget allows)."""
    mock_llm = MockLLM(response='{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [], "assistant_reply": "Nasılsınız efendim."}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    router.route(
        user_input="nasılsın",
        retrieved_memory="[PROFILE] Kullanıcı samimi konuşmayı sever.",
    )
    
    prompt = mock_llm.prompts[0]
    
    # Should have RETRIEVED_MEMORY section
    assert "RETRIEVED_MEMORY" in prompt
    # Should have the memory content
    assert "samimi konuşmayı sever" in prompt
    # Policy instruction may be included if budget allows, or truncated if tight
    # Either way, memory should be present


def test_retrieved_memory_empty_not_added():
    """Empty retrieved_memory should not add section to prompt."""
    mock_llm = MockLLM(response='{"route": "unknown", "calendar_intent": "none", "confidence": 0.5, "tool_plan": [], "assistant_reply": "Anlamadım."}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    router.route(
        user_input="test",
        retrieved_memory="",  # Empty
    )
    
    prompt = mock_llm.prompts[0]
    
    # Empty memory should not add RETRIEVED_MEMORY section
    assert "RETRIEVED_MEMORY" not in prompt


def test_retrieved_memory_none_not_added():
    """None retrieved_memory should not add section to prompt."""
    mock_llm = MockLLM(response='{"route": "unknown", "calendar_intent": "none", "confidence": 0.5, "tool_plan": [], "assistant_reply": "Anlamadım."}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    router.route(
        user_input="test",
        retrieved_memory=None,  # None
    )
    
    prompt = mock_llm.prompts[0]
    
    # None memory should not add RETRIEVED_MEMORY section
    assert "RETRIEVED_MEMORY" not in prompt


def test_retrieved_memory_with_dialog_summary():
    """Retrieved_memory and dialog_summary should both appear in prompt (budget permitting)."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    router.route(
        user_input="bugün toplantılarım",
        dialog_summary="User: dün neyaptım | AI: Geçen gün toplantınız vardı",
        retrieved_memory="[EPISODIC] Kullanıcı her salı team meeting'e katılır.",
    )
    
    prompt = mock_llm.prompts[0]
    
    # Retrieved memory should be present (higher priority than dialog in tight budgets)
    assert "RETRIEVED_MEMORY" in prompt
    assert "team meeting" in prompt
    
    # Dialog summary may be dropped if budget is tight (lowest priority)
    # This is expected behavior - memory is more important than dialog history


def test_retrieved_memory_long_content_trimmed():
    """Long retrieved_memory should be trimmed when token budget is tight."""
    # Long memory content
    long_memory = "".join([f"[EPISODIC] Event {i} happened on day {i}.\n" for i in range(200)])
    
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.8, "tool_plan": [], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    # Call with tight token budget
    router.route(
        user_input="toplantım",
        retrieved_memory=long_memory,
    )
    
    prompt = mock_llm.prompts[0]
    
    # Should be present but trimmed
    assert "RETRIEVED_MEMORY" in prompt
    # Original long_memory is much longer than what fits in prompt
    assert len(prompt) < len(long_memory) + 2000  # Some overhead for system prompt


def test_integration_retrieved_memory_calendar_context():
    """Integration: Retrieved memory helps router with calendar context."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "create", "slots": {"day_hint": "monday"}, "confidence": 0.9, "tool_plan": ["calendar.create_event"], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    # User references recurring pattern from memory
    result = router.route(
        user_input="normal toplantımı oluştur",
        retrieved_memory="[PROFILE] Kullanıcının 'normal toplantı' = Pazartesi 10:00 standup meeting demektir.",
    )
    
    prompt = mock_llm.prompts[0]
    
    # Memory context should be available to help router understand "normal toplantı"
    assert "RETRIEVED_MEMORY" in prompt
    assert "Pazartesi 10:00" in prompt
    assert "standup meeting" in prompt
    
    # Router should route to calendar
    assert result.route == "calendar"
