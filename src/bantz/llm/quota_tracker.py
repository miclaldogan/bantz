"""Gemini API quota tracker and circuit breaker (Issue #410).

Tracks daily/monthly API usage, enforces quotas, and implements a
circuit breaker to disable Gemini temporarily after repeated failures.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "QuotaTracker",
    "QuotaExceeded",
    "CircuitBreaker",
    "CircuitOpen",
]


class QuotaExceeded(Exception):
    """Raised when Gemini API quota has been exceeded."""

    def __init__(self, message: str, daily_remaining: int = 0, monthly_remaining: int = 0):
        super().__init__(message)
        self.daily_remaining = daily_remaining
        self.monthly_remaining = monthly_remaining


class CircuitOpen(Exception):
    """Raised when the circuit breaker is open (Gemini temporarily disabled)."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Quota Tracker
# ---------------------------------------------------------------------------

@dataclass
class QuotaStats:
    """Current quota usage statistics."""

    daily_calls: int = 0
    daily_tokens: int = 0
    monthly_calls: int = 0
    monthly_tokens: int = 0
    daily_limit_calls: int = 1500
    daily_limit_tokens: int = 1_000_000
    monthly_limit_calls: int = 30000
    monthly_limit_tokens: int = 20_000_000
    current_date: str = ""
    current_month: str = ""

    @property
    def daily_calls_remaining(self) -> int:
        return max(0, self.daily_limit_calls - self.daily_calls)

    @property
    def monthly_calls_remaining(self) -> int:
        return max(0, self.monthly_limit_calls - self.monthly_calls)

    @property
    def daily_tokens_remaining(self) -> int:
        return max(0, self.daily_limit_tokens - self.daily_tokens)

    @property
    def is_daily_exceeded(self) -> bool:
        return (
            self.daily_calls >= self.daily_limit_calls
            or self.daily_tokens >= self.daily_limit_tokens
        )

    @property
    def is_monthly_exceeded(self) -> bool:
        return (
            self.monthly_calls >= self.monthly_limit_calls
            or self.monthly_tokens >= self.monthly_limit_tokens
        )


