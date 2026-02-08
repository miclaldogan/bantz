"""Tests for Issue #410: Gemini rate-limit + quota management.

Tests cover:
  - QuotaTracker: daily/monthly limits, auto-reset, thread safety
  - CircuitBreaker: state transitions, threshold, timeout, probe
  - GeminiClient retry: exponential backoff, retryable codes, non-retryable codes
  - GeminiClient integration: circuit breaker + quota pre-flight checks
  - Rate limit header parsing
  - Backoff calculation
"""

from __future__ import annotations

import threading
import time
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from bantz.llm.quota_tracker import (
    QuotaTracker,
    QuotaExceeded,
    QuotaStats,
    CircuitBreaker,
    CircuitOpen,
)
from bantz.llm.gemini_client import (
    GeminiClient,
    _calculate_backoff,
    _parse_rate_limit_remaining,
    _parse_retry_after,
    RETRY_MAX_ATTEMPTS,
    RETRY_BASE_DELAY,
    RETRY_BACKOFF_FACTOR,
    RETRY_MAX_DELAY,
    RETRYABLE_STATUS_CODES,
)
from bantz.llm.base import (
    LLMMessage,
    LLMConnectionError,
    LLMTimeoutError,
    LLMModelNotFoundError,
    LLMInvalidResponseError,
)


# ======================================================================
# QuotaTracker Tests
# ======================================================================


class TestQuotaTracker:
    """Tests for QuotaTracker daily/monthly limits."""

    def test_record_and_check_within_limits(self):
        qt = QuotaTracker(daily_limit_calls=10, monthly_limit_calls=100)
        for _ in range(5):
            qt.record(tokens_used=50)
        qt.check()  # Should not raise

    def test_daily_call_limit_exceeded(self):
        qt = QuotaTracker(daily_limit_calls=3, monthly_limit_calls=100)
        for _ in range(3):
            qt.record(tokens_used=10)
        with pytest.raises(QuotaExceeded, match="Daily call limit"):
            qt.check()

    def test_daily_token_limit_exceeded(self):
        qt = QuotaTracker(daily_limit_calls=1000, daily_limit_tokens=100)
        qt.record(tokens_used=100)
        with pytest.raises(QuotaExceeded, match="Daily token limit"):
            qt.check()

    def test_monthly_call_limit_exceeded(self):
        qt = QuotaTracker(daily_limit_calls=1000, monthly_limit_calls=2)
        qt.record(tokens_used=1)
        qt.record(tokens_used=1)
        with pytest.raises(QuotaExceeded, match="Monthly call limit"):
            qt.check()

    def test_negative_tokens_clamped_to_zero(self):
        qt = QuotaTracker()
        qt.record(tokens_used=-100)
        stats = qt.get_stats()
        assert stats.daily_tokens == 0

    def test_get_stats_snapshot(self):
        qt = QuotaTracker(daily_limit_calls=50, daily_limit_tokens=5000)
        qt.record(tokens_used=200)
        qt.record(tokens_used=300)
        stats = qt.get_stats()
        assert stats.daily_calls == 2
        assert stats.daily_tokens == 500
        assert stats.monthly_calls == 2
        assert stats.daily_calls_remaining == 48
        assert stats.daily_tokens_remaining == 4500

    def test_stats_properties(self):
        stats = QuotaStats(
            daily_calls=10,
            daily_tokens=500,
            daily_limit_calls=10,
            daily_limit_tokens=1000,
            monthly_calls=50,
            monthly_limit_calls=100,
        )
        assert stats.is_daily_exceeded is True  # calls hit limit
        assert stats.is_monthly_exceeded is False
        assert stats.daily_calls_remaining == 0
        assert stats.monthly_calls_remaining == 50

    def test_daily_reset_on_date_change(self):
        qt = QuotaTracker(daily_limit_calls=5)
        qt.record(tokens_used=10)
        qt.record(tokens_used=10)
        assert qt.get_stats().daily_calls == 2

        # Simulate date change
        qt._current_date = "2020-01-01"
        stats = qt.get_stats()
        assert stats.daily_calls == 0  # Reset happened

    def test_monthly_reset_on_month_change(self):
        qt = QuotaTracker(monthly_limit_calls=5)
        qt.record(tokens_used=10)
        qt.record(tokens_used=10)
        assert qt.get_stats().monthly_calls == 2

        # Simulate month change
        qt._current_month = "2020-01"
        stats = qt.get_stats()
        assert stats.monthly_calls == 0

    def test_thread_safety(self):
        """Concurrent record calls should not lose data."""
        qt = QuotaTracker(daily_limit_calls=100_000, monthly_limit_calls=100_000)
        n_threads = 10
        n_per_thread = 100
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            for _ in range(n_per_thread):
                qt.record(tokens_used=1)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = qt.get_stats()
        assert stats.daily_calls == n_threads * n_per_thread
        assert stats.daily_tokens == n_threads * n_per_thread

    def test_quota_exceeded_attributes(self):
        exc = QuotaExceeded("test", daily_remaining=5, monthly_remaining=100)
        assert exc.daily_remaining == 5
        assert exc.monthly_remaining == 100
        assert str(exc) == "test"


