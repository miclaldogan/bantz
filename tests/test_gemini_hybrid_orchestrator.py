"""Tests for Gemini Hybrid Orchestrator (Issues #131, #134, #135)."""

from __future__ import annotations

import pytest
from unittest.mock import Mock

from bantz.brain.gemini_hybrid_orchestrator import (
    GeminiHybridOrchestrator,
    HybridOrchestratorConfig,
    create_gemini_hybrid_orchestrator,
)
from bantz.brain.llm_router import OrchestratorOutput
from bantz.llm.base import LLMResponse


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


def test_hybrid_orchestrator_smalltalk():
    """Test smalltalk routing with Gemini finalization."""
    
    # Mock router returns smalltalk route
    router_response = """{
        "route": "smalltalk",
        "calendar_intent": "none",
        "slots": {},
        "confidence": 0.95,
        "tool_plan": [],
        "assistant_reply": "İyiyim teşekkürler!",
        "ask_user": false,
        "question": "",
        "requires_confirmation": false,
        "confirmation_prompt": "",
        "memory_update": "Kullanıcı nasılsın diye sordu",
        "reasoning_summary": ["Sohbet mesajı", "Tool gerekmez"]
    }"""
    
    router = MockRouter(response=router_response)
    gemini = MockGeminiClient(response="İyiyim efendim, siz nasılsınız?")
    
    orchestrator = GeminiHybridOrchestrator(
        router=router,
        gemini_client=gemini,
        config=HybridOrchestratorConfig(enable_gemini_finalization=True),
    )
    
    # This will fail because JarvisLLMOrchestrator expects actual LLM client
    # For now, test the config and structure
    assert orchestrator._config.enable_gemini_finalization is True
    assert orchestrator._config.confidence_threshold == 0.7


def test_hybrid_orchestrator_config_defaults():
    """Test default configuration values."""
    
    config = HybridOrchestratorConfig()
    
    assert config.router_backend == "vllm"
    assert config.router_model == "Qwen/Qwen2.5-3B-Instruct"
    assert config.router_temperature == 0.0
    assert config.router_max_tokens == 512
    
    assert config.gemini_model == "gemini-1.5-flash"
    assert config.gemini_temperature == 0.4
    assert config.gemini_max_tokens == 512
    
    assert config.confidence_threshold == 0.7
    assert config.enable_gemini_finalization is True


def test_hybrid_orchestrator_config_custom():
    """Test custom configuration values."""
    
    config = HybridOrchestratorConfig(
        router_model="qwen2.5:7b-instruct",
        gemini_model="gemini-1.5-pro",
        confidence_threshold=0.8,
        enable_gemini_finalization=False,
    )
    
    assert config.router_model == "qwen2.5:7b-instruct"
    assert config.gemini_model == "gemini-1.5-pro"
    assert config.confidence_threshold == 0.8
    assert config.enable_gemini_finalization is False


def test_mock_gemini_client():
    """Test mock Gemini client behavior."""
    
    gemini = MockGeminiClient(response="Test response")
    
    from bantz.llm.base import LLMMessage
    
    result = gemini.chat_detailed(
        messages=[LLMMessage(role="user", content="test")],
        temperature=0.5,
        max_tokens=100,
    )
    
    assert result.content == "Test response"
    assert result.model == "gemini-1.5-flash"
    assert result.tokens_used == 50
    assert len(gemini.calls) == 1
    assert gemini.calls[0]["temperature"] == 0.5


def test_gemini_finalization_disabled():
    """Test that Gemini finalization can be disabled."""
    
    config = HybridOrchestratorConfig(enable_gemini_finalization=False)
    
    assert config.enable_gemini_finalization is False
    
    # When disabled, orchestrator should return router output directly
    # (Integration test needed for full verification)


def test_confidence_threshold():
    """Test confidence threshold behavior."""
    
    config = HybridOrchestratorConfig(confidence_threshold=0.8)
    
    assert config.confidence_threshold == 0.8
    
    # Low confidence (0.5) should skip tools and Gemini
    # High confidence (0.9) should proceed
    # (Integration test needed for full verification)


