"""Tests for Issue #1298 — Graceful Degradation.

Covers:
- HealthMonitor: check functions, aggregation, periodic loop
- FallbackRegistry: config, strategy dispatch, custom handlers
- CircuitBreaker enhancements: async call(), to_dict(), CircuitOpenError
- EventType additions for health events
- Integration: monitor → circuit breaker → fallback chain
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bantz.agent.circuit_breaker import (CircuitBreaker, CircuitOpenError,
                                         CircuitState)
from bantz.core.events import EventType
from bantz.core.fallback_registry import (FallbackConfig, FallbackRegistry,
                                          FallbackResult, FallbackStrategy,
                                          get_fallback_registry,
                                          reset_fallback_registry)
from bantz.core.health_monitor import (HealthMonitor, HealthReport,
                                       HealthStatus, ServiceStatus,
                                       get_health_monitor,
                                       reset_health_monitor)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singletons before each test."""
    reset_health_monitor()
    reset_fallback_registry()
    yield
    reset_health_monitor()
    reset_fallback_registry()


# ── ServiceStatus ────────────────────────────────────────────────────


class TestServiceStatus:
    def test_values(self):
        assert ServiceStatus.HEALTHY == "healthy"
        assert ServiceStatus.DEGRADED == "degraded"
        assert ServiceStatus.UNHEALTHY == "unhealthy"


# ── HealthStatus ─────────────────────────────────────────────────────


class TestHealthStatus:
    def test_to_dict_healthy(self):
        hs = HealthStatus(
            service="sqlite",
            status=ServiceStatus.HEALTHY,
            latency_ms=12.345,
        )
        d = hs.to_dict()
        assert d["service"] == "sqlite"
        assert d["status"] == "healthy"
        assert d["latency_ms"] == 12.3
        assert "error" not in d

    def test_to_dict_with_error(self):
        hs = HealthStatus(
            service="ollama",
            status=ServiceStatus.UNHEALTHY,
            latency_ms=5000.0,
            error="Connection refused",
        )
        d = hs.to_dict()
        assert d["error"] == "Connection refused"

    def test_to_dict_with_details(self):
        hs = HealthStatus(
            service="ollama",
            status=ServiceStatus.HEALTHY,
            details={"models": ["qwen2.5"]},
        )
        d = hs.to_dict()
        assert "models" in d["details"]


# ── HealthReport ─────────────────────────────────────────────────────


class TestHealthReport:
    def test_overall_healthy(self):
        checks = {
            "a": HealthStatus(service="a", status=ServiceStatus.HEALTHY),
            "b": HealthStatus(service="b", status=ServiceStatus.HEALTHY),
        }
        report = HealthReport(checks=checks, overall=ServiceStatus.HEALTHY)
        assert report.healthy_services == ["a", "b"]
        assert report.unhealthy_services == []
        assert report.degraded_services == []

    def test_overall_mixed(self):
        checks = {
            "a": HealthStatus(service="a", status=ServiceStatus.HEALTHY),
            "b": HealthStatus(service="b", status=ServiceStatus.DEGRADED),
            "c": HealthStatus(service="c", status=ServiceStatus.UNHEALTHY),
        }
        report = HealthReport(checks=checks, overall=ServiceStatus.UNHEALTHY)
        assert report.healthy_services == ["a"]
        assert report.degraded_services == ["b"]
        assert report.unhealthy_services == ["c"]

    def test_to_dict(self):
        checks = {
            "x": HealthStatus(service="x", status=ServiceStatus.HEALTHY, latency_ms=5.0),
        }
        report = HealthReport(checks=checks, overall=ServiceStatus.HEALTHY)
        d = report.to_dict()
        assert d["overall"] == "healthy"
        assert "x" in d["services"]
        assert "timestamp" in d


# ── HealthMonitor ────────────────────────────────────────────────────


