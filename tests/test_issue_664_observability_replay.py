"""Tests for Issue #664 — Observability & Replay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from bantz.brain import trace_exporter


@dataclass
class _DummyOutput:
    route: str = "calendar"
    calendar_intent: str = "query"
    confidence: float = 0.9
    assistant_reply: str = "OK"


def test_build_turn_trace_includes_tier_decision_default() -> None:
    trace = trace_exporter.build_turn_trace(
        turn_id=1,
        user_input="test",
        output=_DummyOutput(),
        tool_results=[],
        state_trace={},
        total_elapsed_ms=123,
        timestamp="2026-02-10T10:00:00",
    )
    assert trace["tier_decision"] == {"router": "unknown", "finalizer": "unknown", "reason": "unknown"}
    assert trace["route"] == "calendar"
    assert trace["intent"] == "query"


def test_write_turn_trace_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trace_exporter, "TRACE_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    trace = {
        "turn_id": 2,
        "timestamp": "2026-02-10T10:01:00",
        "user_input": "hello",
        "route": "smalltalk",
        "intent": "greeting",
        "confidence": 0.95,
        "tier_decision": {"router": "3b", "finalizer": "3b", "reason": "simple"},
        "tools": [],
        "finalizer_strategy": "fast",
        "assistant_reply": "Merhaba",
        "total_elapsed_ms": 50,
    }
    path = trace_exporter.write_turn_trace(trace)
    assert path.exists()
    assert path.read_text(encoding="utf-8")


def test_build_tool_dag_contains_routes_and_tools() -> None:
    dag = trace_exporter.build_tool_dag()
    nodes = {n["id"] for n in dag.get("nodes", [])}
    edges = dag.get("edges", [])

    assert "route:calendar" in nodes
    assert "route:gmail" in nodes
    assert "route:system" in nodes

    # Ensure at least one tool node exists
    assert any(n.startswith("tool:") for n in nodes)
    # Ensure route->tool edges exist
    assert any(e.get("type") == "route_tool" for e in edges)


def test_replay_golden_traces_echo() -> None:
    result = trace_exporter.replay_golden_traces()
    assert result["failed"] == 0
    assert result["total"] == result["passed"]


def test_compare_traces_detects_route_mismatch() -> None:
    expected = {"route": "calendar", "tools": [{"name": "calendar.list_events"}]}
    actual = {"route": "gmail", "tools": [{"name": "calendar.list_events"}]}
    diff = trace_exporter.compare_traces(expected, actual)
    assert "route" in diff
