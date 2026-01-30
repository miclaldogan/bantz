"""
Tests for Interrupt Manager (Issue #31 - V2-1).

Tests the InterruptManager class for barge-in/interrupt handling.
"""

import pytest
import time

from bantz.core.events import EventBus
from bantz.core.job import Job, JobState
from bantz.core.job_manager import JobManager
from bantz.core.interrupt import InterruptManager


@pytest.fixture
def event_bus():
    """Create fresh EventBus for each test."""
    return EventBus()


@pytest.fixture
def job_manager(event_bus):
    """Create JobManager with test EventBus."""
    return JobManager(event_bus=event_bus)


@pytest.fixture
def interrupt_manager(job_manager, event_bus):
    """Create InterruptManager with test dependencies."""
    return InterruptManager(job_manager=job_manager, event_bus=event_bus)


class TestInterruptBasic:
    """Test basic interrupt functionality."""
    
    def test_interrupt_pauses_parent(self, interrupt_manager, job_manager):
        """Interrupt parent job'ı PAUSED yapar."""
        parent = job_manager.create_job("parent task")
        job_manager.start_job(parent.id)
        assert parent.state == JobState.RUNNING
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        
        assert parent.state == JobState.PAUSED
        assert child is not None
    
    def test_interrupt_creates_child_job(self, interrupt_manager, job_manager):
        """Child job oluşturulur."""
        parent = job_manager.create_job("parent task")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        
        assert child is not None
        assert child.request == "urgent request"
        assert child.state == JobState.CREATED
    
    def test_interrupt_child_has_parent_id(self, interrupt_manager, job_manager):
        """Child.parent_id parent'a işaret eder."""
        parent = job_manager.create_job("parent task")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        
        assert child.parent_id == parent.id
    
    def test_interrupt_child_high_priority(self, interrupt_manager, job_manager):
        """Child priority > parent priority."""
        parent = job_manager.create_job("parent task", priority=5)
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        
        assert child.priority > parent.priority
        assert child.priority == parent.priority + InterruptManager.INTERRUPT_PRIORITY_BOOST
    
    def test_interrupt_custom_priority_boost(self, interrupt_manager, job_manager):
        """Custom priority boost works."""
        parent = job_manager.create_job("parent task", priority=0)
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent", priority_boost=50)
        
        assert child.priority == 50
    
    def test_interrupt_nonexistent_parent(self, interrupt_manager):
        """Interrupt nonexistent parent returns None."""
        result = interrupt_manager.interrupt("nonexistent", "request")
        assert result is None
    
    def test_interrupt_non_running_parent(self, interrupt_manager, job_manager):
        """Interrupt non-running parent returns None."""
        parent = job_manager.create_job("parent task")
        # Parent is CREATED, not RUNNING
        
        result = interrupt_manager.interrupt(parent.id, "request")
        
        assert result is None


class TestInterruptAutoResume:
    """Test auto-resume after child completion."""
    
    def test_interrupt_resume_after_child_done(self, interrupt_manager, job_manager, event_bus):
        """Child DONE olunca parent RUNNING."""
        parent = job_manager.create_job("parent task")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        job_manager.start_job(child.id)
        
        # Complete child
        job_manager.complete_job(child.id, {"result": "done"})
        
        # Parent should be resumed
        assert parent.state == JobState.RUNNING
    
    def test_interrupt_resume_after_child_failed(self, interrupt_manager, job_manager):
        """Child FAILED olunca parent RUNNING."""
        parent = job_manager.create_job("parent task")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        job_manager.start_job(child.id)
        
        # Fail child
        job_manager.fail_job(child.id, "error")
        
        # Parent should be resumed
        assert parent.state == JobState.RUNNING
    
    def test_interrupt_cancelled_child(self, interrupt_manager, job_manager):
        """Child iptal edilirse parent yine resume."""
        parent = job_manager.create_job("parent task")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "urgent request")
        job_manager.start_job(child.id)
        job_manager.pause_job(child.id)
        
        # Cancel child
        job_manager.cancel_job(child.id)
        
        # Parent should be resumed
        assert parent.state == JobState.RUNNING


