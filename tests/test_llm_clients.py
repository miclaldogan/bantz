"""Tests for LLM client abstraction (Issue #133).

This repository is vLLM-only (OpenAI-compatible API).

Run:
    pytest tests/test_llm_clients.py -v
    pytest tests/test_llm_clients.py -k vllm -v
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch

from bantz.llm.base import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMInvalidResponseError,
    create_client,
)
from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm import create_quality_client


# ========================================================================
# Contract Tests - Verify Interface Compliance
# ========================================================================

def test_factory_creates_vllm_backend():
    """Test that factory creates vLLM client."""
    client = create_client(
        "vllm",
        base_url="http://127.0.0.1:8000",
        model="Qwen/Qwen2.5-3B-Instruct",
    )
    
    # Verify interface compliance
    assert hasattr(client, "chat")
    assert hasattr(client, "chat_detailed")
    assert hasattr(client, "complete_text")
    assert hasattr(client, "is_available")
    assert hasattr(client, "model_name")
    assert hasattr(client, "backend_name")
    
    assert client.backend_name == "vllm"
    assert client.model_name == "Qwen/Qwen2.5-3B-Instruct"


def test_factory_invalid_backend():
    """Test that factory raises ValueError for unknown backend."""
    with pytest.raises(ValueError, match="Unknown backend"):
        create_client("unknown_backend")


# ========================================================================
# Quality Client Selection (Hybrid mode)
# ========================================================================


def test_create_quality_client_falls_back_to_fast_when_vllm_quality_unavailable(monkeypatch):
    monkeypatch.delenv("QUALITY_PROVIDER", raising=False)
    monkeypatch.delenv("BANTZ_QUALITY_PROVIDER", raising=False)
    monkeypatch.setenv("BANTZ_QUALITY_FALLBACK_TO_FAST", "1")

    # Ensure the vLLM quality endpoint is configured but "down".
    monkeypatch.setenv("BANTZ_VLLM_QUALITY_URL", "http://127.0.0.1:8002")
    monkeypatch.setenv("BANTZ_VLLM_URL", "http://127.0.0.1:8001")

    # Force availability probe to fail.
    monkeypatch.setattr(VLLMOpenAIClient, "is_available", lambda self, timeout_seconds=1.5: False)

    llm = create_quality_client()
    assert llm.backend_name == "vllm"
    # Fallback should return the fast URL.
    assert getattr(llm, "base_url", "").endswith(":8001")


def test_create_quality_client_gemini_is_blocked_when_cloud_mode_local(monkeypatch):
    monkeypatch.setenv("QUALITY_PROVIDER", "gemini")
    monkeypatch.setenv("BANTZ_CLOUD_MODE", "local")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("BANTZ_VLLM_URL", "http://127.0.0.1:8001")

    llm = create_quality_client()
    assert llm.backend_name == "vllm"
    assert getattr(llm, "base_url", "").endswith(":8001")


def test_create_quality_client_gemini_missing_key_falls_back(monkeypatch):
    monkeypatch.setenv("QUALITY_PROVIDER", "gemini")
    monkeypatch.setenv("BANTZ_CLOUD_MODE", "cloud")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("BANTZ_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("BANTZ_VLLM_URL", "http://127.0.0.1:8001")

    llm = create_quality_client()
    assert llm.backend_name == "vllm"
    assert getattr(llm, "base_url", "").endswith(":8001")


# ========================================================================
# VLLMOpenAIClient Tests
# ========================================================================

def test_vllm_client_interface():
    """Test VLLMOpenAIClient implements LLMClient interface."""
    client = VLLMOpenAIClient(
        base_url="http://127.0.0.1:8000",
        model="Qwen/Qwen2.5-3B-Instruct",
    )
    
    # Verify it's a proper LLMClient
    assert isinstance(client, LLMClient)
    assert client.backend_name == "vllm"
    assert client.model_name == "Qwen/Qwen2.5-3B-Instruct"


@patch("requests.get")
def test_vllm_is_available(mock_get):
    """Test vLLM is_available checks /v1/models endpoint."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    
    client = VLLMOpenAIClient()
    assert client.is_available() is True
    
    mock_get.assert_called_once()
    args = mock_get.call_args
    assert "/v1/models" in args[0][0]


@patch("requests.get")
def test_vllm_is_available_failure(mock_get):
    """Test is_available returns False on error."""
    mock_get.side_effect = ConnectionError("Connection refused")
    
    client = VLLMOpenAIClient()
    assert client.is_available() is False


