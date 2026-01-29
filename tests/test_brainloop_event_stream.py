from __future__ import annotations

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.core.events import EventBus, EventType


class _FailingLLM:
    def complete_json(self, *, messages, schema_hint):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM should not be called in this test")


def test_event_stream_for_deterministic_list_events_is_ordered() -> None:
    """Issue #103: ACK/PROGRESS/FOUND/SUMMARIZING/RESULT order for CLI."""

    tools = ToolRegistry()

    def list_events(**params):
        assert "time_min" in params
        assert "time_max" in params
        return {"ok": True, "count": 0, "events": []}

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    bus = EventBus()
    seen: list[str] = []

    def on_any(ev):  # type: ignore[no-untyped-def]
        t = str(ev.event_type)
        if t in {
            EventType.ACK.value,
            EventType.PROGRESS.value,
            EventType.FOUND.value,
            EventType.SUMMARIZING.value,
            EventType.RESULT.value,
        }:
            seen.append(t)

    bus.subscribe_all(on_any)

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, event_bus=bus, config=BrainLoopConfig(max_steps=1, debug=False))
    res = loop.run(
        turn_input="Bu akşam planım var mı?",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context={"session_id": "t"},
    )

    assert res.kind == "say"

    # Must be ordered (duplicates allowed, but the first occurrence order must hold)
    joined = " > ".join(seen)
    assert joined.find(EventType.ACK.value) != -1
    assert joined.find(EventType.PROGRESS.value) > joined.find(EventType.ACK.value)
    assert joined.find(EventType.FOUND.value) > joined.find(EventType.PROGRESS.value)
    assert joined.find(EventType.SUMMARIZING.value) > joined.find(EventType.FOUND.value)
    assert joined.find(EventType.RESULT.value) > joined.find(EventType.SUMMARIZING.value)
