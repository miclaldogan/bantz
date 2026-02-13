"""
Tests for Issue #437 — Router Accuracy Benchmark.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bantz.analytics.router_accuracy import (
    AccuracyReport,
    GoldenCase,
    PredictionResult,
    RouterAccuracyBenchmark,
    load_golden_cases,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "router_accuracy.jsonl"


class TestGoldenCase:
    def test_frozen(self):
        c = GoldenCase(text="test", expected_route="calendar")
        with pytest.raises(AttributeError):
            c.text = "other"


class TestAccuracyReport:
    def test_empty_report(self):
        r = AccuracyReport()
        assert r.route_accuracy == 0.0
        assert r.to_dict()["total_cases"] == 0

    def test_perfect_accuracy(self):
        r = AccuracyReport(total_cases=10, route_correct=10, intent_correct=10, slot_correct=10)
        assert r.route_accuracy == 1.0
        assert r.intent_accuracy == 1.0
        assert r.slot_accuracy == 1.0

    def test_partial_accuracy(self):
        r = AccuracyReport(total_cases=10, route_correct=8, intent_correct=7, slot_correct=6)
        assert r.route_accuracy == 0.8
        assert r.intent_accuracy == 0.7

    def test_to_dict(self):
        r = AccuracyReport(total_cases=5, route_correct=5, intent_correct=4, slot_correct=3)
        d = r.to_dict()
        assert d["route_accuracy"] == 1.0
        assert d["intent_accuracy"] == 0.8
        assert d["total_cases"] == 5

    def test_summary_text(self):
        r = AccuracyReport(total_cases=100, route_correct=95, intent_correct=90, slot_correct=85)
        text = r.summary_text()
        assert "95.0%" in text
        assert "100 cases" in text


class TestGoldenFile:
    def test_golden_file_exists(self):
        assert GOLDEN_PATH.exists()

    def test_load_golden_cases(self):
        cases = load_golden_cases(GOLDEN_PATH)
        assert len(cases) >= 90  # We defined ~97 cases

    def test_golden_has_calendar(self):
        cases = load_golden_cases(GOLDEN_PATH)
        cal_cases = [c for c in cases if c.expected_route == "calendar"]
        assert len(cal_cases) >= 25

    def test_golden_has_gmail(self):
        cases = load_golden_cases(GOLDEN_PATH)
        gmail_cases = [c for c in cases if c.expected_route == "gmail"]
        assert len(gmail_cases) >= 10

    def test_golden_has_smalltalk(self):
        cases = load_golden_cases(GOLDEN_PATH)
        st_cases = [c for c in cases if c.expected_route == "smalltalk"]
        assert len(st_cases) >= 20


class TestRouterAccuracyBenchmark:
    def test_perfect_predictor(self):
        cases = [
            GoldenCase("test1", "calendar", "query"),
            GoldenCase("test2", "gmail", "list"),
            GoldenCase("test3", "smalltalk", "none"),
        ]
        bench = RouterAccuracyBenchmark(cases)

        def perfect(text: str) -> PredictionResult:
            m = {
                "test1": PredictionResult("calendar", "query"),
                "test2": PredictionResult("gmail", "list"),
                "test3": PredictionResult("smalltalk", "none"),
            }
            return m[text]

        report = bench.evaluate(perfect)
        assert report.route_accuracy == 1.0
        assert report.intent_accuracy == 1.0
        assert len(report.errors) == 0

    def test_bad_predictor(self):
        cases = [
            GoldenCase("test1", "calendar", "query"),
            GoldenCase("test2", "gmail", "list"),
        ]
        bench = RouterAccuracyBenchmark(cases)

        def always_smalltalk(text: str) -> PredictionResult:
            return PredictionResult("smalltalk", "none")

        report = bench.evaluate(always_smalltalk)
        assert report.route_accuracy == 0.0
        assert len(report.errors) == 2

    def test_exception_in_predictor(self):
        cases = [GoldenCase("test", "calendar")]
        bench = RouterAccuracyBenchmark(cases)

        def broken(text: str) -> PredictionResult:
            raise ValueError("model crashed")

        report = bench.evaluate(broken)
        assert len(report.errors) == 1
        assert "model crashed" in report.errors[0]["error"]

    def test_confusion_matrix(self):
        cases = [
            GoldenCase("a", "calendar"),
            GoldenCase("b", "calendar"),
            GoldenCase("c", "gmail"),
        ]
        bench = RouterAccuracyBenchmark(cases)

        def mixed(text: str) -> PredictionResult:
            if text == "a":
                return PredictionResult("calendar")
            return PredictionResult("smalltalk")

        report = bench.evaluate(mixed)
        assert report.confusion["calendar"]["calendar"] == 1
        assert report.confusion["calendar"]["smalltalk"] == 1
        assert report.confusion["gmail"]["smalltalk"] == 1

    def test_slot_accuracy_check(self):
        cases = [
            GoldenCase("test", "calendar", "create", {"title": "toplantı", "time": "14:00"}),
        ]
        bench = RouterAccuracyBenchmark(cases)

        def with_slots(text: str) -> PredictionResult:
            return PredictionResult("calendar", "create", {"title": "toplantı", "time": "14:00"})

        report = bench.evaluate(with_slots)
        assert report.slot_accuracy == 1.0

    def test_slot_mismatch(self):
        cases = [
            GoldenCase("test", "calendar", "create", {"title": "toplantı"}),
        ]
        bench = RouterAccuracyBenchmark(cases)

        def wrong_slots(text: str) -> PredictionResult:
            return PredictionResult("calendar", "create", {"title": "yemek"})

        report = bench.evaluate(wrong_slots)
        assert report.slot_accuracy == 0.0

    def test_case_count(self):
        bench = RouterAccuracyBenchmark.from_golden_file(GOLDEN_PATH)
        assert bench.case_count >= 90
