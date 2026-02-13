"""Tests for Unified Finalizer Strategy (Issue #356).

Issue #356: BrainLoop and OrchestratorLoop have duplicate finalizer logic
with inconsistent quality. This creates maintenance burden and quality variance.

Solution: Create src/bantz/brain/finalizer.py as a shared module with:
- Unified prompt building
- Smart tool results truncation (max 2000 tokens)
- No-new-facts guard
- Fallback strategies (quality → fast → draft)
- Support for both loop styles (draft-based vs decision-based)
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock

import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from bantz.brain.finalizer import (
        finalize,
        FinalizerConfig,
        FinalizerResult,
        _prepare_tool_results_for_finalizer,
        _build_finalizer_prompt,
    )


# ============================================================================
# Mock LLM Clients
# ============================================================================

class MockLLM:
    """Mock LLM for testing."""
    
    def __init__(self, response: str = "Test response"):
        self.response = response
        self.calls = []
    
    def complete_text(self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:
        self.calls.append({"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens})
        return self.response


# ============================================================================
# Tool Results Preparation Tests
# ============================================================================

def test_prepare_tool_results_empty():
    """Empty tool results should return empty list."""
    results, truncated = _prepare_tool_results_for_finalizer([])
    assert results == []
    assert truncated is False


def test_prepare_tool_results_small():
    """Small tool results should pass through unchanged."""
    tool_results = [
        {"tool": "get_weather", "success": True, "raw_result": {"temp": 72}}
    ]
    results, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=1000)
    
    assert len(results) == 1
    assert results[0]["tool"] == "get_weather"
    assert results[0]["success"] is True
    assert results[0]["result"] == {"temp": 72}
    assert truncated is False


def test_prepare_tool_results_large_uses_summary():
    """Large results should use result_summary if available."""
    # Create a large raw_result
    large_result = {"events": [{"id": f"event_{i}", "summary": f"Meeting {i}"} for i in range(100)]}
    
    tool_results = [
        {
            "tool": "calendar_list_events",
            "success": True,
            "raw_result": large_result,
            "result_summary": "100 events found"
        }
    ]
    
    results, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=500)
    
    assert len(results) == 1
    assert results[0]["result"] == "100 events found"
    assert truncated is True


def test_prepare_tool_results_aggressive_truncation():
    """Very large results should be aggressively truncated to first 3 tools."""
    tool_results = [
        {
            "tool": f"tool_{i}",
            "success": True,
            "raw_result": {"data": "x" * 1000},  # Large raw data
            "result_summary": "y" * 500,          # Large summary too
        }
        for i in range(10)  # 10 tools
    ]
    
    results, truncated = _prepare_tool_results_for_finalizer(tool_results, max_tokens=200)
    
    assert len(results) <= 3  # Should keep only first 3
    assert truncated is True


# ============================================================================
# Prompt Building Tests
# ============================================================================

def test_build_prompt_minimal():
    """Build prompt with minimal inputs (OrchestratorLoop style)."""
    prompt = _build_finalizer_prompt(
        user_input="Merhaba",
        planner_decision={"route": "smalltalk", "confidence": 0.9}
    )
    
    assert "BANTZ" in prompt
    assert "SADECE TÜRKÇE" in prompt
    assert "USER: Merhaba" in prompt
    assert "PLANNER_DECISION" in prompt
    assert "smalltalk" in prompt


def test_build_prompt_with_draft():
    """Build prompt with draft text (BrainLoop style)."""
    prompt = _build_finalizer_prompt(
        user_input="Bugün ne var?",
        draft_text="3 etkinliğiniz var efendim.",
        route="calendar",
        last_tool="calendar.list_events"
    )
    
    assert "USER: Bugün ne var?" in prompt
    assert "DRAFT:" in prompt
    assert "3 etkinliğiniz var efendim" in prompt
    assert "ROUTE: calendar" in prompt
    assert "LAST_TOOL: calendar.list_events" in prompt


def test_build_prompt_with_tool_results():
    """Build prompt with tool results."""
    tool_results = [{"tool": "get_weather", "success": True, "result": {"temp": 72}}]
    
    prompt = _build_finalizer_prompt(
        user_input="Hava nasıl?",
        tool_results=tool_results
    )
    
    assert "TOOL_RESULTS (JSON):" in prompt
    assert "get_weather" in prompt


def test_build_prompt_with_dialog_summary():
    """Build prompt with dialog summary."""
    prompt = _build_finalizer_prompt(
        user_input="Devam et",
        dialog_summary="Kullanıcı takvim hakkında sordu."
    )
    
    assert "DIALOG_SUMMARY:" in prompt
    assert "Kullanıcı takvim hakkında sordu" in prompt


# ============================================================================
# Finalization Tests - Mode Selection
# ============================================================================

def test_finalize_mode_off():
    """Mode 'off' should return draft without calling LLM."""
    mock_llm = MockLLM()
    config = FinalizerConfig(mode="off")
    
    result = finalize(
        user_input="Test",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft response"
    )
    
    assert result.text == "Draft response"
    assert result.used_finalizer is False
    assert result.tier_name == "draft"
    assert result.tier_reason == "finalizer_disabled"
    assert len(mock_llm.calls) == 0


def test_finalize_mode_calendar_only_with_calendar_tool():
    """Mode 'calendar_only' should finalize when last tool is calendar.*"""
    mock_llm = MockLLM(response="Oluşturdum efendim.")
    config = FinalizerConfig(mode="calendar_only")
    
    result = finalize(
        user_input="Yarın 10'da toplantı",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft",
        last_tool="calendar.create_event"
    )
    
    assert result.text == "Oluşturdum efendim."
    assert result.used_finalizer is True
    assert result.tier_name == "quality"
    assert len(mock_llm.calls) == 1


def test_finalize_mode_calendar_only_without_calendar_tool():
    """Mode 'calendar_only' should skip finalization for non-calendar tools."""
    mock_llm = MockLLM()
    config = FinalizerConfig(mode="calendar_only")
    
    result = finalize(
        user_input="Hava nasıl?",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft",
        last_tool="weather.get_current"
    )
    
    assert result.text == "Draft"
    assert result.used_finalizer is False
    assert result.tier_name == "draft"
    assert result.tier_reason == "not_calendar"
    assert len(mock_llm.calls) == 0


def test_finalize_mode_smalltalk_with_smalltalk_route():
    """Mode 'smalltalk' should finalize for smalltalk route."""
    mock_llm = MockLLM(response="Merhaba efendim!")
    config = FinalizerConfig(mode="smalltalk")
    
    result = finalize(
        user_input="Merhaba",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft",
        route="smalltalk"
    )
    
    assert result.text == "Merhaba efendim!"
    assert result.used_finalizer is True
    assert result.tier_name == "quality"
    assert len(mock_llm.calls) == 1


def test_finalize_mode_smalltalk_without_smalltalk_route():
    """Mode 'smalltalk' should skip finalization for non-smalltalk routes."""
    mock_llm = MockLLM()
    config = FinalizerConfig(mode="smalltalk")
    
    result = finalize(
        user_input="Bugün ne var?",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft",
        route="calendar"
    )
    
    assert result.text == "Draft"
    assert result.used_finalizer is False
    assert result.tier_name == "draft"
    assert result.tier_reason == "not_smalltalk"
    assert len(mock_llm.calls) == 0


def test_finalize_mode_always():
    """Mode 'always' should always finalize."""
    mock_llm = MockLLM(response="Finalized")
    config = FinalizerConfig(mode="always")
    
    result = finalize(
        user_input="Any input",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft",
        route="unknown",
        last_tool="some.tool"
    )
    
    assert result.text == "Finalized"
    assert result.used_finalizer is True
    assert result.tier_name == "quality"
    assert result.tier_reason == "success"
    assert len(mock_llm.calls) == 1


# ============================================================================
# Finalization Tests - No-New-Facts Guard
# ============================================================================

def test_finalize_no_new_facts_guard_pass():
    """Finalization should succeed when no new facts are added."""
    mock_llm = MockLLM(response="3 etkinliğiniz var efendim.")
    config = FinalizerConfig(mode="always", enable_no_new_facts_guard=True)
    
    result = finalize(
        user_input="Bugün ne var?",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="3 etkinlik bulundu",
        tool_results=[{"tool": "calendar.list", "result": {"count": 3}}]
    )
    
    assert result.text == "3 etkinliğiniz var efendim."
    assert result.used_finalizer is True
    assert result.guard_violated is False
    assert result.guard_retried is False


def test_finalize_no_new_facts_guard_violation_with_retry():
    """Guard violation should trigger retry with stricter prompt."""
    # First call: violates guard (adds "100")
    # Second call (retry): passes guard
    responses = ["100 etkinliğiniz var efendim.", "Etkinlikleriniz listelendi efendim."]
    call_count = [0]
    
    def mock_complete(*, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:
        response = responses[call_count[0]]
        call_count[0] += 1
        return response
    
    mock_llm = Mock()
    mock_llm.complete_text = mock_complete
    
    config = FinalizerConfig(
        mode="always",
        enable_no_new_facts_guard=True,
        retry_on_guard_violation=True
    )
    
    result = finalize(
        user_input="Etkinlikleri listele",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Etkinlikler listelendi",
        tool_results=[{"tool": "calendar.list", "result": "success"}]
    )
    
    assert result.text == "Etkinlikleriniz listelendi efendim."
    assert result.used_finalizer is True
    assert result.guard_retried is True
    # Guard was violated on first call but recovered on retry
    assert result.guard_violated is False


def test_finalize_guard_disabled():
    """Guard can be disabled via config."""
    # Response with new number should pass when guard disabled
    mock_llm = MockLLM(response="100 etkinlik bulundu.")
    config = FinalizerConfig(mode="always", enable_no_new_facts_guard=False)
    
    result = finalize(
        user_input="Etkinlikleri listele",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Listelendi"
    )
    
    assert result.text == "100 etkinlik bulundu."
    assert result.used_finalizer is True
    assert result.guard_violated is False  # Guard disabled, so no violation


# ============================================================================
# Finalization Tests - Fallback Strategies
# ============================================================================

def test_finalize_quality_empty_fallback_to_draft():
    """Empty quality response should fallback to draft."""
    mock_llm = MockLLM(response="")  # Empty response
    config = FinalizerConfig(mode="always")
    
    result = finalize(
        user_input="Test",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft response"
    )
    
    assert result.text == "Draft response"
    assert result.used_finalizer is False
    assert result.tier_name == "draft"
    assert result.tier_reason == "quality_empty_fallback_draft"


def test_finalize_quality_empty_fallback_to_fast():
    """Empty quality response should try fast LLM if available."""
    quality_llm = MockLLM(response="")  # Empty
    fast_llm = MockLLM(response="Fast response")
    config = FinalizerConfig(mode="always")
    
    result = finalize(
        user_input="Test",
        finalizer_llm=quality_llm,
        config=config,
        draft_text="Draft",
        fallback_llm=fast_llm
    )
    
    assert result.text == "Fast response"
    assert result.used_finalizer is True
    assert result.tier_name == "fast"
    assert result.tier_reason == "quality_empty_fallback_fast"


def test_finalize_quality_failed_fallback_to_fast():
    """Quality LLM error should fallback to fast LLM."""
    def failing_llm(*, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:
        raise Exception("LLM error")
    
    quality_llm = Mock()
    quality_llm.complete_text = failing_llm
    
    fast_llm = MockLLM(response="Fast fallback")
    config = FinalizerConfig(mode="always")
    
    result = finalize(
        user_input="Test",
        finalizer_llm=quality_llm,
        config=config,
        draft_text="Draft",
        fallback_llm=fast_llm
    )
    
    assert result.text == "Fast fallback"
    assert result.used_finalizer is True
    assert result.tier_name == "fast"
    assert result.tier_reason == "quality_failed_fallback_fast"


def test_finalize_all_failed_fallback_to_draft():
    """All LLMs failing should fallback to draft."""
    def failing_llm(*, prompt: str, temperature: float = 0.2, max_tokens: int = 256) -> str:
        raise Exception("LLM error")
    
    quality_llm = Mock()
    quality_llm.complete_text = failing_llm
    fast_llm = Mock()
    fast_llm.complete_text = failing_llm
    
    config = FinalizerConfig(mode="always")
    
    result = finalize(
        user_input="Test",
        finalizer_llm=quality_llm,
        config=config,
        draft_text="Final draft fallback",
        fallback_llm=fast_llm
    )
    
    assert result.text == "Final draft fallback"
    assert result.used_finalizer is False
    assert result.tier_name == "draft"
    assert result.tier_reason == "quality_failed_fallback_draft"


# ============================================================================
# Integration Tests - Different Loop Styles
# ============================================================================

def test_finalize_brainloop_style():
    """Finalization should work with BrainLoop style (draft-based)."""
    mock_llm = MockLLM(response="3 etkinliğiniz var efendim.")
    config = FinalizerConfig(mode="calendar_only")
    
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "result": {"events": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
        }
    ]
    
    result = finalize(
        user_input="Bugün ne var?",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="3 etkinlik bulundu",
        route="calendar",
        last_tool="calendar.list_events",
        tool_results=tool_results
    )
    
    assert result.text == "3 etkinliğiniz var efendim."
    assert result.used_finalizer is True
    
    # Check prompt includes BrainLoop-style elements
    prompt = mock_llm.calls[0]["prompt"]
    assert "DRAFT:" in prompt
    assert "ROUTE: calendar" in prompt
    assert "LAST_TOOL: calendar.list_events" in prompt


def test_finalize_orchestratorloop_style():
    """Finalization should work with OrchestratorLoop style (decision-based)."""
    mock_llm = MockLLM(response="Toplantı oluşturdum efendim.")
    config = FinalizerConfig(mode="always")
    
    planner_decision = {
        "route": "calendar",
        "calendar_intent": "create",
        "slots": {"time": "10:00", "title": "Toplantı"},
        "confidence": 0.95
    }
    
    tool_results = [
        {
            "tool": "calendar.create_event",
            "success": True,
            "result": {"event_id": "evt_123"}
        }
    ]
    
    result = finalize(
        user_input="Yarın 10'da toplantı koy",
        finalizer_llm=mock_llm,
        config=config,
        planner_decision=planner_decision,
        tool_results=tool_results,
        dialog_summary="Kullanıcı takvim ile çalışıyor."
    )
    
    assert result.text == "Toplantı oluşturdum efendim."
    assert result.used_finalizer is True
    
    # Check prompt includes OrchestratorLoop-style elements
    prompt = mock_llm.calls[0]["prompt"]
    assert "PLANNER_DECISION" in prompt
    assert "calendar_intent" in prompt
    assert "DIALOG_SUMMARY:" in prompt


def test_finalize_large_tool_results_truncation():
    """Large tool results should be truncated."""
    mock_llm = MockLLM(response="100 etkinlik listelendi efendim.")
    config = FinalizerConfig(mode="always", tool_results_token_budget=500)
    
    # Create large tool results (100 events)
    large_events = [{"id": f"event_{i}", "summary": f"Meeting {i}"} for i in range(100)]
    tool_results = [
        {
            "tool": "calendar.list_events",
            "success": True,
            "raw_result": {"events": large_events},
            "result_summary": "100 events found"
        }
    ]
    
    result = finalize(
        user_input="Etkinlikleri listele",
        finalizer_llm=mock_llm,
        config=config,
        draft_text="Draft",
        tool_results=tool_results,
        last_tool="calendar.list_events"
    )
    
    assert result.text == "100 etkinlik listelendi efendim."
    assert result.used_finalizer is True
    assert result.was_truncated is True  # Should be truncated due to size
