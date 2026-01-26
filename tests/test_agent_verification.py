from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.types import RouterResult


class VerifyRouter(Router):
    def __init__(self, policy: Policy, logger: JsonlLogger):
        super().__init__(policy=policy, logger=logger)
        self.calls: list[str] = []
        self.info_ok = True

    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:  # type: ignore[override]
        self.calls.append(str(intent))

        if intent == "browser_click":
            return RouterResult(ok=True, intent="browser_click", user_text="click ok")

        if intent == "browser_info":
            if self.info_ok:
                return RouterResult(ok=True, intent="browser_info", user_text="Sayfa: X\nURL: https://example.com")
            return RouterResult(ok=False, intent="browser_info", user_text="Extension bağlı değil")

        return RouterResult(ok=True, intent=intent, user_text="ok")


def _init_agent_record(router: Router, task_id: str) -> None:
    rec = {
        "id": task_id,
        "request": "x",
        "state": "running",
        "steps": [{"description": "click", "action": "browser_click", "params": {"index": 1}, "status": "pending"}],
    }
    router._agent_history.append(rec)
    router._agent_history_by_id[task_id] = rec


def test_agent_verification_records_info_success(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = VerifyRouter(policy=policy, logger=logger)

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1")

    ctx.set_queue([QueueStep(original_text="click", intent="browser_click", slots={"index": 1})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True

    # pre-signature info -> preflight scan -> click -> post-signature info
    assert router.calls == ["browser_info", "browser_scan", "browser_click", "browser_info"]

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0["status"] == "completed"
    assert s0["verification_attempted"] is True
    assert s0["verification_ok"] is True
    # Click often doesn't change title/url; treat as a warning.
    assert s0.get("verification_warn") in {True, None}
    assert "URL:" in s0["verification_summary"]


def test_agent_verification_does_not_block_on_failure(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = VerifyRouter(policy=policy, logger=logger)
    router.info_ok = False

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1")

    ctx.set_queue([QueueStep(original_text="click", intent="browser_click", slots={"index": 1})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True

    # Still runs verification call
    assert router.calls == ["browser_info", "browser_scan", "browser_click", "browser_info"]

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0["status"] == "completed"
    assert s0["verification_attempted"] is True
    assert s0["verification_ok"] is False
