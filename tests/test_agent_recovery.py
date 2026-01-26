from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.types import RouterResult


class RecoveryRouter(Router):
    def __init__(self, policy: Policy, logger: JsonlLogger):
        super().__init__(policy=policy, logger=logger)
        self.calls: list[tuple[str, dict]] = []
        self._click_attempts = 0
        self._retry_always_fails = False

    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:  # type: ignore[override]
        self.calls.append((str(intent), dict(slots)))

        if intent == "browser_scan":
            return RouterResult(ok=True, intent="browser_scan", user_text="scan ok")

        if intent == "browser_click":
            self._click_attempts += 1
            if self._click_attempts == 1:
                return RouterResult(ok=False, intent="browser_click", user_text="click failed")
            if self._retry_always_fails:
                return RouterResult(ok=False, intent="browser_click", user_text="click retry failed")
            return RouterResult(ok=True, intent="browser_click", user_text="click ok")

        return RouterResult(ok=True, intent=intent, user_text="ok")


def _init_agent_record(router: Router, task_id: str, step_desc: str, action: str, params: dict) -> None:
    rec = {
        "id": task_id,
        "request": "x",
        "state": "running",
        "steps": [
            {
                "description": step_desc,
                "action": action,
                "params": dict(params),
                "status": "pending",
            }
        ],
    }
    router._agent_history.append(rec)
    router._agent_history_by_id[task_id] = rec


def test_agent_recovery_scan_retry_success(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = RecoveryRouter(policy=policy, logger=logger)

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1", "click something", "browser_click", {"index": 1})

    ctx.set_queue([QueueStep(original_text="click something", intent="browser_click", slots={"index": 1})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True
    assert ctx.queue_active() is False

    # pre-signature info -> preflight scan -> click (fail) -> recovery scan -> click (ok) -> post-signature info
    assert [c[0] for c in router.calls[:6]] == [
        "browser_info",
        "browser_scan",
        "browser_click",
        "browser_scan",
        "browser_click",
        "browser_info",
    ]

    rec = router._agent_history_by_id["agent-1"]
    s0 = rec["steps"][0]
    assert s0["status"] == "completed"
    assert s0["attempts"] == 2
    assert s0["recovered"] is True
    assert s0["recovery_strategy"] == "scan_retry"


def test_agent_recovery_scan_retry_failure_pauses(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = RecoveryRouter(policy=policy, logger=logger)
    router._retry_always_fails = True

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1", "click something", "browser_click", {"index": 1})

    ctx.set_queue([QueueStep(original_text="click something", intent="browser_click", slots={"index": 1})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is False
    assert ctx.queue_paused is True

    # pre-signature info -> preflight scan -> click (fail) -> recovery scan -> click (fail)
    assert [c[0] for c in router.calls[:5]] == ["browser_info", "browser_scan", "browser_click", "browser_scan", "browser_click"]

    rec = router._agent_history_by_id["agent-1"]
    s0 = rec["steps"][0]
    assert s0["status"] == "failed"
    assert s0["recovery_attempted"] is True
    assert s0["recovered"] is False
    assert s0["recovery_result"] == "retry_failed"
