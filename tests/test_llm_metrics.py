"""Tests for unified LLM metrics logging.

Issue #234: Observability - Unified LLM metrics (vLLM+Gemini) -> JSONL + summary report

Test categories:
1. MetricEntry schema and serialization
2. Record functions (success, failure, generic)
3. JSONL file writing and reading
4. Report analysis and generation
5. Environment variable handling
6. Thread safety
7. Edge cases and error handling
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from bantz.llm.metrics import (
    DEFAULT_METRICS_FILE,
    MetricEntry,
    MetricsConfig,
    MetricsReport,
    _percentile,
    analyze_metrics,
    format_report_markdown,
    generate_report,
    get_metrics_file_path,
    load_metrics,
    metrics_enabled,
    record_llm_failure,
    record_llm_metric,
    record_llm_success,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_metrics_file() -> Generator[str, None, None]:
    """Create a temporary file for metrics testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    try:
        os.unlink(temp_path)
    except OSError:
        pass


@pytest.fixture
def sample_entries() -> list[MetricEntry]:
    """Create sample metric entries for testing."""
    return [
        MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="vllm",
            model="Qwen/Qwen2.5-3B-Instruct",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            success=True,
            error_type=None,
            tier="fast",
            reason="router_call",
        ),
        MetricEntry(
            ts="2024-01-15T10:01:00+00:00",
            backend="vllm",
            model="Qwen/Qwen2.5-3B-Instruct",
            prompt_tokens=150,
            completion_tokens=100,
            total_tokens=250,
            latency_ms=350,
            success=True,
            error_type=None,
            tier="fast",
            reason="smalltalk",
        ),
        MetricEntry(
            ts="2024-01-15T10:02:00+00:00",
            backend="gemini",
            model="gemini-2.0-flash",
            prompt_tokens=200,
            completion_tokens=150,
            total_tokens=350,
            latency_ms=800,
            success=True,
            error_type=None,
            tier="quality",
            reason="complex_query",
        ),
        MetricEntry(
            ts="2024-01-15T10:03:00+00:00",
            backend="vllm",
            model="Qwen/Qwen2.5-3B-Instruct",
            prompt_tokens=100,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=5000,
            success=False,
            error_type="timeout",
            tier="fast",
            reason="router_call",
        ),
        MetricEntry(
            ts="2024-01-15T10:04:00+00:00",
            backend="gemini",
            model="gemini-2.0-flash",
            prompt_tokens=180,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=2000,
            success=False,
            error_type="rate_limited",
            tier="quality",
            reason="email_draft",
        ),
    ]


# ============================================================================
# METRIC ENTRY TESTS
# ============================================================================


