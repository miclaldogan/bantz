"""
Tests for plan module.
"""

import pytest
from bantz.automation.plan import (
    StepStatus,
    PlanStep,
    PlanStatus,
    TaskPlan,
    create_task_plan,
)


class TestStepStatus:
    """Tests for StepStatus enum."""
    
    def test_step_status_values(self):
        """Test all status values exist."""
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.RUNNING.value == "running"
        assert StepStatus.SUCCESS.value == "success"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.NEEDS_INPUT.value == "needs_input"


class TestPlanStep:
    """Tests for PlanStep dataclass."""
    
    def test_create_step(self):
        """Test creating a basic step."""
        step = PlanStep(
            id="step_1",
            action="open_browser",
            description="Open the browser",
        )
        
        assert step.id == "step_1"
        assert step.action == "open_browser"
        assert step.description == "Open the browser"
        assert step.status == StepStatus.PENDING
        assert step.parameters == {}
        assert step.depends_on == []
        assert step.retry_count == 0
    
    def test_mark_running(self):
        """Test marking step as running."""
        step = PlanStep(id="s1", action="test", description="Test")
        step.mark_running()
        
        assert step.status == StepStatus.RUNNING
        assert step.started_at is not None
    
    def test_mark_success(self):
        """Test marking step as successful."""
        step = PlanStep(id="s1", action="test", description="Test")
        step.mark_running()
        step.mark_success({"data": "result"})
        
        assert step.status == StepStatus.SUCCESS
        assert step.result == {"data": "result"}
        assert step.completed_at is not None
    
    def test_mark_failed(self):
        """Test marking step as failed."""
        step = PlanStep(id="s1", action="test", description="Test")
        step.mark_running()
        step.mark_failed("Something went wrong")
        
        assert step.status == StepStatus.FAILED
        assert step.error == "Something went wrong"
    
    def test_mark_skipped(self):
        """Test marking step as skipped."""
        step = PlanStep(id="s1", action="test", description="Test")
        step.mark_skipped()
        
        assert step.status == StepStatus.SKIPPED
    
    def test_retry_count(self):
        """Test retry counting."""
        step = PlanStep(id="s1", action="test", description="Test", max_retries=3)
        
        assert step.can_retry
        step.increment_retry()
        assert step.retry_count == 1
        assert step.can_retry
        
        step.increment_retry()
        step.increment_retry()
        assert step.retry_count == 3
        assert not step.can_retry
    
    def test_duration_ms(self):
        """Test duration calculation."""
        step = PlanStep(id="s1", action="test", description="Test")
        
        # Duration is 0.0 before running
        assert step.duration_ms == 0.0
        
        step.mark_running()
        step.mark_success({})
        
        # Duration should be calculated
        assert step.duration_ms >= 0
    
    def test_to_dict(self):
        """Test serialization."""
        step = PlanStep(
            id="s1",
            action="test",
            description="Test step",
            parameters={"key": "value"},
        )
        
        d = step.to_dict()
        assert d["id"] == "s1"
        assert d["action"] == "test"
        assert d["description"] == "Test step"
        assert d["parameters"] == {"key": "value"}
        assert d["status"] == "pending"


class TestPlanStatus:
    """Tests for PlanStatus enum."""
    
    def test_plan_status_values(self):
        """Test all status values exist."""
        assert PlanStatus.PENDING.value == "pending"
        assert PlanStatus.RUNNING.value == "running"
        assert PlanStatus.COMPLETED.value == "completed"
        assert PlanStatus.FAILED.value == "failed"
        assert PlanStatus.PAUSED.value == "paused"
        assert PlanStatus.CANCELLED.value == "cancelled"


