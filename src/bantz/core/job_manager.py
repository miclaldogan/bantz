"""
Job Manager for Bantz Agent OS.

This module provides the JobManager class for creating, managing, and
tracking jobs in the Bantz system.

Reference: Issue #31 - V2-1: Agent OS Core
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import threading

from bantz.core.events import EventBus, EventType, get_event_bus
from bantz.core.job import (
    Job,
    JobState,
    InvalidTransitionError,
    FINAL_STATES,
)


class JobManager:
    """
    Manages the lifecycle of jobs in the Bantz system.
    
    Responsibilities:
    - Create new jobs
    - Track job state transitions
    - Emit events for state changes
    - Provide job queries (active, by priority, etc.)
    
    Usage:
        >>> manager = JobManager()
        >>> job = manager.create_job("search for news")
        >>> manager.start_job(job.id)
        >>> manager.complete_job(job.id, {"results": [...]})
    """
    
    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        Initialize JobManager.
        
        Args:
            event_bus: EventBus instance for publishing events.
                      If None, uses singleton instance.
        """
        self._jobs: Dict[str, Job] = {}
        self._event_bus = event_bus or get_event_bus()
        self._lock = threading.Lock()
    
    def create_job(
        self,
        request: str,
        priority: int = 0,
        parent_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Job:
        """
        Create a new job.
        
        Args:
            request: The user request/command
            priority: Job priority (higher = more important)
            parent_id: Parent job ID if this is a child job
            metadata: Additional metadata
            
        Returns:
            New Job instance
        """
        job = Job.create(
            request=request,
            priority=priority,
            parent_id=parent_id,
            metadata=metadata,
        )
        
        with self._lock:
            self._jobs[job.id] = job
        
        # Emit event
        self._emit_job_event(EventType.JOB_CREATED, job)
        
        return job
    
    def start_job(self, job_id: str) -> bool:
        """
        Start a job (transition to RUNNING).
        
        Args:
            job_id: Job ID to start
            
        Returns:
            True if successful, False if job not found or invalid transition
        """
        return self._transition_job(job_id, JobState.RUNNING, EventType.JOB_STARTED)
    
    def pause_job(self, job_id: str) -> bool:
        """
        Pause a running job.
        
        Args:
            job_id: Job ID to pause
            
        Returns:
            True if successful, False otherwise
        """
        return self._transition_job(job_id, JobState.PAUSED, EventType.JOB_PAUSED)
    
    def resume_job(self, job_id: str) -> bool:
        """
        Resume a paused job.
        
        Args:
            job_id: Job ID to resume
            
        Returns:
            True if successful, False otherwise
        """
        return self._transition_job(job_id, JobState.RUNNING, EventType.JOB_RESUMED)
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a job.
        
        Args:
            job_id: Job ID to cancel
            
        Returns:
            True if successful, False otherwise
        """
        return self._transition_job(job_id, JobState.CANCELLED, EventType.JOB_CANCELLED)
    
    def complete_job(self, job_id: str, result: Any = None) -> bool:
        """
        Mark a job as completed with result.
        
        Args:
            job_id: Job ID to complete
            result: Result data
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            
            try:
                job.transition_to(JobState.DONE)
                job.result = result
            except InvalidTransitionError:
                return False
        
        self._emit_job_event(EventType.JOB_COMPLETED, job, {"result": result})
        return True
    
    def fail_job(self, job_id: str, error: str) -> bool:
        """
        Mark a job as failed with error.
        
        Args:
            job_id: Job ID to fail
            error: Error message
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            
            try:
                job.transition_to(JobState.FAILED)
                job.error = error
            except InvalidTransitionError:
                return False
        
        self._emit_job_event(EventType.JOB_FAILED, job, {"error": error})
        return True
    
    def set_waiting_user(self, job_id: str, question: str) -> bool:
        """
        Set job to waiting for user input.
        
        Args:
            job_id: Job ID
            question: Question to ask user
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            
            try:
                job.transition_to(JobState.WAITING_USER)
                job.metadata["pending_question"] = question
            except InvalidTransitionError:
                return False
        
        self._event_bus.publish(
            EventType.QUESTION.value,
            {"job_id": job_id, "question": question},
            source="job_manager",
        )
        return True
    
    def set_verifying(self, job_id: str) -> bool:
        """
        Set job to verifying state.
        
        Args:
            job_id: Job ID
            
        Returns:
            True if successful, False otherwise
        """
        return self._transition_job(job_id, JobState.VERIFYING)
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Get a job by ID.
        
        Args:
            job_id: Job ID
            
        Returns:
            Job instance or None if not found
        """
        with self._lock:
            return self._jobs.get(job_id)
    
    def get_active_jobs(self) -> List[Job]:
        """
        Get all active (non-final) jobs.
        
        Returns:
            List of active jobs
        """
        with self._lock:
            return [job for job in self._jobs.values() if job.is_active]
    
    def get_jobs_by_state(self, state: JobState) -> List[Job]:
        """
        Get all jobs in a specific state.
        
        Args:
            state: JobState to filter by
            
        Returns:
            List of jobs in that state
        """
        with self._lock:
            return [job for job in self._jobs.values() if job.state == state]
    
    def get_job_by_priority(self) -> Optional[Job]:
        """
        Get the highest priority active job.
        
        Returns:
            Highest priority active job, or None if no active jobs
        """
        active_jobs = self.get_active_jobs()
        if not active_jobs:
            return None
        
        return max(active_jobs, key=lambda j: j.priority)
    
    def get_running_jobs(self) -> List[Job]:
        """Get all currently running jobs."""
        return self.get_jobs_by_state(JobState.RUNNING)
    
    def get_paused_jobs(self) -> List[Job]:
        """Get all paused jobs."""
        return self.get_jobs_by_state(JobState.PAUSED)
    
    def get_children(self, parent_id: str) -> List[Job]:
        """
        Get all child jobs of a parent.
        
        Args:
            parent_id: Parent job ID
            
        Returns:
            List of child jobs
        """
        with self._lock:
            return [job for job in self._jobs.values() if job.parent_id == parent_id]
    
    def _transition_job(
        self,
        job_id: str,
        new_state: JobState,
        event_type: Optional[EventType] = None,
    ) -> bool:
        """
        Internal method to transition a job to a new state.
        
        Args:
            job_id: Job ID
            new_state: Target state
            event_type: Event to emit on success
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            
            try:
                job.transition_to(new_state)
            except InvalidTransitionError:
                return False
        
        if event_type:
            self._emit_job_event(event_type, job)
        
        return True
    
    def _emit_job_event(
        self,
        event_type: EventType,
        job: Job,
        extra_data: Optional[dict] = None,
    ) -> None:
        """
        Emit a job-related event.
        
        Args:
            event_type: Type of event
            job: Job instance
            extra_data: Additional data to include
        """
        data = {
            "job_id": job.id,
            "request": job.request,
            "state": job.state.value,
            "priority": job.priority,
        }
        
        if job.parent_id:
            data["parent_id"] = job.parent_id
        
        if extra_data:
            data.update(extra_data)
        
        self._event_bus.publish(event_type.value, data, source="job_manager")
    
    def clear_completed_jobs(self) -> int:
        """
        Remove all completed (final state) jobs.
        
        Returns:
            Number of jobs removed
        """
        with self._lock:
            to_remove = [jid for jid, job in self._jobs.items() if job.is_final]
            for jid in to_remove:
                del self._jobs[jid]
            return len(to_remove)
    
    @property
    def job_count(self) -> int:
        """Total number of jobs."""
        with self._lock:
            return len(self._jobs)
    
    @property
    def active_job_count(self) -> int:
        """Number of active jobs."""
        return len(self.get_active_jobs())


# Singleton instance
_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    """Get or create singleton JobManager instance."""
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
