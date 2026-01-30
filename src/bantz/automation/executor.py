"""
Executor module.

Executes task plan steps with pause/resume/cancel support.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Protocol


from bantz.automation.plan import TaskPlan, PlanStep, StepStatus, PlanStatus


class ToolRuntime(Protocol):
    """Protocol for tool execution runtime."""
    
    async def execute(self, action: str, parameters: dict) -> Any:
        """Execute an action with parameters."""
        ...


class EventBus(Protocol):
    """Protocol for event bus."""
    
    async def emit(self, event: str, data: dict) -> None:
        """Emit an event."""
        ...


class ExecutorState(Enum):
    """Executor state."""
    
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class ExecutionResult:
    """Result of executing a step."""
    
    step_id: str
    """ID of the executed step."""
    
    success: bool
    """Whether execution succeeded."""
    
    result: Optional[Any] = None
    """Result value (if success)."""
    
    error: Optional[str] = None
    """Error message (if failed)."""
    
    duration_ms: float = 0.0
    """Execution duration in milliseconds."""
    
    retry_count: int = 0
    """Number of retries attempted."""
    
    timestamp: datetime = field(default_factory=datetime.now)
    """When execution completed."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "step_id": self.step_id,
            "success": self.success,
            "result": str(self.result) if self.result else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp.isoformat(),
        }


