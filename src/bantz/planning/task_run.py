"""TaskRun & TaskStep data models + SQLite persistence (Issue #451).

Provides persistent lifecycle tracking for multi-step agent tasks:

- :class:`TaskStep` — a single planned action in a task
- :class:`StepResult` — the outcome of executing a step
- :class:`TaskRun` — envelope for the full goal → plan → execute → verify cycle

Data is stored in ``task_run`` and ``task_step`` tables inside the same
memory SQLite database used by :class:`~bantz.memory.persistent.PersistentMemoryStore`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TaskStatus",
    "StepStatus",
    "TaskStep",
    "StepResult",
    "TaskRun",
    "TaskRunStore",
]


# ── Enums ─────────────────────────────────────────────────────────────

class TaskStatus(Enum):
    """Lifecycle states for a :class:`TaskRun`."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    """Lifecycle states for a :class:`TaskStep`."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Data models ───────────────────────────────────────────────────────

@dataclass
class TaskStep:
    """A single planned step inside a :class:`TaskRun`.

    Attributes
    ----------
    index:
        0-based position in the plan.
    tool_name:
        Name of the tool / action to execute.
    args:
        Keyword arguments to pass to the tool.
    expected_output:
        Optional human-readable description of what we expect back.
    status:
        Current lifecycle state.
    """

    index: int = 0
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    expected_output: Optional[str] = None
    status: StepStatus = StepStatus.PENDING

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = StepStatus(self.status)


@dataclass
class StepResult:
    """Outcome of executing a :class:`TaskStep`.

    Attributes
    ----------
    step_index:
        Which step this result belongs to.
    output:
        The tool's return value (JSON-serialisable).
    error:
        Error message if the step failed.
    started_at:
        When execution started.
    finished_at:
        When execution finished.
    """

    step_index: int = 0
    output: Any = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


@dataclass
class TaskRun:
    """Persistent envelope for a multi-step agent task.

    Attributes
    ----------
    id:
        Unique UUID.
    goal:
        The user's original request.
    plan:
        Ordered list of :class:`TaskStep` objects.
    status:
        Current lifecycle state.
    steps:
        Results of executed steps.
    artifacts:
        Intermediate outputs keyed by step index or name.
    errors:
        Accumulated error messages.
    created_at / updated_at:
        Timestamps.
    resumed_from:
        If this run was resumed from another, the original run ID.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    plan: List[TaskStep] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    steps: List[StepResult] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    resumed_from: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = TaskStatus(self.status)

    @property
    def current_step_index(self) -> int:
        """Index of the next step to execute."""
        return len(self.steps)

    @property
    def is_terminal(self) -> bool:
        """Whether the run is in a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    def touch(self) -> None:
        """Bump *updated_at*."""
        self.updated_at = datetime.utcnow()


# ── SQLite DDL ────────────────────────────────────────────────────────

_CREATE_TASK_RUN = """
CREATE TABLE IF NOT EXISTS task_run (
    id           TEXT PRIMARY KEY,
    goal         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    artifacts    TEXT NOT NULL DEFAULT '{}',
    errors       TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    resumed_from TEXT
);
"""

_CREATE_TASK_STEP = """
CREATE TABLE IF NOT EXISTS task_step (
    run_id          TEXT NOT NULL REFERENCES task_run(id) ON DELETE CASCADE,
    step_index      INTEGER NOT NULL,
    tool_name       TEXT NOT NULL,
    args            TEXT NOT NULL DEFAULT '{}',
    expected_output TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    output          TEXT,
    error           TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    PRIMARY KEY (run_id, step_index)
);
"""


# ── Persistence layer ─────────────────────────────────────────────────

