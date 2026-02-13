"""System health check skill — CPU/RAM/Disk/GPU (Issue #295).

Provides system metrics collection, verdict logic, and voice-friendly
formatting for the ``system.health_check`` tool.

Usage::

    from bantz.skills.sysinfo import run_health_check
    text = run_health_check()
"""

from __future__ import annotations

import logging

from bantz.skills.sysinfo.collector import SystemMetrics, collect_metrics
from bantz.skills.sysinfo.formatter import format_for_voice
from bantz.skills.sysinfo.verdict import Verdict, compute_verdict

logger = logging.getLogger(__name__)

__all__ = [
    "SystemMetrics",
    "collect_metrics",
    "compute_verdict",
    "format_for_voice",
    "run_health_check",
    "Verdict",
]


def run_health_check() -> str:
    """Collect metrics, compute verdict, and return voice-friendly output.

    This is the main entry point for the ``system.health_check`` tool.
    Never raises — returns a safe Turkish fallback on any failure.
    """
    try:
        logger.debug("[sysinfo] collecting system metrics …")
        metrics = collect_metrics()
        logger.debug("[sysinfo] metrics collected: cpu=%.1f%%, ram=%.1f%%", metrics.cpu_percent, metrics.ram_percent)

        verdict, warnings = compute_verdict(metrics)
        logger.debug("[sysinfo] verdict=%s, warnings=%d", verdict.value, len(warnings))

        text = format_for_voice(metrics, verdict, warnings)
        logger.debug("[sysinfo] formatted output: %s", text[:120])
        return text
    except Exception as exc:
        logger.error("[sysinfo] health check failed: %s", exc, exc_info=True)
        return "Üzgünüm efendim, sistem bilgilerini okuyamadım. Lütfen tekrar deneyin."
