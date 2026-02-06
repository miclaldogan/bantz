"""Tests for Router config params (Issue #362).

Issue #362: HybridOrchestratorConfig has router_temperature and router_max_tokens
but they are not passed to JarvisLLMOrchestrator.route(), so config is ignored.

Solution:
- Add temperature and max_tokens_override parameters to JarvisLLMOrchestrator.route()
- Update GeminiHybridOrchestrator to pass config values to router
- Ensure config override works correctly
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, call

from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.brain.gemini_hybrid_orchestrator import (
    GeminiHybridOrchestrator,
    HybridOrchestratorConfig,
)
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
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
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


# ============================================================================
# GeminiHybridOrchestrator Integration Tests
# ============================================================================

class MockRouter:
    """Mock 3B router for testing."""
    
    def __init__(self, response: str = ""):
        self.response = response
        self.calls = []
        self.model_name = "test-router"
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        self.calls.append({
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens
        })
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


def test_hybrid_orchestrator_default_router_params():
    """Hybrid orchestrator should use default router params from config."""
    router_json = '{"route": "smalltalk", "confidence": 0.9}'
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Merhaba efendim.")
    
    # Default config: router_temperature=0.0, router_max_tokens=512
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
    
    orchestrator.orchestrate(
        user_input="Merhaba",
        dialog_summary="",
    )
    
    # Verify router was called with default config values
    assert len(mock_router.calls) == 1
    assert mock_router.calls[0]["temperature"] == 0.0  # Default from config
    assert mock_router.calls[0]["max_tokens"] == 512  # Default from config


def test_hybrid_orchestrator_custom_router_temperature():
    """Hybrid orchestrator should use custom router_temperature from config."""
    router_json = '{"route": "calendar", "confidence": 0.95, "calendar_intent": "list"}'
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Tamam efendim.")
    
    # Custom temperature
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        router_temperature=0.5,  # Custom value
        router_max_tokens=512,
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    orchestrator.orchestrate(
        user_input="Bugün ne yapacağım?",
        dialog_summary="",
    )
    
    # Verify custom temperature was used
    assert len(mock_router.calls) == 1
    assert mock_router.calls[0]["temperature"] == 0.5


def test_hybrid_orchestrator_custom_router_max_tokens():
    """Hybrid orchestrator should use custom router_max_tokens from config."""
    router_json = '{"route": "calendar", "confidence": 0.95, "calendar_intent": "create"}'
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Oluşturdum efendim.")
    
    # Custom max_tokens
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        router_temperature=0.0,
        router_max_tokens=256,  # Custom value
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    orchestrator.orchestrate(
        user_input="Yarın 10'da toplantı",
        dialog_summary="",
    )
    
    # Verify custom max_tokens was used
    assert len(mock_router.calls) == 1
    assert mock_router.calls[0]["max_tokens"] == 256


def test_hybrid_orchestrator_both_custom_params():
    """Hybrid orchestrator should use both custom temperature and max_tokens."""
    router_json = '{"route": "gmail", "confidence": 0.92, "gmail_intent": "list"}'
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Mail listeniz efendim.")
    
    # Both custom
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        router_temperature=0.3,  # Custom
        router_max_tokens=384,   # Custom
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    orchestrator.orchestrate(
        user_input="Maillerimi göster",
        dialog_summary="",
    )
    
    # Verify both custom values were used
    assert len(mock_router.calls) == 1
    assert mock_router.calls[0]["temperature"] == 0.3
    assert mock_router.calls[0]["max_tokens"] == 384


def test_hybrid_orchestrator_params_persist_across_calls():
    """Config params should be used consistently across multiple calls."""
    router_json = '{"route": "smalltalk", "confidence": 0.9}'
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Tamam efendim.")
    
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        router_temperature=0.7,
        router_max_tokens=200,
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    # Call 1
    orchestrator.orchestrate(user_input="Merhaba", dialog_summary="")
    # Call 2
    orchestrator.orchestrate(user_input="Nasılsın?", dialog_summary="")
    
    # Both calls should use the same config
    assert len(mock_router.calls) == 2
    assert mock_router.calls[0]["temperature"] == 0.7
    assert mock_router.calls[0]["max_tokens"] == 200
    assert mock_router.calls[1]["temperature"] == 0.7
    assert mock_router.calls[1]["max_tokens"] == 200


def test_hybrid_orchestrator_zero_temperature():
    """Config should work with temperature=0.0 (fully deterministic)."""
    router_json = '{"route": "calendar", "confidence": 0.99, "calendar_intent": "query"}'
    
    mock_router = MockRouter(response=router_json)
    mock_gemini = MockGeminiClient(response="Etkinlikleriniz efendim.")
    
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model="Qwen/Qwen2.5-3B-Instruct",
        router_temperature=0.0,  # Fully deterministic
        router_max_tokens=512,
        gemini_model="gemini-1.5-flash",
    )
    
    orchestrator = GeminiHybridOrchestrator(
        config=config,
        router=mock_router,
        gemini_client=mock_gemini,
    )
    
    orchestrator.orchestrate(
        user_input="Bugün ne var?",
        dialog_summary="",
    )
    
    assert len(mock_router.calls) == 1
    assert mock_router.calls[0]["temperature"] == 0.0