class TaskRunStore:
    """SQLite-backed CRUD for :class:`TaskRun`.

    Parameters
    ----------
    conn:
        An open ``sqlite3.Connection`` (typically the same one used by
        :class:`~bantz.memory.persistent.PersistentMemoryStore`).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        with self._lock:
            self._conn.execute(_CREATE_TASK_RUN)
            self._conn.execute(_CREATE_TASK_STEP)

    # ── create ────────────────────────────────────────────────────────

    def create(self, run: TaskRun) -> str:
        """Persist a new :class:`TaskRun` (including its plan steps)."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO task_run
                    (id, goal, status, artifacts, errors,
                     created_at, updated_at, resumed_from)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.goal,
                    run.status.value,
                    json.dumps(run.artifacts),
                    json.dumps(run.errors),
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                    run.resumed_from,
                ),
            )
            for step in run.plan:
                self._insert_step(run.id, step)
        return run.id

    def _insert_step(self, run_id: str, step: TaskStep) -> None:
        """Insert a single plan step (must hold self._lock)."""
        self._conn.execute(
            """
            INSERT INTO task_step
                (run_id, step_index, tool_name, args,
                 expected_output, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step.index,
                step.tool_name,
                json.dumps(step.args),
                step.expected_output,
                step.status.value,
            ),
        )

    # ── read ──────────────────────────────────────────────────────────

    def get(self, run_id: str) -> Optional[TaskRun]:
        """Load a :class:`TaskRun` by ID (with plan + step results)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM task_run WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None

            step_rows = self._conn.execute(
                "SELECT * FROM task_step WHERE run_id = ? ORDER BY step_index",
                (run_id,),
            ).fetchall()

        return self._build_task_run(row, step_rows)

    def list_runs(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 20,
    ) -> List[TaskRun]:
        """List task runs, optionally filtered by status."""
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status.value)
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM task_run {where} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()

        runs: List[TaskRun] = []
        for row in rows:
            with self._lock:
                step_rows = self._conn.execute(
                    "SELECT * FROM task_step WHERE run_id = ? ORDER BY step_index",
                    (row["id"],),
                ).fetchall()
            runs.append(self._build_task_run(row, step_rows))
        return runs

    # ── update ────────────────────────────────────────────────────────

    def update_status(self, run_id: str, status: TaskStatus) -> bool:
        """Change the status of a run.  Returns *True* if updated."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE task_run SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, run_id),
            )
        return cur.rowcount > 0

    def record_step_result(self, run_id: str, result: StepResult) -> bool:
        """Record the outcome of executing a step."""
        now = datetime.utcnow().isoformat()
        status = StepStatus.FAILED.value if result.error else StepStatus.DONE.value
        finished = result.finished_at.isoformat() if result.finished_at else now
        started = result.started_at.isoformat()

        with self._lock:
            cur = self._conn.execute(
                """
                UPDATE task_step
                SET status = ?, output = ?, error = ?,
                    started_at = ?, finished_at = ?
                WHERE run_id = ? AND step_index = ?
                """,
                (
                    status,
                    json.dumps(result.output),
                    result.error,
                    started,
                    finished,
                    run_id,
                    result.step_index,
                ),
            )
            # Also update the run's updated_at
            self._conn.execute(
                "UPDATE task_run SET updated_at = ? WHERE id = ?",
                (now, run_id),
            )

            # If error, append to run's errors
            if result.error:
                row = self._conn.execute(
                    "SELECT errors FROM task_run WHERE id = ?", (run_id,)
                ).fetchone()
                if row:
                    errors = json.loads(row["errors"])
                    errors.append(result.error)
                    self._conn.execute(
                        "UPDATE task_run SET errors = ? WHERE id = ?",
                        (json.dumps(errors), run_id),
                    )

        return cur.rowcount > 0

    def save_artifact(self, run_id: str, key: str, value: Any) -> bool:
        """Store an intermediate artifact on a run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT artifacts FROM task_run WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return False
            arts = json.loads(row["artifacts"])
            arts[key] = value
            now = datetime.utcnow().isoformat()
            self._conn.execute(
                "UPDATE task_run SET artifacts = ?, updated_at = ? WHERE id = ?",
                (json.dumps(arts), now, run_id),
            )
        return True

    # ── delete ────────────────────────────────────────────────────────

    def delete(self, run_id: str) -> bool:
        """Delete a run and its steps.  Returns *True* if deleted."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM task_run WHERE id = ?", (run_id,)
            )
        return cur.rowcount > 0

    # ── internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _build_task_run(row: sqlite3.Row, step_rows: list) -> TaskRun:
        plan: List[TaskStep] = []
        results: List[StepResult] = []

        for sr in step_rows:
            step = TaskStep(
                index=sr["step_index"],
                tool_name=sr["tool_name"],
                args=json.loads(sr["args"]),
                expected_output=sr["expected_output"],
                status=StepStatus(sr["status"]),
            )
            plan.append(step)

            # If the step has been executed, build a StepResult
            if sr["status"] in (StepStatus.DONE.value, StepStatus.FAILED.value):
                results.append(
                    StepResult(
                        step_index=sr["step_index"],
                        output=json.loads(sr["output"]) if sr["output"] else None,
                        error=sr["error"],
                        started_at=(
                            datetime.fromisoformat(sr["started_at"])
                            if sr["started_at"]
                            else datetime.utcnow()
                        ),
                        finished_at=(
                            datetime.fromisoformat(sr["finished_at"])
                            if sr["finished_at"]
                            else None
                        ),
                    )
                )

        return TaskRun(
            id=row["id"],
            goal=row["goal"],
            status=TaskStatus(row["status"]),
            artifacts=json.loads(row["artifacts"]),
            errors=json.loads(row["errors"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            resumed_from=row["resumed_from"],
            plan=plan,
            steps=results,
        )
