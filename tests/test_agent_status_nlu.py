from __future__ import annotations

from bantz.router.nlu import parse_intent


def test_agent_status_intent():
    p = parse_intent("agent durum")
    assert p.intent == "agent_status"


def test_agent_history_with_n():
    p = parse_intent("son 3 agent")
    assert p.intent == "agent_history"
    assert p.slots.get("n") == 3
