"""Unified LLM metrics logging for vLLM + Gemini.

Issue #234: Observability - Unified LLM metrics -> JSONL + summary report

This module provides a unified metrics logging interface for all LLM backends
(vLLM local inference and Gemini cloud API). Metrics are written to a JSONL
file for easy analysis and reporting.

Features:
- JSONL format for easy parsing and analysis
- Unified schema for both backends
- Thread-safe file writes
- Environment variable toggle (BANTZ_LLM_METRICS=1)
- Tier classification (fast/quality)

Usage:
    # Enable via environment:
    # export BANTZ_LLM_METRICS=1
    # export BANTZ_LLM_METRICS_FILE=artifacts/logs/llm_metrics.jsonl
    
    from bantz.llm.metrics import record_llm_metric, MetricEntry
    
    # Record a metric
    record_llm_metric(
        backend="vllm",
        model="Qwen/Qwen2.5-3B-Instruct",
        prompt_tokens=150,
        completion_tokens=50,
        latency_ms=245,
        success=True,
        tier="fast",
        reason="router_call",
    )

Report generation:
    python scripts/report_llm_metrics.py artifacts/logs/llm_metrics.jsonl
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Thread lock for file writes
_write_lock = threading.Lock()

# Default metrics file path
DEFAULT_METRICS_FILE = "artifacts/logs/llm_metrics.jsonl"


@dataclass(frozen=True)
class MetricEntry:
    """Single LLM call metric entry.
    
    Fields (per Issue #234 spec):
        ts: ISO timestamp
        backend: "vllm" | "gemini"
        model: Model identifier
        prompt_tokens: Input token count
        completion_tokens: Output token count
        total_tokens: Total tokens (prompt + completion)
        latency_ms: Request latency in milliseconds
        success: Whether the call succeeded
        error_type: Error classification if failed (None if success)
        tier: "fast" | "quality"
        reason: Why this tier was chosen (e.g., "router_call", "complex_query")
    """
    ts: str
    backend: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    success: bool
    error_type: Optional[str]
    tier: str
    reason: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class MetricsConfig:
    """Configuration for metrics logging."""
    enabled: bool = False
    file_path: str = DEFAULT_METRICS_FILE
    
    @classmethod
    def from_env(cls) -> "MetricsConfig":
        """Create config from environment variables."""
        enabled = _parse_bool_env("BANTZ_LLM_METRICS", default=False)
        file_path = os.environ.get("BANTZ_LLM_METRICS_FILE", DEFAULT_METRICS_FILE)
        return cls(enabled=enabled, file_path=file_path)


def _parse_bool_env(name: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def metrics_enabled() -> bool:
    """Check if metrics logging is enabled.
    
    Returns:
        True if BANTZ_LLM_METRICS=1
    """
    return _parse_bool_env("BANTZ_LLM_METRICS", default=False)


def get_metrics_file_path() -> str:
    """Get the metrics file path from environment or default.
    
    Returns:
        Path to metrics JSONL file
    """
    return os.environ.get("BANTZ_LLM_METRICS_FILE", DEFAULT_METRICS_FILE)


def _get_iso_timestamp() -> str:
    """Get current timestamp in ISO format with timezone."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_directory(file_path: str) -> None:
    """Ensure parent directory exists."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)


def record_llm_metric(
    *,
    backend: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    success: bool,
    tier: str,
    reason: str,
    error_type: Optional[str] = None,
    total_tokens: Optional[int] = None,
    ts: Optional[str] = None,
) -> Optional[MetricEntry]:
    """Record a single LLM call metric.
    
    This is the main entry point for recording metrics. Called by LLM clients
    after each API call.
    
    Args:
        backend: "vllm" | "gemini"
        model: Model identifier
        prompt_tokens: Input token count
        completion_tokens: Output token count
        latency_ms: Request latency in milliseconds
        success: Whether the call succeeded
        tier: "fast" | "quality"
        reason: Why this tier was chosen
        error_type: Error classification if failed
        total_tokens: Override total (default: prompt + completion)
        ts: Override timestamp (default: now)
    
    Returns:
        MetricEntry if written, None if metrics disabled
    """
    if not metrics_enabled():
        return None
    
    # Normalize inputs
    backend = str(backend or "unknown").strip().lower()
    model = str(model or "unknown").strip()
    tier = str(tier or "unknown").strip().lower()
    reason = str(reason or "").strip()
    
    # Calculate total tokens
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    else:
        total_tokens = max(0, int(total_tokens))
    
    latency_ms = max(0, int(latency_ms or 0))
    
    # Generate timestamp
    if ts is None:
        ts = _get_iso_timestamp()
    
    # Create entry
    entry = MetricEntry(
        ts=ts,
        backend=backend,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        success=bool(success),
        error_type=str(error_type).strip() if error_type else None,
        tier=tier,
        reason=reason,
    )
    
    # Write to file
    file_path = get_metrics_file_path()
    try:
        _ensure_directory(file_path)
        with _write_lock:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(entry.to_json() + "\n")
        logger.debug("Recorded LLM metric: backend=%s model=%s latency=%dms", backend, model, latency_ms)
    except Exception as e:
        logger.warning("Failed to write LLM metric: %s", e)
    
    return entry


def record_llm_success(
    *,
    backend: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    tier: str = "fast",
    reason: str = "",
    total_tokens: Optional[int] = None,
) -> Optional[MetricEntry]:
    """Convenience wrapper for recording successful LLM calls.
    
    Args:
        backend: "vllm" | "gemini"
        model: Model identifier
        prompt_tokens: Input token count
        completion_tokens: Output token count
        latency_ms: Request latency in milliseconds
        tier: "fast" | "quality" (default: "fast")
        reason: Why this tier was chosen
        total_tokens: Override total (default: prompt + completion)
    
    Returns:
        MetricEntry if written, None if metrics disabled
    """
    return record_llm_metric(
        backend=backend,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        success=True,
        tier=tier,
        reason=reason,
        error_type=None,
        total_tokens=total_tokens,
    )


def record_llm_failure(
    *,
    backend: str,
    model: str,
    prompt_tokens: int,
    latency_ms: int,
    error_type: str,
    tier: str = "fast",
    reason: str = "",
) -> Optional[MetricEntry]:
    """Convenience wrapper for recording failed LLM calls.
    
    Args:
        backend: "vllm" | "gemini"
        model: Model identifier
        prompt_tokens: Input token count (estimate)
        latency_ms: Request latency in milliseconds
        error_type: Error classification
        tier: "fast" | "quality" (default: "fast")
        reason: Why this tier was chosen
    
    Returns:
        MetricEntry if written, None if metrics disabled
    """
    return record_llm_metric(
        backend=backend,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=0,
        latency_ms=latency_ms,
        success=False,
        tier=tier,
        reason=reason,
        error_type=error_type,
        total_tokens=0,
    )


def load_metrics(file_path: Optional[str] = None) -> list[MetricEntry]:
    """Load metrics from JSONL file.
    
    Args:
        file_path: Path to metrics file (default: from environment)
    
    Returns:
        List of MetricEntry objects
    """
    if file_path is None:
        file_path = get_metrics_file_path()
    
    path = Path(file_path)
    if not path.exists():
        return []
    
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entry = MetricEntry(
                    ts=str(data.get("ts", "")),
                    backend=str(data.get("backend", "unknown")),
                    model=str(data.get("model", "unknown")),
                    prompt_tokens=int(data.get("prompt_tokens", 0)),
                    completion_tokens=int(data.get("completion_tokens", 0)),
                    total_tokens=int(data.get("total_tokens", 0)),
                    latency_ms=int(data.get("latency_ms", 0)),
                    success=bool(data.get("success", False)),
                    error_type=data.get("error_type"),
                    tier=str(data.get("tier", "unknown")),
                    reason=str(data.get("reason", "")),
                )
                entries.append(entry)
            except Exception as e:
                logger.warning("Failed to parse metrics line %d: %s", line_num, e)
    
    return entries


@dataclass
class MetricsReport:
    """Aggregated metrics report.
    
    Generated by analyze_metrics() from raw JSONL data.
    """
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    success_rate: float = 0.0
    
    # Per-backend stats
    vllm_calls: int = 0
    vllm_tokens: int = 0
    gemini_calls: int = 0
    gemini_tokens: int = 0
    
    # Tier stats
    fast_calls: int = 0
    quality_calls: int = 0
    quality_call_rate: float = 0.0
    
    # Latency stats (milliseconds)
    latency_p50: int = 0
    latency_p95: int = 0
    latency_mean: int = 0
    latency_min: int = 0
    latency_max: int = 0
    
    # Per-backend latency
    vllm_latency_p50: int = 0
    vllm_latency_p95: int = 0
    gemini_latency_p50: int = 0
    gemini_latency_p95: int = 0
    
    # Error breakdown
    error_types: dict = field(default_factory=dict)
    
    # Time range
    first_ts: str = ""
    last_ts: str = ""


def _percentile(values: list[int], p: float) -> int:
    """Calculate percentile from sorted list."""
    if not values:
        return 0
    values = sorted(values)
    idx = int(len(values) * p / 100)
    idx = min(idx, len(values) - 1)
    return values[idx]


def analyze_metrics(entries: list[MetricEntry]) -> MetricsReport:
    """Analyze metrics and generate summary report.
    
    Args:
        entries: List of MetricEntry objects
    
    Returns:
        MetricsReport with aggregated statistics
    """
    report = MetricsReport()
    
    if not entries:
        return report
    
    # Basic counts
    report.total_calls = len(entries)
    report.successful_calls = sum(1 for e in entries if e.success)
    report.failed_calls = report.total_calls - report.successful_calls
    report.success_rate = report.successful_calls / report.total_calls if report.total_calls > 0 else 0.0
    
    # Per-backend stats
    vllm_entries = [e for e in entries if e.backend == "vllm"]
    gemini_entries = [e for e in entries if e.backend == "gemini"]
    
    report.vllm_calls = len(vllm_entries)
    report.vllm_tokens = sum(e.total_tokens for e in vllm_entries)
    report.gemini_calls = len(gemini_entries)
    report.gemini_tokens = sum(e.total_tokens for e in gemini_entries)
    
    # Tier stats
    report.fast_calls = sum(1 for e in entries if e.tier == "fast")
    report.quality_calls = sum(1 for e in entries if e.tier == "quality")
    report.quality_call_rate = report.quality_calls / report.total_calls if report.total_calls > 0 else 0.0
    
    # Latency stats (successful calls only)
    latencies = [e.latency_ms for e in entries if e.success]
    if latencies:
        report.latency_p50 = _percentile(latencies, 50)
        report.latency_p95 = _percentile(latencies, 95)
        report.latency_mean = sum(latencies) // len(latencies)
        report.latency_min = min(latencies)
        report.latency_max = max(latencies)
    
    # Per-backend latency
    vllm_latencies = [e.latency_ms for e in vllm_entries if e.success]
    if vllm_latencies:
        report.vllm_latency_p50 = _percentile(vllm_latencies, 50)
        report.vllm_latency_p95 = _percentile(vllm_latencies, 95)
    
    gemini_latencies = [e.latency_ms for e in gemini_entries if e.success]
    if gemini_latencies:
        report.gemini_latency_p50 = _percentile(gemini_latencies, 50)
        report.gemini_latency_p95 = _percentile(gemini_latencies, 95)
    
    # Error breakdown
    error_counts: dict[str, int] = {}
    for e in entries:
        if not e.success and e.error_type:
            error_counts[e.error_type] = error_counts.get(e.error_type, 0) + 1
    report.error_types = error_counts
    
    # Time range
    timestamps = [e.ts for e in entries if e.ts]
    if timestamps:
        report.first_ts = min(timestamps)
        report.last_ts = max(timestamps)
    
    return report


def format_report_markdown(report: MetricsReport) -> str:
    """Format metrics report as Markdown.
    
    Args:
        report: MetricsReport object
    
    Returns:
        Markdown formatted string
    """
    lines = [
        "# LLM Metrics Report",
        "",
        f"**Time Range**: {report.first_ts} → {report.last_ts}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Calls | {report.total_calls:,} |",
        f"| Successful | {report.successful_calls:,} ({report.success_rate:.1%}) |",
        f"| Failed | {report.failed_calls:,} |",
        "",
        "## Latency (Successful Calls)",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| p50 | {report.latency_p50:,} ms |",
        f"| p95 | {report.latency_p95:,} ms |",
        f"| Mean | {report.latency_mean:,} ms |",
        f"| Min | {report.latency_min:,} ms |",
        f"| Max | {report.latency_max:,} ms |",
        "",
        "## Backend Breakdown",
        "",
        f"| Backend | Calls | Total Tokens | p50 Latency | p95 Latency |",
        f"|---------|-------|--------------|-------------|-------------|",
        f"| vLLM | {report.vllm_calls:,} | {report.vllm_tokens:,} | {report.vllm_latency_p50:,} ms | {report.vllm_latency_p95:,} ms |",
        f"| Gemini | {report.gemini_calls:,} | {report.gemini_tokens:,} | {report.gemini_latency_p50:,} ms | {report.gemini_latency_p95:,} ms |",
        "",
        "## Tier Distribution",
        "",
        f"| Tier | Calls | Rate |",
        f"|------|-------|------|",
        f"| Fast | {report.fast_calls:,} | {(report.fast_calls / report.total_calls * 100) if report.total_calls > 0 else 0:.1f}% |",
        f"| Quality | {report.quality_calls:,} | {report.quality_call_rate:.1%} |",
        "",
    ]
    
    # Error breakdown
    if report.error_types:
        lines.extend([
            "## Error Breakdown",
            "",
            "| Error Type | Count |",
            "|------------|-------|",
        ])
        for error_type, count in sorted(report.error_types.items(), key=lambda x: -x[1]):
            lines.append(f"| {error_type} | {count:,} |")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "*Generated by `scripts/report_llm_metrics.py`*",
    ])
    
    return "\n".join(lines)


def generate_report(file_path: Optional[str] = None) -> str:
    """Generate full metrics report from JSONL file.
    
    Args:
        file_path: Path to metrics file (default: from environment)
    
    Returns:
        Markdown formatted report string
    """
    entries = load_metrics(file_path)
    report = analyze_metrics(entries)
    return format_report_markdown(report)