# ======================================================================
# CircuitBreaker Tests
# ======================================================================


class TestCircuitBreaker:
    """Tests for CircuitBreaker state machine."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreaker.CLOSED

    def test_check_passes_when_closed(self):
        cb = CircuitBreaker()
        cb.check()  # No exception

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

    def test_open_circuit_raises(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        cb.record_failure()
        with pytest.raises(CircuitOpen, match="Circuit breaker OPEN"):
            cb.check()

    def test_circuit_open_retry_after(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        cb.record_failure()
        try:
            cb.check()
        except CircuitOpen as e:
            assert e.retry_after > 0
            assert e.retry_after <= 60

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED
        # One more failure should not open (count reset)
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        time.sleep(0.1)
        assert cb.state == CircuitBreaker.HALF_OPEN

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
        cb.record_failure()
        time.sleep(0.1)
        assert cb.state == CircuitBreaker.HALF_OPEN
        cb.check()  # Should pass (half-open allows probe)
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)
        cb.record_failure()
        time.sleep(0.1)
        assert cb.state == CircuitBreaker.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

    def test_manual_reset(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=999)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        cb.reset()
        assert cb.state == CircuitBreaker.CLOSED
        cb.check()  # No exception

    def test_thread_safety(self):
        cb = CircuitBreaker(failure_threshold=100, reset_timeout=60)
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            for _ in range(10):
                cb.record_failure()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cb.state == CircuitBreaker.OPEN


# ======================================================================
# Backoff & Header Parsing Tests
# ======================================================================


class TestBackoffCalculation:
    """Tests for exponential backoff computation."""

    def test_first_attempt_base_delay(self):
        # With no retry-after, attempt 1 → ~base_delay (±25% jitter)
        delays = [_calculate_backoff(1) for _ in range(20)]
        for d in delays:
            assert RETRY_BASE_DELAY * 0.7 <= d <= RETRY_BASE_DELAY * 1.3

    def test_second_attempt_doubled(self):
        delays = [_calculate_backoff(2) for _ in range(20)]
        expected = RETRY_BASE_DELAY * RETRY_BACKOFF_FACTOR
        for d in delays:
            assert expected * 0.7 <= d <= expected * 1.3

    def test_capped_at_max_delay(self):
        # Very high attempt number should be capped
        d = _calculate_backoff(100)
        assert d <= RETRY_MAX_DELAY

    def test_retry_after_header_honoured(self):
        d = _calculate_backoff(1, retry_after_header=5.0)
        assert d == 5.0

    def test_retry_after_header_capped(self):
        d = _calculate_backoff(1, retry_after_header=9999.0)
        assert d == RETRY_MAX_DELAY


class TestHeaderParsing:
    """Tests for rate limit header parsers."""

    def test_parse_remaining_standard(self):
        assert _parse_rate_limit_remaining({"X-RateLimit-Remaining": "42"}) == 42

    def test_parse_remaining_lowercase(self):
        assert _parse_rate_limit_remaining({"x-ratelimit-remaining": "7"}) == 7

    def test_parse_remaining_missing(self):
        assert _parse_rate_limit_remaining({}) is None

    def test_parse_remaining_invalid(self):
        assert _parse_rate_limit_remaining({"X-RateLimit-Remaining": "abc"}) is None

    def test_parse_retry_after_seconds(self):
        assert _parse_retry_after({"Retry-After": "30"}) == 30.0

    def test_parse_retry_after_float(self):
        assert _parse_retry_after({"Retry-After": "2.5"}) == 2.5

    def test_parse_retry_after_missing(self):
        assert _parse_retry_after({}) is None


# ======================================================================
# GeminiClient Retry Integration Tests
# ======================================================================


def _make_client(
    *,
    quota_tracker=None,
    circuit_breaker=None,
    max_retries=3,
) -> GeminiClient:
    """Create a GeminiClient for testing."""
    return GeminiClient(
        api_key="test-key",
        model="gemini-2.0-flash",
        timeout_seconds=5.0,
        quota_tracker=quota_tracker,
        circuit_breaker=circuit_breaker,
        max_retries=max_retries,
    )


def _mock_response(status_code=200, json_data=None, headers=None):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    if json_data is None:
        json_data = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Merhaba efendim!"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15,
            },
        }
    resp.json.return_value = json_data
    return resp


class TestGeminiRetry:
    """Tests for retry logic in GeminiClient.chat_detailed."""

    @patch("bantz.llm.gemini_client.requests.post")
    def test_success_no_retry(self, mock_post):
        """Successful call should not retry."""
        mock_post.return_value = _mock_response(200)
        client = _make_client()
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"
        assert mock_post.call_count == 1

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_429_retries_then_succeeds(self, mock_post, mock_sleep):
        """429 should trigger retry and succeed on second attempt."""
        mock_post.side_effect = [
            _mock_response(429, headers={"Retry-After": "1"}),
            _mock_response(200),
        ]
        client = _make_client(max_retries=3)
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"
        assert mock_post.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_500_retries_then_succeeds(self, mock_post, mock_sleep):
        """500 should trigger retry."""
        mock_post.side_effect = [
            _mock_response(500),
            _mock_response(200),
        ]
        client = _make_client(max_retries=3)
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"
        assert mock_post.call_count == 2

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_503_retries_then_succeeds(self, mock_post, mock_sleep):
        """503 should trigger retry."""
        mock_post.side_effect = [
            _mock_response(503),
            _mock_response(503),
            _mock_response(200),
        ]
        client = _make_client(max_retries=3)
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"
        assert mock_post.call_count == 3

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_429_all_retries_exhausted(self, mock_post, mock_sleep):
        """If all retries return 429, should raise LLMConnectionError."""
        mock_post.return_value = _mock_response(429)
        client = _make_client(max_retries=3)
        with pytest.raises(LLMConnectionError, match="rate_limited"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 3

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_500_all_retries_exhausted(self, mock_post, mock_sleep):
        """If all retries return 500, should raise LLMConnectionError."""
        mock_post.return_value = _mock_response(500)
        client = _make_client(max_retries=3)
        with pytest.raises(LLMConnectionError, match="server_error"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 3

    @patch("bantz.llm.gemini_client.requests.post")
    def test_401_no_retry(self, mock_post):
        """401 should not retry — immediate auth error."""
        mock_post.return_value = _mock_response(401)
        client = _make_client(max_retries=3)
        with pytest.raises(LLMConnectionError, match="auth_error"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 1

    @patch("bantz.llm.gemini_client.requests.post")
    def test_404_no_retry(self, mock_post):
        """404 should not retry — model not found."""
        mock_post.return_value = _mock_response(404)
        client = _make_client(max_retries=3)
        with pytest.raises(LLMModelNotFoundError, match="model_not_found"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 1

    @patch("bantz.llm.gemini_client.requests.post")
    def test_400_no_retry(self, mock_post):
        """400 should not retry — invalid request."""
        mock_post.return_value = _mock_response(400)
        client = _make_client(max_retries=3)
        with pytest.raises(LLMInvalidResponseError, match="invalid_request"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 1

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_timeout_retries(self, mock_post, mock_sleep):
        """Timeout should trigger retry."""
        mock_post.side_effect = [
            requests.Timeout("timed out"),
            _mock_response(200),
        ]
        client = _make_client(max_retries=3)
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"
        assert mock_post.call_count == 2

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_timeout_all_retries_exhausted(self, mock_post, mock_sleep):
        """If all retries timeout, should raise LLMTimeoutError."""
        mock_post.side_effect = requests.Timeout("timed out")
        client = _make_client(max_retries=2)
        with pytest.raises(LLMTimeoutError, match="timeout"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 2

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_connection_error_retries(self, mock_post, mock_sleep):
        """Connection error should trigger retry."""
        mock_post.side_effect = [
            requests.ConnectionError("refused"),
            _mock_response(200),
        ]
        client = _make_client(max_retries=3)
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_connection_error_all_retries_exhausted(self, mock_post, mock_sleep):
        """All connection errors → LLMConnectionError."""
        mock_post.side_effect = requests.ConnectionError("refused")
        client = _make_client(max_retries=2)
        with pytest.raises(LLMConnectionError, match="connection_error"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 2

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_retry_after_header_honoured(self, mock_post, mock_sleep):
        """Retry-After header should set sleep delay."""
        mock_post.side_effect = [
            _mock_response(429, headers={"Retry-After": "5"}),
            _mock_response(200),
        ]
        client = _make_client(max_retries=3)
        client.chat_detailed([LLMMessage(role="user", content="test")])
        # sleep should have been called with ~5.0
        assert mock_sleep.call_count == 1
        actual_delay = mock_sleep.call_args[0][0]
        assert 4.5 <= actual_delay <= 5.5

    @patch("bantz.llm.gemini_client.requests.post")
    def test_max_retries_1_no_retry(self, mock_post):
        """max_retries=1 means only one attempt, no retry."""
        mock_post.return_value = _mock_response(429)
        client = _make_client(max_retries=1)
        with pytest.raises(LLMConnectionError, match="rate_limited"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 1


# ======================================================================
# Circuit Breaker Integration with GeminiClient
# ======================================================================


class TestGeminiCircuitBreaker:
    """Tests for circuit breaker integration in GeminiClient."""

    def test_circuit_open_blocks_call(self):
        """When circuit is open, chat_detailed should not make HTTP call."""
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        cb.record_failure()  # Opens circuit
        client = _make_client(circuit_breaker=cb)
        with pytest.raises(LLMConnectionError, match="circuit_open"):
            client.chat_detailed([LLMMessage(role="user", content="test")])

    @patch("bantz.llm.gemini_client.requests.post")
    def test_success_resets_circuit(self, mock_post):
        """Successful call should reset circuit breaker."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        client = _make_client(circuit_breaker=cb)
        mock_post.return_value = _mock_response(200)
        client.chat_detailed([LLMMessage(role="user", content="test")])
        assert cb.state == CircuitBreaker.CLOSED

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_retries_exhausted_opens_circuit(self, mock_post, mock_sleep):
        """All retries failing should record circuit failure."""
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        client = _make_client(circuit_breaker=cb, max_retries=2)
        mock_post.return_value = _mock_response(500)
        with pytest.raises(LLMConnectionError):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert cb.state == CircuitBreaker.OPEN

    def test_circuit_open_turkish_message(self):
        """User-facing error should include Turkish message."""
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        cb.record_failure()
        client = _make_client(circuit_breaker=cb)
        with pytest.raises(LLMConnectionError, match="yerel model"):
            client.chat_detailed([LLMMessage(role="user", content="test")])


