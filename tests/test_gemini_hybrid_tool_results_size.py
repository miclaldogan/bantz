"""Tests for Gemini Hybrid tool_results size control (Issue #361).

Issue #361: GeminiHybridOrchestrator should limit tool_results JSON size to prevent
context overflow. Large datasets (e.g., 200 calendar events) can generate 10KB+ JSON
which breaks Gemini's context window.

Solution: Add _summarize_tool_results_for_gemini() helper with smart truncation:
- Max 2KB (2000 chars) for tool results
- Lists: First 5 items + metadata
- Dicts with "events": Calendar-aware preview (5 events + total count)
- Large strings/dicts: Truncate to 500 chars
- Fallback: Keep only first 3 tools if still too large
"""

from __future__ import annotations

import pytest

from bantz.brain.gemini_hybrid_orchestrator import (
    _summarize_tool_results_for_gemini,
    GeminiHybridOrchestrator,
    HybridOrchestratorConfig,
)
from bantz.brain.llm_router import OrchestratorOutput
from bantz.llm.base import LLMResponse


# ============================================================================
# Helper Function Tests
# ============================================================================

def test_summarize_empty_tool_results():
    """Empty tool results should return empty string."""
    result, truncated = _summarize_tool_results_for_gemini([])
    assert result == ""
    assert truncated is False


def test_summarize_small_tool_results():
    """Small tool results should pass through unchanged."""
    tool_results = [
        {
            "tool_name": "get_weather",
            "status": "success",
            "result": {"temp": 72, "condition": "sunny"}
        }
    ]
    result, truncated = _summarize_tool_results_for_gemini(tool_results)
    
    assert "get_weather" in result
    assert "72" in result
    assert "sunny" in result
    assert truncated is False
    assert len(result) < 2000


def test_summarize_list_truncation():
    """Lists with >5 items should be truncated to first 5 + metadata."""
    tool_results = [
        {
            "tool_name": "list_contacts",
            "status": "success",
            "result": [f"Contact {i}" for i in range(100)]  # 100 contacts
        }
    ]
    result, truncated = _summarize_tool_results_for_gemini(tool_results)
    
    assert truncated is True
    assert "Contact 0" in result
    assert "Contact 4" in result
    assert "Contact 5" not in result  # Should not include 6th item
    assert "_total_count" in result
    assert "100" in result  # Total count
    assert len(result) < 2000


def test_summarize_calendar_events_truncation():
    """Calendar results with >5 events should show preview + metadata."""
    # Simulate 100 calendar events
    events = [
        {
            "id": f"event_{i}",
            "summary": f"Meeting {i}",
            "start": {"dateTime": f"2024-01-{i+1:02d}T10:00:00"},
            "end": {"dateTime": f"2024-01-{i+1:02d}T11:00:00"},
        }
        for i in range(100)
    ]
    
    tool_results = [
        {
            "tool_name": "list_events",
            "status": "success",
            "result": {
                "events": events,
                "calendar": "primary",
                "time_range": "next 30 days"
            }
        }
    ]
    
    result, truncated = _summarize_tool_results_for_gemini(tool_results)
    
    assert truncated is True
    assert "event_0" in result
    assert "event_4" in result
    assert "event_5" not in result  # Should not include 6th event
    assert "_total_events" in result
    assert "100" in result  # Total event count
    assert "calendar" in result  # Metadata preserved
    assert len(result) < 2000


def test_summarize_large_string_truncation():
    """Large strings should be truncated to 500 chars."""
    large_text = "x" * 1000  # 1000 chars
    
    tool_results = [
        {
            "tool_name": "read_file",
            "status": "success",
            "result": large_text
        }
    ]
    
    result, truncated = _summarize_tool_results_for_gemini(tool_results)
    
    assert truncated is True
    assert "(truncated" in result
    assert len(result) < 2000


def test_summarize_large_dict_truncation():
    """Large dicts (not calendar) should be truncated to 500 chars."""
    large_dict = {f"key_{i}": f"value_{i}" for i in range(100)}
    
    tool_results = [
        {
            "tool_name": "get_data",
            "status": "success",
            "result": large_dict
        }
    ]
    
    result, truncated = _summarize_tool_results_for_gemini(tool_results)
    
    assert truncated is True
    assert "(truncated" in result
    assert len(result) < 2000


def test_summarize_multiple_tools_all_large():
    """When multiple tools all have large results, should keep first 3."""
    tool_results = [
        {
            "tool_name": f"tool_{i}",
            "status": "success",
            "result": [f"item_{j}" for j in range(50)]  # 50 items each
        }
        for i in range(10)  # 10 tools
    ]
    
    result, truncated = _summarize_tool_results_for_gemini(tool_results, max_chars=2000)
    
    assert truncated is True
    assert "tool_0" in result
    assert "tool_1" in result
    assert "tool_2" in result
    # Should not include tool_3+ in final aggressive truncation
    assert len(result) <= 2000


def test_summarize_fallback_to_string():
    """If JSON serialization fails, should fallback to string representation."""
    # Create an object that can't be JSON serialized
    class NonSerializable:
        def __repr__(self):
            return "NonSerializable()"
    
    tool_results = [
        {
            "tool_name": "test",
            "status": "success",
            "result": NonSerializable()
        }
    ]
    
    result, truncated = _summarize_tool_results_for_gemini(tool_results)
    
    # Should succeed without raising exception
    assert isinstance(result, str)
    assert len(result) < 2000


