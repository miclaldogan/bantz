"""Tests for Otonom Gece Modu — Issue #836.

Covers:
    - OvernightTask lifecycle (create, status, retry, serialization)
    - OvernightState (serialization, progress, next_pending_task)
    - Checkpoint persistence (save/load/clear)
    - OvernightFailSafe (decision queueing, WAITING_HUMAN)
    - ResourceMonitor (rate limiting, exponential backoff)
    - OvernightRunner (task execution, checkpoint, morning report)
    - Morning report generation
    - NLU parsing (is_overnight_request, parse_overnight_tasks)
    - Resume from checkpoint
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bantz.automation.overnight import (
    DEFAULT_API_COOLDOWN_SECONDS,
    DEFAULT_TASK_DELAY_SECONDS,
    MAX_CONSECUTIVE_ERRORS,
    OvernightFailSafe,
    OvernightRunner,
    OvernightState,
    OvernightStatus,
    OvernightTask,
    ResourceMonitor,
    TaskStatus,
    clear_checkpoint,
    generate_morning_report,
    is_overnight_request,
    load_checkpoint,
    parse_overnight_tasks,
    resume_overnight,
    save_checkpoint,
)


# ─────────────────────────────────────────────────────────────────
# OvernightTask
# ─────────────────────────────────────────────────────────────────

class TestOvernightTask:

    def test_create(self):
        task = OvernightTask.create("Test görevi")
        assert task.description == "Test görevi"
        assert task.status == TaskStatus.PENDING
        assert task.id
        assert task.priority == 0
        assert task.result is None
        assert task.error is None
        assert task.retry_count == 0

    def test_create_with_priority(self):
        task = OvernightTask.create("Önemli görev", priority=5)
        assert task.priority == 5

    def test_is_terminal(self):
        task = OvernightTask.create("x")
        assert not task.is_terminal

        for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.WAITING_HUMAN):
            task.status = status
            assert task.is_terminal

        task.status = TaskStatus.RUNNING
        assert not task.is_terminal

    def test_can_retry(self):
        task = OvernightTask.create("x")
        task.max_retries = 2
        assert task.can_retry  # retry_count=0

        task.retry_count = 1
        assert task.can_retry

        task.retry_count = 2
        assert not task.can_retry

    def test_serialization(self):
        task = OvernightTask.create("Görev A")
        task.status = TaskStatus.COMPLETED
        task.result = "Done"
        task.duration_ms = 123.4
        task.retry_count = 1
        task.metadata = {"key": "value"}

        data = task.to_dict()
        assert data["description"] == "Görev A"
        assert data["status"] == "completed"
        assert data["result"] == "Done"
        assert data["duration_ms"] == 123.4
        assert data["retry_count"] == 1

        restored = OvernightTask.from_dict(data)
        assert restored.id == task.id
        assert restored.description == task.description
        assert restored.status == TaskStatus.COMPLETED
        assert restored.result == "Done"
        assert restored.duration_ms == 123.4
        assert restored.metadata == {"key": "value"}


# ─────────────────────────────────────────────────────────────────
# OvernightState
# ─────────────────────────────────────────────────────────────────

class TestOvernightState:

    def test_create_from_descriptions(self):
        state = OvernightState.create(["Task A", "Task B", "Task C"])
        assert state.total_tasks == 3
        assert state.session_id
        assert state.status == OvernightStatus.IDLE
        assert all(t.status == TaskStatus.PENDING for t in state.tasks)

    def test_progress(self):
        state = OvernightState.create(["A", "B", "C", "D"])
        assert state.progress_percent == 0.0

        state.tasks[0].status = TaskStatus.COMPLETED
        assert state.progress_percent == 25.0

        state.tasks[1].status = TaskStatus.FAILED
        assert state.progress_percent == 50.0

    def test_counts(self):
        state = OvernightState.create(["A", "B", "C"])
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[1].status = TaskStatus.FAILED
        state.tasks[2].status = TaskStatus.WAITING_HUMAN

        assert state.completed_count == 1
        assert state.failed_count == 1
        assert state.waiting_human_count == 1

    def test_next_pending_task(self):
        state = OvernightState.create(["A", "B", "C"])
        first = state.next_pending_task
        assert first.description == "A"

        state.tasks[0].status = TaskStatus.COMPLETED
        second = state.next_pending_task
        assert second.description == "B"

        state.tasks[1].status = TaskStatus.COMPLETED
        state.tasks[2].status = TaskStatus.COMPLETED
        assert state.next_pending_task is None

    def test_serialization(self):
        state = OvernightState.create(["Task X", "Task Y"])
        state.status = OvernightStatus.RUNNING
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[0].result = "Done X"
        state.error_log = ["some error"]

        data = state.to_dict()
        assert data["status"] == "running"
        assert len(data["tasks"]) == 2
        assert data["tasks"][0]["status"] == "completed"

        restored = OvernightState.from_dict(data)
        assert restored.session_id == state.session_id
        assert restored.status == OvernightStatus.RUNNING
        assert restored.tasks[0].status == TaskStatus.COMPLETED
        assert restored.tasks[0].result == "Done X"
        assert restored.error_log == ["some error"]

    def test_empty_state(self):
        state = OvernightState.create([])
        assert state.total_tasks == 0
        assert state.progress_percent == 0.0
        assert state.next_pending_task is None


# ─────────────────────────────────────────────────────────────────
# Checkpoint Persistence
# ─────────────────────────────────────────────────────────────────

class TestCheckpoint:

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "checkpoint.json"
        state = OvernightState.create(["A", "B"])
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[0].result = "Done A"

        save_checkpoint(state, path)
        assert path.exists()

        loaded = load_checkpoint(path)
        assert loaded is not None
        assert loaded.session_id == state.session_id
        assert loaded.tasks[0].status == TaskStatus.COMPLETED
        assert loaded.tasks[0].result == "Done A"
        assert loaded.tasks[1].status == TaskStatus.PENDING

    def test_load_nonexistent(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert load_checkpoint(path) is None

    def test_clear(self, tmp_path):
        path = tmp_path / "checkpoint.json"
        path.write_text("{}")
        clear_checkpoint(path)
        assert not path.exists()

    def test_clear_nonexistent(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        clear_checkpoint(path)  # Should not raise

    def test_save_atomic(self, tmp_path):
        """Ensure atomic write (no .tmp leftover)."""
        path = tmp_path / "checkpoint.json"
        state = OvernightState.create(["X"])
        save_checkpoint(state, path)

        tmp_file = path.with_suffix(".tmp")
        assert not tmp_file.exists()
        assert path.exists()


# ─────────────────────────────────────────────────────────────────
# OvernightFailSafe
# ─────────────────────────────────────────────────────────────────

class TestOvernightFailSafe:

    def test_should_wait_for_human(self):
        fs = OvernightFailSafe(max_consecutive_failures=3)
        assert not fs.should_wait_for_human(0)
        assert not fs.should_wait_for_human(2)
        assert fs.should_wait_for_human(3)
        assert fs.should_wait_for_human(5)

    def test_queue_decision(self):
        fs = OvernightFailSafe()
        task = OvernightTask.create("Test")

        fs.queue_decision(task, error="Timeout", question="Devam edelim mi?")

        assert task.status == TaskStatus.WAITING_HUMAN
        assert task.human_question == "Devam edelim mi?"
        assert len(fs.pending_decisions) == 1
        assert fs.pending_decisions[0]["task_id"] == task.id
        assert fs.pending_decisions[0]["error"] == "Timeout"

    def test_clear(self):
        fs = OvernightFailSafe()
        task = OvernightTask.create("Test")
        fs.queue_decision(task, "err", "q?")
        assert len(fs.pending_decisions) == 1

        fs.clear()
        assert len(fs.pending_decisions) == 0


# ─────────────────────────────────────────────────────────────────
# ResourceMonitor
# ─────────────────────────────────────────────────────────────────

class TestResourceMonitor:

    def test_defaults(self):
        rm = ResourceMonitor()
        assert rm.task_delay == DEFAULT_TASK_DELAY_SECONDS
        assert rm.api_cooldown == DEFAULT_API_COOLDOWN_SECONDS

    def test_report_rate_limit_exponential_backoff(self):
        rm = ResourceMonitor()
        base = rm.api_cooldown

        rm.report_rate_limit()
        assert rm.api_cooldown == base * 2  # 4s

        rm.report_rate_limit()
        assert rm.api_cooldown == base * 4  # 8s

        rm.report_rate_limit()
        assert rm.api_cooldown == base * 8  # 16s

    def test_report_rate_limit_max_cap(self):
        rm = ResourceMonitor()
        for _ in range(20):
            rm.report_rate_limit()
        assert rm.api_cooldown <= 60.0

    def test_report_success_resets_cooldown(self):
        rm = ResourceMonitor()
        rm.report_rate_limit()
        rm.report_rate_limit()
        assert rm.api_cooldown > DEFAULT_API_COOLDOWN_SECONDS

        rm.report_success()
        assert rm.api_cooldown == DEFAULT_API_COOLDOWN_SECONDS


# ─────────────────────────────────────────────────────────────────
# Morning Report
# ─────────────────────────────────────────────────────────────────

class TestMorningReport:

    def test_basic_report(self):
        state = OvernightState.create(["Görev A", "Görev B"])
        state.started_at = "2025-01-01T00:00:00"
        state.completed_at = "2025-01-01T06:00:00"
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[0].result = "Sonuç A"
        state.tasks[1].status = TaskStatus.FAILED
        state.tasks[1].error = "Timeout"

        report = generate_morning_report(state)
        assert "Günaydın" in report
        assert "1/2" in report
        assert "Görev A" in report
        assert "Görev B" in report
        assert "Sonuç A" in report
        assert "Timeout" in report
        assert "❌" in report
        assert "✅" in report

    def test_waiting_human_in_report(self):
        state = OvernightState.create(["Görev X"])
        state.tasks[0].status = TaskStatus.WAITING_HUMAN
        state.tasks[0].human_question = "Devam edeyim mi?"
        state.human_decisions_pending = [{"task_description": "Görev X", "question": "Devam edeyim mi?"}]

        report = generate_morning_report(state)
        assert "Devam edeyim mi?" in report
        assert "⚠️" in report
        assert "Bekleyen Kararlar" in report

    def test_long_result_truncated(self):
        state = OvernightState.create(["Uzun görev"])
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[0].result = "x" * 500

        report = generate_morning_report(state)
        assert "..." in report


# ─────────────────────────────────────────────────────────────────
# NLU Parsing
# ─────────────────────────────────────────────────────────────────

class TestNLUParsing:

    @pytest.mark.parametrize("text", [
        "gece şunu yap: X",
        "Gece şunları yap: 1. X 2. Y",
        "gece boyunca araştır",
        "sabaha kadar çalış",
        "overnight run tasks",
        "uyurken şunu yap: test",
    ])
    def test_is_overnight_request_positive(self, text):
        assert is_overnight_request(text)

    @pytest.mark.parametrize("text", [
        "google aç",
        "takvime ekle",
        "hava durumu ne?",
        "nasılsın",
    ])
    def test_is_overnight_request_negative(self, text):
        assert not is_overnight_request(text)

    def test_parse_numbered_tasks(self):
        text = "gece şunları yap: 1. AI konferanslarını araştır 2. Haftalık haberleri özetle"
        tasks = parse_overnight_tasks(text)
        assert len(tasks) == 2
        assert "AI konferanslarını araştır" in tasks[0]
        assert "Haftalık haberleri özetle" in tasks[1]

    def test_parse_bullet_tasks(self):
        text = "gece şunları yap:\n- Araştır\n- Özetle\n- Raporla"
        tasks = parse_overnight_tasks(text)
        assert len(tasks) == 3

    def test_parse_single_task(self):
        text = "gece şunu yap: AI haberleri özetle"
        tasks = parse_overnight_tasks(text)
        assert len(tasks) == 1
        assert "AI haberleri özetle" in tasks[0]

    def test_parse_empty(self):
        text = "gece şunu yap:"
        tasks = parse_overnight_tasks(text)
        assert len(tasks) == 0

    def test_parse_newline_separated(self):
        text = "gece şunları yap:\nGörev A\nGörev B\nGörev C"
        tasks = parse_overnight_tasks(text)
        assert len(tasks) == 3


# ─────────────────────────────────────────────────────────────────
# OvernightRunner
# ─────────────────────────────────────────────────────────────────

class TestOvernightRunner:

    def _make_mock_server(self, responses=None):
        """Create a mock BantzServer with handle_command."""
        server = MagicMock()
        if responses:
            server.handle_command.side_effect = responses
        else:
            server.handle_command.return_value = {"ok": True, "text": "Tamamlandı"}
        return server

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_run_all_success(self, mock_cooldown, mock_wait, mock_save):
        server = self._make_mock_server()
        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["Görev 1", "Görev 2", "Görev 3"])

        state = runner.run()

        assert state.status == OvernightStatus.COMPLETED
        assert state.completed_count == 3
        assert state.failed_count == 0
        assert state.morning_report is not None
        assert "Günaydın" in state.morning_report
        assert server.handle_command.call_count == 3

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_run_with_failure(self, mock_cooldown, mock_wait, mock_save):
        server = self._make_mock_server(responses=[
            {"ok": True, "text": "Done 1"},
            {"ok": False, "text": "Error"},  # 1st fail → retry
            {"ok": False, "text": "Error"},  # 2nd fail → retry
            {"ok": False, "text": "Error"},  # 3rd fail → final fail
            {"ok": True, "text": "Done 3"},
        ])
        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["Task A", "Task B", "Task C"])

        state = runner.run()

        assert state.completed_count == 2
        # Task B becomes WAITING_HUMAN after exhausting retries + consecutive errors
        assert state.waiting_human_count == 1

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_run_exception_handling(self, mock_cooldown, mock_wait, mock_save):
        server = self._make_mock_server()
        server.handle_command.side_effect = [
            RuntimeError("Connection lost"),
            RuntimeError("Connection lost"),
            RuntimeError("Connection lost"),
            {"ok": True, "text": "Done"},
        ]

        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["Crashing Task", "Good Task"])

        state = runner.run()

        assert state.total_tasks == 2
        assert len(state.error_log) > 0

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_waiting_human_on_consecutive_failures(self, mock_cooldown, mock_wait, mock_save):
        """After MAX_CONSECUTIVE_ERRORS, task should be WAITING_HUMAN."""
        server = self._make_mock_server()
        # Fail consistently for 3+ consecutive
        server.handle_command.return_value = {"ok": False, "text": "Hata"}

        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["Fail 1", "Fail 2", "Fail 3", "Fail 4"])

        state = runner.run()

        # Some tasks should be WAITING_HUMAN due to consecutive failures
        waiting = sum(1 for t in state.tasks if t.status == TaskStatus.WAITING_HUMAN)
        failed = sum(1 for t in state.tasks if t.status == TaskStatus.FAILED)
        assert waiting + failed == state.total_tasks

    def test_add_task(self):
        runner = OvernightRunner()
        task = runner.add_task("Test task")
        assert task.description == "Test task"
        assert runner.state is not None
        assert runner.state.total_tasks == 1

    def test_add_tasks(self):
        runner = OvernightRunner()
        tasks = runner.add_tasks(["A", "B", "C"])
        assert len(tasks) == 3
        assert runner.state.total_tasks == 3

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_run_empty(self, mock_cooldown, mock_wait, mock_save):
        runner = OvernightRunner()
        state = runner.run()
        assert state is not None

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_cancel(self, mock_cooldown, mock_wait, mock_save):
        server = self._make_mock_server()
        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["Task 1", "Task 2"])
        runner.cancel()  # Set cancel before run

        state = runner.run()
        assert state.status == OvernightStatus.CANCELLED

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_checkpoint_called_after_each_task(self, mock_cooldown, mock_wait, mock_save):
        server = self._make_mock_server()
        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["A", "B"])

        runner.run()

        # Checkpoint called after each task + final
        assert mock_save.call_count >= 3  # 2 tasks + final

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_morning_report_generated(self, mock_cooldown, mock_wait, mock_save):
        server = self._make_mock_server()
        runner = OvernightRunner(bantz_server=server, checkpoint_path=Path("/tmp/test_ckpt.json"))
        runner.add_tasks(["Task A"])

        state = runner.run()

        assert state.morning_report is not None
        assert "Günaydın" in state.morning_report
        assert "Task A" in state.morning_report


# ─────────────────────────────────────────────────────────────────
# Resume
# ─────────────────────────────────────────────────────────────────

class TestResume:

    @patch("bantz.automation.overnight.save_checkpoint")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks")
    @patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown")
    def test_resume_from_checkpoint(self, mock_cooldown, mock_wait, mock_save, tmp_path):
        # Create a state with partial progress
        state = OvernightState.create(["A", "B", "C"])
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[0].result = "Done A"
        state.status = OvernightStatus.RUNNING

        ckpt_path = tmp_path / "checkpoint.json"
        # Write checkpoint manually
        with open(ckpt_path, "w") as f:
            json.dump(state.to_dict(), f)

        server = MagicMock()
        server.handle_command.return_value = {"ok": True, "text": "Done"}

        result = resume_overnight(bantz_server=server, checkpoint_path=ckpt_path)

        assert result is not None
        assert result.completed_count >= 2  # A was already done + B,C

    def test_resume_no_checkpoint(self, tmp_path):
        ckpt_path = tmp_path / "nonexistent.json"
        result = resume_overnight(checkpoint_path=ckpt_path)
        assert result is None

    def test_resume_completed_session(self, tmp_path):
        state = OvernightState.create(["A"])
        state.status = OvernightStatus.COMPLETED

        ckpt_path = tmp_path / "checkpoint.json"
        with open(ckpt_path, "w") as f:
            json.dump(state.to_dict(), f)

        result = resume_overnight(checkpoint_path=ckpt_path)
        assert result is not None
        assert result.status == OvernightStatus.COMPLETED


# ─────────────────────────────────────────────────────────────────
# Integration-ish: Full run with checkpoint save/load cycle
# ─────────────────────────────────────────────────────────────────

class TestIntegration:

    def test_full_cycle_with_real_checkpoint(self, tmp_path):
        """Test full overnight cycle: run → checkpoint → load → verify."""
        ckpt_path = tmp_path / "checkpoint.json"
        server = MagicMock()
        server.handle_command.return_value = {"ok": True, "text": "Tamamlandı"}

        with patch("bantz.automation.overnight.ResourceMonitor.wait_between_tasks"), \
             patch("bantz.automation.overnight.ResourceMonitor.wait_for_api_cooldown"):

            runner = OvernightRunner(
                bantz_server=server,
                checkpoint_path=ckpt_path,
            )
            runner.add_tasks(["Görev Alpha", "Görev Beta"])
            state = runner.run()

        # Checkpoint should exist
        assert ckpt_path.exists()

        # Load and verify
        loaded = load_checkpoint(ckpt_path)
        assert loaded is not None
        assert loaded.session_id == state.session_id
        assert loaded.completed_count == 2
        assert loaded.status == OvernightStatus.COMPLETED
        assert loaded.morning_report is not None

    def test_state_roundtrip(self):
        """OvernightState serialization roundtrip."""
        state = OvernightState.create(["Task 1", "Task 2", "Task 3"])
        state.status = OvernightStatus.RUNNING
        state.tasks[0].status = TaskStatus.COMPLETED
        state.tasks[0].result = "Done"
        state.tasks[1].status = TaskStatus.WAITING_HUMAN
        state.tasks[1].human_question = "Devam?"
        state.human_decisions_pending = [{"q": "test"}]
        state.error_log = ["err1"]

        data = state.to_dict()
        json_str = json.dumps(data, ensure_ascii=False)
        restored = OvernightState.from_dict(json.loads(json_str))

        assert restored.session_id == state.session_id
        assert restored.total_tasks == 3
        assert restored.tasks[0].result == "Done"
        assert restored.tasks[1].human_question == "Devam?"
        assert restored.error_log == ["err1"]