# ======================================================================
# Quota Tracker Integration with GeminiClient
# ======================================================================


class TestGeminiQuota:
    """Tests for quota tracker integration in GeminiClient."""

    def test_quota_exceeded_blocks_call(self):
        """When quota exceeded, should not make HTTP call."""
        qt = QuotaTracker(daily_limit_calls=1)
        qt.record(tokens_used=10)  # Exhaust quota
        client = _make_client(quota_tracker=qt)
        with pytest.raises(LLMConnectionError, match="quota_exceeded"):
            client.chat_detailed([LLMMessage(role="user", content="test")])

    @patch("bantz.llm.gemini_client.requests.post")
    def test_success_records_quota(self, mock_post):
        """Successful call should record usage to quota tracker."""
        qt = QuotaTracker(daily_limit_calls=100)
        client = _make_client(quota_tracker=qt)
        mock_post.return_value = _mock_response(200)
        client.chat_detailed([LLMMessage(role="user", content="test")])
        stats = qt.get_stats()
        assert stats.daily_calls == 1
        assert stats.daily_tokens == 15  # totalTokenCount from mock

    def test_quota_exceeded_turkish_message(self):
        """User-facing error should include Turkish message."""
        qt = QuotaTracker(daily_limit_calls=0)
        client = _make_client(quota_tracker=qt)
        with pytest.raises(LLMConnectionError, match="yerel model"):
            client.chat_detailed([LLMMessage(role="user", content="test")])

    @patch("bantz.llm.gemini_client.requests.post")
    def test_quota_not_recorded_on_failure(self, mock_post):
        """Failed call should not count towards quota tokens."""
        qt = QuotaTracker(daily_limit_calls=100)
        client = _make_client(quota_tracker=qt, max_retries=1)
        mock_post.return_value = _mock_response(401)
        with pytest.raises(LLMConnectionError):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        stats = qt.get_stats()
        assert stats.daily_calls == 0  # Not recorded for non-success


