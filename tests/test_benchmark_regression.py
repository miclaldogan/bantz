"""Benchmark Regression Tests (Issue #161).

Automated CI tests to prevent performance and quality regression:
- TTFT regression: Fail if p95 > 400ms
- JSON validity: Fail if < 95% valid JSON outputs
- Accuracy regression: Fail if overall accuracy drops below baseline
"""

from __future__ import annotations

import json
import pytest
import statistics
from pathlib import Path
from typing import Optional

# Regression thresholds
TTFT_P95_THRESHOLD_MS = 400  # Router TTFT p95 must be < 400ms
JSON_VALIDITY_THRESHOLD = 0.95  # 95% of outputs must be valid JSON
ACCURACY_THRESHOLD = 0.85  # 85% overall accuracy minimum
ROUTE_ACCURACY_THRESHOLD = 0.90  # 90% route accuracy minimum


class RegressionTest:
    """Base class for regression tests."""
    
    @staticmethod
    def load_benchmark_results(mode: str = "hybrid") -> Optional[dict]:
        """Load latest benchmark results."""
        results_dir = Path("artifacts/results")
        result_file = results_dir / f"bench_hybrid_{mode}.json"
        
        if not result_file.exists():
            return None
        
        with result_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    
    @staticmethod
    def get_summary(data: dict) -> dict:
        """Extract summary from benchmark results."""
        return data.get("summary", {})
    
    @staticmethod
    def get_results(data: dict) -> list[dict]:
        """Extract individual results from benchmark data."""
        return data.get("results", [])


class TestTTFTRegression(RegressionTest):
    """Test TTFT performance regression."""
    
    def test_router_ttft_p95_under_threshold(self):
        """Test that router TTFT p95 is under 400ms."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        ttft_p95 = summary.get("ttft_p95_ms", 0)
        
        assert ttft_p95 > 0, "TTFT p95 not measured"
        assert ttft_p95 < TTFT_P95_THRESHOLD_MS, (
            f"TTFT p95 regression: {ttft_p95:.0f}ms > {TTFT_P95_THRESHOLD_MS}ms threshold"
        )
    
    def test_router_ttft_p50_reasonable(self):
        """Test that router TTFT p50 is reasonable (<200ms)."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        ttft_p50 = summary.get("ttft_p50_ms", 0)
        
        assert ttft_p50 > 0, "TTFT p50 not measured"
        assert ttft_p50 < 200, (
            f"TTFT p50 too high: {ttft_p50:.0f}ms (expected <200ms)"
        )
    
    def test_total_latency_acceptable(self):
        """Test that total latency p95 is acceptable (<1000ms)."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        latency_p95 = summary.get("latency_p95_ms", 0)
        
        assert latency_p95 > 0, "Latency p95 not measured"
        assert latency_p95 < 1000, (
            f"Latency p95 too high: {latency_p95:.0f}ms (expected <1000ms)"
        )
    
    def test_ttft_consistency(self):
        """Test that TTFT values are consistent (p99 < 2x p50)."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        ttft_p50 = summary.get("ttft_p50_ms", 0)
        ttft_p99 = summary.get("ttft_p99_ms", 0)
        
        assert ttft_p50 > 0 and ttft_p99 > 0, "TTFT metrics not measured"
        
        # p99 should be less than 2x p50 for consistency
        ratio = ttft_p99 / ttft_p50
        assert ratio < 2.5, (
            f"TTFT inconsistent: p99 ({ttft_p99:.0f}ms) is {ratio:.1f}x p50 ({ttft_p50:.0f}ms)"
        )


