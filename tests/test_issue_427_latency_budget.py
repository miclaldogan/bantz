"""
Tests for Issue #427 — Voice Pipeline Latency Budget.

Covers:
- LatencyBudgetConfig defaults and construction
- PhaseBudget exceeded checks
- LatencyTracker per-phase recording + e2e finalization
- Percentile calculation (p50 / p95)
- Dashboard export
- Degradation action mapping
- Feedback phrases
- should_skip_finalizer decision
- check_budget helper
- load_budget_from_yaml (with mock and real file)
- Conversation orchestrator integration (latency in get_stats)
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bantz.core.latency_budget import (
    DegradationAction,
    LatencyBudgetConfig,
    LatencyTracker,
    Phase,
    PhaseBudget,
    PhaseRecord,
    PipelineRun,
    _percentile,
    check_budget,
    load_budget_from_yaml,
    should_skip_finalizer,
)


# ─────────────────────────────────────────────────────────────────
# Config defaults
# ─────────────────────────────────────────────────────────────────


class TestLatencyBudgetConfig:
    """Test configuration dataclass."""

    def test_defaults(self):
        cfg = LatencyBudgetConfig()
        assert cfg.asr_max_ms == 500.0
        assert cfg.router_max_ms == 100.0
        assert cfg.tool_max_ms == 1000.0
        assert cfg.finalizer_max_ms == 500.0
        assert cfg.tts_max_ms == 300.0
        assert cfg.end_to_end_max_ms == 2000.0

    def test_total_phase_budget(self):
        cfg = LatencyBudgetConfig()
        assert cfg.total_phase_budget_ms == 2400.0  # 500+100+1000+500+300

    def test_custom_values(self):
        cfg = LatencyBudgetConfig(asr_max_ms=300, router_max_ms=50)
        assert cfg.asr_max_ms == 300
        assert cfg.router_max_ms == 50

    def test_phase_budget_returns_correct_type(self):
        cfg = LatencyBudgetConfig()
        pb = cfg.phase_budget(Phase.ASR)
        assert isinstance(pb, PhaseBudget)
        assert pb.phase == Phase.ASR
        assert pb.max_ms == 500.0

    def test_all_phase_budgets_has_five(self):
        cfg = LatencyBudgetConfig()
        budgets = cfg.all_phase_budgets()
        assert len(budgets) == 5
        phases = [b.phase for b in budgets]
        assert Phase.ASR in phases
        assert Phase.TTS in phases


# ─────────────────────────────────────────────────────────────────
# Phase budget checks
# ─────────────────────────────────────────────────────────────────


class TestPhaseBudget:
    """Test single-phase budget behaviour."""

    def test_within_budget(self):
        pb = PhaseBudget(phase=Phase.ROUTER, max_ms=100, degradation=DegradationAction.NONE)
        assert not pb.is_exceeded(99)

    def test_exactly_at_budget(self):
        pb = PhaseBudget(phase=Phase.ROUTER, max_ms=100, degradation=DegradationAction.NONE)
        assert not pb.is_exceeded(100)

    def test_exceeds_budget(self):
        pb = PhaseBudget(phase=Phase.ROUTER, max_ms=100, degradation=DegradationAction.NONE)
        assert pb.is_exceeded(101)


# ─────────────────────────────────────────────────────────────────
# Percentile helper
# ─────────────────────────────────────────────────────────────────


class TestPercentile:
    """Test _percentile()."""

    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single_value(self):
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 95) == 42.0

    def test_known_p50(self):
        samples = [10, 20, 30, 40, 50]
        assert _percentile(samples, 50) == 30.0

    def test_p95_high(self):
        samples = list(range(1, 101))  # 1..100
        p95 = _percentile(samples, 95)
        assert 95 <= p95 <= 96  # close to 95.05


# ─────────────────────────────────────────────────────────────────
# Pipeline Run
# ─────────────────────────────────────────────────────────────────


class TestPipelineRun:
    """Test PipelineRun aggregate methods."""

    def test_total_from_records(self):
        run = PipelineRun()
        run.records = [
            PhaseRecord(Phase.ASR, 200, 500, False),
            PhaseRecord(Phase.ROUTER, 50, 100, False),
        ]
        assert run.total_ms == 250

    def test_total_from_epoch(self):
        run = PipelineRun(start_epoch=1000.0, end_epoch=1001.5)
        assert run.total_ms == 1500.0

    def test_exceeded_phases(self):
        run = PipelineRun()
        run.records = [
            PhaseRecord(Phase.ASR, 200, 500, False),
            PhaseRecord(Phase.TOOL, 1500, 1000, True, DegradationAction.ASYNC_TOOL_WITH_FEEDBACK),
        ]
        assert len(run.exceeded_phases) == 1
        assert run.exceeded_phases[0].phase == Phase.TOOL

    def test_degradation_actions(self):
        run = PipelineRun()
        run.records = [
            PhaseRecord(Phase.TOOL, 1500, 1000, True, DegradationAction.ASYNC_TOOL_WITH_FEEDBACK),
            PhaseRecord(Phase.FINALIZER, 600, 500, True, DegradationAction.SKIP_FINALIZER_USE_3B),
        ]
        actions = run.degradation_actions
        assert DegradationAction.ASYNC_TOOL_WITH_FEEDBACK in actions
        assert DegradationAction.SKIP_FINALIZER_USE_3B in actions

    def test_feedback_phrases(self):
        run = PipelineRun()
        run.records = [
            PhaseRecord(Phase.TOOL, 1500, 1000, True, feedback_phrase="Bir bakayım efendim..."),
        ]
        assert run.feedback_phrases == ["Bir bakayım efendim..."]

    def test_summary_keys(self):
        run = PipelineRun()
        run.records = [PhaseRecord(Phase.ASR, 200, 500, False)]
        s = run.summary()
        assert "total_ms" in s
        assert "phases" in s
        assert "exceeded_count" in s
        assert "degradation_actions" in s

    def test_headroom(self):
        rec = PhaseRecord(Phase.ASR, 300, 500, False)
        assert rec.headroom_ms == 200


# ─────────────────────────────────────────────────────────────────
# Latency Tracker
# ─────────────────────────────────────────────────────────────────


class TestLatencyTracker:
    """Test the main tracker with rolling window."""

    def test_basic_pipeline(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        tracker.record_phase(run, Phase.ASR, 300)
        tracker.record_phase(run, Phase.ROUTER, 50)
        tracker.record_phase(run, Phase.TOOL, 400)
        tracker.record_phase(run, Phase.FINALIZER, 200)
        tracker.record_phase(run, Phase.TTS, 150)
        tracker.finish_pipeline(run)

        assert tracker._total_runs == 1
        assert tracker._exceeded_runs == 0

    def test_exceeded_pipeline(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        tracker.record_phase(run, Phase.ASR, 600)  # over 500
        tracker.record_phase(run, Phase.ROUTER, 50)
        tracker.record_phase(run, Phase.TOOL, 400)
        tracker.record_phase(run, Phase.FINALIZER, 200)
        tracker.record_phase(run, Phase.TTS, 150)
        tracker.finish_pipeline(run)

        assert tracker._exceeded_runs == 1
        assert run.exceeded_phases[0].phase == Phase.ASR

    def test_phase_stats(self):
        tracker = LatencyTracker()
        for val in [100, 200, 300, 400, 500]:
            run = tracker.start_pipeline()
            tracker.record_phase(run, Phase.ASR, val)
            tracker.finish_pipeline(run)

        stats = tracker.phase_stats(Phase.ASR)
        assert stats["count"] == 5
        assert stats["min"] == 100
        assert stats["max"] == 500
        assert stats["p50"] == 300.0

    def test_e2e_stats(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        tracker.record_phase(run, Phase.ASR, 200)
        tracker.record_phase(run, Phase.ROUTER, 50)
        tracker.finish_pipeline(run)

        stats = tracker.e2e_stats()
        assert stats["count"] == 1
        # p50 may be very small (near zero) because start/finish are close
        assert stats["p50"] >= 0

    def test_dashboard_structure(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        tracker.record_phase(run, Phase.ASR, 200)
        tracker.finish_pipeline(run)

        dash = tracker.dashboard()
        assert "total_runs" in dash
        assert "exceeded_runs" in dash
        assert "budget_violation_rate" in dash
        assert "end_to_end" in dash
        assert "phases" in dash
        assert "budget_config" in dash
        assert "asr" in dash["phases"]

    def test_reset(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        tracker.record_phase(run, Phase.ASR, 200)
        tracker.finish_pipeline(run)
        tracker.reset()

        assert tracker._total_runs == 0
        assert tracker.phase_stats(Phase.ASR)["count"] == 0

    def test_degradation_logged_on_exceed(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        rec = tracker.record_phase(run, Phase.TOOL, 1500)
        assert rec.exceeded
        assert rec.degradation == DegradationAction.ASYNC_TOOL_WITH_FEEDBACK

    def test_no_degradation_within_budget(self):
        tracker = LatencyTracker()
        run = tracker.start_pipeline()
        rec = tracker.record_phase(run, Phase.ROUTER, 50)
        assert not rec.exceeded
        assert rec.degradation == DegradationAction.NONE

    def test_max_samples_cap(self):
        tracker = LatencyTracker(max_samples=10)
        for i in range(20):
            run = tracker.start_pipeline()
            tracker.record_phase(run, Phase.ASR, float(i * 10))
            tracker.finish_pipeline(run)
        assert tracker.phase_stats(Phase.ASR)["count"] == 10


# ─────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────


class TestCheckBudget:
    """Test check_budget() one-shot helper."""

    def test_within_budget(self):
        cfg = LatencyBudgetConfig()
        exceeded, action, phrase = check_budget(cfg, Phase.ROUTER, 50)
        assert not exceeded
        assert action == DegradationAction.NONE
        assert phrase == ""

    def test_over_budget(self):
        cfg = LatencyBudgetConfig()
        exceeded, action, phrase = check_budget(cfg, Phase.TOOL, 1500)
        assert exceeded
        assert action == DegradationAction.ASYNC_TOOL_WITH_FEEDBACK
        assert phrase == "Bir bakayım efendim..."

    def test_finalizer_over_budget(self):
        cfg = LatencyBudgetConfig()
        exceeded, action, phrase = check_budget(cfg, Phase.FINALIZER, 600)
        assert exceeded
        assert action == DegradationAction.SKIP_FINALIZER_USE_3B
        assert phrase == "Hemen söylüyorum..."


class TestShouldSkipFinalizer:
    """Test should_skip_finalizer decision."""

    def test_plenty_of_time(self):
        cfg = LatencyBudgetConfig()
        # elapsed 800ms, remaining 1200ms > 500ms finalizer budget
        assert not should_skip_finalizer(cfg, 800)

    def test_no_time_left(self):
        cfg = LatencyBudgetConfig()
        # elapsed 1700ms, remaining 300ms < 500ms finalizer budget
        assert should_skip_finalizer(cfg, 1700)

    def test_exact_boundary(self):
        cfg = LatencyBudgetConfig()
        # remaining == finalizer budget → should NOT skip (not less than)
        assert not should_skip_finalizer(cfg, 1500)


# ─────────────────────────────────────────────────────────────────
# YAML loading
# ─────────────────────────────────────────────────────────────────


class TestLoadBudgetFromYaml:
    """Test load_budget_from_yaml."""

    def test_load_real_config(self):
        """Load actual model-settings.yaml from project."""
        cfg = load_budget_from_yaml()
        assert cfg.asr_max_ms == 500
        assert cfg.router_max_ms == 100
        assert cfg.end_to_end_max_ms == 2000

    def test_missing_file_returns_defaults(self):
        cfg = load_budget_from_yaml(Path("/nonexistent/path.yaml"))
        assert cfg.asr_max_ms == 500  # default
        assert cfg.end_to_end_max_ms == 2000

    def test_yaml_without_section_returns_defaults(self, tmp_path):
        """YAML file that has no voice_pipeline section."""
        p = tmp_path / "empty.yaml"
        p.write_text("models:\n  router:\n    name: test\n")
        cfg = load_budget_from_yaml(p)
        assert cfg.asr_max_ms == 500


# ─────────────────────────────────────────────────────────────────
# Degradation mapping
# ─────────────────────────────────────────────────────────────────


class TestDegradationMapping:
    """Verify every phase has a sensible degradation action."""

    def test_all_phases_have_degradation(self):
        cfg = LatencyBudgetConfig()
        for phase in Phase:
            pb = cfg.phase_budget(phase)
            # every phase has a degradation defined (even if no feedback)
            assert pb.degradation is not None

    def test_asr_degradation(self):
        cfg = LatencyBudgetConfig()
        pb = cfg.phase_budget(Phase.ASR)
        assert pb.degradation == DegradationAction.USE_PARTIAL_ASR

    def test_tts_degradation(self):
        cfg = LatencyBudgetConfig()
        pb = cfg.phase_budget(Phase.TTS)
        assert pb.degradation == DegradationAction.USE_CACHED_TTS


# ─────────────────────────────────────────────────────────────────
# Feedback phrases
# ─────────────────────────────────────────────────────────────────


class TestFeedbackPhrases:
    """Verify Turkish feedback phrases are set for slow phases."""

    def test_tool_has_phrase(self):
        cfg = LatencyBudgetConfig()
        pb = cfg.phase_budget(Phase.TOOL)
        assert "bakayım" in pb.feedback_phrase

    def test_finalizer_has_phrase(self):
        cfg = LatencyBudgetConfig()
        pb = cfg.phase_budget(Phase.FINALIZER)
        assert "söylüyorum" in pb.feedback_phrase

    def test_asr_no_phrase(self):
        cfg = LatencyBudgetConfig()
        pb = cfg.phase_budget(Phase.ASR)
        assert pb.feedback_phrase == ""


# ─────────────────────────────────────────────────────────────────
# Orchestrator integration (latency in stats)
# ─────────────────────────────────────────────────────────────────


class TestOrchestratorIntegration:
    """Verify conversation orchestrator exposes latency dashboard."""

    def test_get_stats_has_latency(self):
        from bantz.conversation.orchestrator import ConversationOrchestrator
        orch = ConversationOrchestrator()
        stats = orch.get_stats()
        assert "latency" in stats
        assert "total_runs" in stats["latency"]
        assert "phases" in stats["latency"]
