"""Tests for 3B Model Benchmark Framework.

Issue #239: Test model benchmark, scoring, and report generation.

Test categories:
1. ModelCandidate dataclass
2. Test case structures
3. Result dataclasses
4. Benchmark engine (with mock)
5. Report generation
6. Mock benchmark
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from bantz.llm.model_benchmark import (
    DEFAULT_CANDIDATES,
    ModelBenchmark,
    ModelBenchmarkResult,
    ModelCandidate,
    ROUTER_TEST_CASES,
    RouterResult,
    RouterTestCase,
    SMALLTALK_TEST_CASES,
    SmalltalkResult,
    SmalltalkTestCase,
    generate_report,
    run_mock_benchmark,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_model() -> ModelCandidate:
    """Create a sample model candidate."""
    return ModelCandidate(
        name="Test-Model-3B",
        hf_id="test/test-model-3b",
        quantization="awq",
        notes="Test model",
    )


@pytest.fixture
def sample_router_test() -> RouterTestCase:
    """Create a sample router test case."""
    return RouterTestCase(
        user_text="saat kaç",
        expected_route="system",
        expected_intent="time",
    )


@pytest.fixture
def sample_smalltalk_test() -> SmalltalkTestCase:
    """Create a sample smalltalk test case."""
    return SmalltalkTestCase(
        user_text="merhaba",
        expected_keywords=["merhaba", "selam", "iyi"],
    )


@pytest.fixture
def temp_report_path() -> Generator[str, None, None]:
    """Create a temporary report path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        temp_path = f.name
    
    yield temp_path
    
    try:
        Path(temp_path).unlink()
    except OSError:
        pass


# ============================================================================
# MODEL CANDIDATE TESTS
# ============================================================================

class TestModelCandidate:
    """Test ModelCandidate dataclass."""
    
    def test_create_candidate(self, sample_model):
        """Test candidate creation."""
        assert sample_model.name == "Test-Model-3B"
        assert sample_model.hf_id == "test/test-model-3b"
        assert sample_model.quantization == "awq"
    
    def test_candidate_defaults(self):
        """Test default values."""
        model = ModelCandidate(
            name="Test",
            hf_id="test/test",
        )
        
        assert model.quantization == "awq"
        assert model.gpu_memory_utilization == 0.85
        assert model.max_model_len == 4096
    
    def test_candidate_to_dict(self, sample_model):
        """Test dictionary conversion."""
        data = sample_model.to_dict()
        
        assert data["name"] == "Test-Model-3B"
        assert data["hf_id"] == "test/test-model-3b"
    
    def test_default_candidates_exist(self):
        """Test that default candidates are defined."""
        assert len(DEFAULT_CANDIDATES) >= 3
        assert all(isinstance(c, ModelCandidate) for c in DEFAULT_CANDIDATES)


# ============================================================================
# TEST CASE TESTS
# ============================================================================

class TestRouterTestCase:
    """Test RouterTestCase structure."""
    
    def test_create_test_case(self, sample_router_test):
        """Test creation."""
        assert sample_router_test.user_text == "saat kaç"
        assert sample_router_test.expected_route == "system"
        assert sample_router_test.expected_intent == "time"
    
    def test_optional_slots(self):
        """Test optional expected_slots."""
        tc = RouterTestCase(
            user_text="test",
            expected_route="test",
            expected_slots={"key": "value"},
        )
        
        assert tc.expected_slots["key"] == "value"
    
    def test_default_test_cases_exist(self):
        """Test that default test cases are defined."""
        assert len(ROUTER_TEST_CASES) >= 5
        assert all(isinstance(tc, RouterTestCase) for tc in ROUTER_TEST_CASES)


class TestSmalltalkTestCase:
    """Test SmalltalkTestCase structure."""
    
    def test_create_test_case(self, sample_smalltalk_test):
        """Test creation."""
        assert sample_smalltalk_test.user_text == "merhaba"
        assert "merhaba" in sample_smalltalk_test.expected_keywords
    
    def test_defaults(self):
        """Test default values."""
        tc = SmalltalkTestCase(user_text="test")
        
        assert tc.min_length == 10
        assert tc.max_length == 500
        assert tc.expected_keywords == []
    
    def test_default_test_cases_exist(self):
        """Test that default test cases are defined."""
        assert len(SMALLTALK_TEST_CASES) >= 3
        assert all(isinstance(tc, SmalltalkTestCase) for tc in SMALLTALK_TEST_CASES)


# ============================================================================
# RESULT DATACLASS TESTS
# ============================================================================