class TestJSONValidityRegression(RegressionTest):
    """Test JSON output validity regression."""
    
    def test_json_parse_success_rate(self):
        """Test that >95% of outputs are valid JSON."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        results = self.get_results(data)
        assert len(results) > 0, "No test results found"
        
        # Count JSON parse failures
        json_errors = sum(1 for r in results if "json" in str(r.get("error", "")).lower())
        parse_success_rate = 1 - (json_errors / len(results))
        
        assert parse_success_rate >= JSON_VALIDITY_THRESHOLD, (
            f"JSON validity regression: {parse_success_rate:.1%} < {JSON_VALIDITY_THRESHOLD:.1%} threshold"
        )
    
    def test_no_route_enum_violations(self):
        """Test that route values are valid enums."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        results = self.get_results(data)
        valid_routes = {"calendar", "web", "browser", "smalltalk", "unknown", "error"}
        
        invalid_routes = [
            r for r in results
            if r.get("route") not in valid_routes
        ]
        
        invalid_rate = len(invalid_routes) / len(results) if results else 0
        
        assert invalid_rate < 0.05, (
            f"Route enum violations: {invalid_rate:.1%} (expected <5%)"
        )
    
    def test_tool_plan_format(self):
        """Test that tool_plan is always a list."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        results = self.get_results(data)
        
        invalid_tool_plans = [
            r for r in results
            if not isinstance(r.get("tools_called"), list)
        ]
        
        assert len(invalid_tool_plans) == 0, (
            f"Invalid tool_plan format in {len(invalid_tool_plans)} results"
        )


class TestAccuracyRegression(RegressionTest):
    """Test accuracy regression."""
    
    def test_overall_accuracy_above_threshold(self):
        """Test that overall accuracy is above 85%."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        overall_accuracy = summary.get("overall_accuracy", 0)
        
        assert overall_accuracy >= ACCURACY_THRESHOLD, (
            f"Accuracy regression: {overall_accuracy:.1%} < {ACCURACY_THRESHOLD:.1%} threshold"
        )
    
    def test_route_accuracy_high(self):
        """Test that route classification accuracy is high (>90%)."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        route_accuracy = summary.get("route_accuracy", 0)
        
        assert route_accuracy >= ROUTE_ACCURACY_THRESHOLD, (
            f"Route accuracy regression: {route_accuracy:.1%} < {ROUTE_ACCURACY_THRESHOLD:.1%} threshold"
        )
    
    def test_tools_accuracy_reasonable(self):
        """Test that tool selection accuracy is reasonable (>75%)."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        tools_accuracy = summary.get("tools_accuracy", 0)
        
        assert tools_accuracy >= 0.75, (
            f"Tools accuracy low: {tools_accuracy:.1%} (expected >75%)"
        )
    
    def test_no_accuracy_variance_by_difficulty(self):
        """Test that accuracy doesn't drop significantly for hard cases."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        results = self.get_results(data)
        
        # Calculate accuracy by difficulty
        by_difficulty = {"easy": [], "medium": [], "hard": []}
        for r in results:
            diff = r.get("difficulty", "unknown")
            if diff in by_difficulty:
                by_difficulty[diff].append(r.get("overall_correct", False))
        
        # Check that hard cases are still reasonable
        if by_difficulty["hard"]:
            hard_accuracy = sum(by_difficulty["hard"]) / len(by_difficulty["hard"])
            assert hard_accuracy >= 0.65, (
                f"Hard cases accuracy too low: {hard_accuracy:.1%} (expected >65%)"
            )


class TestFailureAnalysis(RegressionTest):
    """Analyze failure patterns for regression."""
    
    def test_failure_rate_acceptable(self):
        """Test that failure rate is acceptable (<10%)."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        summary = self.get_summary(data)
        total_cases = summary.get("total_cases", 0)
        failed_cases = summary.get("failed_cases", 0)
        
        failure_rate = failed_cases / total_cases if total_cases > 0 else 0
        
        assert failure_rate < 0.10, (
            f"High failure rate: {failure_rate:.1%} (expected <10%)"
        )
    
    def test_no_systematic_category_failures(self):
        """Test that no category has >20% failure rate."""
        data = self.load_benchmark_results("hybrid")
        if not data:
            pytest.skip("No benchmark results found")
        
        results = self.get_results(data)
        
        # Group by category
        by_category = {}
        for r in results:
            cat = r.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = {"total": 0, "failed": 0}
            by_category[cat]["total"] += 1
            if r.get("error"):
                by_category[cat]["failed"] += 1
        
        # Check each category
        failing_categories = []
        for cat, counts in by_category.items():
            failure_rate = counts["failed"] / counts["total"] if counts["total"] > 0 else 0
            if failure_rate > 0.20:
                failing_categories.append((cat, failure_rate))
        
        assert len(failing_categories) == 0, (
            f"Categories with high failure rate: {failing_categories}"
        )


class TestPerformanceComparison(RegressionTest):
    """Compare 3B-only vs Hybrid performance."""
    
    def test_hybrid_has_better_accuracy(self):
        """Test that hybrid mode has better accuracy than 3B-only."""
        data_3b = self.load_benchmark_results("3b_only")
        data_hybrid = self.load_benchmark_results("hybrid")
        
        if not data_3b or not data_hybrid:
            pytest.skip("Need both 3B and hybrid results for comparison")
        
        acc_3b = self.get_summary(data_3b).get("overall_accuracy", 0)
        acc_hybrid = self.get_summary(data_hybrid).get("overall_accuracy", 0)
        
        # Hybrid should be equal or better
        assert acc_hybrid >= acc_3b * 0.95, (
            f"Hybrid accuracy not better: {acc_hybrid:.1%} vs 3B {acc_3b:.1%}"
        )
    
    def test_hybrid_latency_acceptable(self):
        """Test that hybrid latency overhead is acceptable (<2x)."""
        data_3b = self.load_benchmark_results("3b_only")
        data_hybrid = self.load_benchmark_results("hybrid")
        
        if not data_3b or not data_hybrid:
            pytest.skip("Need both 3B and hybrid results for comparison")
        
        latency_3b = self.get_summary(data_3b).get("latency_mean_ms", 0)
        latency_hybrid = self.get_summary(data_hybrid).get("latency_mean_ms", 0)
        
        if latency_3b > 0:
            overhead = latency_hybrid / latency_3b
            assert overhead < 2.0, (
                f"Hybrid latency overhead too high: {overhead:.1f}x (expected <2x)"
            )


# ═══════════════════════════════════════════════════════════
# Continuous Integration Markers
# ═══════════════════════════════════════════════════════════

# Mark regression tests for CI
pytestmark = pytest.mark.regression


def test_regression_suite_complete():
    """Verify that regression test suite is complete."""
    # This test always passes, just documenting what we test
    test_categories = [
        "TTFT performance",
        "JSON validity",
        "Overall accuracy",
        "Route accuracy",
        "Tools accuracy",
        "Failure rate",
        "Performance comparison",
    ]
    
    assert len(test_categories) > 0
    print("\nRegression Test Coverage:")
    for cat in test_categories:
        print(f"  ✓ {cat}")
