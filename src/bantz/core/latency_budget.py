"""
Voice Pipeline Latency Budget — Issue #427.

Per-phase latency budgets for the ASR → Router → Tool → Finalizer → TTS pipeline.
Provides:
- Budget configuration (from model-settings.yaml or defaults)
- Per-phase timing tracking with p50/p95 percentile calculation
- Budget violation detection with degradation recommendations
- Feedback phrase trigger points
- Dashboard-ready metric export

Typical budget (end-to-end ≤2000ms):
  ASR:        max 500ms  → timeout + partial result
  Router:     max 100ms  → pre-route cache hit
  Tool:       max 1000ms → async + feedback phrase
  Finalizer:  max 500ms  → streaming + 3B fallback
  TTS:        max 300ms  → pre-cache common phrases

Reference: Issue #302, Issue #427
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Constants / Defaults
# ─────────────────────────────────────────────────────────────────

_DEFAULT_YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "model-settings.yaml"

# Maximum number of samples retained per phase for percentile calculation
_MAX_SAMPLES = 500


class Phase(str, Enum):
    """Pipeline phases in execution order."""
    ASR = "asr"
    ROUTER = "router"
    TOOL = "tool"
    FINALIZER = "finalizer"
    TTS = "tts"


class DegradationAction(str, Enum):
    """Recommended degradation when a phase exceeds its budget."""
    NONE = "none"
    USE_PARTIAL_ASR = "use_partial_asr"
    USE_PREROUTE_CACHE = "use_preroute_cache"
    ASYNC_TOOL_WITH_FEEDBACK = "async_tool_with_feedback"
    SKIP_FINALIZER_USE_3B = "skip_finalizer_use_3b"
    USE_CACHED_TTS = "use_cached_tts"
    STREAM_FINALIZER = "stream_finalizer"


# Mapping: phase → default degradation action
_PHASE_DEGRADATION: Dict[Phase, DegradationAction] = {
    Phase.ASR: DegradationAction.USE_PARTIAL_ASR,
    Phase.ROUTER: DegradationAction.USE_PREROUTE_CACHE,
    Phase.TOOL: DegradationAction.ASYNC_TOOL_WITH_FEEDBACK,
    Phase.FINALIZER: DegradationAction.SKIP_FINALIZER_USE_3B,
    Phase.TTS: DegradationAction.USE_CACHED_TTS,
}

# Turkish feedback phrases injected when a phase blocks
_FEEDBACK_PHRASES: Dict[Phase, str] = {
    Phase.ASR: "",  # ASR phase — no feedback while listening
    Phase.ROUTER: "",  # Router too fast for feedback
    Phase.TOOL: "Bir bakayım efendim...",
    Phase.FINALIZER: "Hemen söylüyorum...",
    Phase.TTS: "",
}


# ─────────────────────────────────────────────────────────────────
# Budget Configuration
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PhaseBudget:
    """Budget for a single pipeline phase."""
    phase: Phase
    max_ms: float
    degradation: DegradationAction
    feedback_phrase: str = ""

    def is_exceeded(self, elapsed_ms: float) -> bool:
        return elapsed_ms > self.max_ms


@dataclass(frozen=True)
class LatencyBudgetConfig:
    """
    Full pipeline latency budget.

    Can be loaded from model-settings.yaml ``voice_pipeline.latency_budget``
    section or constructed with defaults.
    """
    asr_max_ms: float = 500.0
    router_max_ms: float = 100.0
    tool_max_ms: float = 1000.0
    finalizer_max_ms: float = 500.0
    tts_max_ms: float = 300.0
    end_to_end_max_ms: float = 2000.0

    # ── helpers ──────────────────────────────────────────────

    @property
    def total_phase_budget_ms(self) -> float:
        """Sum of individual phase budgets."""
        return (
            self.asr_max_ms
            + self.router_max_ms
            + self.tool_max_ms
            + self.finalizer_max_ms
            + self.tts_max_ms
        )

    def phase_budget(self, phase: Phase) -> PhaseBudget:
        """Get *PhaseBudget* for a single phase."""
        max_map = {
            Phase.ASR: self.asr_max_ms,
            Phase.ROUTER: self.router_max_ms,
            Phase.TOOL: self.tool_max_ms,
            Phase.FINALIZER: self.finalizer_max_ms,
            Phase.TTS: self.tts_max_ms,
        }
        return PhaseBudget(
            phase=phase,
            max_ms=max_map[phase],
            degradation=_PHASE_DEGRADATION[phase],
            feedback_phrase=_FEEDBACK_PHRASES.get(phase, ""),
        )

    def all_phase_budgets(self) -> List[PhaseBudget]:
        return [self.phase_budget(p) for p in Phase]


def load_budget_from_yaml(path: Optional[Path] = None) -> LatencyBudgetConfig:
    """
    Load latency budget from model-settings.yaml.

    Looks for ``voice_pipeline.latency_budget`` section.
    Falls back to defaults if missing or yaml not loadable.
    """
    yaml_path = path or _DEFAULT_YAML_PATH
    try:
        import yaml  # type: ignore[import-untyped]

        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        budget = (data.get("voice_pipeline") or {}).get("latency_budget") or {}
        if not budget:
            return LatencyBudgetConfig()
        return LatencyBudgetConfig(
            asr_max_ms=float(budget.get("asr_max_ms", 500)),
            router_max_ms=float(budget.get("router_max_ms", 100)),
            tool_max_ms=float(budget.get("tool_max_ms", 1000)),
            finalizer_max_ms=float(budget.get("finalizer_max_ms", 500)),
            tts_max_ms=float(budget.get("tts_max_ms", 300)),
            end_to_end_max_ms=float(budget.get("end_to_end_max_ms", 2000)),
        )
    except Exception as exc:
        logger.warning("Failed to load latency budget from %s: %s — using defaults", yaml_path, exc)
        return LatencyBudgetConfig()


# ─────────────────────────────────────────────────────────────────
# Phase Timing Record
# ─────────────────────────────────────────────────────────────────


@dataclass
class PhaseRecord:
    """Timing record for one pipeline phase execution."""
    phase: Phase
    elapsed_ms: float
    budget_ms: float
    exceeded: bool
    degradation: DegradationAction = DegradationAction.NONE
    feedback_phrase: str = ""

    @property
    def headroom_ms(self) -> float:
        """Positive = under budget, negative = over budget."""
        return self.budget_ms - self.elapsed_ms


@dataclass
class PipelineRun:
    """Full end-to-end pipeline timing for one utterance."""
    records: List[PhaseRecord] = field(default_factory=list)
    start_epoch: float = 0.0
    end_epoch: float = 0.0

    @property
    def total_ms(self) -> float:
        if self.end_epoch and self.start_epoch:
            return (self.end_epoch - self.start_epoch) * 1000
        return sum(r.elapsed_ms for r in self.records)

    @property
    def exceeded_phases(self) -> List[PhaseRecord]:
        return [r for r in self.records if r.exceeded]

    @property
    def degradation_actions(self) -> List[DegradationAction]:
        """Recommended degradation actions for exceeded phases."""
        return [r.degradation for r in self.records if r.exceeded and r.degradation != DegradationAction.NONE]

    @property
    def feedback_phrases(self) -> List[str]:
        """Feedback phrases to inject for slow phases."""
        return [r.feedback_phrase for r in self.records if r.exceeded and r.feedback_phrase]

    def summary(self) -> Dict[str, Any]:
        return {
            "total_ms": round(self.total_ms, 1),
            "phases": {
                r.phase.value: {
                    "elapsed_ms": round(r.elapsed_ms, 1),
                    "budget_ms": r.budget_ms,
                    "exceeded": r.exceeded,
                }
                for r in self.records
            },
            "exceeded_count": len(self.exceeded_phases),
            "degradation_actions": [a.value for a in self.degradation_actions],
        }


# ─────────────────────────────────────────────────────────────────
# Latency Tracker  (p50 / p95 dashboard)
# ─────────────────────────────────────────────────────────────────


def _percentile(samples: List[float], pct: float) -> float:
    """Calculate percentile from sorted sample list."""
    if not samples:
        return 0.0
    sorted_s = sorted(samples)
    k = (len(sorted_s) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_s):
        return sorted_s[-1]
    return sorted_s[f] + (sorted_s[c] - sorted_s[f]) * (k - f)


class LatencyTracker:
    """
    Per-phase latency tracker with rolling window percentiles.

    Usage::

        tracker = LatencyTracker(budget_config)
        run = tracker.start_pipeline()
        tracker.record_phase(run, Phase.ASR, elapsed_ms=320)
        tracker.record_phase(run, Phase.ROUTER, elapsed_ms=45)
        ...
        tracker.finish_pipeline(run)
        dashboard = tracker.dashboard()
    """

    def __init__(self, config: Optional[LatencyBudgetConfig] = None, max_samples: int = _MAX_SAMPLES):
        self._config = config or LatencyBudgetConfig()
        self._max_samples = max_samples
        # phase → deque of elapsed_ms values
        self._samples: Dict[Phase, Deque[float]] = {p: deque(maxlen=max_samples) for p in Phase}
        # end-to-end totals
        self._e2e_samples: Deque[float] = deque(maxlen=max_samples)
        self._total_runs = 0
        self._exceeded_runs = 0

    @property
    def config(self) -> LatencyBudgetConfig:
        return self._config

    # ── pipeline lifecycle ────────────────────────────────────

    def start_pipeline(self) -> PipelineRun:
        """Begin a new pipeline run."""
        return PipelineRun(start_epoch=time.monotonic())

    def record_phase(self, run: PipelineRun, phase: Phase, elapsed_ms: float) -> PhaseRecord:
        """Record one phase's latency into *run* and the rolling window."""
        budget = self._config.phase_budget(phase)
        exceeded = budget.is_exceeded(elapsed_ms)
        record = PhaseRecord(
            phase=phase,
            elapsed_ms=elapsed_ms,
            budget_ms=budget.max_ms,
            exceeded=exceeded,
            degradation=budget.degradation if exceeded else DegradationAction.NONE,
            feedback_phrase=budget.feedback_phrase if exceeded else "",
        )
        run.records.append(record)
        self._samples[phase].append(elapsed_ms)

        if exceeded:
            logger.warning(
                "Phase %s exceeded budget: %.1fms > %.1fms — recommend %s",
                phase.value, elapsed_ms, budget.max_ms, record.degradation.value,
            )
        return record

    def finish_pipeline(self, run: PipelineRun) -> PipelineRun:
        """Finalise a pipeline run and record e2e latency."""
        run.end_epoch = time.monotonic()
        self._e2e_samples.append(run.total_ms)
        self._total_runs += 1
        if run.exceeded_phases:
            self._exceeded_runs += 1
        return run

    # ── dashboard / metrics ──────────────────────────────────

    def phase_stats(self, phase: Phase) -> Dict[str, float]:
        """p50 / p95 / min / max for a single phase."""
        samples = list(self._samples[phase])
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        return {
            "p50": round(_percentile(samples, 50), 1),
            "p95": round(_percentile(samples, 95), 1),
            "min": round(min(samples), 1),
            "max": round(max(samples), 1),
            "count": len(samples),
        }

    def e2e_stats(self) -> Dict[str, float]:
        """End-to-end pipeline percentiles."""
        samples = list(self._e2e_samples)
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        return {
            "p50": round(_percentile(samples, 50), 1),
            "p95": round(_percentile(samples, 95), 1),
            "min": round(min(samples), 1),
            "max": round(max(samples), 1),
            "count": len(samples),
        }

    def dashboard(self) -> Dict[str, Any]:
        """Full dashboard export suitable for logging / UI."""
        return {
            "total_runs": self._total_runs,
            "exceeded_runs": self._exceeded_runs,
            "budget_violation_rate": (
                round(self._exceeded_runs / self._total_runs, 3) if self._total_runs else 0.0
            ),
            "end_to_end": self.e2e_stats(),
            "phases": {p.value: self.phase_stats(p) for p in Phase},
            "budget_config": {
                "asr_max_ms": self._config.asr_max_ms,
                "router_max_ms": self._config.router_max_ms,
                "tool_max_ms": self._config.tool_max_ms,
                "finalizer_max_ms": self._config.finalizer_max_ms,
                "tts_max_ms": self._config.tts_max_ms,
                "end_to_end_max_ms": self._config.end_to_end_max_ms,
            },
        }

    def reset(self) -> None:
        """Clear all samples."""
        for d in self._samples.values():
            d.clear()
        self._e2e_samples.clear()
        self._total_runs = 0
        self._exceeded_runs = 0


# ─────────────────────────────────────────────────────────────────
# Budget Check Helper (for orchestrator integration)
# ─────────────────────────────────────────────────────────────────


def check_budget(
    config: LatencyBudgetConfig,
    phase: Phase,
    elapsed_ms: float,
) -> Tuple[bool, DegradationAction, str]:
    """
    Quick one-shot budget check.

    Returns:
        (exceeded, degradation_action, feedback_phrase)
    """
    budget = config.phase_budget(phase)
    exceeded = budget.is_exceeded(elapsed_ms)
    action = budget.degradation if exceeded else DegradationAction.NONE
    phrase = budget.feedback_phrase if exceeded else ""
    return exceeded, action, phrase


def should_skip_finalizer(
    config: LatencyBudgetConfig,
    elapsed_so_far_ms: float,
) -> bool:
    """
    Determine if the Gemini finalizer should be skipped in favor of 3B fallback.

    Called after ASR+Router+Tool phases. If the remaining budget is less than
    the finalizer's max, skip it.
    """
    remaining = config.end_to_end_max_ms - elapsed_so_far_ms
    return remaining < config.finalizer_max_ms
