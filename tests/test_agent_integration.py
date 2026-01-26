"""Integration tests for agent retry and plan preview features."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from bantz.router.context import ConversationContext, QueueStep
from bantz.router.nlu import parse_intent


class TestAgentRetryIntegration:
    """Integration tests for agent retry functionality."""

    @pytest.fixture
    def mock_router(self):
        """Create a router with mocked dependencies."""
        from bantz.router.engine import Router
        from bantz.logs.logger import JsonlLogger
        from bantz.router.policy import Policy

        policy = Policy(
            deny_patterns=(),
            confirm_patterns=(),
            deny_even_if_confirmed_patterns=(),
            intent_levels={},
        )
        logger = JsonlLogger(path="/dev/null")
        router = Router(policy=policy, logger=logger)
        return router

    def test_agent_retry_no_history(self, mock_router):
        """agent tekrar komutu, geçmiş yoksa hata döndürmeli."""
        ctx = ConversationContext()
        result = mock_router.handle("agent tekrar", ctx)
        
        assert result.ok is False
        assert "başarısız bir agent task" in result.user_text.lower() or "bulamadım" in result.user_text.lower()

    def test_agent_retry_with_active_queue(self, mock_router):
        """agent tekrar komutu, aktif kuyruk varsa hata döndürmeli."""
        ctx = ConversationContext()
        ctx.set_queue([QueueStep(original_text="test", intent="browser_open", slots={"url": "x"})], source="chain")
        
        result = mock_router.handle("agent tekrar", ctx)
        
        assert result.ok is False
        assert "aktif" in result.user_text.lower()


class TestAgentPlanPreviewIntegration:
    """Integration tests for agent plan preview functionality."""

    @pytest.fixture
    def mock_router(self):
        """Create a router with mocked planner."""
        from bantz.router.engine import Router
        from bantz.logs.logger import JsonlLogger
        from bantz.router.policy import Policy

        policy = Policy(
            deny_patterns=(),
            confirm_patterns=(),
            deny_even_if_confirmed_patterns=(),
            intent_levels={},
        )
        logger = JsonlLogger(path="/dev/null")
        router = Router(policy=policy, logger=logger)
        return router

    def test_plan_preview_is_shown(self, mock_router):
        """agent: komutu plan preview göstermeli."""
        ctx = ConversationContext()

        # Mock the planner to return a simple plan
        with patch("bantz.agent.planner.Planner.plan") as mock_plan:
            from bantz.agent.planner import PlannedStep
            mock_plan.return_value = [
                PlannedStep(action="browser_open", params={"url": "youtube"}, description="YouTube'u aç"),
                PlannedStep(action="browser_search", params={"query": "coldplay"}, description="Coldplay ara"),
            ]

            result = mock_router.handle("agent: youtube'a git ve coldplay ara", ctx)

        # Should show preview, not execute immediately
        assert "Plan" in result.user_text or "adım" in result.user_text
        assert result.needs_confirmation is True

        # Should have pending plan
        assert ctx.get_pending_agent_plan() is not None

    def test_immediate_mode_skips_preview(self, mock_router):
        """agent!: komutu preview atlamalı ve direkt çalıştırmalı."""
        ctx = ConversationContext()

        # Mock the planner to return a simple plan
        with patch("bantz.agent.planner.Planner.plan") as mock_plan:
            from bantz.agent.planner import PlannedStep
            mock_plan.return_value = [
                PlannedStep(action="browser_open", params={"url": "youtube"}, description="YouTube'u aç"),
            ]

            # Mock browser_open execution
            with patch("bantz.browser.skills.browser_open", return_value=(True, "OK")):
                result = mock_router.handle("agent!: youtube'a git", ctx)

        # Should not have pending plan (executed immediately)
        assert ctx.get_pending_agent_plan() is None


class TestAgentConfirmPlanFlow:
    """Test the full plan confirmation flow."""

    @pytest.fixture
    def mock_router(self):
        """Create a router with mocked planner."""
        from bantz.router.engine import Router
        from bantz.logs.logger import JsonlLogger
        from bantz.router.policy import Policy

        policy = Policy(
            deny_patterns=(),
            confirm_patterns=(),
            deny_even_if_confirmed_patterns=(),
            intent_levels={},
        )
        logger = JsonlLogger(path="/dev/null")
        router = Router(policy=policy, logger=logger)
        return router

    def test_confirm_yes_executes_plan(self, mock_router):
        """evet komutu planı çalıştırmalı."""
        ctx = ConversationContext()

        # Set up pending plan
        steps = [QueueStep(original_text="test", intent="browser_open", slots={"url": "test"})]
        ctx.set_pending_agent_plan(task_id="test-1", steps=steps)
        mock_router._agent_history.append({"id": "test-1", "state": "awaiting_confirmation", "steps": []})
        mock_router._agent_history_by_id["test-1"] = mock_router._agent_history[-1]

        # Mock execution
        with patch("bantz.browser.skills.browser_open", return_value=(True, "OK")):
            result = mock_router.handle("evet", ctx)

        # Plan should be cleared and queue should be set
        assert ctx.get_pending_agent_plan() is None

    def test_confirm_no_cancels_plan(self, mock_router):
        """hayır komutu planı iptal etmeli."""
        ctx = ConversationContext()

        # Set up pending plan
        steps = [QueueStep(original_text="test", intent="browser_open", slots={"url": "test"})]
        ctx.set_pending_agent_plan(task_id="test-1", steps=steps)
        mock_router._agent_history.append({"id": "test-1", "state": "awaiting_confirmation", "steps": []})
        mock_router._agent_history_by_id["test-1"] = mock_router._agent_history[-1]

        result = mock_router.handle("hayır", ctx)

        # Plan should be cleared
        assert ctx.get_pending_agent_plan() is None
        assert "iptal" in result.user_text.lower()

        # Task state should be cancelled
        assert mock_router._agent_history[-1]["state"] == "cancelled"


class TestStepTimingMetadata:
    """Test that step timing metadata is recorded correctly."""

    def test_step_timeout_values(self):
        """Step timeout değerleri makul olmalı."""
        from bantz.agent.recovery import STEP_TIMEOUTS, get_step_timeout

        # All values should be positive
        for intent, timeout in STEP_TIMEOUTS.items():
            assert timeout > 0, f"Timeout for {intent} should be positive"

        # Specific checks
        assert get_step_timeout("browser_wait") >= 30  # browser_wait can be up to 30s
        assert get_step_timeout("browser_scan") <= 30  # scan shouldn't take long
        assert get_step_timeout("default") >= 30  # reasonable default
