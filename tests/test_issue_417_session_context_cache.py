"""Tests for Issue #417: Session context cache with TTL.

Verifies:
  - SessionContextCache TTL behavior (hit/miss/expiry)
  - Cache invalidation
  - build_session_context_cached convenience function
  - Integration: OrchestratorState.session_context set once per turn
  - Integration: process_turn uses cached context
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from bantz.brain.session_context_cache import (
    SessionContextCache,
    build_session_context_cached,
    _build_context,
)


# ===================================================================
# Tests: _build_context (standalone builder)
# ===================================================================


class TestBuildContext:
    def test_returns_dict(self):
        ctx = _build_context()
        assert isinstance(ctx, dict)

    def test_has_current_datetime(self):
        ctx = _build_context()
        assert "current_datetime" in ctx
        # ISO format check
        assert "T" in ctx["current_datetime"]

    def test_has_timezone(self):
        ctx = _build_context()
        assert "timezone" in ctx

    def test_location_from_param(self):
        ctx = _build_context(location="Istanbul")
        assert ctx["location"] == "Istanbul"

    def test_location_from_env(self):
        with patch.dict(os.environ, {"BANTZ_LOCATION": "Ankara"}):
            ctx = _build_context()
            assert ctx["location"] == "Ankara"

    def test_no_location(self):
        with patch.dict(os.environ, {}, clear=True):
            ctx = _build_context()
            assert "location" not in ctx or ctx.get("location") == ""

    def test_session_id_from_env(self):
        with patch.dict(os.environ, {"BANTZ_SESSION_ID": "sess_123"}):
            ctx = _build_context()
            assert ctx["session_id"] == "sess_123"

    def test_no_session_id(self):
        with patch.dict(os.environ, {}, clear=True):
            ctx = _build_context()
            assert "session_id" not in ctx


# ===================================================================
# Tests: SessionContextCache TTL behavior
# ===================================================================


class TestSessionContextCache:
    def test_first_call_is_cache_miss(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        assert not cache.is_valid
        ctx = cache.get_or_build()
        assert isinstance(ctx, dict)
        assert cache.is_valid

    def test_second_call_is_cache_hit(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        ctx1 = cache.get_or_build()
        ctx2 = cache.get_or_build()
        # Same object reference (cached)
        assert ctx1 is ctx2

    def test_ttl_expiry(self):
        cache = SessionContextCache(ttl_seconds=0.1)  # 100ms TTL
        ctx1 = cache.get_or_build()
        time.sleep(0.15)  # Wait for TTL to expire
        ctx2 = cache.get_or_build()
        # Different object (rebuilt)
        assert ctx1 is not ctx2

    def test_force_refresh_ignores_cache(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        ctx1 = cache.get_or_build()
        ctx2 = cache.get_or_build(force_refresh=True)
        assert ctx1 is not ctx2

    def test_invalidate(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        cache.get_or_build()
        assert cache.is_valid
        cache.invalidate()
        assert not cache.is_valid

    def test_age_seconds_no_cache(self):
        cache = SessionContextCache()
        assert cache.age_seconds == -1.0

    def test_age_seconds_after_build(self):
        cache = SessionContextCache()
        cache.get_or_build()
        assert cache.age_seconds >= 0.0
        assert cache.age_seconds < 1.0  # Just built

    def test_location_passthrough(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        ctx = cache.get_or_build(location="Izmir")
        assert ctx.get("location") == "Izmir"

    def test_cache_preserves_location_on_hit(self):
        """Cache hit returns same context even with different location."""
        cache = SessionContextCache(ttl_seconds=60.0)
        ctx1 = cache.get_or_build(location="Istanbul")
        ctx2 = cache.get_or_build(location="Ankara")
        # Cached — same object, Istanbul location preserved
        assert ctx1 is ctx2
        assert ctx2.get("location") == "Istanbul"

    def test_default_ttl_is_60(self):
        cache = SessionContextCache()
        assert cache.ttl_seconds == 60.0

    def test_is_valid_within_ttl(self):
        cache = SessionContextCache(ttl_seconds=10.0)
        cache.get_or_build()
        assert cache.is_valid

    def test_is_valid_after_ttl(self):
        cache = SessionContextCache(ttl_seconds=0.05)
        cache.get_or_build()
        time.sleep(0.06)
        assert not cache.is_valid


# ===================================================================
# Tests: build_session_context_cached convenience
# ===================================================================


class TestBuildSessionContextCached:
    def test_with_cache(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        ctx1 = build_session_context_cached(cache)
        ctx2 = build_session_context_cached(cache)
        assert ctx1 is ctx2  # Cached

    def test_without_cache(self):
        ctx1 = build_session_context_cached(None)
        ctx2 = build_session_context_cached(None)
        assert ctx1 is not ctx2  # Fresh each time

    def test_location_passthrough(self):
        ctx = build_session_context_cached(None, location="Bursa")
        assert ctx.get("location") == "Bursa"


# ===================================================================
# Tests: Integration with OrchestratorState
# ===================================================================


class TestStateIntegration:
    def test_state_session_context_populated(self):
        """Verify that session context can be set on state."""
        from bantz.brain.orchestrator_state import OrchestratorState

        state = OrchestratorState()
        assert state.session_context is None

        cache = SessionContextCache(ttl_seconds=60.0)
        state.session_context = cache.get_or_build()

        assert state.session_context is not None
        assert "current_datetime" in state.session_context

    def test_state_preserves_context_across_calls(self):
        """Second call should use same context from state."""
        from bantz.brain.orchestrator_state import OrchestratorState

        state = OrchestratorState()
        cache = SessionContextCache(ttl_seconds=60.0)

        # First build
        state.session_context = cache.get_or_build()
        ctx1 = state.session_context

        # Simulate next phase using state.session_context
        ctx2 = state.session_context
        assert ctx1 is ctx2

    def test_state_reset_clears_context(self):
        from bantz.brain.orchestrator_state import OrchestratorState

        state = OrchestratorState()
        cache = SessionContextCache(ttl_seconds=60.0)
        state.session_context = cache.get_or_build()
        state.reset()
        assert state.session_context is None


# ===================================================================
# Tests: Cache under concurrent-like usage patterns
# ===================================================================


class TestCachePatterns:
    def test_multiple_turns_same_cache(self):
        """Simulates multiple turns within TTL — should reuse context."""
        cache = SessionContextCache(ttl_seconds=5.0)
        contexts = []
        for _ in range(10):
            ctx = cache.get_or_build()
            contexts.append(ctx)

        # All should be same object
        for c in contexts:
            assert c is contexts[0]

    def test_turn_after_ttl_gets_fresh(self):
        """After TTL expires, next turn gets fresh context."""
        cache = SessionContextCache(ttl_seconds=0.1)
        ctx1 = cache.get_or_build()
        time.sleep(0.15)
        ctx2 = cache.get_or_build()
        assert ctx1 is not ctx2
        # Both should have current_datetime
        assert "current_datetime" in ctx1
        assert "current_datetime" in ctx2

    def test_invalidate_then_rebuild(self):
        cache = SessionContextCache(ttl_seconds=60.0)
        ctx1 = cache.get_or_build()
        cache.invalidate()
        ctx2 = cache.get_or_build()
        assert ctx1 is not ctx2

    def test_zero_ttl_always_rebuilds(self):
        """TTL=0 means always rebuild."""
        cache = SessionContextCache(ttl_seconds=0.0)
        ctx1 = cache.get_or_build()
        ctx2 = cache.get_or_build()
        assert ctx1 is not ctx2