class Executor:
    """
    Executes task plan steps.
    
    Supports pause, resume, and cancel operations.
    """
    
    def __init__(
        self,
        tool_runtime: Optional[ToolRuntime] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the executor.
        
        Args:
            tool_runtime: Runtime for executing tool actions.
            event_bus: Event bus for progress notifications.
        """
        self._runtime = tool_runtime
        self._event_bus = event_bus
        self._state = ExecutorState.IDLE
        self._current_plan: Optional[TaskPlan] = None
        self._current_step: Optional[PlanStep] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially
        self._cancel_requested = False
        self._results: list[ExecutionResult] = []
        self._consecutive_failures = 0
    
    @property
    def is_running(self) -> bool:
        """Check if executor is running."""
        return self._state == ExecutorState.RUNNING
    
    @property
    def is_paused(self) -> bool:
        """Check if executor is paused."""
        return self._state == ExecutorState.PAUSED
    
    @property
    def is_cancelled(self) -> bool:
        """Check if execution was cancelled."""
        return self._cancel_requested
    
    @property
    def current_plan(self) -> Optional[TaskPlan]:
        """Get current plan being executed."""
        return self._current_plan
    
    @property
    def current_step(self) -> Optional[PlanStep]:
        """Get current step being executed."""
        return self._current_step
    
    @property
    def consecutive_failures(self) -> int:
        """Get consecutive failure count."""
        return self._consecutive_failures
    
    async def execute_step(self, step: PlanStep) -> ExecutionResult:
        """
        Execute a single step.
        
        Args:
            step: Step to execute.
            
        Returns:
            Execution result.
        """
        self._current_step = step
        start_time = datetime.now()
        
        step.mark_running()
        
        # Emit step started event
        await self._emit_event("step_started", {
            "step_id": step.id,
            "action": step.action,
            "description": step.description,
        })
        
        try:
            # Execute the action
            if self._runtime:
                result_value = await self._runtime.execute(
                    step.action,
                    step.parameters,
                )
            else:
                # Mock execution without runtime
                result_value = {"status": "simulated", "action": step.action}
            
            end_time = datetime.now()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            
            step.mark_success(result_value)
            self._consecutive_failures = 0
            
            result = ExecutionResult(
                step_id=step.id,
                success=True,
                result=result_value,
                duration_ms=duration_ms,
                retry_count=step.retry_count,
            )
            
            await self._emit_event("step_completed", {
                "step_id": step.id,
                "success": True,
                "duration_ms": duration_ms,
            })
            
        except Exception as e:
            end_time = datetime.now()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            
            error_msg = str(e)
            step.mark_failed(error_msg)
            self._consecutive_failures += 1
            
            result = ExecutionResult(
                step_id=step.id,
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
                retry_count=step.retry_count,
            )
            
            await self._emit_event("step_failed", {
                "step_id": step.id,
                "error": error_msg,
                "consecutive_failures": self._consecutive_failures,
            })
        
        self._current_step = None
        return result
    
    async def execute_plan(
        self,
        plan: TaskPlan,
        on_step_complete: Optional[Callable[[ExecutionResult], None]] = None,
    ) -> list[ExecutionResult]:
        """
        Execute an entire plan.
        
        Args:
            plan: Plan to execute.
            on_step_complete: Callback for each step completion.
            
        Returns:
            List of execution results.
        """
        self._current_plan = plan
        self._state = ExecutorState.RUNNING
        self._cancel_requested = False
        self._results = []
        self._consecutive_failures = 0
        
        plan.start()
        
        await self._emit_event("plan_started", {
            "plan_id": plan.id,
            "goal": plan.goal,
            "total_steps": plan.total_steps,
        })
        
        try:
            while True:
                # Check for cancellation
                if self._cancel_requested:
                    plan.cancel()
                    break
                
                # Wait if paused
                await self._pause_event.wait()
                
                # Get next step
                next_step = plan.get_next_step()
                if next_step is None:
                    # No more steps
                    break
                
                # Execute step
                result = await self.execute_step(next_step)
                self._results.append(result)
                
                # Call callback
                if on_step_complete:
                    on_step_complete(result)
                
                # Handle failure
                if not result.success:
                    # Check if we should continue or need intervention
                    # This is handled by fail-safe handler externally
                    break
            
            # Update plan status
            if not self._cancel_requested:
                plan._update_progress()
            
            await self._emit_event("plan_completed", {
                "plan_id": plan.id,
                "status": plan.status.value,
                "progress": plan.progress_percent,
            })
            
        finally:
            self._state = ExecutorState.IDLE
            self._current_plan = None
        
        return self._results
    
    async def pause(self) -> None:
        """Pause execution."""
        if self._state == ExecutorState.RUNNING:
            self._state = ExecutorState.PAUSED
            self._pause_event.clear()
            
            if self._current_plan:
                self._current_plan.pause()
            
            await self._emit_event("execution_paused", {
                "plan_id": self._current_plan.id if self._current_plan else None,
            })
    
    async def resume(self) -> None:
        """Resume execution."""
        if self._state == ExecutorState.PAUSED:
            self._state = ExecutorState.RUNNING
            self._pause_event.set()
            
            if self._current_plan:
                self._current_plan.resume()
            
            await self._emit_event("execution_resumed", {
                "plan_id": self._current_plan.id if self._current_plan else None,
            })
    
    async def cancel(self) -> None:
        """Cancel execution."""
        self._cancel_requested = True
        self._pause_event.set()  # Unblock if paused
        self._state = ExecutorState.CANCELLED
        
        await self._emit_event("execution_cancelled", {
            "plan_id": self._current_plan.id if self._current_plan else None,
        })
    
    def reset_failure_count(self) -> None:
        """Reset consecutive failure count."""
        self._consecutive_failures = 0
    
    async def retry_step(self, step: PlanStep) -> ExecutionResult:
        """
        Retry a failed step.
        
        Args:
            step: Step to retry.
            
        Returns:
            Execution result.
        """
        step.increment_retry()
        return await self.execute_step(step)
    
    async def _emit_event(self, event: str, data: dict) -> None:
        """Emit an event to the event bus."""
        if self._event_bus:
            await self._event_bus.emit(f"executor.{event}", data)
    
    def get_results(self) -> list[ExecutionResult]:
        """Get all execution results."""
        return list(self._results)


def create_executor(
    tool_runtime: Optional[ToolRuntime] = None,
    event_bus: Optional[EventBus] = None,
) -> Executor:
    """
    Factory function to create an executor.
    
    Args:
        tool_runtime: Runtime for executing tool actions.
        event_bus: Event bus for progress notifications.
        
    Returns:
        Configured Executor instance.
    """
    return Executor(
        tool_runtime=tool_runtime,
        event_bus=event_bus,
    )
