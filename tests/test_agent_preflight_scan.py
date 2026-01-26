from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.types import RouterResult


class PreflightRouter(Router):
    def __init__(self, policy: Policy, logger: JsonlLogger):
        super().__init__(policy=policy, logger=logger)
        self.calls: list[str] = []
        self.scan_elements: list[dict] = []

    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:  # type: ignore[override]
        self.calls.append(str(intent))

        if intent == "browser_info":
            return RouterResult(ok=True, intent="browser_info", user_text="Sayfa: A\nURL: https://a")

        if intent == "browser_scan":
            return RouterResult(ok=True, intent="browser_scan", user_text="scan ok", data={"scan": {"elements": list(self.scan_elements)}})

        if intent == "browser_click":
            return RouterResult(ok=True, intent="browser_click", user_text="clicked")

        if intent == "browser_wait":
            return RouterResult(ok=True, intent="browser_wait", user_text="waited")

        return RouterResult(ok=True, intent=intent, user_text="ok")


def _init_agent_record(router: Router, task_id: str, desc: str, action: str, params: dict) -> None:
    rec = {
        "id": task_id,
        "request": "x",
        "state": "running",
        "steps": [{"description": desc, "action": action, "params": dict(params), "status": "pending"}],
    }
    router._agent_history.append(rec)
    router._agent_history_by_id[task_id] = rec


def test_agent_preflight_missing_index_pauses(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = PreflightRouter(policy=policy, logger=logger)

    # scan returns indexes 1..2, but step asks for 9
    router.scan_elements = [
        {"index": 1, "text": "Home"},
        {"index": 2, "text": "Search"},
    ]

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1", "click", "browser_click", {"index": 9})

    ctx.set_queue([QueueStep(original_text="click", intent="browser_click", slots={"index": 9})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is False
    assert ctx.queue_paused is True

    # pre_sig info -> preflight scan (pause before click)
    assert router.calls[:2] == ["browser_info", "browser_scan"]
    assert "index" in res.user_text.lower()

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0["status"] == "failed"
    assert s0["preflight_attempted"] is True
    assert s0["preflight_elements"] == 2


def test_agent_preflight_valid_index_allows_click(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = PreflightRouter(policy=policy, logger=logger)

    router.scan_elements = [
        {"index": 1, "text": "Home"},
        {"index": 2, "text": "Search"},
    ]

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1", "click", "browser_click", {"index": 2})

    ctx.set_queue([QueueStep(original_text="click", intent="browser_click", slots={"index": 2})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True

    # pre_sig info -> preflight scan -> click -> post_sig info
    assert router.calls[:4] == ["browser_info", "browser_scan", "browser_click", "browser_info"]

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0["status"] == "completed"
    assert s0["preflight_attempted"] is True
    assert s0["preflight_elements"] == 2
