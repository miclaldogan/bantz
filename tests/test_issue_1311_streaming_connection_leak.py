"""Tests for Issue #1311: Streaming connection leak prevention.

Verifies that both vLLM and Gemini streaming clients properly close
underlying HTTP connections/streams in all scenarios:
  - Normal completion (generator fully consumed)
  - Early exit (caller breaks out of generator)
  - Exception during iteration
  - Gemini retry loop (429/500 responses closed before retry)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from bantz.llm.base import (
    LLMMessage,
    LLMConnectionError,
    LLMTimeoutError,
    LLMInvalidResponseError,
)
from bantz.llm.vllm_openai_client import VLLMOpenAIClient, StreamChunk
from bantz.llm.gemini_client import GeminiClient, GeminiStreamChunk


# ======================================================================
# Helpers
# ======================================================================


def _vllm_client() -> VLLMOpenAIClient:
    """Create a vLLM client for testing (no real server)."""
    return VLLMOpenAIClient(
        base_url="http://127.0.0.1:9999",
        model="test-model",
        track_ttft=False,
    )


def _gemini_client() -> GeminiClient:
    """Create a Gemini client for testing."""
    return GeminiClient(
        api_key="test-key",
        model="gemini-2.0-flash",
        timeout_seconds=5.0,
        use_default_gates=False,
    )


def _messages() -> list[LLMMessage]:
    return [LLMMessage(role="user", content="test")]


def _mock_openai_chunk(content: str, finish_reason: str | None = None):
    """Build a mock OpenAI-style streaming chunk."""
    delta = MagicMock()
    delta.content = content

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason

    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


def _mock_openai_stream(chunks: list):
    """Create a mock stream object that supports iteration and close()."""
    stream = MagicMock()
    stream.__iter__ = MagicMock(return_value=iter(chunks))
    stream.close = MagicMock()
    return stream


def _gemini_stream_response(chunks: list[dict], status_code: int = 200):
    """Create a mock Gemini streaming response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}

    lines = ["["]
    for i, chunk in enumerate(chunks):
        prefix = "," if i > 0 else ""
        lines.append(f"{prefix}{json.dumps(chunk)}")
    lines.append("]")

    resp.iter_lines = MagicMock(return_value=iter(lines))
    resp.close = MagicMock()
    return resp


def _gemini_chunk(text: str, finish_reason: str | None = None) -> dict:
    """Build a single Gemini stream chunk dict."""
    cand: dict = {"content": {"parts": [{"text": text}]}}
    if finish_reason:
        cand["finishReason"] = finish_reason
    return {"candidates": [cand]}


# ======================================================================
# vLLM Stream Cleanup Tests
# ======================================================================


