"""
Tests for PEV orchestrator module.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bantz.automation.plan import TaskPlan, PlanStep, StepStatus, PlanStatus, create_task_plan
from bantz.automation.planner import Planner
from bantz.automation.executor import Executor, ExecutionResult, ExecutorState
from bantz.automation.verifier import Verifier, VerificationResult
from bantz.automation.failsafe import FailSafeHandler, FailSafeChoice, FailSafeAction
from bantz.automation.templates import TemplateRegistry, TaskTemplate
from bantz.automation.orchestrator import (
    PEVOrchestrator,
    PEVState,
    PEVResult,
    create_pev_orchestrator,
)


class MockEventBus:
    """Mock event bus."""
    
    def __init__(self):
        self.events = []
        self.emit = AsyncMock(side_effect=self._record)
    
    async def _record(self, event: str, data: dict):
        self.events.append((event, data))


class MockPlanner:
    """Mock planner."""
    
    def __init__(self, plan: TaskPlan = None):
        self.plan = plan
        self.create_plan = AsyncMock(return_value=plan)
        self.decompose_goal = AsyncMock(return_value=[])
        self.validate_plan = MagicMock(return_value=MagicMock(valid=True, issues=[]))


class MockExecutor:
    """Mock executor."""
    
    def __init__(self, success: bool = True):
        self.success = success
        self.state = ExecutorState.IDLE
        self._consecutive_failures = 0
        
        self.execute_step = AsyncMock(side_effect=self._execute)
        self.execute_plan = AsyncMock(return_value=[])
        self.pause = AsyncMock(side_effect=self._pause)
        self.resume = AsyncMock(side_effect=self._resume)
        self.cancel = AsyncMock(side_effect=self._cancel)
    
    async def _execute(self, plan: TaskPlan, step: PlanStep):
        if self.success:
            self._consecutive_failures = 0
            return ExecutionResult(
                step_id=step.id,
                success=True,
                result={"done": True},
                duration_ms=100,
            )
        else:
            self._consecutive_failures += 1
            return ExecutionResult(
                step_id=step.id,
                success=False,
                error="Mock failure",
                duration_ms=50,
            )
    
    async def _pause(self):
        self.state = ExecutorState.PAUSED
    
    async def _resume(self):
        self.state = ExecutorState.RUNNING
    
    async def _cancel(self):
        self.state = ExecutorState.CANCELLED
    
    @property
    def is_running(self):
        return self.state == ExecutorState.RUNNING
    
    @property
    def is_paused(self):
        return self.state == ExecutorState.PAUSED
    
    @property
    def is_cancelled(self):
        return self.state == ExecutorState.CANCELLED
    
    @property
    def consecutive_failures(self):
        return self._consecutive_failures


class MockVerifier:
    """Mock verifier."""
    
    def __init__(self, verified: bool = True, confidence: float = 0.9):
        self.verified = verified
        self.confidence = confidence
        
        self.verify_step = AsyncMock(side_effect=self._verify)
        self.verify_plan = AsyncMock(side_effect=self._verify_plan)
    
    async def _verify(self, step: PlanStep, result: dict):
        return VerificationResult(
            step_id=step.id,
            verified=self.verified,
            confidence=self.confidence,
        )
    
    async def _verify_plan(self, plan: TaskPlan):
        return VerificationResult(
            step_id="plan",
            verified=self.verified,
            confidence=self.confidence,
        )


class MockFailSafe:
    """Mock fail-safe handler."""
    
    def __init__(self, action: FailSafeAction = FailSafeAction.RETRY):
        self.action = action
        self.handle_failure = AsyncMock(return_value=FailSafeChoice(action=action))
        self.should_ask_user = MagicMock(return_value=True)
        self.notify_retry = AsyncMock()
        self.notify_skip = AsyncMock()
        self.notify_abort = AsyncMock()
        self.notify_manual = AsyncMock()
        self.wait_for_manual_completion = AsyncMock(return_value=True)


class TestPEVState:
    """Tests for PEVState enum."""
    
    def test_state_values(self):
        """Test all state values exist."""
        assert PEVState.IDLE.value == "idle"
        assert PEVState.PLANNING.value == "planning"
        assert PEVState.EXECUTING.value == "executing"
        assert PEVState.VERIFYING.value == "verifying"
        assert PEVState.HANDLING_FAILURE.value == "handling_failure"
        assert PEVState.COMPLETED.value == "completed"
        assert PEVState.FAILED.value == "failed"
        assert PEVState.CANCELLED.value == "cancelled"


class TestPEVResult:
    """Tests for PEVResult dataclass."""
    
    def test_create_result(self):
        """Test creating result."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        
        result = PEVResult(
            plan=plan,
            success=True,
            completed_steps=1,
            failed_steps=0,
            skipped_steps=0,
            duration_ms=1000,
        )
        
        assert result.success
        assert result.completed_steps == 1
        assert result.duration_ms == 1000
    
    def test_to_dict(self):
        """Test serialization."""
        plan = create_task_plan("Test", [{"action": "a", "description": "A"}])
        
        result = PEVResult(
            plan=plan,
            success=True,
            completed_steps=1,
            failed_steps=0,
            skipped_steps=0,
            duration_ms=1000,
        )
        
        d = result.to_dict()
        assert d["success"] is True
        assert d["completed_steps"] == 1


