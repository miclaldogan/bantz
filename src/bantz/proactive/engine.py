"""Proactive Intelligence Engine — Main orchestrator.

The ProactiveEngine is the central coordinator that:
1. Manages registered proactive checks (built-in + custom)
2. Runs a background scheduler thread that triggers checks
3. Delegates cross-analysis to the CrossAnalyzer
4. Routes results through the NotificationQueue
5. Respects notification policies and quiet hours
6. Integrates with the EventBus for CLI/UI delivery

Lifecycle::

    engine = ProactiveEngine(tool_registry=tools, event_bus=bus)
    engine.start()   # Starts background scheduler thread
    # ... runs autonomously ...
    engine.stop()    # Graceful shutdown

Issue #835
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time as _time
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from bantz.proactive.checks import get_builtin_checks
from bantz.proactive.cross_analyzer import CrossAnalyzer
from bantz.proactive.models import (
    CheckResult,
    CheckSchedule,
    CrossAnalysis,
    InsightSeverity,
    NotificationPolicy,
    ProactiveCheck,
    ProactiveNotification,
    ScheduleType,
)
from bantz.proactive.notification_queue import NotificationQueue

logger = logging.getLogger(__name__)

# Default config path
_CONFIG_DIR = Path.home() / ".config" / "bantz"
_PROACTIVE_CONFIG = _CONFIG_DIR / "proactive.json"

# Scheduler poll interval
_POLL_INTERVAL_SECONDS = 30


class ProactiveEngine:
    """Central proactive intelligence orchestrator.

    Parameters
    ----------
    tool_registry:
        The Bantz ToolRegistry for calling tools.
    event_bus:
        The shared EventBus for notifications.
    policy:
        Notification policy (loaded from config if not provided).
    config_path:
        Path to proactive config file.
    """

    def __init__(
        self,
        tool_registry: Any = None,
        event_bus: Any = None,
        policy: Optional[NotificationPolicy] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._event_bus = event_bus

        # Load policy from config or use default
        self._config_path = config_path or _PROACTIVE_CONFIG
        if policy:
            self._policy = policy
        else:
            self._policy = self._load_policy()

        # Core components
        self._notification_queue = NotificationQueue(
            policy=self._policy,
            event_bus=self._event_bus,
        )
        self._cross_analyzer = CrossAnalyzer()

        # Check registry
        self._checks: Dict[str, ProactiveCheck] = {}

        # Scheduler thread
        self._scheduler_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # Event-based check subscriptions
        self._event_subscriptions: List[str] = []

        # Run history (last N results per check)
        self._history: Dict[str, List[CheckResult]] = {}
        self._max_history_per_check = 10

        # Register built-in checks
        self._register_builtins()

    # ── Public API ──────────────────────────────────────────────

    def start(self) -> None:
        """Start the proactive engine background scheduler."""
        if self._running:
            logger.warning("ProactiveEngine already running")
            return

        self._running = True

        # Initialize next_run for all checks
        now = datetime.now()
        for check in self._checks.values():
            if check.enabled and check.next_run is None:
                check.next_run = check.schedule.next_run_after(now)

        # Subscribe to event-based checks
        self._setup_event_subscriptions()

        # Start scheduler thread
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="ProactiveEngine-Scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()

        logger.info(
            "ProactiveEngine started: %d checks registered (%d enabled)",
            len(self._checks),
            sum(1 for c in self._checks.values() if c.enabled),
        )

    def stop(self) -> None:
        """Stop the proactive engine gracefully."""
        self._running = False

        # Unsubscribe from events
        self._teardown_event_subscriptions()

        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=10)
            self._scheduler_thread = None

        logger.info("ProactiveEngine stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Check Management ────────────────────────────────────────

    def register_check(self, check: ProactiveCheck) -> None:
        """Register a proactive check."""
        with self._lock:
            self._checks[check.name] = check
            if check.enabled and check.next_run is None:
                check.next_run = check.schedule.next_run_after(datetime.now())
        logger.info("Proactive check registered: %s", check.name)

    def unregister_check(self, name: str) -> bool:
        """Unregister a check. Returns True if found."""
        with self._lock:
            return self._checks.pop(name, None) is not None

    def get_check(self, name: str) -> Optional[ProactiveCheck]:
        """Get a check by name."""
        return self._checks.get(name)

    def get_all_checks(self) -> List[ProactiveCheck]:
        """Get all registered checks."""
        return list(self._checks.values())

    def enable_check(self, name: str) -> bool:
        """Enable a check."""
        check = self._checks.get(name)
        if check:
            check.enabled = True
            if check.next_run is None:
                check.next_run = check.schedule.next_run_after(datetime.now())
            return True
        return False

    def disable_check(self, name: str) -> bool:
        """Disable a check."""
        check = self._checks.get(name)
        if check:
            check.enabled = False
            return True
        return False

    # ── Manual Execution ────────────────────────────────────────

    def run_check(self, name: str) -> Optional[CheckResult]:
        """Manually run a specific check (ignoring schedule)."""
        check = self._checks.get(name)
        if not check:
            logger.warning("Check '%s' not found", name)
            return None
        return self._execute_check(check)

    def run_all_checks(self) -> List[CheckResult]:
        """Manually run all enabled checks."""
        results: List[CheckResult] = []
        for check in self._checks.values():
            if check.enabled:
                result = self._execute_check(check)
                if result:
                    results.append(result)
        return results

    # ── Notification Access ─────────────────────────────────────

    @property
    def notifications(self) -> NotificationQueue:
        """Access the notification queue."""
        return self._notification_queue

    @property
    def policy(self) -> NotificationPolicy:
        """Current notification policy."""
        return self._policy

    def update_policy(self, policy: NotificationPolicy) -> None:
        """Update notification policy."""
        self._policy = policy
        self._notification_queue.update_policy(policy)
        self._save_policy()

    def set_dnd(self, enabled: bool) -> None:
        """Toggle Do Not Disturb."""
        self._notification_queue.set_dnd(enabled)

    # ── Cross-Analyzer Access ───────────────────────────────────

    @property
    def analyzer(self) -> CrossAnalyzer:
        """Access the cross-analyzer for adding custom rules."""
        return self._cross_analyzer

    # ── History ─────────────────────────────────────────────────

    def get_history(self, check_name: Optional[str] = None, limit: int = 10) -> List[CheckResult]:
        """Get recent check results."""
        if check_name:
            return list(self._history.get(check_name, []))[-limit:]
        # All checks, sorted by time
        all_results: List[CheckResult] = []
        for results in self._history.values():
            all_results.extend(results)
        all_results.sort(key=lambda r: r.timestamp, reverse=True)
        return all_results[:limit]

    # ── Status ──────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get engine status summary."""
        checks_status = []
        for check in self._checks.values():
            checks_status.append({
                "name": check.name,
                "enabled": check.enabled,
                "last_run": check.last_run.isoformat() if check.last_run else None,
                "next_run": check.next_run.isoformat() if check.next_run else None,
                "schedule": check.schedule.to_dict(),
            })

        return {
            "running": self._running,
            "checks": checks_status,
            "total_checks": len(self._checks),
            "enabled_checks": sum(1 for c in self._checks.values() if c.enabled),
            "notification_queue_size": self._notification_queue.size,
            "unread_notifications": self._notification_queue.get_unread_count(),
            "policy": self._policy.to_dict(),
            "dnd": self._policy.dnd,
        }

    # ── Internal: Scheduler ─────────────────────────────────────

    def _scheduler_loop(self) -> None:
        """Background scheduler that polls for due checks."""
        logger.debug("ProactiveEngine scheduler loop started (poll=%ds)", _POLL_INTERVAL_SECONDS)

        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error("ProactiveEngine scheduler error: %s", e, exc_info=True)

            # Sleep in small increments for responsive shutdown
            for _ in range(int(_POLL_INTERVAL_SECONDS / 2)):
                if not self._running:
                    break
                _time.sleep(2)

    def _tick(self) -> None:
        """Single scheduler tick: check all due proactive checks."""
        now = datetime.now()
        due_checks: List[ProactiveCheck] = []

        with self._lock:
            for check in self._checks.values():
                if check.is_due(now):
                    due_checks.append(check)

        for check in due_checks:
            self._execute_check(check)

    def _execute_check(self, check: ProactiveCheck) -> Optional[CheckResult]:
        """Execute a single proactive check."""
        if not check.handler:
            logger.warning("Check '%s' has no handler", check.name)
            return None

        logger.info("Running proactive check: %s", check.name)
        start = datetime.now()

        ctx: Dict[str, Any] = {
            "tool_registry": self._tool_registry,
            "event_bus": self._event_bus,
            "cross_analyzer": self._cross_analyzer,
        }

        try:
            result = check.handler(check, ctx)
        except Exception as e:
            logger.error("Proactive check '%s' failed: %s", check.name, e, exc_info=True)
            result = CheckResult(
                check_name=check.name,
                ok=False,
                error=str(e),
                duration_ms=(datetime.now() - start).total_seconds() * 1000,
            )

        # Update schedule
        check.update_next_run(start)

        # Store in history
        self._add_to_history(result)

        # Submit to notification queue
        if result.ok and result.analysis:
            self._notification_queue.submit(result)

        return result

    def _add_to_history(self, result: CheckResult) -> None:
        """Add a check result to history."""
        if result.check_name not in self._history:
            self._history[result.check_name] = []
        history = self._history[result.check_name]
        history.append(result)
        # Trim to max
        if len(history) > self._max_history_per_check:
            self._history[result.check_name] = history[-self._max_history_per_check:]

    # ── Internal: Event Subscriptions ───────────────────────────

    def _setup_event_subscriptions(self) -> None:
        """Subscribe to events for event-triggered checks."""
        if not self._event_bus:
            return

        for check in self._checks.values():
            if check.schedule.type == ScheduleType.EVENT and check.schedule.event_type:
                event_type = check.schedule.event_type

                def make_handler(c: ProactiveCheck) -> Callable:
                    def handler(event: Any) -> None:
                        if c.enabled:
                            self._execute_check(c)
                    return handler

                self._event_bus.subscribe(event_type, make_handler(check))
                self._event_subscriptions.append(event_type)

    def _teardown_event_subscriptions(self) -> None:
        """Clean up event subscriptions."""
        # Note: EventBus doesn't have unsubscribe-by-type, so we just clear
        self._event_subscriptions.clear()

    # ── Internal: Built-in Registration ─────────────────────────

    def _register_builtins(self) -> None:
        """Register all built-in proactive checks."""
        for check in get_builtin_checks():
            self._checks[check.name] = check

    # ── Internal: Config Persistence ────────────────────────────

    def _load_policy(self) -> NotificationPolicy:
        """Load notification policy from config file."""
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text())
                policy_data = data.get("notification_policy", {})
                return NotificationPolicy.from_dict(policy_data)
            except Exception as e:
                logger.warning("Failed to load proactive config: %s", e)
        return NotificationPolicy()

    def _save_policy(self) -> None:
        """Save notification policy to config file."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            data: Dict[str, Any] = {}
            if self._config_path.exists():
                try:
                    data = json.loads(self._config_path.read_text())
                except Exception:
                    pass
            data["notification_policy"] = self._policy.to_dict()
            self._config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.warning("Failed to save proactive config: %s", e)

    def _load_config(self) -> Dict[str, Any]:
        """Load full proactive config."""
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text())
            except Exception:
                pass
        return {}


# ── Singleton ───────────────────────────────────────────────────

_engine: Optional[ProactiveEngine] = None


def get_proactive_engine() -> Optional[ProactiveEngine]:
    """Get the global ProactiveEngine instance (if started)."""
    return _engine


def setup_proactive_engine(
    tool_registry: Any = None,
    event_bus: Any = None,
    *,
    auto_start: bool = True,
) -> ProactiveEngine:
    """Create and optionally start the global ProactiveEngine.

    Called from ``runtime_factory.py`` during brain wiring.
    """
    global _engine

    _engine = ProactiveEngine(
        tool_registry=tool_registry,
        event_bus=event_bus,
    )

    if auto_start:
        _engine.start()

    return _engine