def test_summarize_max_chars_custom():
    """Should respect custom max_chars parameter."""
    large_text = "x" * 1000
    tool_results = [{"tool_name": "test", "status": "success", "result": large_text}]
    
    result, truncated = _summarize_tool_results_for_gemini(tool_results, max_chars=500)
    
    assert truncated is True
    assert len(result) <= 500


# ============================================================================
# Integration Tests with GeminiHybridOrchestrator
# ============================================================================

class MockRouter:
    """Mock 3B router for testing."""
    
    def __init__(self, response: str = ""):
        self.response = response
        self.calls = []
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        self.calls.append({"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens})
        return self.response


class MockGeminiClient:
    """Mock Gemini client for testing."""
    
    def __init__(self, response: str = "Anladım efendim."):
        self.response = response
        self.calls = []
    
    def chat_detailed(self, messages, *, temperature: float = 0.4, max_tokens: int = 512):
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return LLMResponse(
            content=self.response,
            model="gemini-1.5-flash",
            tokens_used=50,
            finish_reason="stop",
        )


def test_orchestrator_with_large_calendar_results(caplog):
    """Integration: Large calendar results should be truncated in Gemini context."""
    # Router output: calendar route with 100 events
    router_json = """{
        "route": "calendar",
        "calendar_intent": "list",
        "confidence": 0.95,
        "slots": {"time_range": "this week"}
    }"""
    
    # 100 calendar events
    events = [
        {
            "id": f"event_{i}",
            "summary": f"Meeting {i}",
            "start": {"dateTime": f"2024-01-{i+1:02d}T10:00:00"},
            "end": {"dateTime": f"2024-01-{i+1:02d}T11:00:00"},
        }
        for i in range(100)
    ]
    
    tool_results = [
        {
            "tool_name": "calendar_list_events",
            "status": "success",
            "result": {
                "events": events,
                "calendar": "primary",
                "time_range": "this week"
            }
        }
    ]
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Bu hafta birçok etkinliğiniz var efendim.")
    
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    response = orchestrator.orchestrate(
        user_input="Bu hafta ne gibi etkinliklerim var?",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Verify response (may use router response due to no-new-facts guard)
    assert "etkinli" in response.assistant_reply.lower() or "anladım" in response.assistant_reply.lower()
    assert response.route == "calendar"
    
    # Verify Gemini was called with truncated context
    assert len(mock_gemini.calls) == 1
    gemini_call = mock_gemini.calls[0]
    
    # Extract user message (context)
    user_msg = next((m for m in gemini_call["messages"] if m.role == "user"), None)
    assert user_msg is not None
    
    context = user_msg.content
    
    # Context should contain tool results but truncated
    assert "Tool Results:" in context
    assert "event_0" in context  # First event should be there
    assert "event_4" in context  # Fifth event should be there
    # Should not contain all 100 events
    assert "_total_events" in context or "_preview" in context
    
    # Context should be reasonably sized (not 10KB+)
    assert len(context) < 5000  # Much smaller than full 100 events
    
    # Warning should be logged about truncation
    assert any("truncated" in record.message.lower() for record in caplog.records)


def test_orchestrator_with_small_tool_results():
    """Integration: Small tool results should pass through unchanged."""
    router_json = """{
        "route": "calendar",
        "calendar_intent": "list",
        "confidence": 0.95,
        "slots": {}
    }"""
    
    # Small result: only 3 events
    tool_results = [
        {
            "tool_name": "calendar_list_events",
            "status": "success",
            "result": {
                "events": [
                    {"id": "1", "summary": "Meeting 1"},
                    {"id": "2", "summary": "Meeting 2"},
                    {"id": "3", "summary": "Meeting 3"},
                ],
                "calendar": "primary"
            }
        }
    ]
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="3 etkinliğiniz var efendim.")
    
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    response = orchestrator.orchestrate(
        user_input="Bugün ne yapacağım?",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    assert response.assistant_reply == "3 etkinliğiniz var efendim."
    
    # Small results should not be truncated
    gemini_call = mock_gemini.calls[0]
    user_msg = next((m for m in gemini_call["messages"] if m.role == "user"), None)
    context = user_msg.content
    
    # All 3 events should be present
    assert "Meeting 1" in context
    assert "Meeting 2" in context
    assert "Meeting 3" in context


def test_orchestrator_with_multiple_large_tools(caplog):
    """Integration: Multiple tools with large results should be handled."""
    router_json = """{
        "route": "calendar",
        "calendar_intent": "list",
        "confidence": 0.95,
        "slots": {}
    }"""
    
    # Multiple tools, each with large results
    tool_results = [
        {
            "tool_name": f"tool_{i}",
            "status": "success",
            "result": [f"item_{j}" for j in range(50)]  # 50 items each
        }
        for i in range(5)  # 5 tools
    ]
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Tamam efendim.")
    
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    response = orchestrator.orchestrate(
        user_input="Test",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    assert response.assistant_reply == "Tamam efendim."
    
    # Context should be truncated
    gemini_call = mock_gemini.calls[0]
    user_msg = next((m for m in gemini_call["messages"] if m.role == "user"), None)
    context = user_msg.content
    
    # Should be reasonably sized
    assert len(context) < 5000
    
    # Warning should be logged
    assert any("truncated" in record.message.lower() for record in caplog.records)
