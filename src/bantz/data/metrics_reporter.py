"""
CLI Metrics Reporter for Bantz Observability.

Prints a summary of runs, tool calls, slow tools, and errors
from the observability database.

Usage (standalone)::

    python -m bantz.data.metrics_reporter --period 24h
    python -m bantz.data.metrics_reporter --period 7d --db ~/.bantz/data/observability.db

Usage (library)::

    reporter = MetricsReporter(tracker)
    text = await reporter.generate_report(period_hours=24)
    print(text)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Optional

from bantz.data.run_tracker import RunTracker


class MetricsReporter:
    """Generates human-readable metrics reports from the RunTracker store."""

    def __init__(self, tracker: RunTracker) -> None:
        self._tracker = tracker

    async def generate_report(self, period_hours: float = 24) -> str:
        """Build a full text report for the given period."""
        since = time.time() - (period_hours * 3600)
        lines: list[str] = []

        # Header
        period_label = self._period_label(period_hours)
        lines.append(f"📊 Bantz Metrics — Last {period_label}")
        lines.append("=" * 48)

        # Run stats
        rs = await self._tracker.run_stats(since=since)
        lines.append("")
        lines.append("Runs")
        lines.append("-" * 32)
        lines.append(f"  Total         : {rs['total']}")
        lines.append(f"  Successful    : {rs['success']} ({rs['success_rate']}%)")
        lines.append(f"  Errors        : {rs['errors']}")
        if rs["timeouts"]:
            lines.append(f"  Timeout       : {rs['timeouts']}")
        if rs["cancelled"]:
            lines.append(f"  Cancelled     : {rs['cancelled']}")
        lines.append(f"  Ort. latency  : {rs['avg_latency_ms']:.0f} ms")
        lines.append(f"  Max latency   : {rs['max_latency_ms']} ms")
        if rs["total_tokens"]:
            lines.append(f"  Total tokens  : {rs['total_tokens']:,}")

        # Tool stats
        ts = await self._tracker.tool_stats(since=since)
        if ts:
            lines.append("")
            lines.append("Tool Usage")
            lines.append("-" * 48)
            lines.append(f"  {'Tool':<30} {'Calls':>6} {'Avg ms':>8} {'Err%':>6}")
            lines.append(f"  {'─' * 30} {'─' * 6} {'─' * 8} {'─' * 6}")
            for t in ts:
                lines.append(
                    f"  {t['tool_name']:<30} {t['calls']:>6} "
                    f"{t['avg_latency_ms']:>7.0f} {t['error_rate']:>5.1f}%"
                )

        # Slow tools
        slow = await self._tracker.slow_tools(threshold_ms=2000, since=since)
        if slow:
            lines.append("")
            lines.append("Slow Tools (>2s)")
            lines.append("-" * 48)
            for s in slow:
                lines.append(
                    f"  {s['tool_name']:<30} "
                    f"avg: {s['avg_latency_ms']:.0f}ms  "
                    f"max: {s['max_latency_ms']}ms  "
                    f"({s['slow_count']}x)"
                )

        # Error details
        errors = await self._tracker.error_breakdown(since=since, limit=5)
        if errors:
            lines.append("")
            lines.append("Recent Errors")
            lines.append("-" * 48)
            for e in errors:
                lines.append(f"  [{e['tool_name']}] {e['error']}")

        # Artifacts
        art = await self._tracker.artifact_stats(since=since)
        if art:
            lines.append("")
            lines.append("Artifacts")
            lines.append("-" * 32)
            for atype, count in sorted(art.items()):
                lines.append(f"  {atype:<20} : {count}")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _period_label(hours: float) -> str:
        if hours <= 24:
            return f"{hours:.0f} Hours"
        days = hours / 24
        if days <= 7:
            return f"{days:.0f} Days"
        return f"{days:.0f} Days"


def _parse_period(period_str: str) -> float:
    """Parse '24h', '7d', '30d' into hours."""
    period_str = period_str.strip().lower()
    if period_str.endswith("h"):
        return float(period_str[:-1])
    elif period_str.endswith("d"):
        return float(period_str[:-1]) * 24
    else:
        raise ValueError(f"Invalid period format: {period_str!r} — use '24h', '7d', '30d'")


async def _main(args: argparse.Namespace) -> None:
    tracker = RunTracker(db_path=args.db)
    await tracker.initialise()
    try:
        reporter = MetricsReporter(tracker)
        report = await reporter.generate_report(
            period_hours=_parse_period(args.period),
        )
        print(report)
    finally:
        await tracker.close()


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.  Called by ``bantz metrics`` or ``python -m``."""
    parser = argparse.ArgumentParser(
        prog="bantz metrics",
        description="Bantz Observability Metrics Reporter",
    )
    parser.add_argument(
        "--period", default="24h",
        help="Time period: 24h, 7d, 30d (default: 24h)",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to observability.db (default: ~/.bantz/data/observability.db)",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(_main(args))
    except FileNotFoundError:
        print("❌ Observability DB not found. Run Bantz first to generate data.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
