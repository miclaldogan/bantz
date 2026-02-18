"""Tests for Issue #1298 — Graceful degradation event wiring & health CLI.

Covers:
- CircuitBreaker emits CIRCUIT_OPENED / CIRCUIT_CLOSED events
- FallbackRegistry emits FALLBACK_EXECUTED events
- HealthMonitor emits HEALTH_DEGRADED / HEALTH_RECOVERED events
- ``bantz health`` CLI subcommand output & exit codes
- Integration: CB ↔ HealthMonitor ↔ FallbackRegistry event flow
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset all singletons before each test."""
    from bantz.core.events import get_event_bus
    from bantz.agent.circuit_breaker import get_circuit_breaker
    from bantz.core.health_monitor import reset_health_monitor
    from bantz.core.fallback_registry import reset_fallback_registry

    bus = get_event_bus()
    bus._subscribers.clear()
    bus._middleware.clear()

    cb = get_circuit_breaker()
    cb.reset_all()

    reset_health_monitor()
    reset_fallback_registry()
    yield


@pytest.fixture
def event_bus():
    from bantz.core.events import get_event_bus
    return get_event_bus()


@pytest.fixture
def circuit_breaker():
    from bantz.agent.circuit_breaker import CircuitBreaker
    return CircuitBreaker(failure_threshold=3, reset_timeout=0.1, success_threshold=1)


@pytest.fixture
def health_monitor(event_bus):
    from bantz.core.health_monitor import HealthMonitor
    return HealthMonitor(event_bus=event_bus, check_interval=1)


@pytest.fixture
def fallback_registry(tmp_path):
    from bantz.core.fallback_registry import FallbackRegistry
    return FallbackRegistry(cache_dir=tmp_path)


# ═══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER EVENT TESTS
# ═══════════════════════════════════════════════════════════════

class TestCircuitBreakerEvents:
    """CircuitBreaker should emit events on state transitions."""

    def test_circuit_opened_event_on_threshold(self, event_bus):
        """CIRCUIT_OPENED emitted when failures reach threshold."""
        from bantz.agent.circuit_breaker import CircuitBreaker

        received = []
        event_bus.subscribe("system.circuit_opened", lambda e: received.append(e))

        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("ollama")
        cb.record_failure("ollama")
        assert len(received) == 0  # Not yet

        cb.record_failure("ollama")  # Threshold reached
        assert len(received) == 1
        assert received[0].data["domain"] == "ollama"
        assert "3 consecutive failures" in received[0].data["message"]

    def test_circuit_closed_event_on_recovery(self, event_bus):
        """CIRCUIT_CLOSED emitted when half-open probe succeeds."""
        from bantz.agent.circuit_breaker import CircuitBreaker

        received = []
        event_bus.subscribe("system.circuit_closed", lambda e: received.append(e))

        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0, success_threshold=1)
        cb.record_failure("google")
        cb.record_failure("google")  # → OPEN

        # Force half-open via is_open (timeout=0)
        import time
        time.sleep(0.01)
        assert cb.is_open("google") is False  # transitions to HALF_OPEN

        cb.record_success("google")  # → CLOSED
        assert len(received) == 1
        assert received[0].data["domain"] == "google"
        assert "recovery confirmed" in received[0].data["message"]

    def test_circuit_reopened_event_on_half_open_failure(self, event_bus):
        """CIRCUIT_OPENED re-emitted when half-open probe fails."""
        from bantz.agent.circuit_breaker import CircuitBreaker

        received = []
        event_bus.subscribe("system.circuit_opened", lambda e: received.append(e))

        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0, success_threshold=1)
        cb.record_failure("neo4j")
        cb.record_failure("neo4j")  # → OPEN (event #1)
        assert len(received) == 1

        import time
        time.sleep(0.01)
        cb.is_open("neo4j")  # → HALF_OPEN
        cb.record_failure("neo4j")  # → OPEN again (event #2)
        assert len(received) == 2
        assert "half-open probe failed" in received[1].data["message"]

    def test_no_event_on_normal_failure(self, event_bus):
        """No event when failures are below threshold."""
        from bantz.agent.circuit_breaker import CircuitBreaker

        received = []
        event_bus.subscribe("system.circuit_opened", lambda e: received.append(e))

        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure("sqlite")
        cb.record_failure("sqlite")
        assert len(received) == 0

    def test_no_event_on_normal_success(self, event_bus):
        """No event when recording success in CLOSED state."""
        from bantz.agent.circuit_breaker import CircuitBreaker

        received = []
        event_bus.subscribe("system.circuit_closed", lambda e: received.append(e))

        cb = CircuitBreaker()
        cb.record_success("ollama")
        cb.record_success("ollama")
        assert len(received) == 0

    def test_circuit_events_are_best_effort(self):
        """Events fail silently if EventBus is unavailable."""
        from bantz.agent.circuit_breaker import CircuitBreaker

        with patch("bantz.agent.circuit_breaker._get_event_bus_safe", return_value=None):
            cb = CircuitBreaker(failure_threshold=1)
            cb.record_failure("test")  # Should not raise


