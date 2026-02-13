"""Pipeline success-rate and confirmation-rate metrics (Issue #1220).

Reads JSONL turn-metrics file and computes:
- Pipeline success rate  (successful turns / total turns)
- Confirmation trigger rate (confirmation turns / total turns)
- Latency breakdown per phase (p50, p95, max)

Usage::

    from bantz.metrics.pipeline_metrics import compute_pipeline_metrics
    report = compute_pipeline_metrics("artifacts/logs/turn_metrics.jsonl")
    print(report)
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["PipelineMetrics", "compute_pipeline_metrics"]


@dataclass
class PhaseLatency:
    """Percentile latency summary for a pipeline phase."""

    phase: str
    count: int = 0
    p50: float = 0.0
    p95: float = 0.0
    max: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "count": self.count,
            "p50_ms": round(self.p50, 1),
            "p95_ms": round(self.p95, 1),
            "max_ms": round(self.max, 1),
        }


@dataclass
class PipelineMetrics:
    """Aggregated pipeline metrics report."""

    total_turns: int = 0
    successful_turns: int = 0
    failed_turns: int = 0
    success_rate: float = 0.0

    confirmation_triggered: int = 0
    confirmation_rate: float = 0.0

    total_tools_ok: int = 0
    total_tools_fail: int = 0
    tool_success_rate: float = 0.0

    latency_breakdown: List[PhaseLatency] = field(default_factory=list)

    # Per-route success counts
    route_breakdown: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_turns": self.total_turns,
            "successful_turns": self.successful_turns,
            "failed_turns": self.failed_turns,
            "success_rate": round(self.success_rate, 4),
            "confirmation_triggered": self.confirmation_triggered,
            "confirmation_rate": round(self.confirmation_rate, 4),
            "total_tools_ok": self.total_tools_ok,
            "total_tools_fail": self.total_tools_fail,
            "tool_success_rate": round(self.tool_success_rate, 4),
            "latency_breakdown": [l.to_dict() for l in self.latency_breakdown],
            "route_breakdown": self.route_breakdown,
        }

    def __str__(self) -> str:
        lines = [
            "═══ Pipeline Metrics Report ═══",
            f"Turns:        {self.total_turns} total, {self.successful_turns} ok, {self.failed_turns} fail",
            f"Success Rate: {self.success_rate:.1%}",
            f"Confirmation: {self.confirmation_triggered} triggered ({self.confirmation_rate:.1%})",
            f"Tools:        {self.total_tools_ok} ok, {self.total_tools_fail} fail "
            f"({self.tool_success_rate:.1%})",
            "",
            "Latency (ms):",
        ]
        for lat in self.latency_breakdown:
            lines.append(
                f"  {lat.phase:<12s}  p50={lat.p50:>7.0f}  p95={lat.p95:>7.0f}  max={lat.max:>7.0f}  (n={lat.count})"
            )
        if self.route_breakdown:
            lines.append("")
            lines.append("Per-route:")
            for route, counts in sorted(self.route_breakdown.items()):
                lines.append(f"  {route:<16s}  ok={counts.get('ok', 0)}  fail={counts.get('fail', 0)}")
        return "\n".join(lines)


def _percentile(data: List[float], pct: float) -> float:
    """Simple percentile calculation."""
    if not data:
        return 0.0
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(data_sorted):
        return data_sorted[-1]
    return data_sorted[f] + (k - f) * (data_sorted[c] - data_sorted[f])


def compute_pipeline_metrics(
    path: str = "artifacts/logs/turn_metrics.jsonl",
    *,
    last_n: Optional[int] = None,
) -> PipelineMetrics:
    """Compute pipeline metrics from JSONL turn metrics file.

    Parameters
    ----------
    path:
        Path to the turn_metrics JSONL file.
    last_n:
        If set, only consider the last *n* records.
    """
    records: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        logger.warning("Turn metrics file not found: %s", path)
        return PipelineMetrics()

    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if last_n and last_n > 0:
        records = records[-last_n:]

    if not records:
        return PipelineMetrics()

    m = PipelineMetrics()
    m.total_turns = len(records)

    # Phase latency collectors
    phase_data: Dict[str, List[float]] = {
        "router": [],
        "tool": [],
        "finalize": [],
        "total": [],
    }

    for rec in records:
        # Success tracking
        if rec.get("success", True):
            m.successful_turns += 1
        else:
            m.failed_turns += 1

        # Confirmation tracking
        if rec.get("confirmation_triggered", False):
            m.confirmation_triggered += 1

        # Tool tracking
        m.total_tools_ok += rec.get("tools_ok", 0)
        m.total_tools_fail += rec.get("tools_fail", 0)

        # Route breakdown
        route = rec.get("route", "unknown")
        if route not in m.route_breakdown:
            m.route_breakdown[route] = {"ok": 0, "fail": 0}
        if rec.get("success", True):
            m.route_breakdown[route]["ok"] += 1
        else:
            m.route_breakdown[route]["fail"] += 1

        # Latency collection
        for phase, key in [
            ("router", "router_ms"),
            ("tool", "tool_ms"),
            ("finalize", "finalize_ms"),
            ("total", "total_ms"),
        ]:
            val = rec.get(key)
            if val is not None:
                phase_data[phase].append(float(val))

    # Compute rates
    m.success_rate = m.successful_turns / m.total_turns if m.total_turns else 0.0
    m.confirmation_rate = m.confirmation_triggered / m.total_turns if m.total_turns else 0.0
    total_tools = m.total_tools_ok + m.total_tools_fail
    m.tool_success_rate = m.total_tools_ok / total_tools if total_tools else 1.0

    # Compute latency percentiles
    for phase in ("router", "tool", "finalize", "total"):
        data = phase_data[phase]
        lat = PhaseLatency(
            phase=phase,
            count=len(data),
            p50=_percentile(data, 50),
            p95=_percentile(data, 95),
            max=max(data) if data else 0.0,
        )
        m.latency_breakdown.append(lat)

    return m


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "artifacts/logs/turn_metrics.jsonl"
    report = compute_pipeline_metrics(path)
    print(report)
    print()
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
