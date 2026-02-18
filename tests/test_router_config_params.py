"""Tests for Router config params (Issue #362).

Issue #362: JarvisLLMOrchestrator.route() should accept temperature and
max_tokens parameters so callers can configure routing behavior.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, call

from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.llm.base import LLMResponse


# ============================================================================
# JarvisLLMOrchestrator Tests
# ============================================================================

class MockLLMClient:
    """Mock LLM client for testing."""
    
    def __init__(self, response: str = ""):
        self.response = response
        self.calls = []
        self.model_name = "test-model"
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200, **_kwargs) -> str:
        self.calls.append({
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens
        })
        return self.response


def test_router_temperature_default():
    """Router should use temperature=0.0 by default (deterministic)."""
    mock_llm = MockLLMClient(response='{"route": "smalltalk", "confidence": 0.9}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(user_input="Merhaba")
    
    assert len(mock_llm.calls) == 1
    assert mock_llm.calls[0]["temperature"] == 0.0


def test_router_temperature_override():
    """Router should use provided temperature parameter."""
    mock_llm = MockLLMClient(response='{"route": "smalltalk", "confidence": 0.9}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(user_input="Merhaba", temperature=0.5)
    
    assert len(mock_llm.calls) == 1
    assert mock_llm.calls[0]["temperature"] == 0.5


def test_router_temperature_zero():
    """Router should accept temperature=0.0 explicitly."""
    mock_llm = MockLLMClient(response='{"route": "smalltalk", "confidence": 0.9}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(user_input="Merhaba", temperature=0.0)
    
    assert len(mock_llm.calls) == 1
    assert mock_llm.calls[0]["temperature"] == 0.0


def test_router_max_tokens_default():
    """Router should use calculated max_tokens by default."""
    mock_llm = MockLLMClient(response='{"route": "smalltalk", "confidence": 0.9}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(user_input="Merhaba")
    
    assert len(mock_llm.calls) == 1
    # Should use calculated budget, not a specific default
    assert mock_llm.calls[0]["max_tokens"] > 0


def test_router_max_tokens_override():
    """Router should use provided max_tokens_override parameter."""
    mock_llm = MockLLMClient(response='{"route": "smalltalk", "confidence": 0.9}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(user_input="Merhaba", max_tokens_override=300)
    
    assert len(mock_llm.calls) == 1
    assert mock_llm.calls[0]["max_tokens"] == 300


def test_router_both_params_override():
    """Router should use both temperature and max_tokens when provided."""
    mock_llm = MockLLMClient(response='{"route": "calendar", "confidence": 0.95, "calendar_intent": "list"}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(
        user_input="Bugün ne yapacağım?",
        temperature=0.3,
        max_tokens_override=400
    )
    
    assert len(mock_llm.calls) == 1
    assert mock_llm.calls[0]["temperature"] == 0.3
    assert mock_llm.calls[0]["max_tokens"] == 400


def test_router_params_with_context():
    """Router should pass params correctly even with dialog_summary and session_context."""
    mock_llm = MockLLMClient(response='{"route": "calendar", "confidence": 0.95, "calendar_intent": "create"}')
    router = JarvisLLMOrchestrator(llm=mock_llm)
    
    router.route(
        user_input="Yarın 10'da toplantı koy",
        dialog_summary="Previous conversation...",
        session_context={"timezone": "Europe/Istanbul"},
        temperature=0.2,
        max_tokens_override=350
    )
    
    assert len(mock_llm.calls) == 1
    assert mock_llm.calls[0]["temperature"] == 0.2
    assert mock_llm.calls[0]["max_tokens"] == 350
