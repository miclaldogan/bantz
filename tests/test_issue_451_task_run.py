"""Tests for issue #451 — TaskRun persistence + pause/resume."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from bantz.planning.task_run import (
    StepResult,
    StepStatus,
    TaskRun,
    TaskRunStore,
    TaskStatus,
    TaskStep,
)
from bantz.planning.task_runner import TaskRunner


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def conn():
    """In-memory SQLite connection with WAL + FK."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture()
def store(conn):
    return TaskRunStore(conn)


@pytest.fixture()
def runner(conn):
    """TaskRunner with a dummy executor that echoes args."""
    def echo_executor(tool_name: str, args: dict):
        return {"tool": tool_name, **args}
    return TaskRunner(conn, tool_executor=echo_executor)


def _plan() -> list[TaskStep]:
    return [
        TaskStep(index=0, tool_name="search", args={"q": "Ankara"}, expected_output="results"),
        TaskStep(index=1, tool_name="summarise", args={"text": "..."}),
        TaskStep(index=2, tool_name="respond", args={"msg": "done"}),
    ]


# ── TestTaskRunStore ──────────────────────────────────────────────────

class TestTaskRunStore:
    """Persistence round-trip tests."""

    def test_create_and_read(self, store):
        run = TaskRun(goal="test görev", plan=_plan())
        store.create(run)
        loaded = store.get(run.id)
        assert loaded is not None
        assert loaded.goal == "test görev"
        assert loaded.status == TaskStatus.PENDING
        assert len(loaded.plan) == 3

    def test_step_fields_persisted(self, store):
        run = TaskRun(goal="g", plan=_plan())
        store.create(run)
        loaded = store.get(run.id)
        assert loaded.plan[0].tool_name == "search"
        assert loaded.plan[0].args == {"q": "Ankara"}
        assert loaded.plan[0].expected_output == "results"
        assert loaded.plan[0].status == StepStatus.PENDING

    def test_update_status(self, store):
        run = TaskRun(goal="g", plan=_plan())
        store.create(run)
        store.update_status(run.id, TaskStatus.RUNNING)
        loaded = store.get(run.id)
        assert loaded.status == TaskStatus.RUNNING

    def test_record_step_result(self, store):
        run = TaskRun(goal="g", plan=_plan())
        store.create(run)
        result = StepResult(step_index=0, output={"key": "val"})
        store.record_step_result(run.id, result)
        loaded = store.get(run.id)
        assert loaded.plan[0].status == StepStatus.DONE
        assert len(loaded.steps) == 1
        assert loaded.steps[0].output == {"key": "val"}

    def test_record_failed_step(self, store):
        run = TaskRun(goal="g", plan=_plan())
        store.create(run)
        result = StepResult(step_index=0, error="boom")
        store.record_step_result(run.id, result)
        loaded = store.get(run.id)
        assert loaded.plan[0].status == StepStatus.FAILED
        assert "boom" in loaded.errors

    def test_save_artifact(self, store):
        run = TaskRun(goal="g", plan=_plan())
        store.create(run)
        store.save_artifact(run.id, "url", "https://example.com")
        loaded = store.get(run.id)
        assert loaded.artifacts["url"] == "https://example.com"

    def test_delete(self, store):
        run = TaskRun(goal="g", plan=_plan())
        store.create(run)
        assert store.delete(run.id)
        assert store.get(run.id) is None

    def test_list_runs(self, store):
        for i in range(5):
            store.create(TaskRun(goal=f"goal-{i}", plan=[]))
        runs = store.list_runs(limit=3)
        assert len(runs) == 3

    def test_list_runs_by_status(self, store):
        r1 = TaskRun(goal="a", plan=[], status=TaskStatus.RUNNING)
        r2 = TaskRun(goal="b", plan=[], status=TaskStatus.PENDING)
        store.create(r1)
        store.create(r2)
        runs = store.list_runs(status=TaskStatus.RUNNING)
        assert len(runs) == 1
        assert runs[0].status == TaskStatus.RUNNING


# ── TestTaskRunner ────────────────────────────────────────────────────