class TestRouterResult:
    """Test RouterResult dataclass."""
    
    def test_create_result(self, sample_router_test):
        """Test result creation."""
        result = RouterResult(
            test_case=sample_router_test,
            raw_output='{"route": "system"}',
            parsed_output={"route": "system"},
            parse_success=True,
            route_correct=True,
            latency_ms=45.5,
            tokens_generated=10,
        )
        
        assert result.parse_success is True
        assert result.route_correct is True
        assert result.latency_ms == 45.5
    
    def test_result_to_dict(self, sample_router_test):
        """Test dictionary conversion."""
        result = RouterResult(
            test_case=sample_router_test,
            raw_output="{}",
            parse_success=True,
            latency_ms=50,
        )
        
        data = result.to_dict()
        
        assert data["user_text"] == "saat kaç"
        assert data["latency_ms"] == 50


class TestSmalltalkResult:
    """Test SmalltalkResult dataclass."""
    
    def test_create_result(self, sample_smalltalk_test):
        """Test result creation."""
        result = SmalltalkResult(
            test_case=sample_smalltalk_test,
            response="Merhaba! Size nasıl yardımcı olabilirim?",
            keyword_hits=1,
            length_ok=True,
            quality_score=0.85,
            latency_ms=60,
        )
        
        assert result.quality_score == 0.85
        assert result.length_ok is True
    
    def test_result_to_dict(self, sample_smalltalk_test):
        """Test dictionary conversion."""
        result = SmalltalkResult(
            test_case=sample_smalltalk_test,
            response="Test response",
            quality_score=0.7,
            latency_ms=55,
        )
        
        data = result.to_dict()
        
        assert data["quality_score"] == 0.7


class TestModelBenchmarkResult:
    """Test ModelBenchmarkResult dataclass."""
    
    def test_create_result(self, sample_model):
        """Test result creation."""
        result = ModelBenchmarkResult(
            model=sample_model,
            json_compliance_rate=0.95,
            route_accuracy=0.90,
            smalltalk_quality=0.85,
            avg_latency_ms=50,
            overall_score=0.88,
        )
        
        assert result.json_compliance_rate == 0.95
        assert result.overall_score == 0.88
    
    def test_result_to_dict(self, sample_model):
        """Test dictionary conversion."""
        result = ModelBenchmarkResult(
            model=sample_model,
            json_compliance_rate=0.90,
            route_accuracy=0.85,
            avg_tokens_per_sec=100,
        )
        
        data = result.to_dict()
        
        assert data["json_compliance_rate"] == 0.90
        assert data["avg_tokens_per_sec"] == 100
        assert "model" in data


# ============================================================================
# BENCHMARK ENGINE TESTS
# ============================================================================

