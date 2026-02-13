"""TaskRunner — orchestrates multi-step task execution (Issue #451).

Provides the high-level lifecycle API on top of :class:`TaskRunStore`:

- :meth:`start` — create a new run from a goal + plan
- :meth:`execute_step` — execute the next (or specific) step
- :meth:`pause` / :meth:`resume` / :meth:`cancel`
- :meth:`get_status` — retrieve current state
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from bantz.planning.task_run import (
    StepResult,
    StepStatus,
    TaskRun,
    TaskRunStore,
    TaskStatus,
    TaskStep,
)

logger = logging.getLogger(__name__)

__all__ = ["TaskRunner"]

# Type alias for tool executors: (tool_name, args) → output
ToolExecutor = Callable[[str, Dict[str, Any]], Any]


class TaskRunner:
    """Orchestrates multi-step task execution with persistence.

    Parameters
    ----------
    conn:
        SQLite connection (shared with PersistentMemoryStore).
    tool_executor:
        Optional callback ``(tool_name, args) → output``.
        If *None*, steps must be executed externally and results recorded
        via :meth:`record_result`.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> None:
        self._store = TaskRunStore(conn)
        self._executor = tool_executor

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self, goal: str, plan: List[TaskStep]) -> TaskRun:
        """Create and persist a new task run.

        Parameters
        ----------
        goal:
            The user's request / objective.
        plan:
            Ordered list of steps to execute.

        Returns
        -------
        TaskRun
            The newly created run in ``PENDING`` state.
        """
        run = TaskRun(goal=goal, plan=plan, status=TaskStatus.PENDING)
        self._store.create(run)
        logger.info("TaskRun %s created: %s (%d steps)", run.id, goal, len(plan))
        return run

    def execute_step(self, run_id: str, step_index: Optional[int] = None) -> StepResult:
        """Execute a step of the run.

        If *step_index* is ``None``, the next pending step is used.

        Returns
        -------
        StepResult
            The result of the executed step.

        Raises
        ------
        ValueError
            If the run doesn't exist, is in a terminal state, or no
            pending steps remain.
        RuntimeError
            If no tool_executor is configured.
        """
        run = self._store.get(run_id)
        if run is None:
            raise ValueError(f"TaskRun {run_id} not found")
        if run.is_terminal:
            raise ValueError(f"TaskRun {run_id} is in terminal state: {run.status.value}")

        # Move to RUNNING if still PENDING
        if run.status == TaskStatus.PENDING:
            self._store.update_status(run_id, TaskStatus.RUNNING)

        idx = step_index if step_index is not None else run.current_step_index
        if idx >= len(run.plan):
            raise ValueError(f"No pending step at index {idx}")

        step = run.plan[idx]

        if self._executor is None:
            raise RuntimeError("No tool_executor configured")

        started = datetime.utcnow()
        try:
            output = self._executor(step.tool_name, step.args)
            result = StepResult(
                step_index=idx,
                output=output,
                started_at=started,
                finished_at=datetime.utcnow(),
            )
        except Exception as exc:
            result = StepResult(
                step_index=idx,
                error=str(exc),
                started_at=started,
                finished_at=datetime.utcnow(),
            )

        self._store.record_step_result(run_id, result)
        logger.info("Step %d of run %s: %s", idx, run_id, "OK" if not result.error else result.error)

        # Check if all steps done → mark completed / failed
        updated_run = self._store.get(run_id)
        if updated_run and updated_run.current_step_index >= len(updated_run.plan):
            if updated_run.errors:
                self._store.update_status(run_id, TaskStatus.FAILED)
            else:
                self._store.update_status(run_id, TaskStatus.COMPLETED)

        return result

    def record_result(self, run_id: str, result: StepResult) -> bool:
        """Manually record a step result (for external execution)."""
        return self._store.record_step_result(run_id, result)

    def pause(self, run_id: str) -> bool:
        """Pause a running task.  Returns *True* if status changed."""
        run = self._store.get(run_id)
        if run is None:
            raise ValueError(f"TaskRun {run_id} not found")
        if run.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ValueError(f"Cannot pause run in state {run.status.value}")
        return self._store.update_status(run_id, TaskStatus.PAUSED)

    def resume(self, run_id: str) -> TaskRun:
        """Resume a paused task — returns the run so caller can continue.

        Raises
        ------
        ValueError
            If the run is not paused.
        """
        run = self._store.get(run_id)
        if run is None:
            raise ValueError(f"TaskRun {run_id} not found")
        if run.status != TaskStatus.PAUSED:
            raise ValueError(f"Cannot resume run in state {run.status.value}")
        self._store.update_status(run_id, TaskStatus.RUNNING)
        run.status = TaskStatus.RUNNING
        logger.info("TaskRun %s resumed from step %d", run_id, run.current_step_index)
        return run

    def cancel(self, run_id: str) -> bool:
        """Cancel a task.  Returns *True* if status changed."""
        run = self._store.get(run_id)
        if run is None:
            raise ValueError(f"TaskRun {run_id} not found")
        if run.is_terminal:
            raise ValueError(f"Cannot cancel run in terminal state {run.status.value}")
        # Mark remaining pending steps as SKIPPED
        for step in run.plan:
            if step.status == StepStatus.PENDING:
                self._store.record_step_result(
                    run_id,
                    StepResult(
                        step_index=step.index,
                        error="cancelled",
                        finished_at=datetime.utcnow(),
                    ),
                )
        return self._store.update_status(run_id, TaskStatus.CANCELLED)

    def get_status(self, run_id: str) -> TaskRun:
        """Get the current state of a task run.

        Raises
        ------
        ValueError
            If the run doesn't exist.
        """
        run = self._store.get(run_id)
        if run is None:
            raise ValueError(f"TaskRun {run_id} not found")
        return run

    def get_last_run(self) -> Optional[TaskRun]:
        """Return the most recently updated run, or *None*."""
        runs = self._store.list_runs(limit=1)
        return runs[0] if runs else None

    def save_artifact(self, run_id: str, key: str, value: Any) -> bool:
        """Store an intermediate artifact on a run."""
        return self._store.save_artifact(run_id, key, value)
