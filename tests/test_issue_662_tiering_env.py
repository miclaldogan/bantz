# SPDX-License-Identifier: MIT
"""Issue #662: Tiering env normalization, deterministic fallback, trace updates."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.agent.tools import ToolRegistry


class _SimpleLLM:
    def __init__(self, reply: str = "Efendim, tamam."):
        self.reply = reply
        self.model_name = "Qwen/Qwen2.5-3B-Instruct-AWQ"
        self.backend_name = "vllm"

    def complete_text(self, *, prompt: str, **_):
        return self.reply


def _make_output(**overrides) -> OrchestratorOutput:
    defaults = dict(
        route="smalltalk",
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=[],
        assistant_reply="",
        raw_output={},
    )
    defaults.update(overrides)
    return OrchestratorOutput(**defaults)


def test_legacy_env_warning(caplog, monkeypatch):
    """Legacy tier env vars should emit a deprecation warning."""
    monkeypatch.setenv("BANTZ_TIERED_MODE", "1")
    monkeypatch.delenv("BANTZ_TIER_MODE", raising=False)

    from bantz.llm.tier_env import get_tier_mode_enabled

    caplog.clear()
    _ = get_tier_mode_enabled()

    warnings = [r for r in caplog.records if "legacy env var" in r.message]
    assert warnings


def test_trace_includes_tier_decision(monkeypatch):
    """Each turn should record tier_decision in the trace."""
    llm = _SimpleLLM()

    orch = Mock()
    orch._llm = llm  # prevent Mock auto-attribute leaking into pipeline
    orch.route.return_value = _make_output()
    # Prevent Mock auto-attributes from leaking into route recovery logic
    orch._detect_route_from_input.return_value = "smalltalk"
    orch._resolve_tool_from_intent.return_value = None
    orch._is_anaphoric_followup.return_value = False
    tools = ToolRegistry()

    loop = OrchestratorLoop(
        orchestrator=orch,
        tools=tools,
        config=OrchestratorConfig(enable_safety_guard=False, enable_preroute=False),
        finalizer_llm=llm,
    )

    state = OrchestratorState()
    loop.run_full_cycle("Merhaba", state=state)

    tier_decision = state.trace.get("tier_decision")
    assert isinstance(tier_decision, dict)
    assert "router" in tier_decision
    assert "finalizer" in tier_decision
    assert "reason" in tier_decision


def test_quality_requested_but_falls_back_to_fast(monkeypatch):
    """QUALITY forced with 3B-only finalizer should show 3b_fallback."""
    monkeypatch.setenv("BANTZ_TIER_FORCE", "quality")

    llm = _SimpleLLM()
    orch = Mock()
    orch._llm = llm
    orch.route.return_value = _make_output(
        route="system",
        calendar_intent="none",
    )

    loop = OrchestratorLoop(
        orchestrator=orch,
        tools=ToolRegistry(),
        config=OrchestratorConfig(enable_safety_guard=False, enable_preroute=False),
        finalizer_llm=llm,
    )

    state = OrchestratorState()
    loop.run_full_cycle("Sistem durumu nedir?", state=state)

    tier_decision = state.trace.get("tier_decision") or {}
    assert tier_decision.get("finalizer") == "3b_fallback"


def test_system_status_includes_tiering():
    """/status should include tiering section."""
    from bantz.tools.system_tools import system_status

    status = system_status()
    assert "tiering" in status
    if status["tiering"] is not None:
        assert "enabled" in status["tiering"]
        assert "forced" in status["tiering"]
        assert "finalizer_forced" in status["tiering"]