class TestMetricEntry:
    """Test MetricEntry schema and serialization."""
    
    def test_create_entry(self):
        """Test basic entry creation."""
        entry = MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="vllm",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            success=True,
            error_type=None,
            tier="fast",
            reason="test",
        )
        
        assert entry.backend == "vllm"
        assert entry.model == "test-model"
        assert entry.prompt_tokens == 100
        assert entry.completion_tokens == 50
        assert entry.total_tokens == 150
        assert entry.latency_ms == 200
        assert entry.success is True
        assert entry.error_type is None
        assert entry.tier == "fast"
        assert entry.reason == "test"
    
    def test_entry_is_frozen(self):
        """Test that entries are immutable."""
        entry = MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="vllm",
            model="test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            success=True,
            error_type=None,
            tier="fast",
            reason="test",
        )
        
        with pytest.raises(AttributeError):
            entry.backend = "gemini"  # type: ignore
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        entry = MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="vllm",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            success=True,
            error_type=None,
            tier="fast",
            reason="test_reason",
        )
        
        data = entry.to_dict()
        
        assert isinstance(data, dict)
        assert data["ts"] == "2024-01-15T10:00:00+00:00"
        assert data["backend"] == "vllm"
        assert data["model"] == "test-model"
        assert data["prompt_tokens"] == 100
        assert data["completion_tokens"] == 50
        assert data["total_tokens"] == 150
        assert data["latency_ms"] == 200
        assert data["success"] is True
        assert data["error_type"] is None
        assert data["tier"] == "fast"
        assert data["reason"] == "test_reason"
    
    def test_to_json(self):
        """Test JSON serialization."""
        entry = MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="gemini",
            model="gemini-2.0-flash",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            latency_ms=500,
            success=True,
            error_type=None,
            tier="quality",
            reason="complex",
        )
        
        json_str = entry.to_json()
        data = json.loads(json_str)
        
        assert data["backend"] == "gemini"
        assert data["model"] == "gemini-2.0-flash"
        assert data["total_tokens"] == 300
    
    def test_json_roundtrip(self):
        """Test JSON serialization and deserialization."""
        original = MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="vllm",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            success=False,
            error_type="timeout",
            tier="fast",
            reason="test",
        )
        
        json_str = original.to_json()
        data = json.loads(json_str)
        
        restored = MetricEntry(
            ts=data["ts"],
            backend=data["backend"],
            model=data["model"],
            prompt_tokens=data["prompt_tokens"],
            completion_tokens=data["completion_tokens"],
            total_tokens=data["total_tokens"],
            latency_ms=data["latency_ms"],
            success=data["success"],
            error_type=data["error_type"],
            tier=data["tier"],
            reason=data["reason"],
        )
        
        assert restored == original
    
    def test_unicode_handling(self):
        """Test Turkish and unicode characters in model/reason."""
        entry = MetricEntry(
            ts="2024-01-15T10:00:00+00:00",
            backend="vllm",
            model="Türkçe-Model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
            success=True,
            error_type=None,
            tier="fast",
            reason="takvim_sorgusu",
        )
        
        json_str = entry.to_json()
        assert "Türkçe-Model" in json_str
        assert "takvim_sorgusu" in json_str
        
        # Verify it parses back correctly
        data = json.loads(json_str)
        assert data["model"] == "Türkçe-Model"
        assert data["reason"] == "takvim_sorgusu"


# ============================================================================
# ENVIRONMENT VARIABLE TESTS
# ============================================================================


