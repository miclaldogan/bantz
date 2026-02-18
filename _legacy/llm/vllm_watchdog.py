"""
vLLM Watchdog — Issue #442.

Periodically checks vLLM /health endpoint and takes corrective action:
- Health check on configurable interval
- Auto-restart on consecutive failures (up to max_restarts)
- Gemini-only fallback mode when vLLM is persistently down
- Event callbacks for monitoring integration

Usage::

    from bantz.llm.vllm_watchdog import VLLMWatchdog, WatchdogConfig

    config = WatchdogConfig(
        vllm_url="http://localhost:8001",
        check_interval=10.0,
        max_restarts=3,
    )
    watchdog = VLLMWatchdog(config)
    watchdog.start()
    ...
    watchdog.stop()
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Config & State
# ─────────────────────────────────────────────────────────────────


class VLLMStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    RESTARTING = "restarting"
    DOWN = "down"           # Permanently down (max restarts exceeded)
    UNKNOWN = "unknown"


def _default_vllm_url() -> str:
    """Read vLLM URL from env, matching runtime_factory / vllm_openai_client."""
    import os
    return os.getenv("BANTZ_VLLM_URL", "http://localhost:8001").rstrip("/")


@dataclass
class WatchdogConfig:
    """Configuration for the vLLM watchdog."""
    vllm_url: str = field(default_factory=_default_vllm_url)
    health_endpoint: str = "/v1/models"
    check_interval: float = 10.0       # seconds between checks
    failure_threshold: int = 3          # consecutive failures before restart
    max_restarts: int = 3               # max auto-restart attempts
    restart_cooldown: float = 30.0      # seconds between restart attempts
    request_timeout: float = 5.0        # HTTP timeout for health check
    restart_command: str = "systemctl --user restart vllm"


@dataclass
class WatchdogEvent:
    """An event emitted by the watchdog."""
    type: str           # health_ok, health_fail, restart_attempt, restart_success,
                        # restart_failed, fallback_activated, recovered
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "details": self.details,
        }


# Type alias for event callbacks
EventCallback = Callable[[WatchdogEvent], None]


# ─────────────────────────────────────────────────────────────────
# Health Checker (pluggable for testing)
# ─────────────────────────────────────────────────────────────────


class HealthChecker:
    """Check vLLM /health endpoint."""

    def __init__(self, base_url: str, endpoint: str, timeout: float):
        self._url = f"{base_url.rstrip('/')}{endpoint}"
        self._timeout = timeout

    def check(self) -> bool:
        """Return True if vLLM is healthy."""
        try:
            import urllib.request
            req = urllib.request.Request(self._url, method="GET")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status == 200
        except Exception:
            return False


class MockHealthChecker:
    """Pluggable health checker for testing."""

    def __init__(self, healthy: bool = True):
        self._healthy = healthy
        self.check_count = 0

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = healthy

    def check(self) -> bool:
        self.check_count += 1
        return self._healthy


# ─────────────────────────────────────────────────────────────────
# Restart Handler (pluggable for testing)
# ─────────────────────────────────────────────────────────────────


class RestartHandler:
    """Execute vLLM restart command."""

    def __init__(self, command: str):
        self._command = command

    def restart(self) -> bool:
        """Return True if restart command succeeded."""
        try:
            result = subprocess.run(
                self._command.split(),
                capture_output=True,
                timeout=30,
            )
            return result.returncode == 0
        except Exception as e:
            logger.error("Restart failed: %s", e)
            return False


class MockRestartHandler:
    """Pluggable restart handler for testing."""

    def __init__(self, success: bool = True):
        self._success = success
        self.restart_count = 0

    def set_success(self, success: bool) -> None:
        self._success = success

    def restart(self) -> bool:
        self.restart_count += 1
        return self._success


# ─────────────────────────────────────────────────────────────────
# vLLM Watchdog
# ─────────────────────────────────────────────────────────────────


class VLLMWatchdog:
    """
    Monitors vLLM health and takes corrective action.

    Lifecycle:
    1. Periodically check /health
    2. On consecutive failures → attempt restart
    3. On max restarts exceeded → activate Gemini-only fallback
    4. On recovery → deactivate fallback
    """

    def __init__(
        self,
        config: Optional[WatchdogConfig] = None,
        health_checker: Optional[Any] = None,
        restart_handler: Optional[Any] = None,
    ):
        self._config = config or WatchdogConfig()
        self._checker = health_checker or HealthChecker(
            self._config.vllm_url,
            self._config.health_endpoint,
            self._config.request_timeout,
        )
        self._restarter = restart_handler or RestartHandler(self._config.restart_command)

        # State
        self._status = VLLMStatus.UNKNOWN
        self._consecutive_failures = 0
        self._restart_count = 0
        self._last_restart_time: float = 0.0
        self._fallback_active = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Event system
        self._callbacks: List[EventCallback] = []
        self._events: List[WatchdogEvent] = []
        self._max_events = 200

    # ── Properties ──────────────────────────────────────────────

    @property
    def status(self) -> VLLMStatus:
        with self._lock:
            return self._status

    @property
    def is_fallback_active(self) -> bool:
        with self._lock:
            return self._fallback_active

    @property
    def restart_count(self) -> int:
        with self._lock:
            return self._restart_count

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    # ── Event system ────────────────────────────────────────────

    def on_event(self, callback: EventCallback) -> None:
        """Register an event callback."""
        self._callbacks.append(callback)

    def _emit(self, event_type: str, **details: Any) -> None:
        evt = WatchdogEvent(type=event_type, details=details)
        self._events.append(evt)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        for cb in self._callbacks:
            try:
                cb(evt)
            except Exception as e:
                logger.error("Event callback error: %s", e)

    # ── Core logic ──────────────────────────────────────────────

    def _do_health_check(self) -> None:
        """Run one health check cycle."""
        healthy = self._checker.check()

        with self._lock:
            if healthy:
                was_failing = self._consecutive_failures > 0 or self._fallback_active
                self._consecutive_failures = 0
                self._status = VLLMStatus.HEALTHY

                if self._fallback_active:
                    self._fallback_active = False
                    self._restart_count = 0
                    logger.info("[Watchdog] vLLM recovered — exiting fallback mode")
                    self._emit("recovered")

                if was_failing:
                    self._emit("health_ok")
                return

            # Unhealthy
            self._consecutive_failures += 1
            self._status = VLLMStatus.UNHEALTHY
            self._emit(
                "health_fail",
                consecutive=self._consecutive_failures,
            )
            logger.warning(
                "[Watchdog] vLLM health check failed (%d/%d)",
                self._consecutive_failures,
                self._config.failure_threshold,
            )

            if self._consecutive_failures < self._config.failure_threshold:
                return

            # Threshold reached — attempt restart
            if self._restart_count >= self._config.max_restarts:
                if not self._fallback_active:
                    self._fallback_active = True
                    self._status = VLLMStatus.DOWN
                    logger.error(
                        "[Watchdog] Max restarts (%d) exceeded — Gemini-only fallback",
                        self._config.max_restarts,
                    )
                    self._emit(
                        "fallback_activated",
                        restart_count=self._restart_count,
                    )
                return

            # Cooldown check
            now = time.time()
            if now - self._last_restart_time < self._config.restart_cooldown:
                return

        # Attempt restart (outside lock to avoid blocking)
        self._attempt_restart()

    def _attempt_restart(self) -> None:
        """Try to restart vLLM."""
        with self._lock:
            self._status = VLLMStatus.RESTARTING
            self._restart_count += 1
            self._last_restart_time = time.time()
            attempt = self._restart_count

        self._emit("restart_attempt", attempt=attempt)
        logger.info("[Watchdog] Restarting vLLM (attempt %d/%d)",
                     attempt, self._config.max_restarts)

        success = self._restarter.restart()

        with self._lock:
            if success:
                self._consecutive_failures = 0
                self._status = VLLMStatus.HEALTHY
                self._emit("restart_success", attempt=attempt)
                logger.info("[Watchdog] vLLM restart successful")
            else:
                self._status = VLLMStatus.UNHEALTHY
                self._emit("restart_failed", attempt=attempt)
                logger.error("[Watchdog] vLLM restart failed")

    # ── Thread lifecycle ────────────────────────────────────────

    def start(self) -> None:
        """Start the watchdog monitoring thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="vllm-watchdog",
        )
        self._thread.start()
        logger.info("[Watchdog] Started (interval=%.1fs)", self._config.check_interval)

    def stop(self) -> None:
        """Stop the watchdog monitoring thread."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("[Watchdog] Stopped")

    def _run_loop(self) -> None:
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                self._do_health_check()
            except Exception as e:
                logger.error("[Watchdog] Unexpected error: %s", e)
            self._stop_event.wait(timeout=self._config.check_interval)

    # ── Single check (for sync usage) ──────────────────────────

    def check_once(self) -> VLLMStatus:
        """Run a single health check cycle (synchronous)."""
        self._do_health_check()
        return self.status

    # ── Stats ───────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": self._status.value,
                "consecutive_failures": self._consecutive_failures,
                "restart_count": self._restart_count,
                "max_restarts": self._config.max_restarts,
                "fallback_active": self._fallback_active,
                "running": self._running,
                "total_events": len(self._events),
            }

    def get_recent_events(self, n: int = 10) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._events[-n:]]

    def reset(self) -> None:
        """Reset all state (for testing)."""
        with self._lock:
            self._status = VLLMStatus.UNKNOWN
            self._consecutive_failures = 0
            self._restart_count = 0
            self._last_restart_time = 0.0
            self._fallback_active = False
            self._events.clear()