class TestHealthMonitor:
    @pytest.mark.asyncio
    async def test_custom_check_healthy(self):
        async def always_healthy():
            return HealthStatus(
                service="test_svc",
                status=ServiceStatus.HEALTHY,
                latency_ms=1.0,
            )

        monitor = HealthMonitor(checks={"test_svc": always_healthy})
        status = await monitor.check_service("test_svc")
        assert status.status == ServiceStatus.HEALTHY
        assert status.service == "test_svc"

    @pytest.mark.asyncio
    async def test_custom_check_unhealthy(self):
        async def always_fail():
            return HealthStatus(
                service="bad",
                status=ServiceStatus.UNHEALTHY,
                error="down",
            )

        monitor = HealthMonitor(checks={"bad": always_fail})
        status = await monitor.check_service("bad")
        assert status.status == ServiceStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_unknown_service(self):
        monitor = HealthMonitor(checks={})
        status = await monitor.check_service("nope")
        assert status.status == ServiceStatus.UNHEALTHY
        assert "Bilinmeyen" in status.error

    @pytest.mark.asyncio
    async def test_check_all_aggregation(self):
        async def healthy():
            return HealthStatus(service="a", status=ServiceStatus.HEALTHY)

        async def degraded():
            return HealthStatus(service="b", status=ServiceStatus.DEGRADED)

        monitor = HealthMonitor(checks={"a": healthy, "b": degraded})
        report = await monitor.check_all()
        assert report.overall == ServiceStatus.DEGRADED
        assert len(report.checks) == 2

    @pytest.mark.asyncio
    async def test_check_all_all_healthy(self):
        async def healthy():
            return HealthStatus(service="x", status=ServiceStatus.HEALTHY)

        monitor = HealthMonitor(checks={"x": healthy, "y": healthy})
        report = await monitor.check_all()
        assert report.overall == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_all_unhealthy_wins(self):
        async def healthy():
            return HealthStatus(service="a", status=ServiceStatus.HEALTHY)

        async def bad():
            return HealthStatus(service="b", status=ServiceStatus.UNHEALTHY)

        monitor = HealthMonitor(checks={"a": healthy, "b": bad})
        report = await monitor.check_all()
        assert report.overall == ServiceStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_exception_in_check_fn(self):
        async def boom():
            raise RuntimeError("kaboom")

        monitor = HealthMonitor(checks={"boom": boom})
        status = await monitor.check_service("boom")
        assert status.status == ServiceStatus.UNHEALTHY
        assert "kaboom" in status.error

    @pytest.mark.asyncio
    async def test_last_report(self):
        async def ok():
            return HealthStatus(service="s", status=ServiceStatus.HEALTHY)

        monitor = HealthMonitor(checks={"s": ok})
        assert monitor.last_report is None
        await monitor.check_all()
        assert monitor.last_report is not None
        assert monitor.last_report.overall == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_event_bus_publish_on_degraded(self):
        async def bad():
            return HealthStatus(service="x", status=ServiceStatus.UNHEALTHY)

        bus = MagicMock()
        monitor = HealthMonitor(checks={"x": bad}, event_bus=bus)
        await monitor.check_all()
        bus.publish.assert_called_once()
        call_kwargs = bus.publish.call_args
        assert call_kwargs[1]["event_type"] == "system.health_degraded"

    @pytest.mark.asyncio
    async def test_no_event_when_healthy(self):
        async def ok():
            return HealthStatus(service="s", status=ServiceStatus.HEALTHY)

        bus = MagicMock()
        monitor = HealthMonitor(checks={"s": ok}, event_bus=bus)
        await monitor.check_all()
        bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        async def bad():
            return HealthStatus(service="x", status=ServiceStatus.UNHEALTHY)

        async def ok():
            return HealthStatus(service="y", status=ServiceStatus.HEALTHY)

        cb = MagicMock()
        monitor = HealthMonitor(checks={"x": bad, "y": ok}, circuit_breaker=cb)
        await monitor.check_all()
        cb.record_failure.assert_called_once_with("x")
        cb.record_success.assert_called_once_with("y")

    def test_register_unregister_check(self):
        monitor = HealthMonitor(checks={})
        assert "new" not in monitor._checks

        async def new_check():
            return HealthStatus(service="new", status=ServiceStatus.HEALTHY)

        monitor.register_check("new", new_check)
        assert "new" in monitor._checks

        monitor.unregister_check("new")
        assert "new" not in monitor._checks

    @pytest.mark.asyncio
    async def test_periodic_check_stop(self):
        call_count = 0

        async def counting():
            nonlocal call_count
            call_count += 1
            return HealthStatus(service="s", status=ServiceStatus.HEALTHY)

        monitor = HealthMonitor(checks={"s": counting}, check_interval=0)

        async def run_then_stop():
            task = asyncio.create_task(monitor.periodic_check())
            await asyncio.sleep(0.1)
            monitor.stop()
            await task

        await run_then_stop()
        assert call_count >= 1

    def test_format_report(self):
        checks = {
            "sqlite": HealthStatus(
                service="sqlite", status=ServiceStatus.HEALTHY, latency_ms=5.0
            ),
            "ollama": HealthStatus(
                service="ollama",
                status=ServiceStatus.UNHEALTHY,
                latency_ms=0,
                error="refused",
            ),
        }
        report = HealthReport(checks=checks, overall=ServiceStatus.UNHEALTHY)
        monitor = HealthMonitor(checks={})
        text = monitor.format_report(report)
        assert "UNHEALTHY" in text
        assert "ollama" in text
        assert "sqlite" in text

    def test_format_report_none(self):
        monitor = HealthMonitor(checks={})
        text = monitor.format_report()
        assert "henüz" in text

    def test_singleton(self):
        m1 = get_health_monitor()
        m2 = get_health_monitor()
        assert m1 is m2

    def test_compute_overall_empty(self):
        assert HealthMonitor._compute_overall({}) == ServiceStatus.HEALTHY


