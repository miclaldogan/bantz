"""Regression tests for Issue #360: tool_plan args preservation

Problem: When LLM returns tool_plan with args like [{"name": "gmail.send", "args": {...}}],
         the _extract_output() function only extracts names, losing args completely.
         
Solution: Added tool_plan_with_args field to OrchestratorOutput to preserve full dicts.
"""

import pytest
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput


class MockLLM:
    """Mock LLM for testing."""
    def __init__(self, response: str):
        self.response = response
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        return self.response


def test_tool_plan_string_list():
    """tool_plan as list of strings should work (backward compat)."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": ["calendar.list_events", "calendar.find_free_slots"], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="show my meetings")
    
    # Tool plan should have names
    assert output.tool_plan == ["calendar.list_events", "calendar.find_free_slots"]
    
    # tool_plan_with_args should be populated with empty args
    assert len(output.tool_plan_with_args) == 2
    assert output.tool_plan_with_args[0] == {"name": "calendar.list_events", "args": {}}
    assert output.tool_plan_with_args[1] == {"name": "calendar.find_free_slots", "args": {}}


def test_tool_plan_dict_with_args():
    """tool_plan as dicts with args should preserve args (Issue #360)."""
    mock_llm = MockLLM(response='{"route": "gmail", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [{"name": "gmail.send", "args": {"to": "alice@example.com", "subject": "Test"}}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="send email to alice")
    
    # Tool plan should have name (backward compat)
    assert output.tool_plan == ["gmail.send"]
    
    # tool_plan_with_args should have full dict WITH args
    assert len(output.tool_plan_with_args) == 1
    assert output.tool_plan_with_args[0]["name"] == "gmail.send"
    assert output.tool_plan_with_args[0]["args"] == {
        "to": "alice@example.com",
        "subject": "Test"
    }


def test_tool_plan_mixed_strings_and_dicts():
    """tool_plan with mix of strings and dicts should work."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": ["calendar.list_events", {"name": "calendar.find_free_slots", "args": {"duration_minutes": 30}}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="meetings and free slots")
    
    # Tool plan should have both names
    assert output.tool_plan == ["calendar.list_events", "calendar.find_free_slots"]
    
    # tool_plan_with_args: first has no args, second has args
    assert len(output.tool_plan_with_args) == 2
    assert output.tool_plan_with_args[0] == {"name": "calendar.list_events", "args": {}}
    assert output.tool_plan_with_args[1] == {
        "name": "calendar.find_free_slots",
        "args": {"duration_minutes": 30}
    }


def test_tool_plan_args_complex_nested():
    """tool_plan with complex nested args should be preserved."""
    mock_llm = MockLLM(response='{"route": "gmail", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [{"name": "gmail.send", "args": {"to": ["alice@ex.com", "bob@ex.com"], "cc": ["charlie@ex.com"], "body": "Hello world", "attachments": [{"filename": "doc.pdf", "size": 1024}]}}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="send complex email")
    
    # Tool plan name
    assert output.tool_plan == ["gmail.send"]
    
    # Complex args preserved
    assert len(output.tool_plan_with_args) == 1
    args = output.tool_plan_with_args[0]["args"]
    
    assert args["to"] == ["alice@ex.com", "bob@ex.com"]
    assert args["cc"] == ["charlie@ex.com"]
    assert args["body"] == "Hello world"
    assert args["attachments"] == [{"filename": "doc.pdf", "size": 1024}]


def test_tool_plan_empty_args():
    """tool_plan dict with empty args should be handled."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": [{"name": "calendar.list_events", "args": {}}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="my meetings")
    
    assert output.tool_plan == ["calendar.list_events"]
    assert output.tool_plan_with_args == [{"name": "calendar.list_events", "args": {}}]


def test_tool_plan_dict_missing_args_field():
    """tool_plan dict without 'args' field should default to empty args."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": [{"name": "calendar.list_events"}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="my meetings")
    
    assert output.tool_plan == ["calendar.list_events"]
    # Missing args should default to {}
    assert output.tool_plan_with_args == [{"name": "calendar.list_events", "args": {}}]


def test_tool_plan_dict_invalid_args_type():
    """tool_plan dict with non-dict args should default to empty args."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": [{"name": "calendar.list_events", "args": "invalid"}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="my meetings")
    
    assert output.tool_plan == ["calendar.list_events"]
    # Invalid args type should default to {}
    assert output.tool_plan_with_args == [{"name": "calendar.list_events", "args": {}}]


def test_tool_plan_alternative_name_fields():
    """tool_plan dict with 'tool' or 'tool_name' instead of 'name' should work."""
    # Using 'tool' field
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": [{"tool": "calendar.list_events", "args": {"max": 10}}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="meetings")
    
    assert output.tool_plan == ["calendar.list_events"]
    assert output.tool_plan_with_args == [{"name": "calendar.list_events", "args": {"max": 10}}]


def test_tool_plan_empty_list():
    """tool_plan as empty list should work."""
    mock_llm = MockLLM(response='{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [], "assistant_reply": "Merhaba efendim"}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="hello")
    
    assert output.tool_plan == []
    assert output.tool_plan_with_args == []


def test_tool_plan_none():
    """tool_plan as None should default to empty lists."""
    mock_llm = MockLLM(response='{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9, "assistant_reply": "Merhaba efendim"}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="hello")
    
    assert output.tool_plan == []
    assert output.tool_plan_with_args == []


def test_tool_plan_length_consistency():
    """tool_plan and tool_plan_with_args should always have same length."""
    test_cases = [
        # Empty
        '{"route": "chat", "calendar_intent": "none", "confidence": 0.9, "tool_plan": [], "assistant_reply": ""}',
        # Strings only
        '{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": ""}',
        # Dicts only
        '{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": [{"name": "calendar.list_events", "args": {}}], "assistant_reply": ""}',
        # Mixed
        '{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": ["calendar.list_events", {"name": "calendar.find_free_slots", "args": {"duration": 30}}], "assistant_reply": ""}',
    ]
    
    for response in test_cases:
        mock_llm = MockLLM(response=response)
        router = JarvisLLMOrchestrator(llm_client=mock_llm)
        output = router.route(user_input="test")
        
        # Lengths must match
        assert len(output.tool_plan) == len(output.tool_plan_with_args), \
            f"Length mismatch: tool_plan={len(output.tool_plan)}, tool_plan_with_args={len(output.tool_plan_with_args)}"
        
        # Each tool_plan[i] should match tool_plan_with_args[i]["name"]
        for i, name in enumerate(output.tool_plan):
            assert output.tool_plan_with_args[i]["name"] == name, \
                f"Name mismatch at index {i}: tool_plan={name}, tool_plan_with_args={output.tool_plan_with_args[i]['name']}"


def test_backward_compatibility():
    """Existing code using tool_plan should continue to work."""
    mock_llm = MockLLM(response='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9, "tool_plan": [{"name": "calendar.list_events", "args": {"max": 5}}], "assistant_reply": ""}')
    
    router = JarvisLLMOrchestrator(llm_client=mock_llm)
    output = router.route(user_input="meetings")
    
    # Old code using tool_plan should still work
    assert "calendar.list_events" in output.tool_plan
    assert len(output.tool_plan) == 1
    
    # New code can access args
    assert output.tool_plan_with_args[0]["args"]["max"] == 5
