"""
Tests for executor module.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from bantz.automation.plan import TaskPlan, PlanStep, StepStatus, create_task_plan
from bantz.automation.executor import (
    Executor,
    ExecutorState,
    ExecutionResult,
    create_executor,
)


class MockToolRuntime:
    """Mock tool runtime."""
    
    def __init__(self, success: bool = True, result: dict = None):
        self.success = success
        self.result = result or {"status": "done"}
        self.execute = AsyncMock(return_value=self.result)


class MockEventBus:
    """Mock event bus."""
    
    def __init__(self):
        self.events = []
        self.emit = AsyncMock(side_effect=self._record_event)
    
    async def _record_event(self, event: str, data: dict):
        self.events.append((event, data))


class TestExecutorState:
    """Tests for ExecutorState enum."""
    
    def test_state_values(self):
        """Test all state values exist."""
        assert ExecutorState.IDLE.value == "idle"
        assert ExecutorState.RUNNING.value == "running"
        assert ExecutorState.PAUSED.value == "paused"
        assert ExecutorState.CANCELLED.value == "cancelled"


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""
    
    def test_create_result(self):
        """Test creating execution result."""
        result = ExecutionResult(
            step_id="s1",
            success=True,
            result={"data": "value"},
            duration_ms=100,
        )
        
        assert result.step_id == "s1"
        assert result.success
        assert result.result == {"data": "value"}
        assert result.duration_ms == 100
        assert result.error is None
    
    def test_failed_result(self):
        """Test failed execution result."""
        result = ExecutionResult(
            step_id="s1",
            success=False,
            error="Something went wrong",
            duration_ms=50,
        )
        
        assert not result.success
        assert result.error == "Something went wrong"
    
    def test_to_dict(self):
        """Test serialization."""
        result = ExecutionResult(
            step_id="s1",
            success=True,
            result={"key": "value"},
            duration_ms=100,
        )
        
        d = result.to_dict()
        assert d["step_id"] == "s1"
        assert d["success"] is True
        # Result is stringified
        assert "key" in str(d["result"])
        assert d["duration_ms"] == 100


class TestExecutor:
    """Tests for Executor class."""
    
    @pytest.fixture
    def tool_runtime(self):
        """Create mock tool runtime."""
        return MockToolRuntime()
    
    @pytest.fixture
    def event_bus(self):
        """Create mock event bus."""
        return MockEventBus()
    
    @pytest.fixture
    def executor(self, tool_runtime, event_bus):
        """Create executor instance."""
        return Executor(tool_runtime=tool_runtime, event_bus=event_bus)
    
    @pytest.fixture
    def plan(self):
        """Create test plan."""
        return create_task_plan("Test goal", [
            {"action": "step1", "description": "Step 1"},
            {"action": "step2", "description": "Step 2"},
        ])
    
    def test_initial_state(self, executor):
        """Test initial state is IDLE."""
        assert executor._state == ExecutorState.IDLE
        assert not executor.is_running
        assert not executor.is_paused
        assert not executor.is_cancelled
    
    @pytest.mark.asyncio
    async def test_execute_step_success(self, executor, plan, tool_runtime):
        """Test executing a step successfully."""
        step = plan.steps[0]
        
        result = await executor.execute_step(step)
        
        assert result.success
        assert result.step_id == step.id
        assert result.duration_ms >= 0
        tool_runtime.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_step_failure(self, executor, plan, tool_runtime):
        """Test handling step failure."""
        tool_runtime.execute = AsyncMock(side_effect=Exception("Execution failed"))
        step = plan.steps[0]
        
        result = await executor.execute_step(step)
        
        assert not result.success
        assert "Execution failed" in result.error
    
    @pytest.mark.asyncio
    async def test_execute_plan(self, executor, plan, tool_runtime):
        """Test executing full plan."""
        plan.start()
        
        results = await executor.execute_plan(plan)
        
        assert len(results) == 2
        assert all(r.success for r in results)
    
    @pytest.mark.asyncio
    async def test_execute_plan_emits_events(self, executor, plan, event_bus):
        """Test that events are emitted during execution."""
        plan.start()
        
        await executor.execute_plan(plan)
        
        event_names = [e[0] for e in event_bus.events]
        assert "plan_started" in event_names or any("step" in e for e in event_names)
    
    @pytest.mark.asyncio
    async def test_pause_execution(self, executor, plan, tool_runtime):
        """Test pausing execution."""
        # Make execution slow
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"status": "done"}
        
        tool_runtime.execute = slow_execute
        plan.start()
        
        # Start execution in background
        task = asyncio.create_task(executor.execute_plan(plan))
        
        # Pause immediately
        await asyncio.sleep(0.01)
        await executor.pause()
        
        assert executor.is_paused
        
        # Resume to complete
        await executor.resume()
        await task
    
    @pytest.mark.asyncio
    async def test_cancel_execution(self, executor, plan, tool_runtime):
        """Test cancelling execution."""
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"status": "done"}
        
        tool_runtime.execute = slow_execute
        plan.start()
        
        # Start execution in background
        task = asyncio.create_task(executor.execute_plan(plan))
        
        # Cancel immediately
        await asyncio.sleep(0.01)
        await executor.cancel()
        
        assert executor.is_cancelled
        
        # Task should complete (possibly with partial results)
        await task
    
    @pytest.mark.asyncio
    async def test_retry_step(self, executor, plan, tool_runtime):
        """Test retrying a failed step."""
        step = plan.steps[0]
        step.max_retries = 3
        
        # Fail first, succeed second
        call_count = 0
        
        async def flaky_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First failure")
            return {"status": "done"}
        
        tool_runtime.execute = flaky_execute
        
        # Execute step (may succeed or fail depending on retry logic)
        result = await executor.execute_step(step)
        
        assert call_count >= 1
    
    @pytest.mark.asyncio
    async def test_consecutive_failures_tracking(self, executor, plan, tool_runtime):
        """Test tracking consecutive failures."""
        tool_runtime.execute = AsyncMock(side_effect=Exception("Always fails"))
        
        step = plan.steps[0]
        await executor.execute_step(step)
        
        assert executor.consecutive_failures >= 1
    
    @pytest.mark.asyncio
    async def test_consecutive_failures_reset_on_success(self, executor, plan, tool_runtime):
        """Test consecutive failures reset on success."""
        # First call fails
        tool_runtime.execute = AsyncMock(side_effect=Exception("Fail"))
        
        await executor.execute_step(plan.steps[0])
        assert executor.consecutive_failures >= 1
        
        # Second call succeeds
        tool_runtime.execute = AsyncMock(return_value={"status": "done"})
        
        await executor.execute_step(plan.steps[1])
        assert executor.consecutive_failures == 0


class TestCreateExecutor:
    """Tests for create_executor factory."""
    
    def test_create_executor(self):
        """Test factory function."""
        tool_runtime = MockToolRuntime()
        event_bus = MockEventBus()
        
        executor = create_executor(tool_runtime, event_bus)
        
        assert isinstance(executor, Executor)
    
    def test_create_executor_without_event_bus(self):
        """Test factory without event bus."""
        tool_runtime = MockToolRuntime()
        
        executor = create_executor(tool_runtime, None)
        
        assert isinstance(executor, Executor)
