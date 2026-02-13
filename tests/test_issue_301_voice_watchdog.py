"""Tests for Issue #301 — Voice Watchdog (heartbeat + log rotation).

Covers:
  - Heartbeat: tick, is_stale, clear, missing file, malformed file
  - LogRotator: rotate_if_needed, cleanup_old, list_logs, total_size
  - VoicePipeline heartbeat integration (_tick_heartbeat)
  - Watchdog script existence and permissions
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# Heartbeat
# ─────────────────────────────────────────────────────────────────


class TestHeartbeat:
    """Heartbeat file management."""

    def test_tick_creates_file(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "hb")
        hb.tick()
        assert (tmp_path / "hb").exists()
        ts = float((tmp_path / "hb").read_text())
        assert abs(time.time() - ts) < 5

    def test_tick_updates_last_tick(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "hb")
        assert hb.last_tick == 0.0
        hb.tick()
        assert hb.last_tick > 0.0

    def test_tick_creates_parent_dirs(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "deep" / "nested" / "hb")
        hb.tick()
        assert (tmp_path / "deep" / "nested" / "hb").exists()

    def test_is_stale_when_no_file(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "nonexistent")
        assert hb.is_stale() is True

    def test_is_stale_fresh_tick(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "hb", max_age_s=30.0)
        hb.tick()
        assert hb.is_stale() is False

    def test_is_stale_old_timestamp(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        path = tmp_path / "hb"
        # Write a timestamp 60 seconds in the past
        old_ts = time.time() - 60
        path.write_text(str(old_ts))

        hb = Heartbeat(path=path, max_age_s=30.0)
        assert hb.is_stale() is True

    def test_is_stale_custom_threshold(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        path = tmp_path / "hb"
        # Write a timestamp 10 seconds in the past
        old_ts = time.time() - 10
        path.write_text(str(old_ts))

        hb = Heartbeat(path=path, max_age_s=30.0)
        assert hb.is_stale(max_age_s=5.0) is True
        assert hb.is_stale(max_age_s=20.0) is False

    def test_is_stale_malformed_file(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        path = tmp_path / "hb"
        path.write_text("NOT A NUMBER")

        hb = Heartbeat(path=path)
        assert hb.is_stale() is True

    def test_clear_removes_file(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "hb")
        hb.tick()
        assert (tmp_path / "hb").exists()
        hb.clear()
        assert not (tmp_path / "hb").exists()

    def test_clear_no_error_when_missing(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "nonexistent")
        hb.clear()  # Should not raise

    def test_repr(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat

        hb = Heartbeat(path=tmp_path / "hb", max_age_s=42.0)
        r = repr(hb)
        assert "Heartbeat" in r
        assert "42.0" in r


# ─────────────────────────────────────────────────────────────────
# LogRotator
# ─────────────────────────────────────────────────────────────────


class TestLogRotator:
    """Log rotation mechanics."""

    def test_no_rotation_when_small(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path, max_size_mb=10.0)
        log = tmp_path / "voice.log"
        log.write_text("small content\n")

        assert rotator.rotate_if_needed() is False

    def test_rotation_when_large(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path, max_size_mb=0.001)  # ~1KB
        log = tmp_path / "voice.log"
        log.write_text("x" * 2000)  # 2KB > 1KB

        assert rotator.rotate_if_needed() is True
        assert not log.exists()  # current rotated away
        assert (tmp_path / "voice.log.1").exists()

    def test_cascading_rotation(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path, max_size_mb=0.001)

        # Create existing rotated files
        (tmp_path / "voice.log.1").write_text("old-1\n")
        (tmp_path / "voice.log.2").write_text("old-2\n")
        (tmp_path / "voice.log").write_text("x" * 2000)

        rotator.rotate_if_needed()

        assert (tmp_path / "voice.log.1").exists()
        assert (tmp_path / "voice.log.2").exists()
        assert (tmp_path / "voice.log.3").exists()
        # .1 should be the old current
        content = (tmp_path / "voice.log.1").read_text()
        assert "x" * 100 in content

    def test_oldest_deleted_at_max(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path, max_files=3, max_size_mb=0.001)

        # Fill up to max
        (tmp_path / "voice.log.1").write_text("a\n")
        (tmp_path / "voice.log.2").write_text("b\n")
        (tmp_path / "voice.log.3").write_text("c-should-be-deleted\n")
        (tmp_path / "voice.log").write_text("x" * 2000)

        rotator.rotate_if_needed()

        # .3 was at max_files, so it gets deleted before cascade
        assert not (tmp_path / "voice.log.4").exists()

    def test_no_rotation_when_file_missing(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path)
        assert rotator.rotate_if_needed() is False

    def test_list_logs(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path)
        (tmp_path / "voice.log").write_text("current\n")
        (tmp_path / "voice.log.1").write_text("old-1\n")
        (tmp_path / "voice.log.2").write_text("old-2\n")

        logs = rotator.list_logs()
        assert len(logs) == 3
        assert logs[0] == tmp_path / "voice.log"

    def test_total_size_mb(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path)
        (tmp_path / "voice.log").write_text("a" * 1024)
        (tmp_path / "voice.log.1").write_text("b" * 1024)

        size = rotator.total_size_mb()
        assert 0.001 < size < 0.01  # ~2KB

    def test_cleanup_old(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path, max_files=3)
        # Create files beyond max
        for i in range(1, 8):
            (tmp_path / f"voice.log.{i}").write_text(f"content-{i}\n")

        deleted = rotator.cleanup_old()
        assert deleted == 4  # files 4, 5, 6, 7
        assert not (tmp_path / "voice.log.4").exists()
        assert (tmp_path / "voice.log.3").exists()

    def test_current_log_property(self, tmp_path):
        from bantz.voice.heartbeat import LogRotator

        rotator = LogRotator(log_dir=tmp_path, log_name="test.log")
        assert rotator.current_log == tmp_path / "test.log"


# ─────────────────────────────────────────────────────────────────
# Pipeline integration
# ─────────────────────────────────────────────────────────────────


class TestPipelineHeartbeat:
    """VoicePipeline._tick_heartbeat wiring."""

    def test_tick_heartbeat_creates_heartbeat(self, tmp_path):
        from bantz.voice.pipeline import VoicePipeline

        hb_path = tmp_path / "hb"
        pipe = VoicePipeline()

        with mock.patch("bantz.voice.heartbeat.Heartbeat") as MockHB:
            instance = MockHB.return_value
            instance.path = hb_path
            pipe._tick_heartbeat()

            MockHB.assert_called_once()
            instance.tick.assert_called_once()

    def test_tick_heartbeat_reuses_instance(self, tmp_path):
        from bantz.voice.heartbeat import Heartbeat
        from bantz.voice.pipeline import VoicePipeline

        hb = Heartbeat(path=tmp_path / "hb")
        pipe = VoicePipeline()
        pipe._heartbeat = hb

        pipe._tick_heartbeat()
        assert (tmp_path / "hb").exists()

    def test_tick_heartbeat_handles_exception(self):
        from bantz.voice.pipeline import VoicePipeline

        pipe = VoicePipeline()

        with mock.patch("bantz.voice.heartbeat.Heartbeat", side_effect=RuntimeError("boom")):
            pipe._tick_heartbeat()  # Should not raise


# ─────────────────────────────────────────────────────────────────
# Watchdog script
# ─────────────────────────────────────────────────────────────────


class TestWatchdogScript:
    """Verify watchdog script file exists and is executable."""

    def test_script_exists(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "watchdog_voice.sh"
        assert script.exists(), f"Watchdog script not found: {script}"

    def test_script_executable(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "watchdog_voice.sh"
        assert os.access(str(script), os.X_OK), "watchdog_voice.sh is not executable"

    def test_script_has_shebang(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "watchdog_voice.sh"
        first_line = script.read_text().split("\n")[0]
        assert first_line.startswith("#!/"), f"Missing shebang: {first_line}"


# ─────────────────────────────────────────────────────────────────
# Systemd service
# ─────────────────────────────────────────────────────────────────


class TestSystemdService:
    """Verify watchdog systemd unit file."""

    def test_service_file_exists(self):
        svc = Path(__file__).resolve().parents[1] / "systemd" / "user" / "bantz-voice-watchdog.service"
        assert svc.exists(), f"Service file not found: {svc}"

    def test_service_has_exec_start(self):
        svc = Path(__file__).resolve().parents[1] / "systemd" / "user" / "bantz-voice-watchdog.service"
        content = svc.read_text()
        assert "ExecStart=" in content
        assert "watchdog_voice.sh" in content

    def test_service_has_restart(self):
        svc = Path(__file__).resolve().parents[1] / "systemd" / "user" / "bantz-voice-watchdog.service"
        content = svc.read_text()
        assert "Restart=always" in content
