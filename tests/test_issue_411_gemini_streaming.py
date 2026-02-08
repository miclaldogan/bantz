"""Tests for Issue #411: Gemini streaming support.

Tests cover:
  - GeminiStreamChunk dataclass
  - chat_stream() method: successful streaming, TTFT measurement,
    error handling, circuit breaker/quota pre-flight
  - chat_stream_to_text() convenience wrapper
  - JSON parsing of streamGenerateContent response format
"""

from __future__ import annotations

import json
import time
from io import BytesIO
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from bantz.llm.gemini_client import (
    GeminiClient,
    GeminiStreamChunk,
)
from bantz.llm.quota_tracker import (
    QuotaTracker,
    CircuitBreaker,
)
from bantz.llm.base import (
    LLMMessage,
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelNotFoundError,
    LLMInvalidResponseError,
)


# ======================================================================
# Helpers
# ======================================================================


def _make_client(**kwargs) -> GeminiClient:
    defaults = dict(api_key="test-key", model="gemini-2.0-flash", timeout_seconds=5.0)
    defaults.update(kwargs)
    return GeminiClient(**defaults)


def _stream_response(chunks: list[dict], status_code: int = 200):
    """Create a mock streaming response.

    Each chunk is a dict matching Gemini streamGenerateContent format.
    The response is returned as NDJSON lines (Gemini format: JSON array).
    """
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}

    # Build NDJSON lines: Gemini wraps in JSON array
    lines = ["["]
    for i, chunk in enumerate(chunks):
        prefix = "," if i > 0 else ""
        lines.append(f"{prefix}{json.dumps(chunk)}")
    lines.append("]")

    resp.iter_lines = MagicMock(return_value=iter(lines))
    return resp


def _gemini_chunk(text: str, finish_reason: str = None) -> dict:
    """Build a single Gemini stream chunk dict."""
    cand: dict = {
        "content": {"parts": [{"text": text}]},
    }
    if finish_reason:
        cand["finishReason"] = finish_reason
    return {"candidates": [cand]}


def _gemini_finish_chunk(finish_reason: str = "STOP") -> dict:
    """Build a finish-only chunk (no text)."""
    return {"candidates": [{"finishReason": finish_reason}]}


# ======================================================================
# GeminiStreamChunk Tests
# ======================================================================


class TestGeminiStreamChunk:
    def test_defaults(self):
        chunk = GeminiStreamChunk(content="hello")
        assert chunk.content == "hello"
        assert chunk.is_first_token is False
        assert chunk.ttft_ms is None
        assert chunk.finish_reason is None

    def test_first_token(self):
        chunk = GeminiStreamChunk(content="hi", is_first_token=True, ttft_ms=42)
        assert chunk.is_first_token is True
        assert chunk.ttft_ms == 42

    def test_finish_reason(self):
        chunk = GeminiStreamChunk(content="", finish_reason="STOP")
        assert chunk.finish_reason == "STOP"


# ======================================================================
# chat_stream() Tests
# ======================================================================