class TestVLLMStreamCleanup:
    """Verify vLLM chat_stream() closes the stream in all scenarios."""

    @patch.object(VLLMOpenAIClient, "_get_client")
    @patch.object(VLLMOpenAIClient, "_resolve_auto_model")
    def test_stream_closed_after_full_consumption(self, _mock_resolve, mock_get_client):
        """Stream.close() is called when generator is fully consumed."""
        chunks = [
            _mock_openai_chunk("Hello "),
            _mock_openai_chunk("world!", "stop"),
        ]
        stream = _mock_openai_stream(chunks)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = stream
        mock_get_client.return_value = mock_client

        client = _vllm_client()
        result = list(client.chat_stream(_messages()))

        assert len(result) >= 1
        stream.close.assert_called_once()

    @patch.object(VLLMOpenAIClient, "_get_client")
    @patch.object(VLLMOpenAIClient, "_resolve_auto_model")
    def test_stream_closed_on_early_exit(self, _mock_resolve, mock_get_client):
        """Stream.close() is called when caller breaks out of generator early."""
        chunks = [
            _mock_openai_chunk("Hello "),
            _mock_openai_chunk("world "),
            _mock_openai_chunk("this "),
            _mock_openai_chunk("is "),
            _mock_openai_chunk("long!", "stop"),
        ]
        stream = _mock_openai_stream(chunks)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = stream
        mock_get_client.return_value = mock_client

        client = _vllm_client()
        gen = client.chat_stream(_messages())
        first_chunk = next(gen)
        assert first_chunk.content == "Hello "
        # Simulate early exit — caller closes generator
        gen.close()

        stream.close.assert_called_once()

    @patch.object(VLLMOpenAIClient, "_get_client")
    @patch.object(VLLMOpenAIClient, "_resolve_auto_model")
    def test_stream_closed_on_iteration_error(self, _mock_resolve, mock_get_client):
        """Stream.close() is called when iteration raises an exception."""
        def _exploding_iter():
            yield _mock_openai_chunk("Hello ")
            raise ConnectionError("connection reset")

        stream = MagicMock()
        stream.__iter__ = MagicMock(return_value=_exploding_iter())
        stream.close = MagicMock()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = stream
        mock_get_client.return_value = mock_client

        client = _vllm_client()
        with pytest.raises(LLMConnectionError):
            list(client.chat_stream(_messages()))

        stream.close.assert_called_once()

    @patch.object(VLLMOpenAIClient, "_get_client")
    @patch.object(VLLMOpenAIClient, "_resolve_auto_model")
    def test_stream_closed_on_timeout_error(self, _mock_resolve, mock_get_client):
        """Stream.close() is called on timeout during iteration."""
        def _timeout_iter():
            yield _mock_openai_chunk("partial")
            raise TimeoutError("request timeout exceeded")

        stream = MagicMock()
        stream.__iter__ = MagicMock(return_value=_timeout_iter())
        stream.close = MagicMock()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = stream
        mock_get_client.return_value = mock_client

        client = _vllm_client()
        with pytest.raises(LLMTimeoutError):
            list(client.chat_stream(_messages()))

        stream.close.assert_called_once()

    @patch.object(VLLMOpenAIClient, "_get_client")
    @patch.object(VLLMOpenAIClient, "_resolve_auto_model")
    def test_no_error_if_stream_creation_fails(self, _mock_resolve, mock_get_client):
        """No crash in finally when stream was never created (creation error)."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = ConnectionError("refused")
        mock_get_client.return_value = mock_client

        client = _vllm_client()
        with pytest.raises(LLMConnectionError):
            list(client.chat_stream(_messages()))
        # Should not crash — stream is None, finally handles gracefully

    @patch.object(VLLMOpenAIClient, "_get_client")
    @patch.object(VLLMOpenAIClient, "_resolve_auto_model")
    def test_empty_stream_still_closed(self, _mock_resolve, mock_get_client):
        """Stream.close() called even when stream yields no content chunks."""
        stream = _mock_openai_stream([])
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = stream
        mock_get_client.return_value = mock_client

        client = _vllm_client()
        result = list(client.chat_stream(_messages()))
        assert result == []
        stream.close.assert_called_once()


# ======================================================================
# Gemini Stream Cleanup Tests
# ======================================================================


class TestGeminiStreamCleanup:
    """Verify GeminiClient.chat_stream() closes responses in all scenarios."""

    @patch("bantz.llm.gemini_client.requests.post")
    def test_response_closed_after_full_consumption(self, mock_post):
        """Response.close() called when stream is fully consumed."""
        resp = _gemini_stream_response([
            _gemini_chunk("Merhaba "),
            _gemini_chunk("efendim!", "STOP"),
        ])
        mock_post.return_value = resp

        client = _gemini_client()
        chunks = list(client.chat_stream(_messages()))

        assert len(chunks) >= 1
        resp.close.assert_called()

    @patch("bantz.llm.gemini_client.requests.post")
    def test_response_closed_on_early_exit(self, mock_post):
        """Response.close() called when caller breaks out early."""
        resp = _gemini_stream_response([
            _gemini_chunk("chunk1 "),
            _gemini_chunk("chunk2 "),
            _gemini_chunk("chunk3!", "STOP"),
        ])
        mock_post.return_value = resp

        client = _gemini_client()
        gen = client.chat_stream(_messages())
        first = next(gen)
        assert first.content == "chunk1 "
        gen.close()

        resp.close.assert_called()

    @patch("bantz.llm.gemini_client.requests.post")
    def test_response_closed_on_error_status(self, mock_post):
        """Response.close() called even when status indicates error."""
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.headers = {}
        resp.close = MagicMock()
        mock_post.return_value = resp

        client = _gemini_client()
        with pytest.raises(LLMConnectionError, match="auth_error"):
            list(client.chat_stream(_messages()))

        resp.close.assert_called()

    @patch("bantz.llm.gemini_client.requests.post")
    def test_response_closed_on_parse_error(self, mock_post):
        """Response.close() called when JSON parsing fails."""
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.headers = {}
        resp.iter_lines = MagicMock(return_value=iter(["not valid json {"]))
        resp.close = MagicMock()
        mock_post.return_value = resp

        client = _gemini_client()
        # Stream should complete without error (partial JSON buffered)
        # or raise parse_error — either way, response must be closed
        try:
            list(client.chat_stream(_messages()))
        except (LLMInvalidResponseError, StopIteration):
            pass

        resp.close.assert_called()


class TestGeminiRetryCleanup:
    """Verify Gemini retry loop closes responses before retrying."""

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_429_response_closed_before_retry(self, mock_post, mock_sleep):
        """On 429, response is closed before the next retry attempt."""
        # First call: 429, second call: success
        resp_429 = MagicMock(spec=requests.Response)
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.close = MagicMock()

        resp_ok = _gemini_stream_response([_gemini_chunk("ok", "STOP")])
        mock_post.side_effect = [resp_429, resp_ok]

        client = _gemini_client()
        chunks = list(client.chat_stream(_messages()))

        assert len(chunks) >= 1
        # The 429 response must have been closed
        resp_429.close.assert_called()

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_500_response_closed_before_retry(self, mock_post, mock_sleep):
        """On 500, response is closed before the next retry attempt."""
        resp_500 = MagicMock(spec=requests.Response)
        resp_500.status_code = 500
        resp_500.headers = {}
        resp_500.close = MagicMock()

        resp_ok = _gemini_stream_response([_gemini_chunk("ok", "STOP")])
        mock_post.side_effect = [resp_500, resp_ok]

        client = _gemini_client()
        chunks = list(client.chat_stream(_messages()))

        assert len(chunks) >= 1
        resp_500.close.assert_called()

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_multiple_retries_all_closed(self, mock_post, mock_sleep):
        """Multiple failed responses are all closed before final success."""
        resp_429 = MagicMock(spec=requests.Response)
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.close = MagicMock()

        resp_500 = MagicMock(spec=requests.Response)
        resp_500.status_code = 500
        resp_500.headers = {}
        resp_500.close = MagicMock()

        resp_ok = _gemini_stream_response([_gemini_chunk("ok", "STOP")])
        mock_post.side_effect = [resp_429, resp_500, resp_ok]

        client = _gemini_client()
        chunks = list(client.chat_stream(_messages()))

        assert len(chunks) >= 1
        resp_429.close.assert_called()
        resp_500.close.assert_called()

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_all_retries_exhausted_last_response_closed(self, mock_post, mock_sleep):
        """When all retries fail with 500, the final response is also closed."""
        responses = []
        for _ in range(3):
            resp = MagicMock(spec=requests.Response)
            resp.status_code = 500
            resp.headers = {}
            resp.close = MagicMock()
            responses.append(resp)
        mock_post.side_effect = responses

        client = _gemini_client()
        with pytest.raises(LLMConnectionError, match="server_error"):
            list(client.chat_stream(_messages()))

        # First two closed in retry loop, last closed in finally
        for resp in responses:
            resp.close.assert_called()