class TestEnvironmentVariables:
    """Test environment variable handling."""
    
    def test_metrics_enabled_default_false(self):
        """Test that metrics are disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if it exists
            os.environ.pop("BANTZ_LLM_METRICS", None)
            assert metrics_enabled() is False
    
    def test_metrics_enabled_true_values(self):
        """Test various truthy values for BANTZ_LLM_METRICS."""
        truthy_values = ["1", "true", "TRUE", "yes", "YES", "y", "Y", "on", "ON", "enable", "enabled"]
        
        for value in truthy_values:
            with patch.dict(os.environ, {"BANTZ_LLM_METRICS": value}):
                assert metrics_enabled() is True, f"Failed for value: {value}"
    
    def test_metrics_enabled_false_values(self):
        """Test various falsy values for BANTZ_LLM_METRICS."""
        falsy_values = ["0", "false", "FALSE", "no", "NO", "n", "off", "OFF", "disable", "disabled", ""]
        
        for value in falsy_values:
            with patch.dict(os.environ, {"BANTZ_LLM_METRICS": value}):
                assert metrics_enabled() is False, f"Failed for value: {value}"
    
    def test_get_metrics_file_path_default(self):
        """Test default metrics file path."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("BANTZ_LLM_METRICS_FILE", None)
            assert get_metrics_file_path() == DEFAULT_METRICS_FILE
    
    def test_get_metrics_file_path_custom(self):
        """Test custom metrics file path."""
        custom_path = "/custom/path/metrics.jsonl"
        with patch.dict(os.environ, {"BANTZ_LLM_METRICS_FILE": custom_path}):
            assert get_metrics_file_path() == custom_path
    
    def test_metrics_config_from_env(self):
        """Test MetricsConfig.from_env()."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": "/custom/path/metrics.jsonl",
        }):
            config = MetricsConfig.from_env()
            assert config.enabled is True
            assert config.file_path == "/custom/path/metrics.jsonl"


# ============================================================================
# RECORD FUNCTIONS TESTS
# ============================================================================


class TestRecordFunctions:
    """Test metric recording functions."""
    
    def test_record_llm_metric_disabled(self):
        """Test that record returns None when metrics disabled."""
        with patch.dict(os.environ, {"BANTZ_LLM_METRICS": "0"}):
            result = record_llm_metric(
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="fast",
                reason="test",
            )
            assert result is None
    
    def test_record_llm_metric_enabled(self, temp_metrics_file):
        """Test metric recording when enabled."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend="vllm",
                model="test-model",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="fast",
                reason="test_reason",
            )
            
            assert result is not None
            assert result.backend == "vllm"
            assert result.model == "test-model"
            assert result.prompt_tokens == 100
            assert result.completion_tokens == 50
            assert result.total_tokens == 150  # Calculated
            assert result.latency_ms == 200
            assert result.success is True
            assert result.tier == "fast"
            assert result.reason == "test_reason"
            
            # Verify file was written
            with open(temp_metrics_file) as f:
                lines = f.readlines()
            assert len(lines) == 1
            
            data = json.loads(lines[0])
            assert data["backend"] == "vllm"
    
    def test_record_llm_success(self, temp_metrics_file):
        """Test convenience success recording function."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_success(
                backend="gemini",
                model="gemini-2.0-flash",
                prompt_tokens=200,
                completion_tokens=100,
                latency_ms=500,
                tier="quality",
                reason="complex_query",
            )
            
            assert result is not None
            assert result.success is True
            assert result.error_type is None
            assert result.backend == "gemini"
    
    def test_record_llm_failure(self, temp_metrics_file):
        """Test convenience failure recording function."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_failure(
                backend="vllm",
                model="test-model",
                prompt_tokens=100,
                latency_ms=5000,
                error_type="timeout",
                tier="fast",
                reason="router_call",
            )
            
            assert result is not None
            assert result.success is False
            assert result.error_type == "timeout"
            assert result.completion_tokens == 0
            assert result.total_tokens == 0
    
    def test_record_with_total_tokens_override(self, temp_metrics_file):
        """Test total_tokens override."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="fast",
                reason="test",
                total_tokens=999,  # Override
            )
            
            assert result is not None
            assert result.total_tokens == 999
    
    def test_record_normalizes_backend(self, temp_metrics_file):
        """Test backend name normalization."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend="  VLLM  ",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="fast",
                reason="test",
            )
            
            assert result is not None
            assert result.backend == "vllm"  # Normalized
    
    def test_record_normalizes_tier(self, temp_metrics_file):
        """Test tier normalization."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="  QUALITY  ",
                reason="test",
            )
            
            assert result is not None
            assert result.tier == "quality"  # Normalized
    
    def test_record_handles_negative_values(self, temp_metrics_file):
        """Test that negative values are clamped to 0."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend="vllm",
                model="test",
                prompt_tokens=-100,
                completion_tokens=-50,
                latency_ms=-200,
                success=True,
                tier="fast",
                reason="test",
            )
            
            assert result is not None
            assert result.prompt_tokens == 0
            assert result.completion_tokens == 0
            assert result.latency_ms == 0
            assert result.total_tokens == 0
    
    def test_record_creates_directory(self, tmp_path):
        """Test that parent directory is created if needed."""
        nested_path = tmp_path / "deep" / "nested" / "metrics.jsonl"
        
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": str(nested_path),
        }):
            result = record_llm_metric(
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="fast",
                reason="test",
            )
            
            assert result is not None
            assert nested_path.exists()


# ============================================================================
# FILE I/O TESTS
# ============================================================================


