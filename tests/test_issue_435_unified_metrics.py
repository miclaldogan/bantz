"""
Tests for Issue #435 — Unified Metrics Collector.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bantz.analytics.metrics import (
    HistogramBucket,
    MetricPoint,
    MetricType,
    MetricsCollector,
    record_gemini_tokens,
    record_json_validity,
    record_llm_call,
    record_tool_call,
    record_turn_latency,
    metrics,
)


class TestMetricPoint:
    def test_to_dict(self):
        p = MetricPoint("llm_calls", MetricType.COUNTER, 1.0, {"model": "3b"}, 100.0)
        d = p.to_dict()
        assert d["name"] == "llm_calls"
        assert d["type"] == "counter"
        assert d["labels"]["model"] == "3b"


class TestHistogramBucket:
    def test_empty(self):
        b = HistogramBucket()
        assert b.count == 0
        assert b.avg == 0.0

    def test_single_observation(self):
        b = HistogramBucket()
        b.observe(100.0)
        assert b.count == 1
        assert b.avg == 100.0
        assert b.min_val == 100.0
        assert b.max_val == 100.0

    def test_multiple_observations(self):
        b = HistogramBucket()
        for v in [10, 20, 30, 40, 50]:
            b.observe(v)
        assert b.count == 5
        assert b.avg == 30.0
        assert b.min_val == 10
        assert b.max_val == 50

    def test_percentiles(self):
        b = HistogramBucket()
        for v in range(1, 101):
            b.observe(float(v))
        assert 49.0 <= b.p50 <= 51.0
        assert b.p95 >= 94.0

    def test_to_dict(self):
        b = HistogramBucket()
        b.observe(10.0)
        b.observe(20.0)
        d = b.to_dict()
        assert d["count"] == 2
        assert d["avg"] == 15.0
        assert "p50" in d


class TestMetricsCollector:
    def setup_method(self):
        self.m = MetricsCollector()

    def test_increment_counter(self):
        self.m.increment("calls", labels={"model": "3b"})
        self.m.increment("calls", labels={"model": "3b"})
        assert self.m.get_counter("calls", {"model": "3b"}) == 2.0

    def test_increment_different_labels(self):
        self.m.increment("calls", labels={"model": "3b"})
        self.m.increment("calls", labels={"model": "gemini"})
        assert self.m.get_counter("calls", {"model": "3b"}) == 1.0
        assert self.m.get_counter("calls", {"model": "gemini"}) == 1.0

    def test_set_gauge(self):
        self.m.set_gauge("rate", 0.95)
        assert self.m.get_gauge("rate") == 0.95
        self.m.set_gauge("rate", 0.80)
        assert self.m.get_gauge("rate") == 0.80

    def test_observe_histogram(self):
        self.m.observe("latency", 100.0, labels={"phase": "router"})
        self.m.observe("latency", 200.0, labels={"phase": "router"})
        h = self.m.get_histogram("latency", {"phase": "router"})
        assert h["count"] == 2
        assert h["avg"] == 150.0

    def test_summary(self):
        self.m.increment("calls")
        self.m.set_gauge("rate", 0.9)
        self.m.observe("latency", 50.0)
        s = self.m.summary()
        assert "counters" in s
        assert "gauges" in s
        assert "histograms" in s
        assert s["total_points"] == 3

    def test_export_jsonl(self):
        self.m.increment("calls")
        self.m.observe("latency", 100.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "metrics.jsonl"
            count = self.m.export_jsonl(path)
            assert count == 2
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2
            for line in lines:
                d = json.loads(line)
                assert "name" in d

    def test_reset(self):
        self.m.increment("calls")
        self.m.reset()
        assert self.m.get_counter("calls") == 0.0

    def test_nonexistent_counter(self):
        assert self.m.get_counter("nope") == 0.0

    def test_nonexistent_histogram(self):
        h = self.m.get_histogram("nope")
        assert h["count"] == 0

    def test_thread_safety(self):
        """Basic thread safety: concurrent increments should not lose data."""
        import threading
        def inc():
            for _ in range(100):
                self.m.increment("concurrent")
        threads = [threading.Thread(target=inc) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert self.m.get_counter("concurrent") == 400.0


class TestConvenienceHelpers:
    def setup_method(self):
        metrics.reset()

    def test_record_llm_call(self):
        record_llm_call("3b", "router", "ok", 245.0)
        assert metrics.get_counter("llm_calls", {"model": "3b", "phase": "router", "status": "ok"}) == 1.0
        h = metrics.get_histogram("llm_latency", {"model": "3b", "phase": "router"})
        assert h["count"] == 1

    def test_record_tool_call(self):
        record_tool_call("calendar.list_events", "ok", 150.0)
        assert metrics.get_counter("tool_calls", {"tool": "calendar.list_events", "status": "ok"}) == 1.0

    def test_record_turn_latency(self):
        record_turn_latency("calendar", 500.0)
        h = metrics.get_histogram("turn_latency", {"route": "calendar"})
        assert h["count"] == 1

    def test_record_gemini_tokens(self):
        record_gemini_tokens(150)
        assert metrics.get_counter("gemini_tokens_used") == 150.0

    def test_record_json_validity(self):
        record_json_validity(True)
        record_json_validity(True)
        record_json_validity(False)
        rate = metrics.get_gauge("json_validity_rate")
        assert 0.6 < rate < 0.7  # 2/3
