"""Automation verifier tests (Issue #853)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from bantz.automation.verifier import VerificationResult, Verifier, create_verifier


# ─── Minimal stub types so we don't import the real plan/executor ───

@dataclass
class _StubStep:
    id: str = "step-1"
    description: str = "Test step"
    action: str = "test_action"
    parameters: dict = field(default_factory=dict)


@dataclass
class _StubResult:
    success: bool = True
    result: Optional[str] = "ok"
    error: Optional[str] = None
    step_id: str = "step-1"


# ─────────────────────────────────────────────────────────────────
# VerificationResult dataclass
# ─────────────────────────────────────────────────────────────────

class TestVerificationResult:

    def test_defaults(self):
        vr = VerificationResult()
        assert vr.verified is False
        assert vr.confidence == 0.0
        assert vr.issues == []

    def test_to_dict(self):
        vr = VerificationResult(
            step_id="s1", verified=True, confidence=0.9, evidence="ok"
        )
        d = vr.to_dict()
        assert d["step_id"] == "s1"
        assert d["verified"] is True
        assert d["confidence"] == 0.9

    def test_with_issues(self):
        vr = VerificationResult(
            verified=False,
            issues=["timeout", "missing output"],
            suggestions=["retry"],
        )
        assert len(vr.issues) == 2
        assert "retry" in vr.suggestions


# ─────────────────────────────────────────────────────────────────
# Verifier.verify_step
# ─────────────────────────────────────────────────────────────────

class TestVerifyStep:

    @pytest.mark.asyncio
    async def test_successful_step(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=True, result="done")
        vr = await v.verify_step(step, result)
        assert vr.verified is True
        assert vr.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_successful_no_result(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=True, result=None)
        vr = await v.verify_step(step, result)
        assert vr.verified is True
        assert "no result" in (vr.evidence or "").lower() or vr.confidence > 0

    @pytest.mark.asyncio
    async def test_failed_step(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=False, error="timeout")
        vr = await v.verify_step(step, result)
        assert vr.verified is False
        assert "timeout" in (vr.evidence or "")

    @pytest.mark.asyncio
    async def test_failed_step_has_suggestions(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=False, error="connection refused")
        vr = await v.verify_step(step, result)
        assert len(vr.suggestions) > 0


# ─────────────────────────────────────────────────────────────────
# Verifier.verify_plan
# ─────────────────────────────────────────────────────────────────

class TestVerifyPlan:

    @pytest.mark.asyncio
    async def test_all_success(self):
        v = Verifier()

        @dataclass
        class Plan:
            id: str = "plan-1"

        results = [_StubResult(success=True) for _ in range(5)]
        vr = await v.verify_plan(Plan(), results)
        assert vr.verified is True
        assert "All" in (vr.evidence or "")

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        v = Verifier()

        @dataclass
        class Plan:
            id: str = "plan-1"

        results = [
            _StubResult(success=True),
            _StubResult(success=True),
            _StubResult(success=False, error="fail"),
        ]
        vr = await v.verify_plan(Plan(), results)
        # 2/3 = 67% < 70% threshold
        assert len(vr.issues) > 0

    @pytest.mark.asyncio
    async def test_empty_results(self):
        v = Verifier()

        @dataclass
        class Plan:
            id: str = "plan-1"

        vr = await v.verify_plan(Plan(), [])
        assert vr.verified is False


# ─────────────────────────────────────────────────────────────────
# Verifier.quick_verify
# ─────────────────────────────────────────────────────────────────

class TestQuickVerify:

    @pytest.mark.asyncio
    async def test_quick_verify_success(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=True, result="ok")
        assert await v.quick_verify(step, result) is True

    @pytest.mark.asyncio
    async def test_quick_verify_failure(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=False)
        assert await v.quick_verify(step, result) is False

    @pytest.mark.asyncio
    async def test_quick_verify_empty_result(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=True, result="")
        ok = await v.quick_verify(step, result)
        # "" is falsy → should return False
        assert ok is False

    @pytest.mark.asyncio
    async def test_quick_verify_none_result(self):
        v = Verifier()
        step = _StubStep()
        result = _StubResult(success=True, result=None)
        assert await v.quick_verify(step, result) is True


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────

class TestFactory:

    def test_create_verifier_no_llm(self):
        v = create_verifier()
        assert isinstance(v, Verifier)
        assert v._llm is None

    def test_create_verifier_with_llm(self):
        mock_llm = AsyncMock()
        v = create_verifier(llm_client=mock_llm)
        assert v._llm is mock_llm

    def test_verification_prompt(self):
        v = Verifier()
        step = _StubStep(description="Create file", action="file_create", parameters={"path": "x.py"})
        result = _StubResult(success=True, result="created")
        prompt = v.get_verification_prompt(step, result)
        assert "Create file" in prompt
        assert "file_create" in prompt
