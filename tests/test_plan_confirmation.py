from __future__ import annotations

from bantz.agent.tools import ToolRegistry
from bantz.agent.tools import Tool
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.core.events import EventBus, EventType


class _FailingLLM:
    def complete_json(self, *, messages, schema_hint):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM should not be called in this test")


def test_pending_plandraft_accept_onayla() -> None:
    tools = ToolRegistry()
    bus = EventBus()

    seen: list[str] = []

    def on_any(ev):  # type: ignore[no-untyped-def]
        t = str(ev.event_type)
        if t in {EventType.ACK.value, EventType.QUESTION.value, EventType.RESULT.value}:
            seen.append(t)

    bus.subscribe_all(on_any)

    ctx = {"session_id": "t"}
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, event_bus=bus, config=BrainLoopConfig(max_steps=1, debug=False))

    r1 = loop.run(
        turn_input="bugün plan yap",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-30T00:00:00+03:00", "time_max": "2026-01-30T23:59:00+03:00"},
        },
        policy=None,
        context=ctx,
    )
    assert r1.kind == "say"

    joined = " > ".join(seen)
    assert joined.find(EventType.ACK.value) != -1
    assert joined.find(EventType.QUESTION.value) > joined.find(EventType.ACK.value)
    assert joined.find(EventType.RESULT.value) > joined.find(EventType.QUESTION.value)

    seen.clear()

    r2 = loop.run(
        turn_input="onayla",
        session_context={"deterministic_render": True},
        policy=None,
        context=ctx,
    )
    assert r2.kind == "ask_user"
    assert "1/0" in r2.text.lower() or "uygul" in r2.text.lower()


def test_pending_plandraft_cancel_iptal() -> None:
    tools = ToolRegistry()
    bus = EventBus()
    ctx = {"session_id": "t"}

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, event_bus=bus, config=BrainLoopConfig(max_steps=1, debug=False))
    r1 = loop.run(
        turn_input="yarın sabah plan yap",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "tomorrow_window": {"time_min": "2026-01-31T00:00:00+03:00", "time_max": "2026-01-31T23:59:00+03:00"},
        },
        policy=None,
        context=ctx,
    )
    assert r1.kind == "say"

    r2 = loop.run(
        turn_input="iptal",
        session_context={"deterministic_render": True},
        policy=None,
        context=ctx,
    )
    assert r2.kind == "say"
    assert "iptal" in r2.text.lower() or "vazge" in r2.text.lower()


def test_pending_plandraft_edit_updates_preview() -> None:
    tools = ToolRegistry()
    bus = EventBus()
    ctx = {"session_id": "t"}

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, event_bus=bus, config=BrainLoopConfig(max_steps=1, debug=False))

    r1 = loop.run(
        turn_input="bugün plan yap",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-30T00:00:00+03:00", "time_max": "2026-01-30T23:59:00+03:00"},
        },
        policy=None,
        context=ctx,
    )
    assert r1.kind == "say"

    r2 = loop.run(
        turn_input="şunu 30 dk yap",
        session_context={"deterministic_render": True},
        policy=None,
        context=ctx,
    )
    assert r2.kind == "say"
    assert "30 dk" in r2.text.lower()
    assert isinstance(r2.metadata, dict)

    trace = r2.metadata.get("trace")
    assert isinstance(trace, dict)
    slots = trace.get("slots")
    assert isinstance(slots, dict)
    assert slots.get("item_count") == 4


def test_plandraft_apply_state_machine_two_turns() -> None:
    tools = ToolRegistry()
    bus = EventBus()
    ctx: dict[str, object] = {"session_id": "t"}

    calls: list[dict[str, object]] = []

    def _stub_apply_plan_draft(**params):  # type: ignore[no-untyped-def]
        calls.append(dict(params))
        if bool(params.get("dry_run")):
            return {
                "ok": True,
                "dry_run": True,
                "created_count": 0,
                "events": [
                    {"summary": "A", "start": "2026-01-30T09:00:00+03:00", "end": "2026-01-30T09:30:00+03:00"},
                    {"summary": "B", "start": "2026-01-30T09:30:00+03:00", "end": "2026-01-30T10:00:00+03:00"},
                ],
                "warnings": [],
            }
        return {
            "ok": True,
            "dry_run": False,
            "created_count": 2,
            "events": [],
            "created": [{"ok": True, "id": "1"}, {"ok": True, "id": "2"}],
            "warnings": [],
        }

    tools.register(
        Tool(
            name="calendar.apply_plan_draft",
            description="test stub",
            parameters={
                "type": "object",
                "properties": {
                    "draft": {"type": "object"},
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                    "calendar_id": {"type": "string"},
                },
                "required": ["draft", "time_min", "time_max"],
            },
            requires_confirmation=True,
            function=_stub_apply_plan_draft,
        )
    )

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, event_bus=bus, config=BrainLoopConfig(max_steps=1, debug=False))

    # Turn 0: create pending plan draft + persisted window.
    r1 = loop.run(
        turn_input="bugün plan yap",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-30T00:00:00+03:00", "time_max": "2026-01-30T23:59:00+03:00"},
        },
        policy=None,
        context=ctx,
    )
    assert r1.kind == "say"
    assert isinstance(ctx.get("_planning_pending_plan_draft"), dict)

    # Turn A: accept -> dry-run preview + queued confirmation.
    r2 = loop.run(
        turn_input="onayla",
        session_context={"deterministic_render": True},
        policy=None,
        context=ctx,
    )
    assert r2.kind == "ask_user"
    assert "dry-run" in r2.text.lower()  # preview visible in returned text
    assert "1/0" in r2.text.lower() or "uygula" in r2.text.lower()

    # State assertions after Turn A
    assert ctx.get("_planning_pending_plan_draft") is None
    assert isinstance(ctx.get("_planning_confirmed_plan_draft"), dict)
    pending_action = ctx.get("_policy_pending_action")
    assert isinstance(pending_action, dict)
    action = pending_action.get("action")
    assert isinstance(action, dict)
    assert action.get("name") == "calendar.apply_plan_draft"
    params = action.get("params")
    assert isinstance(params, dict)
    assert params.get("dry_run") is False
    assert isinstance(params.get("draft"), dict)
    assert isinstance(params.get("time_min"), str) and params.get("time_min")
    assert isinstance(params.get("time_max"), str) and params.get("time_max")

    # Turn B: confirm -> real apply
    r3 = loop.run(
        turn_input="1",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=ctx,
    )
    assert r3.kind == "say"
    assert "2" in r3.text  # created_count rendered

    # Pending confirmation cleared; confirmed draft cleared after successful apply.
    assert ctx.get("_policy_pending_action") is None
    assert ctx.get("_planning_confirmed_plan_draft") is None

    # Tool call evidence: first dry-run, then real apply.
    assert len(calls) == 2
    assert bool(calls[0].get("dry_run")) is True
    assert bool(calls[1].get("dry_run")) is False
