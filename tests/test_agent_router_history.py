from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext
from bantz.router.engine import Router
from bantz.router.policy import Policy


def test_agent_history_empty(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = Router(policy=policy, logger=logger)
    ctx = ConversationContext(timeout_seconds=120)

    res = router.handle("agent geçmişi", ctx)
    assert res.ok is True
    assert "Henüz agent" in res.user_text


def test_agent_history_shows_statuses(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = Router(policy=policy, logger=logger)
    ctx = ConversationContext(timeout_seconds=120)

    router._agent_history.append(
        {
            "id": "agent-1",
            "request": "x",
            "state": "completed",
            "steps": [
                {"description": "open youtube", "status": "completed"},
                {"description": "search coldplay", "status": "skipped"},
            ],
        }
    )

    res = router.handle("agent history", ctx)
    assert res.ok is True
    assert "durum: completed" in res.user_text
    assert "[completed]" in res.user_text
    assert "[skipped]" in res.user_text