class TestFileIO:
    """Test JSONL file reading and writing."""
    
    def test_load_metrics_empty_file(self, temp_metrics_file):
        """Test loading from empty file."""
        entries = load_metrics(temp_metrics_file)
        assert entries == []
    
    def test_load_metrics_nonexistent_file(self):
        """Test loading from nonexistent file."""
        entries = load_metrics("/nonexistent/path/metrics.jsonl")
        assert entries == []
    
    def test_load_metrics_valid_data(self, temp_metrics_file):
        """Test loading valid JSONL data."""
        # Write test data
        with open(temp_metrics_file, "w") as f:
            f.write(json.dumps({
                "ts": "2024-01-15T10:00:00+00:00",
                "backend": "vllm",
                "model": "test-model",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latency_ms": 200,
                "success": True,
                "error_type": None,
                "tier": "fast",
                "reason": "test",
            }) + "\n")
            f.write(json.dumps({
                "ts": "2024-01-15T10:01:00+00:00",
                "backend": "gemini",
                "model": "gemini-2.0-flash",
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
                "latency_ms": 500,
                "success": True,
                "error_type": None,
                "tier": "quality",
                "reason": "complex",
            }) + "\n")
        
        entries = load_metrics(temp_metrics_file)
        
        assert len(entries) == 2
        assert entries[0].backend == "vllm"
        assert entries[1].backend == "gemini"
    
    def test_load_metrics_skips_blank_lines(self, temp_metrics_file):
        """Test that blank lines are skipped."""
        with open(temp_metrics_file, "w") as f:
            f.write(json.dumps({
                "ts": "2024-01-15T10:00:00+00:00",
                "backend": "vllm",
                "model": "test",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latency_ms": 200,
                "success": True,
                "error_type": None,
                "tier": "fast",
                "reason": "test",
            }) + "\n")
            f.write("\n")
            f.write("   \n")
            f.write(json.dumps({
                "ts": "2024-01-15T10:01:00+00:00",
                "backend": "gemini",
                "model": "test",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latency_ms": 200,
                "success": True,
                "error_type": None,
                "tier": "quality",
                "reason": "test",
            }) + "\n")
        
        entries = load_metrics(temp_metrics_file)
        assert len(entries) == 2
    
    def test_load_metrics_handles_invalid_json(self, temp_metrics_file):
        """Test that invalid JSON lines are skipped."""
        with open(temp_metrics_file, "w") as f:
            f.write(json.dumps({
                "ts": "2024-01-15T10:00:00+00:00",
                "backend": "vllm",
                "model": "test",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latency_ms": 200,
                "success": True,
                "error_type": None,
                "tier": "fast",
                "reason": "test",
            }) + "\n")
            f.write("not valid json\n")
            f.write(json.dumps({
                "ts": "2024-01-15T10:01:00+00:00",
                "backend": "gemini",
                "model": "test",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "latency_ms": 200,
                "success": True,
                "error_type": None,
                "tier": "quality",
                "reason": "test",
            }) + "\n")
        
        entries = load_metrics(temp_metrics_file)
        assert len(entries) == 2  # Invalid line skipped
    
    def test_multiple_records_appended(self, temp_metrics_file):
        """Test that multiple records are appended correctly."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            for i in range(5):
                record_llm_success(
                    backend="vllm",
                    model="test",
                    prompt_tokens=100 + i,
                    completion_tokens=50,
                    latency_ms=200 + i * 10,
                    tier="fast",
                    reason=f"test_{i}",
                )
            
            entries = load_metrics(temp_metrics_file)
            assert len(entries) == 5
            assert entries[0].prompt_tokens == 100
            assert entries[4].prompt_tokens == 104


# ============================================================================
# THREAD SAFETY TESTS
# ============================================================================


class TestThreadSafety:
    """Test thread-safe metric recording."""
    
    def test_concurrent_writes(self, temp_metrics_file):
        """Test that concurrent writes don't corrupt the file."""
        num_threads = 10
        writes_per_thread = 50
        
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            def writer(thread_id: int):
                for i in range(writes_per_thread):
                    record_llm_success(
                        backend="vllm" if thread_id % 2 == 0 else "gemini",
                        model="test",
                        prompt_tokens=100,
                        completion_tokens=50,
                        latency_ms=200,
                        tier="fast",
                        reason=f"thread_{thread_id}_{i}",
                    )
            
            threads = [
                threading.Thread(target=writer, args=(i,))
                for i in range(num_threads)
            ]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            # Verify all entries written correctly
            entries = load_metrics(temp_metrics_file)
            assert len(entries) == num_threads * writes_per_thread
            
            # Verify each line is valid JSON
            with open(temp_metrics_file) as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line:
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            pytest.fail(f"Invalid JSON on line {line_num}: {line[:100]}")


