"""System metrics collector — CPU, RAM, Disk, GPU (Issue #295).

Uses ``psutil`` for CPU/RAM/Disk and ``nvidia-smi`` for GPU.
GPU metrics are optional — gracefully skipped when unavailable.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["SystemMetrics", "collect_metrics"]


@dataclass
class SystemMetrics:
    """Snapshot of system resource usage.

    Attributes
    ----------
    cpu_percent:
        CPU utilisation (0–100 aggregated).
    cpu_count:
        Number of logical CPU cores.
    ram_used_gb:
        Used RAM in GB.
    ram_total_gb:
        Total RAM in GB.
    ram_percent:
        RAM usage percentage.
    disk_free_gb:
        Free disk space in GB (root partition).
    disk_total_gb:
        Total disk space in GB.
    disk_percent:
        Disk usage percentage.
    gpu_memory_used_gb:
        GPU VRAM used (None if no GPU).
    gpu_memory_total_gb:
        GPU VRAM total (None if no GPU).
    gpu_utilization:
        GPU utilisation % (None if no GPU).
    uptime_hours:
        System uptime in hours.
    load_avg_1m:
        1-minute load average.
    """

    cpu_percent: float = 0.0
    cpu_count: int = 1
    ram_used_gb: float = 0.0
    ram_total_gb: float = 1.0
    ram_percent: float = 0.0
    disk_free_gb: float = 0.0
    disk_total_gb: float = 1.0
    disk_percent: float = 0.0
    gpu_memory_used_gb: Optional[float] = None
    gpu_memory_total_gb: Optional[float] = None
    gpu_utilization: Optional[float] = None
    uptime_hours: float = 0.0
    load_avg_1m: float = 0.0


# ─────────────────────────────────────────────────────────────────
# psutil-based collectors
# ─────────────────────────────────────────────────────────────────


def _collect_cpu() -> tuple[float, int]:
    """Return (cpu_percent, cpu_count)."""
    try:
        import psutil  # type: ignore[import-untyped]

        pct = psutil.cpu_percent(interval=0.3)
        count = psutil.cpu_count(logical=True) or 1
        return pct, count
    except ImportError:
        logger.debug("[sysinfo] psutil not available — using fallback CPU")
        count = os.cpu_count() or 1
        # Fallback: read /proc/loadavg
        try:
            load = os.getloadavg()[0]
            pct = min(100.0, (load / count) * 100)
        except (OSError, AttributeError):
            pct = 0.0
        return pct, count


def _collect_ram() -> tuple[float, float, float]:
    """Return (used_gb, total_gb, percent)."""
    try:
        import psutil  # type: ignore[import-untyped]

        mem = psutil.virtual_memory()
        total = mem.total / (1024**3)
        used = mem.used / (1024**3)
        return used, total, mem.percent
    except ImportError:
        logger.debug("[sysinfo] psutil not available — using fallback RAM")
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info: dict[str, float] = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    val = float(parts[1]) / (1024 * 1024)  # kB → GB
                    info[key] = val
            total = info.get("MemTotal", 1.0)
            avail = info.get("MemAvailable", total)
            used = total - avail
            pct = (used / total) * 100 if total > 0 else 0.0
            return used, total, pct
        except Exception:
            return 0.0, 1.0, 0.0


def _collect_disk(path: str = "/") -> tuple[float, float, float]:
    """Return (free_gb, total_gb, used_pct)."""
    try:
        total, used, free = shutil.disk_usage(path)
        total_gb = total / (1024**3)
        free_gb = free / (1024**3)
        used_pct = (used / total) * 100 if total > 0 else 0.0
        return free_gb, total_gb, used_pct
    except Exception:
        return 0.0, 1.0, 0.0


def _collect_uptime() -> float:
    """Return uptime in hours."""
    try:
        import psutil  # type: ignore[import-untyped]

        boot = psutil.boot_time()
        return (datetime.datetime.now().timestamp() - boot) / 3600
    except ImportError:
        try:
            with open("/proc/uptime") as f:
                seconds = float(f.read().split()[0])
            return seconds / 3600
        except Exception:
            return 0.0


def _collect_load() -> float:
    """Return 1-minute load average."""
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return 0.0


# ─────────────────────────────────────────────────────────────────
# GPU collector (nvidia-smi)
# ─────────────────────────────────────────────────────────────────


def _collect_gpu() -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (used_gb, total_gb, util_pct) or (None, None, None).

    Calls ``nvidia-smi`` — graceful when absent.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, None, None

        line = result.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            return None, None, None

        used_mb = float(parts[0])
        total_mb = float(parts[1])
        util = float(parts[2])
        return used_mb / 1024, total_mb / 1024, util
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        logger.debug("[sysinfo] nvidia-smi not available — skipping GPU metrics")
        return None, None, None


# ─────────────────────────────────────────────────────────────────
# Main collector
# ─────────────────────────────────────────────────────────────────


def collect_metrics() -> SystemMetrics:
    """Collect a full system metrics snapshot.

    CPU, RAM, and Disk are always collected.
    GPU metrics are optional (graceful when unavailable).
    """
    cpu_pct, cpu_count = _collect_cpu()
    ram_used, ram_total, ram_pct = _collect_ram()
    disk_free, disk_total, disk_pct = _collect_disk()
    uptime = _collect_uptime()
    load_1m = _collect_load()
    gpu_used, gpu_total, gpu_util = _collect_gpu()

    return SystemMetrics(
        cpu_percent=cpu_pct,
        cpu_count=cpu_count,
        ram_used_gb=ram_used,
        ram_total_gb=ram_total,
        ram_percent=ram_pct,
        disk_free_gb=disk_free,
        disk_total_gb=disk_total,
        disk_percent=disk_pct,
        gpu_memory_used_gb=gpu_used,
        gpu_memory_total_gb=gpu_total,
        gpu_utilization=gpu_util,
        uptime_hours=uptime,
        load_avg_1m=load_1m,
    )
