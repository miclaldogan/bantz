"""Tests for Issue #372: Router health check and automatic fallback mechanism.

Verifies:
1. Health check at init (healthy / unhealthy backends)
2. Fallback route when router is unhealthy
3. Consecutive failure tracking → mark unhealthy
4. Recovery: re-check health on each call → resume normal if recovered
5. is_healthy property
"""

import pytest
from unittest.mock import MagicMock, PropertyMock
from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput


def _make_mock_llm(healthy: bool = True, response: str | None = None):
    """Create a mock LLM client with optional health check support.
    
    Uses spec to control which attributes exist, avoiding MagicMock's
    auto-creation of attributes that would confuse hasattr() checks.
    """
    mock = MagicMock()
    # Delete health_check so hasattr falls through to is_available
    del mock.health_check
    mock.is_available = MagicMock(return_value=healthy)
    mock.model_name = "test-model"
    mock.backend_name = "test"
    
    if response is not None:
        mock.complete_text = MagicMock(return_value=response)
    else:
        # Default: return valid JSON for smalltalk
        mock.complete_text = MagicMock(return_value='{"route":"smalltalk","calendar_intent":"none","slots":{},"confidence":1.0,"tool_plan":[],"assistant_reply":"Merhaba efendim!"}')
    
    return mock


class TestHealthCheckInit:
    """Test health check at router initialization."""

    def test_healthy_backend_marks_healthy(self):
        """Router with healthy backend → is_healthy=True."""
        mock_llm = _make_mock_llm(healthy=True)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        assert router.is_healthy is True

    def test_unhealthy_backend_marks_unhealthy(self):
        """Router with unhealthy backend → is_healthy=False."""
        mock_llm = _make_mock_llm(healthy=False)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        assert router.is_healthy is False

    def test_no_health_method_assumes_healthy(self):
        """LLM client without is_available/health_check → assumes healthy."""
        mock_llm = MagicMock(spec=[])
        mock_llm.complete_text = MagicMock(return_value='{}')
        # Remove health methods
        del mock_llm.is_available
        del mock_llm.health_check
        
        # Use a simple object without health methods
        class SimpleClient:
            def complete_text(self, *, prompt, temperature=0.0, max_tokens=200):
                return '{}'
        
        router = JarvisLLMOrchestrator(llm=SimpleClient())
        assert router.is_healthy is True

    def test_health_check_exception_marks_unhealthy(self):
        """Health check raising exception → marks unhealthy."""
        mock_llm = MagicMock()
        del mock_llm.health_check
        mock_llm.is_available = MagicMock(side_effect=ConnectionError("refused"))
        router = JarvisLLMOrchestrator(llm=mock_llm)
        assert router.is_healthy is False


class TestFallbackRoute:
    """Test fallback routing when router is unhealthy."""

    def test_unhealthy_router_returns_fallback(self):
        """Unhealthy router → returns graceful fallback output."""
        mock_llm = _make_mock_llm(healthy=False)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        result = router.route(user_input="merhaba")
        
        assert result.route == "unknown"
        assert result.confidence == 0.0
        assert result.tool_plan == []
        assert result.ask_user is True
        assert "teknik bir sorun" in result.assistant_reply
        assert result.raw_output.get("fallback") is True

    def test_unhealthy_router_does_not_call_llm(self):
        """Unhealthy router should NOT call the LLM (skip the call)."""
        mock_llm = _make_mock_llm(healthy=False)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        # Ensure is_available returns False on re-check too
        mock_llm.is_available.return_value = False
        
        router.route(user_input="test input")
        
        # complete_text should NOT be called (fallback path)
        mock_llm.complete_text.assert_not_called()


class TestConsecutiveFailureTracking:
    """Test that consecutive LLM failures eventually mark router unhealthy."""

    def test_single_failure_stays_healthy(self):
        """One LLM call failure → still healthy (below threshold)."""
        mock_llm = _make_mock_llm(healthy=True)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        # First call fails
        mock_llm.complete_text.side_effect = ConnectionError("timeout")
        router.route(user_input="test")
        
        # Still healthy (1 < 3 threshold)
        assert router.is_healthy is True

    def test_three_failures_marks_unhealthy(self):
        """Three consecutive failures → marked unhealthy."""
        mock_llm = _make_mock_llm(healthy=True)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        mock_llm.complete_text.side_effect = ConnectionError("refused")
        
        # 3 consecutive failures
        for _ in range(3):
            router.route(user_input="test")
        
        assert router.is_healthy is False

    def test_success_resets_failure_counter(self):
        """Successful call resets consecutive failure counter."""
        mock_llm = _make_mock_llm(healthy=True)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        # Two failures
        mock_llm.complete_text.side_effect = ConnectionError("timeout")
        router.route(user_input="test1")
        router.route(user_input="test2")
        assert router._consecutive_failures == 2
        
        # Then success
        mock_llm.complete_text.side_effect = None
        mock_llm.complete_text.return_value = '{"route":"smalltalk","calendar_intent":"none","slots":{},"confidence":1.0,"tool_plan":[],"assistant_reply":"ok"}'
        router.route(user_input="test3")
        
        assert router._consecutive_failures == 0
        assert router.is_healthy is True


class TestRecovery:
    """Test that unhealthy router can recover."""

    def test_recovery_on_health_check(self):
        """Unhealthy router recovers when health check passes again."""
        mock_llm = _make_mock_llm(healthy=False)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        assert router.is_healthy is False
        
        # Backend recovers
        mock_llm.is_available.return_value = True
        mock_llm.complete_text.return_value = '{"route":"smalltalk","calendar_intent":"none","slots":{},"confidence":1.0,"tool_plan":[],"assistant_reply":"Merhaba!"}'
        
        result = router.route(user_input="merhaba")
        
        # Should have recovered and returned normal result
        assert router.is_healthy is True
        assert result.route == "smalltalk"
        assert "Merhaba" in result.assistant_reply

    def test_still_unhealthy_after_failed_recheck(self):
        """Unhealthy router stays unhealthy if re-check still fails."""
        mock_llm = _make_mock_llm(healthy=False)
        router = JarvisLLMOrchestrator(llm=mock_llm)
        assert router.is_healthy is False
        
        # Backend still down
        mock_llm.is_available.return_value = False
        
        result = router.route(user_input="test")
        
        assert router.is_healthy is False
        assert result.route == "unknown"
        assert result.ask_user is True
