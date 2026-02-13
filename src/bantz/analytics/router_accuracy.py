"""
Router Accuracy Benchmark — Issue #437.

Provides:
- Golden dataset loader (tests/golden/router_accuracy.jsonl)
- AccuracyResult with per-field breakdown (route, intent, slot)
- RouterAccuracyBenchmark runner
- Confusion matrix utilities

Usage::

    from bantz.analytics.router_accuracy import RouterAccuracyBenchmark
    bench = RouterAccuracyBenchmark.from_golden_file("tests/golden/router_accuracy.jsonl")
    report = bench.evaluate(predict_fn)
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Golden Case
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldenCase:
    """A single golden test case: input → expected output."""
    text: str
    expected_route: str
    expected_intent: str = "none"
    expected_slots: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictionResult:
    """Router prediction for a single case."""
    route: str
    intent: str = "none"
    slots: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Accuracy Report
# ─────────────────────────────────────────────────────────────────


@dataclass
class AccuracyReport:
    """Aggregate accuracy report."""
    total_cases: int = 0
    route_correct: int = 0
    intent_correct: int = 0
    slot_correct: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    confusion: Dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @property
    def route_accuracy(self) -> float:
        return self.route_correct / self.total_cases if self.total_cases else 0.0

    @property
    def intent_accuracy(self) -> float:
        return self.intent_correct / self.total_cases if self.total_cases else 0.0

    @property
    def slot_accuracy(self) -> float:
        return self.slot_correct / self.total_cases if self.total_cases else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "route_accuracy": round(self.route_accuracy, 4),
            "intent_accuracy": round(self.intent_accuracy, 4),
            "slot_accuracy": round(self.slot_accuracy, 4),
            "route_correct": self.route_correct,
            "intent_correct": self.intent_correct,
            "slot_correct": self.slot_correct,
            "error_count": len(self.errors),
            "confusion_matrix": {
                k: dict(v) for k, v in self.confusion.items()
            },
        }

    def summary_text(self) -> str:
        lines = [
            f"Router Accuracy Benchmark — {self.total_cases} cases",
            f"  Route accuracy:  {self.route_accuracy:.1%} ({self.route_correct}/{self.total_cases})",
            f"  Intent accuracy: {self.intent_accuracy:.1%} ({self.intent_correct}/{self.total_cases})",
            f"  Slot accuracy:   {self.slot_accuracy:.1%} ({self.slot_correct}/{self.total_cases})",
        ]
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Benchmark
# ─────────────────────────────────────────────────────────────────


class RouterAccuracyBenchmark:
    """
    Evaluates router accuracy against a golden dataset.

    Args:
        cases: List of GoldenCase instances.
    """

    def __init__(self, cases: List[GoldenCase]) -> None:
        self._cases = cases

    @classmethod
    def from_golden_file(cls, path: str | Path) -> "RouterAccuracyBenchmark":
        """Load golden cases from JSONL file."""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        cases: List[GoldenCase] = []
        for item in data.get("cases", []):
            cases.append(GoldenCase(
                text=item["text"],
                expected_route=item["route"],
                expected_intent=item.get("intent", "none"),
                expected_slots=item.get("slots", {}),
            ))
        return cls(cases)

    @property
    def case_count(self) -> int:
        return len(self._cases)

    def evaluate(
        self,
        predict_fn: Callable[[str], PredictionResult],
    ) -> AccuracyReport:
        """
        Run benchmark against a prediction function.

        Args:
            predict_fn: Takes user text, returns PredictionResult.
        """
        report = AccuracyReport()

        for case in self._cases:
            report.total_cases += 1

            try:
                pred = predict_fn(case.text)
            except Exception as exc:
                report.errors.append({
                    "text": case.text,
                    "error": str(exc),
                })
                continue

            # Route accuracy
            route_match = pred.route == case.expected_route
            if route_match:
                report.route_correct += 1
            report.confusion[case.expected_route][pred.route] += 1

            # Intent accuracy
            intent_match = pred.intent == case.expected_intent
            if intent_match:
                report.intent_correct += 1

            # Slot accuracy (all expected slots must match)
            slot_match = True
            for key, expected_val in case.expected_slots.items():
                actual_val = pred.slots.get(key)
                if actual_val != expected_val:
                    slot_match = False
                    break
            # If no expected slots, count as match
            if not case.expected_slots:
                slot_match = True
            if slot_match:
                report.slot_correct += 1

            if not (route_match and intent_match):
                report.errors.append({
                    "text": case.text,
                    "expected_route": case.expected_route,
                    "predicted_route": pred.route,
                    "expected_intent": case.expected_intent,
                    "predicted_intent": pred.intent,
                })

        return report


def load_golden_cases(path: str | Path) -> List[GoldenCase]:
    """Load golden cases from file."""
    return RouterAccuracyBenchmark.from_golden_file(path)._cases
