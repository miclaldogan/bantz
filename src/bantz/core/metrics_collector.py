"""Unified Metrics Collector (Issue #462).

Central metrics aggregation with JSONL persistence, in-memory
percentile computation, and time-window filtering.

This module complements the existing ``bantz.llm.metrics`` (LLM-specific
JSONL logger) and ``bantz.core.timing`` (timing constants) by providing
a **general-purpose** metric collection / query layer that any subsystem
can use.

Key features
------------
- ``MetricsCollector.record()`` — fire-and-forget metric recording
- JSONL persistence (``flush()``) with configurable path
- In-memory ring buffer with configurable max size
- Percentile computation (p50 / p90 / p99)
- Time-window filtering (last N seconds)
- ``MetricsSummary`` — aggregated snapshot per metric name

See Also
--------
- ``src/bantz/core/timing.py`` — timing constants / thresholds
- ``src/bantz/llm/metrics.py`` — LLM-specific JSONL logging
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "MetricRecord",
    "MetricsSummary",
    "MetricsConfig",
    "MetricsCollector",
    "percentile",
]


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class MetricRecord:
    """A single metric data point."""

    name: str
    value: float
    unit: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    ts: float = field(default_factory=time.monotonic)
    wall_ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class MetricsSummary:
    """Aggregated statistics for one metric name."""

    name: str
    count: int
    total: float
    mean: float
    min: float
    max: float
    p50: float
    p90: float
    p99: float
    unit: str = ""

    def __str__(self) -> str:
        return (
            f"[{self.name}] count={self.count}  mean={self.mean:.2f}  "
            f"p50={self.p50:.2f}  p90={self.p90:.2f}  p99={self.p99:.2f}  "
            f"min={self.min:.2f}  max={self.max:.2f}  ({self.unit})"
        )


# ── Config ────────────────────────────────────────────────────────────

@dataclass
class MetricsConfig:
    """Configuration for the metrics collector."""

    jsonl_path: Optional[str] = None
    max_records: int = 10_000  # ring buffer size
    auto_flush_every: int = 0  # 0 = manual flush only


# ── Percentile helper ─────────────────────────────────────────────────

def percentile(values: Sequence[float], p: float) -> float:
    """Compute the *p*-th percentile (0–100) using nearest-rank.

    Parameters
    ----------
    values:
        Sorted (or unsorted) numeric sequence.  Must be non-empty.
    p:
        Percentile in [0, 100].

    Returns
    -------
    float
        The percentile value.

    Raises
    ------
    ValueError
        If *values* is empty or *p* is out of range.
    """
    if not values:
        raise ValueError("Cannot compute percentile of empty sequence")
    if not (0 <= p <= 100):
        raise ValueError(f"p must be between 0 and 100, got {p}")

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    if n == 1:
        return sorted_vals[0]

    # nearest-rank index
    rank = (p / 100) * (n - 1)
    lo = int(math.floor(rank))
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


# ── Collector ─────────────────────────────────────────────────────────

class MetricsCollector:
    """General-purpose metric collector with JSONL persistence.

    Thread-safe — safe to call ``record()`` from any thread.

    Parameters
    ----------
    config:
        Optional ``MetricsConfig``.  Defaults are sensible for dev use.

    Examples
    --------
    >>> mc = MetricsCollector()
    >>> mc.record("llm_latency", 245.0, unit="ms", tags={"backend": "vllm"})
    >>> mc.record("llm_latency", 310.0, unit="ms", tags={"backend": "vllm"})
    >>> s = mc.summarize("llm_latency")
    >>> s.count
    2
    """

    def __init__(self, config: Optional[MetricsConfig] = None) -> None:
        self._config = config or MetricsConfig()
        self._lock = threading.Lock()
        self._records: List[MetricRecord] = []
        self._flush_counter = 0

    # ── recording ─────────────────────────────────────────────────────

    def record(
        self,
        name: str,
        value: float,
        *,
        unit: str = "",
        tags: Optional[Dict[str, str]] = None,
    ) -> MetricRecord:
        """Record a metric data point.

        Parameters
        ----------
        name:
            Metric name (e.g. ``"llm_latency"``, ``"tool_exec_time"``).
        value:
            Numeric value.
        unit:
            Unit label (e.g. ``"ms"``, ``"bytes"``).
        tags:
            Optional key-value tags for filtering.

        Returns
        -------
        MetricRecord
            The recorded data point.
        """
        rec = MetricRecord(name=name, value=value, unit=unit, tags=tags or {})

        with self._lock:
            self._records.append(rec)
            # Ring buffer — drop oldest when over limit
            if len(self._records) > self._config.max_records:
                self._records = self._records[-self._config.max_records :]

            self._flush_counter += 1
            need_flush = (
                self._config.auto_flush_every > 0
                and self._flush_counter >= self._config.auto_flush_every
            )

        if need_flush:
            self.flush()

        return rec

    # ── query ─────────────────────────────────────────────────────────

    def get_records(
        self,
        name: Optional[str] = None,
        *,
        last_seconds: Optional[float] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> List[MetricRecord]:
        """Return matching records.

        Parameters
        ----------
        name:
            Filter by metric name.  ``None`` returns all names.
        last_seconds:
            Only records from the last N seconds (monotonic clock).
        tags:
            Require records whose tags are a superset of these.
        """
        with self._lock:
            snapshot = list(self._records)

        if name is not None:
            snapshot = [r for r in snapshot if r.name == name]

        if last_seconds is not None:
            cutoff = time.monotonic() - last_seconds
            snapshot = [r for r in snapshot if r.ts >= cutoff]

        if tags:
            snapshot = [
                r for r in snapshot
                if all(r.tags.get(k) == v for k, v in tags.items())
            ]

        return snapshot

    def summarize(
        self,
        name: str,
        *,
        last_seconds: Optional[float] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> Optional[MetricsSummary]:
        """Aggregate stats for a single metric name.

        Returns ``None`` if no matching records exist.
        """
        records = self.get_records(name, last_seconds=last_seconds, tags=tags)
        if not records:
            return None

        values = [r.value for r in records]
        total = sum(values)
        count = len(values)

        return MetricsSummary(
            name=name,
            count=count,
            total=total,
            mean=total / count,
            min=min(values),
            max=max(values),
            p50=percentile(values, 50),
            p90=percentile(values, 90),
            p99=percentile(values, 99),
            unit=records[0].unit,
        )

    def summarize_all(
        self,
        *,
        last_seconds: Optional[float] = None,
    ) -> Dict[str, MetricsSummary]:
        """Summarize all metric names.

        Returns
        -------
        Dict[str, MetricsSummary]
            Keys are metric names.
        """
        with self._lock:
            names = {r.name for r in self._records}

        result: Dict[str, MetricsSummary] = {}
        for n in sorted(names):
            s = self.summarize(n, last_seconds=last_seconds)
            if s is not None:
                result[n] = s
        return result

    # ── persistence ───────────────────────────────────────────────────

    def flush(self) -> int:
        """Write all un-flushed records to JSONL file.

        Returns
        -------
        int
            Number of records written.
        """
        if not self._config.jsonl_path:
            return 0

        with self._lock:
            to_write = list(self._records)
            self._flush_counter = 0

        if not to_write:
            return 0

        path = Path(self._config.jsonl_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with path.open("a", encoding="utf-8") as fh:
                for rec in to_write:
                    fh.write(rec.to_json() + "\n")
        except OSError:
            logger.exception("Failed to flush metrics to %s", self._config.jsonl_path)
            return 0

        logger.debug("Flushed %d metric records to %s", len(to_write), self._config.jsonl_path)
        return len(to_write)

    # ── housekeeping ──────────────────────────────────────────────────

    def clear(self) -> None:
        """Drop all in-memory records."""
        with self._lock:
            self._records.clear()
            self._flush_counter = 0

    @property
    def count(self) -> int:
        """Total records currently in memory."""
        with self._lock:
            return len(self._records)

    def metric_names(self) -> List[str]:
        """Return sorted list of distinct metric names."""
        with self._lock:
            return sorted({r.name for r in self._records})
