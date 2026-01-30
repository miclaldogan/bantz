"""Bantz Core - Event bus, state management, proactive systems.

Note:
This package intentionally avoids importing `bantz.core.orchestrator` at
import-time. Running `python -m bantz.core.orchestrator` causes Python to load
the package `bantz.core` first; eager imports would load the orchestrator
module twice and trigger a `runpy` warning.
"""

from __future__ import annotations

import importlib
from typing import Any

from bantz.core.events import EventBus, Event, get_event_bus, EventType
from bantz.core.timing import (
    TimingRequirements,
    TIMING,
    is_ack_fast_enough,
    is_source_time_valid,
    is_summary_fast_enough,
    get_retry_delay,
    TimingMetric,
    measure_ack_timing,
    measure_summary_timing,
)
from bantz.core.job import Job, JobState, InvalidTransitionError, TRANSITIONS
from bantz.core.job_manager import JobManager, get_job_manager
from bantz.core.interrupt import InterruptManager, get_interrupt_manager

_ORCHESTRATOR_EXPORTS = {
    "BantzOrchestrator",
    "OrchestratorConfig",
    "SystemState",
    "ComponentState",
    "ComponentStatus",
    "get_orchestrator",
    "start_jarvis",
    "stop_jarvis",
}


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name in _ORCHESTRATOR_EXPORTS:
        module = importlib.import_module("bantz.core.orchestrator")
        return getattr(module, name)
    raise AttributeError(f"module 'bantz.core' has no attribute {name!r}")

__all__ = [
    # Events
    "EventBus",
    "Event",
    "get_event_bus",
    "EventType",
    # Timing
    "TimingRequirements",
    "TIMING",
    "is_ack_fast_enough",
    "is_source_time_valid",
    "is_summary_fast_enough",
    "get_retry_delay",
    "TimingMetric",
    "measure_ack_timing",
    "measure_summary_timing",
    # Job Management (V2-1)
    "Job",
    "JobState",
    "InvalidTransitionError",
    "TRANSITIONS",
    "JobManager",
    "get_job_manager",
    # Interrupt Management (V2-1)
    "InterruptManager",
    "get_interrupt_manager",
    # Orchestrator (Full System Startup)
    "BantzOrchestrator",
    "OrchestratorConfig",
    "SystemState",
    "ComponentState",
    "ComponentStatus",
    "get_orchestrator",
    "start_jarvis",
    "stop_jarvis",
]

