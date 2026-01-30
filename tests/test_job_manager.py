"""
Tests for Job Manager (Issue #31 - V2-1).

Tests the JobManager class for job lifecycle management.
"""

import pytest
from datetime import datetime

from bantz.core.events import EventBus
from bantz.core.job import Job, JobState
from bantz.core.job_manager import JobManager


@pytest.fixture
def event_bus():
    """Create fresh EventBus for each test."""
    return EventBus()


@pytest.fixture
def job_manager(event_bus):
    """Create JobManager with test EventBus."""
    return JobManager(event_bus=event_bus)


class TestJobManagerCreate:
    """Test JobManager job creation."""
    
    def test_job_manager_create_returns_job(self, job_manager):
        """create_job Job döndürür."""
        job = job_manager.create_job("test request")
        assert isinstance(job, Job)
        assert job.request == "test request"
    
    def test_job_manager_create_job_stored(self, job_manager):
        """Created job is stored in manager."""
        job = job_manager.create_job("test")
        retrieved = job_manager.get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id
    
    def test_job_manager_create_with_priority(self, job_manager):
        """create_job accepts priority."""
        job = job_manager.create_job("test", priority=5)
        assert job.priority == 5
    
    def test_job_manager_create_with_parent(self, job_manager):
        """create_job accepts parent_id."""
        parent = job_manager.create_job("parent")
        child = job_manager.create_job("child", parent_id=parent.id)
        assert child.parent_id == parent.id
    
    def test_job_manager_create_emits_event(self, job_manager, event_bus):
        """create_job emits JOB_CREATED event."""
        events = []
        event_bus.subscribe("job.created", lambda e: events.append(e))
        
        job = job_manager.create_job("test")
        
        assert len(events) == 1
        assert events[0].data["job_id"] == job.id


class TestJobManagerStateTransitions:
    """Test JobManager state transition methods."""
    
    def test_job_manager_start_changes_state(self, job_manager):
        """start_job state'i RUNNING yapar."""
        job = job_manager.create_job("test")
        assert job.state == JobState.CREATED
        
        result = job_manager.start_job(job.id)
        
        assert result is True
        assert job.state == JobState.RUNNING
    
    def test_job_manager_pause_changes_state(self, job_manager):
        """pause_job state'i PAUSED yapar."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        
        result = job_manager.pause_job(job.id)
        
        assert result is True
        assert job.state == JobState.PAUSED
    
    def test_job_manager_resume_changes_state(self, job_manager):
        """resume_job PAUSED → RUNNING."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.pause_job(job.id)
        
        result = job_manager.resume_job(job.id)
        
        assert result is True
        assert job.state == JobState.RUNNING
    
    def test_job_manager_cancel_changes_state(self, job_manager):
        """cancel_job state'i CANCELLED yapar."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.pause_job(job.id)
        
        result = job_manager.cancel_job(job.id)
        
        assert result is True
        assert job.state == JobState.CANCELLED
    
    def test_job_manager_complete_with_result(self, job_manager):
        """complete_job result kaydeder."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        
        result_data = {"answer": 42}
        success = job_manager.complete_job(job.id, result_data)
        
        assert success is True
        assert job.state == JobState.DONE
        assert job.result == result_data
    
    def test_job_manager_fail_with_error(self, job_manager):
        """fail_job error kaydeder."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        
        error_msg = "Something went wrong"
        success = job_manager.fail_job(job.id, error_msg)
        
        assert success is True
        assert job.state == JobState.FAILED
        assert job.error == error_msg
    
    def test_job_manager_invalid_transition_returns_false(self, job_manager):
        """Invalid transition returns False."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.complete_job(job.id, None)
        
        # Try to start a completed job
        result = job_manager.start_job(job.id)
        
        assert result is False
    
    def test_job_manager_nonexistent_job_returns_false(self, job_manager):
        """Operations on nonexistent job return False."""
        assert job_manager.start_job("nonexistent") is False
        assert job_manager.pause_job("nonexistent") is False
        assert job_manager.resume_job("nonexistent") is False
        assert job_manager.cancel_job("nonexistent") is False
        assert job_manager.complete_job("nonexistent", None) is False
        assert job_manager.fail_job("nonexistent", "error") is False