@pytest.mark.integration
@pytest.mark.vllm
def test_vllm_chat_integration(vllm_mock_server_url: str):
    """Integration test: chat with real vLLM server.
    
    Run with: pytest tests/test_llm_clients.py::test_vllm_chat_integration --run-integration
    
    Requires:
        python scripts/vllm_mock_server.py  # or real vLLM server
    """
    client = VLLMOpenAIClient(base_url=vllm_mock_server_url)
    
    messages = [LLMMessage(role="user", content="Hello")]
    response = client.chat(messages, temperature=0.0, max_tokens=50)
    
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
@pytest.mark.vllm
def test_vllm_complete_text_integration(vllm_mock_server_url: str):
    """Integration test: complete_text with real server."""
    client = VLLMOpenAIClient(base_url=vllm_mock_server_url)
    
    result = client.complete_text(prompt="Test prompt", temperature=0.0, max_tokens=50)
    
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.integration
@pytest.mark.vllm
def test_vllm_list_models(vllm_mock_server_url: str):
    """Test list_available_models with real server."""
    client = VLLMOpenAIClient(base_url=vllm_mock_server_url)
    
    models = client.list_available_models()
    
    assert isinstance(models, list)
    assert len(models) > 0


# ========================================================================
# Backend Interface Tests (vLLM-only)
# ========================================================================

def test_backend_interface_consistency_vllm_only():
    """Test that the vLLM backend exposes the expected interface."""
    backend = "vllm"
    client = create_client(backend, base_url="http://127.0.0.1:8000", model="Qwen/Qwen2.5-3B-Instruct")
    
    # All backends must have these methods with same signature
    assert callable(client.chat)
    assert callable(client.chat_detailed)
    assert callable(client.complete_text)
    assert callable(client.is_available)
    
    # All backends must have these properties
    assert isinstance(client.model_name, str)
    assert isinstance(client.backend_name, str)
    
    # Backend name must match what was requested
    assert client.backend_name == backend


def test_message_format_consistency():
    """Test that LLMMessage is stable and backend-agnostic."""
    msg = LLMMessage(role="user", content="Test")

    # Message should remain valid without any backend connectivity
    assert msg.role == "user"
    assert msg.content == "Test"


# ========================================================================
# Mock-Based Behavior Tests
# ========================================================================

@patch("bantz.llm.vllm_openai_client.VLLMOpenAIClient._get_client")
def test_vllm_error_classification(mock_get_client):
    """Test vLLM error classification."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client
    
    client = VLLMOpenAIClient()
    messages = [LLMMessage(role="user", content="Test")]
    
    # Connection error
    mock_client.chat.completions.create.side_effect = Exception("connection refused")
    with pytest.raises(LLMConnectionError):
        client.chat(messages)
    
    # Timeout
    mock_client.chat.completions.create.side_effect = Exception("request timeout")
    with pytest.raises(LLMTimeoutError):
        client.chat(messages)
    
    # Model not found
    mock_client.chat.completions.create.side_effect = Exception("model not found: 404")
    with pytest.raises(LLMModelNotFoundError):
        client.chat(messages)
    
    # Generic error
    mock_client.chat.completions.create.side_effect = Exception("something else")
    with pytest.raises(LLMInvalidResponseError):
        client.chat(messages)


@patch("bantz.llm.vllm_openai_client.VLLMOpenAIClient._get_client")
def test_vllm_chat_detailed_response(mock_get_client):
    """Test vLLM chat_detailed returns proper LLMResponse."""
    mock_client = Mock()
    mock_get_client.return_value = mock_client
    
    # Mock OpenAI response
    mock_completion = Mock()
    mock_completion.choices = [Mock()]
    mock_completion.choices[0].message.content = "Test response"
    mock_completion.choices[0].message.tool_calls = None  # prevent Mock auto-attribute
    mock_completion.choices[0].finish_reason = "stop"
    mock_completion.model = "test-model"
    mock_completion.usage.total_tokens = 42
    
    mock_client.chat.completions.create.return_value = mock_completion
    
    client = VLLMOpenAIClient()
    messages = [LLMMessage(role="user", content="Test")]
    
    response = client.chat_detailed(messages)
    
    assert isinstance(response, LLMResponse)
    assert response.content == "Test response"
    assert response.model == "test-model"
    assert response.tokens_used == 42
    assert response.finish_reason == "stop"


# ========================================================================
# Determinism Test (Real Server)
# ========================================================================

@pytest.mark.integration
@pytest.mark.vllm
def test_determinism_vllm(vllm_mock_server_url: str):
    """Test deterministic output with seed (vLLM).

    This test verifies that vLLM respects temperature=0 and seed for deterministic output.
    """
    prompt = "What is 2+2?"
    messages = [LLMMessage(role="user", content=prompt)]

    # Test vLLM (if available)
    vllm = create_client("vllm", base_url=vllm_mock_server_url)
    resp1 = vllm.chat_detailed(messages, temperature=0.0, max_tokens=50, seed=42)
    resp2 = vllm.chat_detailed(messages, temperature=0.0, max_tokens=50, seed=42)
    assert resp1.content == resp2.content, "vLLM should be deterministic with temp=0 and seed"
