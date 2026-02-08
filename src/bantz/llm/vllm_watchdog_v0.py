"""vLLM Watchdog v0 (Issue #461).

Periodic health checks on the local vLLM server with:

- Consecutive failure tracking → auto-restart trigger
- Max restarts per hour (prevents infinite restart loops)
- Gemini fallback routing when vLLM is down
- Uptime / restart metrics

This module is designed to run **synchronously** (no asyncio) so it can
be used from both sync and async callers via a background thread.

See Also
--------
- ``src/bantz/llm/vllm_watchdog.py`` — existing vLLM watchdog (extended)
- ``src/bantz/brain/llm_router.py`` — hybrid LLM routing
- ``scripts/health_check_vllm.py`` — CLI health check
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "HealthStatus",
    "VLLMStatus",
    "WatchdogConfig",
    "VLLMWatchdogV0",
]


# ── Health check result ──────────────────────────────────────────────

@dataclass
class HealthStatus:
    """Result of a single health check."""

    is_healthy: bool
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: datetime = field(default_factory=datetime.utcnow)


# ── Status enum ───────────────────────────────────────────────────────

class VLLMStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"       # 1-2 failures, not yet restarting
    DOWN = "down"               # 3+ failures, restart attempted
    RESTARTING = "restarting"   # Restart in progress
    UNKNOWN = "unknown"         # Never checked

    def __str__(self) -> str:
        return self.value


# ── Config ────────────────────────────────────────────────────────────

def _default_vllm_url() -> str:
    """Read vLLM URL from env, matching runtime_factory / vllm_openai_client."""
    import os
    return os.getenv("BANTZ_VLLM_URL", "http://localhost:8001").rstrip("/")


@dataclass
class WatchdogConfig:
    """Configuration for the vLLM watchdog."""

    vllm_url: str = field(default_factory=_default_vllm_url)
    check_interval: int = 30          # seconds between checks
    consecutive_failures_to_restart: int = 3
    max_restarts_per_hour: int = 3
    warmup_seconds: float = 30.0      # Wait after restart
    health_timeout: float = 5.0       # HTTP timeout for health check


# ── Callback types ────────────────────────────────────────────────────

# health_checker: (url, timeout) → HealthStatus
HealthChecker = Callable[[str, float], HealthStatus]

# restarter: () → bool (True if restart succeeded)
Restarter = Callable[[], bool]

# fallback_toggler: (enable: bool) → None
FallbackToggler = Callable[[bool], None]

# event_logger: (event_type, data) → None
EventLogger = Callable[[str, Dict[str, Any]], None]


# ── Watchdog ──────────────────────────────────────────────────────────

class VLLMWatchdogV0:
    """vLLM health monitor with auto-restart and fallback routing.

    Parameters
    ----------
    config:
        Watchdog configuration.
    health_checker:
        ``(url, timeout) → HealthStatus``.
        If ``None``, a default HTTP checker is used (requires requests).
    restarter:
        ``() → bool``. Called to restart vLLM.
    fallback_toggler:
        ``(enable: bool) → None``. Enables/disables Gemini fallback.
    event_logger:
        ``(event_type, data) → None``. Logs events to audit log.
    """

    def __init__(
        self,
        config: Optional[WatchdogConfig] = None,
        *,
        health_checker: Optional[HealthChecker] = None,
        restarter: Optional[Restarter] = None,
        fallback_toggler: Optional[FallbackToggler] = None,
        event_logger: Optional[EventLogger] = None,
    ) -> None:
        self._config = config or WatchdogConfig()
        self._check_health = health_checker or self._default_health_check
        self._restart = restarter
        self._toggle_fallback = fallback_toggler
        self._log_event = event_logger

        self._status = VLLMStatus.UNKNOWN
        self._consecutive_failures = 0
        self._restart_timestamps: List[float] = []
        self._fallback_active = False
        self._last_check: Optional[HealthStatus] = None
        self._total_checks = 0
        self._total_failures = 0

    # ── properties ────────────────────────────────────────────────────

    @property
    def status(self) -> VLLMStatus:
        return self._status

    @property
    def is_fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def last_check(self) -> Optional[HealthStatus]:
        return self._last_check

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    # ── main check cycle ──────────────────────────────────────────────

    def check(self) -> HealthStatus:
        """Perform a single health check cycle.

        This is the main method to call periodically (e.g. every 30s).
        It checks health, tracks failures, triggers restart if needed,
        and manages fallback routing.
        """
        self._total_checks += 1
        result = self._check_health(self._config.vllm_url, self._config.health_timeout)
        self._last_check = result

        if result.is_healthy:
            self._on_healthy(result)
        else:
            self._on_unhealthy(result)

        return result

    def _on_healthy(self, result: HealthStatus) -> None:
        """Handle a healthy check."""
        if self._consecutive_failures > 0:
            logger.info("vLLM recovered after %d failures", self._consecutive_failures)

        self._consecutive_failures = 0
        self._status = VLLMStatus.HEALTHY

        # Disable fallback if it was active
        if self._fallback_active:
            self._set_fallback(False)

    def _on_unhealthy(self, result: HealthStatus) -> None:
        """Handle an unhealthy check."""
        self._consecutive_failures += 1
        self._total_failures += 1

        threshold = self._config.consecutive_failures_to_restart

        if self._consecutive_failures < threshold:
            self._status = VLLMStatus.DEGRADED
            logger.warning(
                "vLLM unhealthy (%d/%d): %s",
                self._consecutive_failures, threshold, result.error,
            )
        else:
            self._status = VLLMStatus.DOWN
            logger.error("vLLM down (%d consecutive failures)", self._consecutive_failures)

            # Enable fallback
            if not self._fallback_active:
                self._set_fallback(True)

            # Attempt restart
            self._attempt_restart()

    # ── restart ───────────────────────────────────────────────────────

    def _attempt_restart(self) -> bool:
        """Try to restart vLLM if within restart budget."""
        if self._restart is None:
            logger.warning("No restarter configured, cannot restart vLLM")
            return False

        # Check restart budget (max per hour)
        now = time.monotonic()
        hour_ago = now - 3600.0
        self._restart_timestamps = [
            ts for ts in self._restart_timestamps if ts > hour_ago
        ]

        if len(self._restart_timestamps) >= self._config.max_restarts_per_hour:
            logger.error(
                "Max restarts/hour reached (%d), skipping restart",
                self._config.max_restarts_per_hour,
            )
            return False

        self._status = VLLMStatus.RESTARTING
        logger.info("Attempting vLLM restart...")

        try:
            success = self._restart()
        except Exception as exc:
            logger.exception("Restart failed: %s", exc)
            success = False

        self._restart_timestamps.append(now)

        if self._log_event:
            self._log_event("vllm_restart", {
                "success": success,
                "consecutive_failures": self._consecutive_failures,
            })

        if success:
            logger.info("vLLM restart initiated, waiting %.0fs for warmup",
                        self._config.warmup_seconds)
            self._status = VLLMStatus.DEGRADED
        else:
            self._status = VLLMStatus.DOWN

        return success

    # ── fallback ──────────────────────────────────────────────────────

    def _set_fallback(self, enable: bool) -> None:
        """Enable or disable Gemini fallback routing."""
        self._fallback_active = enable
        if self._toggle_fallback:
            try:
                self._toggle_fallback(enable)
            except Exception:
                logger.exception("Fallback toggle error")

        action = "enabled" if enable else "disabled"
        logger.info("Gemini fallback %s", action)

        if self._log_event:
            self._log_event("gemini_fallback", {"enabled": enable})

    # ── metrics ───────────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """Return watchdog metrics."""
        return {
            "status": self._status.value,
            "total_checks": self._total_checks,
            "total_failures": self._total_failures,
            "consecutive_failures": self._consecutive_failures,
            "restart_count_last_hour": len(self._restart_timestamps),
            "fallback_active": self._fallback_active,
            "last_response_time_ms": (
                self._last_check.response_time_ms if self._last_check else None
            ),
        }

    # ── startup check ─────────────────────────────────────────────────

    def startup_check(self) -> bool:
        """Quick health check at boot time.

        Returns ``True`` if vLLM is reachable, ``False`` otherwise.
        When False, fallback is automatically enabled.
        """
        result = self.check()
        if not result.is_healthy:
            logger.warning("vLLM not available at startup — Gemini-only mode")
            if not self._fallback_active:
                self._set_fallback(True)
        return result.is_healthy

    # ── default health checker ────────────────────────────────────────

    @staticmethod
    def _default_health_check(url: str, timeout: float) -> HealthStatus:
        """HTTP GET to /health endpoint."""
        try:
            import requests
            start = time.monotonic()
            resp = requests.get(f"{url}/health", timeout=timeout)
            elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                return HealthStatus(
                    is_healthy=True,
                    response_time_ms=elapsed_ms,
                )
            return HealthStatus(
                is_healthy=False,
                response_time_ms=elapsed_ms,
                error=f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return HealthStatus(is_healthy=False, error=str(exc))