class TestNestedInterrupt:
    """Test nested interrupt scenarios."""
    
    def test_nested_interrupt(self, interrupt_manager, job_manager):
        """İç içe interrupt çalışır (A → B → C)."""
        # Create chain: A (parent) → B (child of A) → C (child of B)
        job_a = job_manager.create_job("task A")
        job_manager.start_job(job_a.id)
        
        # Interrupt A with B
        job_b = interrupt_manager.interrupt(job_a.id, "task B")
        job_manager.start_job(job_b.id)
        
        # Interrupt B with C
        job_c = interrupt_manager.interrupt(job_b.id, "task C")
        
        assert job_a.state == JobState.PAUSED
        assert job_b.state == JobState.PAUSED
        assert job_c.parent_id == job_b.id
        
        # Complete C → B should resume
        job_manager.start_job(job_c.id)
        job_manager.complete_job(job_c.id, None)
        
        assert job_b.state == JobState.RUNNING
        assert job_a.state == JobState.PAUSED  # Still waiting for B
        
        # Complete B → A should resume
        job_manager.complete_job(job_b.id, None)
        
        assert job_a.state == JobState.RUNNING


class TestInterruptAllRunning:
    """Test interrupt_all_running functionality."""
    
    def test_interrupt_all_running(self, interrupt_manager, job_manager):
        """interrupt_all_running pauses all running jobs."""
        job1 = job_manager.create_job("job1")
        job2 = job_manager.create_job("job2")
        job3 = job_manager.create_job("job3")
        
        job_manager.start_job(job1.id)
        job_manager.start_job(job2.id)
        # job3 stays CREATED
        
        children = interrupt_manager.interrupt_all_running("urgent")
        
        assert len(children) == 2
        assert job1.state == JobState.PAUSED
        assert job2.state == JobState.PAUSED
        assert job3.state == JobState.CREATED


class TestInterruptQueries:
    """Test InterruptManager query methods."""
    
    def test_get_pending_parent(self, interrupt_manager, job_manager):
        """get_pending_parent returns parent ID."""
        parent = job_manager.create_job("parent")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "child")
        
        assert interrupt_manager.get_pending_parent(child.id) == parent.id
    
    def test_has_pending_resume(self, interrupt_manager, job_manager):
        """has_pending_resume detects pending child."""
        parent = job_manager.create_job("parent")
        job_manager.start_job(parent.id)
        
        assert interrupt_manager.has_pending_resume(parent.id) is False
        
        child = interrupt_manager.interrupt(parent.id, "child")
        
        assert interrupt_manager.has_pending_resume(parent.id) is True
    
    def test_pending_count(self, interrupt_manager, job_manager):
        """pending_count tracks pending relationships."""
        parent1 = job_manager.create_job("parent1")
        parent2 = job_manager.create_job("parent2")
        job_manager.start_job(parent1.id)
        job_manager.start_job(parent2.id)
        
        assert interrupt_manager.pending_count == 0
        
        interrupt_manager.interrupt(parent1.id, "child1")
        assert interrupt_manager.pending_count == 1
        
        interrupt_manager.interrupt(parent2.id, "child2")
        assert interrupt_manager.pending_count == 2


class TestInterruptEvents:
    """Test InterruptManager event handling."""
    
    def test_interrupt_emits_event(self, interrupt_manager, job_manager, event_bus):
        """Interrupt emits interrupt event."""
        events = []
        event_bus.subscribe("interrupt", lambda e: events.append(e))
        
        parent = job_manager.create_job("parent")
        job_manager.start_job(parent.id)
        
        child = interrupt_manager.interrupt(parent.id, "child request")
        
        assert len(events) == 1
        assert events[0].data["parent_job_id"] == parent.id
        assert events[0].data["child_job_id"] == child.id
        assert events[0].data["request"] == "child request"
