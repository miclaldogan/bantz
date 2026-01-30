"""
Tests for Circuit Breaker (Issue #32 - V2-2).

Tests CircuitBreaker, CircuitState, and CircuitStats.
"""

import pytest
from datetime import datetime, timedelta
import time

from bantz.agent.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitStats,
    get_circuit_breaker,
)


class TestCircuitState:
    """Test CircuitState enum."""
    
    def test_circuit_state_values(self):
        """All states have correct values."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitStats:
    """Test CircuitStats dataclass."""
    
    def test_circuit_stats_defaults(self):
        """Stats have correct defaults."""
        stats = CircuitStats()
        assert stats.failures == 0
        assert stats.successes == 0
        assert stats.last_failure is None
        assert stats.state == CircuitState.CLOSED
    
    def test_circuit_stats_reset(self):
        """reset() clears all counters."""
        stats = CircuitStats(
            failures=5,
            successes=2,
            last_failure=datetime.now(),
            state=CircuitState.OPEN
        )
        stats.reset()
        assert stats.failures == 0
        assert stats.successes == 0
        assert stats.state == CircuitState.CLOSED


class TestCircuitBreakerClosed:
    """Test CLOSED state behavior."""
    
    def test_circuit_initial_closed(self):
        """New domain starts in CLOSED state."""
        breaker = CircuitBreaker()
        assert breaker.get_state("test.com") == CircuitState.CLOSED
        assert breaker.is_open("test.com") is False
    
    def test_circuit_stays_closed_under_threshold(self):
        """Circuit stays CLOSED with fewer than threshold failures."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # Record 2 failures (below threshold of 3)
        breaker.record_failure("test.com")
        breaker.record_failure("test.com")
        
        assert breaker.get_state("test.com") == CircuitState.CLOSED
        assert breaker.is_open("test.com") is False
    
    def test_circuit_success_resets_failures(self):
        """Success in CLOSED state resets failure counter."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        breaker.record_failure("test.com")
        breaker.record_failure("test.com")
        # Now at 2 failures
        
        breaker.record_success("test.com")
        # Failures should reset to 0
        
        breaker.record_failure("test.com")
        breaker.record_failure("test.com")
        # Only 2 failures again
        
        assert breaker.get_state("test.com") == CircuitState.CLOSED


class TestCircuitBreakerOpen:
    """Test OPEN state behavior."""
    
    def test_circuit_opens_at_threshold(self):
        """Circuit opens when failure threshold reached."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        breaker.record_failure("test.com")
        breaker.record_failure("test.com")
        breaker.record_failure("test.com")  # Threshold reached
        
        assert breaker.get_state("test.com") == CircuitState.OPEN
    
    def test_circuit_blocks_when_open(self):
        """OPEN circuit blocks requests."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # Open the circuit
        for _ in range(3):
            breaker.record_failure("test.com")
        
        assert breaker.is_open("test.com") is True
    
    def test_circuit_per_domain_isolation(self):
        """Each domain has isolated circuit."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # Open circuit for domain A
        for _ in range(3):
            breaker.record_failure("domain-a.com")
        
        # Domain B should still be closed
        assert breaker.get_state("domain-a.com") == CircuitState.OPEN
        assert breaker.get_state("domain-b.com") == CircuitState.CLOSED
        assert breaker.is_open("domain-b.com") is False


class TestCircuitBreakerHalfOpen:
    """Test HALF_OPEN state behavior."""
    
    def test_circuit_half_open_after_timeout(self):
        """Circuit transitions to HALF_OPEN after reset_timeout."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            reset_timeout=0.1  # 100ms for testing
        )
        
        # Open the circuit
        for _ in range(3):
            breaker.record_failure("test.com")
        
        assert breaker.get_state("test.com") == CircuitState.OPEN
        
        # Wait for reset timeout
        time.sleep(0.15)
        
        # Should transition to HALF_OPEN
        assert breaker.get_state("test.com") == CircuitState.HALF_OPEN
    
    def test_circuit_half_open_allows_request(self):
        """HALF_OPEN allows test request."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            reset_timeout=0.1
        )
        
        # Open the circuit
        for _ in range(3):
            breaker.record_failure("test.com")
        
        # Wait for transition
        time.sleep(0.15)
        
        # HALF_OPEN should not block
        assert breaker.is_open("test.com") is False
    
    def test_circuit_closes_on_half_open_success(self):
        """HALF_OPEN + success → CLOSED."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            reset_timeout=0.1,
            success_threshold=1
        )
        
        # Open the circuit
        for _ in range(3):
            breaker.record_failure("test.com")
        
        # Wait for HALF_OPEN
        time.sleep(0.15)
        assert breaker.get_state("test.com") == CircuitState.HALF_OPEN
        
        # Record success
        breaker.record_success("test.com")
        
        # Should close
        assert breaker.get_state("test.com") == CircuitState.CLOSED
    
    def test_circuit_opens_on_half_open_failure(self):
        """HALF_OPEN + failure → OPEN."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            reset_timeout=0.1
        )
        
        # Open the circuit
        for _ in range(3):
            breaker.record_failure("test.com")
        
        # Wait for HALF_OPEN
        time.sleep(0.15)
        assert breaker.get_state("test.com") == CircuitState.HALF_OPEN
        
        # Record failure
        breaker.record_failure("test.com")
        
        # Should reopen
        assert breaker.get_state("test.com") == CircuitState.OPEN


class TestCircuitBreakerMethods:
    """Test CircuitBreaker utility methods."""
    
    def test_get_stats(self):
        """get_stats returns copy of stats."""
        breaker = CircuitBreaker()
        
        breaker.record_failure("test.com")
        breaker.record_failure("test.com")
        
        stats = breaker.get_stats("test.com")
        assert stats.failures == 2
        assert stats.state == CircuitState.CLOSED
    
    def test_reset_domain(self):
        """reset() resets specific domain."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # Open circuit
        for _ in range(3):
            breaker.record_failure("test.com")
        
        assert breaker.get_state("test.com") == CircuitState.OPEN
        
        # Reset
        breaker.reset("test.com")
        
        assert breaker.get_state("test.com") == CircuitState.CLOSED
    
    def test_reset_all(self):
        """reset_all() clears all circuits."""
        breaker = CircuitBreaker(failure_threshold=3)
        
        # Open circuits for multiple domains
        for domain in ["a.com", "b.com", "c.com"]:
            for _ in range(3):
                breaker.record_failure(domain)
        
        # Reset all
        breaker.reset_all()
        
        for domain in ["a.com", "b.com", "c.com"]:
            assert breaker.get_state(domain) == CircuitState.CLOSED
    
    def test_domains_list(self):
        """domains property lists all tracked domains."""
        breaker = CircuitBreaker()
        
        breaker.record_failure("a.com")
        breaker.record_failure("b.com")
        
        domains = breaker.domains
        assert "a.com" in domains
        assert "b.com" in domains


class TestCircuitBreakerSingleton:
    """Test singleton pattern."""
    
    def test_get_circuit_breaker_singleton(self):
        """get_circuit_breaker returns same instance."""
        # Reset global
        import bantz.agent.circuit_breaker as cb
        cb._circuit_breaker = None
        
        breaker1 = get_circuit_breaker()
        breaker2 = get_circuit_breaker()
        
        assert breaker1 is breaker2
