"""
Attention Gate for Voice Control (Issue #35 - Voice-2).

Controls when the voice system should listen based on:
- IDLE: Not listening at all
- WAKEWORD_ONLY: Only listening for "Hey Bantz"
- ENGAGED: Active conversation, no wake word needed
- TASK_RUNNING: Task in progress, only interrupt wake word

This prevents unnecessary processing during task execution
while still allowing interrupts via wake word.
"""

from enum import Enum
from typing import Optional, Callable
from dataclasses import dataclass
import time
import threading

from bantz.core.events import EventBus, get_event_bus


class ListeningMode(Enum):
    """Voice listening modes."""
    IDLE = "idle"                     # Not listening at all
    WAKEWORD_ONLY = "wakeword_only"   # Only "Hey Bantz" triggers
    ENGAGED = "engaged"               # Active conversation, no wake word needed
    TASK_RUNNING = "task_running"     # Task running, only interrupt wake word


@dataclass
class AttentionGateConfig:
    """Configuration for AttentionGate."""
    engaged_timeout: float = 15.0      # Seconds before engaged → wakeword_only
    initial_mode: ListeningMode = ListeningMode.WAKEWORD_ONLY
    auto_engage_on_wake: bool = True   # Auto transition to ENGAGED on wake word


class AttentionGate:
    """
    Controls voice listening behavior based on system state.
    
    State Machine:
        WAKEWORD_ONLY ──(wake word)──> ENGAGED
        ENGAGED ───(timeout)────────> WAKEWORD_ONLY
        ENGAGED ───(job started)────> TASK_RUNNING
        TASK_RUNNING ──(job done)──> ENGAGED
        TASK_RUNNING ──(wake word)──> INTERRUPT (stays TASK_RUNNING)
    
    Usage:
        gate = AttentionGate(job_manager, event_bus)
        
        if gate.should_process_speech():
            # Process normal speech
        elif gate.should_interrupt():
            # Handle interrupt
    """
    
    def __init__(
        self,
        job_manager=None,  # Optional[JobManager]
        event_bus: Optional[EventBus] = None,
        config: Optional[AttentionGateConfig] = None
    ):
        """
        Initialize AttentionGate.
        
        Args:
            job_manager: JobManager instance for job state tracking
            event_bus: EventBus for listening to events
            config: Gate configuration
        """
        self._job_manager = job_manager
        self._event_bus = event_bus or get_event_bus()
        self._config = config or AttentionGateConfig()
        
        self._mode = self._config.initial_mode
        self._mode_lock = threading.Lock()
        
        # Engaged window tracking
        self._engaged_start_time: Optional[float] = None
        self._current_job_id: Optional[str] = None
        
        # Wake word detection flag (for interrupt handling)
        self._wake_detected = False
        
        # Callbacks
        self._on_mode_change: Optional[Callable[[ListeningMode, ListeningMode], None]] = None
        
        # Subscribe to events
        self._setup_event_subscriptions()
    
    def _setup_event_subscriptions(self):
        """Subscribe to relevant events."""
        if self._event_bus:
            self._event_bus.subscribe("job.started", self._handle_job_started)
            self._event_bus.subscribe("job.completed", self._handle_job_completed)
            self._event_bus.subscribe("job.failed", self._handle_job_failed)
            self._event_bus.subscribe("job.cancelled", self._handle_job_cancelled)
    
    @property
    def mode(self) -> ListeningMode:
        """Get current listening mode."""
        with self._mode_lock:
            # Check for engaged timeout
            if self._mode == ListeningMode.ENGAGED:
                if self._is_engaged_expired():
                    self._set_mode(ListeningMode.WAKEWORD_ONLY)
            return self._mode
    
    def _set_mode(self, new_mode: ListeningMode) -> None:
        """Set mode with callback notification."""
        old_mode = self._mode
        self._mode = new_mode
        
        if old_mode != new_mode:
            if self._on_mode_change:
                self._on_mode_change(old_mode, new_mode)
            
            # Publish mode change event
            if self._event_bus:
                self._event_bus.publish(
                    "attention.mode_changed",
                    {"old_mode": old_mode.value, "new_mode": new_mode.value},
                    source="attention_gate"
                )
    
    def _is_engaged_expired(self) -> bool:
        """Check if engaged window has expired."""
        if self._engaged_start_time is None:
            return True
        elapsed = time.time() - self._engaged_start_time
        return elapsed >= self._config.engaged_timeout
    
    def on_wake_word_detected(self) -> None:
        """
        Handle wake word detection.
        
        - From WAKEWORD_ONLY: Transition to ENGAGED
        - From ENGAGED: Reset engaged timer
        - From TASK_RUNNING: Set interrupt flag
        """
        with self._mode_lock:
            if self._mode == ListeningMode.WAKEWORD_ONLY:
                if self._config.auto_engage_on_wake:
                    self._engaged_start_time = time.time()
                    self._set_mode(ListeningMode.ENGAGED)
            
            elif self._mode == ListeningMode.ENGAGED:
                # Reset engaged timer
                self._engaged_start_time = time.time()
            
            elif self._mode == ListeningMode.TASK_RUNNING:
                # Set interrupt flag
                self._wake_detected = True
    
    def on_speech_end(self) -> None:
        """
        Handle end of user speech.
        
        Extends engaged window on speech activity.
        """
        with self._mode_lock:
            if self._mode == ListeningMode.ENGAGED:
                # Extend engaged window
                self._engaged_start_time = time.time()
    
    def on_job_started(self, job_id: str) -> None:
        """
        Handle job start event.
        
        Transitions to TASK_RUNNING mode.
        """
        with self._mode_lock:
            self._current_job_id = job_id
            if self._mode in (ListeningMode.ENGAGED, ListeningMode.WAKEWORD_ONLY):
                self._set_mode(ListeningMode.TASK_RUNNING)
    
    def on_job_completed(self, job_id: str) -> None:
        """
        Handle job completion.
        
        Transitions back to ENGAGED mode.
        """
        with self._mode_lock:
            if self._current_job_id == job_id:
                self._current_job_id = None
                if self._mode == ListeningMode.TASK_RUNNING:
                    self._engaged_start_time = time.time()
                    self._set_mode(ListeningMode.ENGAGED)
    
    def should_process_speech(self) -> bool:
        """
        Check if speech should be processed.
        
        Returns:
            True if system should process normal speech
        """
        current_mode = self.mode  # Property checks timeout
        return current_mode == ListeningMode.ENGAGED
    
    def should_interrupt(self) -> bool:
        """
        Check if interrupt was requested.
        
        Returns:
            True if wake word was detected during TASK_RUNNING
        """
        with self._mode_lock:
            if self._wake_detected:
                self._wake_detected = False  # Clear flag
                return True
            return False
    
    def clear_interrupt(self) -> None:
        """Clear interrupt flag."""
        with self._mode_lock:
            self._wake_detected = False
    
    def set_idle(self) -> None:
        """Set mode to IDLE (stop all listening)."""
        with self._mode_lock:
            self._set_mode(ListeningMode.IDLE)
            self._engaged_start_time = None
    
    def set_wakeword_only(self) -> None:
        """Set mode to WAKEWORD_ONLY."""
        with self._mode_lock:
            self._set_mode(ListeningMode.WAKEWORD_ONLY)
            self._engaged_start_time = None
    
    def force_engaged(self, timeout: Optional[float] = None) -> None:
        """Force ENGAGED mode with optional custom timeout."""
        with self._mode_lock:
            self._engaged_start_time = time.time()
            if timeout is not None:
                # Temporarily adjust timeout
                self._config.engaged_timeout = timeout
            self._set_mode(ListeningMode.ENGAGED)
    
    def extend_engaged(self, seconds: float = 5.0) -> None:
        """Extend engaged window by additional seconds."""
        with self._mode_lock:
            if self._mode == ListeningMode.ENGAGED and self._engaged_start_time:
                self._engaged_start_time += seconds
    
    def on_mode_change(self, callback: Callable[[ListeningMode, ListeningMode], None]) -> None:
        """Register mode change callback."""
        self._on_mode_change = callback
    
    def get_current_job_id(self) -> Optional[str]:
        """Get current job ID if any."""
        with self._mode_lock:
            return self._current_job_id
    
    def _handle_job_started(self, event) -> None:
        """Event handler for job.started."""
        job_id = event.data.get("job_id")
        if job_id:
            self.on_job_started(job_id)
    
    def _handle_job_completed(self, event) -> None:
        """Event handler for job.completed."""
        job_id = event.data.get("job_id")
        if job_id:
            self.on_job_completed(job_id)
    
    def _handle_job_failed(self, event) -> None:
        """Event handler for job.failed."""
        job_id = event.data.get("job_id")
        if job_id:
            self.on_job_completed(job_id)  # Treat as completion
    
    def _handle_job_cancelled(self, event) -> None:
        """Event handler for job.cancelled."""
        job_id = event.data.get("job_id")
        if job_id:
            self.on_job_completed(job_id)  # Treat as completion


def create_attention_gate(
    job_manager=None,
    event_bus: Optional[EventBus] = None,
    engaged_timeout: float = 15.0,
    **config_kwargs
) -> AttentionGate:
    """
    Factory function to create AttentionGate.
    
    Args:
        job_manager: Optional JobManager instance
        event_bus: Optional EventBus instance
        engaged_timeout: Engaged window timeout in seconds
        **config_kwargs: Additional AttentionGateConfig parameters
    
    Returns:
        Configured AttentionGate instance
    """
    config = AttentionGateConfig(
        engaged_timeout=engaged_timeout,
        **config_kwargs
    )
    return AttentionGate(job_manager, event_bus, config)