# ============================================================================
# ANALYSIS TESTS
# ============================================================================


class TestAnalysis:
    """Test metrics analysis and reporting."""
    
    def test_analyze_empty_entries(self):
        """Test analysis of empty entries list."""
        report = analyze_metrics([])
        
        assert report.total_calls == 0
        assert report.successful_calls == 0
        assert report.failed_calls == 0
        assert report.success_rate == 0.0
    
    def test_analyze_basic_counts(self, sample_entries):
        """Test basic count calculations."""
        report = analyze_metrics(sample_entries)
        
        assert report.total_calls == 5
        assert report.successful_calls == 3
        assert report.failed_calls == 2
        assert report.success_rate == pytest.approx(0.6, rel=0.01)
    
    def test_analyze_backend_breakdown(self, sample_entries):
        """Test per-backend statistics."""
        report = analyze_metrics(sample_entries)
        
        assert report.vllm_calls == 3
        assert report.gemini_calls == 2
        
        # vLLM: 150 + 250 + 0 = 400 tokens
        assert report.vllm_tokens == 400
        # Gemini: 350 + 0 = 350 tokens
        assert report.gemini_tokens == 350
    
    def test_analyze_tier_breakdown(self, sample_entries):
        """Test tier statistics."""
        report = analyze_metrics(sample_entries)
        
        assert report.fast_calls == 3
        assert report.quality_calls == 2
        assert report.quality_call_rate == pytest.approx(0.4, rel=0.01)
    
    def test_analyze_latency_stats(self, sample_entries):
        """Test latency calculations (successful calls only)."""
        report = analyze_metrics(sample_entries)
        
        # Successful latencies: [200, 350, 800]
        # Sorted: [200, 350, 800]
        assert report.latency_min == 200
        assert report.latency_max == 800
        assert report.latency_mean == (200 + 350 + 800) // 3
        
        # p50: middle value
        assert report.latency_p50 == 350
        # p95: near max
        assert report.latency_p95 == 800
    
    def test_analyze_per_backend_latency(self, sample_entries):
        """Test per-backend latency calculations."""
        report = analyze_metrics(sample_entries)
        
        # vLLM successful: [200, 350]
        # p50 of 2 elements with our percentile function returns element at index 1
        assert report.vllm_latency_p50 == 350  # Index 1 of sorted [200, 350]
        assert report.vllm_latency_p95 == 350
        
        # Gemini successful: [800]
        assert report.gemini_latency_p50 == 800
        assert report.gemini_latency_p95 == 800
    
    def test_analyze_error_breakdown(self, sample_entries):
        """Test error type breakdown."""
        report = analyze_metrics(sample_entries)
        
        assert "timeout" in report.error_types
        assert report.error_types["timeout"] == 1
        assert "rate_limited" in report.error_types
        assert report.error_types["rate_limited"] == 1
    
    def test_analyze_time_range(self, sample_entries):
        """Test time range extraction."""
        report = analyze_metrics(sample_entries)
        
        assert report.first_ts == "2024-01-15T10:00:00+00:00"
        assert report.last_ts == "2024-01-15T10:04:00+00:00"
    
    def test_percentile_empty_list(self):
        """Test percentile calculation with empty list."""
        assert _percentile([], 50) == 0
        assert _percentile([], 95) == 0
    
    def test_percentile_single_element(self):
        """Test percentile calculation with single element."""
        assert _percentile([100], 50) == 100
        assert _percentile([100], 95) == 100
    
    def test_percentile_multiple_elements(self):
        """Test percentile calculation with multiple elements."""
        values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        
        assert _percentile(values, 0) == 100
        assert _percentile(values, 50) == 600  # Index 5
        assert _percentile(values, 95) == 1000  # Index 9


