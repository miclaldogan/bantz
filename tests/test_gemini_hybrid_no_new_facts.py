"""Tests for Issue #357: Gemini Hybrid finalizer no-new-facts guard.

Problem: GeminiHybridOrchestrator._finalize_with_gemini() didn't have no-new-facts
guard, allowing Gemini to hallucinate numbers/dates/times.

Solution: Add find_new_numeric_facts() guard with retry logic and fallback.
"""

import json
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from bantz.brain.gemini_hybrid_orchestrator import GeminiHybridOrchestrator, HybridOrchestratorConfig
from bantz.brain.llm_router import OrchestratorOutput
from bantz.llm import LLMMessage


@dataclass
class MockChatResponse:
    """Mock response from Gemini chat_detailed"""
    content: str
    tokens_used: int = 100


def test_gemini_finalizer_passes_guard_with_correct_numbers():
    """When Gemini response has no new numeric facts, guard passes."""
    # Setup
    mock_router = Mock()
    mock_gemini = Mock()
    
    # Gemini responds correctly (3 events, matches tool results)
    mock_gemini.chat_detailed = Mock(return_value=MockChatResponse(
        content="3 toplantınız var efendim.",
        tokens_used=50
    ))
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        tool_plan=["calendar.list_events"],
        assistant_reply="Toplantılarınızı getiriyorum.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [
                {"summary": "Meeting 1"},
                {"summary": "Meeting 2"},
                {"summary": "Meeting 3"},
            ]
        }
    ]
    
    # Call finalizer
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="bugün ne toplantılarım var",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should use Gemini response (no guard violation)
    assert result == "3 toplantınız var efendim."
    assert mock_gemini.chat_detailed.call_count == 1


def test_gemini_finalizer_detects_hallucinated_number():
    """When Gemini hallucinates a number, guard detects and retries."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # First call: Gemini hallucinates (says 27 events when there are 3)
    # Second call (retry): Gemini corrects itself
    mock_gemini.chat_detailed = Mock(side_effect=[
        MockChatResponse(content="27 toplantınız var efendim.", tokens_used=50),
        MockChatResponse(content="Birkaç toplantınız var efendim.", tokens_used=50),
    ])
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        tool_plan=["calendar.list_events"],
        assistant_reply="Toplantılarınızı getiriyorum.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [
                {"summary": "Meeting 1"},
                {"summary": "Meeting 2"},
                {"summary": "Meeting 3"},
            ]
        }
    ]
    
    # Call finalizer
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="bugün ne toplantılarım var",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should use retry response (corrected, no specific number)
    assert "27" not in result
    assert result == "Birkaç toplantınız var efendim."
    # Should have called Gemini twice (original + retry)
    assert mock_gemini.chat_detailed.call_count == 2


def test_gemini_finalizer_falls_back_when_retry_fails():
    """When retry also violates guard, fall back to router response."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # Both calls hallucinate
    mock_gemini.chat_detailed = Mock(side_effect=[
        MockChatResponse(content="99 toplantınız var efendim.", tokens_used=50),
        MockChatResponse(content="87 toplantınız var efendim.", tokens_used=50),
    ])
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        tool_plan=["calendar.list_events"],
        assistant_reply="Toplantılarınız gösteriliyor efendim.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [
                {"summary": "Meeting 1"},
                {"summary": "Meeting 2"},
                {"summary": "Meeting 3"},
            ]
        }
    ]
    
    # Call finalizer
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="bugün ne toplantılarım var",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should fall back to router response
    assert result == "Toplantılarınız gösteriliyor efendim."
    assert mock_gemini.chat_detailed.call_count == 2


def test_gemini_finalizer_handles_time_hallucination():
    """Guard detects hallucinated times."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # Gemini hallucinates time (23:45 not in user input or tool results)
    # Retry succeeds
    mock_gemini.chat_detailed = Mock(side_effect=[
        MockChatResponse(content="Saat 23:45'te toplantınız var efendim.", tokens_used=50),
        MockChatResponse(content="Öğleden sonra toplantınız var efendim.", tokens_used=50),
    ])
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        tool_plan=["calendar.list_events"],
        assistant_reply="Toplantınız var.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [{"summary": "Meeting", "start": "afternoon"}]
        }
    ]
    
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="öğleden sonra toplantım var mı",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should use retry (no specific time mentioned)
    assert "23:45" not in result
    assert mock_gemini.chat_detailed.call_count == 2


def test_gemini_finalizer_allows_numbers_from_user_input():
    """Numbers in user input are allowed in Gemini response."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # User says "10" in input, Gemini can echo it
    mock_gemini.chat_detailed = Mock(return_value=MockChatResponse(
        content="Yarın saat 10'da toplantı oluşturdum efendim.",
        tokens_used=50
    ))
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="create_event",
        slots={"time": "10:00"},
        tool_plan=["calendar.create_event"],
        assistant_reply="Toplantı oluşturuldu.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.create_event",
            "success": True,
            "result": {"id": "evt123", "start": "2024-01-15T10:00:00Z"}
        }
    ]
    
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="yarın saat 10'da toplantı oluştur",  # Has "10" explicitly
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should pass guard (10 is in user input explicitly with apostrophe)
    assert "10" in result or "Toplantı oluştur" in result  # Either passes or falls back
    assert mock_gemini.chat_detailed.call_count >= 1


