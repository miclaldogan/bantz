"""
Tests for Job State Machine (Issue #31 - V2-1).

Tests the Job dataclass, JobState enum, and state transitions.
"""

import pytest
from datetime import datetime
import time

from bantz.core.job import (
    Job,
    JobState,
    InvalidTransitionError,
    TRANSITIONS,
    FINAL_STATES,
)


class TestJobState:
    """Test JobState enum values."""
    
    def test_job_state_created_value(self):
        """JobState.CREATED has correct value."""
        assert JobState.CREATED.value == "created"
    
    def test_job_state_running_value(self):
        """JobState.RUNNING has correct value."""
        assert JobState.RUNNING.value == "running"
    
    def test_job_state_paused_value(self):
        """JobState.PAUSED has correct value."""
        assert JobState.PAUSED.value == "paused"
    
    def test_job_state_done_value(self):
        """JobState.DONE has correct value."""
        assert JobState.DONE.value == "done"
    
    def test_job_state_failed_value(self):
        """JobState.FAILED has correct value."""
        assert JobState.FAILED.value == "failed"
    
    def test_job_state_cancelled_value(self):
        """JobState.CANCELLED has correct value."""
        assert JobState.CANCELLED.value == "cancelled"


class TestJobCreation:
    """Test Job creation and initial state."""
    
    def test_job_initial_state_created(self):
        """Yeni job CREATED state'inde başlar."""
        job = Job.create("test request")
        assert job.state == JobState.CREATED
    
    def test_job_create_has_id(self):
        """Job.create generates unique ID."""
        job = Job.create("test")
        assert job.id is not None
        assert len(job.id) == 36  # UUID format
    
    def test_job_create_stores_request(self):
        """Job.create stores request."""
        job = Job.create("search for news")
        assert job.request == "search for news"
    
    def test_job_create_default_priority(self):
        """Job.create default priority is 0."""
        job = Job.create("test")
        assert job.priority == 0
    
    def test_job_create_custom_priority(self):
        """Job.create accepts custom priority."""
        job = Job.create("test", priority=10)
        assert job.priority == 10
    
    def test_job_create_with_parent_id(self):
        """Job.create accepts parent_id."""
        job = Job.create("child task", parent_id="parent-123")
        assert job.parent_id == "parent-123"
    
    def test_job_create_with_metadata(self):
        """Job.create accepts metadata."""
        job = Job.create("test", metadata={"key": "value"})
        assert job.metadata == {"key": "value"}
    
    def test_job_create_has_timestamp(self):
        """Job.create sets created_at."""
        before = datetime.now()
        job = Job.create("test")
        after = datetime.now()
        assert before <= job.created_at <= after


