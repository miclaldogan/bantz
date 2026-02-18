# SPDX-License-Identifier: MIT
"""Tests for Issue #1220: Sprint framework & pipeline metrics."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter
from bantz.metrics.pipeline_metrics import (
    PipelineMetrics,
    compute_pipeline_metrics,
    _percentile,
)


class TestTurnMetricsNewFields:
    """TurnMetrics has Issue #1220 fields."""

    def test_tools_ok_default(self) -> None:
        m = TurnMetrics()
        assert m.tools_ok == 0
        assert m.tools_fail == 0

    def test_confirmation_triggered_default(self) -> None:
        m = TurnMetrics()
        assert m.confirmation_triggered is False
        assert m.confirmation_tool is None

    def test_to_dict_includes_new_fields(self) -> None:
        m = TurnMetrics(tools_ok=2, tools_fail=1, confirmation_triggered=True,
                        confirmation_tool="calendar.create_event")
        d = m.to_dict()
        assert d["tools_ok"] == 2
        assert d["tools_fail"] == 1
        assert d["confirmation_triggered"] is True
        assert d["confirmation_tool"] == "calendar.create_event"

    def test_to_dict_omits_none_confirmation_tool(self) -> None:
        m = TurnMetrics()
        d = m.to_dict()
        assert "confirmation_tool" not in d

    def test_json_roundtrip(self) -> None:
        m = TurnMetrics(tools_ok=3, confirmation_triggered=True)
        s = m.to_json()
        d = json.loads(s)
        assert d["tools_ok"] == 3
        assert d["confirmation_triggered"] is True


class TestPipelineMetrics:
    """compute_pipeline_metrics computes correct aggregates."""

    @pytest.fixture
    def sample_jsonl(self, tmp_path: Path) -> str:
        p = tmp_path / "metrics.jsonl"
        records = [
            {"success": True, "route": "calendar", "tools_ok": 1, "tools_fail": 0,
             "confirmation_triggered": False, "router_ms": 200, "tool_ms": 500,
             "finalize_ms": 300, "total_ms": 1000},
            {"success": True, "route": "gmail", "tools_ok": 1, "tools_fail": 0,
             "confirmation_triggered": False, "router_ms": 250, "tool_ms": 600,
             "finalize_ms": 400, "total_ms": 1250},
            {"success": False, "route": "calendar", "tools_ok": 0, "tools_fail": 1,
             "confirmation_triggered": False, "router_ms": 180, "tool_ms": 100,
             "finalize_ms": 50, "total_ms": 330},
            {"success": True, "route": "calendar", "tools_ok": 1, "tools_fail": 0,
             "confirmation_triggered": True, "confirmation_tool": "calendar.create_event",
             "router_ms": 220, "tool_ms": 800, "finalize_ms": 350, "total_ms": 1370},
        ]
        with p.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        return str(p)

    def test_total_turns(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        assert m.total_turns == 4

    def test_success_rate(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        assert m.successful_turns == 3
        assert m.failed_turns == 1
        assert m.success_rate == pytest.approx(0.75)

    def test_confirmation_count(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        assert m.confirmation_triggered == 1
        assert m.confirmation_rate == pytest.approx(0.25)

    def test_tool_success_rate(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        assert m.total_tools_ok == 3
        assert m.total_tools_fail == 1
        assert m.tool_success_rate == pytest.approx(0.75)

    def test_route_breakdown(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        assert m.route_breakdown["calendar"]["ok"] == 2
        assert m.route_breakdown["calendar"]["fail"] == 1
        assert m.route_breakdown["gmail"]["ok"] == 1

    def test_latency_breakdown(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        total_lat = next(l for l in m.latency_breakdown if l.phase == "total")
        assert total_lat.count == 4
        assert total_lat.max == 1370

    def test_last_n(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl, last_n=2)
        assert m.total_turns == 2

    def test_missing_file(self, tmp_path: Path) -> None:
        m = compute_pipeline_metrics(str(tmp_path / "nope.jsonl"))
        assert m.total_turns == 0
        assert m.success_rate == 0.0

    def test_str_output(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        s = str(m)
        assert "Pipeline Metrics Report" in s
        assert "75.0%" in s

    def test_to_dict(self, sample_jsonl: str) -> None:
        m = compute_pipeline_metrics(sample_jsonl)
        d = m.to_dict()
        assert d["total_turns"] == 4
        assert isinstance(d["latency_breakdown"], list)


class TestPercentile:
    """Unit tests for _percentile helper."""

    def test_empty(self) -> None:
        assert _percentile([], 50) == 0.0

    def test_single(self) -> None:
        assert _percentile([100.0], 50) == 100.0

    def test_p50(self) -> None:
        data = [10, 20, 30, 40, 50]
        assert _percentile(data, 50) == 30.0

    def test_p95(self) -> None:
        data = list(range(1, 101))
        assert _percentile(data, 95) == pytest.approx(95.05, abs=0.1)