class TestJobManagerQueries:
    """Test JobManager query methods."""
    
    def test_job_manager_get_job(self, job_manager):
        """get_job returns job by ID."""
        job = job_manager.create_job("test")
        retrieved = job_manager.get_job(job.id)
        assert retrieved is job
    
    def test_job_manager_get_job_nonexistent(self, job_manager):
        """get_job returns None for nonexistent ID."""
        assert job_manager.get_job("nonexistent") is None
    
    def test_job_manager_active_jobs_filter(self, job_manager):
        """get_active_jobs returns only active jobs."""
        job1 = job_manager.create_job("job1")
        job2 = job_manager.create_job("job2")
        job3 = job_manager.create_job("job3")
        
        job_manager.start_job(job1.id)
        job_manager.start_job(job2.id)
        job_manager.start_job(job3.id)
        job_manager.complete_job(job2.id, None)  # Make job2 inactive
        
        active = job_manager.get_active_jobs()
        
        assert len(active) == 2
        assert job1 in active
        assert job3 in active
        assert job2 not in active
    
    def test_job_manager_priority_order(self, job_manager):
        """get_job_by_priority returns highest priority job."""
        job1 = job_manager.create_job("low priority", priority=1)
        job2 = job_manager.create_job("high priority", priority=10)
        job3 = job_manager.create_job("medium priority", priority=5)
        
        highest = job_manager.get_job_by_priority()
        
        assert highest is job2
    
    def test_job_manager_priority_no_active(self, job_manager):
        """get_job_by_priority returns None if no active jobs."""
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.complete_job(job.id, None)
        
        assert job_manager.get_job_by_priority() is None
    
    def test_job_manager_get_running_jobs(self, job_manager):
        """get_running_jobs returns only running jobs."""
        job1 = job_manager.create_job("job1")
        job2 = job_manager.create_job("job2")
        
        job_manager.start_job(job1.id)
        job_manager.start_job(job2.id)
        job_manager.pause_job(job2.id)
        
        running = job_manager.get_running_jobs()
        
        assert len(running) == 1
        assert job1 in running
    
    def test_job_manager_get_paused_jobs(self, job_manager):
        """get_paused_jobs returns only paused jobs."""
        job1 = job_manager.create_job("job1")
        job2 = job_manager.create_job("job2")
        
        job_manager.start_job(job1.id)
        job_manager.start_job(job2.id)
        job_manager.pause_job(job1.id)
        
        paused = job_manager.get_paused_jobs()
        
        assert len(paused) == 1
        assert job1 in paused
    
    def test_job_manager_get_children(self, job_manager):
        """get_children returns child jobs."""
        parent = job_manager.create_job("parent")
        child1 = job_manager.create_job("child1", parent_id=parent.id)
        child2 = job_manager.create_job("child2", parent_id=parent.id)
        other = job_manager.create_job("other")
        
        children = job_manager.get_children(parent.id)
        
        assert len(children) == 2
        assert child1 in children
        assert child2 in children
        assert other not in children


class TestJobManagerEvents:
    """Test JobManager event emissions."""
    
    def test_job_manager_start_emits_event(self, job_manager, event_bus):
        """start_job emits JOB_STARTED event."""
        events = []
        event_bus.subscribe("job.started", lambda e: events.append(e))
        
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        
        assert len(events) == 1
        assert events[0].data["job_id"] == job.id
    
    def test_job_manager_pause_emits_event(self, job_manager, event_bus):
        """pause_job emits JOB_PAUSED event."""
        events = []
        event_bus.subscribe("job.paused", lambda e: events.append(e))
        
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.pause_job(job.id)
        
        assert len(events) == 1
    
    def test_job_manager_complete_emits_event(self, job_manager, event_bus):
        """complete_job emits JOB_COMPLETED event."""
        events = []
        event_bus.subscribe("job.completed", lambda e: events.append(e))
        
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.complete_job(job.id, {"result": "success"})
        
        assert len(events) == 1
        assert events[0].data["result"] == {"result": "success"}
    
    def test_job_manager_fail_emits_event(self, job_manager, event_bus):
        """fail_job emits JOB_FAILED event."""
        events = []
        event_bus.subscribe("job.failed", lambda e: events.append(e))
        
        job = job_manager.create_job("test")
        job_manager.start_job(job.id)
        job_manager.fail_job(job.id, "error message")
        
        assert len(events) == 1
        assert events[0].data["error"] == "error message"


class TestJobManagerMaintenance:
    """Test JobManager maintenance methods."""
    
    def test_job_manager_job_count(self, job_manager):
        """job_count returns total jobs."""
        assert job_manager.job_count == 0
        
        job_manager.create_job("job1")
        job_manager.create_job("job2")
        
        assert job_manager.job_count == 2
    
    def test_job_manager_active_job_count(self, job_manager):
        """active_job_count returns active jobs only."""
        job1 = job_manager.create_job("job1")
        job2 = job_manager.create_job("job2")
        
        assert job_manager.active_job_count == 2
        
        job_manager.start_job(job1.id)
        job_manager.complete_job(job1.id, None)
        
        assert job_manager.active_job_count == 1
    
    def test_job_manager_clear_completed(self, job_manager):
        """clear_completed_jobs removes final state jobs."""
        job1 = job_manager.create_job("job1")
        job2 = job_manager.create_job("job2")
        job3 = job_manager.create_job("job3")
        
        job_manager.start_job(job1.id)
        job_manager.start_job(job2.id)
        job_manager.complete_job(job1.id, None)
        job_manager.fail_job(job2.id, "error")
        
        removed = job_manager.clear_completed_jobs()
        
        assert removed == 2
        assert job_manager.job_count == 1
        assert job_manager.get_job(job3.id) is not None
