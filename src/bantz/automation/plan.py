"""
Task Plan module.

Provides data structures for task planning and step tracking.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class StepStatus(Enum):
    """Status of a plan step."""
    
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NEEDS_INPUT = "needs_input"


@dataclass
class PlanStep:
    """A single step in a task plan."""
    
    id: str
    """Unique step ID."""
    
    action: str
    """Action to perform (tool/skill name)."""
    
    description: str
    """Human-readable description."""
    
    parameters: dict = field(default_factory=dict)
    """Parameters for the action."""
    
    status: StepStatus = StepStatus.PENDING
    """Current status."""
    
    result: Optional[Any] = None
    """Result of execution (if success)."""
    
    error: Optional[str] = None
    """Error message (if failed)."""
    
    depends_on: list[str] = field(default_factory=list)
    """IDs of steps this depends on."""
    
    retry_count: int = 0
    """Number of times this step has been retried."""
    
    max_retries: int = 2
    """Maximum retry attempts."""
    
    started_at: Optional[datetime] = None
    """When execution started."""
    
    completed_at: Optional[datetime] = None
    """When execution completed."""
    
    @property
    def can_retry(self) -> bool:
        """Check if step can be retried."""
        return self.retry_count < self.max_retries
    
    @property
    def duration_ms(self) -> float:
        """Get execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000
        return 0.0
    
    def mark_running(self) -> None:
        """Mark step as running."""
        self.status = StepStatus.RUNNING
        self.started_at = datetime.now()
    
    def mark_success(self, result: Any = None) -> None:
        """Mark step as successful."""
        self.status = StepStatus.SUCCESS
        self.result = result
        self.completed_at = datetime.now()
    
    def mark_failed(self, error: str) -> None:
        """Mark step as failed."""
        self.status = StepStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()
    
    def mark_skipped(self, reason: str = "") -> None:
        """Mark step as skipped."""
        self.status = StepStatus.SKIPPED
        self.error = reason or "Skipped by user"
        self.completed_at = datetime.now()
    
    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1
        self.status = StepStatus.PENDING
        self.error = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "action": self.action,
            "description": self.description,
            "parameters": self.parameters,
            "status": self.status.value,
            "result": str(self.result) if self.result else None,
            "error": self.error,
            "depends_on": self.depends_on,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "duration_ms": self.duration_ms,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        """Create from dictionary."""
        step = cls(
            id=data["id"],
            action=data["action"],
            description=data["description"],
            parameters=data.get("parameters", {}),
            depends_on=data.get("depends_on", []),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
        )
        step.status = StepStatus(data.get("status", "pending"))
        step.error = data.get("error")
        return step


