"""bantz.metrics — latency budgets, turn metrics, and CI gates (Issue #302).

Exports
-------
- :class:`TurnMetrics` / :class:`TurnMetricsWriter` — per-turn JSONL logging
- :class:`LatencyGate` / :class:`GateResult` / :func:`check_gates` — CI gates
- :func:`check_gates_from_records` — gate check from pre-loaded records
- :func:`read_turn_metrics` — JSONL reader utility
- :class:`PipelineMetrics` / :func:`compute_pipeline_metrics` — sprint metrics (Issue #1220)
"""

from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter
from bantz.metrics.gates import (
    LatencyGate,
    GateResult,
    check_gates,
    check_gates_from_records,
    read_turn_metrics,
    DEFAULT_GATES,
)
from bantz.metrics.pipeline_metrics import PipelineMetrics, compute_pipeline_metrics

__all__ = [
    "TurnMetrics",
    "TurnMetricsWriter",
    "LatencyGate",
    "GateResult",
    "check_gates",
    "check_gates_from_records",
    "read_turn_metrics",
    "DEFAULT_GATES",
    "PipelineMetrics",
    "compute_pipeline_metrics",
]
