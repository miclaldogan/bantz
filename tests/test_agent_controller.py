"""Tests for Agent Controller (Issue #22).

Multi-Step Task Execution - Agent Framework tests.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

# ─────────────────────────────────────────────────────────────────
# Controller Imports
# ─────────────────────────────────────────────────────────────────

from bantz.agent.controller import (
    AgentController,
    ControllerState,
    ControllerContext,
    PlanDisplay,
    PlanStepDisplay,
    MockAgentController,
    get_step_icon,
    STEP_STATUS_COLORS,
    StepStatusIcon,
)


# ─────────────────────────────────────────────────────────────────
# Test Step Status Icons
# ─────────────────────────────────────────────────────────────────

class TestStepStatusIcon:
    """Test step status icon enumeration."""
    
    def test_pending_icon(self):
        assert StepStatusIcon.PENDING.value == "○"
    
    def test_in_progress_icon(self):
        assert StepStatusIcon.IN_PROGRESS.value == "⏳"
    
    def test_completed_icon(self):
        assert StepStatusIcon.COMPLETED.value == "✓"
    
    def test_failed_icon(self):
        assert StepStatusIcon.FAILED.value == "✗"
    
    def test_skipped_icon(self):
        assert StepStatusIcon.SKIPPED.value == "⊘"


class TestGetStepIcon:
    """Test get_step_icon function."""
    
    def test_get_pending_icon(self):
        assert get_step_icon("pending") == "○"
    
    def test_get_running_icon(self):
        assert get_step_icon("running") == "⏳"
    
    def test_get_completed_icon(self):
        assert get_step_icon("completed") == "✓"
    
    def test_get_failed_icon(self):
        assert get_step_icon("failed") == "✗"
    
    def test_get_skipped_icon(self):
        assert get_step_icon("skipped") == "⊘"
    
    def test_get_unknown_icon_returns_pending(self):
        assert get_step_icon("unknown") == "○"


class TestStepStatusColors:
    """Test step status colors."""
    
    def test_pending_color(self):
        assert STEP_STATUS_COLORS["pending"] == "#888888"
    
    def test_running_color(self):
        assert STEP_STATUS_COLORS["running"] == "#FFD700"
    
    def test_completed_color(self):
        assert STEP_STATUS_COLORS["completed"] == "#00FF7F"
    
    def test_failed_color(self):
        assert STEP_STATUS_COLORS["failed"] == "#FF4444"
    
    def test_skipped_color(self):
        assert STEP_STATUS_COLORS["skipped"] == "#666666"


# ─────────────────────────────────────────────────────────────────
# Test Plan Display Data Classes
# ─────────────────────────────────────────────────────────────────

class TestPlanStepDisplay:
    """Test PlanStepDisplay dataclass."""
    
    def test_create_step_display(self):
        step = PlanStepDisplay(
            index=1,
            description="Hava durumunu kontrol et",
            status="pending",
            icon="○",
            color="#888888",
            tool="weather_check",
        )
        
        assert step.index == 1
        assert step.description == "Hava durumunu kontrol et"
        assert step.status == "pending"
        assert step.icon == "○"
        assert step.color == "#888888"
        assert step.tool == "weather_check"
        assert step.elapsed_time is None
    
    def test_step_with_elapsed_time(self):
        step = PlanStepDisplay(
            index=1,
            description="Test",
            status="completed",
            icon="✓",
            color="#00FF7F",
            tool="test",
            elapsed_time=2.5,
        )
        
        assert step.elapsed_time == 2.5


class TestPlanDisplay:
    """Test PlanDisplay dataclass."""
    
    def test_create_plan_display(self):
        steps = [
            PlanStepDisplay(index=1, description="Adım 1", status="completed", icon="✓", color="#00FF7F", tool="tool1"),
            PlanStepDisplay(index=2, description="Adım 2", status="running", icon="⏳", color="#FFD700", tool="tool2"),
            PlanStepDisplay(index=3, description="Adım 3", status="pending", icon="○", color="#888888", tool="tool3"),
        ]
        
        plan = PlanDisplay(
            id="task_123",
            title="GÖREV PLANI",
            description="Hava durumu ve haberleri özetle",
            steps=steps,
            current_step=1,
            total_steps=3,
            status="executing",
            progress_percent=33.3,
        )
        
        assert plan.id == "task_123"
        assert plan.title == "GÖREV PLANI"
        assert len(plan.steps) == 3
        assert plan.current_step == 1
        assert plan.total_steps == 3
        assert plan.status == "executing"
        assert plan.progress_percent == 33.3
    
    def test_plan_with_timestamps(self):
        plan = PlanDisplay(
            id="test",
            title="Test",
            description="Test plan",
            steps=[],
            current_step=0,
            total_steps=0,
            status="completed",
            progress_percent=100,
            started_at=1000.0,
            completed_at=1005.0,
        )
        
        assert plan.started_at == 1000.0
        assert plan.completed_at == 1005.0


# ─────────────────────────────────────────────────────────────────
# Test Controller State
# ─────────────────────────────────────────────────────────────────

class TestControllerState:
    """Test ControllerState enum."""
    
    def test_idle_state(self):
        assert ControllerState.IDLE.value == "idle"
    
    def test_planning_state(self):
        assert ControllerState.PLANNING.value == "planning"
    
    def test_awaiting_confirmation_state(self):
        assert ControllerState.AWAITING_CONFIRMATION.value == "awaiting_confirmation"
    
    def test_executing_state(self):
        assert ControllerState.EXECUTING.value == "executing"
    
    def test_paused_state(self):
        assert ControllerState.PAUSED.value == "paused"
    
    def test_completed_state(self):
        assert ControllerState.COMPLETED.value == "completed"
    
    def test_failed_state(self):
        assert ControllerState.FAILED.value == "failed"
    
    def test_cancelled_state(self):
        assert ControllerState.CANCELLED.value == "cancelled"


class TestControllerContext:
    """Test ControllerContext dataclass."""
    
    def test_default_context(self):
        ctx = ControllerContext()
        
        assert ctx.results == {}
        assert ctx.errors == []
        assert ctx.step_times == {}
        assert ctx.start_time > 0
    
    def test_context_with_results(self):
        ctx = ControllerContext()
        ctx.results["step1"] = {"data": "test"}
        ctx.errors.append("error1")
        ctx.step_times[0] = 1.5
        
        assert ctx.results["step1"]["data"] == "test"
        assert "error1" in ctx.errors
        assert ctx.step_times[0] == 1.5


# ─────────────────────────────────────────────────────────────────
# Test Mock Agent Controller
# ─────────────────────────────────────────────────────────────────

class TestMockAgentController:
    """Test MockAgentController for testing without LLM."""
    
    def test_initial_state(self):
        controller = MockAgentController()
        
        assert controller.state == ControllerState.IDLE
        assert controller.plans == []
        assert not controller.is_confirmed()
        assert not controller.is_cancelled()
    
    def test_add_mock_plan(self):
        controller = MockAgentController()
        
        plan = controller.add_mock_plan(
            "Hava durumu ve haberleri kontrol et",
            ["Hava durumunu kontrol et", "Haberleri özetle", "Sonuçları göster"]
        )
        
        assert len(controller.plans) == 1
        assert plan.description == "Hava durumu ve haberleri kontrol et"
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "Hava durumunu kontrol et"
        assert plan.steps[0].status == "pending"
        assert plan.steps[0].icon == "○"
    
    def test_confirm(self):
        controller = MockAgentController()
        
        assert not controller.is_confirmed()
        controller.confirm()
        assert controller.is_confirmed()
    
    def test_cancel(self):
        controller = MockAgentController()
        
        assert not controller.is_cancelled()
        controller.cancel()
        assert controller.is_cancelled()
    
    def test_set_state(self):
        controller = MockAgentController()
        
        controller.set_state(ControllerState.EXECUTING)
        assert controller.state == ControllerState.EXECUTING
        
        controller.set_state(ControllerState.COMPLETED)
        assert controller.state == ControllerState.COMPLETED


# ─────────────────────────────────────────────────────────────────
# Test Agent Controller Core Functionality
# ─────────────────────────────────────────────────────────────────

class TestAgentControllerInit:
    """Test AgentController initialization."""
    
    def test_controller_with_defaults(self):
        """Controller should create default agent if none provided."""
        # This test is lighter - just checks instantiation
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            assert controller.state == ControllerState.IDLE
            assert controller.current_task is None
            assert not controller.is_running
    
    def test_controller_with_custom_panel(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        panel = MockJarvisPanelController()
        
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController(panel=panel)
            
            assert controller.panel == panel
    
    def test_controller_auto_confirm_mode(self):
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController(auto_confirm=True)
            
            assert controller.auto_confirm is True


class TestAgentControllerControls:
    """Test AgentController control methods."""
    
    def test_cancel(self):
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            assert controller._cancelled is False
            controller.cancel()
            assert controller._cancelled is True
    
    def test_skip_current_step(self):
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            assert controller._skip_current is False
            controller.skip_current_step()
            assert controller._skip_current is True
    
    def test_pause_and_resume(self):
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            controller.pause()
            assert controller._paused is True
            assert controller._state == ControllerState.PAUSED
            
            controller.resume()
            assert controller._paused is False


class TestAgentControllerPlanDisplay:
    """Test AgentController plan display building."""
    
    def test_build_empty_plan_display(self):
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            plan_display = controller._build_plan_display()
            
            assert plan_display.id == ""
            assert plan_display.steps == []
            assert plan_display.progress_percent == 0
    
    def test_generate_summary(self):
        from bantz.agent.core import Task, Step
        
        task = Task(
            id="test",
            original_request="Test request",
            steps=[
                Step(id=1, action="tool1", params={}, description="Step 1", status="completed", result={"summary": "Done"}),
                Step(id=2, action="tool2", params={}, description="Step 2", status="completed", result={}),
                Step(id=3, action="tool3", params={}, description="Step 3", status="failed", error="Error"),
            ],
            current_step=3,
        )
        
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            summary = controller._generate_summary(task)
            
            assert "2/3 adım tamamlandı" in summary


class TestAgentControllerCriticalSteps:
    """Test critical step detection."""
    
    def test_payment_is_critical(self):
        from bantz.agent.core import Step
        
        step = Step(id=1, action="payment", params={}, description="Payment")
        
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            assert controller._is_critical_step(step) is True
    
    def test_delete_is_critical(self):
        from bantz.agent.core import Step
        
        step = Step(id=1, action="delete", params={}, description="Delete")
        
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            assert controller._is_critical_step(step) is True
    
    def test_browser_open_is_not_critical(self):
        from bantz.agent.core import Step
        
        step = Step(id=1, action="browser_open", params={}, description="Open browser")
        
        with patch('bantz.llm.ollama_client.OllamaClient'):
            controller = AgentController()
            
            assert controller._is_critical_step(step) is False


# ─────────────────────────────────────────────────────────────────
# Test NLU Multi-Step Patterns
# ─────────────────────────────────────────────────────────────────

class TestNLUAgentPatterns:
    """Test NLU patterns for agent mode."""
    
    def test_agent_prefix_pattern(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("agent: youtube'a git ve coldplay ara")
        
        assert result.intent == "agent_run"
        assert result.slots.get("skip_preview") is False
        assert "youtube" in result.slots.get("request", "").lower()
    
    def test_agent_immediate_mode(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("agent!: instagram'a git")
        
        assert result.intent == "agent_run"
        assert result.slots.get("skip_preview") is True
    
    def test_planla_prefix(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("planla: hava durumunu kontrol et")
        
        assert result.intent == "agent_run"
        assert "hava" in result.slots.get("request", "").lower()
    
    def test_agent_confirm_pattern(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("planı onayla")
        
        assert result.intent == "agent_confirm_plan"
    
    def test_agent_status_pattern(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("agent durumu")
        
        assert result.intent == "agent_status"
    
    def test_agent_cancel_pattern(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("agent iptal")
        
        assert result.intent == "queue_abort"


class TestNLUMultiStepDetection:
    """Test multi-step request detection."""
    
    def test_chain_split_with_ve_sonra(self):
        from bantz.router.nlu import split_chain
        
        parts = split_chain("youtube'a git ve sonra coldplay ara")
        
        assert len(parts) == 2
        assert "youtube" in parts[0].lower()
        assert "coldplay" in parts[1].lower()
    
    def test_chain_split_with_ardindan(self):
        from bantz.router.nlu import split_chain
        
        parts = split_chain("haberleri oku ardından özetle")
        
        assert len(parts) == 2
    
    def test_no_split_for_reminder(self):
        from bantz.router.nlu import split_chain
        
        # Reminder with "5 dakika sonra" should NOT be split
        parts = split_chain("5 dakika sonra hatırlat")
        
        assert len(parts) == 1


# ─────────────────────────────────────────────────────────────────
# Test JarvisPanel Plan Display
# ─────────────────────────────────────────────────────────────────

class TestJarvisPanelPlanDisplay:
    """Test JarvisPanel plan display functionality."""
    
    def test_mock_controller_show_plan(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        
        plan = PlanDisplay(
            id="test_123",
            title="GÖREV PLANI",
            description="Test görev",
            steps=[
                PlanStepDisplay(index=1, description="Adım 1", status="pending", icon="○", color="#888888", tool="tool1"),
                PlanStepDisplay(index=2, description="Adım 2", status="pending", icon="○", color="#888888", tool="tool2"),
            ],
            current_step=0,
            total_steps=2,
            status="planning",
            progress_percent=0,
        )
        
        controller.show_plan(plan)
        
        assert controller.current_plan is not None
        assert controller.current_plan["id"] == "test_123"
        assert len(controller.current_plan["steps"]) == 2
        assert controller.panel.is_visible
    
    def test_mock_controller_show_plan_dict(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        
        plan_dict = {
            "id": "dict_plan",
            "title": "Dict Plan",
            "description": "Test with dict",
            "steps": [
                {"index": 1, "description": "Step 1", "status": "completed", "icon": "✓", "color": "#00FF7F"},
            ],
            "current_step": 1,
            "total_steps": 1,
            "status": "completed",
            "progress_percent": 100,
        }
        
        controller.show_plan(plan_dict)
        
        assert controller.current_plan["id"] == "dict_plan"
        assert controller.current_plan["progress_percent"] == 100


# ─────────────────────────────────────────────────────────────────
# Test Agent Core Classes
# ─────────────────────────────────────────────────────────────────

class TestAgentCoreClasses:
    """Test core agent classes."""
    
    def test_agent_state_enum(self):
        from bantz.agent.core import AgentState
        
        assert AgentState.IDLE.value == "idle"
        assert AgentState.PLANNING.value == "planning"
        assert AgentState.EXECUTING.value == "executing"
        assert AgentState.COMPLETED.value == "completed"
        assert AgentState.FAILED.value == "failed"
    
    def test_step_dataclass(self):
        from bantz.agent.core import Step
        
        step = Step(
            id=1,
            action="browser_open",
            params={"url": "youtube.com"},
            description="YouTube'u aç",
        )
        
        assert step.id == 1
        assert step.action == "browser_open"
        assert step.params["url"] == "youtube.com"
        assert step.status == "pending"
        assert step.result is None
        assert step.error is None
    
    def test_task_dataclass(self):
        from bantz.agent.core import Task, AgentState
        
        task = Task(
            id="task_1",
            original_request="YouTube'a git",
        )
        
        assert task.id == "task_1"
        assert task.original_request == "YouTube'a git"
        assert task.steps == []
        assert task.current_step == 0
        assert task.state == AgentState.IDLE


class TestToolRegistry:
    """Test ToolRegistry functionality."""
    
    def test_register_tool(self):
        from bantz.agent.tools import Tool, ToolRegistry
        
        registry = ToolRegistry()
        
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
        )
        
        registry.register(tool)
        
        assert registry.get("test_tool") is not None
        assert "test_tool" in registry.names()
    
    def test_validate_call_missing_tool(self):
        from bantz.agent.tools import ToolRegistry
        
        registry = ToolRegistry()
        
        ok, reason = registry.validate_call("nonexistent", {})
        
        assert ok is False
        assert "unknown_tool" in reason
    
    def test_validate_call_missing_required_param(self):
        from bantz.agent.tools import Tool, ToolRegistry
        
        registry = ToolRegistry()
        
        tool = Tool(
            name="test",
            description="Test",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        )
        registry.register(tool)
        
        ok, reason = registry.validate_call("test", {})
        
        assert ok is False
        assert "missing_param" in reason


class TestBuiltinTools:
    """Test builtin tools registry."""
    
    def test_build_default_registry(self):
        from bantz.agent.builtin_tools import build_default_registry
        
        registry = build_default_registry()
        
        # Check some expected tools exist
        assert registry.get("browser_open") is not None
        assert registry.get("browser_scan") is not None
        assert registry.get("browser_click") is not None
        assert registry.get("browser_type") is not None
    
    def test_browser_open_tool_schema(self):
        from bantz.agent.builtin_tools import build_default_registry
        
        registry = build_default_registry()
        tool = registry.get("browser_open")
        
        assert tool is not None
        assert tool.description
        assert "url" in tool.parameters.get("required", [])


# ─────────────────────────────────────────────────────────────────
# Test Planner
# ─────────────────────────────────────────────────────────────────

class TestPlanner:
    """Test Planner class."""
    
    def test_planner_system_prompt_contains_tools(self):
        from bantz.agent.planner import Planner
        
        assert "tool" in Planner.SYSTEM_PROMPT.lower()
        assert "JSON" in Planner.SYSTEM_PROMPT
    
    def test_parse_json_object_simple(self):
        from bantz.agent.planner import Planner
        
        result = Planner._parse_json_object('{"steps": []}')
        
        assert result == {"steps": []}
    
    def test_parse_json_object_with_prefix(self):
        from bantz.agent.planner import Planner
        
        result = Planner._parse_json_object('Some text before {"steps": []}')
        
        assert result == {"steps": []}
    
    def test_parse_json_object_empty_raises(self):
        from bantz.agent.planner import Planner
        
        with pytest.raises(ValueError, match="planner_empty"):
            Planner._parse_json_object("")
    
    def test_parse_json_object_no_json_raises(self):
        from bantz.agent.planner import Planner
        
        with pytest.raises(ValueError, match="planner_no_json"):
            Planner._parse_json_object("no json here")


# ─────────────────────────────────────────────────────────────────
# Test Executor
# ─────────────────────────────────────────────────────────────────

class TestExecutor:
    """Test Executor class."""
    
    def test_execution_result_dataclass(self):
        from bantz.agent.executor import ExecutionResult
        
        result = ExecutionResult(ok=True, data={"key": "value"})
        
        assert result.ok is True
        assert result.data == {"key": "value"}
        assert result.error is None
    
    def test_execution_result_with_error(self):
        from bantz.agent.executor import ExecutionResult
        
        result = ExecutionResult(ok=False, error="Something went wrong")
        
        assert result.ok is False
        assert result.error == "Something went wrong"


# ─────────────────────────────────────────────────────────────────
# Test Recovery Policy
# ─────────────────────────────────────────────────────────────────

class TestRecoveryPolicy:
    """Test RecoveryPolicy class."""
    
    def test_retry_on_first_attempt(self):
        from bantz.agent.recovery import RecoveryPolicy
        
        policy = RecoveryPolicy(max_retries=2)
        
        decision = policy.decide(attempt=1)
        
        assert decision.action == "retry"
    
    def test_abort_after_max_retries(self):
        from bantz.agent.recovery import RecoveryPolicy
        
        policy = RecoveryPolicy(max_retries=2)
        
        decision = policy.decide(attempt=3)
        
        assert decision.action == "abort"
    
    def test_timeout_detection(self):
        from bantz.agent.recovery import RecoveryPolicy
        
        policy = RecoveryPolicy(step_timeout_seconds=30)
        
        decision = policy.decide(attempt=1, elapsed_seconds=35.0)
        
        assert decision.action == "timeout"
    
    def test_should_timeout(self):
        from bantz.agent.recovery import RecoveryPolicy
        
        policy = RecoveryPolicy(step_timeout_seconds=60)
        
        assert policy.should_timeout(30.0) is False
        assert policy.should_timeout(60.0) is True
        assert policy.should_timeout(90.0) is True


# ─────────────────────────────────────────────────────────────────
# Test Verifier
# ─────────────────────────────────────────────────────────────────

class TestVerifier:
    """Test Verifier class."""
    
    def test_verify_success(self):
        from bantz.agent.verifier import Verifier
        from bantz.agent.executor import ExecutionResult
        from bantz.agent.core import Step
        
        verifier = Verifier()
        step = Step(id=1, action="test", params={}, description="Test")
        result = ExecutionResult(ok=True)
        
        verification = verifier.verify(step, result)
        
        assert verification.ok is True
    
    def test_verify_failure(self):
        from bantz.agent.verifier import Verifier
        from bantz.agent.executor import ExecutionResult
        from bantz.agent.core import Step
        
        verifier = Verifier()
        step = Step(id=1, action="test", params={}, description="Test")
        result = ExecutionResult(ok=False, error="failed")
        
        verification = verifier.verify(step, result)
        
        assert verification.ok is False
        assert verification.reason == "failed"


# ─────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────

class TestAgentIntegration:
    """Integration tests for the agent framework."""
    
    def test_full_mock_workflow(self):
        """Test complete mock workflow without LLM."""
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        # Setup mock controller
        mock_ctrl = MockAgentController()
        panel_ctrl = MockJarvisPanelController()
        
        # Create a mock plan
        plan = mock_ctrl.add_mock_plan(
            "YouTube'a git ve video ara",
            ["YouTube'u aç", "Arama kutusuna yaz", "Sonuçları göster"]
        )
        
        # Show on panel
        panel_ctrl.show_plan(plan)
        
        # Verify state
        assert mock_ctrl.state == ControllerState.IDLE
        assert len(plan.steps) == 3
        assert panel_ctrl.current_plan is not None
        assert panel_ctrl.panel.is_visible
    
    def test_plan_step_status_progression(self):
        """Test step status progression through execution."""
        mock_ctrl = MockAgentController()
        
        plan = mock_ctrl.add_mock_plan(
            "Test task",
            ["Step 1", "Step 2", "Step 3"]
        )
        
        # Initially all pending
        assert all(s.status == "pending" for s in plan.steps)
        
        # Simulate execution progress
        plan.steps[0].status = "completed"
        plan.steps[0].icon = "✓"
        plan.steps[0].color = "#00FF7F"
        
        plan.steps[1].status = "running"
        plan.steps[1].icon = "⏳"
        plan.steps[1].color = "#FFD700"
        
        # Verify progression
        assert plan.steps[0].status == "completed"
        assert plan.steps[1].status == "running"
        assert plan.steps[2].status == "pending"


# ─────────────────────────────────────────────────────────────────
# Test Module Exports
# ─────────────────────────────────────────────────────────────────

class TestAgentModuleExports:
    """Test that agent module exports are correct."""
    
    def test_agent_module_exports(self):
        from bantz.agent import (
            Agent,
            AgentState,
            Planner,
            Step,
            Task,
            Tool,
            ToolRegistry,
            AgentController,
            ControllerState,
            PlanDisplay,
            PlanStepDisplay,
            MockAgentController,
            get_step_icon,
            STEP_STATUS_COLORS,
        )
        
        # Just verify imports work
        assert Agent is not None
        assert AgentController is not None
        assert ControllerState is not None
        assert PlanDisplay is not None


class TestUIExports:
    """Test UI module exports for plan display."""
    
    def test_panel_controller_has_show_plan(self):
        from bantz.ui.jarvis_panel import JarvisPanelController, MockJarvisPanelController
        
        # Verify method exists
        assert hasattr(JarvisPanelController, "show_plan")
        assert hasattr(MockJarvisPanelController, "show_plan")
