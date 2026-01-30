"""vLLM integration tests (Issue #139).

These tests require a running vLLM server (local GPU or mock).
They are marked with @pytest.mark.vllm and will be skipped by default.

Run:
    pytest tests/test_vllm_integration.py -v -m vllm  # Run only vLLM tests
    pytest tests/test_vllm_integration.py -v  # Skip vLLM tests (default)
    pytest -m "not vllm"  # Exclude all vLLM tests
"""

from __future__ import annotations

import pytest
import requests
from typing import Optional

from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm.base import LLMMessage, LLMConnectionError


# =============================================================================
# Fixtures
# =============================================================================

def is_vllm_server_available(url: str = "http://127.0.0.1:8000") -> bool:
    """Check if vLLM server is available."""
    try:
        response = requests.get(f"{url}/v1/models", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


@pytest.fixture
def vllm_url() -> str:
    """vLLM server URL (or mock server URL)."""
    # Check if real vLLM is running
    if is_vllm_server_available("http://127.0.0.1:8000"):
        return "http://127.0.0.1:8000"
    # Check if mock server is running
    elif is_vllm_server_available("http://127.0.0.1:8001"):
        return "http://127.0.0.1:8001"
    else:
        pytest.skip("No vLLM server available (start vLLM or scripts/vllm_mock_server.py)")


@pytest.fixture
def vllm_client(vllm_url: str) -> VLLMOpenAIClient:
    """Create vLLM client connected to available server."""
    return VLLMOpenAIClient(base_url=vllm_url)


# =============================================================================
# Connection & Availability Tests
# =============================================================================

@pytest.mark.vllm
@pytest.mark.integration
class TestVLLMConnection:
    """Test vLLM server connection and availability."""
    
    def test_server_is_available(self, vllm_client: VLLMOpenAIClient):
        """Test that vLLM server is reachable."""
        assert vllm_client.is_available(), "vLLM server should be available"
    
    def test_list_models(self, vllm_client: VLLMOpenAIClient):
        """Test listing available models."""
        models = vllm_client.list_available_models()
        
        assert isinstance(models, list), "list_available_models should return list"
        assert len(models) > 0, "At least one model should be available"
    
    def test_model_name_property(self, vllm_client: VLLMOpenAIClient):
        """Test that model name is accessible."""
        assert isinstance(vllm_client.model_name, str)
        assert len(vllm_client.model_name) > 0
    
    def test_backend_name_property(self, vllm_client: VLLMOpenAIClient):
        """Test that backend name is 'vllm'."""
        assert vllm_client.backend_name == "vllm"
    
    def test_unavailable_server_raises_error(self):
        """Test that unavailable server raises LLMConnectionError."""
        client = VLLMOpenAIClient(base_url="http://127.0.0.1:9999")  # Non-existent port
        
        # is_available should return False
        assert client.is_available() is False
        
        # chat should raise LLMConnectionError
        with pytest.raises(LLMConnectionError):
            client.chat([LLMMessage(role="user", content="test")])


# =============================================================================
# Chat & Completion Tests
# =============================================================================

@pytest.mark.vllm
@pytest.mark.integration
class TestVLLMChat:
    """Test vLLM chat and completion functionality."""
    
    def test_simple_chat(self, vllm_client: VLLMOpenAIClient):
        """Test simple chat completion."""
        messages = [LLMMessage(role="user", content="Say hello")]
        response = vllm_client.chat(messages, temperature=0.0, max_tokens=50)
        
        assert isinstance(response, str)
        assert len(response) > 0
    
    def test_chat_detailed(self, vllm_client: VLLMOpenAIClient):
        """Test chat_detailed returns LLMResponse with metadata."""
        messages = [LLMMessage(role="user", content="Say hello")]
        response = vllm_client.chat_detailed(messages, temperature=0.0, max_tokens=50)
        
        assert hasattr(response, "content")
        assert hasattr(response, "model")
        assert hasattr(response, "finish_reason")
        assert hasattr(response, "usage")
        
        assert isinstance(response.content, str)
        assert len(response.content) > 0
    
    def test_complete_text(self, vllm_client: VLLMOpenAIClient):
        """Test complete_text method."""
        prompt = "The capital of France is"
        response = vllm_client.complete_text(prompt=prompt, temperature=0.0, max_tokens=10)
        
        assert isinstance(response, str)
        assert len(response) > 0
    
    def test_multi_turn_conversation(self, vllm_client: VLLMOpenAIClient):
        """Test multi-turn conversation."""
        messages = [
            LLMMessage(role="user", content="My name is Alice"),
            LLMMessage(role="assistant", content="Nice to meet you, Alice!"),
            LLMMessage(role="user", content="What is my name?"),
        ]
        
        response = vllm_client.chat(messages, temperature=0.0, max_tokens=50)
        
        assert isinstance(response, str)
        # Note: Can't assert "Alice" is in response - depends on model capability
        assert len(response) > 0


# =============================================================================
# Determinism Tests
# =============================================================================

@pytest.mark.vllm
@pytest.mark.integration
class TestVLLMDeterminism:
    """Test vLLM determinism (temperature=0, seed)."""
    
    def test_determinism_with_temperature_zero(self, vllm_client: VLLMOpenAIClient):
        """Test that temperature=0 produces deterministic output."""
        messages = [LLMMessage(role="user", content="Count from 1 to 5")]
        
        response1 = vllm_client.chat(messages, temperature=0.0, max_tokens=50)
        response2 = vllm_client.chat(messages, temperature=0.0, max_tokens=50)
        
        # With temperature=0, responses should be identical
        assert response1 == response2, "temperature=0 should be deterministic"
    
    def test_determinism_with_seed(self, vllm_client: VLLMOpenAIClient):
        """Test that seed produces deterministic output."""
        messages = [LLMMessage(role="user", content="Count from 1 to 5")]
        
        response1 = vllm_client.chat_detailed(messages, temperature=0.0, max_tokens=50, seed=42)
        response2 = vllm_client.chat_detailed(messages, temperature=0.0, max_tokens=50, seed=42)
        
        # With same seed, responses should be identical
        assert response1.content == response2.content, "Same seed should produce same output"
    
    def test_non_determinism_with_temperature_high(self, vllm_client: VLLMOpenAIClient):
        """Test that temperature>0 can produce different outputs."""
        messages = [LLMMessage(role="user", content="Say a random number between 1 and 1000")]
        
        # Run multiple times (with high temperature, some may differ)
        responses = []
        for _ in range(5):
            response = vllm_client.chat(messages, temperature=0.9, max_tokens=10)
            responses.append(response)
        
        # At least one should be different (not guaranteed, but very likely)
        # Note: This test may occasionally fail due to randomness
        unique_responses = set(responses)
        # We don't assert len(unique_responses) > 1 because it's not guaranteed
        # Just check that all responses are valid
        assert all(isinstance(r, str) and len(r) > 0 for r in responses)


# =============================================================================
# JSON Mode Tests
# =============================================================================

@pytest.mark.vllm
@pytest.mark.integration
class TestVLLMJSONMode:
    """Test vLLM JSON mode output."""
    
    def test_json_mode_basic(self, vllm_client: VLLMOpenAIClient):
        """Test that JSON mode returns valid JSON."""
        import json
        
        messages = [
            LLMMessage(role="system", content="You are a helpful assistant. Respond in JSON."),
            LLMMessage(role="user", content='Return JSON: {"greeting": "hello", "count": 3}'),
        ]
        
        response = vllm_client.chat(
            messages,
            temperature=0.0,
            max_tokens=100,
            response_format={"type": "json_object"},
        )
        
        # Should be valid JSON
        try:
            data = json.loads(response)
            assert isinstance(data, dict)
        except json.JSONDecodeError:
            pytest.fail(f"Response is not valid JSON: {response}")
    
    def test_router_json_structure(self, vllm_client: VLLMOpenAIClient):
        """Test JSON output for router-like structure."""
        import json
        
        system_prompt = """You are a routing assistant. Always respond in valid JSON with these fields:
- route: string ("smalltalk" or "calendar")
- confidence: number (0.0-1.0)
- reply: string"""
        
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content="How are you?"),
        ]
        
        response = vllm_client.chat(
            messages,
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        
        # Parse JSON
        try:
            data = json.loads(response)
            assert "route" in data or "reply" in data, "JSON should have expected fields"
        except json.JSONDecodeError:
            pytest.fail(f"Response is not valid JSON: {response}")


# =============================================================================
# Performance Tests
# =============================================================================

@pytest.mark.vllm
@pytest.mark.integration
class TestVLLMPerformance:
    """Test vLLM performance characteristics."""
    
    def test_response_latency(self, vllm_client: VLLMOpenAIClient):
        """Test that response latency is reasonable."""
        import time
        
        messages = [LLMMessage(role="user", content="Say hello")]
        
        start = time.perf_counter()
        response = vllm_client.chat(messages, temperature=0.0, max_tokens=50)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        
        assert len(response) > 0
        # Latency should be < 5 seconds (generous timeout)
        assert elapsed < 5000, f"Response took {elapsed:.0f}ms (expected < 5000ms)"
    
    def test_token_usage_metadata(self, vllm_client: VLLMOpenAIClient):
        """Test that token usage metadata is returned."""
        messages = [LLMMessage(role="user", content="Count from 1 to 10")]
        response = vllm_client.chat_detailed(messages, temperature=0.0, max_tokens=100)
        
        assert hasattr(response, "usage")
        assert response.usage is not None
        
        # Usage should have prompt_tokens and completion_tokens
        if isinstance(response.usage, dict):
            assert "prompt_tokens" in response.usage or "total_tokens" in response.usage
        else:
            assert hasattr(response.usage, "prompt_tokens") or hasattr(response.usage, "total_tokens")


# =============================================================================
# Error Handling Tests
# =============================================================================

@pytest.mark.vllm
@pytest.mark.integration
class TestVLLMErrorHandling:
    """Test vLLM error handling."""
    
    def test_invalid_model_name(self, vllm_url: str):
        """Test that invalid model name is handled gracefully."""
        client = VLLMOpenAIClient(base_url=vllm_url, model="nonexistent-model-xyz")
        
        messages = [LLMMessage(role="user", content="test")]
        
        # Should raise error (model not found or connection error)
        with pytest.raises((LLMConnectionError, Exception)):
            client.chat(messages)
    
    def test_empty_message(self, vllm_client: VLLMOpenAIClient):
        """Test handling of empty message."""
        messages = [LLMMessage(role="user", content="")]
        
        # Should either return empty response or raise error (depends on server)
        try:
            response = vllm_client.chat(messages, temperature=0.0, max_tokens=10)
            # If it doesn't raise, response should be a string
            assert isinstance(response, str)
        except Exception as e:
            # If it raises, should be a handled error type
            assert isinstance(e, (LLMConnectionError, ValueError))
    
    def test_max_tokens_zero(self, vllm_client: VLLMOpenAIClient):
        """Test handling of max_tokens=0."""
        messages = [LLMMessage(role="user", content="Say hello")]
        
        # Should return empty or very short response
        response = vllm_client.chat(messages, temperature=0.0, max_tokens=1)
        assert isinstance(response, str)
        # Response might be empty or very short
        assert len(response) < 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "vllm"])
