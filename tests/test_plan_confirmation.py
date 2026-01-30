from __future__ import annotations

from bantz.agent.tools import ToolRegistry
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
    assert r2.kind == "say"
    assert "onay" in r2.text.lower()


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