class TestChatStream:
    """Tests for GeminiClient.chat_stream()."""

    @patch("bantz.llm.gemini_client.requests.post")
    def test_basic_streaming(self, mock_post):
        """Should yield chunks with correct text."""
        mock_post.return_value = _stream_response([
            _gemini_chunk("Merhaba "),
            _gemini_chunk("efendim!"),
            _gemini_finish_chunk("STOP"),
        ])
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))

        texts = [c.content for c in chunks if c.content]
        assert texts == ["Merhaba ", "efendim!"]

    @patch("bantz.llm.gemini_client.requests.post")
    def test_ttft_on_first_chunk(self, mock_post):
        """First chunk should have is_first_token=True and ttft_ms set."""
        mock_post.return_value = _stream_response([
            _gemini_chunk("Hello"),
            _gemini_chunk(" world"),
        ])
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))

        assert len(chunks) >= 2
        assert chunks[0].is_first_token is True
        assert chunks[0].ttft_ms is not None
        assert chunks[0].ttft_ms >= 0
        # Subsequent chunks should not have ttft
        assert chunks[1].is_first_token is False
        assert chunks[1].ttft_ms is None

    @patch("bantz.llm.gemini_client.requests.post")
    def test_finish_reason_propagated(self, mock_post):
        """Finish reason should appear on the appropriate chunk."""
        mock_post.return_value = _stream_response([
            _gemini_chunk("Done", finish_reason="STOP"),
        ])
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))
        assert any(c.finish_reason == "STOP" for c in chunks)

    @patch("bantz.llm.gemini_client.requests.post")
    def test_finish_only_chunk(self, mock_post):
        """A chunk with only finish_reason (no text) should be yielded."""
        mock_post.return_value = _stream_response([
            _gemini_chunk("text"),
            _gemini_finish_chunk("STOP"),
        ])
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))
        finish_chunks = [c for c in chunks if c.finish_reason == "STOP"]
        assert len(finish_chunks) >= 1

    @patch("bantz.llm.gemini_client.requests.post")
    def test_empty_stream(self, mock_post):
        """Empty stream should yield nothing."""
        mock_post.return_value = _stream_response([])
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))
        assert chunks == []

    @patch("bantz.llm.gemini_client.requests.post")
    def test_single_chunk(self, mock_post):
        """Single chunk with text and finish."""
        mock_post.return_value = _stream_response([
            _gemini_chunk("Tamam efendim.", finish_reason="STOP"),
        ])
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))
        assert len(chunks) == 1
        assert chunks[0].content == "Tamam efendim."
        assert chunks[0].is_first_token is True
        assert chunks[0].finish_reason == "STOP"

    @patch("bantz.llm.gemini_client.requests.post")
    def test_url_uses_stream_endpoint(self, mock_post):
        """Should use streamGenerateContent endpoint."""
        mock_post.return_value = _stream_response([_gemini_chunk("ok")])
        client = _make_client()
        list(client.chat_stream([LLMMessage(role="user", content="test")]))

        call_args = mock_post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "streamGenerateContent" in url

    @patch("bantz.llm.gemini_client.requests.post")
    def test_stream_flag_set(self, mock_post):
        """Should pass stream=True to requests.post."""
        mock_post.return_value = _stream_response([_gemini_chunk("ok")])
        client = _make_client()
        list(client.chat_stream([LLMMessage(role="user", content="test")]))

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs.get("stream") is True

    @patch("bantz.llm.gemini_client.requests.post")
    def test_system_message_handled(self, mock_post):
        """System messages should be in systemInstruction."""
        mock_post.return_value = _stream_response([_gemini_chunk("ok")])
        client = _make_client()
        messages = [
            LLMMessage(role="system", content="You are Jarvis."),
            LLMMessage(role="user", content="Merhaba"),
        ]
        list(client.chat_stream(messages))

        call_kwargs = mock_post.call_args[1]
        payload = json.loads(call_kwargs["data"])
        assert "systemInstruction" in payload

    @patch("bantz.llm.gemini_client.requests.post")
    def test_many_chunks(self, mock_post):
        """Should handle many small chunks."""
        chunks_data = [_gemini_chunk(f"word{i} ") for i in range(20)]
        mock_post.return_value = _stream_response(chunks_data)
        client = _make_client()
        chunks = list(client.chat_stream([LLMMessage(role="user", content="test")]))
        assert len(chunks) == 20
        assert chunks[0].is_first_token is True
        for c in chunks[1:]:
            assert c.is_first_token is False


# ======================================================================
# Error Handling Tests
# ======================================================================


