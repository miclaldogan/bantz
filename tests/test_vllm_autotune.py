"""Tests for vLLM Auto-tune Framework.

Issue #240: Test auto-tune profiles, grid search, and report generation.

Test categories:
1. Profile definitions
2. VLLMConfig dataclass
3. Grid parameters
4. Benchmark results
5. Tuner operations
6. Report generation
7. Mock tuning
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from bantz.llm.vllm_autotune import (
    BenchmarkResult,
    FULL_GRID,
    PROFILES,
    QUICK_GRID,
    TuneGridParams,
    TuneProfile,
    TuneResult,
    VLLMBenchmark,
    VLLMConfig,
    VLLMTuner,
    generate_tune_report,
    run_mock_tune,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_config() -> VLLMConfig:
    """Create a sample vLLM config."""
    return VLLMConfig(
        model="test/model",
        quantization="awq",
        gpu_memory_utilization=0.85,
        max_model_len=4096,
        max_num_seqs=256,
    )


@pytest.fixture
def router_profile() -> TuneProfile:
    """Get router profile."""
    return PROFILES["router"]


@pytest.fixture
def generation_profile() -> TuneProfile:
    """Get generation profile."""
    return PROFILES["generation"]


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
# PROFILE TESTS
# ============================================================================

class TestTuneProfile:
    """Test TuneProfile dataclass."""
    
    def test_router_profile_exists(self):
        """Test router profile is defined."""
        assert "router" in PROFILES
        profile = PROFILES["router"]
        assert profile.name == "router"
        assert profile.latency_weight > profile.throughput_weight
    
    def test_generation_profile_exists(self):
        """Test generation profile is defined."""
        assert "generation" in PROFILES
        profile = PROFILES["generation"]
        assert profile.name == "generation"
    
    def test_profile_to_dict(self, router_profile):
        """Test profile dictionary conversion."""
        data = router_profile.to_dict()
        
        assert data["name"] == "router"
        assert "latency_weight" in data
        assert "throughput_weight" in data
    
    def test_router_profile_parameters(self, router_profile):
        """Test router profile has appropriate parameters."""
        assert router_profile.concurrency >= 32
        assert router_profile.max_tokens <= 128
        assert router_profile.target_p95_latency_ms <= 100
    
    def test_generation_profile_parameters(self, generation_profile):
        """Test generation profile has appropriate parameters."""
        assert generation_profile.max_tokens >= 200
        assert generation_profile.target_tokens_per_sec >= 50


# ============================================================================
# VLLM CONFIG TESTS
# ============================================================================

class TestVLLMConfig:
    """Test VLLMConfig dataclass."""
    
    def test_create_config(self, sample_config):
        """Test config creation."""
        assert sample_config.model == "test/model"
        assert sample_config.gpu_memory_utilization == 0.85
    
    def test_config_defaults(self):
        """Test default values."""
        config = VLLMConfig()
        
        assert config.quantization == "awq"
        assert config.gpu_memory_utilization == 0.85
        assert config.max_model_len == 4096
    
    def test_config_to_dict(self, sample_config):
        """Test dictionary conversion."""
        data = sample_config.to_dict()
        
        assert data["model"] == "test/model"
        assert data["max_num_seqs"] == 256
    
    def test_config_to_cli_args(self, sample_config):
        """Test CLI argument generation."""
        args = sample_config.to_cli_args()
        
        assert "--model" in args
        assert "test/model" in args
        assert "--gpu-memory-utilization" in args
        assert "0.85" in args
    
    def test_config_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "model": "test/from-dict",
            "quantization": "gptq",
            "max_model_len": 2048,
        }
        
        config = VLLMConfig.from_dict(data)
        
        assert config.model == "test/from-dict"
        assert config.max_model_len == 2048
    
    def test_config_roundtrip(self, sample_config):
        """Test dict roundtrip."""
        data = sample_config.to_dict()
        restored = VLLMConfig.from_dict(data)
        
        assert restored.model == sample_config.model
        assert restored.max_num_seqs == sample_config.max_num_seqs


# ============================================================================
# GRID PARAMS TESTS
# ============================================================================

class TestTuneGridParams:
    """Test TuneGridParams."""
    
    def test_quick_grid_count(self):
        """Test quick grid has reasonable size."""
        count = QUICK_GRID.config_count()
        assert count > 0
        assert count <= 10  # Should be small for quick testing
    
    def test_full_grid_count(self):
        """Test full grid is larger."""
        quick_count = QUICK_GRID.config_count()
        full_count = FULL_GRID.config_count()
        
        assert full_count > quick_count
    
    def test_iter_configs(self):
        """Test configuration iteration."""
        grid = TuneGridParams(
            gpu_memory_utilization=[0.8, 0.9],
            max_model_len=[2048],
            max_num_seqs=[128, 256],
            enable_prefix_caching=[False],
        )
        
        base = VLLMConfig()
        configs = list(grid.iter_configs(base))
        
        assert len(configs) == 4  # 2 * 1 * 2 * 1
    
    def test_iter_configs_preserves_base(self):
        """Test that iteration preserves base config values."""
        grid = TuneGridParams(
            gpu_memory_utilization=[0.85],
            max_model_len=[4096],
            max_num_seqs=[256],
            enable_prefix_caching=[False],
        )
        
        base = VLLMConfig(model="custom/model", quantization="gptq")
        configs = list(grid.iter_configs(base))
        
        assert configs[0].model == "custom/model"
        assert configs[0].quantization == "gptq"


# ============================================================================
# BENCHMARK RESULT TESTS
# ============================================================================

class TestBenchmarkResult:
    """Test BenchmarkResult dataclass."""
    
    def test_create_result(self, sample_config, router_profile):
        """Test result creation."""
        result = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            avg_latency_ms=50,
            p95_latency_ms=80,
            tokens_per_sec=120,
        )
        
        assert result.avg_latency_ms == 50
        assert result.tokens_per_sec == 120
    
    def test_calculate_objective(self, sample_config, router_profile):
        """Test objective calculation."""
        result = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=80,  # Target is 80
            tokens_per_sec=150,  # Target is 150
            success_rate=1.0,
        )
        
        score = result.calculate_objective()
        
        assert score > 0
        assert score <= 1.0
    
    def test_objective_penalizes_failures(self, sample_config, router_profile):
        """Test that low success rate penalizes score."""
        # Perfect result
        good = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=80,
            tokens_per_sec=150,
            success_rate=1.0,
        )
        good.calculate_objective()
        
        # Same but with failures
        bad = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=80,
            tokens_per_sec=150,
            success_rate=0.5,
        )
        bad.calculate_objective()
        
        assert bad.objective_score < good.objective_score
    
    def test_result_to_dict(self, sample_config, router_profile):
        """Test dictionary conversion."""
        result = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=80,
            tokens_per_sec=100,
        )
        
        data = result.to_dict()
        
        assert "p95_latency_ms" in data
        assert "tokens_per_sec" in data
        assert "config" in data


# ============================================================================
# BENCHMARK ENGINE TESTS
# ============================================================================

class TestVLLMBenchmark:
    """Test VLLMBenchmark engine."""
    
    def test_create_benchmark(self):
        """Test benchmark creation."""
        bench = VLLMBenchmark(vllm_base="http://test:8001")
        
        assert bench.vllm_base == "http://test:8001"
    
    def test_generate_prompts(self):
        """Test prompt generation."""
        bench = VLLMBenchmark()
        prompts = bench._generate_prompts(20)
        
        assert len(prompts) == 20
        assert all(isinstance(p, str) for p in prompts)
    
    def test_run_benchmark_mock(self, sample_config, router_profile):
        """Test benchmark with mocked requests."""
        bench = VLLMBenchmark()
        
        # Mock the send request
        call_count = 0
        
        def mock_send(prompt, max_tokens, temperature):
            nonlocal call_count
            call_count += 1
            return True, 45.0, 20
        
        bench._send_request = mock_send
        
        result = bench.run_benchmark(
            sample_config,
            TuneProfile(
                name="router",
                description="test",
                num_requests=10,
                concurrency=1,
            ),
        )
        
        assert call_count == 10
        assert result.success_count == 10
        assert result.avg_latency_ms > 0


# ============================================================================
# TUNER TESTS
# ============================================================================

class TestVLLMTuner:
    """Test VLLMTuner."""
    
    def test_create_tuner(self):
        """Test tuner creation."""
        bench = VLLMBenchmark()
        tuner = VLLMTuner(bench)
        
        assert tuner.benchmark == bench
    
    def test_generate_recommendations_router(self, sample_config, router_profile):
        """Test router recommendations."""
        bench = VLLMBenchmark()
        tuner = VLLMTuner(bench)
        
        baseline = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=100,
        )
        
        recommendations = tuner.generate_recommendations(router_profile, baseline)
        
        assert len(recommendations) >= 1
        # Router should prefer smaller max_model_len
        assert any(r.max_model_len <= 2048 for r in recommendations)
    
    def test_generate_recommendations_generation(self, sample_config, generation_profile):
        """Test generation recommendations."""
        bench = VLLMBenchmark()
        tuner = VLLMTuner(bench)
        
        baseline = BenchmarkResult(
            config=sample_config,
            profile=generation_profile,
            p95_latency_ms=200,
        )
        
        recommendations = tuner.generate_recommendations(generation_profile, baseline)
        
        assert len(recommendations) >= 1


# ============================================================================
# TUNE RESULT TESTS
# ============================================================================

class TestTuneResult:
    """Test TuneResult dataclass."""
    
    def test_create_result(self, router_profile):
        """Test result creation."""
        result = TuneResult(profile=router_profile)
        
        assert result.profile == router_profile
        assert result.baseline is None
    
    def test_calculate_improvement(self, sample_config, router_profile):
        """Test improvement calculation."""
        result = TuneResult(profile=router_profile)
        
        result.baseline = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=100,
            tokens_per_sec=100,
        )
        
        result.best = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=80,  # 20% better
            tokens_per_sec=120,  # 20% better
        )
        
        result.calculate_improvement()
        
        assert result.latency_improvement_pct == pytest.approx(20.0)
        assert result.throughput_improvement_pct == pytest.approx(20.0)
    
    def test_result_to_dict(self, router_profile, sample_config):
        """Test dictionary conversion."""
        result = TuneResult(profile=router_profile)
        result.baseline = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
        )
        
        data = result.to_dict()
        
        assert data["profile"] == "router"
        assert "baseline" in data


# ============================================================================
# REPORT GENERATION TESTS
# ============================================================================

class TestReportGeneration:
    """Test report generation."""
    
    def test_generate_empty_report(self, temp_report_path):
        """Test report with no results."""
        report = generate_tune_report({}, temp_report_path)
        
        assert "# vLLM Auto-tune Report" in report
    
    def test_generate_report_with_results(
        self, temp_report_path, router_profile, sample_config
    ):
        """Test report with results."""
        result = TuneResult(profile=router_profile)
        result.baseline = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
            p95_latency_ms=100,
            tokens_per_sec=100,
            success_rate=0.98,
        )
        result.best = result.baseline
        
        report = generate_tune_report({"router": result}, temp_report_path)
        
        assert "Router" in report
        assert "Baseline" in report
        assert Path(temp_report_path).exists()
    
    def test_report_contains_recommendations(
        self, temp_report_path, router_profile, sample_config
    ):
        """Test that report includes recommendations."""
        result = TuneResult(profile=router_profile)
        result.baseline = BenchmarkResult(
            config=sample_config,
            profile=router_profile,
        )
        result.best = result.baseline
        
        report = generate_tune_report({"router": result}, temp_report_path)
        
        assert "Recommended" in report


# ============================================================================
# MOCK TUNE TESTS
# ============================================================================

class TestMockTune:
    """Test mock tuning functionality."""
    
    def test_run_mock_tune(self):
        """Test mock tune returns results."""
        results = run_mock_tune()
        
        assert "router" in results
        assert "generation" in results
    
    def test_mock_results_have_improvement(self):
        """Test mock results show improvement."""
        results = run_mock_tune()
        
        for profile_name, result in results.items():
            assert result.latency_improvement_pct > 0
            # Router should hit 20% improvement target
            if profile_name == "router":
                assert result.latency_improvement_pct >= 20.0
    
    def test_mock_results_have_baseline_and_best(self):
        """Test mock results have baseline and best."""
        results = run_mock_tune()
        
        for result in results.values():
            assert result.baseline is not None
            assert result.best is not None
            assert result.best.p95_latency_ms < result.baseline.p95_latency_ms


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for full workflow."""
    
    def test_full_workflow(self, temp_report_path):
        """Test complete tune -> report workflow."""
        # Run mock tune
        results = run_mock_tune()
        
        # Generate report
        report = generate_tune_report(results, temp_report_path)
        
        # Verify
        assert Path(temp_report_path).exists()
        assert "Router" in report
        assert "Generation" in report
        assert "Recommended" in report
    
    def test_acceptance_router_improvement(self):
        """Acceptance test: router p95 latency 20% improvement."""
        results = run_mock_tune()
        
        router_result = results["router"]
        
        # Verify 20% improvement target
        assert router_result.latency_improvement_pct >= 20.0
