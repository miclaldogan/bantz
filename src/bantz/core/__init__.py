"""Bantz Core - Event bus, state management, proactive systems."""
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
]