class TestPEVOrchestrator:
    """Tests for PEVOrchestrator class."""
    
    @pytest.fixture
    def plan(self):
        """Create test plan."""
        return create_task_plan("Test goal", [
            {"action": "step1", "description": "Step 1"},
            {"action": "step2", "description": "Step 2"},
        ])
    
    @pytest.fixture
    def planner(self, plan):
        """Create mock planner."""
        return MockPlanner(plan=plan)
    
    @pytest.fixture
    def executor(self):
        """Create mock executor."""
        return MockExecutor(success=True)
    
    @pytest.fixture
    def verifier(self):
        """Create mock verifier."""
        return MockVerifier(verified=True)
    
    @pytest.fixture
    def failsafe(self):
        """Create mock failsafe."""
        return MockFailSafe()
    
    @pytest.fixture
    def event_bus(self):
        """Create mock event bus."""
        return MockEventBus()
    
    @pytest.fixture
    def orchestrator(self, planner, executor, verifier, failsafe, event_bus):
        """Create orchestrator instance."""
        return PEVOrchestrator(
            planner=planner,
            executor=executor,
            verifier=verifier,
            failsafe=failsafe,
            event_bus=event_bus,
            auto_verify=True,
        )
    
    def test_initial_state(self, orchestrator):
        """Test initial state is IDLE."""
        assert orchestrator.state == PEVState.IDLE
        assert not orchestrator.is_running
        assert orchestrator.current_plan is None
    
    @pytest.mark.asyncio
    async def test_run_success(self, orchestrator, planner):
        """Test successful run."""
        result = await orchestrator.run("Test goal")
        
        assert result is not None
        assert result.plan is not None
        planner.create_plan.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_with_context(self, orchestrator, planner):
        """Test run with context."""
        context = {"user": "test"}
        
        await orchestrator.run("Test goal", context)
        
        planner.create_plan.assert_called_with("Test goal", context)
    
    @pytest.mark.asyncio
    async def test_run_planning_failure(self, orchestrator, planner):
        """Test handling planning failure."""
        planner.create_plan = AsyncMock(return_value=None)
        
        result = await orchestrator.run("Test goal")
        
        assert not result.success
        assert "Failed to create plan" in result.error
    
    @pytest.mark.asyncio
    async def test_run_with_plan(self, orchestrator, plan):
        """Test running with pre-created plan."""
        result = await orchestrator.run_with_plan(plan)
        
        assert result is not None
        assert result.plan == plan
    
    @pytest.mark.asyncio
    async def test_run_emits_events(self, orchestrator, event_bus):
        """Test events are emitted."""
        await orchestrator.run("Test goal")
        
        event_names = [e[0] for e in event_bus.events]
        assert "pev_planning_started" in event_names
        assert "pev_plan_created" in event_names
    
    @pytest.mark.asyncio
    async def test_verification_failure_triggers_failsafe(
        self, planner, executor, failsafe, event_bus, plan
    ):
        """Test verification failure triggers failsafe."""
        verifier = MockVerifier(verified=False, confidence=0.3)
        failsafe.action = FailSafeAction.SKIP
        failsafe.handle_failure = AsyncMock(
            return_value=FailSafeChoice(action=FailSafeAction.SKIP)
        )
        
        orchestrator = PEVOrchestrator(
            planner=planner,
            executor=executor,
            verifier=verifier,
            failsafe=failsafe,
            event_bus=event_bus,
            auto_verify=True,
            verify_threshold=0.7,
        )
        
        await orchestrator.run("Test goal")
        
        # Failsafe should be triggered
        assert failsafe.handle_failure.called or failsafe.should_ask_user.called
    
    @pytest.mark.asyncio
    async def test_execution_failure_abort(
        self, planner, verifier, failsafe, event_bus, plan
    ):
        """Test execution failure with abort."""
        executor = MockExecutor(success=False)
        failsafe.handle_failure = AsyncMock(
            return_value=FailSafeChoice(action=FailSafeAction.ABORT)
        )
        
        orchestrator = PEVOrchestrator(
            planner=planner,
            executor=executor,
            verifier=verifier,
            failsafe=failsafe,
            event_bus=event_bus,
            auto_verify=False,
        )
        
        result = await orchestrator.run("Test goal")
        
        # Plan should be cancelled
        assert orchestrator.state in (PEVState.CANCELLED, PEVState.FAILED)
    
    @pytest.mark.asyncio
    async def test_pause_resume(self, orchestrator, executor, event_bus):
        """Test pause and resume."""
        # Simulate running state
        executor.state = ExecutorState.RUNNING
        orchestrator._current_plan = create_task_plan("Test", [])
        
        await orchestrator.pause()
        
        assert executor.pause.called
        
        executor.state = ExecutorState.PAUSED
        
        await orchestrator.resume()
        
        assert executor.resume.called
    
    @pytest.mark.asyncio
    async def test_cancel(self, orchestrator, executor, event_bus):
        """Test cancel."""
        orchestrator._current_plan = create_task_plan("Test", [])
        
        await orchestrator.cancel()
        
        assert executor.cancel.called
        assert orchestrator.state == PEVState.CANCELLED


class TestCreatePEVOrchestrator:
    """Tests for create_pev_orchestrator factory."""
    
    def test_create_orchestrator(self):
        """Test factory function."""
        planner = MockPlanner()
        executor = MockExecutor()
        verifier = MockVerifier()
        failsafe = MockFailSafe()
        
        orchestrator = create_pev_orchestrator(
            planner=planner,
            executor=executor,
            verifier=verifier,
            failsafe=failsafe,
        )
        
        assert isinstance(orchestrator, PEVOrchestrator)
    
    def test_create_orchestrator_with_options(self):
        """Test factory with options."""
        planner = MockPlanner()
        executor = MockExecutor()
        verifier = MockVerifier()
        failsafe = MockFailSafe()
        event_bus = MockEventBus()
        
        orchestrator = create_pev_orchestrator(
            planner=planner,
            executor=executor,
            verifier=verifier,
            failsafe=failsafe,
            event_bus=event_bus,
            auto_verify=False,
            verify_threshold=0.8,
        )
        
        assert isinstance(orchestrator, PEVOrchestrator)
        assert not orchestrator._auto_verify
        assert orchestrator._verify_threshold == 0.8
