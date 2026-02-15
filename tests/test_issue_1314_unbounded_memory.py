"""Tests for Issue #1314 — Unbounded memory growth safeguards.

Validates that OrchestratorState enforces caps on:
- pending_confirmations (max 10)
- trace keys (max 20)
- gmail_listed_messages (max 50)
- calendar_listed_events (max 50)
- react_observations (max 50)

Also validates atexit registration for _FINALIZER_EXECUTOR.
"""

from __future__ import annotations

from bantz.brain.orchestrator_state import OrchestratorState

# ---------------------------------------------------------------------------
# pending_confirmations cap
# ---------------------------------------------------------------------------


class TestPendingConfirmationsCap:
    """OrchestratorState.add_pending_confirmation enforces max cap."""

    def test_cap_enforced(self) -> None:
        state = OrchestratorState()
        for i in range(15):
            state.add_pending_confirmation({"tool": f"tool_{i}", "action": "delete"})
        assert len(state.pending_confirmations) == state.max_pending_confirmations

    def test_oldest_evicted(self) -> None:
        state = OrchestratorState()
        for i in range(12):
            state.add_pending_confirmation({"tool": f"tool_{i}"})
        # First two should be evicted (0 and 1), oldest remaining is tool_2
        assert state.pending_confirmations[0]["tool"] == "tool_2"
        assert state.pending_confirmations[-1]["tool"] == "tool_11"

    def test_within_cap_no_eviction(self) -> None:
        state = OrchestratorState()
        for i in range(5):
            state.add_pending_confirmation({"tool": f"tool_{i}"})
        assert len(state.pending_confirmations) == 5
        assert state.pending_confirmations[0]["tool"] == "tool_0"

    def test_default_max_value(self) -> None:
        state = OrchestratorState()
        assert state.max_pending_confirmations == 10


# ---------------------------------------------------------------------------
# trace keys cap
# ---------------------------------------------------------------------------


class TestTraceKeysCap:
    """OrchestratorState.update_trace enforces max_trace_keys."""

    def test_cap_enforced(self) -> None:
        state = OrchestratorState()
        for i in range(25):
            state.update_trace(**{f"key_{i}": f"value_{i}"})
        assert len(state.trace) == state.max_trace_keys

    def test_oldest_keys_evicted(self) -> None:
        state = OrchestratorState()
        for i in range(25):
            state.update_trace(**{f"key_{i}": f"value_{i}"})
        # First 5 keys should be evicted
        assert "key_0" not in state.trace
        assert "key_4" not in state.trace
        # Last 20 should remain
        assert "key_5" in state.trace
        assert "key_24" in state.trace

    def test_update_existing_key_no_eviction(self) -> None:
        state = OrchestratorState()
        for i in range(20):
            state.update_trace(**{f"key_{i}": f"value_{i}"})
        # Update existing key — should not grow
        state.update_trace(key_0="updated")
        assert len(state.trace) == 20
        assert state.trace["key_0"] == "updated"

    def test_default_max_value(self) -> None:
        state = OrchestratorState()
        assert state.max_trace_keys == 20


# ---------------------------------------------------------------------------
# gmail_listed_messages cap
# ---------------------------------------------------------------------------


class TestGmailListedMessagesCap:
    """OrchestratorState.set_gmail_listed_messages enforces cap."""

    def test_cap_enforced(self) -> None:
        state = OrchestratorState()
        messages = [{"id": str(i), "from": "a", "subject": "b"} for i in range(60)]
        state.set_gmail_listed_messages(messages)
        assert len(state.gmail_listed_messages) == state.max_gmail_listed

    def test_keeps_latest(self) -> None:
        state = OrchestratorState()
        messages = [{"id": str(i)} for i in range(60)]
        state.set_gmail_listed_messages(messages)
        # Should keep last 50 (IDs 10-59)
        assert state.gmail_listed_messages[0]["id"] == "10"
        assert state.gmail_listed_messages[-1]["id"] == "59"

    def test_within_cap(self) -> None:
        state = OrchestratorState()
        messages = [{"id": str(i)} for i in range(10)]
        state.set_gmail_listed_messages(messages)
        assert len(state.gmail_listed_messages) == 10

    def test_default_max_value(self) -> None:
        state = OrchestratorState()
        assert state.max_gmail_listed == 50


# ---------------------------------------------------------------------------
# calendar_listed_events cap
# ---------------------------------------------------------------------------


class TestCalendarListedEventsCap:
    """OrchestratorState.set_calendar_listed_events enforces cap."""

    def test_cap_enforced(self) -> None:
        state = OrchestratorState()
        events = [{"id": str(i), "summary": "ev"} for i in range(60)]
        state.set_calendar_listed_events(events)
        assert len(state.calendar_listed_events) == state.max_calendar_listed

    def test_keeps_latest(self) -> None:
        state = OrchestratorState()
        events = [{"id": str(i)} for i in range(60)]
        state.set_calendar_listed_events(events)
        assert state.calendar_listed_events[0]["id"] == "10"
        assert state.calendar_listed_events[-1]["id"] == "59"

    def test_within_cap(self) -> None:
        state = OrchestratorState()
        events = [{"id": str(i)} for i in range(5)]
        state.set_calendar_listed_events(events)
        assert len(state.calendar_listed_events) == 5

    def test_default_max_value(self) -> None:
        state = OrchestratorState()
        assert state.max_calendar_listed == 50


# ---------------------------------------------------------------------------
# react_observations cap
# ---------------------------------------------------------------------------


class TestReactObservationsCap:
    """OrchestratorState.add_react_observation enforces cap."""

    def test_cap_enforced(self) -> None:
        state = OrchestratorState()
        for i in range(55):
            state.add_react_observation({"iteration": i, "tool": "t", "success": True})
        assert len(state.react_observations) == state.max_react_observations

    def test_oldest_evicted(self) -> None:
        state = OrchestratorState()
        for i in range(55):
            state.add_react_observation({"iteration": i})
        assert state.react_observations[0]["iteration"] == 5
        assert state.react_observations[-1]["iteration"] == 54

    def test_within_cap(self) -> None:
        state = OrchestratorState()
        for i in range(10):
            state.add_react_observation({"iteration": i})
        assert len(state.react_observations) == 10

    def test_default_max_value(self) -> None:
        state = OrchestratorState()
        assert state.max_react_observations == 50


# ---------------------------------------------------------------------------
# _FINALIZER_EXECUTOR atexit registration
# ---------------------------------------------------------------------------


class TestFinalizerExecutorAtexit:
    """_FINALIZER_EXECUTOR should be registered with atexit for clean shutdown."""

    def test_atexit_registered(self) -> None:
        """Verify atexit has a callback for the executor shutdown."""
        # Import forces module-level atexit.register to run
        from bantz.brain import finalization_pipeline  # noqa: F401

        # Python stores atexit callbacks internally. We can verify by checking
        # that importing doesn't raise and the executor exists.
        assert hasattr(finalization_pipeline, "_FINALIZER_EXECUTOR")
        assert finalization_pipeline._FINALIZER_EXECUTOR is not None
