"""
PEV (Planner-Executor-Verifier) Orchestrator module.

Coordinates the full PEV loop for agentic automation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol

from bantz.automation.plan import TaskPlan, PlanStep, PlanStatus, StepStatus, create_task_plan
from bantz.automation.planner import Planner
from bantz.automation.executor import Executor, ExecutionResult, ExecutorState
from bantz.automation.verifier import Verifier, VerificationResult
from bantz.automation.failsafe import FailSafeHandler, FailSafeChoice, FailSafeAction


class EventBus(Protocol):
    """Protocol for event bus."""
    
    async def emit(self, event: str, data: dict) -> None:
        """Emit an event."""
        ...


class PEVState(Enum):
    """State of the PEV orchestrator."""
    
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    HANDLING_FAILURE = "handling_failure"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PEVResult:
    """Result of PEV execution."""
    
    plan: TaskPlan
    """The executed plan."""
    
    success: bool
    """Overall success status."""
    
    completed_steps: int
    """Number of completed steps."""
    
    failed_steps: int
    """Number of failed steps."""
    
    skipped_steps: int
    """Number of skipped steps."""
    
    duration_ms: int
    """Total duration in milliseconds."""
    
    verification_results: list[VerificationResult] = field(default_factory=list)
    """Verification results for each step."""
    
    failure_choices: list[FailSafeChoice] = field(default_factory=list)
    """User choices made during failures."""
    
    error: Optional[str] = None
    """Error message if failed."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "plan_id": self.plan.id,
            "goal": self.plan.goal,
            "success": self.success,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "duration_ms": self.duration_ms,
            "verification_results": [v.to_dict() for v in self.verification_results],
            "failure_choices": [f.to_dict() for f in self.failure_choices],
            "error": self.error,
        }


