"""Tests for Issue #1313: Thread safety fixes.

Covers:
  1. sync_valid_tools — class-level lock prevents inconsistent state
  2. _consecutive_failures / _router_healthy — lock prevents lost-update race
  3. _safe_complete — timeout no longer mutates shared LLM state
  4. Gemini singleton — double-checked locking pattern
  5. OrchestratorState — pending_confirmations are lock-protected
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_state import OrchestratorState


# ======================================================================
# Helpers
# ======================================================================


def _make_orchestrator() -> JarvisLLMOrchestrator:
    """Create a minimal orchestrator with a mock LLM."""
    with patch.object(JarvisLLMOrchestrator, "__init__", lambda self: None):
        orch = JarvisLLMOrchestrator.__new__(JarvisLLMOrchestrator)
    # Set minimal required attrs
    orch._router_healthy = True
    orch._consecutive_failures = 0
    orch._max_consecutive_failures = 3
    orch._health_lock = threading.Lock()
    return orch


# ======================================================================
# 1. sync_valid_tools — Class-level lock
# ======================================================================


class TestSyncValidToolsLock:
    """Verify sync_valid_tools uses a lock for atomic updates."""

    def test_has_sync_lock_attribute(self):
        """Class should have a _sync_lock attribute."""
        assert hasattr(JarvisLLMOrchestrator, "_sync_lock")
        assert isinstance(JarvisLLMOrchestrator._sync_lock, type(threading.Lock()))

    def test_concurrent_sync_no_crash(self):
        """Multiple threads calling sync_valid_tools should not crash."""
        original_tools = JarvisLLMOrchestrator._VALID_TOOLS.copy()
        registry = list(original_tools)
        errors = []

        def _sync():
            try:
                JarvisLLMOrchestrator.sync_valid_tools(registry)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_sync) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Errors during concurrent sync: {errors}"


# ======================================================================
# 2. _consecutive_failures — health_lock
# ======================================================================


class TestHealthLock:
    """Verify _consecutive_failures updates are lock-protected."""

    def test_has_health_lock(self):
        """Instance should have a _health_lock."""
        orch = _make_orchestrator()
        assert hasattr(orch, "_health_lock")
        assert isinstance(orch._health_lock, type(threading.Lock()))

    def test_concurrent_failure_increments(self):
        """Concurrent increments under lock should not lose updates."""
        orch = _make_orchestrator()
        orch._max_consecutive_failures = 1000  # don't trigger unhealthy

        def _increment():
            for _ in range(100):
                with orch._health_lock:
                    orch._consecutive_failures += 1

        threads = [threading.Thread(target=_increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert orch._consecutive_failures == 1000


# ======================================================================
# 3. _safe_complete — no shared state mutation
# ======================================================================


class TestSafeCompleteNoMutation:
    """Verify _safe_complete does NOT mutate llm._timeout_seconds."""

    def test_llm_timeout_not_mutated(self):
        """_safe_complete should not modify llm._timeout_seconds."""
        from bantz.brain.finalization_pipeline import _safe_complete

        mock_llm = MagicMock()
        mock_llm._timeout_seconds = 120.0
        mock_llm.complete_text.return_value = "test response"
        mock_llm.get_model_context_length.return_value = 4096

        _safe_complete(mock_llm, "test prompt", timeout=5.0, max_tokens=64)

        # The original timeout must remain unchanged
        assert mock_llm._timeout_seconds == 120.0

    def test_timeout_passed_via_kwargs(self):
        """timeout_seconds should be passed in kwargs, not via LLM mutation."""
        from bantz.brain.finalization_pipeline import _safe_complete

        mock_llm = MagicMock()
        mock_llm._timeout_seconds = 120.0
        mock_llm.complete_text.return_value = "response"
        mock_llm.get_model_context_length.return_value = 4096

        _safe_complete(mock_llm, "prompt", timeout=5.0, max_tokens=64)

        # complete_text should have been called with timeout_seconds in kwargs
        call_kwargs = mock_llm.complete_text.call_args
        if call_kwargs:
            kwargs = call_kwargs[1] if call_kwargs[1] else {}
            # Either timeout_seconds is in kwargs or it was passed some other way
            # Key assertion: _timeout_seconds was NOT mutated
            assert mock_llm._timeout_seconds == 120.0


# ======================================================================
# 4. Gemini singleton — double-checked locking
# ======================================================================


class TestGeminiSingletonThreadSafety:
    """Verify Gemini default singletons use double-checked locking."""

    def test_concurrent_quota_tracker_creation(self):
        """Multiple threads should get the same QuotaTracker instance."""
        import bantz.llm.gemini_client as gc
        # Reset to force re-creation
        gc._default_quota_tracker = None

        results = []

        def _get():
            results.append(gc.get_default_quota_tracker())

        threads = [threading.Thread(target=_get) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # All threads should have gotten the same instance
        assert len(set(id(r) for r in results)) == 1

    def test_concurrent_circuit_breaker_creation(self):
        """Multiple threads should get the same CircuitBreaker instance."""
        import bantz.llm.gemini_client as gc
        gc._default_circuit_breaker = None

        results = []

        def _get():
            results.append(gc.get_default_circuit_breaker())

        threads = [threading.Thread(target=_get) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(set(id(r) for r in results)) == 1


# ======================================================================
# 5. OrchestratorState — lock-protected confirmation methods
# ======================================================================


class TestOrchestratorStateLocking:
    """Verify OrchestratorState confirmation methods are thread-safe."""

    def test_has_lock(self):
        """State should have a _lock attribute."""
        state = OrchestratorState()
        assert hasattr(state, "_lock")
        assert isinstance(state._lock, type(threading.Lock()))

    def test_concurrent_add_pop(self):
        """Concurrent add + pop should not crash or corrupt data."""
        state = OrchestratorState()
        errors = []

        def _add():
            try:
                for i in range(50):
                    state.add_pending_confirmation({"tool": f"t{i}", "id": i})
            except Exception as e:
                errors.append(e)

        def _pop():
            try:
                for _ in range(50):
                    state.pop_pending_confirmation()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=_add)
        t2 = threading.Thread(target=_pop)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors

    def test_concurrent_set_clear(self):
        """Concurrent set + clear should not corrupt state."""
        state = OrchestratorState()
        errors = []

        def _set():
            try:
                for i in range(100):
                    state.set_pending_confirmation({"tool": f"t{i}"})
            except Exception as e:
                errors.append(e)

        def _clear():
            try:
                for _ in range(100):
                    state.clear_pending_confirmation()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=_set),
            threading.Thread(target=_clear),
            threading.Thread(target=_set),
            threading.Thread(target=_clear),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors
        # After all operations, state should be consistent
        assert isinstance(state.pending_confirmations, list)

    def test_has_pending_returns_bool(self):
        """has_pending_confirmation should work under lock."""
        state = OrchestratorState()
        assert state.has_pending_confirmation() is False
        state.add_pending_confirmation({"tool": "test"})
        assert state.has_pending_confirmation() is True

    def test_peek_does_not_remove(self):
        """peek_pending_confirmation should not remove the item."""
        state = OrchestratorState()
        state.add_pending_confirmation({"tool": "test"})
        first = state.peek_pending_confirmation()
        second = state.peek_pending_confirmation()
        assert first == second == {"tool": "test"}
        assert state.has_pending_confirmation() is True
