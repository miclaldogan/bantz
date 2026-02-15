"""
Circuit Breaker Pattern (Issue #32 - V2-2).

Implements the circuit breaker pattern to prevent cascading failures
when external services are unavailable.

States:
- CLOSED: Normal operation, requests allowed
- OPEN: Service is failing, requests blocked
- HALF_OPEN: Testing if service recovered
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking requests
    HALF_OPEN = "half_open" # Testing recovery


@dataclass
class CircuitStats:
    """
    Statistics for a domain's circuit breaker.
    
    Attributes:
        failures: Consecutive failure count
        successes: Consecutive success count (in HALF_OPEN)
        last_failure: Timestamp of last failure
        last_success: Timestamp of last success
        state: Current circuit state
        opened_at: When circuit was opened
    """
    failures: int = 0
    successes: int = 0
    last_failure: Optional[datetime] = None
    last_success: Optional[datetime] = None
    state: CircuitState = CircuitState.CLOSED
    opened_at: Optional[datetime] = None
    
    def reset(self) -> None:
        """Reset all counters to initial state."""
        self.failures = 0
        self.successes = 0
        self.last_failure = None
        self.state = CircuitState.CLOSED
        self.opened_at = None


class CircuitBreaker:
    """
    Circuit breaker to protect against cascading failures.
    
    Tracks failures per domain and opens the circuit when
    the failure threshold is reached. After reset_timeout,
    the circuit enters HALF_OPEN state to test recovery.
    
    Attributes:
        failure_threshold: Number of failures before opening (default 3)
        reset_timeout: Seconds before OPEN → HALF_OPEN (default 60)
        success_threshold: Successes needed in HALF_OPEN to close (default 1)
    
    Example:
        breaker = CircuitBreaker()
        
        if breaker.is_open("google.com"):
            # Use fallback
            return fallback_result
        
        try:
            result = await fetch("google.com")
            breaker.record_success("google.com")
            return result
        except Exception:
            breaker.record_failure("google.com")
            raise
    """
    
    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,
        success_threshold: int = 1
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold
        self._stats: dict[str, CircuitStats] = {}
        self._lock = threading.Lock()
    
    def _get_stats(self, domain: str) -> CircuitStats:
        """Get or create stats for domain."""
        if domain not in self._stats:
            self._stats[domain] = CircuitStats()
        return self._stats[domain]
    
    def record_success(self, domain: str) -> None:
        """
        Record a successful request for domain.
        
        In CLOSED state: resets failure counter
        In HALF_OPEN state: increments success counter, may close circuit
        In OPEN state: ignored
        """
        with self._lock:
            stats = self._get_stats(domain)
            stats.last_success = datetime.now()
            
            if stats.state == CircuitState.CLOSED:
                # Reset failures on success
                stats.failures = 0
            
            elif stats.state == CircuitState.HALF_OPEN:
                stats.successes += 1
                if stats.successes >= self.success_threshold:
                    # Recovery confirmed, close circuit
                    stats.reset()
    
    def record_failure(self, domain: str) -> None:
        """
        Record a failed request for domain.
        
        In CLOSED state: increments failure counter, may open circuit
        In HALF_OPEN state: reopens circuit
        In OPEN state: updates timestamp
        """
        with self._lock:
            stats = self._get_stats(domain)
            stats.last_failure = datetime.now()
            
            if stats.state == CircuitState.CLOSED:
                stats.failures += 1
                if stats.failures >= self.failure_threshold:
                    # Threshold reached, open circuit
                    stats.state = CircuitState.OPEN
                    stats.opened_at = datetime.now()
            
            elif stats.state == CircuitState.HALF_OPEN:
                # Recovery failed, reopen circuit
                stats.state = CircuitState.OPEN
                stats.opened_at = datetime.now()
                stats.successes = 0
    
    def is_open(self, domain: str) -> bool:
        """
        Check if circuit is open for domain.
        
        Returns True if requests should be blocked.
        Also handles OPEN → HALF_OPEN transition after timeout.
        """
        with self._lock:
            stats = self._get_stats(domain)
            
            if stats.state == CircuitState.CLOSED:
                return False
            
            if stats.state == CircuitState.OPEN:
                # Check if reset timeout has passed
                if stats.opened_at:
                    elapsed = (datetime.now() - stats.opened_at).total_seconds()
                    if elapsed >= self.reset_timeout:
                        # Transition to HALF_OPEN
                        stats.state = CircuitState.HALF_OPEN
                        stats.successes = 0
                        return False
                return True
            
            # HALF_OPEN: allow request (testing recovery)
            return False
    
    def get_state(self, domain: str) -> CircuitState:
        """Get current circuit state for domain."""
        with self._lock:
            # Check for timeout transition first
            self._check_half_open_transition(domain)
            return self._get_stats(domain).state
    
    def _check_half_open_transition(self, domain: str) -> None:
        """Check if OPEN circuit should transition to HALF_OPEN."""
        stats = self._get_stats(domain)
        if stats.state == CircuitState.OPEN and stats.opened_at:
            elapsed = (datetime.now() - stats.opened_at).total_seconds()
            if elapsed >= self.reset_timeout:
                stats.state = CircuitState.HALF_OPEN
                stats.successes = 0
    
    def get_stats(self, domain: str) -> CircuitStats:
        """Get stats for domain (copy)."""
        with self._lock:
            stats = self._get_stats(domain)
            # Return a copy
            return CircuitStats(
                failures=stats.failures,
                successes=stats.successes,
                last_failure=stats.last_failure,
                last_success=stats.last_success,
                state=stats.state,
                opened_at=stats.opened_at
            )
    
    def reset(self, domain: str) -> None:
        """Manually reset circuit for domain."""
        with self._lock:
            if domain in self._stats:
                self._stats[domain].reset()
    
    def reset_all(self) -> None:
        """Reset all circuits."""
        with self._lock:
            self._stats.clear()
    
    @property
    def domains(self) -> list[str]:
        """List all tracked domains."""
        with self._lock:
            return list(self._stats.keys())

    async def call(
        self,
        domain: str,
        fn: Callable[..., Any],
        *args: Any,
        fallback: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute *fn* through the circuit breaker.

        If the circuit is open and a *fallback* is provided, the fallback
        is called instead of raising.  Both sync and async callables are
        supported for *fn* and *fallback*.

        Raises ``CircuitOpenError`` when no fallback is available and the
        circuit is open.
        """
        if self.is_open(domain):
            logger.warning("[CB] Circuit OPEN for '%s'", domain)
            if fallback is not None:
                result = fallback(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            raise CircuitOpenError(domain)

        try:
            result = fn(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            self.record_success(domain)
            return result
        except Exception:
            self.record_failure(domain)
            if self.is_open(domain) and fallback is not None:
                fb = fallback(*args, **kwargs)
                if asyncio.iscoroutine(fb):
                    fb = await fb
                return fb
            raise

    def to_dict(self) -> dict[str, Any]:
        """Serialize all domain states for health reporting."""
        with self._lock:
            out: dict[str, Any] = {}
            for domain in list(self._stats):
                self._check_half_open_transition(domain)
                s = self._stats[domain]
                out[domain] = {
                    "state": s.state.value,
                    "failures": s.failures,
                    "successes": s.successes,
                    "last_failure": (
                        s.last_failure.isoformat() if s.last_failure else None
                    ),
                    "last_success": (
                        s.last_success.isoformat() if s.last_success else None
                    ),
                    "opened_at": (
                        s.opened_at.isoformat() if s.opened_at else None
                    ),
                }
            return out


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit with no fallback."""

    def __init__(self, domain: str) -> None:
        self.domain = domain
        super().__init__(f"Circuit open for '{domain}'")


# Singleton instance
_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    """Get or create the global CircuitBreaker instance."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
