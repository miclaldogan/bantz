"""CI latency gates for pipeline quality enforcement (Issue #302).

Each :class:`LatencyGate` defines a *phase* + *percentile* + *max_ms*
threshold.  :func:`check_gates` reads a JSONL file written by
:class:`~bantz.metrics.turn_metrics.TurnMetricsWriter` and verifies
that every gate passes.

Typical CI usage::

    from bantz.metrics.gates import check_gates, DEFAULT_GATES
    results = check_gates("artifacts/logs/turn_metrics.jsonl")
    if not all(r.passed for r in results):
        sys.exit(1)

Command-line usage::

    python -m bantz.metrics.gates artifacts/logs/turn_metrics.jsonl
"""

from __future__ import annotations

import json
import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    "LatencyGate",
    "GateResult",
    "check_gates",
    "DEFAULT_GATES",
]


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LatencyGate:
    """A single latency threshold.

    Attributes
    ----------
    phase:
        JSONL field name (e.g. ``"router_ms"``, ``"total_ms"``).
    percentile:
        Percentile level to check (e.g. 95 → p95).
    max_ms:
        Maximum acceptable value at *percentile*.
    label:
        Human-readable label for CI output.
    """

    phase: str
    percentile: float
    max_ms: float
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            # Construct label: "router p95 < 500ms"
            object.__setattr__(
                self,
                "label",
                f"{self.phase.replace('_ms', '')} p{int(self.percentile)} < {self.max_ms:.0f}ms",
            )


@dataclass
class GateResult:
    """Result of evaluating one :class:`LatencyGate`."""

    gate: LatencyGate
    actual_value: float
    sample_count: int
    passed: bool
    detail: str = ""

    def summary_line(self) -> str:
        """Human-readable one-liner for CI output."""
        icon = "✅" if self.passed else "❌"
        pname = self.gate.phase.replace("_ms", "")
        return (
            f"{icon} {pname} p{int(self.gate.percentile)}: "
            f"{self.actual_value:.0f}ms "
            f"(budget: {self.gate.max_ms:.0f}ms, n={self.sample_count})"
        )


# ─────────────────────────────────────────────────────────────────
# Default gates per Issue #302 spec
# ─────────────────────────────────────────────────────────────────

DEFAULT_GATES: List[LatencyGate] = [
    LatencyGate(phase="router_ms", percentile=95, max_ms=500.0),
    LatencyGate(phase="tool_ms", percentile=95, max_ms=2000.0),
    LatencyGate(phase="finalize_ms", percentile=95, max_ms=2000.0),
    LatencyGate(phase="tts_ms", percentile=95, max_ms=500.0),
    LatencyGate(phase="total_ms", percentile=95, max_ms=5000.0),
]


# ─────────────────────────────────────────────────────────────────
# Percentile helper (standalone — no dependency on metrics_collector)
# ─────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────
# JSONL reader
# ─────────────────────────────────────────────────────────────────


def read_turn_metrics(path: str | Path) -> List[Dict[str, Any]]:
    """Read JSONL file and return list of dicts.

    Skips malformed lines with a warning.
    """
    records: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        logger.warning("Turn metrics file not found: %s", p)
        return records

    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed line %d in %s: %s", lineno, p, exc)

    return records


# ─────────────────────────────────────────────────────────────────
# Gate checker
# ─────────────────────────────────────────────────────────────────


def check_gates(
    path: str | Path,
    *,
    gates: Optional[List[LatencyGate]] = None,
    min_samples: int = 1,
) -> List[GateResult]:
    """Check all latency gates against a JSONL file.

    Parameters
    ----------
    path:
        Path to ``turn_metrics.jsonl``.
    gates:
        Gate definitions.  Defaults to :data:`DEFAULT_GATES`.
    min_samples:
        Minimum number of samples required.  If fewer, the gate
        is marked as passed with a warning detail.

    Returns
    -------
    list[GateResult]
        One result per gate.
    """
    gates = gates or DEFAULT_GATES
    records = read_turn_metrics(path)
    results: List[GateResult] = []

    for gate in gates:
        # Extract values for this phase
        values = [
            float(r[gate.phase])
            for r in records
            if gate.phase in r and r[gate.phase] is not None
        ]

        if len(values) < min_samples:
            results.append(
                GateResult(
                    gate=gate,
                    actual_value=0.0,
                    sample_count=len(values),
                    passed=True,
                    detail=f"Yetersiz örnek: {len(values)} < {min_samples} (atlandı)",
                )
            )
            continue

        actual = _percentile(values, gate.percentile)
        passed = actual <= gate.max_ms

        results.append(
            GateResult(
                gate=gate,
                actual_value=actual,
                sample_count=len(values),
                passed=passed,
                detail="" if passed else f"p{int(gate.percentile)} aşıldı: {actual:.0f}ms > {gate.max_ms:.0f}ms",
            )
        )

    return results


def check_gates_from_records(
    records: List[Dict[str, Any]],
    *,
    gates: Optional[List[LatencyGate]] = None,
    min_samples: int = 1,
) -> List[GateResult]:
    """Same as :func:`check_gates` but takes pre-loaded records."""
    gates = gates or DEFAULT_GATES
    results: List[GateResult] = []

    for gate in gates:
        values = [
            float(r[gate.phase])
            for r in records
            if gate.phase in r and r[gate.phase] is not None
        ]

        if len(values) < min_samples:
            results.append(
                GateResult(
                    gate=gate,
                    actual_value=0.0,
                    sample_count=len(values),
                    passed=True,
                    detail=f"Yetersiz örnek: {len(values)} < {min_samples} (atlandı)",
                )
            )
            continue

        actual = _percentile(values, gate.percentile)
        passed = actual <= gate.max_ms

        results.append(
            GateResult(
                gate=gate,
                actual_value=actual,
                sample_count=len(values),
                passed=passed,
                detail="" if passed else f"p{int(gate.percentile)} aşıldı: {actual:.0f}ms > {gate.max_ms:.0f}ms",
            )
        )

    return results


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for CI gate checking.

    Usage::

        python -m bantz.metrics.gates artifacts/logs/turn_metrics.jsonl
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print("Kullanım: python -m bantz.metrics.gates <turn_metrics.jsonl>", file=sys.stderr)
        return 2

    path = args[0]
    min_samples = int(args[1]) if len(args) > 1 else 5

    results = check_gates(path, min_samples=min_samples)

    print("\n── Bantz Latency Gates ──────────────────────────────")
    all_passed = True
    for r in results:
        print(r.summary_line())
        if not r.passed:
            all_passed = False

    if all_passed:
        print("\n✅ Tüm latency gate'leri geçti.\n")
        return 0
    else:
        print("\n❌ Bazı gate'ler aşıldı — CI başarısız.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
