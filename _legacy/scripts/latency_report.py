#!/usr/bin/env python3
"""Latency report generator — reads turn_metrics.jsonl (Issue #302).

Computes per-phase p50 / p95 / p99 percentiles and outputs a Markdown
report or JSON summary.

Usage::

    python scripts/latency_report.py                           # last 24h, markdown
    python scripts/latency_report.py --hours 1                 # last 1h
    python scripts/latency_report.py --format json             # JSON output
    python scripts/latency_report.py --file path/to/metrics.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ── Defaults ──────────────────────────────────────────────────────

DEFAULT_METRICS_FILE = "artifacts/logs/turn_metrics.jsonl"

PHASES = ["asr_ms", "router_ms", "tool_ms", "finalize_ms", "tts_ms", "total_ms"]
PHASE_LABELS = {
    "asr_ms": "ASR",
    "router_ms": "Router",
    "tool_ms": "Tool",
    "finalize_ms": "Finalize",
    "tts_ms": "TTS",
    "total_ms": "Total (E2E)",
}

BUDGETS = {
    "asr_ms": 500,
    "router_ms": 500,
    "tool_ms": 2000,
    "finalize_ms": 2000,
    "tts_ms": 500,
    "total_ms": 5000,
}


# ── Helpers ───────────────────────────────────────────────────────

def _percentile(values: Sequence[float], p: float) -> float:
    """Interpolated percentile (p in 0–100)."""
    if not values:
        return 0.0
    sv = sorted(values)
    n = len(sv)
    if n == 1:
        return sv[0]
    rank = (p / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sv[lo] + frac * (sv[hi] - sv[lo])


def _read_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    """Read JSONL, skip malformed lines."""
    records: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        print(f"Hata: {p} bulunamadı.", file=sys.stderr)
        return records
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _filter_by_time(
    records: List[Dict[str, Any]], hours: Optional[float]
) -> List[Dict[str, Any]]:
    """Filter records by timestamp within last *hours*."""
    if hours is None or hours <= 0:
        return records

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_str = cutoff.isoformat()

    filtered = []
    for r in records:
        ts = r.get("timestamp", "")
        if ts >= cutoff_str:
            filtered.append(r)
    return filtered


# ── Report generation ─────────────────────────────────────────────

def _compute_stats(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Compute per-phase statistics."""
    stats: Dict[str, Dict[str, Any]] = {}

    for phase in PHASES:
        values = [
            float(r[phase])
            for r in records
            if phase in r and r[phase] is not None
        ]
        if not values:
            stats[phase] = {"count": 0, "p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0, "mean": 0}
            continue

        stats[phase] = {
            "count": len(values),
            "p50": round(_percentile(values, 50), 1),
            "p95": round(_percentile(values, 95), 1),
            "p99": round(_percentile(values, 99), 1),
            "min": round(min(values), 1),
            "max": round(max(values), 1),
            "mean": round(sum(values) / len(values), 1),
        }

    return stats


def _budget_violations(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count records with budget violations."""
    violations: Dict[str, int] = {}
    for r in records:
        bv = r.get("budget_violations", [])
        for v in bv:
            phase = v.split(":")[0] if ":" in v else v
            violations[phase] = violations.get(phase, 0) + 1
    return violations


def _route_distribution(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count records per route."""
    routes: Dict[str, int] = {}
    for r in records:
        route = r.get("route", "unknown")
        routes[route] = routes.get(route, 0) + 1
    return dict(sorted(routes.items(), key=lambda x: -x[1]))


def generate_markdown_report(
    records: List[Dict[str, Any]],
    hours: Optional[float] = None,
) -> str:
    """Generate a Markdown latency report."""
    stats = _compute_stats(records)
    violations = _budget_violations(records)
    routes = _route_distribution(records)

    lines: List[str] = []
    lines.append("# 📊 Bantz Latency Report")
    lines.append("")

    period = f"son {hours:.0f} saat" if hours else "tüm kayıtlar"
    lines.append(f"**Dönem:** {period}  ")
    lines.append(f"**Toplam turn:** {len(records)}  ")
    ts_list = [r.get("timestamp", "") for r in records if r.get("timestamp")]
    if ts_list:
        lines.append(f"**İlk:** {min(ts_list)[:19]}  ")
        lines.append(f"**Son:** {max(ts_list)[:19]}  ")
    lines.append("")

    # ── Per-phase table ──
    lines.append("## Phase Latency (ms)")
    lines.append("")
    lines.append("| Phase | Count | p50 | p95 | p99 | Min | Max | Budget |")
    lines.append("|-------|------:|----:|----:|----:|----:|----:|-------:|")

    for phase in PHASES:
        s = stats.get(phase, {})
        label = PHASE_LABELS.get(phase, phase)
        budget = BUDGETS.get(phase, "-")
        count = s.get("count", 0)
        if count == 0:
            lines.append(f"| {label} | 0 | - | - | - | - | - | {budget} |")
            continue

        p95 = s["p95"]
        p95_str = f"**{p95}** ⚠" if isinstance(budget, int) and p95 > budget else str(p95)
        lines.append(
            f"| {label} | {count} | {s['p50']} | {p95_str} | {s['p99']} | {s['min']} | {s['max']} | {budget} |"
        )

    lines.append("")

    # ── Budget violations ──
    if violations:
        lines.append("## Budget Violations")
        lines.append("")
        for phase, cnt in sorted(violations.items(), key=lambda x: -x[1]):
            pct = (cnt / len(records)) * 100 if records else 0
            lines.append(f"- **{phase}**: {cnt} violations ({pct:.1f}%)")
        lines.append("")

    # ── Route distribution ──
    if routes:
        lines.append("## Route Distribution")
        lines.append("")
        lines.append("| Route | Count | % |")
        lines.append("|-------|------:|--:|")
        for route, cnt in routes.items():
            pct = (cnt / len(records)) * 100 if records else 0
            lines.append(f"| {route} | {cnt} | {pct:.1f}% |")
        lines.append("")

    # ── Gate check ──
    lines.append("## CI Gate Status")
    lines.append("")
    all_pass = True
    for phase in ["router_ms", "tool_ms", "finalize_ms", "tts_ms", "total_ms"]:
        s = stats.get(phase, {})
        budget = BUDGETS.get(phase, 9999)
        p95 = s.get("p95", 0)
        count = s.get("count", 0)
        if count == 0:
            lines.append(f"- ⏭ {PHASE_LABELS.get(phase, phase)}: veri yok")
            continue
        if p95 <= budget:
            lines.append(f"- ✅ {PHASE_LABELS.get(phase, phase)} p95={p95}ms ≤ {budget}ms")
        else:
            lines.append(f"- ❌ {PHASE_LABELS.get(phase, phase)} p95={p95}ms > {budget}ms")
            all_pass = False

    lines.append("")
    if all_pass:
        lines.append("**Sonuç: ✅ Tüm gate'ler geçti.**")
    else:
        lines.append("**Sonuç: ❌ Bazı gate'ler aşıldı.**")
    lines.append("")

    return "\n".join(lines)


def generate_json_report(
    records: List[Dict[str, Any]],
    hours: Optional[float] = None,
) -> str:
    """Generate a JSON latency report."""
    stats = _compute_stats(records)
    violations = _budget_violations(records)
    routes = _route_distribution(records)

    report = {
        "period_hours": hours,
        "total_turns": len(records),
        "phases": {},
        "budget_violations": violations,
        "route_distribution": routes,
    }

    for phase in PHASES:
        s = stats.get(phase, {})
        report["phases"][phase] = {
            "label": PHASE_LABELS.get(phase, phase),
            "budget_ms": BUDGETS.get(phase),
            **s,
        }

    return json.dumps(report, indent=2, ensure_ascii=False)


# ── CLI ───────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bantz latency report generator (Issue #302)"
    )
    parser.add_argument(
        "--file", "-f",
        default=DEFAULT_METRICS_FILE,
        help=f"Turn metrics JSONL file (default: {DEFAULT_METRICS_FILE})",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Filter to last N hours (default: all records)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file (default: stdout)",
    )

    args = parser.parse_args(argv)

    records = _read_jsonl(args.file)
    if not records:
        print(f"Kayıt bulunamadı: {args.file}", file=sys.stderr)
        return 1

    records = _filter_by_time(records, args.hours)
    if not records:
        print("Belirtilen zaman aralığında kayıt bulunamadı.", file=sys.stderr)
        return 1

    if args.format == "json":
        output = generate_json_report(records, args.hours)
    else:
        output = generate_markdown_report(records, args.hours)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Rapor yazıldı: {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