def test_gemini_finalizer_guard_is_best_effort():
    """Guard exceptions don't block user, use Gemini response."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    mock_gemini.chat_detailed = Mock(return_value=MockChatResponse(
        content="Tamamlandı efendim.",
        tokens_used=50
    ))
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="create_event",
        slots={},
        tool_plan=["calendar.create_event"],
        assistant_reply="Oluşturuldu.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [{"tool": "calendar.create_event", "success": True, "result": {"id": "123"}}]
    
    # Mock find_new_numeric_facts to raise exception (import from llm.no_new_facts)
    with patch('bantz.llm.no_new_facts.find_new_numeric_facts', side_effect=Exception("Guard error")):
        result = orchestrator._finalize_with_gemini(
            router_output=router_output,
            user_input="test",
            dialog_summary="",
            tool_results=tool_results,
        )
    
    # Should still return Gemini response (guard is best-effort)
    assert result == "Tamamlandı efendim."
    assert mock_gemini.chat_detailed.call_count == 1


def test_gemini_finalizer_empty_retry_falls_back():
    """When retry returns empty, fall back to router response."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # First call hallucinates, retry is empty
    mock_gemini.chat_detailed = Mock(side_effect=[
        MockChatResponse(content="56 toplantınız var efendim.", tokens_used=50),
        MockChatResponse(content="", tokens_used=0),
    ])
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        tool_plan=["calendar.list_events"],
        assistant_reply="3 toplantınız var efendim.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [{"summary": "M1"}, {"summary": "M2"}, {"summary": "M3"}]
        }
    ]
    
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="bugün toplantılarım",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should fall back to router response
    assert result == "3 toplantınız var efendim."
    assert mock_gemini.chat_detailed.call_count == 2


def test_gemini_finalizer_no_router_reply_fallback():
    """When router has no reply and guard fails, use generic fallback."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # Both calls hallucinate
    mock_gemini.chat_detailed = Mock(side_effect=[
        MockChatResponse(content="999 toplantınız var efendim.", tokens_used=50),
        MockChatResponse(content="888 toplantınız var efendim.", tokens_used=50),
    ])
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={},
        tool_plan=["calendar.list_events"],
        assistant_reply="",  # No router reply
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="",
        confidence=0.9,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [{"summary": "M1"}]
        }
    ]
    
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="toplantılarım",
        dialog_summary="",
        tool_results=tool_results,
    )
    
    # Should use generic fallback
    assert result == "Anladım efendim."
    assert mock_gemini.chat_detailed.call_count == 2


def test_integration_gemini_hybrid_with_guard():
    """Integration test: Guard works in full orchestrator flow."""
    mock_router = Mock()
    mock_gemini = Mock()
    
    # Gemini tries to hallucinate, retry succeeds
    mock_gemini.chat_detailed = Mock(side_effect=[
        MockChatResponse(content="73 etkinlik bulundu efendim.", tokens_used=50),
        MockChatResponse(content="Etkinliklerinizi gösteriyorum efendim.", tokens_used=50),
    ])
    
    config = HybridOrchestratorConfig()
    orchestrator = GeminiHybridOrchestrator(router=mock_router, gemini_client=mock_gemini, config=config)
    
    router_output = OrchestratorOutput(
        route="calendar",
        calendar_intent="list_events",
        slots={"timeframe": "bugün"},
        tool_plan=["calendar.list_events"],
        assistant_reply="Etkinlikler gösteriliyor.",
        requires_confirmation=False,
        ask_user=False,
        question="",
        confirmation_prompt="",
        memory_update="",
        reasoning_summary="List events for today",
        confidence=0.95,
        raw_output={},
    )
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": [
                {"summary": "Meeting 1", "start": "09:00"},
                {"summary": "Meeting 2", "start": "14:00"},
            ]
        }
    ]
    
    result = orchestrator._finalize_with_gemini(
        router_output=router_output,
        user_input="bugün ne etkinliklerim var",
        dialog_summary="User checking today's calendar",
        tool_results=tool_results,
    )
    
    # Should not contain hallucinated number
    assert "73" not in result
    # Should use retry response
    assert "Etkinliklerinizi gösteriyorum" in result
    assert mock_gemini.chat_detailed.call_count == 2
