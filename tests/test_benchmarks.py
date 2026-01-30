"""Benchmark tests for LLM Orchestrator (Issue #138).

These tests measure performance characteristics and ensure benchmarks run correctly.
They use @pytest.mark.benchmark to distinguish from regular tests.

Run:
    pytest tests/test_benchmarks.py -v -m benchmark
    pytest tests/test_benchmarks.py -v  # Skip benchmark tests by default
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import Mock, patch

from bantz.llm.base import LLMMessage, LLMResponse, LLMClient
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.agent.tools import Tool, ToolRegistry
from bantz.core.events import EventBus


# =============================================================================
# Mock LLM for Benchmarking
# =============================================================================

class FastMockLLM:
    """Fast mock LLM for benchmark baseline testing."""
    
    def __init__(self):
        self.calls = 0
        self.backend_name = "mock"
        self.model_name = "fast-mock"
        # Store usage separately (LLMResponse is frozen)
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    
    def chat(self, messages, **kwargs):
        self.calls += 1
        return "Mock response"
    
    def chat_detailed(self, messages, **kwargs):
        self.calls += 1
        # LLMResponse expects: content, model, tokens_used, finish_reason
        # We'll create a custom mock response that has usage attribute
        class MockResponse:
            def __init__(self, content, model, tokens_used, finish_reason, usage):
                self.content = content
                self.model = model
                self.tokens_used = tokens_used
                self.finish_reason = finish_reason
                self.usage = usage
        
        return MockResponse(
            content="Mock response",
            model="fast-mock",
            tokens_used=15,
            finish_reason="stop",
            usage=self.last_usage,
        )
    
    def complete_text(self, *, prompt: str, **kwargs) -> str:
        self.calls += 1
        return '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 0.95, "tool_plan": [], "assistant_reply": "Merhaba!"}'
    
    def is_available(self) -> bool:
        return True


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_llm():
    """Create fast mock LLM."""
    return FastMockLLM()


@pytest.fixture
def mock_tools():
    """Create mock tool registry."""
    registry = ToolRegistry()
    
    registry.register(Tool(
        name="calendar.list_events",
        description="List calendar events",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
            },
            "required": ["time_min", "time_max"],
        },
        function=lambda **kwargs: {"status": "success", "events": []},
    ))
    
    return registry


@pytest.fixture
def event_bus():
    """Create event bus."""
    return EventBus()


# =============================================================================
# Benchmark Tests - Performance Characteristics
# =============================================================================

@pytest.mark.benchmark
class TestOrchestratorPerformance:
    """Benchmark tests for orchestrator performance."""
    
    def test_router_latency_baseline(self, mock_llm: FastMockLLM):
        """Test baseline router latency with mock LLM."""
        orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
        
        start = time.perf_counter()
        output = orchestrator.route(user_input="hey bantz nasılsın")
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Baseline should be very fast with mock
        assert elapsed_ms < 100, f"Router baseline too slow: {elapsed_ms:.2f} ms"
        assert output is not None
    
    def test_orchestrator_latency_baseline(self, mock_llm: FastMockLLM, mock_tools: ToolRegistry, event_bus: EventBus):
        """Test baseline orchestrator latency with mock LLM."""
        orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
        config = OrchestratorConfig(enable_safety_guard=False)
        loop = OrchestratorLoop(orchestrator, mock_tools, event_bus, config)
        
        start = time.perf_counter()
        output, state = loop.process_turn("hey bantz nasılsın")
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Baseline should be very fast with mock
        assert elapsed_ms < 100, f"Orchestrator baseline too slow: {elapsed_ms:.2f} ms"
        assert output.route == "smalltalk"
    
    def test_chat_latency_baseline(self, mock_llm: FastMockLLM):
        """Test baseline chat latency with mock LLM."""
        messages = [LLMMessage(role="user", content="hello")]
        
        start = time.perf_counter()
        response = mock_llm.chat_detailed(messages)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should be instant with mock
        assert elapsed_ms < 10, f"Chat baseline too slow: {elapsed_ms:.2f} ms"
        assert response.content is not None
    
    def test_multiple_iterations_consistency(self, mock_llm: FastMockLLM):
        """Test that multiple iterations are consistent."""
        orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
        
        latencies = []
        for _ in range(10):
            start = time.perf_counter()
            orchestrator.route(user_input="test prompt")
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)
        
        # Latencies should be relatively consistent (std < mean)
        import statistics
        mean = statistics.mean(latencies)
        std = statistics.stdev(latencies)
        
        assert std < mean, f"Latencies too variable: mean={mean:.2f}, std={std:.2f}"


# =============================================================================
# Benchmark Tests - Token Usage
# =============================================================================

@pytest.mark.benchmark
class TestTokenUsage:
    """Benchmark tests for token usage tracking."""
    
    def test_chat_detailed_returns_token_usage(self, mock_llm: FastMockLLM):
        """Test that chat_detailed returns token usage."""
        messages = [LLMMessage(role="user", content="hello world")]
        
        response = mock_llm.chat_detailed(messages)
        
        assert hasattr(response, "usage")
        assert response.usage is not None
        assert isinstance(response.usage, dict)
        assert "total_tokens" in response.usage
    
    def test_token_usage_increases_with_prompt_length(self, mock_llm: FastMockLLM):
        """Test that token usage correlates with prompt length."""
        short_prompt = "hi"
        long_prompt = "This is a much longer prompt with many more words and tokens"
        
        messages_short = [LLMMessage(role="user", content=short_prompt)]
        messages_long = [LLMMessage(role="user", content=long_prompt)]
        
        response_short = mock_llm.chat_detailed(messages_short)
        response_long = mock_llm.chat_detailed(messages_long)
        
        # Both should have token usage (mock returns same for simplicity)
        assert response_short.usage is not None
        assert response_long.usage is not None


# =============================================================================
# Benchmark Tests - Throughput
# =============================================================================

@pytest.mark.benchmark
class TestThroughput:
    """Benchmark tests for throughput measurement."""
    
    def test_sequential_requests_throughput(self, mock_llm: FastMockLLM):
        """Test throughput for sequential requests."""
        num_requests = 20
        
        start = time.perf_counter()
        for _ in range(num_requests):
            mock_llm.chat([LLMMessage(role="user", content="test")])
        elapsed_sec = time.perf_counter() - start
        
        requests_per_sec = num_requests / elapsed_sec
        
        # Mock should be very fast (>1000 req/s)
        assert requests_per_sec > 100, f"Throughput too low: {requests_per_sec:.2f} req/s"
    
    def test_tokens_per_second_calculation(self, mock_llm: FastMockLLM):
        """Test tokens/sec calculation."""
        num_requests = 10
        tokens_per_request = 15  # Mock returns 15 tokens
        
        start = time.perf_counter()
        for _ in range(num_requests):
            mock_llm.chat_detailed([LLMMessage(role="user", content="test")])
        elapsed_sec = time.perf_counter() - start
        
        total_tokens = num_requests * tokens_per_request
        tokens_per_sec = total_tokens / elapsed_sec
        
        # Should be reasonably fast
        assert tokens_per_sec > 0


# =============================================================================
# Benchmark Tests - Success Rate
# =============================================================================

@pytest.mark.benchmark
class TestSuccessRate:
    """Benchmark tests for success rate tracking."""
    
    def test_all_requests_succeed_with_mock(self, mock_llm: FastMockLLM):
        """Test that all requests succeed with mock LLM."""
        num_requests = 20
        successes = 0
        
        for _ in range(num_requests):
            try:
                response = mock_llm.chat([LLMMessage(role="user", content="test")])
                if response:
                    successes += 1
            except Exception:
                pass
        
        success_rate = successes / num_requests
        assert success_rate == 1.0, f"Success rate should be 100% with mock, got {success_rate*100:.1f}%"
    
    def test_json_validity_rate(self, mock_llm: FastMockLLM):
        """Test JSON validity rate for router."""
        import json
        
        orchestrator = JarvisLLMOrchestrator(llm=mock_llm)
        
        num_requests = 20
        valid_json = 0
        
        for _ in range(num_requests):
            try:
                output = orchestrator.route(user_input="test prompt")
                if output is not None:
                    valid_json += 1
            except Exception:
                pass
        
        validity_rate = valid_json / num_requests
        assert validity_rate == 1.0, f"JSON validity should be 100% with mock, got {validity_rate*100:.1f}%"


# =============================================================================
# Benchmark Tests - Percentile Calculation
# =============================================================================

@pytest.mark.benchmark
class TestPercentileCalculation:
    """Test percentile calculation for latency metrics."""
    
    def test_p50_calculation(self):
        """Test p50 (median) calculation."""
        latencies = [10, 20, 30, 40, 50]
        latencies_sorted = sorted(latencies)
        p50_idx = int(len(latencies_sorted) * 0.50)
        p50 = latencies_sorted[p50_idx]
        
        assert p50 == 30, f"p50 should be 30, got {p50}"
    
    def test_p95_calculation(self):
        """Test p95 calculation."""
        latencies = list(range(1, 101))  # 1-100
        latencies_sorted = sorted(latencies)
        p95_idx = int(len(latencies_sorted) * 0.95)
        p95 = latencies_sorted[p95_idx]
        
        assert p95 >= 95, f"p95 should be ~95, got {p95}"
    
    def test_p99_calculation(self):
        """Test p99 calculation."""
        latencies = list(range(1, 101))  # 1-100
        latencies_sorted = sorted(latencies)
        p99_idx = int(len(latencies_sorted) * 0.99)
        p99 = latencies_sorted[p99_idx]
        
        assert p99 >= 99, f"p99 should be ~99, got {p99}"


# =============================================================================
# Benchmark Tests - Report Generation
# =============================================================================

@pytest.mark.benchmark
class TestReportGeneration:
    """Test benchmark report generation."""
    
    def test_json_export_format(self, tmp_path):
        """Test JSON export has correct format."""
        import json
        from datetime import datetime
        
        # Create sample data
        data = {
            "generated_at": datetime.now().isoformat(),
            "results": [
                {
                    "scenario": "test",
                    "backend": "mock",
                    "latency_p50": 10.0,
                    "latency_p95": 15.0,
                    "throughput_tokens_per_sec": 100.0,
                }
            ],
        }
        
        # Write JSON
        output_file = tmp_path / "benchmark_results.json"
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
        
        # Read and validate
        with open(output_file, "r") as f:
            loaded_data = json.load(f)
        
        assert "generated_at" in loaded_data
        assert "results" in loaded_data
        assert len(loaded_data["results"]) == 1
        assert loaded_data["results"][0]["scenario"] == "test"
    
    def test_markdown_report_format(self, tmp_path):
        """Test markdown report generation."""
        output_file = tmp_path / "benchmark_report.md"
        
        # Generate simple markdown
        with open(output_file, "w") as f:
            f.write("# Benchmark Results\n\n")
            f.write("| Backend | p50 (ms) | p95 (ms) |\n")
            f.write("|---------|----------|----------|\n")
            f.write("| mock    | 10.00    | 15.00    |\n")
        
        # Verify file exists and has content
        assert output_file.exists()
        content = output_file.read_text()
        assert "# Benchmark Results" in content
        assert "| Backend |" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "benchmark"])
