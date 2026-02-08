"""Verdict logic for system health check (Issue #295).

Evaluates collected metrics against configurable thresholds and returns
a verdict + list of warnings in Turkish.

Verdict levels:
  - ``ready``    — sistem rahat, projeye hazır
  - ``warning``  — uyarılar var ama çalışabilir
  - ``critical`` — ciddi kaynak sorunu
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

from bantz.skills.sysinfo.collector import SystemMetrics

logger = logging.getLogger(__name__)

__all__ = ["Verdict", "VerdictThresholds", "compute_verdict"]


class Verdict(Enum):
    """Health check verdict."""

    READY = "ready"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class VerdictThresholds:
    """Configurable thresholds for system health evaluation.

    Defaults match the issue spec.
    """

    cpu_warning: float = 80.0
    ram_warning: float = 85.0
    disk_warning_gb: float = 10.0
    disk_critical_gb: float = 5.0
    gpu_warning: float = 90.0

    # Load average: warning if > 2x CPU cores
    load_factor: float = 2.0


# Default thresholds (singleton)
DEFAULT_THRESHOLDS = VerdictThresholds()


def compute_verdict(
    metrics: SystemMetrics,
    thresholds: VerdictThresholds | None = None,
) -> Tuple[Verdict, List[str]]:
    """Compute a health verdict from system metrics.

    Parameters
    ----------
    metrics:
        Collected system metrics.
    thresholds:
        Optional custom thresholds. Defaults to spec values.

    Returns
    -------
    tuple of (Verdict, list[str])
        Verdict enum and list of Turkish warning messages.
    """
    t = thresholds or DEFAULT_THRESHOLDS
    warnings: List[str] = []

    # ── Disk (critical first — early return) ──────────────────────
    if metrics.disk_free_gb < t.disk_critical_gb:
        logger.debug("[verdict] CRITICAL: disk %.1f GB < %.1f GB", metrics.disk_free_gb, t.disk_critical_gb)
        return Verdict.CRITICAL, [
            "Disk neredeyse dolu! ({:.1f} GB kaldı)".format(metrics.disk_free_gb)
        ]

    if metrics.disk_free_gb < t.disk_warning_gb:
        warnings.append(
            "Disk alanı azalıyor ({:.1f} GB kaldı)".format(metrics.disk_free_gb)
        )

    # ── CPU ───────────────────────────────────────────────────────
    if metrics.cpu_percent > t.cpu_warning:
        warnings.append(
            "CPU yükü yüksek (%{:.0f})".format(metrics.cpu_percent)
        )

    # ── RAM ───────────────────────────────────────────────────────
    if metrics.ram_percent > t.ram_warning:
        warnings.append(
            "RAM dolmak üzere (%{:.0f})".format(metrics.ram_percent)
        )

    # ── GPU ───────────────────────────────────────────────────────
    if metrics.gpu_utilization is not None and metrics.gpu_utilization > t.gpu_warning:
        warnings.append(
            "GPU belleği yüksek (%{:.0f})".format(metrics.gpu_utilization)
        )

    # ── Load average ──────────────────────────────────────────────
    load_threshold = metrics.cpu_count * t.load_factor
    if metrics.load_avg_1m > load_threshold:
        warnings.append(
            "Load average yüksek ({:.1f}, {} çekirdek için)".format(
                metrics.load_avg_1m, metrics.cpu_count
            )
        )

    # ── Final verdict ─────────────────────────────────────────────
    if warnings:
        logger.debug("[verdict] WARNING: %d issues", len(warnings))
        return Verdict.WARNING, warnings

    logger.debug("[verdict] READY — no issues")
    return Verdict.READY, []