# ═══════════════════════════════════════════════════════════════
# FALLBACK REGISTRY EVENT TESTS
# ═══════════════════════════════════════════════════════════════

class TestFallbackRegistryEvents:
    """FallbackRegistry should emit FALLBACK_EXECUTED events."""

    def test_fallback_executed_event(self, event_bus, fallback_registry):
        """FALLBACK_EXECUTED emitted on execute_fallback()."""
        received = []
        event_bus.subscribe("system.fallback_executed", lambda e: received.append(e))

        result = fallback_registry.execute_fallback("spotify")
        assert len(received) == 1
        assert received[0].data["service"] == "spotify"
        assert received[0].data["strategy"] == "graceful_error"
        assert received[0].source == "fallback_registry"

    def test_fallback_event_includes_success_status(self, event_bus, fallback_registry):
        """Event data includes success field."""
        received = []
        event_bus.subscribe("system.fallback_executed", lambda e: received.append(e))

        fallback_registry.execute_fallback("spotify")  # graceful_error → success=True
        assert received[0].data["success"] is True

    def test_fallback_event_for_unknown_service(self, event_bus, fallback_registry):
        """Event emitted even for unknown services (success=False)."""
        received = []
        event_bus.subscribe("system.fallback_executed", lambda e: received.append(e))

        fallback_registry.execute_fallback("unknown_service")
        assert len(received) == 1
        assert received[0].data["success"] is False

    def test_fallback_event_for_cache_strategy(self, event_bus, tmp_path):
        """Cache fallback emits event with cache details."""
        from bantz.core.fallback_registry import (
            FallbackRegistry,
            FallbackConfig,
            FallbackStrategy,
        )

        received = []
        event_bus.subscribe("system.fallback_executed", lambda e: received.append(e))

        # Create a cache file
        cache_file = tmp_path / "weather_cache.json"
        cache_file.write_text('{"temp": 22}')

        registry = FallbackRegistry(
            configs={
                "weather": FallbackConfig(
                    service="weather",
                    strategy=FallbackStrategy.CACHE,
                    message="Using cached weather data",
                    max_cache_age_s=3600,
                ),
            },
            cache_dir=tmp_path,
        )
        registry.execute_fallback("weather")
        assert len(received) == 1
        assert received[0].data["strategy"] == "cache_fallback"

    def test_fallback_event_best_effort(self):
        """Events fail silently if EventBus is unavailable."""
        from bantz.core.fallback_registry import FallbackRegistry

        with patch("bantz.core.fallback_registry._get_event_bus_safe", return_value=None):
            registry = FallbackRegistry()
            result = registry.execute_fallback("spotify")
            assert result.success  # Should work fine without event bus


# ═══════════════════════════════════════════════════════════════
# HEALTH MONITOR EVENT TESTS
# ═══════════════════════════════════════════════════════════════

