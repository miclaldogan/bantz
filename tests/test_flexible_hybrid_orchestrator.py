"""Tests for Flexible Hybrid Orchestrator (Issue #157)."""

import pytest
from unittest.mock import Mock, MagicMock

from bantz.brain.flexible_hybrid_orchestrator import (
    FlexibleHybridOrchestrator,
    FlexibleHybridConfig,
    create_flexible_hybrid_orchestrator,
)
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput
from bantz.llm.base import LLMMessage, LLMResponse


class MockRouter:
    """Mock 3B router."""
    
    def __init__(self, response_override=None):
        self.response_override = response_override
        self.model_name = "mock-3b"
        self.backend_name = "mock"
    
    def plan(self, user_input: str, dialog_summary: str = ""):
        if self.response_override:
            return self.response_override
        
        # Default mock response
        return OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={"date": "bugün"},
            confidence=0.9,
            tool_plan=["list_events"],
            assistant_reply="Bugün 2 toplantınız var.",
            raw_output={},
        )


class MockFinalizer:
    """Mock finalizer (Gemini or 7B vLLM)."""
    
    def __init__(self, available=True, response_override=None):
        self._available = available
        self.response_override = response_override
        self.model_name = "mock-7b"
        self.backend_name = "mock"
        self.call_count = 0
    
    def is_available(self, timeout_seconds: float = 1.5):
        return self._available
    
    def chat_detailed(self, messages, *, temperature=0.4, max_tokens=512):
        self.call_count += 1
        
        if self.response_override:
            content = self.response_override
        else:
            content = "Efendim, bugün 2 toplantınız var: sabah 10'da standup ve öğleden sonra 3'te review."
        
        return LLMResponse(
            content=content,
            model="mock-7b",
            tokens_used=42,
            finish_reason="stop",
        )


