from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.types import RouterResult


class TextResolveRouter(Router):
    def __init__(self, policy: Policy, logger: JsonlLogger):
        super().__init__(policy=policy, logger=logger)
        self.calls: list[tuple[str, dict]] = []
        self.scan_elements: list[dict] = []

    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:  # type: ignore[override]
        self.calls.append((str(intent), dict(slots)))

        if intent == "browser_info":
            return RouterResult(ok=True, intent="browser_info", user_text="Sayfa: A\nURL: https://a")

        if intent == "browser_scan":
            return RouterResult(ok=True, intent="browser_scan", user_text="scan ok", data={"scan": {"elements": list(self.scan_elements)}})

        if intent == "browser_click":
            # emulate successful click
            if "index" in slots:
                return RouterResult(ok=True, intent="browser_click", user_text=f"clicked index={slots['index']}")
            return RouterResult(ok=True, intent="browser_click", user_text="clicked")

        if intent == "browser_wait":
            return RouterResult(ok=True, intent="browser_wait", user_text="waited")

        return RouterResult(ok=True, intent=intent, user_text="ok")


def _init_agent_record(router: Router, task_id: str) -> None:
    rec = {
        "id": task_id,
        "request": "x",
        "state": "running",
        "steps": [{"description": "click", "action": "browser_click", "params": {"text": "Search"}, "status": "pending"}],
    }
    router._agent_history.append(rec)
    router._agent_history_by_id[task_id] = rec


def test_preflight_resolves_text_to_index_and_rewrites_slots(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = TextResolveRouter(policy=policy, logger=logger)

    router.scan_elements = [
        {"index": 1, "text": "Search videos"},
        {"index": 2, "text": "Search"},
        {"index": 3, "text": "Search results"},
    ]

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1")

    ctx.set_queue([QueueStep(original_text="click", intent="browser_click", slots={"text": "Search"})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True

    # pre_sig info -> preflight scan -> click(index) -> post_sig info
    assert [c[0] for c in router.calls[:4]] == ["browser_info", "browser_scan", "browser_click", "browser_info"]

    click_intent, click_slots = router.calls[2]
    assert click_intent == "browser_click"
    assert click_slots.get("index") == 2
    assert "text" not in click_slots

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0.get("resolved_index") == 2
    assert s0.get("resolved_text") == "Search"
