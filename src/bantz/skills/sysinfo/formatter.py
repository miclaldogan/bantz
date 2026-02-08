"""Voice-friendly formatter for system health check (Issue #295).

Produces short, clear Turkish output suitable for TTS:
  - 3–4 main metrics
  - Verdict line
  - Warnings if any
"""

from __future__ import annotations

import logging
from typing import List

from bantz.skills.sysinfo.collector import SystemMetrics
from bantz.skills.sysinfo.verdict import Verdict

logger = logging.getLogger(__name__)

__all__ = ["format_for_voice"]


def format_for_voice(
    metrics: SystemMetrics,
    verdict: Verdict,
    warnings: List[str],
) -> str:
    """Format system metrics into voice-friendly Turkish text.

    Parameters
    ----------
    metrics:
        Collected system metrics snapshot.
    verdict:
        Health verdict (ready / warning / critical).
    warnings:
        List of Turkish warning messages.

    Returns
    -------
    str
        Multi-line text suitable for TTS.
    """
    lines: List[str] = ["Sisteminizi kontrol ettim efendim:"]

    # ── Core metrics ──────────────────────────────────────────────
    lines.append(
        "- CPU yükü: %{:.0f}, {}".format(
            metrics.cpu_percent,
            _cpu_comment(metrics.cpu_percent),
        )
    )

    lines.append(
        "- RAM kullanımı: {:.1f} GB / {:.1f} GB (%{:.0f})".format(
            metrics.ram_used_gb,
            metrics.ram_total_gb,
            metrics.ram_percent,
        )
    )

    lines.append(
        "- Disk: {:.0f} GB boş alan var".format(metrics.disk_free_gb)
    )

    # ── GPU (optional) ────────────────────────────────────────────
    if metrics.gpu_memory_used_gb is not None and metrics.gpu_memory_total_gb is not None:
        lines.append(
            "- GPU belleği: {:.1f} GB / {:.1f} GB kullanımda".format(
                metrics.gpu_memory_used_gb,
                metrics.gpu_memory_total_gb,
            )
        )

    # ── Verdict ───────────────────────────────────────────────────
    lines.append("")
    lines.append(_verdict_text(verdict))

    # ── Warnings ──────────────────────────────────────────────────
    if warnings:
        for w in warnings:
            lines.append(f"  ⚠️ {w}")

    return "\n".join(lines)


def _cpu_comment(pct: float) -> str:
    """Short Turkish comment for CPU usage."""
    if pct < 30:
        return "gayet iyi"
    if pct < 60:
        return "normal"
    if pct < 80:
        return "biraz yüksek"
    return "çok yüksek"


def _verdict_text(verdict: Verdict) -> str:
    """Turkish verdict sentence."""
    if verdict == Verdict.READY:
        return "Sonuç: Projeye başlamaya hazırsınız efendim. Sistem rahat."
    if verdict == Verdict.WARNING:
        return "Sonuç: Çalışabilirsiniz ama bazı uyarılar var:"
    # CRITICAL
    return "Sonuç: Kritik kaynak sorunu tespit edildi:"
