"""Tests for Issue #295 — System health check skill.

Covers:
  - SystemMetrics: defaults, field types
  - collect_metrics: mocked psutil + nvidia-smi
  - compute_verdict: ready/warning/critical, threshold logic
  - format_for_voice: Turkish output, GPU optional, structure
  - run_health_check: integration, error fallback
  - VerdictThresholds: custom thresholds
  - File existence
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# SystemMetrics
# ─────────────────────────────────────────────────────────────────


class TestSystemMetrics:
    """SystemMetrics dataclass."""

    def test_defaults(self):
        from bantz.skills.sysinfo.collector import SystemMetrics

        m = SystemMetrics()
        assert m.cpu_percent == 0.0
        assert m.cpu_count == 1
        assert m.gpu_memory_used_gb is None
        assert m.gpu_utilization is None

    def test_custom_values(self):
        from bantz.skills.sysinfo.collector import SystemMetrics

        m = SystemMetrics(
            cpu_percent=45.0,
            cpu_count=8,
            ram_used_gb=12.0,
            ram_total_gb=32.0,
            ram_percent=37.5,
            disk_free_gb=120.0,
            disk_total_gb=500.0,
            disk_percent=76.0,
            gpu_memory_used_gb=4.0,
            gpu_memory_total_gb=8.0,
            gpu_utilization=50.0,
            uptime_hours=48.0,
            load_avg_1m=2.5,
        )
        assert m.cpu_percent == 45.0
        assert m.ram_total_gb == 32.0
        assert m.gpu_memory_total_gb == 8.0


# ─────────────────────────────────────────────────────────────────
# collect_metrics (mocked)
# ─────────────────────────────────────────────────────────────────


class TestCollectMetrics:
    """Metrics collection with mocked psutil."""

    def _mock_psutil(self):
        """Create a psutil mock module."""
        psutil_mock = mock.MagicMock()
        psutil_mock.cpu_percent.return_value = 15.0
        psutil_mock.cpu_count.return_value = 8

        mem = mock.MagicMock()
        mem.total = 32 * (1024**3)
        mem.used = 8 * (1024**3)
        mem.percent = 25.0
        psutil_mock.virtual_memory.return_value = mem

        psutil_mock.boot_time.return_value = 0.0

        return psutil_mock

    def test_collect_returns_metrics(self):
        from bantz.skills.sysinfo.collector import collect_metrics, SystemMetrics

        psutil_mock = self._mock_psutil()
        with mock.patch.dict("sys.modules", {"psutil": psutil_mock}):
            with mock.patch("bantz.skills.sysinfo.collector._collect_gpu", return_value=(None, None, None)):
                m = collect_metrics()
        assert isinstance(m, SystemMetrics)
        assert m.cpu_percent == 15.0
        assert m.cpu_count == 8

    def test_no_gpu(self):
        from bantz.skills.sysinfo.collector import collect_metrics

        psutil_mock = self._mock_psutil()
        with mock.patch.dict("sys.modules", {"psutil": psutil_mock}):
            with mock.patch("bantz.skills.sysinfo.collector._collect_gpu", return_value=(None, None, None)):
                m = collect_metrics()
        assert m.gpu_memory_used_gb is None
        assert m.gpu_memory_total_gb is None
        assert m.gpu_utilization is None

    def test_with_gpu(self):
        from bantz.skills.sysinfo.collector import collect_metrics

        psutil_mock = self._mock_psutil()
        with mock.patch.dict("sys.modules", {"psutil": psutil_mock}):
            with mock.patch("bantz.skills.sysinfo.collector._collect_gpu", return_value=(4.0, 8.0, 50.0)):
                m = collect_metrics()
        assert m.gpu_memory_used_gb == 4.0
        assert m.gpu_memory_total_gb == 8.0
        assert m.gpu_utilization == 50.0


# ─────────────────────────────────────────────────────────────────
# _collect_gpu
# ─────────────────────────────────────────────────────────────────


class TestCollectGPU:
    """GPU collection via nvidia-smi."""

    def test_no_nvidia_smi(self):
        from bantz.skills.sysinfo.collector import _collect_gpu

        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            used, total, util = _collect_gpu()
        assert used is None
        assert total is None
        assert util is None

    def test_nvidia_smi_success(self):
        from bantz.skills.sysinfo.collector import _collect_gpu

        result = mock.MagicMock()
        result.returncode = 0
        result.stdout = "4096, 8192, 50\n"

        with mock.patch("subprocess.run", return_value=result):
            used, total, util = _collect_gpu()
        assert used == 4.0  # 4096 / 1024
        assert total == 8.0  # 8192 / 1024
        assert util == 50.0

    def test_nvidia_smi_failure(self):
        from bantz.skills.sysinfo.collector import _collect_gpu

        result = mock.MagicMock()
        result.returncode = 1
        result.stdout = ""

        with mock.patch("subprocess.run", return_value=result):
            used, total, util = _collect_gpu()
        assert used is None

    def test_nvidia_smi_timeout(self):
        from bantz.skills.sysinfo.collector import _collect_gpu

        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)):
            used, total, util = _collect_gpu()
        assert used is None


# ─────────────────────────────────────────────────────────────────
# CPU / RAM fallbacks
# ─────────────────────────────────────────────────────────────────


class TestFallbacks:
    """Fallback metric collection without psutil."""

    def test_cpu_fallback_with_loadavg(self):
        from bantz.skills.sysinfo.collector import _collect_cpu

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _import_no_psutil(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("no psutil")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=_import_no_psutil):
            with mock.patch("os.cpu_count", return_value=4):
                with mock.patch("os.getloadavg", return_value=(2.0, 1.5, 1.0)):
                    pct, count = _collect_cpu()
        assert count == 4
        assert pct == 50.0  # 2.0/4 * 100

    def test_collect_load(self):
        from bantz.skills.sysinfo.collector import _collect_load

        with mock.patch("os.getloadavg", return_value=(1.5, 1.0, 0.5)):
            load = _collect_load()
        assert load == 1.5


# ─────────────────────────────────────────────────────────────────
# Verdict
# ─────────────────────────────────────────────────────────────────


class TestVerdict:
    """Health verdict logic."""

    def _make_metrics(self, **kw):
        from bantz.skills.sysinfo.collector import SystemMetrics
        return SystemMetrics(**kw)

    def test_ready(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=15.0, ram_percent=25.0,
            disk_free_gb=120.0, disk_total_gb=500.0,
            cpu_count=8, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.READY
        assert warnings == []

    def test_cpu_warning(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=90.0, ram_percent=25.0,
            disk_free_gb=120.0, cpu_count=8, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.WARNING
        assert any("CPU" in w for w in warnings)

    def test_ram_warning(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=10.0, ram_percent=90.0,
            disk_free_gb=120.0, cpu_count=8, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.WARNING
        assert any("RAM" in w for w in warnings)

    def test_disk_warning(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=10.0, ram_percent=25.0,
            disk_free_gb=8.0, cpu_count=8, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.WARNING
        assert any("Disk" in w for w in warnings)

    def test_disk_critical(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=10.0, ram_percent=25.0,
            disk_free_gb=3.0, cpu_count=8, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.CRITICAL
        assert any("dolu" in w for w in warnings)

    def test_gpu_warning(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=10.0, ram_percent=25.0,
            disk_free_gb=120.0, cpu_count=8, load_avg_1m=1.0,
            gpu_utilization=95.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.WARNING
        assert any("GPU" in w for w in warnings)

    def test_load_warning(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=10.0, ram_percent=25.0,
            disk_free_gb=120.0, cpu_count=4, load_avg_1m=10.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.WARNING
        assert any("Load" in w for w in warnings)

    def test_multiple_warnings(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=90.0, ram_percent=90.0,
            disk_free_gb=8.0, cpu_count=4, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.WARNING
        assert len(warnings) >= 3

    def test_custom_thresholds(self):
        from bantz.skills.sysinfo.verdict import Verdict, VerdictThresholds, compute_verdict

        m = self._make_metrics(
            cpu_percent=50.0, ram_percent=25.0,
            disk_free_gb=120.0, cpu_count=8, load_avg_1m=1.0,
        )
        # Strict thresholds
        strict = VerdictThresholds(cpu_warning=40.0)
        verdict, warnings = compute_verdict(m, strict)
        assert verdict == Verdict.WARNING
        assert any("CPU" in w for w in warnings)

    def test_disk_critical_overrides_other_warnings(self):
        from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

        m = self._make_metrics(
            cpu_percent=90.0, ram_percent=90.0,
            disk_free_gb=2.0, cpu_count=4, load_avg_1m=1.0,
        )
        verdict, warnings = compute_verdict(m)
        assert verdict == Verdict.CRITICAL
        # Only disk warning, early return
        assert len(warnings) == 1


# ─────────────────────────────────────────────────────────────────
# Formatter
# ─────────────────────────────────────────────────────────────────


class TestFormatter:
    """Voice-friendly formatter."""

    def _make_metrics(self, **kw):
        from bantz.skills.sysinfo.collector import SystemMetrics
        return SystemMetrics(**kw)

    def test_ready_format(self):
        from bantz.skills.sysinfo.formatter import format_for_voice
        from bantz.skills.sysinfo.verdict import Verdict

        m = self._make_metrics(
            cpu_percent=15.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=120.0,
        )
        text = format_for_voice(m, Verdict.READY, [])
        assert "Sisteminizi kontrol ettim" in text
        assert "CPU" in text
        assert "RAM" in text
        assert "Disk" in text
        assert "hazırsınız" in text

    def test_warning_format(self):
        from bantz.skills.sysinfo.formatter import format_for_voice
        from bantz.skills.sysinfo.verdict import Verdict

        m = self._make_metrics(
            cpu_percent=90.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=120.0,
        )
        text = format_for_voice(m, Verdict.WARNING, ["CPU yükü yüksek (%90)"])
        assert "uyarılar var" in text
        assert "⚠️" in text

    def test_critical_format(self):
        from bantz.skills.sysinfo.formatter import format_for_voice
        from bantz.skills.sysinfo.verdict import Verdict

        m = self._make_metrics(
            cpu_percent=10.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=3.0,
        )
        text = format_for_voice(m, Verdict.CRITICAL, ["Disk neredeyse dolu!"])
        assert "Kritik" in text

    def test_gpu_in_output(self):
        from bantz.skills.sysinfo.formatter import format_for_voice
        from bantz.skills.sysinfo.verdict import Verdict

        m = self._make_metrics(
            cpu_percent=15.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=120.0,
            gpu_memory_used_gb=4.0, gpu_memory_total_gb=8.0,
        )
        text = format_for_voice(m, Verdict.READY, [])
        assert "GPU" in text

    def test_no_gpu_in_output(self):
        from bantz.skills.sysinfo.formatter import format_for_voice
        from bantz.skills.sysinfo.verdict import Verdict

        m = self._make_metrics(
            cpu_percent=15.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=120.0,
        )
        text = format_for_voice(m, Verdict.READY, [])
        assert "GPU" not in text

    def test_cpu_comment_low(self):
        from bantz.skills.sysinfo.formatter import _cpu_comment

        assert _cpu_comment(10.0) == "gayet iyi"

    def test_cpu_comment_normal(self):
        from bantz.skills.sysinfo.formatter import _cpu_comment

        assert _cpu_comment(50.0) == "normal"

    def test_cpu_comment_high(self):
        from bantz.skills.sysinfo.formatter import _cpu_comment

        assert _cpu_comment(70.0) == "biraz yüksek"

    def test_cpu_comment_very_high(self):
        from bantz.skills.sysinfo.formatter import _cpu_comment

        assert _cpu_comment(95.0) == "çok yüksek"


# ─────────────────────────────────────────────────────────────────
# run_health_check (integration)
# ─────────────────────────────────────────────────────────────────


class TestRunHealthCheck:
    """Integration test for run_health_check."""

    def test_happy_path(self):
        from bantz.skills.sysinfo import run_health_check
        from bantz.skills.sysinfo.collector import SystemMetrics

        m = SystemMetrics(
            cpu_percent=15.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=120.0, disk_total_gb=500.0, disk_percent=76.0,
            uptime_hours=48.0, load_avg_1m=1.0,
        )
        with mock.patch("bantz.skills.sysinfo.collect_metrics", return_value=m):
            text = run_health_check()
        assert "Sisteminizi kontrol ettim" in text
        assert "hazırsınız" in text

    def test_error_fallback(self):
        from bantz.skills.sysinfo import run_health_check

        with mock.patch("bantz.skills.sysinfo.collect_metrics", side_effect=RuntimeError("boom")):
            text = run_health_check()
        assert "Üzgünüm" in text
        assert "tekrar deneyin" in text

    def test_warning_path(self):
        from bantz.skills.sysinfo import run_health_check
        from bantz.skills.sysinfo.collector import SystemMetrics

        m = SystemMetrics(
            cpu_percent=90.0, cpu_count=8,
            ram_used_gb=28.0, ram_total_gb=32.0, ram_percent=87.5,
            disk_free_gb=8.0, disk_total_gb=500.0, disk_percent=98.4,
            uptime_hours=48.0, load_avg_1m=1.0,
        )
        with mock.patch("bantz.skills.sysinfo.collect_metrics", return_value=m):
            text = run_health_check()
        assert "uyarılar var" in text

    def test_critical_path(self):
        from bantz.skills.sysinfo import run_health_check
        from bantz.skills.sysinfo.collector import SystemMetrics

        m = SystemMetrics(
            cpu_percent=10.0, cpu_count=8,
            ram_used_gb=8.0, ram_total_gb=32.0, ram_percent=25.0,
            disk_free_gb=2.0, disk_total_gb=500.0, disk_percent=99.6,
            uptime_hours=48.0, load_avg_1m=1.0,
        )
        with mock.patch("bantz.skills.sysinfo.collect_metrics", return_value=m):
            text = run_health_check()
        assert "Kritik" in text


# ─────────────────────────────────────────────────────────────────
# VerdictThresholds
# ─────────────────────────────────────────────────────────────────


class TestVerdictThresholds:
    """Configurable thresholds."""

    def test_defaults(self):
        from bantz.skills.sysinfo.verdict import VerdictThresholds

        t = VerdictThresholds()
        assert t.cpu_warning == 80.0
        assert t.ram_warning == 85.0
        assert t.disk_warning_gb == 10.0
        assert t.disk_critical_gb == 5.0
        assert t.gpu_warning == 90.0

    def test_custom(self):
        from bantz.skills.sysinfo.verdict import VerdictThresholds

        t = VerdictThresholds(cpu_warning=50.0, disk_critical_gb=20.0)
        assert t.cpu_warning == 50.0
        assert t.disk_critical_gb == 20.0


# ─────────────────────────────────────────────────────────────────
# Verdict enum
# ─────────────────────────────────────────────────────────────────


class TestVerdictEnum:
    """Verdict enum values."""

    def test_values(self):
        from bantz.skills.sysinfo.verdict import Verdict

        assert Verdict.READY.value == "ready"
        assert Verdict.WARNING.value == "warning"
        assert Verdict.CRITICAL.value == "critical"


# ─────────────────────────────────────────────────────────────────
# File existence
# ─────────────────────────────────────────────────────────────────


class TestFileExistence:
    """Verify Issue #295 files exist."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_init_exists(self):
        assert (self.ROOT / "src" / "bantz" / "skills" / "sysinfo" / "__init__.py").is_file()

    def test_collector_exists(self):
        assert (self.ROOT / "src" / "bantz" / "skills" / "sysinfo" / "collector.py").is_file()

    def test_verdict_exists(self):
        assert (self.ROOT / "src" / "bantz" / "skills" / "sysinfo" / "verdict.py").is_file()

    def test_formatter_exists(self):
        assert (self.ROOT / "src" / "bantz" / "skills" / "sysinfo" / "formatter.py").is_file()