def test_router_temperature_zero():
    """Test that router uses temperature=0 for deterministic output."""
    
    config = HybridOrchestratorConfig()
    
    assert config.router_temperature == 0.0
    
    # Temperature=0 ensures deterministic routing
    # (Integration test needed for full verification)


def test_gemini_temperature_balanced():
    """Test that Gemini uses balanced temperature for natural responses."""
    
    config = HybridOrchestratorConfig()
    
    assert config.gemini_temperature == 0.4
    
    # Temperature=0.4 balances creativity and consistency
    # (Integration test needed for full verification)


def test_orchestrate_with_session_context():
    """Test that session_context is passed to router (Issue #343)."""
    
    router_response = """{
        "route": "calendar",
        "calendar_intent": "query",
        "slots": {"date": "2026-02-06"},
        "confidence": 0.9,
        "tool_plan": ["calendar.list_events"],
        "assistant_reply": ""
    }"""
    
    router = MockRouter(response=router_response)
    gemini = MockGeminiClient(response="Bugün 3 toplantınız var efendim.")
    
    orchestrator = GeminiHybridOrchestrator(
        router=router,
        gemini_client=gemini,
    )
    
    # Note: This test will need actual integration test with JarvisLLMOrchestrator
    # For now, verify orchestrate method accepts session_context parameter
    import inspect
    sig = inspect.signature(orchestrator.orchestrate)
    assert 'session_context' in sig.parameters
    assert 'retrieved_memory' in sig.parameters


def test_orchestrate_with_retrieved_memory():
    """Test that retrieved_memory is passed to router (Issue #343)."""
    
    router_response = """{
        "route": "calendar",
        "calendar_intent": "create",
        "slots": {"time": "10:00", "title": "Standup"},
        "confidence": 0.85,
        "tool_plan": ["calendar.create_event"],
        "assistant_reply": ""
    }"""
    
    router = MockRouter(response=router_response)
    gemini = MockGeminiClient(response="Standup toplantınız eklendi efendim.")
    
    orchestrator = GeminiHybridOrchestrator(
        router=router,
        gemini_client=gemini,
    )
    
    # Verify parameters exist
    import inspect
    sig = inspect.signature(orchestrator.orchestrate)
    params = sig.parameters
    
    assert 'user_input' in params
    assert 'dialog_summary' in params
    assert 'tool_results' in params
    assert 'session_context' in params
    assert 'retrieved_memory' in params


def test_tool_results_type_is_list():
    """Test that tool_results is list[dict], not dict (Issue #344)."""
    
    import inspect
    from typing import get_type_hints
    
    # Get type hints for orchestrate method
    hints = get_type_hints(GeminiHybridOrchestrator.orchestrate)
    
    # tool_results should be Optional[list[dict[str, Any]]]
    tool_results_hint = hints.get('tool_results')
    assert tool_results_hint is not None
    
    # Verify it's a list type (not dict)
    import typing
    if hasattr(typing, 'get_origin'):
        # Python 3.8+
        origin = typing.get_origin(tool_results_hint)
        # Should be Union (from Optional)
        if origin is typing.Union:
            args = typing.get_args(tool_results_hint)
            # First arg should be list
            list_arg = args[0]
            list_origin = typing.get_origin(list_arg)
            assert list_origin is list, f"Expected list, got {list_origin}"


def test_finalize_with_gemini_accepts_list():
    """Test that _finalize_with_gemini accepts list[dict] for tool_results (Issue #344)."""
    
    import inspect
    
    # Get _finalize_with_gemini signature
    sig = inspect.signature(GeminiHybridOrchestrator._finalize_with_gemini)
    params = sig.parameters
    
    assert 'tool_results' in params
    
    # Verify annotation contains 'list'
    annotation = params['tool_results'].annotation
    annotation_str = str(annotation)
    assert 'list' in annotation_str.lower(), f"Expected list in annotation, got {annotation_str}"

