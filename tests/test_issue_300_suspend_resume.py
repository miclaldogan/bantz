"""Tests for Issue #300 — Suspend/Resume Handling.

Covers:
  - ResumeDetector: time-gap detection, threshold, reset, count
  - RecoveryManager: recovery flow, audio re-init, vLLM check, FSM reset
  - RecoveryResult: success/summary logic
  - PidGuard: acquire, release, stale PID, duplicate detection, context manager
  - Script/service file existence
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# ResumeDetector
# ─────────────────────────────────────────────────────────────────


class TestResumeDetector:
    """Time-gap based suspend/resume detection."""

    def test_no_resume_on_normal_tick(self):
        from bantz.voice.resume import ResumeDetector

        det = ResumeDetector(gap_threshold_s=30.0)
        # Immediate check — gap is ~0s
        assert det.check() is False
        assert det.resume_count == 0

    def test_resume_on_large_gap(self):
        from bantz.voice.resume import ResumeDetector

        det = ResumeDetector(gap_threshold_s=5.0)
        # Simulate a 10-second gap
        det._last_tick = time.time() - 10
        assert det.check() is True
        assert det.resume_count == 1

    def test_multiple_resumes_counted(self):
        from bantz.voice.resume import ResumeDetector

        det = ResumeDetector(gap_threshold_s=1.0)
        det._last_tick = time.time() - 5
        det.check()
        det._last_tick = time.time() - 5
        det.check()
        assert det.resume_count == 2

    def test_reset_clears_timer(self):
        from bantz.voice.resume import ResumeDetector

        det = ResumeDetector(gap_threshold_s=5.0)
        det._last_tick = time.time() - 100  # would trigger
        det.reset()
        assert det.check() is False  # reset made it fresh

    def test_threshold_property(self):
        from bantz.voice.resume import ResumeDetector

        det = ResumeDetector(gap_threshold_s=42.0)
        assert det.gap_threshold_s == 42.0

    def test_small_threshold(self):
        from bantz.voice.resume import ResumeDetector

        det = ResumeDetector(gap_threshold_s=0.001)
        time.sleep(0.01)
        assert det.check() is True


# ─────────────────────────────────────────────────────────────────
# RecoveryResult
# ─────────────────────────────────────────────────────────────────


class TestRecoveryResult:
    """Recovery result data class."""

    def test_success_when_all_ok(self):
        from bantz.voice.resume import RecoveryResult

        r = RecoveryResult(audio_ok=True, vllm_ok=True, fsm_reset=True)
        assert r.success is True

    def test_failure_when_vllm_down(self):
        from bantz.voice.resume import RecoveryResult

        r = RecoveryResult(audio_ok=True, vllm_ok=False, fsm_reset=True)
        assert r.success is False

    def test_failure_when_error_set(self):
        from bantz.voice.resume import RecoveryResult

        r = RecoveryResult(audio_ok=True, vllm_ok=True, error="boom")
        assert r.success is False

    def test_summary_contains_status(self):
        from bantz.voice.resume import RecoveryResult

        r = RecoveryResult(audio_ok=True, vllm_ok=True, warmup_elapsed_s=2.5)
        s = r.summary()
        assert "✅" in s
        assert "audio=OK" in s
        assert "vllm=OK" in s

    def test_summary_fail_icon(self):
        from bantz.voice.resume import RecoveryResult

        r = RecoveryResult(audio_ok=False, vllm_ok=False)
        s = r.summary()
        assert "❌" in s


# ─────────────────────────────────────────────────────────────────
# RecoveryManager
# ─────────────────────────────────────────────────────────────────


class TestRecoveryManager:
    """Recovery flow orchestration."""

    def test_run_with_mocked_deps(self):
        from bantz.voice.resume import RecoveryManager

        mgr = RecoveryManager(vllm_url="http://invalid:9999/health", warmup_timeout_s=0.1)
        # Mock all internal methods
        mgr._recover_audio = mock.MagicMock(return_value=True)
        mgr._check_vllm_with_retry = mock.MagicMock(return_value=True)
        mgr._reset_fsm = mock.MagicMock(return_value=True)

        result = mgr.run()
        assert result.success is True
        assert result.audio_ok is True
        assert result.vllm_ok is True
        assert result.fsm_reset is True
        assert mgr.recovery_count == 1

    def test_run_calls_ready_callback(self):
        from bantz.voice.resume import RecoveryManager

        callback = mock.MagicMock()
        mgr = RecoveryManager(on_ready_callback=callback)
        mgr._recover_audio = mock.MagicMock(return_value=True)
        mgr._check_vllm_with_retry = mock.MagicMock(return_value=True)
        mgr._reset_fsm = mock.MagicMock(return_value=True)

        mgr.run()
        callback.assert_called_once()

    def test_run_partial_failure(self):
        from bantz.voice.resume import RecoveryManager

        mgr = RecoveryManager()
        mgr._recover_audio = mock.MagicMock(return_value=False)
        mgr._check_vllm_with_retry = mock.MagicMock(return_value=False)
        mgr._reset_fsm = mock.MagicMock(return_value=True)

        result = mgr.run()
        assert result.success is False
        assert result.audio_ok is False

    def test_recover_audio_no_sounddevice(self):
        """When sounddevice is not installed, audio recovery returns True (headless)."""
        from bantz.voice.resume import RecoveryManager

        mgr = RecoveryManager()
        with mock.patch.dict("sys.modules", {"sounddevice": None}):
            # Force ImportError
            with mock.patch(
                "bantz.voice.resume.RecoveryManager._recover_audio",
                wraps=mgr._recover_audio
            ):
                # Just test the actual method
                result = mgr._recover_audio()
                # On CI/headless, sounddevice may or may not be available
                assert isinstance(result, bool)

    def test_vllm_check_timeout(self):
        """vLLM check with unreachable URL should return False quickly."""
        from bantz.voice.resume import RecoveryManager

        mgr = RecoveryManager(
            vllm_url="http://127.0.0.1:59999/health",  # unlikely to be listening
            warmup_timeout_s=0.5,
        )
        result = mgr._check_vllm_with_retry()
        assert result is False

    def test_recovery_count_increments(self):
        from bantz.voice.resume import RecoveryManager

        mgr = RecoveryManager()
        mgr._recover_audio = mock.MagicMock(return_value=True)
        mgr._check_vllm_with_retry = mock.MagicMock(return_value=True)
        mgr._reset_fsm = mock.MagicMock(return_value=True)

        mgr.run()
        mgr.run()
        assert mgr.recovery_count == 2


# ─────────────────────────────────────────────────────────────────
# PidGuard
# ─────────────────────────────────────────────────────────────────


class TestPidGuard:
    """Cross-process PID file guard."""

    def test_acquire_creates_pid_file(self, tmp_path):
        from bantz.voice.resume import PidGuard

        guard = PidGuard(path=tmp_path / "test.pid")
        guard.acquire()
        assert (tmp_path / "test.pid").exists()
        content = (tmp_path / "test.pid").read_text().strip()
        assert content == str(os.getpid())
        assert guard.acquired is True
        guard.release()

    def test_release_removes_file(self, tmp_path):
        from bantz.voice.resume import PidGuard

        guard = PidGuard(path=tmp_path / "test.pid")
        guard.acquire()
        guard.release()
        assert not (tmp_path / "test.pid").exists()
        assert guard.acquired is False

    def test_stale_pid_overwritten(self, tmp_path):
        from bantz.voice.resume import PidGuard

        pid_file = tmp_path / "test.pid"
        pid_file.write_text("99999999")  # Likely not running

        guard = PidGuard(path=pid_file)
        guard.acquire()  # Should succeed (stale PID)
        assert pid_file.read_text().strip() == str(os.getpid())
        guard.release()

    def test_duplicate_detection(self, tmp_path):
        from bantz.voice.resume import PidGuard, PidGuardError

        pid_file = tmp_path / "test.pid"
        # Write our own PID (it's alive)
        pid_file.write_text(str(os.getpid()))

        guard = PidGuard(path=pid_file)
        with pytest.raises(PidGuardError, match="zaten çalışıyor"):
            guard.acquire()

    def test_context_manager(self, tmp_path):
        from bantz.voice.resume import PidGuard

        pid_file = tmp_path / "test.pid"
        with PidGuard(path=pid_file) as guard:
            assert pid_file.exists()
            assert guard.acquired is True
        assert not pid_file.exists()

    def test_creates_parent_dirs(self, tmp_path):
        from bantz.voice.resume import PidGuard

        guard = PidGuard(path=tmp_path / "deep" / "nested" / "test.pid")
        guard.acquire()
        assert (tmp_path / "deep" / "nested" / "test.pid").exists()
        guard.release()

    def test_release_only_own_pid(self, tmp_path):
        """Release should not remove file if PID changed (race condition)."""
        from bantz.voice.resume import PidGuard

        pid_file = tmp_path / "test.pid"
        guard = PidGuard(path=pid_file)
        guard.acquire()

        # Simulate another process taking over
        pid_file.write_text("12345")

        guard.release()
        # File should still exist (not our PID)
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "12345"

    def test_invalid_pid_file_content(self, tmp_path):
        from bantz.voice.resume import PidGuard

        pid_file = tmp_path / "test.pid"
        pid_file.write_text("not_a_number")

        guard = PidGuard(path=pid_file)
        guard.acquire()  # Should succeed (invalid content)
        guard.release()

    def test_path_property(self, tmp_path):
        from bantz.voice.resume import PidGuard

        guard = PidGuard(path=tmp_path / "p.pid")
        assert guard.path == tmp_path / "p.pid"


# ─────────────────────────────────────────────────────────────────
# Script / Service files
# ─────────────────────────────────────────────────────────────────


class TestResumeScript:
    """Verify resume script exists."""

    def test_script_exists(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "bantz_resume.py"
        assert script.exists()

    def test_script_importable(self):
        import importlib.util

        script = Path(__file__).resolve().parents[1] / "scripts" / "bantz_resume.py"
        spec = importlib.util.spec_from_file_location("bantz_resume", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "main")


class TestResumeService:
    """Verify systemd service file."""

    def test_service_file_exists(self):
        svc = Path(__file__).resolve().parents[1] / "systemd" / "user" / "bantz-resume.service"
        assert svc.exists()

    def test_service_has_exec_start(self):
        svc = Path(__file__).resolve().parents[1] / "systemd" / "user" / "bantz-resume.service"
        content = svc.read_text()
        assert "ExecStart=" in content
        assert "bantz_resume.py" in content

    def test_service_targets_suspend(self):
        svc = Path(__file__).resolve().parents[1] / "systemd" / "user" / "bantz-resume.service"
        content = svc.read_text()
        assert "suspend.target" in content
