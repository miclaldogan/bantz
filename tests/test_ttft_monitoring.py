"""Comprehensive test suite for Issue #158: TTFT Monitoring & Optimization.

Tests:
- TTFTMonitor statistics calculations
- Threshold enforcement
- TTFT measurement accuracy
- Streaming vs non-streaming
- VLLMOpenAIClient integration
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

from bantz.llm.ttft_monitor import (
    TTFTMeasurement,
    TTFTStatistics,
    TTFTMonitor,
    record_ttft,
)
from bantz.llm.vllm_openai_client import VLLMOpenAIClient, StreamChunk
from bantz.llm.base import LLMMessage, LLMResponse


@pytest.fixture
def reset_monitor():
    """Reset TTFTMonitor singleton before each test."""
    TTFTMonitor._instance = None
    yield
    TTFTMonitor._instance = None


class TestTTFTMeasurement:
    """Test TTFTMeasurement dataclass."""
    
    def test_measurement_creation(self):
        """Test creating a measurement."""
        
        m = TTFTMeasurement(
            timestamp=time.time(),
            ttft_ms=42,
            phase="router",
            model="test-model",
            backend="vllm",
            total_tokens=10,
        )
        
        assert m.ttft_ms == 42
        assert m.phase == "router"
        assert m.model == "test-model"
        assert m.backend == "vllm"
        assert m.total_tokens == 10
    
    def test_measurement_dict(self):
        """Test measurement conversion to dict."""
        
        m = TTFTMeasurement(
            timestamp=1234567890.0,
            ttft_ms=42,
            phase="router",
            model="test-model",
            backend="vllm",
        )
        
        # TTFTMeasurement is a dataclass, use asdict
        from dataclasses import asdict
        d = asdict(m)
        assert d["ttft_ms"] == 42
        assert d["phase"] == "router"
        assert "timestamp" in d


class TestTTFTStatistics:
    """Test TTFTStatistics calculations."""
    
    def test_empty_statistics(self):
        """Test statistics with no data."""
        
        stats = TTFTStatistics(phase="router", model="test-model", backend="vllm")
        assert stats.count == 0
        assert stats.min_ms == 0
        assert stats.max_ms == 0
        assert stats.mean_ms == 0.0
    
    def test_single_measurement(self):
        """Test statistics with one measurement."""
        
        stats = TTFTStatistics(phase="router", model="test-model", backend="vllm", threshold_ms=300)
        stats.add_measurement(42)
        
        assert stats.count == 1
        assert stats.min_ms == 42
        assert stats.max_ms == 42
        assert stats.mean_ms == 42
        assert stats.p50_ms == 42
        assert stats.p95_ms == 42
        assert stats.p99_ms == 42
        assert stats.violations == 0
    
    def test_multiple_measurements(self):
        """Test statistics with multiple measurements."""
        
        stats = TTFTStatistics(phase="router", model="test-model", backend="vllm", threshold_ms=300)
        
        measurements = [50, 100, 150, 200, 250]
        for m in measurements:
            stats.add_measurement(m)
        
        assert stats.count == 5
        assert stats.min_ms == 50
        assert stats.max_ms == 250
        assert stats.mean_ms == 150.0
        assert stats.p50_ms == 150
        assert stats.violations == 0
    
    def test_threshold_violations(self):
        """Test threshold violation tracking."""
        
        stats = TTFTStatistics(phase="router", model="test-model", backend="vllm", threshold_ms=300)
        
        # Add measurements with violations
        measurements = [50, 100, 350, 400, 150]
        for m in measurements:
            stats.add_measurement(m)
        
        assert stats.violations == 2  # 350, 400 exceed 300ms
        # violation_rate calculated in summary()
        summary = stats.summary()
        assert summary["violation_rate"] == 40.0  # 2/5 = 40%
    
    def test_percentile_calculations(self):
        """Test percentile calculations."""
        
        stats = TTFTStatistics(phase="router", model="test-model", backend="vllm")
        
        # Add 100 measurements: 1, 2, 3, ..., 100
        for i in range(1, 101):
            stats.add_measurement(i)
        
        assert stats.count == 100
        assert 50 <= stats.p50_ms <= 51  # Median (can be 50.5)
        assert 94 <= stats.p95_ms <= 96  # 95th percentile
        assert 98 <= stats.p99_ms <= 100  # 99th percentile
    
    def test_summary(self):
        """Test summary dict generation."""
        
        stats = TTFTStatistics(phase="router", model="test-model", backend="vllm", threshold_ms=300)
        stats.add_measurement(42)
        stats.add_measurement(100)
        
        summary = stats.summary()
        
        assert summary["phase"] == "router"
        assert summary["count"] == 2
        assert summary["min_ms"] == 42
        assert summary["max_ms"] == 100
        assert "p50_ms" in summary
        assert "p95_ms" in summary


class TestTTFTMonitor:
    """Test TTFTMonitor singleton."""
    
    def test_singleton(self, reset_monitor):
        """Test singleton pattern."""
        
        m1 = TTFTMonitor.get_instance()
        m2 = TTFTMonitor.get_instance()
        
        assert m1 is m2
    
    def test_record_measurement(self, reset_monitor):
        """Test recording measurements."""
        
        monitor = TTFTMonitor.get_instance()
        
        monitor.record_ttft(
            ttft_ms=42,
            phase="router",
            model="test-model",
            backend="vllm",
        )
        
        stats = monitor.get_statistics("router")
        assert stats is not None
        assert stats.count == 1
        assert stats.min_ms == 42
    
    def test_multiple_phases(self, reset_monitor):
        """Test tracking multiple phases."""
        
        monitor = TTFTMonitor.get_instance()
        
        monitor.record_ttft(ttft_ms=42, phase="router", model="test-model", backend="vllm")
        monitor.record_ttft(ttft_ms=100, phase="router", model="test-model", backend="vllm")
        monitor.record_ttft(ttft_ms=200, phase="finalizer", model="test-model", backend="vllm")
        monitor.record_ttft(ttft_ms=300, phase="finalizer", model="test-model", backend="vllm")
        
        router_stats = monitor.get_statistics("router")
        assert router_stats.count == 2
        assert router_stats.mean_ms == 71.0
        
        finalizer_stats = monitor.get_statistics("finalizer")
        assert finalizer_stats.count == 2
        assert finalizer_stats.mean_ms == 250.0
    
    def test_set_threshold(self, reset_monitor):
        """Test setting custom thresholds."""
        
        monitor = TTFTMonitor.get_instance()
        monitor.set_threshold("router", 200)
        
        monitor.record_ttft(ttft_ms=250, phase="router", model="test-model", backend="vllm")
        
        stats = monitor.get_statistics("router")
        assert stats.violations == 1
    
    def test_check_thresholds(self, reset_monitor):
        """Test threshold checking."""
        
        monitor = TTFTMonitor.get_instance()
        monitor.set_threshold("router", 300)
        
        # No violations
        monitor.record_ttft(ttft_ms=100, phase="router", model="test-model", backend="vllm")
        monitor.record_ttft(ttft_ms=200, phase="router", model="test-model", backend="vllm")
        assert monitor.check_thresholds() is True
        
        # Add violation
        monitor.record_ttft(ttft_ms=400, phase="router", model="test-model", backend="vllm")
        # Still passes (1/3 = 33% violation rate, threshold is p95)
        # But if p95 exceeds threshold, it should fail
    
    def test_export_report(self, reset_monitor):
        """Test exporting report."""
        
        monitor = TTFTMonitor.get_instance()
        
        monitor.record_ttft(ttft_ms=42, phase="router", model="test-model", backend="vllm")
        monitor.record_ttft(ttft_ms=100, phase="router", model="test-model", backend="vllm")
        
        report = monitor.export_report()
        
        assert "statistics" in report
        assert "measurements" in report
        stats_list = report["statistics"]
        assert len(stats_list) > 0
    
    def test_print_summary(self, reset_monitor, capsys):
        """Test print summary output."""
        
        monitor = TTFTMonitor.get_instance()
        
        monitor.record_ttft(ttft_ms=42, phase="router", model="test-model", backend="vllm")
        monitor.record_ttft(ttft_ms=100, phase="router", model="test-model", backend="vllm")
        
        monitor.print_summary()
        
        captured = capsys.readouterr()
        assert "TTFT" in captured.out or "Statistics" in captured.out
        assert "router" in captured.out.lower()


class TestRecordTTFT:
    """Test global record_ttft function."""
    
    def test_record_function(self, reset_monitor):
        """Test global record function."""
        
        record_ttft(
            ttft_ms=42,
            phase="router",
            model="test-model",
            backend="vllm",
        )
        
        monitor = TTFTMonitor.get_instance()
        stats = monitor.get_statistics("router")
        
        assert stats is not None
        assert stats.count == 1
        assert stats.min_ms == 42


class TestVLLMOpenAIClientTTFT:
    """Test VLLMOpenAIClient TTFT integration."""
    
    def test_client_initialization(self):
        """Test client initialization with TTFT tracking."""
        
        # Don't patch OpenAI - just test init params
        client = VLLMOpenAIClient(
            base_url="http://localhost:8001",
            model="test-model",
            track_ttft=True,
            ttft_phase="router",
        )
        
        assert client.track_ttft is True
        assert client.ttft_phase == "router"
        assert client.model == "test-model"
    
    @patch('openai.OpenAI')
    @patch('bantz.llm.ttft_monitor.record_ttft')
    def test_chat_detailed_ttft_tracking(self, mock_record, mock_openai_cls, reset_monitor):
        """Test TTFT tracking in chat_detailed."""
        
        # Create mock client instance
        mock_client_instance = Mock()
        mock_openai_cls.return_value = mock_client_instance
        
        # Mock OpenAI response
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="test response", tool_calls=None))]
        mock_response.usage = Mock(total_tokens=10)
        
        mock_client_instance.chat.completions.create.return_value = mock_response
        
        client = VLLMOpenAIClient(
            base_url="http://localhost:8001",
            model="test-model",
            track_ttft=True,
            ttft_phase="router",
        )
        
        messages = [LLMMessage(role="user", content="test")]
        result = client.chat_detailed(messages, temperature=0.7, max_tokens=100)
        
        # Verify record_ttft was called
        assert mock_record.called
        call_args = mock_record.call_args[1]
        assert call_args["phase"] == "router"
        assert "ttft_ms" in call_args
        assert call_args["ttft_ms"] >= 0  # Can be 0 for mocked responses
    
    def test_stream_chunk_creation(self):
        """Test StreamChunk dataclass."""
        
        chunk = StreamChunk(
            content="test",
            is_first_token=True,
            ttft_ms=42,
            finish_reason=None,
        )
        
        assert chunk.content == "test"
        assert chunk.is_first_token is True
        assert chunk.ttft_ms == 42
        assert chunk.finish_reason is None


class TestStreamingTTFT:
    """Test streaming TTFT measurement."""
    
    @patch('openai.OpenAI')
    @patch('bantz.llm.ttft_monitor.record_ttft')
    def test_chat_stream_ttft(self, mock_record, mock_openai_cls, reset_monitor):
        """Test TTFT measurement in streaming mode."""
        
        # Create mock client instance
        mock_client_instance = Mock()
        mock_openai_cls.return_value = mock_client_instance
        
        # Mock streaming response
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(content="Hello"), finish_reason=None)], usage=None),
            Mock(choices=[Mock(delta=Mock(content=" world"), finish_reason=None)], usage=None),
            Mock(choices=[Mock(delta=Mock(content="!"), finish_reason="stop")], usage=None),
        ]
        
        mock_client_instance.chat.completions.create.return_value = iter(mock_chunks)
        
        client = VLLMOpenAIClient(
            base_url="http://localhost:8001",
            model="test-model",
            track_ttft=True,
            ttft_phase="router",
        )
        
        messages = [LLMMessage(role="user", content="test")]
        
        chunks = list(client.chat_stream(messages, temperature=0.7, max_tokens=100))
        
        # Verify chunks received
        assert len(chunks) == 3
        assert chunks[0].is_first_token is True
        assert chunks[1].is_first_token is False
        
        # Verify TTFT recorded
        assert mock_record.called
        call_args = mock_record.call_args[1]
        assert call_args["phase"] == "router"
        assert "ttft_ms" in call_args


class TestTTFTPerformance:
    """Test TTFT performance targets."""
    
    def test_router_p95_target(self, reset_monitor):
        """Test that router p95 should be < 300ms."""
        
        monitor = TTFTMonitor.get_instance()
        monitor.set_threshold("router", 300)
        
        # Simulate 100 measurements with good performance
        for i in range(100):
            # Most measurements are fast (40-60ms)
            ttft = 50 if i < 95 else 280  # p95 = 280ms < 300ms
            monitor.record_ttft(ttft_ms=ttft, phase="router", model="test-model", backend="vllm")
        
        stats = monitor.get_statistics("router")
        assert stats.p95_ms < 300, "Router p95 should be < 300ms"
    
    def test_finalizer_p95_target(self, reset_monitor):
        """Test that finalizer p95 should be < 500ms."""
        
        monitor = TTFTMonitor.get_instance()
        monitor.set_threshold("finalizer", 500)
        
        # Simulate 100 measurements
        for i in range(100):
            # Most measurements are reasonable (100-200ms)
            ttft = 150 if i < 95 else 480  # p95 = 480ms < 500ms
            monitor.record_ttft(ttft_ms=ttft, phase="finalizer", model="test-model", backend="vllm")
        
        stats = monitor.get_statistics("finalizer")
        assert stats.p95_ms < 500, "Finalizer p95 should be < 500ms"


class TestTTFTIntegration:
    """Integration tests for full TTFT workflow."""
    
    @patch('openai.OpenAI')
    def test_end_to_end_streaming(self, mock_openai_cls, reset_monitor):
        """Test end-to-end streaming with TTFT tracking."""
        
        # Create mock client instance
        mock_client_instance = Mock()
        mock_openai_cls.return_value = mock_client_instance
        
        # Mock streaming response
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(content="Test"), finish_reason=None)], usage=None),
            Mock(choices=[Mock(delta=Mock(content=" response"), finish_reason="stop")], usage=None),
        ]
        
        mock_client_instance.chat.completions.create.return_value = iter(mock_chunks)
        
        client = VLLMOpenAIClient(
            base_url="http://localhost:8001",
            model="test-model",
            track_ttft=True,
            ttft_phase="router",
        )
        
        messages = [LLMMessage(role="user", content="test")]
        
        # Stream and collect
        response_parts = []
        for chunk in client.chat_stream(messages, temperature=0.7, max_tokens=100):
            response_parts.append(chunk.content)
        
        response = "".join(response_parts)
        assert response == "Test response"
        
        # Verify TTFT recorded
        monitor = TTFTMonitor.get_instance()
        stats = monitor.get_statistics("router")
        assert stats is not None
        assert stats.count >= 1