class TestTaskRunner:
    """High-level lifecycle tests."""

    def test_start_creates_run(self, runner):
        run = runner.start("do things", _plan())
        assert run.status == TaskStatus.PENDING
        assert len(run.plan) == 3

    def test_execute_step(self, runner):
        run = runner.start("go", _plan())
        result = runner.execute_step(run.id)
        assert result.error is None
        assert result.output["tool"] == "search"

    def test_execute_all_steps_completes(self, runner):
        run = runner.start("go", _plan())
        for _ in range(3):
            runner.execute_step(run.id)
        status = runner.get_status(run.id)
        assert status.status == TaskStatus.COMPLETED

    def test_pause_and_resume(self, runner):
        run = runner.start("go", _plan())
        runner.execute_step(run.id)  # step 0

        runner.pause(run.id)
        status = runner.get_status(run.id)
        assert status.status == TaskStatus.PAUSED

        resumed = runner.resume(run.id)
        assert resumed.status == TaskStatus.RUNNING
        assert resumed.current_step_index == 1  # resumes from step 1

    def test_cancel(self, runner):
        run = runner.start("go", _plan())
        runner.execute_step(run.id)
        runner.cancel(run.id)
        status = runner.get_status(run.id)
        assert status.status == TaskStatus.CANCELLED

    def test_execute_on_terminal_raises(self, runner):
        run = runner.start("go", _plan())
        for _ in range(3):
            runner.execute_step(run.id)
        with pytest.raises(ValueError, match="terminal"):
            runner.execute_step(run.id)

    def test_pause_completed_raises(self, runner):
        run = runner.start("go", _plan())
        for _ in range(3):
            runner.execute_step(run.id)
        with pytest.raises(ValueError, match="Cannot pause"):
            runner.pause(run.id)

    def test_resume_non_paused_raises(self, runner):
        run = runner.start("go", _plan())
        with pytest.raises(ValueError, match="Cannot resume"):
            runner.resume(run.id)

    def test_failed_step_tracks_error(self, conn):
        def bad_executor(tool: str, args: dict):
            raise RuntimeError("tool exploded")
        runner = TaskRunner(conn, tool_executor=bad_executor)
        run = runner.start("go", [TaskStep(index=0, tool_name="boom", args={})])
        result = runner.execute_step(run.id)
        assert result.error == "tool exploded"
        status = runner.get_status(run.id)
        assert status.status == TaskStatus.FAILED
        assert "tool exploded" in status.errors

    def test_get_last_run(self, runner):
        runner.start("first", [])
        runner.start("second", [])
        last = runner.get_last_run()
        assert last is not None
        assert last.goal == "second"

    def test_save_artifact(self, runner):
        run = runner.start("go", _plan())
        runner.save_artifact(run.id, "data", [1, 2, 3])
        status = runner.get_status(run.id)
        assert status.artifacts["data"] == [1, 2, 3]

    def test_no_executor_raises(self, conn):
        runner = TaskRunner(conn, tool_executor=None)
        run = runner.start("go", [TaskStep(index=0, tool_name="x", args={})])
        with pytest.raises(RuntimeError, match="No tool_executor"):
            runner.execute_step(run.id)


# ── TestTaskRunDataModel ──────────────────────────────────────────────

class TestTaskRunDataModel:
    """Unit tests for data model properties."""

    def test_current_step_index_zero_initially(self):
        run = TaskRun()
        assert run.current_step_index == 0

    def test_is_terminal(self):
        for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            run = TaskRun(status=status)
            assert run.is_terminal

    def test_is_not_terminal(self):
        for status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED):
            run = TaskRun(status=status)
            assert not run.is_terminal

    def test_touch_updates_timestamp(self):
        run = TaskRun()
        old = run.updated_at
        import time; time.sleep(0.01)
        run.touch()
        assert run.updated_at >= old

    def test_string_status_coercion(self):
        run = TaskRun(status="running")  # type: ignore[arg-type]
        assert run.status == TaskStatus.RUNNING

    def test_step_string_status_coercion(self):
        step = TaskStep(status="done")  # type: ignore[arg-type]
        assert step.status == StepStatus.DONE