class TestHealthMonitorEvents:
    """HealthMonitor should emit degradation & recovery events."""

    @pytest.mark.asyncio
    async def test_health_degraded_event(self, event_bus):
        """HEALTH_DEGRADED emitted when a service becomes unhealthy."""
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )

        received = []
        event_bus.subscribe("system.health_degraded", lambda e: received.append(e))

        async def check_fail():
            return HealthStatus(service="ollama", status=ServiceStatus.UNHEALTHY, error="connection refused")

        monitor = HealthMonitor(
            checks={"ollama": check_fail},
            event_bus=event_bus,
        )
        await monitor.check_all()

        degraded_events = [e for e in received if e.data.get("service") == "ollama"]
        assert len(degraded_events) == 1
        assert degraded_events[0].data["status"] == "unhealthy"
        assert degraded_events[0].data["error"] == "connection refused"

    @pytest.mark.asyncio
    async def test_health_recovered_event(self, event_bus):
        """HEALTH_RECOVERED emitted when a service comes back healthy."""
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )

        received = []
        event_bus.subscribe("system.health_recovered", lambda e: received.append(e))

        call_count = 0

        async def check_toggle():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return HealthStatus(service="ollama", status=ServiceStatus.UNHEALTHY, error="down")
            return HealthStatus(service="ollama", status=ServiceStatus.HEALTHY, latency_ms=50)

        monitor = HealthMonitor(
            checks={"ollama": check_toggle},
            event_bus=event_bus,
        )

        await monitor.check_all()  # 1st: unhealthy
        assert len(received) == 0  # No recovery yet

        await monitor.check_all()  # 2nd: healthy → recovery!
        assert len(received) == 1
        assert received[0].data["service"] == "ollama"
        assert received[0].data["previous_status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_no_spurious_degradation_events(self, event_bus):
        """No degradation event if service stays unhealthy."""
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )

        received = []
        event_bus.subscribe("system.health_degraded", lambda e: received.append(e))

        async def check_fail():
            return HealthStatus(service="ollama", status=ServiceStatus.UNHEALTHY, error="down")

        monitor = HealthMonitor(
            checks={"ollama": check_fail},
            event_bus=event_bus,
        )

        await monitor.check_all()  # 1st: fires degradation
        await monitor.check_all()  # 2nd: stays unhealthy — no new event

        degraded_events = [e for e in received if e.data.get("service") == "ollama"]
        assert len(degraded_events) == 1

    @pytest.mark.asyncio
    async def test_no_recovery_if_still_healthy(self, event_bus):
        """No recovery event if service stays healthy."""
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )

        received = []
        event_bus.subscribe("system.health_recovered", lambda e: received.append(e))

        async def check_ok():
            return HealthStatus(service="sqlite", status=ServiceStatus.HEALTHY)

        monitor = HealthMonitor(
            checks={"sqlite": check_ok},
            event_bus=event_bus,
        )

        await monitor.check_all()
        await monitor.check_all()
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_health_check_overall_event(self, event_bus):
        """system.health_check emitted with full report when overall ≠ healthy."""
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )

        received = []
        event_bus.subscribe("system.health_check", lambda e: received.append(e))

        async def check_fail():
            return HealthStatus(service="ollama", status=ServiceStatus.UNHEALTHY, error="down")

        monitor = HealthMonitor(
            checks={"ollama": check_fail},
            event_bus=event_bus,
        )
        await monitor.check_all()
        assert len(received) == 1
        assert "services" in received[0].data


# ═══════════════════════════════════════════════════════════════
# HEALTH CLI TESTS
# ═══════════════════════════════════════════════════════════════

