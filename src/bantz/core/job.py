"""
Job State Machine for Bantz Agent OS.

This module defines the Job dataclass and JobState enum for managing
asynchronous task execution in the Bantz system.

Reference: Issue #31 - V2-1: Agent OS Core
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class JobState(Enum):
    """
    Possible states for a Job in the Bantz system.
    
    State transitions:
    - CREATED: Job oluşturuldu, henüz başlamadı
    - RUNNING: Aktif çalışıyor
    - WAITING_USER: Kullanıcı input bekliyor
    - PAUSED: "bekle" komutu ile duraklatıldı
    - VERIFYING: Sonuç doğrulanıyor
    - DONE: Başarıyla tamamlandı (final)
    - FAILED: Hata ile sonlandı (final)
    - CANCELLED: Kullanıcı iptal etti (final)
    """
    CREATED = "created"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    PAUSED = "paused"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid state transitions
TRANSITIONS: dict[JobState, list[JobState]] = {
    JobState.CREATED: [JobState.RUNNING],
    JobState.RUNNING: [
        JobState.WAITING_USER,
        JobState.PAUSED,
        JobState.VERIFYING,
        JobState.DONE,
        JobState.FAILED,
    ],
    JobState.WAITING_USER: [JobState.RUNNING, JobState.CANCELLED],
    JobState.PAUSED: [JobState.RUNNING, JobState.CANCELLED],
    JobState.VERIFYING: [JobState.DONE, JobState.FAILED, JobState.RUNNING],
    JobState.DONE: [],      # final state
    JobState.FAILED: [],    # final state
    JobState.CANCELLED: [], # final state
}


# Final states (no further transitions allowed)
FINAL_STATES = {JobState.DONE, JobState.FAILED, JobState.CANCELLED}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    
    def __init__(self, from_state: JobState, to_state: JobState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid state transition: {from_state.value} → {to_state.value}"
        )


@dataclass
class Job:
    """
    Represents a task/job in the Bantz system.
    
    Attributes:
        id: Unique identifier for the job
        request: The original user request/command
        state: Current state of the job
        priority: Job priority (higher = more important), default 0
        parent_id: ID of parent job if this is a child (interrupt) job
        created_at: When the job was created
        started_at: When the job started running
        completed_at: When the job finished (done/failed/cancelled)
        result: Result data if job completed successfully
        error: Error message if job failed
        metadata: Additional job metadata
    """
    id: str
    request: str
    state: JobState = JobState.CREATED
    priority: int = 0
    parent_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def create(
        cls,
        request: str,
        priority: int = 0,
        parent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> "Job":
        """
        Factory method to create a new Job.
        
        Args:
            request: The user request/command
            priority: Job priority (default 0)
            parent_id: Parent job ID if this is a child job
            metadata: Additional metadata
            
        Returns:
            New Job instance with generated ID
        """
        return cls(
            id=str(uuid.uuid4()),
            request=request,
            state=JobState.CREATED,
            priority=priority,
            parent_id=parent_id,
            created_at=datetime.now(),
            metadata=metadata or {},
        )
    
    def can_transition_to(self, new_state: JobState) -> bool:
        """
        Check if transition to new_state is valid.
        
        Args:
            new_state: Target state
            
        Returns:
            True if transition is valid, False otherwise
        """
        return new_state in TRANSITIONS.get(self.state, [])
    
    def transition_to(self, new_state: JobState) -> None:
        """
        Transition job to new state.
        
        Args:
            new_state: Target state
            
        Raises:
            InvalidTransitionError: If transition is not valid
        """
        if not self.can_transition_to(new_state):
            raise InvalidTransitionError(self.state, new_state)
        
        old_state = self.state
        self.state = new_state
        
        # Update timestamps
        if new_state == JobState.RUNNING and self.started_at is None:
            self.started_at = datetime.now()
        elif new_state in FINAL_STATES:
            self.completed_at = datetime.now()
    
    @property
    def is_active(self) -> bool:
        """Check if job is in an active (non-final) state."""
        return self.state not in FINAL_STATES
    
    @property
    def is_final(self) -> bool:
        """Check if job is in a final state."""
        return self.state in FINAL_STATES
    
    @property
    def is_running(self) -> bool:
        """Check if job is currently running."""
        return self.state == JobState.RUNNING
    
    @property
    def is_paused(self) -> bool:
        """Check if job is paused."""
        return self.state == JobState.PAUSED
    
    @property
    def duration_ms(self) -> Optional[float]:
        """
        Get job duration in milliseconds.
        
        Returns:
            Duration in ms if job has started, None otherwise
        """
        if self.started_at is None:
            return None
        
        end_time = self.completed_at or datetime.now()
        delta = end_time - self.started_at
        return delta.total_seconds() * 1000
    
    def __repr__(self) -> str:
        return (
            f"Job(id={self.id[:8]}..., "
            f"state={self.state.value}, "
            f"request='{self.request[:30]}...')"
        )