class PEVOrchestrator:
    """
    Orchestrates the Planner-Executor-Verifier loop.
    
    Flow:
    1. Plan: Create plan from goal (using templates or LLM)
    2. Execute: Execute each step
    3. Verify: Verify step completion
    4. Handle failures: Ask user on consecutive failures
    5. Report: Return final result
    """
    
    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        failsafe: FailSafeHandler,
        event_bus: Optional[EventBus] = None,
        auto_verify: bool = True,
        verify_threshold: float = 0.7,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            planner: Planner instance.
            executor: Executor instance.
            verifier: Verifier instance.
            failsafe: Fail-safe handler instance.
            event_bus: Optional event bus.
            auto_verify: Whether to auto-verify steps.
            verify_threshold: Minimum verification confidence.
        """
        self._planner = planner
        self._executor = executor
        self._verifier = verifier
        self._failsafe = failsafe
        self._event_bus = event_bus
        self._auto_verify = auto_verify
        self._verify_threshold = verify_threshold
        
        self._state = PEVState.IDLE
        self._current_plan: Optional[TaskPlan] = None
        self._verification_results: list[VerificationResult] = []
        self._failure_choices: list[FailSafeChoice] = []
        self._start_time: Optional[datetime] = None
    
    @property
    def state(self) -> PEVState:
        """Get current state."""
        return self._state
    
    @property
    def current_plan(self) -> Optional[TaskPlan]:
        """Get current plan."""
        return self._current_plan
    
    @property
    def is_running(self) -> bool:
        """Check if orchestrator is running."""
        return self._state in (
            PEVState.PLANNING,
            PEVState.EXECUTING,
            PEVState.VERIFYING,
            PEVState.HANDLING_FAILURE,
        )
    
    async def run(self, goal: str, context: Optional[dict] = None) -> PEVResult:
        """
        Run the full PEV loop for a goal.
        
        Args:
            goal: User's goal.
            context: Optional context.
            
        Returns:
            PEVResult with execution details.
        """
        self._start_time = datetime.now()
        self._verification_results = []
        self._failure_choices = []
        
        try:
            # Phase 1: Planning
            self._state = PEVState.PLANNING
            await self._emit("pev_planning_started", {"goal": goal})
            
            plan = await self._planner.create_plan(goal, context)
            if not plan:
                return self._create_failed_result(
                    create_task_plan(goal, []),
                    "Failed to create plan",
                )
            
            self._current_plan = plan
            await self._emit("pev_plan_created", {"plan_id": plan.id, "steps": len(plan.steps)})
            
            # Phase 2-4: Execute with verification
            return await self._execute_plan(plan)
            
        except Exception as e:
            self._state = PEVState.FAILED
            return self._create_failed_result(
                self._current_plan or create_task_plan(goal, []),
                str(e),
            )
    
    async def run_with_plan(self, plan: TaskPlan) -> PEVResult:
        """
        Run with a pre-created plan.
        
        Args:
            plan: Pre-created plan.
            
        Returns:
            PEVResult with execution details.
        """
        self._start_time = datetime.now()
        self._verification_results = []
        self._failure_choices = []
        self._current_plan = plan
        
        try:
            return await self._execute_plan(plan)
        except Exception as e:
            self._state = PEVState.FAILED
            return self._create_failed_result(plan, str(e))
    
    async def _execute_plan(self, plan: TaskPlan) -> PEVResult:
        """Execute a plan with verification and fail-safe."""
        self._state = PEVState.EXECUTING
        plan.start()
        
        await self._emit("pev_execution_started", {"plan_id": plan.id})
        
        consecutive_failures = 0
        
        while True:
            # Get next step
            step = plan.get_next_step()
            if not step:
                break
            
            # Execute step
            result = await self._executor.execute_step(plan, step)
            
            if result.success:
                consecutive_failures = 0
                
                # Verify if enabled
                if self._auto_verify:
                    self._state = PEVState.VERIFYING
                    verification = await self._verifier.verify_step(step, result.result)
                    self._verification_results.append(verification)
                    
                    if not verification.verified or verification.confidence < self._verify_threshold:
                        # Verification failed - treat as step failure
                        consecutive_failures += 1
                        plan.mark_step_failed(step.id, "Verification failed")
                        
                        if self._failsafe.should_ask_user(consecutive_failures):
                            choice = await self._handle_failure(
                                plan, step, "Verification failed", consecutive_failures
                            )
                            
                            if choice.action == FailSafeAction.ABORT:
                                plan.cancel()
                                break
                            elif choice.action == FailSafeAction.SKIP:
                                step.mark_skipped()
                                consecutive_failures = 0
                            elif choice.action == FailSafeAction.MANUAL:
                                await self._failsafe.wait_for_manual_completion()
                                step.mark_success({"manual": True})
                                consecutive_failures = 0
                    else:
                        plan.mark_step_complete(step.id, result.result)
                else:
                    plan.mark_step_complete(step.id, result.result)
                
                self._state = PEVState.EXECUTING
                
            else:
                consecutive_failures += 1
                
                # Handle failure
                if self._failsafe.should_ask_user(consecutive_failures):
                    choice = await self._handle_failure(
                        plan, step, result.error or "Unknown error", consecutive_failures
                    )
                    
                    if choice.action == FailSafeAction.ABORT:
                        plan.cancel()
                        break
                    elif choice.action == FailSafeAction.SKIP:
                        step.mark_skipped()
                        consecutive_failures = 0
                    elif choice.action == FailSafeAction.RETRY:
                        # Retry - don't mark as complete, will be picked up again
                        step.status = StepStatus.PENDING
                        await self._failsafe.notify_retry()
                    elif choice.action == FailSafeAction.MANUAL:
                        await self._failsafe.notify_manual()
                        await self._failsafe.wait_for_manual_completion()
                        step.mark_success({"manual": True})
                        consecutive_failures = 0
                else:
                    # Auto-retry
                    step.increment_retry()
                    if not step.can_retry:
                        step.mark_failed(result.error or "Max retries exceeded")
        
        # Determine final status
        if plan.status == PlanStatus.CANCELLED:
            self._state = PEVState.CANCELLED
        elif plan.is_complete:
            self._state = PEVState.COMPLETED
        else:
            self._state = PEVState.FAILED
        
        result = self._create_result(plan)
        await self._emit("pev_completed", result.to_dict())
        
        return result
    
    async def _handle_failure(
        self,
        plan: TaskPlan,
        step: PlanStep,
        error: str,
        consecutive_failures: int,
    ) -> FailSafeChoice:
        """Handle step failure with user interaction."""
        self._state = PEVState.HANDLING_FAILURE
        
        await self._emit("pev_failure", {
            "plan_id": plan.id,
            "step_id": step.id,
            "error": error,
            "consecutive_failures": consecutive_failures,
        })
        
        choice = await self._failsafe.handle_failure(
            plan, step, error, consecutive_failures
        )
        
        self._failure_choices.append(choice)
        
        await self._emit("pev_failure_choice", {
            "plan_id": plan.id,
            "step_id": step.id,
            "action": choice.action.value,
        })
        
        return choice
    
    async def pause(self) -> None:
        """Pause execution."""
        if self._current_plan and self._executor.is_running:
            await self._executor.pause()
            if self._current_plan:
                self._current_plan.pause()
            await self._emit("pev_paused", {"plan_id": self._current_plan.id if self._current_plan else None})
    
    async def resume(self) -> None:
        """Resume execution."""
        if self._current_plan and self._executor.is_paused:
            await self._executor.resume()
            if self._current_plan:
                self._current_plan.resume()
            await self._emit("pev_resumed", {"plan_id": self._current_plan.id if self._current_plan else None})
    
    async def cancel(self) -> None:
        """Cancel execution."""
        if self._current_plan:
            await self._executor.cancel()
            self._current_plan.cancel()
            self._state = PEVState.CANCELLED
            await self._emit("pev_cancelled", {"plan_id": self._current_plan.id})
    
    def _create_result(self, plan: TaskPlan) -> PEVResult:
        """Create result from plan."""
        duration_ms = 0
        if self._start_time:
            duration_ms = int((datetime.now() - self._start_time).total_seconds() * 1000)
        
        completed = len([s for s in plan.steps if s.status == StepStatus.SUCCESS])
        failed = len([s for s in plan.steps if s.status == StepStatus.FAILED])
        skipped = len([s for s in plan.steps if s.status == StepStatus.SKIPPED])
        
        success = plan.status == PlanStatus.COMPLETED or (
            completed > 0 and failed == 0
        )
        
        return PEVResult(
            plan=plan,
            success=success,
            completed_steps=completed,
            failed_steps=failed,
            skipped_steps=skipped,
            duration_ms=duration_ms,
            verification_results=list(self._verification_results),
            failure_choices=list(self._failure_choices),
        )
    
    def _create_failed_result(self, plan: TaskPlan, error: str) -> PEVResult:
        """Create failed result."""
        duration_ms = 0
        if self._start_time:
            duration_ms = int((datetime.now() - self._start_time).total_seconds() * 1000)
        
        return PEVResult(
            plan=plan,
            success=False,
            completed_steps=0,
            failed_steps=len(plan.steps),
            skipped_steps=0,
            duration_ms=duration_ms,
            verification_results=[],
            failure_choices=[],
            error=error,
        )
    
    async def _emit(self, event: str, data: dict) -> None:
        """Emit event if event bus available."""
        if self._event_bus:
            await self._event_bus.emit(event, data)


def create_pev_orchestrator(
    planner: Planner,
    executor: Executor,
    verifier: Verifier,
    failsafe: FailSafeHandler,
    event_bus: Optional[EventBus] = None,
    auto_verify: bool = True,
    verify_threshold: float = 0.7,
) -> PEVOrchestrator:
    """
    Factory function to create a PEV orchestrator.
    
    Args:
        planner: Planner instance.
        executor: Executor instance.
        verifier: Verifier instance.
        failsafe: Fail-safe handler instance.
        event_bus: Optional event bus.
        auto_verify: Whether to auto-verify steps.
        verify_threshold: Minimum verification confidence.
        
    Returns:
        Configured PEVOrchestrator instance.
    """
    return PEVOrchestrator(
        planner=planner,
        executor=executor,
        verifier=verifier,
        failsafe=failsafe,
        event_bus=event_bus,
        auto_verify=auto_verify,
        verify_threshold=verify_threshold,
    )
