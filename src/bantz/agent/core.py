from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .planner import PlannedStep, Planner
from .executor import Executor, ExecutionResult
from .recovery import RecoveryPolicy
from .verifier import Verifier
from .tools import ToolRegistry


class AgentState(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_CONFIRMATION = "waiting_confirmation"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Step:
    id: int
    action: str
    params: dict[str, Any]
    description: str
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class Task:
    id: str
    original_request: str
    steps: list[Step] = field(default_factory=list)
    current_step: int = 0
    state: AgentState = AgentState.IDLE
    context: dict[str, Any] = field(default_factory=dict)


class Agent:
    """Planner-first agent.

    In this repo, execution is typically delegated to the existing Router queue
    runner. This class focuses on producing validated steps.
    """

    def __init__(self, planner: Planner, tools: ToolRegistry):
        self.planner = planner
        self.tools = tools

    def plan(self, request: str, *, task_id: str = "task") -> Task:
        task = Task(id=task_id, original_request=request, state=AgentState.PLANNING)
        planned = self.planner.plan(request, self.tools)

        steps: list[Step] = []
        for i, ps in enumerate(planned, start=1):
            ok, reason = self.tools.validate_call(ps.action, ps.params)
            if not ok:
                raise ValueError(f"invalid_step:{i}:{reason}")
            steps.append(Step(id=i, action=ps.action, params=ps.params, description=ps.description))

        task.steps = steps
        task.state = AgentState.EXECUTING
        return task

    def execute(
        self,
        request: str,
        *,
        task_id: str = "task",
        runner: Optional[callable] = None,
        cancel_check: Optional[callable] = None,
        preview: Optional[callable] = None,
        max_retries: int = 1,
    ) -> Task:
        """Standalone execution loop.

        This is intentionally simple and synchronous.
        Production Bantz execution is delegated to Router's queue runner.
        """

        task = self.plan(request, task_id=task_id)
        executor = Executor(self.tools)
        verifier = Verifier()
        recovery = RecoveryPolicy(max_retries=max_retries)

        if runner is None:
            # No runtime runner provided; only planning.
            task.state = AgentState.FAILED
            return task

        while task.current_step < len(task.steps):
            if cancel_check and bool(cancel_check()):
                task.state = AgentState.FAILED
                for s in task.steps[task.current_step:]:
                    if s.status == "pending":
                        s.status = "skipped"
                return task

            step = task.steps[task.current_step]
            step.status = "running"

            attempt = 0
            while True:
                attempt += 1
                result: ExecutionResult = executor.execute(step, runner=runner, preview=preview)
                step.result = result.data
                step.error = result.error

                v = verifier.verify(step, result)
                if v.ok:
                    step.status = "completed"
                    break

                task.state = AgentState.RECOVERING
                decision = recovery.decide(attempt=attempt)
                if decision.action == "retry":
                    continue
                if decision.action == "skip":
                    step.status = "skipped"
                    break

                # abort
                step.status = "failed"
                task.state = AgentState.FAILED
                return task

            task.current_step += 1

        task.state = AgentState.COMPLETED
        return task

    @staticmethod
    def planned_steps(task: Task) -> list[PlannedStep]:
        return [PlannedStep(action=s.action, params=s.params, description=s.description) for s in task.steps]
