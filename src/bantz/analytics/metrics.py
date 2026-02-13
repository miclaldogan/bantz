"""
Unified Metrics Collector — Issue #435.

Centralized metrics for all Bantz subsystems:
- llm_calls{model, phase, status} (counter)
- llm_latency{model, phase} (histogram)
- tool_calls{tool, status} (counter)
- turn_latency{route} (histogram)
- gemini_tokens_used (counter)
- json_validity_rate (gauge)

Export: in-memory query + JSONL file export.

Usage::

    from bantz.analytics.metrics import metrics, MetricType
    metrics.increment("llm_calls", labels={"model": "3b", "phase": "router", "status": "ok"})
    metrics.observe("llm_latency", 245.0, labels={"model": "3b", "phase": "router"})
    summary = metrics.summary(last_seconds=3600)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricPoint:
    """A single metric observation."""
    name: str
    metric_type: MetricType
    value: float
    labels: Dict[str, str]
    timestamp: float  # monotonic

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.metric_type.value,
            "value": self.value,
            "labels": self.labels,
            "ts": round(self.timestamp, 3),
        }


@dataclass
class HistogramBucket:
    """Aggregated histogram data."""
    count: int = 0
    total: float = 0.0
    min_val: float = float("inf")
    max_val: float = float("-inf")
    values: List[float] = field(default_factory=list)

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.min_val = min(self.min_val, value)
        self.max_val = max(self.max_val, value)
        self.values.append(value)

    @property
    def avg(self) -> float:
        return self.total / self.count if self.count else 0.0

    @property
    def p50(self) -> float:
        return self._percentile(50)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    def _percentile(self, p: int) -> float:
        if not self.values:
            return 0.0
        sorted_vals = sorted(self.values)
        idx = int(len(sorted_vals) * p / 100)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "count": self.count,
            "avg": round(self.avg, 2),
            "min": round(self.min_val, 2) if self.min_val != float("inf") else 0,
            "max": round(self.max_val, 2) if self.max_val != float("-inf") else 0,
        }
        if self.count >= 2:
            d["p50"] = round(self.p50, 2)
            d["p95"] = round(self.p95, 2)
        return d


# ─────────────────────────────────────────────────────────────────
# Collector
# ─────────────────────────────────────────────────────────────────


def _labels_key(labels: Dict[str, str]) -> str:
    """Deterministic string key for label sets."""
    return "|".join(f"{k}={v}" for k, v in sorted(labels.items()))


class MetricsCollector:
    """
    Thread-safe centralized metrics collector.

    Supports counters, gauges, and histograms with arbitrary labels.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._gauges: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._histograms: Dict[str, Dict[str, HistogramBucket]] = defaultdict(lambda: defaultdict(HistogramBucket))
        self._points: List[MetricPoint] = []
        self._start_time = time.monotonic()

    # ── Counters ──

    def increment(self, name: str, value: float = 1.0, *, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        lbls = labels or {}
        key = _labels_key(lbls)
        with self._lock:
            self._counters[name][key] += value
            self._points.append(MetricPoint(
                name=name, metric_type=MetricType.COUNTER,
                value=value, labels=lbls, timestamp=time.monotonic(),
            ))

    # ── Gauges ──

    def set_gauge(self, name: str, value: float, *, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric to an absolute value."""
        lbls = labels or {}
        key = _labels_key(lbls)
        with self._lock:
            self._gauges[name][key] = value
            self._points.append(MetricPoint(
                name=name, metric_type=MetricType.GAUGE,
                value=value, labels=lbls, timestamp=time.monotonic(),
            ))

    # ── Histograms ──

    def observe(self, name: str, value: float, *, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a histogram observation (e.g. latency in ms)."""
        lbls = labels or {}
        key = _labels_key(lbls)
        with self._lock:
            self._histograms[name][key].observe(value)
            self._points.append(MetricPoint(
                name=name, metric_type=MetricType.HISTOGRAM,
                value=value, labels=lbls, timestamp=time.monotonic(),
            ))

    # ── Query ──

    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current counter value."""
        key = _labels_key(labels or {})
        with self._lock:
            return self._counters.get(name, {}).get(key, 0.0)

    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value."""
        key = _labels_key(labels or {})
        with self._lock:
            return self._gauges.get(name, {}).get(key, 0.0)

    def get_histogram(self, name: str, labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Get histogram summary."""
        key = _labels_key(labels or {})
        with self._lock:
            bucket = self._histograms.get(name, {}).get(key)
            return bucket.to_dict() if bucket else {"count": 0}

    # ── Summary ──

    def summary(self, *, last_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        Export a summary of all metrics.

        Args:
            last_seconds: If set, only include points from the last N seconds.
        """
        with self._lock:
            now = time.monotonic()
            cutoff = (now - last_seconds) if last_seconds else 0.0

            counters: Dict[str, Any] = {}
            for name, label_vals in self._counters.items():
                counters[name] = {k: v for k, v in label_vals.items() if v > 0}

            gauges: Dict[str, Any] = {}
            for name, label_vals in self._gauges.items():
                gauges[name] = dict(label_vals)

            histograms: Dict[str, Any] = {}
            for name, label_buckets in self._histograms.items():
                histograms[name] = {
                    k: b.to_dict() for k, b in label_buckets.items() if b.count > 0
                }

            return {
                "uptime_s": round(now - self._start_time, 1),
                "total_points": len(self._points),
                "counters": counters,
                "gauges": gauges,
                "histograms": histograms,
            }

    # ── Export ──

    def export_jsonl(self, path: Path) -> int:
        """Export all metric points as JSONL."""
        with self._lock:
            points = list(self._points)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for p in points:
                f.write(json.dumps(p.to_dict()) + "\n")
        return len(points)

    # ── Reset ──

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._points.clear()
            self._start_time = time.monotonic()


# ─────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────

metrics = MetricsCollector()


# ─────────────────────────────────────────────────────────────────
# Convenience helpers for common metrics
# ─────────────────────────────────────────────────────────────────


def record_llm_call(model: str, phase: str, status: str, latency_ms: float) -> None:
    """Record an LLM call with standard labels."""
    labels = {"model": model, "phase": phase, "status": status}
    metrics.increment("llm_calls", labels=labels)
    metrics.observe("llm_latency", latency_ms, labels={"model": model, "phase": phase})


def record_tool_call(tool: str, status: str, latency_ms: float = 0.0) -> None:
    """Record a tool execution."""
    metrics.increment("tool_calls", labels={"tool": tool, "status": status})
    if latency_ms > 0:
        metrics.observe("tool_latency", latency_ms, labels={"tool": tool})


def record_turn_latency(route: str, latency_ms: float) -> None:
    """Record end-to-end turn latency."""
    metrics.observe("turn_latency", latency_ms, labels={"route": route})


def record_gemini_tokens(tokens: int) -> None:
    """Record Gemini token usage."""
    metrics.increment("gemini_tokens_used", value=float(tokens))


def record_json_validity(valid: bool) -> None:
    """Update JSON validity rate gauge."""
    metrics.increment("json_parse_total")
    if valid:
        metrics.increment("json_parse_valid")
    total = metrics.get_counter("json_parse_total")
    valid_count = metrics.get_counter("json_parse_valid")
    rate = valid_count / total if total > 0 else 1.0
    metrics.set_gauge("json_validity_rate", rate)
