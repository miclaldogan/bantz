"""Tests for issue #461 — vLLM watchdog v0."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bantz.llm.vllm_watchdog_v0 import (
    HealthStatus,
    VLLMStatus,
    VLLMWatchdogV0,
    WatchdogConfig,
)


# ── helpers ───────────────────────────────────────────────────────────

def _healthy_checker(url: str, timeout: float) -> HealthStatus:
    return HealthStatus(is_healthy=True, response_time_ms=50.0)


def _unhealthy_checker(url: str, timeout: float) -> HealthStatus:
    return HealthStatus(is_healthy=False, error="Connection refused")


# ── TestHealthyVLLM ──────────────────────────────────────────────────

class TestHealthyVLLM:
    def test_healthy_no_action(self):
        wd = VLLMWatchdogV0(health_checker=_healthy_checker)
        result = wd.check()
        assert result.is_healthy
        assert wd.status == VLLMStatus.HEALTHY
        assert wd.consecutive_failures == 0

    def test_metrics_after_healthy_check(self):
        wd = VLLMWatchdogV0(health_checker=_healthy_checker)
        wd.check()
        m = wd.get_metrics()
        assert m["status"] == "healthy"
        assert m["total_checks"] == 1
        assert m["total_failures"] == 0


# ── TestConsecutiveFailures ──────────────────────────────────────────

class TestConsecutiveFailures:
    def test_degraded_after_one_failure(self):
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            config=WatchdogConfig(consecutive_failures_to_restart=3),
        )
        wd.check()
        assert wd.status == VLLMStatus.DEGRADED
        assert wd.consecutive_failures == 1

    def test_down_after_threshold(self):
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            config=WatchdogConfig(consecutive_failures_to_restart=3),
        )
        for _ in range(3):
            wd.check()
        assert wd.status == VLLMStatus.DOWN
        assert wd.consecutive_failures == 3


# ── TestAutoRestart ──────────────────────────────────────────────────

class TestAutoRestart:
    def test_restart_triggered(self):
        restarter = MagicMock(return_value=True)
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            restarter=restarter,
            config=WatchdogConfig(consecutive_failures_to_restart=3),
        )
        for _ in range(3):
            wd.check()
        restarter.assert_called_once()

    def test_restart_success_status(self):
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            restarter=lambda: True,
            config=WatchdogConfig(consecutive_failures_to_restart=2),
        )
        for _ in range(2):
            wd.check()
        assert wd.status == VLLMStatus.DEGRADED  # after successful restart, waiting warmup

    def test_restart_failure_stays_down(self):
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            restarter=lambda: False,
            config=WatchdogConfig(consecutive_failures_to_restart=2),
        )
        for _ in range(2):
            wd.check()
        assert wd.status == VLLMStatus.DOWN

    def test_no_restarter_configured(self):
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            config=WatchdogConfig(consecutive_failures_to_restart=2),
        )
        for _ in range(2):
            wd.check()
        assert wd.status == VLLMStatus.DOWN


# ── TestMaxRestartsPerHour ───────────────────────────────────────────

class TestMaxRestarts:
    def test_max_restarts_per_hour(self):
        restarter = MagicMock(return_value=True)
        config = WatchdogConfig(
            consecutive_failures_to_restart=1,
            max_restarts_per_hour=2,
        )
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            restarter=restarter,
            config=config,
        )
        # 3 checks → should try restart at each, but max 2 allowed
        for _ in range(3):
            wd.check()
        assert restarter.call_count == 2  # capped at 2


# ── TestGeminiFallback ───────────────────────────────────────────────

class TestGeminiFallback:
    def test_fallback_enabled_on_down(self):
        toggler = MagicMock()
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            fallback_toggler=toggler,
            config=WatchdogConfig(consecutive_failures_to_restart=2),
        )
        for _ in range(2):
            wd.check()
        toggler.assert_called_with(True)
        assert wd.is_fallback_active

    def test_fallback_disabled_on_recovery(self):
        call_count = {"n": 0}

        def alternating_checker(url, timeout):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return HealthStatus(is_healthy=False, error="down")
            return HealthStatus(is_healthy=True, response_time_ms=50)

        toggler = MagicMock()
        wd = VLLMWatchdogV0(
            health_checker=alternating_checker,
            fallback_toggler=toggler,
            config=WatchdogConfig(consecutive_failures_to_restart=2),
        )
        wd.check()  # fail 1
        wd.check()  # fail 2 → fallback on
        wd.check()  # healthy → fallback off
        assert toggler.call_count == 2
        toggler.assert_called_with(False)
        assert not wd.is_fallback_active


# ── TestStartupCheck ─────────────────────────────────────────────────

class TestStartupCheck:
    def test_startup_healthy(self):
        wd = VLLMWatchdogV0(health_checker=_healthy_checker)
        assert wd.startup_check() is True
        assert wd.status == VLLMStatus.HEALTHY

    def test_startup_unhealthy_enables_fallback(self):
        toggler = MagicMock()
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            fallback_toggler=toggler,
            config=WatchdogConfig(consecutive_failures_to_restart=10),
        )
        assert wd.startup_check() is False
        toggler.assert_called_with(True)


# ── TestEventLogger ──────────────────────────────────────────────────

class TestEventLogger:
    def test_restart_event_logged(self):
        event_log = MagicMock()
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            restarter=lambda: True,
            event_logger=event_log,
            config=WatchdogConfig(consecutive_failures_to_restart=1),
        )
        wd.check()
        event_log.assert_any_call("vllm_restart", {"success": True, "consecutive_failures": 1})

    def test_fallback_event_logged(self):
        event_log = MagicMock()
        wd = VLLMWatchdogV0(
            health_checker=_unhealthy_checker,
            event_logger=event_log,
            config=WatchdogConfig(consecutive_failures_to_restart=1),
        )
        wd.check()
        event_log.assert_any_call("gemini_fallback", {"enabled": True})


# ── TestRecovery ─────────────────────────────────────────────────────

class TestRecovery:
    def test_recovery_resets_failures(self):
        call_count = {"n": 0}

        def checker(url, timeout):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return HealthStatus(is_healthy=False, error="x")
            return HealthStatus(is_healthy=True, response_time_ms=10)

        wd = VLLMWatchdogV0(
            health_checker=checker,
            config=WatchdogConfig(consecutive_failures_to_restart=5),
        )
        wd.check()  # fail
        wd.check()  # fail
        assert wd.consecutive_failures == 2
        wd.check()  # ok
        assert wd.consecutive_failures == 0
        assert wd.status == VLLMStatus.HEALTHY