# ─── Fallback Registry ──────────────────────────────────────────────



class TestFallbackStrategy:
    def test_values(self):
        assert FallbackStrategy.CACHE == "cache_fallback"
        assert FallbackStrategy.SQLITE == "sqlite_fallback"
        assert FallbackStrategy.MODEL_DOWNGRADE == "model_downgrade"
        assert FallbackStrategy.GRACEFUL_ERROR == "graceful_error"
        assert FallbackStrategy.NONE == "none"


class TestFallbackConfig:
    def test_to_dict(self):
        cfg = FallbackConfig(
            service="ollama",
            strategy=FallbackStrategy.MODEL_DOWNGRADE,
            message_tr="Model değiştirildi",
            fallback_model="qwen2.5-coder:3b",
        )
        d = cfg.to_dict()
        assert d["service"] == "ollama"
        assert d["strategy"] == "model_downgrade"
        assert d["fallback_model"] == "qwen2.5-coder:3b"

    def test_to_dict_no_optionals(self):
        cfg = FallbackConfig(
            service="x",
            strategy=FallbackStrategy.NONE,
            message_tr="Yok",
        )
        d = cfg.to_dict()
        assert "max_cache_age_s" not in d
        assert "fallback_model" not in d


class TestFallbackResult:
    def test_to_dict(self):
        result = FallbackResult(
            service="google",
            strategy=FallbackStrategy.CACHE,
            success=True,
            message="Cached",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["strategy"] == "cache_fallback"


class TestFallbackRegistry:
    def test_default_configs(self):
        registry = FallbackRegistry()
        services = registry.list_services()
        assert "ollama" in services
        assert "google" in services
        assert "neo4j" in services
        assert "weather" in services

    def test_register_unregister(self):
        registry = FallbackRegistry(configs={})
        cfg = FallbackConfig(
            service="test_svc",
            strategy=FallbackStrategy.GRACEFUL_ERROR,
            message_tr="Test error",
        )
        registry.register(cfg)
        assert registry.get_config("test_svc") is not None

        registry.unregister("test_svc")
        assert registry.get_config("test_svc") is None

    def test_model_downgrade(self):
        registry = FallbackRegistry(configs={
            "ollama": FallbackConfig(
                service="ollama",
                strategy=FallbackStrategy.MODEL_DOWNGRADE,
                message_tr="Downgrade",
                fallback_model="qwen2.5-coder:3b",
            ),
        })
        result = registry.execute_fallback("ollama")
        assert result.success is True
        assert result.data == {"model": "qwen2.5-coder:3b"}

    def test_model_downgrade_no_model(self):
        registry = FallbackRegistry(configs={
            "ollama": FallbackConfig(
                service="ollama",
                strategy=FallbackStrategy.MODEL_DOWNGRADE,
                message_tr="No model",
                fallback_model="",
            ),
        })
        result = registry.execute_fallback("ollama")
        assert result.success is False

    def test_graceful_error(self):
        registry = FallbackRegistry(configs={
            "spotify": FallbackConfig(
                service="spotify",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="Spotify çalışmıyor",
            ),
        })
        result = registry.execute_fallback("spotify")
        assert result.success is True
        assert "Spotify" in result.message

    def test_unknown_service(self):
        registry = FallbackRegistry(configs={})
        result = registry.execute_fallback("unknown")
        assert result.success is False
        assert result.strategy == FallbackStrategy.NONE

    def test_cache_fallback_no_file(self, tmp_path):
        registry = FallbackRegistry(
            configs={
                "google": FallbackConfig(
                    service="google",
                    strategy=FallbackStrategy.CACHE,
                    message_tr="Cache",
                    max_cache_age_s=3600,
                ),
            },
            cache_dir=tmp_path,
        )
        result = registry.execute_fallback("google")
        assert result.success is False
        assert "bulunamadı" in result.message

    def test_cache_fallback_valid(self, tmp_path):
        cache_file = tmp_path / "google_cache.json"
        cache_file.write_text(json.dumps({"events": []}))

        registry = FallbackRegistry(
            configs={
                "google": FallbackConfig(
                    service="google",
                    strategy=FallbackStrategy.CACHE,
                    message_tr="Cache",
                    max_cache_age_s=3600,
                ),
            },
            cache_dir=tmp_path,
        )
        result = registry.execute_fallback("google")
        assert result.success is True
        assert result.data == {"events": []}

    def test_cache_fallback_too_old(self, tmp_path):
        cache_file = tmp_path / "google_cache.json"
        cache_file.write_text(json.dumps({"events": []}))
        # Set modification time to 2 hours ago
        import os

        old_time = time.time() - 7200
        os.utime(cache_file, (old_time, old_time))

        registry = FallbackRegistry(
            configs={
                "google": FallbackConfig(
                    service="google",
                    strategy=FallbackStrategy.CACHE,
                    message_tr="Cache",
                    max_cache_age_s=60,  # 1 minute max age
                ),
            },
            cache_dir=tmp_path,
        )
        result = registry.execute_fallback("google")
        assert result.success is False
        assert "eski" in result.message

    def test_none_strategy(self):
        registry = FallbackRegistry(configs={
            "x": FallbackConfig(
                service="x",
                strategy=FallbackStrategy.NONE,
                message_tr="Nothing",
            ),
        })
        result = registry.execute_fallback("x")
        assert result.success is False

    def test_custom_fallback_fn(self):
        def custom_fn(service):
            return {"custom": True, "service": service}

        registry = FallbackRegistry(configs={
            "custom": FallbackConfig(
                service="custom",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="Custom",
                fallback_fn=custom_fn,
            ),
        })
        result = registry.execute_fallback("custom")
        assert result.success is True
        assert result.data["custom"] is True

    def test_custom_fallback_fn_failure(self):
        def bad_fn(service):
            raise ValueError("custom fail")

        registry = FallbackRegistry(configs={
            "bad": FallbackConfig(
                service="bad",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="Bad",
                fallback_fn=bad_fn,
            ),
        })
        result = registry.execute_fallback("bad")
        assert result.success is False
        assert "custom fail" in result.message

    def test_history(self):
        registry = FallbackRegistry(configs={
            "x": FallbackConfig(
                service="x",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="Test",
            ),
        })
        registry.execute_fallback("x")
        registry.execute_fallback("x")
        assert len(registry.history) == 2
        registry.clear_history()
        assert len(registry.history) == 0

    def test_to_dict(self):
        registry = FallbackRegistry()
        d = registry.to_dict()
        assert "ollama" in d
        assert d["ollama"]["strategy"] == "model_downgrade"

    def test_singleton(self):
        r1 = get_fallback_registry()
        r2 = get_fallback_registry()
        assert r1 is r2


# ─── Circuit Breaker Enhancements ────────────────────────────────────


class TestCircuitBreakerCall:
    @pytest.mark.asyncio
    async def test_call_sync_success(self):
        cb = CircuitBreaker()

        def add(a, b):
            return a + b

        result = await cb.call("test", add, 1, 2)
        assert result == 3
        assert cb.get_state("test") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_async_success(self):
        cb = CircuitBreaker()

        async def async_add(a, b):
            return a + b

        result = await cb.call("test", async_add, 3, 4)
        assert result == 7

    @pytest.mark.asyncio
    async def test_call_failure_records(self):
        cb = CircuitBreaker(failure_threshold=2)

        def fail():
            raise ValueError("oops")

        with pytest.raises(ValueError):
            await cb.call("test", fail)

        stats = cb.get_stats("test")
        assert stats.failures == 1

    @pytest.mark.asyncio
    async def test_call_open_circuit_no_fallback(self):
        cb = CircuitBreaker(failure_threshold=1)

        def fail():
            raise ValueError("oops")

        with pytest.raises(ValueError):
            await cb.call("test", fail)

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call("test", fail)

        assert exc_info.value.domain == "test"

    @pytest.mark.asyncio
    async def test_call_open_circuit_with_fallback(self):
        cb = CircuitBreaker(failure_threshold=1)

        def fail():
            raise ValueError("oops")

        def fallback():
            return "fallback_value"

        with pytest.raises(ValueError):
            await cb.call("test", fail)

        result = await cb.call("test", fail, fallback=fallback)
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_call_open_circuit_with_async_fallback(self):
        cb = CircuitBreaker(failure_threshold=1)

        def fail():
            raise ValueError("oops")

        async def async_fallback():
            return "async_fb"

        with pytest.raises(ValueError):
            await cb.call("test", fail)

        result = await cb.call("test", fail, fallback=async_fallback)
        assert result == "async_fb"

    @pytest.mark.asyncio
    async def test_call_failure_triggers_fallback(self):
        """When fn fails AND circuit opens, fallback runs."""
        cb = CircuitBreaker(failure_threshold=2)

        call_count = 0

        def fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        def fb():
            return "recovered"

        # First failure — circuit still closed
        with pytest.raises(ValueError):
            await cb.call("svc", fail)

        # Second failure — threshold reached, circuit opens, fallback runs
        result = await cb.call("svc", fail, fallback=fb)
        assert result == "recovered"
        assert call_count == 2


class TestCircuitBreakerToDict:
    def test_empty(self):
        cb = CircuitBreaker()
        assert cb.to_dict() == {}

    def test_with_domains(self):
        cb = CircuitBreaker()
        cb.record_failure("google")
        cb.record_success("ollama")

        d = cb.to_dict()
        assert "google" in d
        assert "ollama" in d
        assert d["google"]["state"] == "closed"
        assert d["google"]["failures"] == 1


class TestCircuitOpenError:
    def test_message(self):
        err = CircuitOpenError("google")
        assert err.domain == "google"
        assert "google" in str(err)


# ─── EventType Health Additions ──────────────────────────────────────


class TestHealthEventTypes:
    def test_health_check(self):
        assert EventType.HEALTH_CHECK.value == "system.health_check"

    def test_health_degraded(self):
        assert EventType.HEALTH_DEGRADED.value == "system.health_degraded"

    def test_health_recovered(self):
        assert EventType.HEALTH_RECOVERED.value == "system.health_recovered"

    def test_circuit_opened(self):
        assert EventType.CIRCUIT_OPENED.value == "system.circuit_opened"

    def test_circuit_closed(self):
        assert EventType.CIRCUIT_CLOSED.value == "system.circuit_closed"

    def test_fallback_executed(self):
        assert EventType.FALLBACK_EXECUTED.value == "system.fallback_executed"


# ─── Integration: Monitor → CB → Fallback ───────────────────────────


class TestIntegration:
    @pytest.mark.asyncio
    async def test_monitor_opens_circuit_then_fallback(self):
        """End-to-end: unhealthy check → CB open → fallback executed."""
        cb = CircuitBreaker(failure_threshold=1)

        async def unhealthy():
            return HealthStatus(service="svc", status=ServiceStatus.UNHEALTHY)

        monitor = HealthMonitor(
            checks={"svc": unhealthy},
            circuit_breaker=cb,
        )
        # Run health check — records failure in CB
        await monitor.check_all()
        # After threshold=1, circuit should be open
        assert cb.is_open("svc")

        # Now fallback should kick in
        registry = FallbackRegistry(configs={
            "svc": FallbackConfig(
                service="svc",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="Servis çalışmıyor",
            ),
        })
        result = registry.execute_fallback("svc")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_monitor_event_bus_circuit_breaker_chain(self):
        """Monitor publishes degraded event with bus, updates CB."""
        cb = CircuitBreaker(failure_threshold=2)
        bus = MagicMock()

        async def degraded():
            return HealthStatus(service="api", status=ServiceStatus.DEGRADED)

        monitor = HealthMonitor(
            checks={"api": degraded},
            event_bus=bus,
            circuit_breaker=cb,
        )
        await monitor.check_all()

        # Degraded publishes event
        bus.publish.assert_called_once()
        # Degraded does NOT record failure in CB (only UNHEALTHY does)
        assert cb.get_stats("api").failures == 0

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Service goes down → fallback → recovery → normal."""
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1)

        # Phase 1: Service unhealthy
        async def down():
            return HealthStatus(service="db", status=ServiceStatus.UNHEALTHY)

        monitor = HealthMonitor(checks={"db": down}, circuit_breaker=cb)
        await monitor.check_all()
        assert cb.is_open("db")

        # Phase 2: Fallback
        registry = FallbackRegistry(configs={
            "db": FallbackConfig(
                service="db",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="DB çöktü",
            ),
        })
        fb = registry.execute_fallback("db")
        assert fb.success

        # Phase 3: Wait for reset_timeout, then recovery
        import time
        time.sleep(0.15)
        # The is_open check will transition to half_open
        assert not cb.is_open("db")  # transitions OPEN → HALF_OPEN

        async def up():
            return HealthStatus(service="db", status=ServiceStatus.HEALTHY)

        monitor._checks["db"] = up
        await monitor.check_all()

        # CB should be closed now (success in half_open)
        assert cb.get_state("db") == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_cb_call_with_health_aware_fallback(self):
        """CircuitBreaker.call() with a fallback from the registry."""
        cb = CircuitBreaker(failure_threshold=1)
        registry = FallbackRegistry(configs={
            "api": FallbackConfig(
                service="api",
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                message_tr="API çöktü",
            ),
        })

        def api_call():
            raise ConnectionError("refused")

        def api_fallback():
            return registry.execute_fallback("api")

        # First call fails, opens circuit
        with pytest.raises(ConnectionError):
            await cb.call("api", api_call)

        # Second call uses fallback
        result = await cb.call("api", api_call, fallback=api_fallback)
        assert isinstance(result, FallbackResult)
        assert result.success is True


# ─── SQLite Fallback ─────────────────────────────────────────────────


class TestSqliteFallback:
    def test_sqlite_fallback_no_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from bantz.core.fallback_registry import _sqlite_fallback

        result = _sqlite_fallback("neo4j")
        assert result.success is False

    def test_sqlite_fallback_with_db(self, tmp_path, monkeypatch):
        db_dir = tmp_path / ".bantz"
        db_dir.mkdir()
        import sqlite3

        conn = sqlite3.connect(str(db_dir / "bantz.db"))
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER)")
        conn.close()

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from bantz.core.fallback_registry import _sqlite_fallback

        result = _sqlite_fallback("neo4j")
        assert result.success is True
        assert "SQLite" in result.message
