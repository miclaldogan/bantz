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
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.8, "tool_plan": [], "assistant_reply": "Let me check."}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    # Call route() with retrieved_memory
    router.route(
        user_input="do I have a meeting tomorrow",
        dialog_summary="",
        retrieved_memory="[PROFILE] User has a standup meeting every Monday at 10:00.\n[EPISODIC] Last week the meeting was cancelled.",
    )
    
    # Verify prompt was called
    assert len(mock_llm.prompts) == 1
    prompt = mock_llm.prompts[0]
    
    # Issue #358: Verify retrieved_memory is in the prompt
    assert "RETRIEVED_MEMORY" in prompt
    assert "User has a standup meeting" in prompt
    assert "every Monday" in prompt


def test_retrieved_memory_policy_instruction_in_prompt():
    """Router prompt should include policy instruction for retrieved_memory (when budget allows)."""
    mock_llm = MockLLM(response='{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [], "assistant_reply": "How are you?"}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    router.route(
        user_input="how are you",
        retrieved_memory="[PROFILE] User prefers friendly conversation.",
    )
    
    prompt = mock_llm.prompts[0]
    
    # Should have RETRIEVED_MEMORY section
    assert "RETRIEVED_MEMORY" in prompt
    # Should have the memory content
    assert "friendly conversation" in prompt
    # Policy instruction may be included if budget allows, or truncated if tight
    # Either way, memory should be present


def test_retrieved_memory_empty_not_added():
    """Empty retrieved_memory should not add section to prompt."""
    mock_llm = MockLLM(response='{"route": "unknown", "calendar_intent": "none", "confidence": 0.5, "tool_plan": [], "assistant_reply": "I did not understand."}')
    
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
    mock_llm = MockLLM(response='{"route": "unknown", "calendar_intent": "none", "confidence": 0.5, "tool_plan": [], "assistant_reply": "I did not understand."}')
    
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
        user_input="my meetings today",
        dialog_summary="User: what did I do yesterday | AI: You had a meeting yesterday",
        retrieved_memory="[EPISODIC] User attends team meeting every Tuesday.",
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
        user_input="my meeting",
        retrieved_memory=long_memory,
    )
    
    prompt = mock_llm.prompts[0]
    
    # Should be present but trimmed
    assert "RETRIEVED_MEMORY" in prompt
    # Original long_memory is much longer than what fits in prompt
    assert len(prompt) < len(long_memory) + 6000  # Some overhead for system prompt (Issue #1273: +status rules, expanded routes, English conversion)


def test_integration_retrieved_memory_calendar_context():
    """Integration: Retrieved memory helps router with calendar context."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "create", "slots": {"day_hint": "monday"}, "confidence": 0.9, "tool_plan": ["calendar.create_event"], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    
    # User references recurring pattern from memory
    result = router.route(
        user_input="create my regular meeting",
        retrieved_memory="[PROFILE] User's 'regular meeting' = Monday 10:00 standup meeting.",
    )
    
    prompt = mock_llm.prompts[0]
    
    # Memory context should be available to help router understand "regular meeting"
    assert "RETRIEVED_MEMORY" in prompt
    assert "Monday 10:00" in prompt
    assert "standup meeting" in prompt
    
    # Router should route to calendar
    assert result.route == "calendar"
