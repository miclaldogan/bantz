from __future__ import annotations

from bantz.logs.logger import JsonlLogger
from bantz.router.context import ConversationContext, QueueStep
from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.types import RouterResult


class SigRouter(Router):
    def __init__(self, policy: Policy, logger: JsonlLogger):
        super().__init__(policy=policy, logger=logger)
        self.calls: list[tuple[str, dict]] = []
        self._phase = 0
        self._open_ok = True
        self._info_texts: list[str] = []

    def _dispatch(self, *, intent: str, slots: dict, ctx: ConversationContext, in_queue: bool) -> RouterResult:  # type: ignore[override]
        self.calls.append((str(intent), dict(slots)))

        if intent == "browser_info":
            # Return successive info texts
            idx = min(self._phase, max(0, len(self._info_texts) - 1))
            txt = self._info_texts[idx] if self._info_texts else "Sayfa: A\nURL: https://a"
            self._phase += 1
            return RouterResult(ok=True, intent="browser_info", user_text=txt)

        if intent == "browser_open":
            return RouterResult(ok=self._open_ok, intent="browser_open", user_text="opened")

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


def test_signature_change_detected_no_pause(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = SigRouter(policy=policy, logger=logger)

    # pre differs from post
    router._info_texts = [
        "Sayfa: A\nURL: https://a",
        "Sayfa: B\nURL: https://b",
    ]

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1", "open", "browser_open", {"url": "https://b"})
    ctx.set_queue([QueueStep(original_text="open", intent="browser_open", slots={"url": "https://b"})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is True
    assert ctx.queue_paused is False

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0["verification_attempted"] is True
    assert s0["verification_ok"] is True
    assert s0.get("signature_changed") is True


def test_signature_no_change_navigation_pauses(tmp_path):
    policy = Policy.from_json_file("config/policy.json")
    logger = JsonlLogger(path=str(tmp_path / "t.jsonl"))
    router = SigRouter(policy=policy, logger=logger)

    # pre == post == post2, should pause after wait retry
    router._info_texts = [
        "Sayfa: A\nURL: https://a",
        "Sayfa: A\nURL: https://a",
        "Sayfa: A\nURL: https://a",
    ]

    ctx = ConversationContext(timeout_seconds=120)
    _init_agent_record(router, "agent-1", "open", "browser_open", {"url": "https://a"})
    ctx.set_queue([QueueStep(original_text="open", intent="browser_open", slots={"url": "https://a"})], source="agent", task_id="agent-1")

    res = router._run_queue(ctx, ctx.snapshot(), "agent: x")
    assert res.ok is False
    assert ctx.queue_paused is True

    s0 = router._agent_history_by_id["agent-1"]["steps"][0]
    assert s0["verification_attempted"] is True
    assert s0["verification_ok"] is False
    assert s0.get("verification_reason") == "no_change_detected"