class TestChatStreamErrors:
    """Tests for error handling in chat_stream."""

    @patch("bantz.llm.gemini_client.requests.post")
    def test_429_raises_connection_error(self, mock_post):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 429
        resp.headers = {}
        mock_post.return_value = resp
        client = _make_client()
        with pytest.raises(LLMConnectionError, match="rate_limited"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    @patch("bantz.llm.gemini_client.requests.post")
    def test_500_raises_connection_error(self, mock_post):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 500
        resp.headers = {}
        mock_post.return_value = resp
        client = _make_client()
        with pytest.raises(LLMConnectionError, match="server_error"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    @patch("bantz.llm.gemini_client.requests.post")
    def test_401_raises_connection_error(self, mock_post):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.headers = {}
        mock_post.return_value = resp
        client = _make_client()
        with pytest.raises(LLMConnectionError, match="auth_error"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    @patch("bantz.llm.gemini_client.requests.post")
    def test_404_raises_model_not_found(self, mock_post):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 404
        resp.headers = {}
        mock_post.return_value = resp
        client = _make_client()
        with pytest.raises(LLMModelNotFoundError, match="model_not_found"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    @patch("bantz.llm.gemini_client.requests.post")
    def test_timeout_raises(self, mock_post):
        mock_post.side_effect = requests.Timeout("timed out")
        client = _make_client()
        with pytest.raises(LLMTimeoutError, match="timeout"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    @patch("bantz.llm.gemini_client.requests.post")
    def test_connection_error_raises(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("refused")
        client = _make_client()
        with pytest.raises(LLMConnectionError, match="connection_error"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    def test_missing_api_key(self):
        client = GeminiClient(api_key="", model="test")
        with pytest.raises(LLMConnectionError, match="API key missing"):
            list(client.chat_stream([LLMMessage(role="user", content="x")]))

    def test_missing_model(self):
        client = GeminiClient(api_key="key", model="")
        with pytest.raises(LLMInvalidResponseError, match="model not set"):
            list(client.chat_stream([LLMMessage(role="user", content="x")]))


# ======================================================================
# Circuit Breaker & Quota Pre-flight Tests
# ======================================================================


class TestChatStreamPreFlight:
    """Circuit breaker and quota checks before streaming."""

    def test_circuit_open_blocks_stream(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        cb.record_failure()
        client = _make_client(circuit_breaker=cb)
        with pytest.raises(LLMConnectionError, match="circuit_open"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    def test_quota_exceeded_blocks_stream(self):
        qt = QuotaTracker(daily_limit_calls=0)
        client = _make_client(quota_tracker=qt)
        with pytest.raises(LLMConnectionError, match="quota_exceeded"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

    @patch("bantz.llm.gemini_client.requests.post")
    def test_success_records_to_circuit_breaker(self, mock_post):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        mock_post.return_value = _stream_response([_gemini_chunk("ok")])
        client = _make_client(circuit_breaker=cb)
        list(client.chat_stream([LLMMessage(role="user", content="test")]))
        assert cb.state == CircuitBreaker.CLOSED

    @patch("bantz.llm.gemini_client.requests.post")
    def test_failure_records_to_circuit_breaker(self, mock_post):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 500
        resp.headers = {}
        mock_post.return_value = resp
        client = _make_client(circuit_breaker=cb)
        with pytest.raises(LLMConnectionError):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))
        assert cb.state == CircuitBreaker.OPEN


# ======================================================================
# chat_stream_to_text() Tests
# ======================================================================


class TestChatStreamToText:
    """Tests for the convenience wrapper."""

    @patch("bantz.llm.gemini_client.requests.post")
    def test_collects_full_text(self, mock_post):
        mock_post.return_value = _stream_response([
            _gemini_chunk("Merhaba "),
            _gemini_chunk("efendim!"),
        ])
        client = _make_client()
        text, ttft = client.chat_stream_to_text(
            [LLMMessage(role="user", content="test")]
        )
        assert text == "Merhaba efendim!"
        assert ttft is not None
        assert ttft >= 0

    @patch("bantz.llm.gemini_client.requests.post")
    def test_empty_stream_returns_empty(self, mock_post):
        mock_post.return_value = _stream_response([])
        client = _make_client()
        text, ttft = client.chat_stream_to_text(
            [LLMMessage(role="user", content="test")]
        )
        assert text == ""
        assert ttft is None

    @patch("bantz.llm.gemini_client.requests.post")
    def test_single_chunk(self, mock_post):
        mock_post.return_value = _stream_response([
            _gemini_chunk("Tamam.", finish_reason="STOP"),
        ])
        client = _make_client()
        text, ttft = client.chat_stream_to_text(
            [LLMMessage(role="user", content="test")]
        )
        assert text == "Tamam."
        assert ttft is not None


# ======================================================================
# Metrics Tests
# ======================================================================


class TestStreamMetrics:
    """Tests for streaming metrics logging."""

    @patch("bantz.llm.gemini_client.requests.post")
    def test_metrics_logged_on_success(self, mock_post, monkeypatch, caplog):
        monkeypatch.setenv("BANTZ_LLM_METRICS", "1")
        mock_post.return_value = _stream_response([
            _gemini_chunk("test"),
        ])
        client = _make_client()
        import logging

        with caplog.at_level(logging.INFO, logger="bantz.llm.metrics"):
            list(client.chat_stream([LLMMessage(role="user", content="test")]))

        assert any("llm_stream" in r.getMessage() for r in caplog.records)
        log_text = "\n".join(r.getMessage() for r in caplog.records)
        assert "backend=gemini" in log_text
        assert "ttft_ms=" in log_text
        assert "chunks=" in log_text
