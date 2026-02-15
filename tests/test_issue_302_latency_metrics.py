"""Tests for Issue #302 — Latency Budgets + Metrics Gates.

Covers:
  - TurnMetrics dataclass (schema, budget checking, serialization)
  - TurnMetricsWriter (JSONL persistence, thread safety, enable/disable)
  - LatencyGate + GateResult (CI gate definitions, evaluation)
  - check_gates / check_gates_from_records (JSONL gate checking)
  - read_turn_metrics (JSONL reader)
  - latency_report.py (report generation — markdown + JSON)
  - VoicePipeline integration (_emit_turn_metrics helper)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────
# TurnMetrics dataclass
# ─────────────────────────────────────────────────────────────────


class TestTurnMetrics:
    """TurnMetrics schema and budget-check logic."""

    def test_default_fields(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics()
        assert len(m.turn_id) == 12
        assert m.timestamp  # ISO string
        assert m.total_ms == 0.0
        assert m.success is True
        assert m.budget_violations == []

    def test_custom_fields(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(
            turn_id="t42",
            user_input="saat kaç",
            route="time",
            router_ms=120.0,
            total_ms=450.0,
        )
        assert m.turn_id == "t42"
        assert m.route == "time"
        assert m.router_ms == 120.0

    def test_check_budgets_no_violation(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(router_ms=100.0, total_ms=1000.0)
        violations = m.check_budgets(router_budget=500.0, total_budget=5000.0)
        assert violations == []
        assert m.budget_violations == []

    def test_check_budgets_with_violations(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(
            router_ms=620.0,
            finalize_ms=2500.0,
            total_ms=4200.0,
        )
        violations = m.check_budgets(
            router_budget=500.0,
            finalize_budget=2000.0,
            total_budget=5000.0,
        )
        assert len(violations) == 2
        assert any("router:620>500" in v for v in violations)
        assert any("finalize:2500>2000" in v for v in violations)

    def test_check_budgets_skips_none_phases(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(router_ms=100.0, total_ms=500.0)
        # asr_ms, tool_ms, finalize_ms, tts_ms are all None
        violations = m.check_budgets()
        assert violations == []

    def test_to_dict_omits_none_latencies(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(router_ms=100.0, total_ms=500.0)
        d = m.to_dict()
        assert "router_ms" in d
        assert "asr_ms" not in d
        assert "tool_ms" not in d
        assert "error" not in d

    def test_to_json_is_valid(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(
            turn_id="t1",
            user_input="merhaba",
            route="greeting",
            router_ms=50.0,
            total_ms=200.0,
        )
        j = m.to_json()
        parsed = json.loads(j)
        assert parsed["turn_id"] == "t1"
        assert parsed["route"] == "greeting"
        assert parsed["router_ms"] == 50.0

    def test_to_json_handles_turkish_chars(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(user_input="bugün hava nasıl?", route="hava")
        j = m.to_json()
        parsed = json.loads(j)
        assert "bugün" in parsed["user_input"]

    def test_log_debug_does_not_raise(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(router_ms=100.0, total_ms=500.0)
        m.log_debug()  # Should not raise

    def test_log_debug_with_violations(self):
        from bantz.metrics.turn_metrics import TurnMetrics

        m = TurnMetrics(router_ms=800.0, total_ms=6000.0)
        m.check_budgets(router_budget=500.0, total_budget=5000.0)
        m.log_debug()  # Should not raise


# ─────────────────────────────────────────────────────────────────
# TurnMetricsWriter
# ─────────────────────────────────────────────────────────────────


class TestTurnMetricsWriter:
    """JSONL writer with enable/disable and thread safety."""

    def test_write_creates_file(self, tmp_path):
        from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter

        path = tmp_path / "metrics.jsonl"
        writer = TurnMetricsWriter(path=str(path), enabled=True)
        m = TurnMetrics(turn_id="t1", router_ms=100.0, total_ms=500.0)

        assert writer.write(m) is True
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["turn_id"] == "t1"

    def test_write_appends(self, tmp_path):
        from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter

        path = tmp_path / "metrics.jsonl"
        writer = TurnMetricsWriter(path=str(path), enabled=True)

        writer.write(TurnMetrics(turn_id="t1", total_ms=100.0))
        writer.write(TurnMetrics(turn_id="t2", total_ms=200.0))

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert writer.count == 2

    def test_write_disabled_returns_false(self, tmp_path):
        from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter

        path = tmp_path / "metrics.jsonl"
        writer = TurnMetricsWriter(path=str(path), enabled=False)

        result = writer.write(TurnMetrics(turn_id="t1", total_ms=100.0))
        assert result is False
        assert not path.exists()
        assert writer.count == 0

    def test_env_var_enable(self, tmp_path):
        from bantz.metrics.turn_metrics import TurnMetricsWriter

        with mock.patch.dict(os.environ, {"BANTZ_TURN_METRICS": "1"}):
            writer = TurnMetricsWriter(path=str(tmp_path / "m.jsonl"))
            assert writer.enabled is True

    def test_env_var_disable(self, tmp_path):
        from bantz.metrics.turn_metrics import TurnMetricsWriter

        with mock.patch.dict(os.environ, {"BANTZ_TURN_METRICS": "0"}):
            writer = TurnMetricsWriter(path=str(tmp_path / "m.jsonl"))
            assert writer.enabled is False

    def test_creates_parent_dirs(self, tmp_path):
        from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter

        path = tmp_path / "deep" / "nested" / "metrics.jsonl"
        writer = TurnMetricsWriter(path=str(path), enabled=True)
        writer.write(TurnMetrics(turn_id="t1", total_ms=100.0))
        assert path.exists()

    def test_thread_safety(self, tmp_path):
        """Multiple threads can write concurrently without data corruption."""
        import threading

        from bantz.metrics.turn_metrics import TurnMetrics, TurnMetricsWriter

        path = tmp_path / "mt.jsonl"
        writer = TurnMetricsWriter(path=str(path), enabled=True)

        def write_batch(start: int):
            for i in range(10):
                writer.write(TurnMetrics(turn_id=f"t{start + i}", total_ms=float(i * 10)))

        threads = [threading.Thread(target=write_batch, args=(i * 10,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 50
        assert writer.count == 50


# ─────────────────────────────────────────────────────────────────
# LatencyGate / GateResult
# ─────────────────────────────────────────────────────────────────


class TestLatencyGate:
    """CI gate definitions."""

    def test_default_label_auto_generated(self):
        from bantz.metrics.gates import LatencyGate

        g = LatencyGate(phase="router_ms", percentile=95, max_ms=500.0)
        assert "router" in g.label
        assert "p95" in g.label
        assert "500" in g.label

    def test_custom_label(self):
        from bantz.metrics.gates import LatencyGate

        g = LatencyGate(phase="total_ms", percentile=99, max_ms=5000.0, label="custom")
        assert g.label == "custom"

    def test_default_gates_exist(self):
        from bantz.metrics.gates import DEFAULT_GATES

        assert len(DEFAULT_GATES) >= 4
        phases = [g.phase for g in DEFAULT_GATES]
        assert "router_ms" in phases
        assert "total_ms" in phases


class TestGateResult:
    """Gate evaluation result."""

    def test_summary_line_pass(self):
        from bantz.metrics.gates import GateResult, LatencyGate

        g = LatencyGate(phase="router_ms", percentile=95, max_ms=500.0)
        r = GateResult(gate=g, actual_value=350.0, sample_count=100, passed=True)
        line = r.summary_line()
        assert "✅" in line
        assert "350" in line

    def test_summary_line_fail(self):
        from bantz.metrics.gates import GateResult, LatencyGate

        g = LatencyGate(phase="router_ms", percentile=95, max_ms=500.0)
        r = GateResult(gate=g, actual_value=620.0, sample_count=100, passed=False)
        line = r.summary_line()
        assert "❌" in line
        assert "620" in line


# ─────────────────────────────────────────────────────────────────
# read_turn_metrics
# ─────────────────────────────────────────────────────────────────


class TestReadTurnMetrics:
    """JSONL reader."""

    def test_read_valid_jsonl(self, tmp_path):
        from bantz.metrics.gates import read_turn_metrics

        path = tmp_path / "m.jsonl"
        lines = [
            json.dumps({"turn_id": "t1", "router_ms": 100, "total_ms": 500}),
            json.dumps({"turn_id": "t2", "router_ms": 200, "total_ms": 600}),
        ]
        path.write_text("\n".join(lines) + "\n")

        records = read_turn_metrics(path)
        assert len(records) == 2
        assert records[0]["turn_id"] == "t1"

    def test_skip_malformed_lines(self, tmp_path):
        from bantz.metrics.gates import read_turn_metrics

        path = tmp_path / "m.jsonl"
        path.write_text('{"ok": true}\nNOT JSON\n{"ok": true}\n')

        records = read_turn_metrics(path)
        assert len(records) == 2

    def test_missing_file_returns_empty(self, tmp_path):
        from bantz.metrics.gates import read_turn_metrics

        records = read_turn_metrics(tmp_path / "nonexistent.jsonl")
        assert records == []

    def test_empty_file_returns_empty(self, tmp_path):
        from bantz.metrics.gates import read_turn_metrics

        path = tmp_path / "empty.jsonl"
        path.write_text("")

        records = read_turn_metrics(path)
        assert records == []


# ─────────────────────────────────────────────────────────────────
# check_gates
# ─────────────────────────────────────────────────────────────────


class TestCheckGates:
    """End-to-end gate checking from JSONL."""

    def _write_jsonl(self, path: Path, records: list[dict]) -> None:
        with path.open("w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def test_all_gates_pass(self, tmp_path):
        from bantz.metrics.gates import LatencyGate, check_gates

        path = tmp_path / "m.jsonl"
        records = [
            {"router_ms": 100, "tool_ms": 500, "finalize_ms": 800, "tts_ms": 200, "total_ms": 1600}
            for _ in range(20)
        ]
        self._write_jsonl(path, records)

        gates = [
            LatencyGate(phase="router_ms", percentile=95, max_ms=500.0),
            LatencyGate(phase="total_ms", percentile=95, max_ms=5000.0),
        ]
        results = check_gates(path, gates=gates)
        assert all(r.passed for r in results)

    def test_gate_fails(self, tmp_path):
        from bantz.metrics.gates import LatencyGate, check_gates

        path = tmp_path / "m.jsonl"
        # 10 fast + 10 slow → p95 will be slow
        records = [{"router_ms": 100, "total_ms": 500} for _ in range(10)]
        records += [{"router_ms": 800, "total_ms": 3000} for _ in range(10)]
        self._write_jsonl(path, records)

        gates = [LatencyGate(phase="router_ms", percentile=95, max_ms=500.0)]
        results = check_gates(path, gates=gates)
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].actual_value > 500

    def test_insufficient_samples_skips(self, tmp_path):
        from bantz.metrics.gates import LatencyGate, check_gates

        path = tmp_path / "m.jsonl"
        records = [{"router_ms": 1000, "total_ms": 5000}]  # only 1
        self._write_jsonl(path, records)

        gates = [LatencyGate(phase="router_ms", percentile=95, max_ms=500.0)]
        results = check_gates(path, gates=gates, min_samples=5)
        assert results[0].passed  # skipped due to insufficient samples
        assert "Insufficient" in results[0].detail

    def test_missing_phase_in_records(self, tmp_path):
        from bantz.metrics.gates import LatencyGate, check_gates

        path = tmp_path / "m.jsonl"
        records = [{"router_ms": 100, "total_ms": 500} for _ in range(10)]
        self._write_jsonl(path, records)

        # Gate for tool_ms which is missing from records
        gates = [LatencyGate(phase="tool_ms", percentile=95, max_ms=2000.0)]
        results = check_gates(path, gates=gates, min_samples=5)
        assert results[0].passed  # skipped — no tool_ms data

    def test_check_gates_from_records(self):
        from bantz.metrics.gates import LatencyGate, check_gates_from_records

        records = [
            {"router_ms": 100, "total_ms": 500},
            {"router_ms": 200, "total_ms": 600},
            {"router_ms": 150, "total_ms": 550},
        ]
        gates = [LatencyGate(phase="router_ms", percentile=95, max_ms=500.0)]
        results = check_gates_from_records(records, gates=gates, min_samples=1)
        assert results[0].passed
        assert results[0].sample_count == 3


# ─────────────────────────────────────────────────────────────────
# Latency report
# ─────────────────────────────────────────────────────────────────


class TestLatencyReport:
    """scripts/latency_report.py report generation."""

    def _write_jsonl(self, path: Path, records: list[dict]) -> None:
        with path.open("w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def test_markdown_report(self, tmp_path):
        import importlib
        import sys

        # Import the script
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "latency_report.py"
        spec = importlib.util.spec_from_file_location("latency_report", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        records = [
            {
                "turn_id": f"t{i}",
                "timestamp": "2025-01-01T00:00:00+00:00",
                "route": "time",
                "router_ms": 100 + i * 5,
                "total_ms": 1000 + i * 20,
            }
            for i in range(20)
        ]

        report = mod.generate_markdown_report(records)
        assert "Bantz Latency Report" in report
        assert "Router" in report
        assert "p50" in report or "p95" in report

    def test_json_report(self, tmp_path):
        import importlib

        script_path = Path(__file__).resolve().parents[1] / "scripts" / "latency_report.py"
        spec = importlib.util.spec_from_file_location("latency_report", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        records = [
            {"turn_id": f"t{i}", "router_ms": 100 + i, "total_ms": 500 + i * 10}
            for i in range(10)
        ]

        output = mod.generate_json_report(records)
        parsed = json.loads(output)
        assert "phases" in parsed
        assert "router_ms" in parsed["phases"]
        assert parsed["total_turns"] == 10

    def test_cli_main(self, tmp_path):
        import importlib

        script_path = Path(__file__).resolve().parents[1] / "scripts" / "latency_report.py"
        spec = importlib.util.spec_from_file_location("latency_report", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        path = tmp_path / "m.jsonl"
        records = [
            {"turn_id": f"t{i}", "router_ms": 100, "total_ms": 500, "timestamp": "2025-01-01T00:00:00+00:00"}
            for i in range(5)
        ]
        self._write_jsonl(path, records)

        output_file = tmp_path / "report.md"
        ret = mod.main(["--file", str(path), "--output", str(output_file)])
        assert ret == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "Bantz" in content


# ─────────────────────────────────────────────────────────────────
# Gates CLI
# ─────────────────────────────────────────────────────────────────


class TestGatesCLI:
    """CLI entry for bantz.metrics.gates."""

    def _write_jsonl(self, path: Path, records: list[dict]) -> None:
        with path.open("w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def test_cli_all_pass(self, tmp_path, capsys):
        from bantz.metrics.gates import main

        path = tmp_path / "m.jsonl"
        records = [
            {"router_ms": 100, "tool_ms": 500, "finalize_ms": 800, "tts_ms": 200, "total_ms": 1600}
            for _ in range(20)
        ]
        self._write_jsonl(path, records)

        ret = main([str(path), "5"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "✅" in captured.out

    def test_cli_gate_fail(self, tmp_path, capsys):
        from bantz.metrics.gates import main

        path = tmp_path / "m.jsonl"
        records = [
            {"router_ms": 800, "tool_ms": 500, "finalize_ms": 800, "tts_ms": 200, "total_ms": 6000}
            for _ in range(20)
        ]
        self._write_jsonl(path, records)

        ret = main([str(path), "5"])
        assert ret == 1
        captured = capsys.readouterr()
        assert "❌" in captured.out

    def test_cli_no_args(self, capsys):
        from bantz.metrics.gates import main

        ret = main([])
        assert ret == 2


# ─────────────────────────────────────────────────────────────────
# VoicePipeline integration
# ─────────────────────────────────────────────────────────────────


class TestPipelineMetricsIntegration:
    """VoicePipeline._emit_turn_metrics wiring."""

    def test_emit_turn_metrics_writes_jsonl(self, tmp_path):
        """_emit_turn_metrics should produce a valid JSONL record."""
        from bantz.voice.pipeline import PipelineResult, StepTiming, VoicePipeline

        # Prepare a writer pointing to tmp_path
        jsonl = tmp_path / "turn_metrics.jsonl"

        with mock.patch(
            "bantz.voice.pipeline._get_metrics_writer"
        ) as mock_get:
            from bantz.metrics.turn_metrics import TurnMetricsWriter

            writer = TurnMetricsWriter(path=str(jsonl), enabled=True)
            mock_get.return_value = writer

            result = PipelineResult(
                transcription="saat kaç",
                route="time",
                reply="Saat 14:30 efendim.",
                timings=[
                    StepTiming(name="brain", elapsed_ms=450.0, budget_ms=4500.0),
                ],
                total_ms=500.0,
                success=True,
                finalizer_tier="3b",
            )

            VoicePipeline._emit_turn_metrics(result)

        assert jsonl.exists()
        data = json.loads(jsonl.read_text().strip())
        assert data["route"] == "time"
        assert data["total_ms"] == 500.0
        assert data["router_ms"] == 450.0  # "brain" maps to router_ms

    def test_emit_turn_metrics_disabled_no_file(self, tmp_path):
        """When writer is disabled, no file is created."""
        from bantz.voice.pipeline import PipelineResult, VoicePipeline

        jsonl = tmp_path / "turn_metrics.jsonl"

        with mock.patch("bantz.voice.pipeline._get_metrics_writer") as mock_get:
            from bantz.metrics.turn_metrics import TurnMetricsWriter

            writer = TurnMetricsWriter(path=str(jsonl), enabled=False)
            mock_get.return_value = writer

            result = PipelineResult(transcription="test", total_ms=100.0)
            VoicePipeline._emit_turn_metrics(result)

        assert not jsonl.exists()

    def test_emit_turn_metrics_handles_missing_writer(self):
        """When _get_metrics_writer returns None, nothing crashes."""
        from bantz.voice.pipeline import PipelineResult, VoicePipeline

        with mock.patch("bantz.voice.pipeline._get_metrics_writer", return_value=None):
            result = PipelineResult(transcription="test", total_ms=100.0)
            VoicePipeline._emit_turn_metrics(result)  # Should not raise

    def test_emit_turn_metrics_with_asr_and_tts(self, tmp_path):
        """Full pipeline with ASR + TTS timings."""
        from bantz.voice.pipeline import PipelineResult, StepTiming, VoicePipeline

        jsonl = tmp_path / "turn_metrics.jsonl"

        with mock.patch("bantz.voice.pipeline._get_metrics_writer") as mock_get:
            from bantz.metrics.turn_metrics import TurnMetricsWriter

            writer = TurnMetricsWriter(path=str(jsonl), enabled=True)
            mock_get.return_value = writer

            result = PipelineResult(
                transcription="haber ver",
                route="news",
                timings=[
                    StepTiming(name="asr", elapsed_ms=300.0, budget_ms=500.0),
                    StepTiming(name="brain", elapsed_ms=800.0, budget_ms=4500.0),
                    StepTiming(name="tts", elapsed_ms=250.0, budget_ms=500.0),
                ],
                total_ms=1350.0,
                success=True,
            )

            VoicePipeline._emit_turn_metrics(result)

        data = json.loads(jsonl.read_text().strip())
        assert data["asr_ms"] == 300.0
        assert data["tts_ms"] == 250.0
        assert data["total_ms"] == 1350.0

    def test_emit_handles_exception_gracefully(self, tmp_path):
        """If TurnMetrics import fails, _emit_turn_metrics doesn't crash."""
        from bantz.voice.pipeline import PipelineResult, VoicePipeline

        with mock.patch("bantz.voice.pipeline._get_metrics_writer") as mock_get:
            # Return a writer that throws on write
            mock_writer = mock.MagicMock()
            mock_writer.return_value = True
            mock_get.return_value = mock_writer

            # Patch TurnMetrics to raise
            with mock.patch(
                "bantz.metrics.turn_metrics.TurnMetrics",
                side_effect=RuntimeError("boom"),
            ):
                result = PipelineResult(transcription="test", total_ms=100.0)
                VoicePipeline._emit_turn_metrics(result)  # Should not raise


# ─────────────────────────────────────────────────────────────────
# Package imports
# ─────────────────────────────────────────────────────────────────


class TestPackageImports:
    """Verify bantz.metrics package exports are accessible."""

    def test_import_turn_metrics(self):
        from bantz.metrics import TurnMetrics, TurnMetricsWriter

        assert TurnMetrics is not None
        assert TurnMetricsWriter is not None

    def test_import_gates(self):
        from bantz.metrics import LatencyGate, GateResult, check_gates, DEFAULT_GATES

        assert LatencyGate is not None
        assert check_gates is not None
        assert len(DEFAULT_GATES) >= 4

    def test_import_read_turn_metrics(self):
        from bantz.metrics import read_turn_metrics

        assert callable(read_turn_metrics)

    def test_import_check_gates_from_records(self):
        from bantz.metrics import check_gates_from_records

        assert callable(check_gates_from_records)
