#!/usr/bin/env python3
"""LLM Metrics Report Generator.

Issue #234: Observability - Unified LLM metrics -> JSONL + summary report

This script reads LLM metrics from a JSONL file and generates a Markdown report
with key statistics:
- p50/p95 latency
- Total tokens per backend
- Quality call rate
- Error breakdown

Usage:
    # Basic usage (reads from default file)
    python scripts/report_llm_metrics.py
    
    # Custom input file
    python scripts/report_llm_metrics.py artifacts/logs/llm_metrics.jsonl
    
    # Save to file
    python scripts/report_llm_metrics.py --output artifacts/results/llm_report.md
    
    # JSON output
    python scripts/report_llm_metrics.py --format json
    
    # Filter by backend
    python scripts/report_llm_metrics.py --backend vllm
    
    # Filter by tier
    python scripts/report_llm_metrics.py --tier quality
    
    # Time window (last N hours)
    python scripts/report_llm_metrics.py --hours 24

Environment:
    BANTZ_LLM_METRICS_FILE: Default input file path

Example output:
    # LLM Metrics Report
    
    **Time Range**: 2024-01-15T10:00:00Z → 2024-01-15T12:00:00Z
    
    ## Summary
    | Metric | Value |
    |--------|-------|
    | Total Calls | 150 |
    | Successful | 145 (96.7%) |
    | Failed | 5 |
    
    ## Latency (Successful Calls)
    | Metric | Value |
    |--------|-------|
    | p50 | 250 ms |
    | p95 | 850 ms |
    ...
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.llm.metrics import (
    DEFAULT_METRICS_FILE,
    MetricEntry,
    MetricsReport,
    analyze_metrics,
    format_report_markdown,
    load_metrics,
)


def filter_by_backend(entries: list[MetricEntry], backend: str) -> list[MetricEntry]:
    """Filter entries by backend."""
    backend = backend.strip().lower()
    return [e for e in entries if e.backend == backend]


def filter_by_tier(entries: list[MetricEntry], tier: str) -> list[MetricEntry]:
    """Filter entries by tier."""
    tier = tier.strip().lower()
    return [e for e in entries if e.tier == tier]


def filter_by_time_window(entries: list[MetricEntry], hours: float) -> list[MetricEntry]:
    """Filter entries to last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    
    filtered = []
    for e in entries:
        try:
            # Compare ISO strings directly (works for ISO format)
            if e.ts >= cutoff_iso:
                filtered.append(e)
        except Exception:
            # Include if we can't parse
            filtered.append(e)
    return filtered


def format_report_json(report: MetricsReport) -> str:
    """Format report as JSON."""
    data = asdict(report)
    return json.dumps(data, indent=2, ensure_ascii=False)


def print_summary_table(report: MetricsReport) -> None:
    """Print a compact summary table to stdout."""
    print("\n" + "=" * 60)
    print("LLM METRICS SUMMARY")
    print("=" * 60)
    print(f"Time Range: {report.first_ts} → {report.last_ts}")
    print("-" * 60)
    print(f"Total Calls:    {report.total_calls:>10,}")
    print(f"Success Rate:   {report.success_rate:>10.1%}")
    print("-" * 60)
    print("Latency (successful calls):")
    print(f"  p50:          {report.latency_p50:>10,} ms")
    print(f"  p95:          {report.latency_p95:>10,} ms")
    print("-" * 60)
    print("Backend breakdown:")
    print(f"  vLLM:         {report.vllm_calls:>10,} calls, {report.vllm_tokens:>10,} tokens")
    print(f"  Gemini:       {report.gemini_calls:>10,} calls, {report.gemini_tokens:>10,} tokens")
    print("-" * 60)
    print("Tier distribution:")
    print(f"  Fast:         {report.fast_calls:>10,} ({(report.fast_calls / report.total_calls * 100) if report.total_calls > 0 else 0:.1f}%)")
    print(f"  Quality:      {report.quality_calls:>10,} ({report.quality_call_rate:.1%})")
    print("=" * 60)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate LLM metrics report from JSONL data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/report_llm_metrics.py
    python scripts/report_llm_metrics.py artifacts/logs/llm_metrics.jsonl
    python scripts/report_llm_metrics.py --output report.md
    python scripts/report_llm_metrics.py --format json
    python scripts/report_llm_metrics.py --backend vllm --hours 24
""",
    )
    
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_METRICS_FILE,
        help=f"Input JSONL file (default: {DEFAULT_METRICS_FILE})",
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: stdout)",
    )
    
    parser.add_argument(
        "-f", "--format",
        choices=["markdown", "json", "table"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    
    parser.add_argument(
        "--backend",
        choices=["vllm", "gemini"],
        help="Filter by backend",
    )
    
    parser.add_argument(
        "--tier",
        choices=["fast", "quality"],
        help="Filter by tier",
    )
    
    parser.add_argument(
        "--hours",
        type=float,
        help="Filter to last N hours",
    )
    
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress informational messages",
    )
    
    args = parser.parse_args()
    
    # Check input file
    input_path = Path(args.input)
    if not input_path.exists():
        if not args.quiet:
            print(f"Warning: Input file not found: {input_path}", file=sys.stderr)
            print("No metrics data available. Enable metrics with BANTZ_LLM_METRICS=1", file=sys.stderr)
        
        # Generate empty report
        entries = []
    else:
        # Load metrics
        entries = load_metrics(str(input_path))
        if not args.quiet:
            print(f"Loaded {len(entries):,} entries from {input_path}", file=sys.stderr)
    
    # Apply filters
    if args.backend:
        entries = filter_by_backend(entries, args.backend)
        if not args.quiet:
            print(f"Filtered by backend={args.backend}: {len(entries):,} entries", file=sys.stderr)
    
    if args.tier:
        entries = filter_by_tier(entries, args.tier)
        if not args.quiet:
            print(f"Filtered by tier={args.tier}: {len(entries):,} entries", file=sys.stderr)
    
    if args.hours:
        entries = filter_by_time_window(entries, args.hours)
        if not args.quiet:
            print(f"Filtered to last {args.hours}h: {len(entries):,} entries", file=sys.stderr)
    
    # Analyze
    report = analyze_metrics(entries)
    
    # Format output
    if args.format == "json":
        output = format_report_json(report)
    elif args.format == "table":
        print_summary_table(report)
        return 0
    else:
        output = format_report_markdown(report)
    
    # Write output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        if not args.quiet:
            print(f"Report written to: {output_path}", file=sys.stderr)
    else:
        print(output)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