class PlanStatus(Enum):
    """Status of a task plan."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class TaskPlan:
    """A complete task plan with multiple steps."""
    
    id: str
    """Unique plan ID."""
    
    goal: str
    """The goal this plan achieves."""
    
    steps: list[PlanStep] = field(default_factory=list)
    """Ordered list of steps."""
    
    status: PlanStatus = PlanStatus.PENDING
    """Current plan status."""
    
    current_step_index: int = 0
    """Index of current/next step."""
    
    created_at: datetime = field(default_factory=datetime.now)
    """When the plan was created."""
    
    started_at: Optional[datetime] = None
    """When execution started."""
    
    completed_at: Optional[datetime] = None
    """When execution completed."""
    
    context: dict = field(default_factory=dict)
    """Execution context (shared data between steps)."""
    
    template_id: Optional[str] = None
    """ID of template used (if any)."""
    
    def __post_init__(self):
        """Generate ID if empty."""
        if not self.id:
            self.id = str(uuid.uuid4())
    
    @property
    def is_complete(self) -> bool:
        """Check if plan is complete."""
        return self.status in (PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED)
    
    @property
    def is_running(self) -> bool:
        """Check if plan is running."""
        return self.status == PlanStatus.RUNNING
    
    @property
    def is_paused(self) -> bool:
        """Check if plan is paused."""
        return self.status == PlanStatus.PAUSED
    
    @property
    def total_steps(self) -> int:
        """Get total number of steps."""
        return len(self.steps)
    
    @property
    def completed_steps(self) -> int:
        """Get number of completed steps."""
        return sum(
            1 for step in self.steps
            if step.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)
        )
    
    @property
    def failed_steps(self) -> int:
        """Get number of failed steps."""
        return sum(1 for step in self.steps if step.status == StepStatus.FAILED)
    
    @property
    def progress_percent(self) -> float:
        """Get completion percentage."""
        if not self.steps:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100
    
    def get_step(self, step_id: str) -> Optional[PlanStep]:
        """Get step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None
    
    def get_next_step(self) -> Optional[PlanStep]:
        """
        Get next step to execute.
        
        Returns next pending step whose dependencies are satisfied.
        """
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue
            
            # Check dependencies
            deps_satisfied = all(
                self._is_step_complete(dep_id)
                for dep_id in step.depends_on
            )
            
            if deps_satisfied:
                return step
        
        return None
    
    def _is_step_complete(self, step_id: str) -> bool:
        """Check if a step is complete (success or skipped)."""
        step = self.get_step(step_id)
        if step is None:
            return True  # Missing dependency = assume satisfied
        return step.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)
    
    def mark_step_complete(self, step_id: str, result: Any = None) -> None:
        """Mark a step as complete."""
        step = self.get_step(step_id)
        if step:
            step.mark_success(result)
            self._update_progress()
    
    def mark_step_failed(self, step_id: str, error: str) -> None:
        """Mark a step as failed."""
        step = self.get_step(step_id)
        if step:
            step.mark_failed(error)
    
    def mark_step_skipped(self, step_id: str, reason: str = "") -> None:
        """Mark a step as skipped."""
        step = self.get_step(step_id)
        if step:
            step.mark_skipped(reason)
            self._update_progress()
    
    def _update_progress(self) -> None:
        """Update progress after step completion."""
        # Check if all steps are done
        all_done = all(
            step.status in (StepStatus.SUCCESS, StepStatus.SKIPPED, StepStatus.FAILED)
            for step in self.steps
        )
        
        if all_done:
            # Check if any failed
            has_failure = any(step.status == StepStatus.FAILED for step in self.steps)
            self.status = PlanStatus.FAILED if has_failure else PlanStatus.COMPLETED
            self.completed_at = datetime.now()
    
    def start(self) -> None:
        """Mark plan as started."""
        self.status = PlanStatus.RUNNING
        self.started_at = datetime.now()
    
    def pause(self) -> None:
        """Pause the plan."""
        self.status = PlanStatus.PAUSED
    
    def resume(self) -> None:
        """Resume the plan."""
        self.status = PlanStatus.RUNNING
    
    def cancel(self) -> None:
        """Cancel the plan."""
        self.status = PlanStatus.CANCELLED
        self.completed_at = datetime.now()
    
    def add_step(
        self,
        action: str,
        description: str,
        parameters: dict = None,
        depends_on: list[str] = None,
    ) -> PlanStep:
        """Add a step to the plan."""
        step = PlanStep(
            id=f"step-{len(self.steps) + 1}",
            action=action,
            description=description,
            parameters=parameters or {},
            depends_on=depends_on or [],
        )
        self.steps.append(step)
        return step
    
    def get_summary(self) -> str:
        """Get a summary of the plan."""
        lines = [f"Plan: {self.goal}"]
        lines.append(f"Status: {self.status.value}")
        lines.append(f"Progress: {self.progress_percent:.1f}%")
        lines.append("Steps:")
        
        for i, step in enumerate(self.steps, 1):
            status_icon = {
                StepStatus.PENDING: "⏳",
                StepStatus.RUNNING: "🔄",
                StepStatus.SUCCESS: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⏭️",
                StepStatus.NEEDS_INPUT: "❓",
            }.get(step.status, "•")
            
            lines.append(f"  {i}. {status_icon} {step.description}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "context": self.context,
            "template_id": self.template_id,
            "progress_percent": self.progress_percent,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TaskPlan":
        """Create from dictionary."""
        plan = cls(
            id=data["id"],
            goal=data["goal"],
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            context=data.get("context", {}),
            template_id=data.get("template_id"),
        )
        plan.status = PlanStatus(data.get("status", "pending"))
        plan.current_step_index = data.get("current_step_index", 0)
        return plan


def create_task_plan(goal: str, steps: list[dict] = None) -> TaskPlan:
    """
    Factory function to create a task plan.
    
    Args:
        goal: The goal to achieve.
        steps: Optional list of step definitions.
        
    Returns:
        New TaskPlan instance.
    """
    plan = TaskPlan(
        id=str(uuid.uuid4()),
        goal=goal,
    )
    
    if steps:
        for step_def in steps:
            plan.add_step(
                action=step_def.get("action", "unknown"),
                description=step_def.get("description", step_def.get("action", "")),
                parameters=step_def.get("parameters", {}),
                depends_on=step_def.get("depends_on", []),
            )
    
    return plan
