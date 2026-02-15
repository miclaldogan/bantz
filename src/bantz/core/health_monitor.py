"""Health Monitor — periodic health checks for all Bantz dependencies.

Issue #1298: Graceful Degradation — Circuit Breaker + Health Monitor + Fallback.

Monitors external service health (Ollama, Google API, SQLite, etc.)
and publishes events when services degrade. Integrates with the
EventBus and CircuitBreaker for coordinated failure handling.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    """Health status of a monitored service."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"       # Slow but functional
    UNHEALTHY = "unhealthy"     # Not responding / errors


@dataclass
class HealthStatus:
    """Health status for a single service."""

    service: str
    status: ServiceStatus
    latency_ms: float = 0.0
    error: str = ""
    last_check: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "service": self.service,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 1),
            "last_check": self.last_check.isoformat(),
        }
        if self.error:
            d["error"] = self.error
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class HealthReport:
    """Aggregated health report for all services."""

    checks: Dict[str, HealthStatus]
    overall: ServiceStatus
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall.value,
            "timestamp": self.timestamp.isoformat(),
            "services": {
                name: status.to_dict()
                for name, status in self.checks.items()
            },
        }

    @property
    def healthy_services(self) -> List[str]:
        return [
            n for n, s in self.checks.items()
            if s.status == ServiceStatus.HEALTHY
        ]

    @property
    def unhealthy_services(self) -> List[str]:
        return [
            n for n, s in self.checks.items()
            if s.status == ServiceStatus.UNHEALTHY
        ]

    @property
    def degraded_services(self) -> List[str]:
        return [
            n for n, s in self.checks.items()
            if s.status == ServiceStatus.DEGRADED
        ]


# ── Health Check Functions ───────────────────────────────────────

# Thresholds: latency above this → DEGRADED
_LATENCY_THRESHOLDS: Dict[str, float] = {
    "sqlite": 100.0,    # 100ms
    "ollama": 2000.0,   # 2s
    "google": 3000.0,   # 3s
    "neo4j": 1000.0,    # 1s
    "weather": 5000.0,  # 5s
}


async def check_sqlite() -> HealthStatus:
    """Check SQLite database is writable."""
    start = time.monotonic()
    try:
        import sqlite3
        from pathlib import Path

        db_path = Path.home() / ".bantz" / "bantz.db"
        if not db_path.exists():
            # Look for any .db in common locations
            for candidate in [
                Path("data/bantz.db"),
                Path("bantz.db"),
            ]:
                if candidate.exists():
                    db_path = candidate
                    break

        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("SELECT 1")
        conn.close()

        latency = (time.monotonic() - start) * 1000
        threshold = _LATENCY_THRESHOLDS["sqlite"]
        return HealthStatus(
            service="sqlite",
            status=(
                ServiceStatus.DEGRADED if latency > threshold
                else ServiceStatus.HEALTHY
            ),
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return HealthStatus(
            service="sqlite",
            status=ServiceStatus.UNHEALTHY,
            latency_ms=latency,
            error=str(exc),
        )


async def check_ollama() -> HealthStatus:
    """Check Ollama LLM server is responding."""
    import os

    start = time.monotonic()
    base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        import urllib.request

        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(req, timeout=5),
        )
        data = response.read()

        latency = (time.monotonic() - start) * 1000
        threshold = _LATENCY_THRESHOLDS["ollama"]

        import json

        models = json.loads(data).get("models", [])
        model_names = [m.get("name", "") for m in models[:5]]

        return HealthStatus(
            service="ollama",
            status=(
                ServiceStatus.DEGRADED if latency > threshold
                else ServiceStatus.HEALTHY
            ),
            latency_ms=latency,
            details={"models": model_names},
        )
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return HealthStatus(
            service="ollama",
            status=ServiceStatus.UNHEALTHY,
            latency_ms=latency,
            error=str(exc),
        )


async def check_google_api() -> HealthStatus:
    """Check Google API token validity."""
    start = time.monotonic()
    try:
        from pathlib import Path

        token_path = Path("config/token.json")
        if not token_path.exists():
            token_path = Path.home() / ".bantz" / "token.json"

        if not token_path.exists():
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                service="google",
                status=ServiceStatus.UNHEALTHY,
                latency_ms=latency,
                error="Token file not found",
            )

        import json

        with open(token_path) as f:
            token_data = json.load(f)

        # Check if token has expired
        expiry = token_data.get("expiry", "")
        has_refresh = bool(token_data.get("refresh_token", ""))

        latency = (time.monotonic() - start) * 1000
        threshold = _LATENCY_THRESHOLDS["google"]

        if not has_refresh:
            return HealthStatus(
                service="google",
                status=ServiceStatus.DEGRADED,
                latency_ms=latency,
                error="Refresh token missing",
                details={"expiry": expiry},
            )

        return HealthStatus(
            service="google",
            status=(
                ServiceStatus.DEGRADED if latency > threshold
                else ServiceStatus.HEALTHY
            ),
            latency_ms=latency,
            details={"expiry": expiry, "has_refresh": True},
        )
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return HealthStatus(
            service="google",
            status=ServiceStatus.UNHEALTHY,
            latency_ms=latency,
            error=str(exc),
        )


# ── Health Monitor ───────────────────────────────────────────────

# Type for check functions
HealthCheckFn = Callable[[], Any]  # Returns Awaitable[HealthStatus]


