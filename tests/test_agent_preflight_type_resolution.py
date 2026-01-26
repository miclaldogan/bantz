from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.types import RouterResult


class DummyAllowPolicy:
    def decide(self, *, text: str, intent: str, confirmed: bool = False, click_target: str | None = None):  # noqa: ANN001
        return "allow", "test_allow"


class TypeResolveRouter(Router):
    def __init__(self, policy: Policy, logger: JsonlLogger):
        super().__init__(policy=policy, logger=logger)
        # Force allow so queue doesn't stop on confirm for browser_type
        self._policy = DummyAllowPolicy()  # type: ignore[assignment]
        self.calls: list[tuple[str, dict]] = []
        self.scan_elements: list[dict] = []

    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:  # type: ignore[override]
        self.calls.append((str(intent), dict(slots)))

        if intent == "browser_info":
            return RouterResult(ok=True, intent="browser_info", user_text="Sayfa: A\nURL: https://a")

        if intent == "browser_scan":
            return RouterResult(ok=True, intent="browser_scan", user_text="scan ok", data={"scan": {"elements": list(self.scan_elements)}})

        if intent == "browser_type":
            # succeed if index exists
            return RouterResult(ok=True, intent="browser_type", user_text=f"typed index={slots.get('index')}")

        if intent == "browser_wait":
            return RouterResult(ok=True, intent="browser_wait", user_text="waited")

        return RouterResult(ok=True, intent=intent, user_text="ok")


def _init_agent_record(router: Router, task_id: str) -> None:
    rec = {
        "id": task_id,
        "request": "x",
        "state": "running",
        "steps": [{"description": "type", "action": "browser_type", "params": {"text": "coldplay"}, "status": "pending"}],
    }
    router._agent_history.append(rec)
    router._agent_history_by_id[task_id] = rec


def test_preflight_resolves_type_target_to_index(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = TypeResolveRouter(policy=policy, logger=logger)

    # Include a search input; should pick index=2
    router.scan_elements = [
        {"index": 1, "tag": "div", "role": "button", "text": "Search"},
        {"index": 2, "tag": "input", "role": "textbox", "inputType": "search", "text": "Search"},
        {"index": 3, "tag": "input", "role": "textbox", "inputType": "text", "text": "Email"},
    ]

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1")

    ctx.set_queue([QueueStep(original_text="type", intent="browser_type", slots={"text": "coldplay"})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True

    # pre_sig info -> preflight scan -> type(index) -> post_sig info
    assert [c[0] for c in router.calls[:4]] == ["browser_info", "browser_scan", "browser_type", "browser_info"]
    assert router.calls[2][1].get("index") == 2

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0.get("resolved_index") == 2
    assert s0.get("resolved_type_target") is True
