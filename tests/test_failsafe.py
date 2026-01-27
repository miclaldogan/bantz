"""
Tests for failsafe module.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bantz.automation.plan import TaskPlan, PlanStep, create_task_plan
from bantz.automation.failsafe import (
    FailSafeAction,
    FailSafeChoice,
    FailSafeHandler,
    create_failsafe_handler,
)


class MockTTS:
    """Mock TTS engine."""
    
    def __init__(self):
        self.spoken = []
        self.speak = AsyncMock(side_effect=self._record)
    
    async def _record(self, text: str):
        self.spoken.append(text)


class MockASR:
    """Mock ASR engine."""
    
    def __init__(self, response: str = "1"):
        self.response = response
        self.listen = AsyncMock(return_value=response)


class TestFailSafeAction:
    """Tests for FailSafeAction enum."""
    
    def test_action_values(self):
        """Test all action values exist."""
        assert FailSafeAction.RETRY.value == "retry"
        assert FailSafeAction.SKIP.value == "skip"
        assert FailSafeAction.ABORT.value == "abort"
        assert FailSafeAction.MANUAL.value == "manual"
        assert FailSafeAction.MODIFY.value == "modify"


class TestFailSafeChoice:
    """Tests for FailSafeChoice dataclass."""
    
    def test_create_choice(self):
        """Test creating a choice."""
        choice = FailSafeChoice(
            action=FailSafeAction.RETRY,
            reason="Will try again",
        )
        
        assert choice.action == FailSafeAction.RETRY
        assert choice.reason == "Will try again"
        assert choice.modified_step is None
    
    def test_to_dict(self):
        """Test serialization."""
        choice = FailSafeChoice(
            action=FailSafeAction.SKIP,
            reason="Not important",
        )
        
        d = choice.to_dict()
        assert d["action"] == "skip"
        assert d["reason"] == "Not important"


class TestFailSafeHandler:
    """Tests for FailSafeHandler class."""
    
    @pytest.fixture
    def tts(self):
        """Create mock TTS."""
        return MockTTS()
    
    @pytest.fixture
    def asr(self):
        """Create mock ASR."""
        return MockASR(response="1")
    
    @pytest.fixture
    def handler(self, tts, asr):
        """Create handler instance."""
        return FailSafeHandler(tts=tts, asr=asr, language="tr")
    
    @pytest.fixture
    def plan(self):
        """Create test plan."""
        return create_task_plan("Test goal", [
            {"action": "step1", "description": "Step 1"},
        ])
    
    def test_should_ask_user_threshold(self, handler):
        """Test user ask threshold."""
        assert not handler.should_ask_user(0)
        assert not handler.should_ask_user(1)
        assert handler.should_ask_user(2)
        assert handler.should_ask_user(3)
    
    def test_max_consecutive_failures(self, handler):
        """Test MAX_CONSECUTIVE_FAILURES constant."""
        assert handler.MAX_CONSECUTIVE_FAILURES == 2
    
    @pytest.mark.asyncio
    async def test_handle_failure_auto_retry(self, handler, plan):
        """Test auto-retry on first failure."""
        step = plan.steps[0]
        
        choice = await handler.handle_failure(plan, step, "Error", 1)
        
        assert choice.action == FailSafeAction.RETRY
        assert "Auto-retry" in choice.reason
    
    @pytest.mark.asyncio
    async def test_handle_failure_asks_user(self, handler, plan, asr):
        """Test asking user on multiple failures."""
        step = plan.steps[0]
        
        # Response "1" means retry
        asr.response = "1"
        asr.listen = AsyncMock(return_value="1")
        
        choice = await handler.handle_failure(plan, step, "Error", 2)
        
        # Should ask user
        assert choice.action == FailSafeAction.RETRY
    
    @pytest.mark.asyncio
    async def test_handle_failure_skip(self, handler, plan, asr):
        """Test skip choice."""
        step = plan.steps[0]
        
        asr.response = "2"
        asr.listen = AsyncMock(return_value="2")
        
        choice = await handler.handle_failure(plan, step, "Error", 2)
        
        assert choice.action == FailSafeAction.SKIP
    
    @pytest.mark.asyncio
    async def test_handle_failure_abort(self, handler, plan, asr):
        """Test abort choice."""
        step = plan.steps[0]
        
        asr.response = "3"
        asr.listen = AsyncMock(return_value="3")
        
        choice = await handler.handle_failure(plan, step, "Error", 2)
        
        assert choice.action == FailSafeAction.ABORT
    
    @pytest.mark.asyncio
    async def test_handle_failure_manual(self, handler, plan, asr):
        """Test manual choice."""
        step = plan.steps[0]
        
        asr.response = "4"
        asr.listen = AsyncMock(return_value="4")
        
        choice = await handler.handle_failure(plan, step, "Error", 2)
        
        assert choice.action == FailSafeAction.MANUAL
    
    @pytest.mark.asyncio
    async def test_ask_user_choice_keyword(self, handler, asr):
        """Test keyword detection."""
        asr.listen = AsyncMock(return_value="iptal et")
        
        choice = await handler.ask_user_choice(["Retry", "Skip", "Abort"])
        
        assert choice == 2  # Abort index
    
    @pytest.mark.asyncio
    async def test_ask_user_choice_number(self, handler, asr):
        """Test number detection."""
        asr.listen = AsyncMock(return_value="2")
        
        choice = await handler.ask_user_choice(["Retry", "Skip", "Abort"])
        
        assert choice == 1  # Second option (0-based)
    
    @pytest.mark.asyncio
    async def test_notify_methods(self, handler, tts):
        """Test notification methods."""
        await handler.notify_retry()
        assert len(tts.spoken) == 1
        
        await handler.notify_skip()
        assert len(tts.spoken) == 2
        
        await handler.notify_abort()
        assert len(tts.spoken) == 3
        
        await handler.notify_manual()
        assert len(tts.spoken) == 4
    
    @pytest.mark.asyncio
    async def test_wait_for_manual_completion(self, handler, asr):
        """Test waiting for manual completion."""
        asr.listen = AsyncMock(return_value="bitti")
        
        completed = await handler.wait_for_manual_completion()
        
        assert completed
    
    @pytest.mark.asyncio
    async def test_wait_for_manual_completion_no_asr(self):
        """Test manual completion without ASR."""
        handler = FailSafeHandler(tts=None, asr=None)
        
        completed = await handler.wait_for_manual_completion()
        
        assert completed  # Defaults to True
    
    def test_failure_history(self, handler):
        """Test failure history tracking."""
        assert len(handler.get_failure_history()) == 0
        
        handler._failure_history.append({
            "plan_id": "p1",
            "step_id": "s1",
            "error": "Test error",
        })
        
        assert len(handler.get_failure_history()) == 1
        
        handler.clear_history()
        assert len(handler.get_failure_history()) == 0
    
    def test_language_messages(self):
        """Test language selection."""
        handler_tr = FailSafeHandler(language="tr")
        handler_en = FailSafeHandler(language="en")
        
        assert handler_tr._messages == handler_tr.MESSAGES_TR
        assert handler_en._messages == handler_en.MESSAGES_EN


class TestCreateFailsafeHandler:
    """Tests for create_failsafe_handler factory."""
    
    def test_create_handler(self):
        """Test factory function."""
        tts = MockTTS()
        asr = MockASR()
        
        handler = create_failsafe_handler(tts, asr, "en")
        
        assert isinstance(handler, FailSafeHandler)
    
    def test_create_handler_minimal(self):
        """Test factory with minimal args."""
        handler = create_failsafe_handler()
        
        assert isinstance(handler, FailSafeHandler)