class TestJobTransitions:
    """Test Job state transitions."""
    
    def test_job_transition_created_running(self):
        """CREATED → RUNNING geçerli."""
        job = Job.create("test")
        assert job.can_transition_to(JobState.RUNNING)
        job.transition_to(JobState.RUNNING)
        assert job.state == JobState.RUNNING
    
    def test_job_transition_running_paused(self):
        """RUNNING → PAUSED geçerli ('bekle')."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.can_transition_to(JobState.PAUSED)
        job.transition_to(JobState.PAUSED)
        assert job.state == JobState.PAUSED
    
    def test_job_transition_paused_running(self):
        """PAUSED → RUNNING geçerli ('devam et')."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        job.transition_to(JobState.PAUSED)
        assert job.can_transition_to(JobState.RUNNING)
        job.transition_to(JobState.RUNNING)
        assert job.state == JobState.RUNNING
    
    def test_job_transition_running_waiting(self):
        """RUNNING → WAITING_USER geçerli."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.can_transition_to(JobState.WAITING_USER)
        job.transition_to(JobState.WAITING_USER)
        assert job.state == JobState.WAITING_USER
    
    def test_job_transition_running_done(self):
        """RUNNING → DONE geçerli."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.can_transition_to(JobState.DONE)
        job.transition_to(JobState.DONE)
        assert job.state == JobState.DONE
    
    def test_job_transition_running_failed(self):
        """RUNNING → FAILED geçerli."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.can_transition_to(JobState.FAILED)
        job.transition_to(JobState.FAILED)
        assert job.state == JobState.FAILED
    
    def test_job_transition_running_verifying(self):
        """RUNNING → VERIFYING geçerli."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.can_transition_to(JobState.VERIFYING)
        job.transition_to(JobState.VERIFYING)
        assert job.state == JobState.VERIFYING
    
    def test_job_invalid_transition_done_running(self):
        """DONE → RUNNING geçersiz, hata fırlatır."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        job.transition_to(JobState.DONE)
        
        assert not job.can_transition_to(JobState.RUNNING)
        with pytest.raises(InvalidTransitionError) as exc_info:
            job.transition_to(JobState.RUNNING)
        
        assert exc_info.value.from_state == JobState.DONE
        assert exc_info.value.to_state == JobState.RUNNING
    
    def test_job_invalid_transition_failed_running(self):
        """FAILED → RUNNING geçersiz."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        job.transition_to(JobState.FAILED)
        
        assert not job.can_transition_to(JobState.RUNNING)
        with pytest.raises(InvalidTransitionError):
            job.transition_to(JobState.RUNNING)
    
    def test_job_invalid_transition_created_done(self):
        """CREATED → DONE geçersiz (RUNNING atlanmaz)."""
        job = Job.create("test")
        assert not job.can_transition_to(JobState.DONE)
        with pytest.raises(InvalidTransitionError):
            job.transition_to(JobState.DONE)


class TestJobProperties:
    """Test Job properties and computed values."""
    
    def test_job_is_active_when_created(self):
        """CREATED state is active."""
        job = Job.create("test")
        assert job.is_active is True
        assert job.is_final is False
    
    def test_job_is_active_when_running(self):
        """RUNNING state is active."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.is_active is True
    
    def test_job_is_final_when_done(self):
        """DONE state is final."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        job.transition_to(JobState.DONE)
        assert job.is_final is True
        assert job.is_active is False
    
    def test_job_is_running_property(self):
        """is_running property works."""
        job = Job.create("test")
        assert job.is_running is False
        job.transition_to(JobState.RUNNING)
        assert job.is_running is True
    
    def test_job_is_paused_property(self):
        """is_paused property works."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.is_paused is False
        job.transition_to(JobState.PAUSED)
        assert job.is_paused is True
    
    def test_job_duration_none_before_start(self):
        """Duration is None before job starts."""
        job = Job.create("test")
        assert job.duration_ms is None
    
    def test_job_duration_after_start(self):
        """Duration is calculated after job starts."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        time.sleep(0.01)  # 10ms
        duration = job.duration_ms
        assert duration is not None
        assert duration >= 10  # At least 10ms
    
    def test_job_started_at_set_on_running(self):
        """started_at is set when transitioning to RUNNING."""
        job = Job.create("test")
        assert job.started_at is None
        job.transition_to(JobState.RUNNING)
        assert job.started_at is not None
    
    def test_job_completed_at_set_on_final(self):
        """completed_at is set when transitioning to final state."""
        job = Job.create("test")
        job.transition_to(JobState.RUNNING)
        assert job.completed_at is None
        job.transition_to(JobState.DONE)
        assert job.completed_at is not None


class TestTransitionsMap:
    """Test TRANSITIONS map configuration."""
    
    def test_all_states_in_transitions(self):
        """All states have entries in TRANSITIONS."""
        for state in JobState:
            assert state in TRANSITIONS
    
    def test_final_states_have_no_transitions(self):
        """Final states have empty transition lists."""
        for state in FINAL_STATES:
            assert TRANSITIONS[state] == []
    
    def test_final_states_set(self):
        """FINAL_STATES contains correct states."""
        assert JobState.DONE in FINAL_STATES
        assert JobState.FAILED in FINAL_STATES
        assert JobState.CANCELLED in FINAL_STATES
        assert len(FINAL_STATES) == 3