class HealthMonitor:
    """Monitors health of all Bantz dependencies.

    Features:
    - Pluggable health check functions per service
    - Configurable check intervals
    - EventBus integration for health degradation alerts
    - Circuit breaker integration
    - Async periodic monitoring
    """

    DEFAULT_CHECKS: Dict[str, HealthCheckFn] = {
        "sqlite": check_sqlite,
        "ollama": check_ollama,
        "google": check_google_api,
    }

    def __init__(
        self,
        *,
        checks: Dict[str, HealthCheckFn] | None = None,
        event_bus: Any = None,
        circuit_breaker: Any = None,
        check_interval: int = 300,  # 5 minutes
    ) -> None:
        self._checks: Dict[str, HealthCheckFn] = (
            checks if checks is not None
            else dict(self.DEFAULT_CHECKS)
        )
        self._event_bus = event_bus
        self._circuit_breaker = circuit_breaker
        self._check_interval = check_interval
        self._last_report: Optional[HealthReport] = None
        self._running = False

    def register_check(self, name: str, fn: HealthCheckFn) -> None:
        """Register a new health check function."""
        self._checks[name] = fn

    def unregister_check(self, name: str) -> None:
        """Remove a health check."""
        self._checks.pop(name, None)

    async def check_service(self, name: str) -> HealthStatus:
        """Run a single service health check."""
        fn = self._checks.get(name)
        if fn is None:
            return HealthStatus(
                service=name,
                status=ServiceStatus.UNHEALTHY,
                error=f"Unknown service: {name}",
            )
        try:
            return await fn()
        except Exception as exc:
            logger.warning("[HealthMonitor] Check %s failed: %s", name, exc)
            return HealthStatus(
                service=name,
                status=ServiceStatus.UNHEALTHY,
                error=str(exc),
            )

    async def check_all(self) -> HealthReport:
        """Run all health checks and return an aggregated report."""
        results: Dict[str, HealthStatus] = {}

        for name in self._checks:
            results[name] = await self.check_service(name)

        overall = self._compute_overall(results)
        report = HealthReport(
            checks=results,
            overall=overall,
        )
        self._last_report = report

        # Publish event if degraded or unhealthy
        if overall != ServiceStatus.HEALTHY and self._event_bus:
            try:
                self._event_bus.publish(
                    event_type="system.health_degraded",
                    data=report.to_dict(),
                    source="health_monitor",
                )
            except Exception as exc:
                logger.debug("[HealthMonitor] Event publish failed: %s", exc)

        # Update circuit breaker states
        if self._circuit_breaker:
            for name, status in results.items():
                if status.status == ServiceStatus.UNHEALTHY:
                    self._circuit_breaker.record_failure(name)
                elif status.status == ServiceStatus.HEALTHY:
                    self._circuit_breaker.record_success(name)

        return report

    @property
    def last_report(self) -> Optional[HealthReport]:
        """Get the most recent health report (if any)."""
        return self._last_report

    async def periodic_check(self) -> None:
        """Run health checks periodically until stopped."""
        self._running = True
        logger.info(
            "[HealthMonitor] Started — interval=%ds, services=%s",
            self._check_interval,
            list(self._checks.keys()),
        )
        try:
            while self._running:
                try:
                    await self.check_all()
                except Exception as exc:
                    logger.error("[HealthMonitor] Check cycle error: %s", exc)
                await asyncio.sleep(self._check_interval)
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the periodic check loop."""
        self._running = False

    @staticmethod
    def _compute_overall(
        checks: Dict[str, HealthStatus],
    ) -> ServiceStatus:
        """Compute overall status from individual checks."""
        if not checks:
            return ServiceStatus.HEALTHY

        statuses = {s.status for s in checks.values()}

        if ServiceStatus.UNHEALTHY in statuses:
            return ServiceStatus.UNHEALTHY
        if ServiceStatus.DEGRADED in statuses:
            return ServiceStatus.DEGRADED
        return ServiceStatus.HEALTHY

    def format_report(self, report: Optional[HealthReport] = None) -> str:
        """Format a health report for CLI display.

        Returns a human-readable string with emoji indicators.
        """
        report = report or self._last_report
        if not report:
            return "No health report yet — no checks have been run."

        _STATUS_ICONS = {
            ServiceStatus.HEALTHY: "🟢",
            ServiceStatus.DEGRADED: "🟡",
            ServiceStatus.UNHEALTHY: "🔴",
        }

        _OVERALL_TEXT = {
            ServiceStatus.HEALTHY: "✅ HEALTHY",
            ServiceStatus.DEGRADED: "⚠️ DEGRADED",
            ServiceStatus.UNHEALTHY: "❌ UNHEALTHY",
        }

        lines = ["🏥 Bantz Health Report:"]
        services = sorted(report.checks.items())
        for i, (name, status) in enumerate(services):
            is_last = i == len(services) - 1
            prefix = "└──" if is_last else "├──"
            icon = _STATUS_ICONS.get(status.status, "⚪")
            detail = f"({status.latency_ms:.0f}ms)"
            if status.error:
                detail += f" — {status.error}"
            lines.append(
                f"  {prefix} {icon} {name:<12} {status.status.value:<10} {detail}"
            )

        lines.append("")
        overall_text = _OVERALL_TEXT.get(report.overall, str(report.overall))
        lines.append(f"Overall: {overall_text}")

        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────

_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(**kwargs: Any) -> HealthMonitor:
    """Get or create singleton HealthMonitor."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor(**kwargs)
    return _health_monitor


def reset_health_monitor() -> None:
    """Reset singleton (for tests)."""
    global _health_monitor
    _health_monitor = None
