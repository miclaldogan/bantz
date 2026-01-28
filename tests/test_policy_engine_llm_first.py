from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.policy.engine import PolicyEngine
from bantz.policy.risk_map import RiskMap
from bantz.policy.session_permits import InMemorySessionPermits


class FakeLLM:
    """Very small LLM stub for BrainLoop.

    Behavior:
    - If last user message contains Observation -> SAY
    - Else -> CALL_TOOL for the configured tool
    """

    def __init__(self, *, tool_name: str, params: dict[str, Any]):
        self.tool_name = tool_name
        self.params = params

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict[str, Any]:
        tail = messages[-1]["content"] if messages else ""
        if "Observation (tool sonucu):" in tail:
            return {"type": "SAY", "text": "Tamam efendim."}
        return {"type": "CALL_TOOL", "name": self.tool_name, "params": dict(self.params)}


def test_policy_engine_low_allows() -> None:
    p = PolicyEngine()
    d = p.check(session_id="s1", tool_name="echo", params={}, risk_level="LOW")
    assert d.allowed is True
    assert d.requires_confirmation is False


def test_policy_engine_high_requires_confirmation_every_time(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    p = PolicyEngine(audit_path=audit)

    d1 = p.check(session_id="s1", tool_name="danger", params={"x": 1}, risk_level="HIGH")
    d2 = p.check(session_id="s1", tool_name="danger", params={"x": 2}, risk_level="HIGH")

    assert d1.allowed is False and d1.requires_confirmation is True
    assert d2.allowed is False and d2.requires_confirmation is True

    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2


def test_policy_engine_med_remembers_once_per_session() -> None:
    permits = InMemorySessionPermits()
    p = PolicyEngine(permits=permits)

    d1 = p.check(session_id="s1", tool_name="write", params={}, risk_level="MED")
    assert d1.allowed is False and d1.requires_confirmation is True

    p.confirm(session_id="s1", tool_name="write", risk_level="MED")

    d2 = p.check(session_id="s1", tool_name="write", params={}, risk_level="MED")
    assert d2.allowed is True and d2.requires_confirmation is False

    # Different session should not be remembered.
    d3 = p.check(session_id="s2", tool_name="write", params={}, risk_level="MED")
    assert d3.allowed is False and d3.requires_confirmation is True


def test_brainloop_policy_blocks_tool_and_resumes_on_confirm(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def create_event(title: str) -> dict[str, Any]:
        calls.append({"title": title})
        return {"ok": True, "id": "evt_1"}

    tools = ToolRegistry()
    tools.register(
        Tool(
            name="calendar.create_event",
            description="Create a calendar event",
            parameters={
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
            function=create_event,
            risk_level="MED",
            requires_confirmation=True,
        )
    )

    audit = tmp_path / "policy.jsonl"
    p = PolicyEngine(audit_path=audit, risk_map=RiskMap({"calendar.create_event": "MED"}))

    llm = FakeLLM(tool_name="calendar.create_event", params={"title": "Koşu"})
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=3, debug=False))

    state: dict[str, Any] = {"session_id": "s1"}

    # First turn: should ask user for confirmation; tool must not run.
    r1 = loop.run(turn_input="Bu akşam koşu ekle", session_context={"user": "demo"}, policy=p, context=state)
    assert r1.kind == "ask_user"
    assert calls == []
    assert "_policy_pending_action" in state

    # Second turn: user confirms; tool runs once and loop finishes with SAY.
    r2 = loop.run(turn_input="evet", session_context={"user": "demo"}, policy=p, context=state)
    assert r2.kind == "say"
    assert len(calls) == 1
    assert "_policy_pending_action" not in state

    # Third turn: since MED confirmed in-session, no extra confirmation needed.
    r3 = loop.run(turn_input="Bir tane daha koşu ekle", session_context={"user": "demo"}, policy=p, context=state)
    assert r3.kind == "say"
    assert len(calls) == 2

    # Audit log should exist and be valid JSONL.
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 3
    for line in lines[:3]:
        json.loads(line)


def test_policy_audit_masks_sensitive_fields(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    p = PolicyEngine(audit_path=audit)

    _ = p.check(
        session_id="s1",
        tool_name="write",
        params={"token": "abc", "nested": {"password": "secret"}},
        risk_level="MED",
    )

    data = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
    assert data["params"]["token"] == "***"
    assert data["params"]["nested"]["password"] == "***"