class TestTaskPlan:
    """Tests for TaskPlan dataclass."""
    
    def test_create_plan(self):
        """Test creating a plan."""
        steps = [
            PlanStep(id="s1", action="a1", description="Step 1"),
            PlanStep(id="s2", action="a2", description="Step 2"),
        ]
        
        plan = TaskPlan(
            id="plan_1",
            goal="Test goal",
            steps=steps,
        )
        
        assert plan.id == "plan_1"
        assert plan.goal == "Test goal"
        assert len(plan.steps) == 2
        assert plan.status == PlanStatus.PENDING
    
    def test_factory_function(self):
        """Test create_task_plan factory."""
        steps = [
            {"action": "open", "description": "Open file"},
            {"action": "edit", "description": "Edit file"},
        ]
        
        plan = create_task_plan("Edit a file", steps)
        
        assert plan.goal == "Edit a file"
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "open"
        assert plan.steps[1].action == "edit"
    
    def test_start_plan(self):
        """Test starting a plan."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        
        plan.start()
        
        assert plan.status == PlanStatus.RUNNING
        assert plan.started_at is not None
    
    def test_get_next_step(self):
        """Test getting next executable step."""
        steps = [
            {"action": "a1", "description": "Step 1"},
            {"action": "a2", "description": "Step 2"},
        ]
        plan = create_task_plan("Test", steps)
        plan.start()
        
        step = plan.get_next_step()
        assert step is not None
        assert step.action == "a1"
    
    def test_mark_step_complete(self):
        """Test marking step as complete."""
        steps = [
            {"action": "a1", "description": "Step 1"},
            {"action": "a2", "description": "Step 2"},
        ]
        plan = create_task_plan("Test", steps)
        plan.start()
        
        step = plan.get_next_step()
        plan.mark_step_complete(step.id, {"done": True})
        
        assert step.status == StepStatus.SUCCESS
        assert step.result == {"done": True}
        
        # Next step should be step 2
        next_step = plan.get_next_step()
        assert next_step.action == "a2"
    
    def test_mark_step_failed(self):
        """Test marking step as failed."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        plan.start()
        
        step = plan.get_next_step()
        plan.mark_step_failed(step.id, "Error occurred")
        
        assert step.status == StepStatus.FAILED
        assert step.error == "Error occurred"
    
    def test_pause_resume(self):
        """Test pausing and resuming."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        plan.start()
        
        plan.pause()
        assert plan.status == PlanStatus.PAUSED
        
        plan.resume()
        assert plan.status == PlanStatus.RUNNING
    
    def test_cancel(self):
        """Test cancelling."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        plan.start()
        
        plan.cancel()
        assert plan.status == PlanStatus.CANCELLED
    
    def test_is_complete(self):
        """Test completion check."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        plan.start()
        
        assert not plan.is_complete
        
        step = plan.get_next_step()
        plan.mark_step_complete(step.id, {})
        
        assert plan.is_complete
    
    def test_progress_percent(self):
        """Test progress calculation."""
        steps = [
            {"action": "a1", "description": "Step 1"},
            {"action": "a2", "description": "Step 2"},
            {"action": "a3", "description": "Step 3"},
            {"action": "a4", "description": "Step 4"},
        ]
        plan = create_task_plan("Test", steps)
        plan.start()
        
        assert plan.progress_percent == 0.0
        
        step1 = plan.get_next_step()
        plan.mark_step_complete(step1.id, {})
        assert plan.progress_percent == 25.0
        
        step2 = plan.get_next_step()
        plan.mark_step_complete(step2.id, {})
        assert plan.progress_percent == 50.0
    
    def test_completed_failed_steps(self):
        """Test counting completed and failed steps."""
        steps = [
            {"action": "a1", "description": "Step 1"},
            {"action": "a2", "description": "Step 2"},
            {"action": "a3", "description": "Step 3"},
        ]
        plan = create_task_plan("Test", steps)
        plan.start()
        
        step1 = plan.get_next_step()
        plan.mark_step_complete(step1.id, {})
        
        step2 = plan.get_next_step()
        plan.mark_step_failed(step2.id, "Error")
        
        assert plan.completed_steps == 1
        assert plan.failed_steps == 1
    
    def test_add_step(self):
        """Test adding step dynamically."""
        plan = create_task_plan("Test", [{"action": "a1", "description": "Step 1"}])
        
        plan.add_step(action="a2", description="Step 2")
        
        assert len(plan.steps) == 2
    
    def test_to_dict(self):
        """Test serialization."""
        plan = create_task_plan("Test goal", [{"action": "a", "description": "A"}])
        
        d = plan.to_dict()
        assert d["goal"] == "Test goal"
        assert len(d["steps"]) == 1
        assert d["status"] == "pending"
