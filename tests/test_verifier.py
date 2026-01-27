"""
Tests for verifier module.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bantz.automation.plan import PlanStep, StepStatus, create_task_plan
from bantz.automation.executor import ExecutionResult
from bantz.automation.verifier import (
    Verifier,
    VerificationResult,
    create_verifier,
)


class MockLLMClient:
    """Mock LLM client."""
    
    def __init__(self, response: str = ""):
        self.response = response
        self.complete = AsyncMock(return_value=response)


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""
    
    def test_create_result(self):
        """Test creating verification result."""
        result = VerificationResult(
            step_id="s1",
            verified=True,
            confidence=0.95,
            evidence="Output matches expected",
        )
        
        assert result.step_id == "s1"
        assert result.verified
        assert result.confidence == 0.95
        assert result.evidence is not None
    
    def test_failed_verification(self):
        """Test failed verification result."""
        result = VerificationResult(
            step_id="s1",
            verified=False,
            confidence=0.3,
            issues=["Expected file not created"],
            suggestions=["Check file permissions"],
        )
        
        assert not result.verified
        assert result.confidence == 0.3
        assert len(result.issues) == 1
        assert len(result.suggestions) == 1
    
    def test_to_dict(self):
        """Test serialization."""
        result = VerificationResult(
            step_id="s1",
            verified=True,
            confidence=0.9,
            evidence="Success",
        )
        
        d = result.to_dict()
        assert d["step_id"] == "s1"
        assert d["verified"] is True
        assert d["confidence"] == 0.9


class TestVerifier:
    """Tests for Verifier class."""
    
    @pytest.fixture
    def llm_client(self):
        """Create mock LLM client."""
        return MockLLMClient(
            response='evet, başarılı bir şekilde tamamlandı'
        )
    
    @pytest.fixture
    def verifier(self, llm_client):
        """Create verifier instance."""
        return Verifier(llm_client=llm_client)
    
    @pytest.fixture
    def step(self):
        """Create test step."""
        step = PlanStep(
            id="s1",
            action="open_file",
            description="Open the file",
        )
        step.mark_running()
        step.mark_success({"file": "test.txt", "opened": True})
        return step
    
    @pytest.fixture
    def exec_result(self, step):
        """Create execution result."""
        return ExecutionResult(
            step_id=step.id,
            success=True,
            result={"file": "test.txt", "opened": True},
            duration_ms=100,
        )
    
    @pytest.mark.asyncio
    async def test_verify_step_success(self, verifier, step, exec_result):
        """Test verifying a successful step."""
        result = await verifier.verify_step(step, exec_result)
        
        assert isinstance(result, VerificationResult)
        assert result.step_id == step.id
        assert result.verified
    
    @pytest.mark.asyncio
    async def test_verify_step_with_llm(self, verifier, step, exec_result, llm_client):
        """Test verification uses LLM."""
        result = await verifier.verify_step_with_llm(step, exec_result)
        
        assert llm_client.complete.called
    
    @pytest.mark.asyncio
    async def test_verify_step_failure(self, verifier, step):
        """Test verifying failed step."""
        failed_result = ExecutionResult(
            step_id=step.id,
            success=False,
            error="Error occurred",
            duration_ms=50,
        )
        
        result = await verifier.verify_step(step, failed_result)
        
        assert isinstance(result, VerificationResult)
        assert not result.verified
    
    @pytest.mark.asyncio
    async def test_verify_step_no_result(self, verifier, step):
        """Test verifying step with no result."""
        no_result = ExecutionResult(
            step_id=step.id,
            success=True,
            result=None,
            duration_ms=100,
        )
        
        result = await verifier.verify_step(step, no_result)
        
        assert isinstance(result, VerificationResult)
        # Should still verify but with lower confidence
        assert result.verified
    
    @pytest.mark.asyncio
    async def test_verify_plan(self, verifier):
        """Test verifying a complete plan."""
        plan = create_task_plan("Test goal", [
            {"action": "a1", "description": "Step 1"},
            {"action": "a2", "description": "Step 2"},
        ])
        plan.start()
        
        # Create execution results
        results = [
            ExecutionResult(step_id=plan.steps[0].id, success=True, result={"done": True}, duration_ms=100),
            ExecutionResult(step_id=plan.steps[1].id, success=True, result={"done": True}, duration_ms=100),
        ]
        
        # Complete steps
        for step in plan.steps:
            step.mark_running()
            step.mark_success({"done": True})
        
        result = await verifier.verify_plan(plan, results)
        
        assert isinstance(result, VerificationResult)
    
    @pytest.mark.asyncio
    async def test_verify_plan_partial_success(self, verifier):
        """Test verifying plan with partial success."""
        plan = create_task_plan("Test goal", [
            {"action": "a1", "description": "Step 1"},
            {"action": "a2", "description": "Step 2"},
            {"action": "a3", "description": "Step 3"},
        ])
        plan.start()
        
        # Create execution results - first two succeed, third fails
        results = [
            ExecutionResult(step_id=plan.steps[0].id, success=True, result={}, duration_ms=100),
            ExecutionResult(step_id=plan.steps[1].id, success=True, result={}, duration_ms=100),
            ExecutionResult(step_id=plan.steps[2].id, success=False, error="Error", duration_ms=50),
        ]
        
        # Complete first two, fail third
        plan.steps[0].mark_running()
        plan.steps[0].mark_success({})
        plan.steps[1].mark_running()
        plan.steps[1].mark_success({})
        plan.steps[2].mark_running()
        plan.steps[2].mark_failed("Error")
        
        result = await verifier.verify_plan(plan, results)
        
        # 66% success rate
        assert isinstance(result, VerificationResult)
    
    def test_get_verification_prompt(self, verifier, step):
        """Test generating verification prompt."""
        exec_result = ExecutionResult(
            step_id=step.id,
            success=True,
            result={"done": True},
            duration_ms=100,
        )
        
        prompt = verifier.get_verification_prompt(step, exec_result)
        
        assert isinstance(prompt, str)
        assert len(prompt) > 0
    
    def test_min_confidence_threshold(self, verifier):
        """Test minimum confidence threshold."""
        assert verifier.MIN_CONFIDENCE_THRESHOLD == 0.7


class TestCreateVerifier:
    """Tests for create_verifier factory."""
    
    def test_create_verifier(self):
        """Test factory function."""
        llm = MockLLMClient()
        
        verifier = create_verifier(llm)
        
        assert isinstance(verifier, Verifier)
    
    def test_create_verifier_without_llm(self):
        """Test factory without LLM."""
        verifier = create_verifier(None)
        
        assert isinstance(verifier, Verifier)
