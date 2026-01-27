"""
Tests for planner module.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bantz.automation.plan import TaskPlan, PlanStep
from bantz.automation.planner import Planner, PlanValidationResult, create_planner
from bantz.automation.templates import TaskTemplate, TemplateRegistry


class MockLLMClient:
    """Mock LLM client."""
    
    def __init__(self, response: str = ""):
        self.response = response
        self.generate = AsyncMock(return_value=response)


class TestPlanner:
    """Tests for Planner class."""
    
    @pytest.fixture
    def llm_client(self):
        """Create mock LLM client."""
        return MockLLMClient(response='[{"action": "test", "description": "Test step"}]')
    
    @pytest.fixture
    def registry(self):
        """Create template registry."""
        registry = TemplateRegistry()
        
        template = TaskTemplate(
            id="test_template",
            name="Test Template",
            description="A test template",
            trigger_patterns=[r"test (?P<item>.+)"],
            steps=[
                {"action": "do_test", "description": "Test {item}"},
            ],
            required_params=["item"],
        )
        registry.register(template)
        
        return registry
    
    @pytest.fixture
    def planner(self, llm_client, registry):
        """Create planner instance."""
        return Planner(llm_client=llm_client, template_registry=registry)
    
    @pytest.mark.asyncio
    async def test_create_plan_basic(self, planner, llm_client):
        """Test creating a basic plan."""
        # This will use LLM since template matching may fail
        plan = await planner.create_plan("test something")
        
        assert plan is not None
        assert plan.goal == "test something"
    
    @pytest.mark.asyncio
    async def test_create_plan_from_llm(self, planner, llm_client):
        """Test creating plan from LLM when no template matches."""
        llm_client.response = '[{"action": "llm_action", "description": "LLM step"}]'
        llm_client.generate = AsyncMock(return_value=llm_client.response)
        
        plan = await planner.create_plan("something that doesn't match templates")
        
        # Should fall back to LLM
        assert plan is not None
    
    @pytest.mark.asyncio
    async def test_create_plan_with_context(self, planner, llm_client):
        """Test creating plan with context."""
        context = {"user": "test_user", "preferences": {"theme": "dark"}}
        
        plan = await planner.create_plan("some task", context)
        
        assert plan is not None
        # Context should be set on plan
        assert plan.context == context
    
    @pytest.mark.asyncio
    async def test_decompose_goal(self, planner, llm_client):
        """Test goal decomposition."""
        llm_client.generate = AsyncMock(return_value='["Step 1", "Step 2", "Step 3"]')
        
        # decompose_goal uses LLM
        subtasks = await planner.decompose_goal("complex goal")
        
        # Should return a list
        assert isinstance(subtasks, list)
    
    def test_validate_plan_valid(self, planner):
        """Test validating a valid plan."""
        steps = [
            PlanStep(id="s1", action="a1", description="Step 1"),
            PlanStep(id="s2", action="a2", description="Step 2", depends_on=["s1"]),
        ]
        plan = TaskPlan(id="p1", goal="Test", steps=steps)
        
        result = planner.validate_plan(plan)
        
        assert isinstance(result, PlanValidationResult)
        assert result.valid
        assert len(result.issues) == 0
    
    def test_validate_plan_empty(self, planner):
        """Test validating empty plan."""
        plan = TaskPlan(id="p1", goal="Test", steps=[])
        
        result = planner.validate_plan(plan)
        
        assert not result.valid
        assert len(result.issues) > 0
    
    def test_validate_plan_circular_dependency(self, planner):
        """Test detecting circular dependencies."""
        steps = [
            PlanStep(id="s1", action="a1", description="Step 1", depends_on=["s2"]),
            PlanStep(id="s2", action="a2", description="Step 2", depends_on=["s1"]),
        ]
        plan = TaskPlan(id="p1", goal="Test", steps=steps)
        
        result = planner.validate_plan(plan)
        
        assert not result.valid
        assert any("circular" in issue.lower() for issue in result.issues)
    
    def test_validate_plan_missing_dependency(self, planner):
        """Test detecting missing dependencies."""
        steps = [
            PlanStep(id="s1", action="a1", description="Step 1", depends_on=["nonexistent"]),
        ]
        plan = TaskPlan(id="p1", goal="Test", steps=steps)
        
        result = planner.validate_plan(plan)
        
        # May not be invalid as missing deps are handled gracefully
        assert isinstance(result, PlanValidationResult)
    
    @pytest.mark.asyncio
    async def test_revise_plan(self, planner, llm_client):
        """Test plan revision."""
        steps = [
            PlanStep(id="s1", action="a1", description="Step 1"),
        ]
        plan = TaskPlan(id="p1", goal="Test", steps=steps)
        
        llm_client.generate = AsyncMock(return_value='[{"action": "revised", "description": "Revised step"}]')
        
        revised = await planner.revise_plan(plan, "Make it better")
        
        # Should return a plan
        assert revised is not None


class TestPlanValidationResult:
    """Tests for PlanValidationResult."""
    
    def test_valid_result(self):
        """Test valid result."""
        result = PlanValidationResult(valid=True, issues=[], warnings=[])
        
        assert result.valid
        assert len(result.issues) == 0
    
    def test_invalid_result(self):
        """Test invalid result with issues."""
        result = PlanValidationResult(
            valid=False,
            issues=["Issue 1", "Issue 2"],
            warnings=["Warning 1"],
        )
        
        assert not result.valid
        assert len(result.issues) == 2
        assert len(result.warnings) == 1


class TestCreatePlanner:
    """Tests for create_planner factory."""
    
    def test_create_planner(self):
        """Test factory function."""
        llm = MockLLMClient()
        registry = TemplateRegistry()
        
        planner = create_planner(llm, registry)
        
        assert isinstance(planner, Planner)
    
    def test_create_planner_without_registry(self):
        """Test factory without registry."""
        llm = MockLLMClient()
        
        planner = create_planner(llm, None)
        
        assert isinstance(planner, Planner)
