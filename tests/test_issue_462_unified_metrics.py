"""Tests for issue #462 — Unified Metrics Collector."""

from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

from bantz.core.metrics_collector import (
    MetricRecord,
    MetricsCollector,
    MetricsConfig,
    MetricsSummary,
    percentile,
)


# ── TestPercentile ────────────────────────────────────────────────────

class TestPercentile:
    def test_single_value(self):
        assert percentile([42.0], 50) == 42.0

    def test_even_count(self):
        assert percentile([10, 20, 30, 40], 50) == 25.0

    def test_p99_large_list(self):
        vals = list(range(1, 101))  # 1..100
        p = percentile(vals, 99)
        assert p >= 99.0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            percentile([], 50)

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError, match="0 and 100"):
            percentile([1, 2, 3], 101)


# ── TestMetricRecord ──────────────────────────────────────────────────

class TestMetricRecord:
    def test_to_dict(self):
        r = MetricRecord(name="latency", value=100.0, unit="ms")
        d = r.to_dict()
        assert d["name"] == "latency"
        assert d["value"] == 100.0
        assert d["unit"] == "ms"

    def test_to_json_roundtrip(self):
        r = MetricRecord(name="x", value=1.5, tags={"k": "v"})
        parsed = json.loads(r.to_json())
        assert parsed["name"] == "x"
        assert parsed["tags"] == {"k": "v"}


# ── TestRecording ─────────────────────────────────────────────────────

class TestRecording:
    def test_record_returns_metric(self):
        mc = MetricsCollector()
        rec = mc.record("test", 42.0)
        assert isinstance(rec, MetricRecord)
        assert rec.name == "test"
        assert rec.value == 42.0

    def test_count_increases(self):
        mc = MetricsCollector()
        assert mc.count == 0
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        assert mc.count == 2

    def test_metric_names(self):
        mc = MetricsCollector()
        mc.record("beta", 1.0)
        mc.record("alpha", 2.0)
        mc.record("alpha", 3.0)
        assert mc.metric_names() == ["alpha", "beta"]


# ── TestRingBuffer ────────────────────────────────────────────────────

class TestRingBuffer:
    def test_max_records_enforced(self):
        mc = MetricsCollector(MetricsConfig(max_records=5))
        for i in range(10):
            mc.record("x", float(i))
        assert mc.count == 5
        records = mc.get_records()
        values = [r.value for r in records]
        assert values == [5.0, 6.0, 7.0, 8.0, 9.0]


# ── TestGetRecords ────────────────────────────────────────────────────

class TestGetRecords:
    def test_filter_by_name(self):
        mc = MetricsCollector()
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        mc.record("a", 3.0)
        recs = mc.get_records("a")
        assert len(recs) == 2
        assert all(r.name == "a" for r in recs)

    def test_filter_by_tags(self):
        mc = MetricsCollector()
        mc.record("lat", 100.0, tags={"backend": "vllm"})
        mc.record("lat", 200.0, tags={"backend": "gemini"})
        recs = mc.get_records("lat", tags={"backend": "vllm"})
        assert len(recs) == 1
        assert recs[0].value == 100.0

    def test_filter_by_time_window(self):
        mc = MetricsCollector()
        # Insert an old record by manually setting ts
        old = MetricRecord(name="x", value=1.0, ts=time.monotonic() - 9999)
        mc._records.append(old)
        mc.record("x", 2.0)
        recs = mc.get_records("x", last_seconds=10)
        assert len(recs) == 1
        assert recs[0].value == 2.0


# ── TestSummarize ─────────────────────────────────────────────────────

class TestSummarize:
    def test_basic_summary(self):
        mc = MetricsCollector()
        for v in [10, 20, 30, 40, 50]:
            mc.record("lat", float(v), unit="ms")
        s = mc.summarize("lat")
        assert s is not None
        assert s.name == "lat"
        assert s.count == 5
        assert s.total == 150.0
        assert s.mean == 30.0
        assert s.min == 10.0
        assert s.max == 50.0
        assert s.unit == "ms"

    def test_summarize_none_if_empty(self):
        mc = MetricsCollector()
        assert mc.summarize("nonexistent") is None

    def test_summarize_all(self):
        mc = MetricsCollector()
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        mc.record("a", 3.0)
        summaries = mc.summarize_all()
        assert set(summaries.keys()) == {"a", "b"}
        assert summaries["a"].count == 2
        assert summaries["b"].count == 1

    def test_percentiles_in_summary(self):
        mc = MetricsCollector()
        for v in range(1, 101):
            mc.record("lat", float(v))
        s = mc.summarize("lat")
        assert s is not None
        assert s.p50 == pytest.approx(50.5, abs=1.0)
        assert s.p90 >= 89.0
        assert s.p99 >= 98.0


# ── TestJSONLPersistence ──────────────────────────────────────────────

class TestJSONLPersistence:
    def test_flush_writes_jsonl(self, tmp_path):
        path = str(tmp_path / "metrics.jsonl")
        mc = MetricsCollector(MetricsConfig(jsonl_path=path))
        mc.record("lat", 100.0, unit="ms")
        mc.record("lat", 200.0, unit="ms")
        written = mc.flush()
        assert written == 2

        lines = open(path).readlines()
        assert len(lines) == 2
        parsed = json.loads(lines[0])
        assert parsed["name"] == "lat"

    def test_flush_no_path_returns_zero(self):
        mc = MetricsCollector()
        assert mc.flush() == 0

    def test_auto_flush(self, tmp_path):
        path = str(tmp_path / "auto.jsonl")
        mc = MetricsCollector(MetricsConfig(jsonl_path=path, auto_flush_every=3))
        mc.record("a", 1.0)
        mc.record("a", 2.0)
        # After 2 records, no auto-flush yet
        assert not os.path.exists(path)
        mc.record("a", 3.0)
        # 3rd record triggers auto flush
        assert os.path.exists(path)
        lines = open(path).readlines()
        assert len(lines) == 3


# ── TestClear ─────────────────────────────────────────────────────────

class TestClear:
    def test_clear_removes_all(self):
        mc = MetricsCollector()
        mc.record("a", 1.0)
        mc.record("b", 2.0)
        mc.clear()
        assert mc.count == 0
        assert mc.metric_names() == []


# ── TestSummaryStr ────────────────────────────────────────────────────

class TestSummaryStr:
    def test_str_format(self):
        s = MetricsSummary(
            name="lat", count=10, total=100.0, mean=10.0,
            min=5.0, max=15.0, p50=10.0, p90=14.0, p99=15.0, unit="ms"
        )
        text = str(s)
        assert "[lat]" in text
        assert "count=10" in text
        assert "(ms)" in text
