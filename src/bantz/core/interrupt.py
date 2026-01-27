"""
Interrupt Manager for Bantz Agent OS.

This module provides the InterruptManager class for handling barge-in
scenarios where a user interrupts an ongoing job.

Reference: Issue #31 - V2-1: Agent OS Core
"""

from typing import Callable, Optional
import threading

from bantz.core.events import EventBus, EventType, get_event_bus
from bantz.core.job import Job, JobState
from bantz.core.job_manager import JobManager, get_job_manager


class InterruptManager:
    """
    Manages interrupts (barge-in) during job execution.
    
    When a user says "hey bantz" during an ongoing job:
    1. Current job is paused
    2. New child job is created with high priority
    3. When child completes, parent is resumed
    
    Usage:
        >>> manager = InterruptManager()
        >>> # User interrupts during ongoing job
        >>> child_job = manager.interrupt(parent_job_id, "new request")
        >>> # ... child job runs ...
        >>> # When child completes, parent auto-resumes
    """
    
    # Default priority boost for interrupt jobs
    INTERRUPT_PRIORITY_BOOST = 100
    
    def __init__(
        self,
        job_manager: Optional[JobManager] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize InterruptManager.
        
        Args:
            job_manager: JobManager instance
            event_bus: EventBus instance
        """
        self._job_manager = job_manager or get_job_manager()
        self._event_bus = event_bus or get_event_bus()
        self._lock = threading.Lock()
        
        # Track parent-child relationships for auto-resume
        self._pending_resumes: dict[str, str] = {}  # child_id -> parent_id
        
        # Subscribe to job completion events for auto-resume
        self._event_bus.subscribe(EventType.JOB_COMPLETED.value, self._on_job_completed)
        self._event_bus.subscribe(EventType.JOB_FAILED.value, self._on_job_completed)
        self._event_bus.subscribe(EventType.JOB_CANCELLED.value, self._on_job_completed)
    
    def interrupt(
        self,
        parent_job_id: str,
        new_request: str,
        priority_boost: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[Job]:
        """
        Interrupt a running job with a new request.
        
        Args:
            parent_job_id: ID of the job to interrupt
            new_request: New user request
            priority_boost: Priority boost for child job (default: 100)
            metadata: Additional metadata for child job
            
        Returns:
            New child Job if successful, None if parent not found or can't be paused
        """
        parent_job = self._job_manager.get_job(parent_job_id)
        if parent_job is None:
            return None
        
        # Only interrupt running jobs
        if parent_job.state != JobState.RUNNING:
            return None
        
        # Pause the parent job
        if not self._job_manager.pause_job(parent_job_id):
            return None
        
        # Calculate child priority
        boost = priority_boost if priority_boost is not None else self.INTERRUPT_PRIORITY_BOOST
        child_priority = parent_job.priority + boost
        
        # Create child job
        child_metadata = metadata or {}
        child_metadata["interrupt_from"] = parent_job_id
        
        child_job = self._job_manager.create_job(
            request=new_request,
            priority=child_priority,
            parent_id=parent_job_id,
            metadata=child_metadata,
        )
        
        # Track for auto-resume
        with self._lock:
            self._pending_resumes[child_job.id] = parent_job_id
        
        # Emit interrupt event
        self._event_bus.publish(
            "interrupt",
            {
                "parent_job_id": parent_job_id,
                "child_job_id": child_job.id,
                "request": new_request,
            },
            source="interrupt_manager",
        )
        
        return child_job
    
    def interrupt_all_running(self, new_request: str) -> list[Job]:
        """
        Interrupt all currently running jobs.
        
        Args:
            new_request: New user request
            
        Returns:
            List of created child jobs
        """
        running_jobs = self._job_manager.get_running_jobs()
        child_jobs = []
        
        for job in running_jobs:
            child = self.interrupt(job.id, new_request)
            if child:
                child_jobs.append(child)
        
        return child_jobs
    
    def cancel_and_resume_parent(self, child_job_id: str) -> bool:
        """
        Cancel a child job and resume its parent.
        
        Args:
            child_job_id: Child job ID to cancel
            
        Returns:
            True if successful
        """
        with self._lock:
            parent_id = self._pending_resumes.get(child_job_id)
        
        if parent_id is None:
            return self._job_manager.cancel_job(child_job_id)
        
        # Cancel child
        self._job_manager.cancel_job(child_job_id)
        
        # Resume parent
        return self._resume_parent(child_job_id)
    
    def _on_job_completed(self, event) -> None:
        """
        Handle job completion events for auto-resume.
        
        When a child job completes (done/failed/cancelled),
        automatically resume the parent job.
        """
        child_job_id = event.data.get("job_id")
        if child_job_id:
            self._resume_parent(child_job_id)
    
    def _resume_parent(self, child_job_id: str) -> bool:
        """
        Resume parent job after child completion.
        
        Args:
            child_job_id: Child job ID
            
        Returns:
            True if parent was resumed
        """
        with self._lock:
            parent_id = self._pending_resumes.pop(child_job_id, None)
        
        if parent_id is None:
            return False
        
        # Resume parent
        parent_job = self._job_manager.get_job(parent_id)
        if parent_job and parent_job.state == JobState.PAUSED:
            return self._job_manager.resume_job(parent_id)
        
        return False
    
    def get_pending_parent(self, child_job_id: str) -> Optional[str]:
        """
        Get the parent job ID for a child job.
        
        Args:
            child_job_id: Child job ID
            
        Returns:
            Parent job ID or None
        """
        with self._lock:
            return self._pending_resumes.get(child_job_id)
    
    def has_pending_resume(self, parent_job_id: str) -> bool:
        """
        Check if a parent job has a pending child.
        
        Args:
            parent_job_id: Parent job ID
            
        Returns:
            True if there's a pending child job
        """
        with self._lock:
            return parent_job_id in self._pending_resumes.values()
    
    @property
    def pending_count(self) -> int:
        """Number of pending parent-child relationships."""
        with self._lock:
            return len(self._pending_resumes)


# Singleton instance
_interrupt_manager: Optional[InterruptManager] = None


def get_interrupt_manager() -> InterruptManager:
    """Get or create singleton InterruptManager instance."""
    global _interrupt_manager
    if _interrupt_manager is None:
        _interrupt_manager = InterruptManager()
    return _interrupt_manager