# ============================================================================
# REPORT FORMATTING TESTS
# ============================================================================


class TestReportFormatting:
    """Test report generation and formatting."""
    
    def test_format_report_markdown_empty(self):
        """Test markdown formatting with empty data."""
        report = MetricsReport()
        markdown = format_report_markdown(report)
        
        assert "# LLM Metrics Report" in markdown
        assert "Total Calls | 0" in markdown
    
    def test_format_report_markdown_with_data(self, sample_entries):
        """Test markdown formatting with real data."""
        report = analyze_metrics(sample_entries)
        markdown = format_report_markdown(report)
        
        assert "# LLM Metrics Report" in markdown
        assert "## Summary" in markdown
        assert "## Latency" in markdown
        assert "## Backend Breakdown" in markdown
        assert "## Tier Distribution" in markdown
        assert "## Error Breakdown" in markdown
        assert "timeout" in markdown
        assert "rate_limited" in markdown
        assert "vLLM" in markdown
        assert "Gemini" in markdown
    
    def test_format_report_markdown_structure(self, sample_entries):
        """Test markdown report structure."""
        report = analyze_metrics(sample_entries)
        markdown = format_report_markdown(report)
        
        # Should have tables
        assert "|" in markdown
        assert "---" in markdown
        
        # Should have section headers
        assert "##" in markdown
        
        # Should have footer
        assert "Generated by" in markdown
    
    def test_generate_report_integration(self, temp_metrics_file):
        """Test full report generation from file."""
        # Write test data
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            record_llm_success(
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                tier="fast",
                reason="test",
            )
            record_llm_failure(
                backend="gemini",
                model="test",
                prompt_tokens=100,
                latency_ms=500,
                error_type="timeout",
                tier="quality",
                reason="test",
            )
        
        markdown = generate_report(temp_metrics_file)
        
        assert "# LLM Metrics Report" in markdown
        assert "Total Calls | 2" in markdown