class TestFlexibleHybridConfig:
    """Test configuration dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = FlexibleHybridConfig()
        
        assert config.router_backend == "vllm"
        assert config.router_model == "Qwen/Qwen2.5-3B-Instruct"
        assert config.router_temperature == 0.0
        
        assert config.finalizer_type == "vllm_7b"
        assert config.finalizer_model == "Qwen/Qwen2.5-7B-Instruct"
        assert config.finalizer_temperature == 0.6
        
        assert config.fallback_to_3b is True
        assert config.enable_streaming is False
        assert config.confidence_threshold == 0.7
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = FlexibleHybridConfig(
            finalizer_type="gemini",
            finalizer_model="gemini-1.5-pro",
            finalizer_temperature=0.8,
            fallback_to_3b=False,
        )
        
        assert config.finalizer_type == "gemini"
        assert config.finalizer_model == "gemini-1.5-pro"
        assert config.finalizer_temperature == 0.8
        assert config.fallback_to_3b is False


class TestFlexibleHybridOrchestrator:
    """Test flexible hybrid orchestrator."""
    
    def test_successful_finalization(self):
        """Test successful finalization with 7B."""
        router = MockRouter()
        finalizer = MockFinalizer(available=True)
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
        )
        
        output = orchestrator.plan(user_input="bugün ne işlerim var")
        
        assert output.route == "calendar"
        assert output.calendar_intent == "query"
        assert "toplantınız var" in output.assistant_reply.lower()
        assert finalizer.call_count == 1  # Finalizer was called
    
    def test_fallback_to_3b_when_finalizer_unavailable(self):
        """Test fallback to 3B when finalizer is unavailable."""
        router = MockRouter()
        finalizer = MockFinalizer(available=False)  # Unavailable
        
        config = FlexibleHybridConfig(fallback_to_3b=True)
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
            config=config,
        )
        
        output = orchestrator.plan(user_input="bugün ne işlerim var")
        
        assert output.route == "calendar"
        # Should use router's response as fallback
        assert output.assistant_reply == "Bugün 2 toplantınız var."
        assert finalizer.call_count == 0  # Finalizer not called
    
    def test_fallback_to_3b_when_finalizer_fails(self):
        """Test fallback to 3B when finalizer throws error."""
        router = MockRouter()
        
        # Create finalizer that throws error
        finalizer = Mock()
        finalizer.is_available.return_value = True
        finalizer.chat_detailed.side_effect = Exception("API Error")
        
        config = FlexibleHybridConfig(fallback_to_3b=True)
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
            config=config,
        )
        
        output = orchestrator.plan(user_input="bugün ne işlerim var")
        
        assert output.route == "calendar"
        # Should fallback to router response
        assert output.assistant_reply == "Bugün 2 toplantınız var."
    
    def test_no_fallback_raises_error(self):
        """Test that error is raised when no fallback enabled."""
        router = MockRouter()
        
        # Create finalizer that throws error
        finalizer = Mock()
        finalizer.is_available.return_value = True
        finalizer.chat_detailed.side_effect = Exception("API Error")
        
        config = FlexibleHybridConfig(fallback_to_3b=False)
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
            config=config,
        )
        
        with pytest.raises(Exception) as exc_info:
            orchestrator.plan(user_input="bugün ne işlerim var")
        
        assert "API Error" in str(exc_info.value)
    
    def test_finalizer_receives_tool_results(self):
        """Test that finalizer receives tool results."""
        router = MockRouter()
        finalizer = MockFinalizer(available=True)
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
        )
        
        tool_results = {"events": [{"title": "Meeting 1"}, {"title": "Meeting 2"}]}
        
        output = orchestrator.plan(
            user_input="bugün ne işlerim var",
            tool_results=tool_results,
        )
        
        assert output.route == "calendar"
        assert finalizer.call_count == 1
    
    def test_smalltalk_handling(self):
        """Test smalltalk route handling."""
        # Mock router to return smalltalk
        smalltalk_output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.99,
            tool_plan=[],
            assistant_reply="Merhaba!",
            raw_output={},
        )
        
        router = MockRouter(response_override=smalltalk_output)
        finalizer = MockFinalizer(
            available=True,
            response_override="Merhaba efendim! Nasıl yardımcı olabilirim?",
        )
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
        )
        
        output = orchestrator.plan(user_input="merhaba")
        
        assert output.route == "smalltalk"
        assert output.calendar_intent == "none"
        assert "merhaba" in output.assistant_reply.lower()
    
    def test_get_active_finalizer_type(self):
        """Test active finalizer type reporting."""
        router = MockRouter()
        
        # Test with available finalizer
        finalizer = MockFinalizer(available=True)
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
        )
        assert orchestrator._get_active_finalizer_type() == "vllm_7b"
        
        # Test with unavailable finalizer
        finalizer = MockFinalizer(available=False)
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
        )
        assert orchestrator._get_active_finalizer_type() == "3b_fallback"


class TestCreateFlexibleHybridOrchestrator:
    """Test factory function."""
    
    def test_create_with_defaults(self):
        """Test creation with default config."""
        router_client = Mock()
        router_client.chat_detailed.return_value = LLMResponse(
            content='{"route": "calendar", "calendar_intent": "query", "confidence": 0.9}',
            model="mock-3b",
            tokens_used=50,
            finish_reason="stop",
        )
        
        finalizer_client = MockFinalizer(available=True)
        
        orchestrator = create_flexible_hybrid_orchestrator(
            router_client=router_client,
            finalizer_client=finalizer_client,
        )
        
        assert orchestrator is not None
        assert orchestrator._config.finalizer_type == "vllm_7b"
    
    def test_create_with_custom_config(self):
        """Test creation with custom config."""
        router_client = Mock()
        finalizer_client = MockFinalizer(available=True)
        
        config = FlexibleHybridConfig(
            finalizer_type="gemini",
            finalizer_temperature=0.8,
        )
        
        orchestrator = create_flexible_hybrid_orchestrator(
            router_client=router_client,
            finalizer_client=finalizer_client,
            config=config,
        )
        
        assert orchestrator._config.finalizer_type == "gemini"
        assert orchestrator._config.finalizer_temperature == 0.8
    
    def test_create_without_finalizer_fallback_mode(self):
        """Test creation without finalizer (fallback mode)."""
        router_client = Mock()
        router_client.chat_detailed.return_value = LLMResponse(
            content='{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.99, "assistant_reply": "Merhaba!"}',
            model="mock-3b",
            tokens_used=50,
            finish_reason="stop",
        )
        
        orchestrator = create_flexible_hybrid_orchestrator(
            router_client=router_client,
            finalizer_client=None,  # No finalizer
        )
        
        assert orchestrator is not None
        assert orchestrator._finalizer_available is False


class TestAcceptanceCriteria:
    """Test Issue #157 acceptance criteria."""
    
    def test_finalizer_phase_uses_7b(self):
        """Test that finalizer phase uses 7B (not 3B)."""
        router = MockRouter()
        finalizer = MockFinalizer(available=True)
        
        config = FlexibleHybridConfig(finalizer_type="vllm_7b")
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
            config=config,
        )
        
        output = orchestrator.plan(user_input="bugün ne işlerim var")
        
        # Finalizer should be called (7B)
        assert finalizer.call_count == 1
        # Response should be from 7B, not 3B router
        assert output.assistant_reply != router.plan("", "").assistant_reply
    
    def test_fallback_when_8002_down(self):
        """Test fallback when port 8002 (7B) is down."""
        router = MockRouter()
        finalizer = MockFinalizer(available=False)  # Simulating down
        
        config = FlexibleHybridConfig(fallback_to_3b=True)
        
        orchestrator = FlexibleHybridOrchestrator(
            router_orchestrator=router,
            finalizer=finalizer,
            config=config,
        )
        
        # Should not crash, should fallback to 3B
        output = orchestrator.plan(user_input="bugün ne işlerim var")
        
        assert output.route == "calendar"
        # Should use 3B router response (fallback)
        assert output.assistant_reply == "Bugün 2 toplantınız var."
        assert finalizer.call_count == 0  # 7B not called
