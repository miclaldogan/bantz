"""Tests for issue #458 — Plan-Execute-Verify (PEV) loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bantz.agent.pev_loop import (
    AgentPlan,
    PEVConfig,
    PEVLoop,
    PlanStep,
    StepResult,
    VerifyResult,
    VerifyStatus,
)


# ── helpers ───────────────────────────────────────────────────────────

def _make_plan(
    goal: str = "test",
    steps: list | None = None,
    risk: str = "low",
) -> AgentPlan:
    if steps is None:
        steps = [
            PlanStep(index=1, description="Create event", tool_name="calendar.create",
                     args_template={"title": "Meeting"}),
            PlanStep(index=2, description="Send mail", tool_name="gmail.send",
                     args_template={"subject": "$prev_result.title"}),
        ]
    return AgentPlan(goal=goal, steps=steps, estimated_risk=risk)


def _success_executor(tool_name: str, args: dict) -> dict:
    """Always succeeds, returns args back."""
    return {"tool": tool_name, **args}


# ── TestPlanStep ──────────────────────────────────────────────────────

class TestPlanStep:
    def test_resolve_args_simple(self):
        step = PlanStep(index=1, description="d", tool_name="t",
                        args_template={"title": "hello"})
        assert step.resolve_args({}) == {"title": "hello"}

    def test_resolve_prev_result(self):
        step = PlanStep(index=2, description="d", tool_name="t",
                        args_template={"val": "$prev_result"})
        resolved = step.resolve_args({1: "output_1"})
        assert resolved["val"] == "output_1"

    def test_resolve_prev_result_attr(self):
        step = PlanStep(index=2, description="d", tool_name="t",
                        args_template={"title": "$prev_result.name"})
        resolved = step.resolve_args({1: {"name": "Test", "id": 42}})
        assert resolved["title"] == "Test"

    def test_resolve_step_n_result(self):
        step = PlanStep(index=3, description="d", tool_name="t",
                        args_template={"ref": "$step_1_result.id"})
        resolved = step.resolve_args({1: {"id": "abc"}, 2: "other"})
        assert resolved["ref"] == "abc"

    def test_resolve_missing_keeps_template(self):
        step = PlanStep(index=2, description="d", tool_name="t",
                        args_template={"val": "$step_99_result"})
        resolved = step.resolve_args({})
        assert resolved["val"] == "$step_99_result"

    def test_resolve_non_string_passthrough(self):
        step = PlanStep(index=1, description="d", tool_name="t",
                        args_template={"count": 5})
        assert step.resolve_args({}) == {"count": 5}


# ── TestAgentPlan ─────────────────────────────────────────────────────

class TestAgentPlan:
    def test_high_risk_requires_confirmation(self):
        plan = AgentPlan(goal="x", steps=[], estimated_risk="high")
        assert plan.requires_confirmation

    def test_five_plus_steps_requires_confirmation(self):
        steps = [PlanStep(index=i, description="d", tool_name="t") for i in range(5)]
        plan = AgentPlan(goal="x", steps=steps, estimated_risk="low")
        assert plan.requires_confirmation

    def test_low_risk_few_steps_no_confirmation(self):
        steps = [PlanStep(index=1, description="d", tool_name="t")]
        plan = AgentPlan(goal="x", steps=steps, estimated_risk="low")
        assert not plan.requires_confirmation


# ── TestPEVLoop: happy path ───────────────────────────────────────────

class TestPEVHappyPath:
    def test_two_step_plan(self):
        plan = _make_plan()
        loop = PEVLoop(_success_executor)
        verify, results = loop.run("test", plan=plan)

        assert verify.status == VerifyStatus.SUCCESS
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_template_substitution(self):
        plan = _make_plan()
        outputs = []

        def executor(tool_name, args):
            outputs.append(args)
            return {"title": "Created Meeting", "tool": tool_name}

        loop = PEVLoop(executor)
        loop.run("test", plan=plan)

        # Step 2 should have resolved $prev_result.title
        assert outputs[1]["subject"] == "Created Meeting"

    def test_single_step(self):
        plan = AgentPlan(
            goal="simple",
            steps=[PlanStep(index=1, description="do it", tool_name="sys.info")],
        )
        loop = PEVLoop(_success_executor)
        verify, results = loop.run("simple", plan=plan)
        assert verify.status == VerifyStatus.SUCCESS
        assert len(results) == 1


# ── TestPermissions ───────────────────────────────────────────────────

class TestPermissions:
    def test_deny_blocks_step(self):
        plan = _make_plan()
        loop = PEVLoop(
            _success_executor,
            permission_checker=lambda tool, desc: "deny",
        )
        verify, results = loop.run("test", plan=plan)
        assert all(not r.success for r in results)
        assert results[0].error == "permission_denied"

    def test_confirm_with_approval(self):
        plan = _make_plan()
        loop = PEVLoop(
            _success_executor,
            permission_checker=lambda tool, desc: "confirm",
            confirmation_requester=lambda summary: True,
        )
        verify, results = loop.run("test", plan=plan)
        assert all(r.success for r in results)

    def test_confirm_denied_by_user(self):
        plan = _make_plan()
        loop = PEVLoop(
            _success_executor,
            permission_checker=lambda tool, desc: "confirm",
            confirmation_requester=lambda summary: False,
        )
        verify, results = loop.run("test", plan=plan)
        assert results[0].error == "user_denied_step"

    def test_confirm_no_mechanism(self):
        plan = _make_plan()
        loop = PEVLoop(
            _success_executor,
            permission_checker=lambda tool, desc: "confirm",
        )
        verify, results = loop.run("test", plan=plan)
        assert results[0].error == "confirmation_required_but_unavailable"


# ── TestHighRiskConfirmation ──────────────────────────────────────────

class TestHighRiskConfirmation:
    def test_high_risk_rejected(self):
        plan = _make_plan(risk="high")
        loop = PEVLoop(_success_executor)
        verify, results = loop.run("test", plan=plan)
        assert verify.status == VerifyStatus.FAILED
        assert "rejected" in verify.explanation.lower()

    def test_high_risk_approved(self):
        plan = _make_plan(risk="high")
        loop = PEVLoop(
            _success_executor,
            confirmation_requester=lambda s: True,
        )
        verify, results = loop.run("test", plan=plan)
        assert verify.status == VerifyStatus.SUCCESS

    def test_five_plus_steps_require_confirmation(self):
        steps = [PlanStep(index=i, description=f"step {i}", tool_name="t") for i in range(6)]
        plan = AgentPlan(goal="big", steps=steps, estimated_risk="low")
        assert plan.requires_confirmation
        loop = PEVLoop(
            _success_executor,
            confirmation_requester=lambda s: True,
        )
        verify, results = loop.run("big", plan=plan)
        assert verify.status == VerifyStatus.SUCCESS


# ── TestDependencies ──────────────────────────────────────────────────

class TestDependencies:
    def test_unmet_dependency(self):
        steps = [
            PlanStep(index=1, description="a", tool_name="t", depends_on=[99]),
        ]
        plan = AgentPlan(goal="dep", steps=steps)
        loop = PEVLoop(_success_executor)
        verify, results = loop.run("dep", plan=plan)
        assert not results[0].success
        assert "unmet" in results[0].error

    def test_met_dependency(self):
        steps = [
            PlanStep(index=1, description="first", tool_name="t"),
            PlanStep(index=2, description="second", tool_name="t", depends_on=[1]),
        ]
        plan = AgentPlan(goal="dep", steps=steps)
        loop = PEVLoop(_success_executor)
        verify, results = loop.run("dep", plan=plan)
        assert all(r.success for r in results)


# ── TestStepFailure + Replan ──────────────────────────────────────────

class TestStepFailure:
    def test_step_failure_partial(self):
        def flaky_executor(tool, args):
            if tool == "gmail.send":
                raise RuntimeError("SMTP error")
            return {"ok": True}

        plan = _make_plan()
        loop = PEVLoop(flaky_executor)
        verify, results = loop.run("test", plan=plan)
        assert verify.status == VerifyStatus.PARTIAL
        assert 1 in verify.failed_steps or 2 in verify.failed_steps

    def test_replan_on_failure(self):
        call_count = {"plan": 0, "exec": 0}

        def gen_plan(goal, tools):
            call_count["plan"] += 1
            return AgentPlan(
                goal=goal,
                steps=[PlanStep(index=1, description="retry", tool_name="t")],
            )

        def executor(tool, args):
            call_count["exec"] += 1
            if call_count["exec"] <= 1:
                raise RuntimeError("first attempt fails")
            return "ok"

        loop = PEVLoop(
            executor,
            plan_generator=gen_plan,
            config=PEVConfig(max_replans=1),
        )

        # First plan fails → triggers replan → second succeeds
        verify, results = loop.run("test")
        # The replan should have been attempted
        assert call_count["plan"] >= 2

    def test_no_infinite_replan(self):
        """max_replans=1 should prevent more than one replan."""
        plan_calls = {"count": 0}

        def gen_plan(goal, tools):
            plan_calls["count"] += 1
            return AgentPlan(
                goal=goal,
                steps=[PlanStep(index=1, description="fail", tool_name="t")],
            )

        def always_fail(tool, args):
            raise RuntimeError("always fails")

        loop = PEVLoop(
            always_fail,
            plan_generator=gen_plan,
            config=PEVConfig(max_replans=1),
        )
        verify, results = loop.run("test")
        # 1 initial plan + 1 replan = 2
        assert plan_calls["count"] == 2


# ── TestMaxSteps ──────────────────────────────────────────────────────

class TestMaxSteps:
    def test_plan_trimmed(self):
        steps = [PlanStep(index=i, description=f"s{i}", tool_name="t") for i in range(15)]
        plan = AgentPlan(goal="big", steps=steps, estimated_risk="low",
                         requires_confirmation=False)
        # Override the auto-flag from __post_init__
        object.__setattr__(plan, "requires_confirmation", False)
        loop = PEVLoop(_success_executor, config=PEVConfig(max_steps=5))
        verify, results = loop.run("big", plan=plan)
        assert len(results) == 5


# ── TestNoplan ────────────────────────────────────────────────────────

class TestNoPlan:
    def test_no_plan_no_generator_raises(self):
        loop = PEVLoop(_success_executor)
        with pytest.raises(ValueError, match="No plan"):
            loop.run("test")

    def test_plan_generator_called(self):
        def gen(goal, tools):
            return AgentPlan(
                goal=goal,
                steps=[PlanStep(index=1, description="auto", tool_name="t")],
            )

        loop = PEVLoop(_success_executor, plan_generator=gen)
        verify, results = loop.run("test")
        assert verify.status == VerifyStatus.SUCCESS


# ── TestDefaultVerifier ───────────────────────────────────────────────

class TestDefaultVerifier:
    def test_empty_results(self):
        loop = PEVLoop(_success_executor)
        verify = loop._default_verifier("g", [])
        assert verify.status == VerifyStatus.FAILED

    def test_all_pass(self):
        results = [StepResult(step_index=1, success=True)]
        verify = PEVLoop._default_verifier("g", results)
        assert verify.status == VerifyStatus.SUCCESS

    def test_all_fail(self):
        results = [StepResult(step_index=1, success=False, error="x")]
        verify = PEVLoop._default_verifier("g", results)
        assert verify.status == VerifyStatus.FAILED

    def test_partial(self):
        results = [
            StepResult(step_index=1, success=True),
            StepResult(step_index=2, success=False, error="x"),
        ]
        verify = PEVLoop._default_verifier("g", results)
        assert verify.status == VerifyStatus.PARTIAL