# ======================================================================
# Combined: Circuit Breaker + Quota + Retry
# ======================================================================


class TestGeminiFullIntegration:
    """Full integration: CB checked first, then quota, then retry."""

    def test_circuit_checked_before_quota(self):
        """Circuit check happens before quota check."""
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=60)
        cb.record_failure()
        qt = QuotaTracker(daily_limit_calls=0)  # Also exceeded
        client = _make_client(circuit_breaker=cb, quota_tracker=qt)
        with pytest.raises(LLMConnectionError, match="circuit_open"):
            client.chat_detailed([LLMMessage(role="user", content="test")])

    @patch("bantz.llm.gemini_client.requests.post")
    def test_quota_checked_before_http_call(self, mock_post):
        """Quota check prevents HTTP call."""
        qt = QuotaTracker(daily_limit_calls=0)
        client = _make_client(quota_tracker=qt)
        with pytest.raises(LLMConnectionError, match="quota_exceeded"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert mock_post.call_count == 0

    @patch("bantz.llm.gemini_client.time.sleep")
    @patch("bantz.llm.gemini_client.requests.post")
    def test_retry_with_circuit_and_quota(self, mock_post, mock_sleep):
        """Full flow: quota OK → retry on 503 → success → record both."""
        cb = CircuitBreaker(failure_threshold=5)
        qt = QuotaTracker(daily_limit_calls=100)
        client = _make_client(circuit_breaker=cb, quota_tracker=qt, max_retries=3)
        mock_post.side_effect = [
            _mock_response(503),
            _mock_response(200),
        ]
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"
        assert cb.state == CircuitBreaker.CLOSED
        assert qt.get_stats().daily_calls == 1

    @patch("bantz.llm.gemini_client.requests.post")
    def test_no_tracker_no_breaker_still_works(self, mock_post):
        """Client without tracker/breaker should work normally."""
        client = _make_client()
        mock_post.return_value = _mock_response(200)
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "Merhaba efendim!"


# ======================================================================
# Edge Cases
# ======================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_missing_api_key_raises_immediately(self):
        client = GeminiClient(api_key="", model="test")
        with pytest.raises(LLMConnectionError, match="API key missing"):
            client.chat_detailed([LLMMessage(role="user", content="x")])

    def test_missing_model_raises_immediately(self):
        client = GeminiClient(api_key="key", model="")
        with pytest.raises(LLMInvalidResponseError, match="model not set"):
            client.chat_detailed([LLMMessage(role="user", content="x")])

    @patch("bantz.llm.gemini_client.requests.post")
    def test_response_with_no_usage_metadata(self, mock_post):
        """Response without usageMetadata should still work."""
        mock_post.return_value = _mock_response(
            200,
            json_data={
                "candidates": [
                    {"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}
                ]
            },
        )
        client = _make_client()
        result = client.chat_detailed([LLMMessage(role="user", content="test")])
        assert result.content == "OK"

    @patch("bantz.llm.gemini_client.requests.post")
    def test_rate_limit_warning_logged(self, mock_post, caplog):
        """When X-RateLimit-Remaining is low, a warning should be logged."""
        mock_post.return_value = _mock_response(
            200, headers={"X-RateLimit-Remaining": "3"}
        )
        client = _make_client()
        import logging

        with caplog.at_level(logging.WARNING, logger="bantz.llm.gemini_client"):
            client.chat_detailed([LLMMessage(role="user", content="test")])
        assert "nearly exhausted" in caplog.text

    def test_retryable_status_codes_constant(self):
        """Ensure the retryable codes include expected values."""
        assert 429 in RETRYABLE_STATUS_CODES
        assert 500 in RETRYABLE_STATUS_CODES
        assert 502 in RETRYABLE_STATUS_CODES
        assert 503 in RETRYABLE_STATUS_CODES
        assert 401 not in RETRYABLE_STATUS_CODES
        assert 404 not in RETRYABLE_STATUS_CODES
