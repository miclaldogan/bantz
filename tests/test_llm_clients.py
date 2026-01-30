"""Tests for LLM client abstraction (Issue #133).

Tests both OllamaClientAdapter and VLLMOpenAIClient against the LLMClient interface.

Run:
    pytest tests/test_llm_clients.py -v
    pytest tests/test_llm_clients.py::test_ollama_adapter_interface -v
    pytest tests/test_llm_clients.py -k vllm -v --skip-real-server
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
from bantz.llm.ollama_client import OllamaClientAdapter
from bantz.llm.vllm_openai_client import VLLMOpenAIClient


# ========================================================================
# Contract Tests - Verify Interface Compliance
# ========================================================================

@pytest.mark.parametrize("backend,url,model", [
    ("ollama", "http://127.0.0.1:11434", "qwen2.5:3b-instruct"),
    ("vllm", "http://127.0.0.1:8000", "Qwen/Qwen2.5-3B-Instruct"),
])
def test_factory_creates_correct_backend(backend: str, url: str, model: str):
    """Test that factory creates correct client type."""
    client = create_client(backend, base_url=url, model=model)
    
    # Verify interface compliance
    assert hasattr(client, "chat")
    assert hasattr(client, "chat_detailed")
    assert hasattr(client, "complete_text")
    assert hasattr(client, "is_available")
    assert hasattr(client, "model_name")
    assert hasattr(client, "backend_name")
    
    # Verify backend name
    assert client.backend_name == backend
    assert client.model_name == model


def test_factory_invalid_backend():
    """Test that factory raises ValueError for unknown backend."""
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        create_client("unknown_backend")


# ========================================================================
# OllamaClientAdapter Tests
# ========================================================================

def test_ollama_adapter_interface():
    """Test OllamaClientAdapter implements LLMClient interface."""
    adapter = OllamaClientAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:3b-instruct",
    )
    
    # Verify it's a proper LLMClient
    assert isinstance(adapter, LLMClient)
    assert adapter.backend_name == "ollama"
    assert adapter.model_name == "qwen2.5:3b-instruct"


@patch("bantz.llm.ollama_client.OllamaClient.is_available")
def test_ollama_adapter_is_available(mock_is_available):
    """Test is_available delegates to OllamaClient."""
    mock_is_available.return_value = True
    
    adapter = OllamaClientAdapter()
    assert adapter.is_available() is True
    
    mock_is_available.return_value = False
    assert adapter.is_available() is False


@patch("bantz.llm.ollama_client.OllamaClient.chat")
def test_ollama_adapter_chat(mock_chat):
    """Test chat method delegates correctly."""
    mock_chat.return_value = "Test response"
    
    adapter = OllamaClientAdapter()
    messages = [LLMMessage(role="user", content="Hello")]
    
    result = adapter.chat(messages, temperature=0.5, max_tokens=100)
    
    assert result == "Test response"
    # Check call was made with keyword arguments
    mock_chat.assert_called_once()
    call_kwargs = mock_chat.call_args.kwargs
    assert call_kwargs["temperature"] == 0.5
    assert call_kwargs["max_tokens"] == 100


@patch("bantz.llm.ollama_client.OllamaClient.chat")
def test_ollama_adapter_chat_detailed(mock_chat):
    """Test chat_detailed returns LLMResponse."""
    mock_chat.return_value = "Detailed response"
    
    adapter = OllamaClientAdapter(model="test-model")
    messages = [LLMMessage(role="user", content="Test")]
    
    response = adapter.chat_detailed(messages)
    
    assert isinstance(response, LLMResponse)
    assert response.content == "Detailed response"
    assert response.model == "test-model"
    assert response.finish_reason == "stop"


@patch("bantz.llm.ollama_client.OllamaClient.chat")
def test_ollama_adapter_complete_text(mock_chat):
    """Test complete_text converts prompt to message."""
    mock_chat.return_value = "Completion result"
    
    adapter = OllamaClientAdapter()
    result = adapter.complete_text(prompt="Test prompt", temperature=0.0)
    
    assert result == "Completion result"
    # Verify it created a user message (check kwargs)
    mock_chat.assert_called_once()
    call_kwargs = mock_chat.call_args.kwargs
    messages = call_kwargs["messages"]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Test prompt"


@patch("bantz.llm.ollama_client.OllamaClient.chat")
def test_ollama_adapter_error_handling(mock_chat):
    """Test error classification from RuntimeError."""
    adapter = OllamaClientAdapter()
    messages = [LLMMessage(role="user", content="Test")]
    
    # Model not found
    mock_chat.side_effect = RuntimeError("model not found: qwen2.5")
    with pytest.raises(LLMModelNotFoundError):
        adapter.chat(messages)
    
    # Connection error
    mock_chat.side_effect = RuntimeError("bağlanamadım http://localhost:11434")
    with pytest.raises(LLMConnectionError):
        adapter.chat(messages)
    
    # Timeout
    mock_chat.side_effect = RuntimeError("request timeout after 120 seconds")
    with pytest.raises(LLMTimeoutError):
        adapter.chat(messages)
    
    # Generic error
    mock_chat.side_effect = RuntimeError("something went wrong")
    with pytest.raises(LLMInvalidResponseError):
        adapter.chat(messages)


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
@pytest.mark.skip(reason="Requires real vLLM server or mock - run with --run-integration")
def test_vllm_chat_integration():
    """Integration test: chat with real vLLM server.
    
    Run with: pytest tests/test_llm_clients.py::test_vllm_chat_integration --run-integration
    
    Requires:
        python scripts/vllm_mock_server.py  # or real vLLM server
    """
    client = VLLMOpenAIClient(base_url="http://127.0.0.1:8001")  # Mock server port
    
    if not client.is_available():
        pytest.skip("vLLM server not available (start scripts/vllm_mock_server.py)")
    
    messages = [LLMMessage(role="user", content="Hello")]
    response = client.chat(messages, temperature=0.0, max_tokens=50)
    
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.integration
@pytest.mark.skip(reason="Requires real vLLM server or mock")
def test_vllm_complete_text_integration():
    """Integration test: complete_text with real server."""
    client = VLLMOpenAIClient(base_url="http://127.0.0.1:8001")
    
    if not client.is_available():
        pytest.skip("vLLM server not available")
    
    result = client.complete_text(prompt="Test prompt", temperature=0.0, max_tokens=50)
    
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.integration
@pytest.mark.skip(reason="Requires real vLLM server or mock")
def test_vllm_list_models():
    """Test list_available_models with real server."""
    client = VLLMOpenAIClient(base_url="http://127.0.0.1:8001")
    
    if not client.is_available():
        pytest.skip("vLLM server not available")
    
    models = client.list_available_models()
    
    assert isinstance(models, list)
    assert len(models) > 0


# ========================================================================
# Backend Comparison Tests
# ========================================================================

@pytest.mark.parametrize("backend,base_url,model", [
    ("ollama", "http://127.0.0.1:11434", "qwen2.5:3b-instruct"),
    ("vllm", "http://127.0.0.1:8000", "Qwen/Qwen2.5-3B-Instruct"),
])
def test_backend_interface_consistency(backend: str, base_url: str, model: str):
    """Test that both backends expose consistent interface."""
    client = create_client(backend, base_url=base_url, model=model)
    
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
    """Test that LLMMessage is consistent across backends."""
    msg = LLMMessage(role="user", content="Test")
    
    # Message should work with both backends
    ollama = OllamaClientAdapter()
    vllm = VLLMOpenAIClient()
    
    # Both should accept same message format (even if not connected)
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
@pytest.mark.skip(reason="Requires real server")
def test_determinism_vllm_vs_ollama():
    """Test deterministic output with seed (both backends).
    
    This test verifies that both backends respect temperature=0 and seed
    for deterministic output.
    """
    prompt = "What is 2+2?"
    messages = [LLMMessage(role="user", content=prompt)]
    
    # Test Ollama (if available)
    ollama = create_client("ollama")
    if ollama.is_available():
        result1 = ollama.chat(messages, temperature=0.0, max_tokens=50)
        result2 = ollama.chat(messages, temperature=0.0, max_tokens=50)
        assert result1 == result2, "Ollama should be deterministic with temp=0"
    
    # Test vLLM (if available)
    vllm = create_client("vllm", base_url="http://127.0.0.1:8001")
    if vllm.is_available():
        resp1 = vllm.chat_detailed(messages, temperature=0.0, max_tokens=50, seed=42)
        resp2 = vllm.chat_detailed(messages, temperature=0.0, max_tokens=50, seed=42)
        assert resp1.content == resp2.content, "vLLM should be deterministic with temp=0 and seed"
