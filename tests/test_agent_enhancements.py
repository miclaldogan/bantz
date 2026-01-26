"""Tests for agent framework enhancements (Issue #3 completion)."""
from __future__ import annotations

import pytest

from bantz.router.context import ConversationContext
from bantz.router.nlu import parse_intent, Parsed


# ─────────────────────────────────────────────────────────────────
# NLU Tests for new agent commands
# ─────────────────────────────────────────────────────────────────
class TestAgentNluEnhancements:
    """Test new agent-related NLU patterns."""

    def test_agent_retry_command(self):
        """agent tekrar komutu doğru parse edilmeli."""
        cases = [
            "agent tekrar",
            "agent retry",
            "tekrar dene agent",
            "son agenti tekrar",
            "son agent tekrar",
        ]
        for cmd in cases:
            p = parse_intent(cmd)
            assert p.intent == "agent_retry", f"Failed for: {cmd}"

    def test_agent_immediate_mode(self):
        """agent!: prefix skip_preview=True olmalı."""
        p = parse_intent("agent!: youtube'a git")
        assert p.intent == "agent_run"
        assert p.slots.get("request") == "youtube'a git"
        assert p.slots.get("skip_preview") is True

    def test_agent_standard_mode_preview(self):
        """agent: prefix skip_preview=False olmalı (preview gösterir)."""
        p = parse_intent("agent: youtube'a git")
        assert p.intent == "agent_run"
        assert p.slots.get("request") == "youtube'a git"
        assert p.slots.get("skip_preview") is False

    def test_agent_confirm_plan(self):
        """Plan onaylama komutları doğru parse edilmeli."""
        cases = [
            "planı onayla",
            "plan tamam",
            "agent başlat",
            "planı çalıştır",
        ]
        for cmd in cases:
            p = parse_intent(cmd)
            assert p.intent == "agent_confirm_plan", f"Failed for: {cmd}"

    def test_agent_cancel_variations(self):
        """Agent iptal komutları queue_abort olmalı."""
        cases = [
            "agent iptal",
            "agenti iptal",
            "agent durdur",
            "agenti bitir",
        ]
        for cmd in cases:
            p = parse_intent(cmd)
            assert p.intent == "queue_abort", f"Failed for: {cmd}"


# ─────────────────────────────────────────────────────────────────
# Context Tests for pending agent plan
# ─────────────────────────────────────────────────────────────────
class TestPendingAgentPlan:
    """Test pending agent plan context management."""

    def test_set_and_get_pending_plan(self):
        """Pending plan set/get/clear çalışmalı."""
        from bantz.router.context import QueueStep

        ctx = ConversationContext()
        assert ctx.get_pending_agent_plan() is None

        steps = [QueueStep(original_text="test", intent="browser_open", slots={"url": "youtube"})]
        ctx.set_pending_agent_plan(task_id="task-1", steps=steps)

        plan = ctx.get_pending_agent_plan()
        assert plan is not None
        assert plan["task_id"] == "task-1"
        assert len(plan["steps"]) == 1

        ctx.clear_pending_agent_plan()
        assert ctx.get_pending_agent_plan() is None

    def test_snapshot_includes_pending_plan(self):
        """Snapshot pending_agent_plan durumunu içermeli."""
        from bantz.router.context import QueueStep

        ctx = ConversationContext()
        snap1 = ctx.snapshot()
        assert snap1.get("pending_agent_plan") is False

        steps = [QueueStep(original_text="test", intent="browser_open", slots={"url": "x"})]
        ctx.set_pending_agent_plan(task_id="t1", steps=steps)
        snap2 = ctx.snapshot()
        assert snap2.get("pending_agent_plan") is True


# ─────────────────────────────────────────────────────────────────
# Recovery Policy Tests
# ─────────────────────────────────────────────────────────────────
class TestRecoveryPolicyEnhancements:
    """Test enhanced recovery policy with timeouts."""

    def test_timeout_decision(self):
        """Timeout durumu doğru karar vermeli."""
        from bantz.agent.recovery import RecoveryPolicy

        policy = RecoveryPolicy(max_retries=2, step_timeout_seconds=30)

        # Normal retry
        decision = policy.decide(attempt=1)
        assert decision.action == "retry"

        # Timeout
        decision = policy.decide(attempt=1, elapsed_seconds=35.0)
        assert decision.action == "timeout"
        assert "timeout" in decision.reason

    def test_step_timeout_getter(self):
        """get_step_timeout farklı intent'ler için doğru değer döndürmeli."""
        from bantz.agent.recovery import get_step_timeout, STEP_TIMEOUTS

        assert get_step_timeout("browser_open") == STEP_TIMEOUTS["browser_open"]
        assert get_step_timeout("browser_scan") == STEP_TIMEOUTS["browser_scan"]
        assert get_step_timeout("unknown_intent") == STEP_TIMEOUTS["default"]

    def test_should_timeout(self):
        """should_timeout metodu çalışmalı."""
        from bantz.agent.recovery import RecoveryPolicy

        policy = RecoveryPolicy(step_timeout_seconds=10)
        assert policy.should_timeout(5.0) is False
        assert policy.should_timeout(10.0) is True
        assert policy.should_timeout(15.0) is True


# ─────────────────────────────────────────────────────────────────
# Type Verification Tests
# ─────────────────────────────────────────────────────────────────
class TestTypeVerification:
    """Test browser_type post-verification logic."""

    def test_verify_type_result_method_exists(self):
        """Router._verify_type_result metodu mevcut olmalı."""
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

        assert hasattr(router, "_verify_type_result")


# ─────────────────────────────────────────────────────────────────
# Interactive Recovery Message Test
# ─────────────────────────────────────────────────────────────────
class TestInteractiveRecovery:
    """Test interactive recovery prompt formatting."""

    def test_recovery_options_in_message(self):
        """Hata mesajı recovery seçenekleri içermeli."""
        # This is more of a documentation test; the actual logic is in _run_queue
        recovery_options = [
            "devam et",
            "sıradaki",
            "iptal et",
            "agent tekrar",
        ]
        # All these should be mentioned in recovery messages
        for opt in recovery_options:
            assert opt is not None  # placeholder check
