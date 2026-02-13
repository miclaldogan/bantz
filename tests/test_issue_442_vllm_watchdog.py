"""Tests for Issue #442 — vLLM Watchdog.

Covers:
- Health check detection
- Auto-restart on failure
- Max restart limit → fallback mode
- Recovery from fallback
- Event callbacks
- Thread lifecycle
- Stats
"""

from __future__ import annotations

import time
import pytest

from bantz.llm.vllm_watchdog import (
    VLLMStatus,
    VLLMWatchdog,
    WatchdogConfig,
    WatchdogEvent,
    MockHealthChecker,
    MockRestartHandler,
)


def _make_watchdog(
    healthy: bool = True,
    restart_success: bool = True,
    failure_threshold: int = 3,
    max_restarts: int = 3,
    restart_cooldown: float = 0.0,
) -> tuple:
    """Helper to create a watchdog with mock components."""
    config = WatchdogConfig(
        failure_threshold=failure_threshold,
        max_restarts=max_restarts,
        restart_cooldown=restart_cooldown,
        check_interval=0.01,
    )
    checker = MockHealthChecker(healthy=healthy)
    restarter = MockRestartHandler(success=restart_success)
    wd = VLLMWatchdog(config=config, health_checker=checker, restart_handler=restarter)
    return wd, checker, restarter


# ─── Health check ────────────────────────────────────────────────


class TestHealthCheck:
    def test_healthy_status(self):
        wd, checker, _ = _make_watchdog(healthy=True)
        status = wd.check_once()
        assert status == VLLMStatus.HEALTHY

    def test_unhealthy_increments_failures(self):
        wd, checker, _ = _make_watchdog(healthy=False, failure_threshold=5)
        wd.check_once()
        assert wd.consecutive_failures == 1
        wd.check_once()
        assert wd.consecutive_failures == 2

    def test_healthy_resets_failures(self):
        wd, checker, _ = _make_watchdog(healthy=False, failure_threshold=5)
        wd.check_once()
        wd.check_once()
        assert wd.consecutive_failures == 2
        checker.set_healthy(True)
        wd.check_once()
        assert wd.consecutive_failures == 0

    def test_unknown_initial_status(self):
        wd, _, _ = _make_watchdog()
        assert wd.status == VLLMStatus.UNKNOWN


# ─── Auto-restart ────────────────────────────────────────────────


class TestAutoRestart:
    def test_restart_on_threshold(self):
        wd, checker, restarter = _make_watchdog(
            healthy=False,
            failure_threshold=2,
            restart_success=True,
        )
        wd.check_once()  # failure 1
        assert restarter.restart_count == 0
        wd.check_once()  # failure 2 → threshold → restart
        assert restarter.restart_count == 1

    def test_successful_restart_resets_failures(self):
        wd, checker, restarter = _make_watchdog(
            healthy=False,
            failure_threshold=2,
            restart_success=True,
        )
        wd.check_once()
        wd.check_once()
        assert wd.consecutive_failures == 0  # reset after restart
        assert wd.status == VLLMStatus.HEALTHY

    def test_failed_restart_keeps_unhealthy(self):
        wd, checker, restarter = _make_watchdog(
            healthy=False,
            failure_threshold=2,
            restart_success=False,
        )
        wd.check_once()
        wd.check_once()
        assert restarter.restart_count == 1
        assert wd.status == VLLMStatus.UNHEALTHY


# ─── Max restarts → fallback ────────────────────────────────────