class QuotaTracker:
    """Track Gemini API call/token usage against configurable limits.

    Thread-safe. Resets daily counters at midnight, monthly at month boundary.

    Args:
        daily_limit_calls: Max API calls per day (default 1500).
        daily_limit_tokens: Max tokens per day (default 1M).
        monthly_limit_calls: Max API calls per month (default 30000).
        monthly_limit_tokens: Max tokens per month (default 20M).
    """

    def __init__(
        self,
        *,
        daily_limit_calls: int = 1500,
        daily_limit_tokens: int = 1_000_000,
        monthly_limit_calls: int = 30000,
        monthly_limit_tokens: int = 20_000_000,
    ):
        self._lock = threading.Lock()
        self._daily_calls = 0
        self._daily_tokens = 0
        self._monthly_calls = 0
        self._monthly_tokens = 0
        self._daily_limit_calls = daily_limit_calls
        self._daily_limit_tokens = daily_limit_tokens
        self._monthly_limit_calls = monthly_limit_calls
        self._monthly_limit_tokens = monthly_limit_tokens
        self._current_date = date.today().isoformat()
        self._current_month = date.today().strftime("%Y-%m")

    def _maybe_reset(self) -> None:
        """Reset counters if date/month has changed."""
        today = date.today()
        today_str = today.isoformat()
        month_str = today.strftime("%Y-%m")

        if today_str != self._current_date:
            self._daily_calls = 0
            self._daily_tokens = 0
            self._current_date = today_str
            logger.info("[QUOTA] Daily counters reset for %s", today_str)

        if month_str != self._current_month:
            self._monthly_calls = 0
            self._monthly_tokens = 0
            self._current_month = month_str
            logger.info("[QUOTA] Monthly counters reset for %s", month_str)

    def record(self, tokens_used: int = 0) -> None:
        """Record a successful API call.

        Args:
            tokens_used: Total tokens consumed (prompt + completion).
        """
        with self._lock:
            self._maybe_reset()
            self._daily_calls += 1
            self._daily_tokens += max(0, tokens_used)
            self._monthly_calls += 1
            self._monthly_tokens += max(0, tokens_used)

    def check(self) -> None:
        """Check if quota is exceeded. Raises QuotaExceeded if so."""
        with self._lock:
            self._maybe_reset()
            if self._daily_calls >= self._daily_limit_calls:
                raise QuotaExceeded(
                    f"Daily call limit exceeded ({self._daily_calls}/{self._daily_limit_calls})",
                    daily_remaining=0,
                )
            if self._daily_tokens >= self._daily_limit_tokens:
                raise QuotaExceeded(
                    f"Daily token limit exceeded ({self._daily_tokens}/{self._daily_limit_tokens})",
                    daily_remaining=self._daily_limit_calls - self._daily_calls,
                )
            if self._monthly_calls >= self._monthly_limit_calls:
                raise QuotaExceeded(
                    f"Monthly call limit exceeded ({self._monthly_calls}/{self._monthly_limit_calls})",
                    monthly_remaining=0,
                )

    def get_stats(self) -> QuotaStats:
        """Get current quota usage snapshot."""
        with self._lock:
            self._maybe_reset()
            return QuotaStats(
                daily_calls=self._daily_calls,
                daily_tokens=self._daily_tokens,
                monthly_calls=self._monthly_calls,
                monthly_tokens=self._monthly_tokens,
                daily_limit_calls=self._daily_limit_calls,
                daily_limit_tokens=self._daily_limit_tokens,
                monthly_limit_calls=self._monthly_limit_calls,
                monthly_limit_tokens=self._monthly_limit_tokens,
                current_date=self._current_date,
                current_month=self._current_month,
            )


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker for Gemini API.

    After ``failure_threshold`` consecutive failures, the circuit opens for
    ``reset_timeout`` seconds.  During that window every call raises
    ``CircuitOpen`` immediately (no API call attempted).

    States:
        CLOSED  — normal operation, failures are counted
        OPEN    — Gemini disabled, raises immediately
        HALF_OPEN — one probe call is allowed to test recovery

    Args:
        failure_threshold: Consecutive failures before opening (default 3).
        reset_timeout: Seconds to stay open before half-open probe (default 60).
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
    ):
        self._lock = threading.Lock()
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failure_count = 0
        self._state = self.CLOSED
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_transition()
            return self._state

    def _maybe_transition(self) -> None:
        """Transition from OPEN → HALF_OPEN if timeout has elapsed."""
        if self._state == self.OPEN:
            if time.monotonic() - self._last_failure_time >= self._reset_timeout:
                self._state = self.HALF_OPEN
                logger.info("[CIRCUIT] State: OPEN → HALF_OPEN (probe allowed)")

    def check(self) -> None:
        """Check if the circuit allows a call. Raises CircuitOpen if not."""
        with self._lock:
            self._maybe_transition()
            if self._state == self.OPEN:
                retry_after = self._reset_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise CircuitOpen(
                    f"Circuit breaker OPEN — Gemini temporarily disabled "
                    f"(retry in {max(0, retry_after):.0f}s)",
                    retry_after=max(0.0, retry_after),
                )
            # CLOSED and HALF_OPEN allow calls

    def record_success(self) -> None:
        """Record a successful API call. Resets failure count."""
        with self._lock:
            if self._state == self.HALF_OPEN:
                logger.info("[CIRCUIT] State: HALF_OPEN → CLOSED (probe succeeded)")
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        """Record a failed API call. Opens circuit if threshold reached."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == self.HALF_OPEN:
                # Probe failed → back to OPEN
                self._state = self.OPEN
                logger.warning("[CIRCUIT] State: HALF_OPEN → OPEN (probe failed)")
            elif self._failure_count >= self._failure_threshold:
                self._state = self.OPEN
                logger.warning(
                    "[CIRCUIT] State: CLOSED → OPEN (%d consecutive failures)",
                    self._failure_count,
                )

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED."""
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED
            logger.info("[CIRCUIT] Manually reset to CLOSED")
