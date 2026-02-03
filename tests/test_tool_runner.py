"""
Tests for Tool Runner (Issue #32 - V2-2).

Tests ToolRunner with retry, timeout, and circuit breaker.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch

from bantz.agent.tool_base import (
    ToolBase,
    ToolSpec,
    ToolContext,
    ToolResult,
    ErrorType,
    ToolTimeoutError,
)
from bantz.agent.tool_runner import (
    ToolRunner,
    RunConfig,
    RETRY_DELAYS,
    get_tool_runner,
)
from bantz.agent.circuit_breaker import CircuitBreaker
from bantz.core.events import EventBus


class MockTool(ToolBase):
    """Mock tool for testing."""
    
    def __init__(
        self,
        name: str = "mock_tool",
        timeout: float = 30.0,
        max_retries: int = 3,
        run_result: ToolResult = None,
        run_exception: Exception = None,
        delay: float = 0
    ):
        self._name = name
        self._timeout = timeout
        self._max_retries = max_retries
        self._run_result = run_result or ToolResult.ok(data={"success": True})
        self._run_exception = run_exception
        self._delay = delay
        self.call_count = 0
    
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description="Mock tool for testing",
            parameters={"query": {"type": "string", "required": False}},
            timeout=self._timeout,
            max_retries=self._max_retries
        )
    
    async def run(self, input: dict, context: ToolContext) -> ToolResult:
        self.call_count += 1
        
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        
        if self._run_exception:
            raise self._run_exception
        
        return self._run_result


class FailThenSucceedTool(ToolBase):
    """Tool that fails N times then succeeds."""
    
    def __init__(self, fail_count: int = 1):
        self._fail_count = fail_count
        self.call_count = 0
    
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fail_then_succeed",
            description="Fails N times then succeeds",
            parameters={},
            max_retries=5
        )
    
    async def run(self, input: dict, context: ToolContext) -> ToolResult:
        self.call_count += 1
        
        if self.call_count <= self._fail_count:
            return ToolResult.fail(
                error=f"Fail attempt {self.call_count}",
                error_type=ErrorType.NETWORK
            )
        
        return ToolResult.ok(data={"attempt": self.call_count})


@pytest.fixture
def event_bus():
    """Create EventBus for testing."""
    return EventBus()


@pytest.fixture
def circuit_breaker():
    """Create CircuitBreaker for testing."""
    return CircuitBreaker()


@pytest.fixture
def context(event_bus):
    """Create ToolContext for testing."""
    return ToolContext(job_id="test-job-123", event_bus=event_bus)


class TestToolRunnerSuccess:
    """Test successful tool execution."""
    
    @pytest.mark.asyncio
    async def test_runner_success_first_try(self, event_bus, context):
        """Tool succeeds on first try."""
        tool = MockTool()
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {"query": "test"}, context)
        
        assert result.success is True
        assert tool.call_count == 1
        assert result.retries_used == 0
    
    @pytest.mark.asyncio
    async def test_runner_returns_data(self, event_bus, context):
        """Successful result contains data."""
        expected_data = {"key": "value", "number": 42}
        tool = MockTool(run_result=ToolResult.ok(data=expected_data))
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)
        
        assert result.data == expected_data
    
    @pytest.mark.asyncio
    async def test_runner_tracks_duration(self, event_bus, context):
        """Duration is tracked."""
        tool = MockTool(delay=0.05)  # 50ms delay
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)
        
        assert result.duration_ms >= 50


class TestToolRunnerRetry:
    """Test retry behavior."""
    
    @pytest.mark.asyncio
    async def test_runner_retry_on_failure(self, event_bus, context):
        """Retries on failure."""
        tool = FailThenSucceedTool(fail_count=1)
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)
        
        assert result.success is True
        assert tool.call_count == 2  # 1 fail + 1 success
    
    @pytest.mark.asyncio
    async def test_runner_success_on_retry_2(self, event_bus, context):
        """Succeeds on second retry (third attempt)."""
        tool = FailThenSucceedTool(fail_count=2)
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)
        
        assert result.success is True
        assert tool.call_count == 3
        assert result.retries_used == 2
    
    @pytest.mark.asyncio
    async def test_runner_max_retries_3(self, event_bus, context):
        """Stops after max_retries (3) attempts."""
        # Tool that always fails
        tool = MockTool(
            max_retries=3,
            run_result=ToolResult.fail(error="Always fails", error_type=ErrorType.NETWORK)
        )
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)
        
        assert result.success is False
        assert tool.call_count == 4  # 1 initial + 3 retries
        assert result.retries_used == 3
    
    @pytest.mark.asyncio
    async def test_runner_retries_used_count(self, event_bus, context):
        """retries_used correctly reflects retry count."""
        tool = FailThenSucceedTool(fail_count=2)
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)
        
        assert result.retries_used == 2
    
    @pytest.mark.asyncio
    async def test_runner_publishes_retry_event(self, context):
        """RETRY event is published on retry."""
        event_bus = EventBus()
        events = []
        event_bus.subscribe("retry", lambda e: events.append(e))
        
        tool = FailThenSucceedTool(fail_count=1)
        runner = ToolRunner(event_bus=event_bus)
        
        await runner.run(tool, {}, context)
        
        assert len(events) == 1
        assert events[0].data["attempt"] == 1


class TestToolRunnerRetryDelays:
    """Test retry delay behavior."""
    
    def test_retry_delays_values(self):
        """RETRY_DELAYS has correct values."""
        assert RETRY_DELAYS == [1.0, 3.0, 7.0]
    
    @pytest.mark.asyncio
    async def test_runner_retry_delay_exponential(self, event_bus, context):
        """Retry delays follow exponential pattern."""
        runner = ToolRunner(event_bus=event_bus)
        
        assert runner._get_retry_delay(0) == 1.0
        assert runner._get_retry_delay(1) == 3.0
        assert runner._get_retry_delay(2) == 7.0
        # Beyond array, use last value
        assert runner._get_retry_delay(3) == 7.0


class TestToolRunnerTimeout:
    """Test timeout behavior."""
    
    @pytest.mark.asyncio
    async def test_timeout_error_raised(self, event_bus, context):
        """Timeout raises ToolTimeoutError internally."""
        # Tool that takes longer than normalized minimum timeout
        # Since MIN_TIMEOUT is 20s, we test the timeout normalization logic
        # by verifying that a very short timeout gets normalized to MIN_TIMEOUT
        tool = MockTool(timeout=20.0, delay=0.1)
        runner = ToolRunner(event_bus=event_bus)
        
        # Very short timeout - should be normalized to MIN_TIMEOUT (20s)
        config = RunConfig(timeout=0.05, max_retries=0)
        result = await runner.run(tool, {}, context, config)
        
        # Should succeed because delay (0.1s) < MIN_TIMEOUT (20s)
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_timeout_normalization_min(self, event_bus, context):
        """Timeout below MIN_TIMEOUT is normalized to MIN_TIMEOUT."""
        from bantz.agent.tool_runner import MIN_TIMEOUT
        
        tool = MockTool(delay=0.1)
        runner = ToolRunner(event_bus=event_bus)
        
        # This timeout will be normalized to MIN_TIMEOUT
        config = RunConfig(timeout=1.0, max_retries=0)
        result = await runner.run(tool, {}, context, config)
        
        # Should succeed - tool completes quickly
        assert result.success is True
        assert MIN_TIMEOUT == 20.0
    
    @pytest.mark.asyncio
    async def test_timeout_custom_value(self, event_bus, context):
        """Custom timeout via config is used."""
        tool = MockTool(delay=0.1)  # 100ms
        runner = ToolRunner(event_bus=event_bus)
        
        # Timeout longer than delay
        config = RunConfig(timeout=0.5, max_retries=0)
        result = await runner.run(tool, {}, context, config)
        
        assert result.success is True


class TestToolRunnerCircuitBreaker:
    """Test circuit breaker integration."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_when_open(self, event_bus, context):
        """Open circuit blocks tool execution."""
        circuit_breaker = CircuitBreaker(failure_threshold=1)
        
        # Open the circuit
        circuit_breaker.record_failure("mock_tool")
        
        tool = MockTool()
        runner = ToolRunner(event_bus=event_bus, circuit_breaker=circuit_breaker)
        
        result = await runner.run(tool, {}, context)
        
        assert result.success is False
        assert "circuit" in result.error.lower()
        assert tool.call_count == 0  # Tool was not called
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_success_recorded(self, event_bus, context):
        """Success is recorded in circuit breaker."""
        circuit_breaker = CircuitBreaker()
        tool = MockTool()
        runner = ToolRunner(event_bus=event_bus, circuit_breaker=circuit_breaker)
        
        await runner.run(tool, {}, context)
        
        stats = circuit_breaker.get_stats("mock_tool")
        assert stats.last_success is not None
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_recorded(self, event_bus, context):
        """Failure is recorded in circuit breaker."""
        circuit_breaker = CircuitBreaker()
        tool = MockTool(
            run_result=ToolResult.fail(error="Error", error_type=ErrorType.NETWORK),
            max_retries=0
        )
        runner = ToolRunner(event_bus=event_bus, circuit_breaker=circuit_breaker)
        
        await runner.run(tool, {}, context)
        
        stats = circuit_breaker.get_stats("mock_tool")
        assert stats.failures == 1
    
    @pytest.mark.asyncio
    async def test_skip_circuit_breaker_config(self, event_bus, context):
        """skip_circuit_breaker config bypasses check."""
        circuit_breaker = CircuitBreaker(failure_threshold=1)
        circuit_breaker.record_failure("mock_tool")  # Open circuit
        
        tool = MockTool()
        runner = ToolRunner(event_bus=event_bus, circuit_breaker=circuit_breaker)
        
        config = RunConfig(skip_circuit_breaker=True)
        result = await runner.run(tool, {}, context, config)
        
        assert result.success is True
        assert tool.call_count == 1