class TestFallbackMode:
    def test_fallback_after_max_restarts(self):
        wd, checker, restarter = _make_watchdog(
            healthy=False,
            failure_threshold=1,
            max_restarts=2,
            restart_success=False,
        )
        wd.check_once()  # fail → restart 1 (fails)
        assert wd.restart_count == 1
        wd.check_once()  # fail → restart 2 (fails)
        assert wd.restart_count == 2
        wd.check_once()  # fail → max restarts exceeded → fallback
        assert wd.is_fallback_active
        assert wd.status == VLLMStatus.DOWN

    def test_no_restart_after_fallback(self):
        wd, checker, restarter = _make_watchdog(
            healthy=False,
            failure_threshold=1,
            max_restarts=1,
            restart_success=False,
        )
        wd.check_once()  # restart 1
        wd.check_once()  # fallback
        count_before = restarter.restart_count
        wd.check_once()  # should NOT restart again
        assert restarter.restart_count == count_before

    def test_recovery_from_fallback(self):
        wd, checker, restarter = _make_watchdog(
            healthy=False,
            failure_threshold=1,
            max_restarts=1,
            restart_success=False,
        )
        wd.check_once()  # restart 1
        wd.check_once()  # fallback
        assert wd.is_fallback_active

        # vLLM comes back
        checker.set_healthy(True)
        wd.check_once()
        assert not wd.is_fallback_active
        assert wd.status == VLLMStatus.HEALTHY


# ─── Event callbacks ─────────────────────────────────────────────


class TestEvents:
    def test_health_fail_event(self):
        events = []
        wd, checker, _ = _make_watchdog(healthy=False, failure_threshold=5)
        wd.on_event(lambda e: events.append(e))
        wd.check_once()
        assert any(e.type == "health_fail" for e in events)

    def test_restart_events(self):
        events = []
        wd, checker, restarter = _make_watchdog(
            healthy=False, failure_threshold=1, restart_success=True,
        )
        wd.on_event(lambda e: events.append(e))
        wd.check_once()
        types = [e.type for e in events]
        assert "restart_attempt" in types
        assert "restart_success" in types

    def test_fallback_event(self):
        events = []
        wd, checker, restarter = _make_watchdog(
            healthy=False, failure_threshold=1, max_restarts=1, restart_success=False,
        )
        wd.on_event(lambda e: events.append(e))
        wd.check_once()  # restart 1
        wd.check_once()  # fallback
        types = [e.type for e in events]
        assert "fallback_activated" in types

    def test_recovery_event(self):
        events = []
        wd, checker, _ = _make_watchdog(
            healthy=False, failure_threshold=1, max_restarts=1, restart_success=False,
        )
        wd.on_event(lambda e: events.append(e))
        wd.check_once()
        wd.check_once()
        checker.set_healthy(True)
        wd.check_once()
        types = [e.type for e in events]
        assert "recovered" in types

    def test_event_to_dict(self):
        evt = WatchdogEvent(type="test", details={"key": "val"})
        d = evt.to_dict()
        assert d["type"] == "test"
        assert d["details"]["key"] == "val"


# ─── Thread lifecycle ────────────────────────────────────────────


class TestThreadLifecycle:
    def test_start_stop(self):
        wd, checker, _ = _make_watchdog(healthy=True)
        wd.start()
        assert wd._running
        time.sleep(0.05)
        wd.stop()
        assert not wd._running

    def test_background_checks(self):
        wd, checker, _ = _make_watchdog(healthy=True)
        wd._config.check_interval = 0.02
        wd.start()
        time.sleep(0.1)
        wd.stop()
        assert checker.check_count >= 2

    def test_double_start_no_op(self):
        wd, _, _ = _make_watchdog()
        wd.start()
        wd.start()  # should not create second thread
        wd.stop()


# ─── Stats ───────────────────────────────────────────────────────


class TestStats:
    def test_initial_stats(self):
        wd, _, _ = _make_watchdog()
        stats = wd.get_stats()
        assert stats["status"] == "unknown"
        assert stats["restart_count"] == 0
        assert stats["fallback_active"] is False

    def test_stats_after_failures(self):
        wd, checker, _ = _make_watchdog(healthy=False, failure_threshold=5)
        wd.check_once()
        wd.check_once()
        stats = wd.get_stats()
        assert stats["consecutive_failures"] == 2

    def test_recent_events(self):
        wd, checker, _ = _make_watchdog(healthy=False, failure_threshold=5)
        wd.check_once()
        events = wd.get_recent_events()
        assert len(events) >= 1
        assert events[-1]["type"] == "health_fail"

    def test_reset(self):
        wd, checker, _ = _make_watchdog(healthy=False, failure_threshold=5)
        wd.check_once()
        wd.reset()
        assert wd.status == VLLMStatus.UNKNOWN
        assert wd.consecutive_failures == 0