# ============================================================================
# EDGE CASES AND ERROR HANDLING
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_record_with_none_values(self, temp_metrics_file):
        """Test recording with None values."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend=None,  # type: ignore
                model=None,  # type: ignore
                prompt_tokens=None,  # type: ignore
                completion_tokens=None,  # type: ignore
                latency_ms=None,  # type: ignore
                success=True,
                tier=None,  # type: ignore
                reason=None,  # type: ignore
            )
            
            assert result is not None
            assert result.backend == "unknown"
            assert result.model == "unknown"
            assert result.prompt_tokens == 0
    
    def test_record_with_empty_strings(self, temp_metrics_file):
        """Test recording with empty strings."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_metric(
                backend="",
                model="",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                success=True,
                tier="",
                reason="",
            )
            
            assert result is not None
            assert result.backend == "unknown"
            assert result.model == "unknown"
    
    def test_analyze_all_failures(self):
        """Test analysis when all calls failed."""
        entries = [
            MetricEntry(
                ts="2024-01-15T10:00:00+00:00",
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=5000,
                success=False,
                error_type="timeout",
                tier="fast",
                reason="test",
            ),
            MetricEntry(
                ts="2024-01-15T10:01:00+00:00",
                backend="gemini",
                model="test",
                prompt_tokens=100,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=2000,
                success=False,
                error_type="rate_limited",
                tier="quality",
                reason="test",
            ),
        ]
        
        report = analyze_metrics(entries)
        
        assert report.total_calls == 2
        assert report.successful_calls == 0
        assert report.failed_calls == 2
        assert report.success_rate == 0.0
        
        # Latency stats should be 0 (no successful calls)
        assert report.latency_p50 == 0
        assert report.latency_p95 == 0
    
    def test_analyze_single_entry(self):
        """Test analysis with single entry."""
        entries = [
            MetricEntry(
                ts="2024-01-15T10:00:00+00:00",
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                latency_ms=200,
                success=True,
                error_type=None,
                tier="fast",
                reason="test",
            ),
        ]
        
        report = analyze_metrics(entries)
        
        assert report.total_calls == 1
        assert report.success_rate == 1.0
        assert report.latency_p50 == 200
        assert report.latency_p95 == 200
    
    def test_large_token_counts(self, temp_metrics_file):
        """Test handling of large token counts."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            result = record_llm_success(
                backend="vllm",
                model="test",
                prompt_tokens=1_000_000,
                completion_tokens=500_000,
                latency_ms=60_000,
                tier="fast",
                reason="test",
            )
            
            assert result is not None
            assert result.prompt_tokens == 1_000_000
            assert result.completion_tokens == 500_000
            assert result.total_tokens == 1_500_000
    
    def test_timestamp_generation(self, temp_metrics_file):
        """Test that timestamps are generated in ISO format."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            before = datetime.now(timezone.utc)
            
            result = record_llm_success(
                backend="vllm",
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200,
                tier="fast",
                reason="test",
            )
            
            after = datetime.now(timezone.utc)
            
            assert result is not None
            # Should be parseable as ISO format
            ts = datetime.fromisoformat(result.ts)
            
            # Should be within the time window
            assert before <= ts <= after


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestIntegration:
    """Integration tests for complete workflows."""
    
    def test_full_workflow(self, temp_metrics_file):
        """Test complete metrics workflow: record -> load -> analyze -> report."""
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": temp_metrics_file,
        }):
            # Record various metrics
            for i in range(10):
                if i < 7:
                    record_llm_success(
                        backend="vllm" if i % 2 == 0 else "gemini",
                        model="test-model",
                        prompt_tokens=100 + i * 10,
                        completion_tokens=50 + i * 5,
                        latency_ms=200 + i * 50,
                        tier="fast" if i < 5 else "quality",
                        reason=f"test_{i}",
                    )
                else:
                    record_llm_failure(
                        backend="vllm",
                        model="test-model",
                        prompt_tokens=100,
                        latency_ms=5000,
                        error_type="timeout",
                        tier="fast",
                        reason=f"test_{i}",
                    )
        
        # Load metrics
        entries = load_metrics(temp_metrics_file)
        assert len(entries) == 10
        
        # Analyze
        report = analyze_metrics(entries)
        assert report.total_calls == 10
        assert report.successful_calls == 7
        assert report.failed_calls == 3
        
        # Generate markdown
        markdown = format_report_markdown(report)
        assert "# LLM Metrics Report" in markdown
        assert "Total Calls | 10" in markdown
        assert "timeout" in markdown
    
    def test_demo_run_creates_metrics(self, tmp_path):
        """Test that a simulated demo run creates metrics file (acceptance criteria)."""
        metrics_file = tmp_path / "demo_metrics.jsonl"
        
        with patch.dict(os.environ, {
            "BANTZ_LLM_METRICS": "1",
            "BANTZ_LLM_METRICS_FILE": str(metrics_file),
        }):
            # Simulate a demo run
            # 1. Router call (fast tier)
            record_llm_success(
                backend="vllm",
                model="Qwen/Qwen2.5-3B-Instruct",
                prompt_tokens=150,
                completion_tokens=50,
                latency_ms=245,
                tier="fast",
                reason="router_call",
            )
            
            # 2. Tool execution (no LLM call)
            # ...
            
            # 3. Finalizer call (quality tier)
            record_llm_success(
                backend="gemini",
                model="gemini-2.0-flash",
                prompt_tokens=300,
                completion_tokens=150,
                latency_ms=850,
                tier="quality",
                reason="response_finalize",
            )
        
        # Verify metrics file was created
        assert metrics_file.exists()
        
        # Verify contents
        entries = load_metrics(str(metrics_file))
        assert len(entries) == 2
        
        # Verify report can be generated
        markdown = generate_report(str(metrics_file))
        assert "vLLM" in markdown
        assert "Gemini" in markdown