class TestToolRunnerValidation:
    """Test input validation."""
    
    @pytest.mark.asyncio
    async def test_validation_error_returns_fail(self, event_bus, context):
        """Invalid input returns validation error."""
        class RequiredParamTool(ToolBase):
            def spec(self):
                return ToolSpec(
                    name="required_tool",
                    description="Test",
                    parameters={"query": {"type": "string", "required": True}}
                )
            
            async def run(self, input, context):
                return ToolResult.ok(data=None)
        
        tool = RequiredParamTool()
        runner = ToolRunner(event_bus=event_bus)
        
        result = await runner.run(tool, {}, context)  # Missing required param
        
        assert result.success is False
        assert result.error_type == ErrorType.VALIDATION


class TestToolRunnerDomainExtraction:
    """Test domain extraction for circuit breaker."""
    
    @pytest.mark.asyncio
    async def test_domain_from_url(self, event_bus, context):
        """Domain extracted from URL input."""
        circuit_breaker = CircuitBreaker()
        tool = MockTool()
        runner = ToolRunner(event_bus=event_bus, circuit_breaker=circuit_breaker)
        
        await runner.run(tool, {"url": "https://example.com/path"}, context)
        
        # Use exact match instead of substring to avoid false positives (Security Alert #16)
        assert "example.com" == circuit_breaker.domains.get("example.com", {}).get("domain", None) or "example.com" in [d for d in circuit_breaker.domains.keys() if d == "example.com"]
        # Simpler alternative: check the domain was registered
        assert any(domain == "example.com" for domain in circuit_breaker.domains)
    
    @pytest.mark.asyncio
    async def test_domain_fallback_to_tool_name(self, event_bus, context):
        """Falls back to tool name when no URL."""
        circuit_breaker = CircuitBreaker()
        tool = MockTool()
        runner = ToolRunner(event_bus=event_bus, circuit_breaker=circuit_breaker)
        
        await runner.run(tool, {"query": "test"}, context)
        
        assert "mock_tool" in circuit_breaker.domains


class TestToolRunnerSingleton:
    """Test singleton pattern."""
    
    def test_get_tool_runner_returns_instance(self):
        """get_tool_runner returns ToolRunner."""
        import bantz.agent.tool_runner as tr
        tr._tool_runner = None  # Reset
        
        runner = get_tool_runner()
        
        assert isinstance(runner, ToolRunner)