class TestModelBenchmark:
    """Test ModelBenchmark engine."""
    
    def test_create_benchmark(self):
        """Test benchmark creation."""
        bench = ModelBenchmark(vllm_base="http://test:8001")
        
        assert bench.vllm_base == "http://test:8001"
        assert bench.timeout == 30.0
    
    def test_parse_json_direct(self):
        """Test direct JSON parsing."""
        bench = ModelBenchmark()
        
        text = '{"route": "calendar", "intent": "create"}'
        result = bench._parse_json(text)
        
        assert result is not None
        assert result["route"] == "calendar"
    
    def test_parse_json_with_preamble(self):
        """Test JSON parsing with extra text."""
        bench = ModelBenchmark()
        
        text = 'Certainly! {"route": "system"}'
        result = bench._parse_json(text)
        
        assert result is not None
        assert result["route"] == "system"
    
    def test_parse_json_invalid(self):
        """Test invalid JSON handling."""
        bench = ModelBenchmark()
        
        text = "This is not JSON at all"
        result = bench._parse_json(text)
        
        assert result is None
    
    def test_run_router_tests_mock(self):
        """Test router tests with mocked vLLM."""
        bench = ModelBenchmark()
        
        # Mock the _call_vllm method
        def mock_call(prompt, **kwargs):
            return '{"route": "system", "intent": "time"}', 50.0, 15
        
        bench._call_vllm = mock_call
        
        # Run with single test case
        results = bench.run_router_tests([
            RouterTestCase(
                user_text="saat kaç",
                expected_route="system",
                expected_intent="time",
            )
        ])
        
        assert len(results) == 1
        assert results[0].parse_success is True
        assert results[0].route_correct is True
    
    def test_run_smalltalk_tests_mock(self):
        """Test smalltalk tests with mocked vLLM."""
        bench = ModelBenchmark()
        
        # Mock response with Turkish
        def mock_call(prompt, **kwargs):
            return "Merhaba! Size nasıl yardımcı olabilirim?", 60.0, 20
        
        bench._call_vllm = mock_call
        
        results = bench.run_smalltalk_tests([
            SmalltalkTestCase(
                user_text="merhaba",
                expected_keywords=["merhaba", "yardım"],
            )
        ])
        
        assert len(results) == 1
        assert results[0].quality_score > 0.5  # Should score well
    
    def test_run_full_benchmark_mock(self, sample_model):
        """Test full benchmark with mocked vLLM."""
        bench = ModelBenchmark()
        
        call_count = 0
        
        def mock_call(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            
            # Alternate between router and smalltalk responses
            if "JSON" in kwargs.get("system_prompt", ""):
                return '{"route": "system", "intent": "time"}', 45.0, 10
            else:
                return "Merhaba efendim!", 55.0, 15
        
        bench._call_vllm = mock_call
        
        result = bench.run_benchmark(sample_model)
        
        assert result.model == sample_model
        assert result.json_compliance_rate >= 0
        assert result.route_accuracy >= 0
        assert result.overall_score >= 0


# ============================================================================
# REPORT GENERATION TESTS
# ============================================================================

class TestReportGeneration:
    """Test report generation."""
    
    def test_generate_empty_report(self, temp_report_path):
        """Test report with no results."""
        report = generate_report([], temp_report_path)
        
        assert "# 3B Model Benchmark Report" in report
        assert "Summary" in report
    
    def test_generate_report_with_results(self, temp_report_path, sample_model):
        """Test report with results."""
        results = [
            ModelBenchmarkResult(
                model=sample_model,
                json_compliance_rate=0.95,
                route_accuracy=0.90,
                smalltalk_quality=0.85,
                avg_latency_ms=50,
                avg_tokens_per_sec=100,
                overall_score=0.88,
            ),
        ]
        
        report = generate_report(results, temp_report_path)
        
        assert "Test-Model-3B" in report
        assert "95%" in report  # JSON compliance
        assert "Recommendation" in report
        assert Path(temp_report_path).exists()
    
    def test_report_contains_vllm_flags(self, temp_report_path, sample_model):
        """Test that report includes vLLM flags."""
        results = [
            ModelBenchmarkResult(
                model=sample_model,
                json_compliance_rate=0.90,
                overall_score=0.85,
            ),
        ]
        
        report = generate_report(results, temp_report_path)
        
        assert "--model" in report
        assert "--quantization" in report


# ============================================================================
# MOCK BENCHMARK TESTS
# ============================================================================

class TestMockBenchmark:
    """Test mock benchmark functionality."""
    
    def test_run_mock_benchmark(self):
        """Test mock benchmark returns results."""
        results = run_mock_benchmark()
        
        assert len(results) >= 3
        assert all(isinstance(r, ModelBenchmarkResult) for r in results)
    
    def test_mock_results_have_scores(self):
        """Test that mock results have realistic scores."""
        results = run_mock_benchmark()
        
        for r in results:
            assert 0 <= r.json_compliance_rate <= 1
            assert 0 <= r.route_accuracy <= 1
            assert 0 <= r.smalltalk_quality <= 1
            assert 0 <= r.overall_score <= 1
            assert r.avg_latency_ms > 0
            assert r.avg_tokens_per_sec > 0
    
    def test_mock_results_sorted_by_score(self):
        """Test that results can be sorted by overall score."""
        results = run_mock_benchmark()
        
        sorted_results = sorted(results, key=lambda r: r.overall_score, reverse=True)
        
        # First should have highest score
        assert sorted_results[0].overall_score >= sorted_results[-1].overall_score


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for full workflow."""
    
    def test_full_workflow(self, temp_report_path, sample_model):
        """Test complete benchmark -> report workflow."""
        # Create mock benchmark
        bench = ModelBenchmark()
        
        # Mock vLLM calls
        def mock_call(prompt, **kwargs):
            if "JSON" in str(kwargs):
                return '{"route": "calendar", "intent": "query"}', 40.0, 12
            return "Merhaba, size yardımcı olabilirim.", 50.0, 18
        
        bench._call_vllm = mock_call
        
        # Run benchmark
        result = bench.run_benchmark(sample_model)
        
        # Generate report
        report = generate_report([result], temp_report_path)
        
        # Verify
        assert result.overall_score > 0
        assert Path(temp_report_path).exists()
        assert sample_model.name in report
    
    def test_multiple_models_ranking(self, temp_report_path):
        """Test ranking of multiple models."""
        models = [
            ModelCandidate(name="Model-A", hf_id="a/a"),
            ModelCandidate(name="Model-B", hf_id="b/b"),
        ]
        
        results = [
            ModelBenchmarkResult(
                model=models[0],
                json_compliance_rate=0.90,
                route_accuracy=0.85,
                overall_score=0.75,
            ),
            ModelBenchmarkResult(
                model=models[1],
                json_compliance_rate=0.95,
                route_accuracy=0.92,
                overall_score=0.88,
            ),
        ]
        
        report = generate_report(results, temp_report_path)
        
        # Model-B should be recommended (higher score)
        assert "Model-B" in report
        assert "Recommended Model" in report