class TestHealthCLI:
    """Tests for ``bantz health`` CLI subcommand."""

    def _make_healthy_checks(self):
        """Return mock check functions that report healthy."""
        from bantz.core.health_monitor import HealthStatus, ServiceStatus

        async def ok_sqlite():
            return HealthStatus(service="sqlite", status=ServiceStatus.HEALTHY, latency_ms=2.0)

        async def ok_ollama():
            return HealthStatus(service="ollama", status=ServiceStatus.HEALTHY, latency_ms=50.0)

        async def ok_google():
            return HealthStatus(service="google", status=ServiceStatus.HEALTHY, latency_ms=10.0)

        return {"sqlite": ok_sqlite, "ollama": ok_ollama, "google": ok_google}

    def test_health_cli_text_output(self, capsys):
        """CLI prints a human-readable health report."""
        from bantz.core.health_cli import main

        with patch.dict("bantz.core.health_monitor.HealthMonitor.DEFAULT_CHECKS", self._make_healthy_checks(), clear=True):
            exit_code = main([])

        captured = capsys.readouterr()
        assert "Health Report" in captured.out
        assert exit_code == 0

    def test_health_cli_json_output(self, capsys):
        """--json flag produces valid JSON output."""
        from bantz.core.health_cli import main

        with patch.dict("bantz.core.health_monitor.HealthMonitor.DEFAULT_CHECKS", self._make_healthy_checks(), clear=True):
            exit_code = main(["--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "overall" in data
        assert "services" in data
        assert exit_code == 0

    def test_health_cli_single_service(self, capsys):
        """--service checks only one service."""
        from bantz.core.health_cli import main

        with patch.dict("bantz.core.health_monitor.HealthMonitor.DEFAULT_CHECKS", self._make_healthy_checks(), clear=True):
            exit_code = main(["--service", "sqlite"])

        captured = capsys.readouterr()
        assert "sqlite" in captured.out
        assert exit_code == 0

    def test_health_cli_exit_code_unhealthy(self, capsys):
        """Exit code 1 when a service is unhealthy."""
        from bantz.core.health_cli import main
        from bantz.core.health_monitor import HealthStatus, ServiceStatus

        async def fail_ollama():
            return HealthStatus(service="ollama", status=ServiceStatus.UNHEALTHY, error="down")

        checks = self._make_healthy_checks()
        checks["ollama"] = fail_ollama

        with patch.dict("bantz.core.health_monitor.HealthMonitor.DEFAULT_CHECKS", checks, clear=True):
            exit_code = main([])

        assert exit_code == 1

    def test_health_cli_with_cb_flag(self, capsys):
        """--cb flag includes circuit breaker section."""
        from bantz.core.health_cli import main

        with patch.dict("bantz.core.health_monitor.HealthMonitor.DEFAULT_CHECKS", self._make_healthy_checks(), clear=True):
            exit_code = main(["--cb"])

        captured = capsys.readouterr()
        assert "Circuit Breaker" in captured.out

    def test_health_cli_with_fallback_flag(self, capsys):
        """--fallback flag includes fallback registry section."""
        from bantz.core.health_cli import main

        with patch.dict("bantz.core.health_monitor.HealthMonitor.DEFAULT_CHECKS", self._make_healthy_checks(), clear=True):
            exit_code = main(["--fallback"])

        captured = capsys.readouterr()
        assert "Fallback Registry" in captured.out


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestGracefulDegradationIntegration:
    """End-to-end: CB → HealthMonitor → Fallback event flow."""

    @pytest.mark.asyncio
    async def test_full_degradation_flow(self, event_bus):
        """Simulate: service fails → CB opens → health degrades → fallback fires."""
        from bantz.agent.circuit_breaker import CircuitBreaker
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )
        from bantz.core.fallback_registry import FallbackRegistry

        events_log: list[str] = []
        event_bus.subscribe("system.circuit_opened", lambda e: events_log.append(f"cb_open:{e.data['domain']}"))
        event_bus.subscribe("system.health_degraded", lambda e: events_log.append(f"degraded:{e.data['service']}"))
        event_bus.subscribe("system.fallback_executed", lambda e: events_log.append(f"fallback:{e.data['service']}"))

        # 1. CB detects failures
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("ollama")
        cb.record_failure("ollama")  # → OPEN, event

        # 2. Health monitor detects unhealthy
        async def check_fail():
            return HealthStatus(service="ollama", status=ServiceStatus.UNHEALTHY, error="unreachable")

        monitor = HealthMonitor(checks={"ollama": check_fail}, event_bus=event_bus)
        await monitor.check_all()

        # 3. Fallback executes
        registry = FallbackRegistry()
        registry.execute_fallback("ollama")

        assert "cb_open:ollama" in events_log
        assert "degraded:ollama" in events_log
        assert "fallback:ollama" in events_log

    @pytest.mark.asyncio
    async def test_full_recovery_flow(self, event_bus):
        """Simulate: service recovers → CB closes → health recovered."""
        from bantz.agent.circuit_breaker import CircuitBreaker
        from bantz.core.health_monitor import (
            HealthMonitor,
            HealthStatus,
            ServiceStatus,
        )
        import time

        events_log: list[str] = []
        event_bus.subscribe("system.circuit_closed", lambda e: events_log.append(f"cb_close:{e.data['domain']}"))
        event_bus.subscribe("system.health_recovered", lambda e: events_log.append(f"recovered:{e.data['service']}"))

        # 1. Open the circuit
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0)
        cb.record_failure("google")
        cb.record_failure("google")  # → OPEN
        time.sleep(0.01)
        cb.is_open("google")  # → HALF_OPEN
        cb.record_success("google")  # → CLOSED, event

        # 2. Health monitor: unhealthy → healthy
        call_count = 0

        async def check_toggle():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return HealthStatus(service="google", status=ServiceStatus.UNHEALTHY, error="down")
            return HealthStatus(service="google", status=ServiceStatus.HEALTHY, latency_ms=30)

        monitor = HealthMonitor(checks={"google": check_toggle}, event_bus=event_bus)
        await monitor.check_all()  # unhealthy
        await monitor.check_all()  # healthy → recovery

        assert "cb_close:google" in events_log
        assert "recovered:google" in events_log

    def test_cli_dispatches_to_health(self):
        """``bantz health`` in CLI argv routes to health subcommand."""
        from bantz.cli import main

        with patch("bantz.core.health_cli.main", return_value=0) as mock_health:
            result = main(["health"])
            mock_health.assert_called_once_with([])

    def test_cli_dispatches_health_with_args(self):
        """``bantz health --json`` passes args through."""
        from bantz.cli import main

        with patch("bantz.core.health_cli.main", return_value=0) as mock_health:
            main(["health", "--json"])
            mock_health.assert_called_once_with(["--json"])
