#!/usr/bin/env python3
"""Generate weekly regression report from trace data (Issue #664).

Usage:
    python scripts/generate_weekly_report.py
    python scripts/generate_weekly_report.py --output artifacts/results/weekly.md
    python scripts/generate_weekly_report.py --limit 200
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bantz.brain.trace_exporter import (
    aggregate_metrics,
    detect_anomalies,
    load_traces,
    replay_golden_traces,
)


def _generate_report(limit: int = 100) -> str:
    traces = load_traces(limit=limit)
    metrics = aggregate_metrics(traces)
    anomalies = detect_anomalies(traces)
    golden = replay_golden_traces()

    lines: list[str] = []
    lines.append(f"# Bantz Weekly Regression Report")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Traces analyzed:** {metrics.get('total_turns', 0)}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Turns | {metrics.get('total_turns', 0)} |")
    lines.append(f"| Avg Latency | {metrics.get('avg_latency_ms', 0)}ms |")
    lines.append(f"| P95 Latency | {metrics.get('p95_latency_ms', 0)}ms |")
    tsr = metrics.get("tool_success_rate", 1.0)
    lines.append(f"| Tool Success Rate | {tsr*100:.1f}% |")
    lines.append(f"| Anomalies | {len(anomalies)} |")
    lines.append("")

    # Golden flow replay
    lines.append("## Golden Flow Replay")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Golden | {golden.get('total', 0)} |")
    lines.append(f"| Passed | {golden.get('passed', 0)} |")
    lines.append(f"| Failed | {golden.get('failed', 0)} |")
    lines.append("")

    if golden.get("diffs"):
        lines.append("### Failures")
        for d in golden["diffs"]:
            lines.append(f"- Turn {d['turn']}: `{d.get('user_input', '')[:50]}` → {d['diff']}")
        lines.append("")

    # Route distribution
    rd = metrics.get("route_distribution", {})
    if rd:
        lines.append("## Route Distribution")
        lines.append("| Route | Count |")
        lines.append("|-------|-------|")
        for route, count in sorted(rd.items(), key=lambda x: -x[1]):
            lines.append(f"| {route} | {count} |")
        lines.append("")

    # Tier distribution
    td = metrics.get("tier_distribution", {})
    if td.get("router"):
        lines.append("## Tier Distribution")
        lines.append("### Router")
        lines.append("| Tier | Count |")
        lines.append("|------|-------|")
        for tier, count in sorted(td["router"].items(), key=lambda x: -x[1]):
            lines.append(f"| {tier} | {count} |")
        lines.append("")

    # Anomalies
    if anomalies:
        lines.append("## Anomalies")
        for a in anomalies[:20]:
            emoji = {"latency_spike": "🐢", "low_confidence": "⚠️", "tool_failure_burst": "❌"}.get(a["type"], "⚠️")
            lines.append(f"- {emoji} Turn #{a.get('turn_id', '?')}: **{a['type']}** — {a.get('user_input', '')[:50]}")
        lines.append("")

    # Regression alerts
    lines.append("## Regression Alerts")
    alerts = []
    if metrics.get("avg_latency_ms", 0) > 2000:
        alerts.append("🔴 Average latency > 2000ms")
    if metrics.get("p95_latency_ms", 0) > 4000:
        alerts.append("🔴 P95 latency > 4000ms")
    if tsr < 0.90:
        alerts.append("🔴 Tool success rate < 90%")
    if golden.get("failed", 0) > 0:
        alerts.append(f"🔴 Golden flow failures: {golden['failed']}/{golden['total']}")
    if len(anomalies) > 10:
        alerts.append(f"🟡 High anomaly count: {len(anomalies)}")

    if alerts:
        for a in alerts:
            lines.append(f"- {a}")
    else:
        lines.append("- ✅ No regression alerts")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate weekly regression report")
    parser.add_argument("--output", default="artifacts/results/weekly_report.md")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    report = _generate_report(limit=args.limit)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"📊 Report written to {out}")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
