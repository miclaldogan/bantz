from __future__ import annotations

from bantz.agent.tools import ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.core.events import EventBus, EventType


class _FailingLLM:
    def complete_json(self, *, messages, schema_hint):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM should not be called in this test")


def _run_once(prompt: str) -> tuple[list[str], dict, str]:
    tools = ToolRegistry()
    bus = EventBus()

    seen: list[str] = []

    def on_any(ev):  # type: ignore[no-untyped-def]
        t = str(ev.event_type)
        if t in {EventType.ACK.value, EventType.PROGRESS.value, EventType.RESULT.value}:
            seen.append(t)

    bus.subscribe_all(on_any)

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, event_bus=bus, config=BrainLoopConfig(max_steps=1, debug=False))
    res = loop.run(
        turn_input=prompt,
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-29T00:00:00+03:00", "time_max": "2026-01-29T23:59:00+03:00"},
            "tomorrow_window": {"time_min": "2026-01-30T00:00:00+03:00", "time_max": "2026-01-30T23:59:00+03:00"},
            "morning_tomorrow_window": {"time_min": "2026-01-30T07:00:00+03:00", "time_max": "2026-01-30T12:00:00+03:00"},
        },
        policy=None,
        context={"session_id": "t"},
    )

    assert res.kind == "say"
    assert isinstance(res.metadata, dict)
    return seen, res.metadata, str(res.text)


def test_plandraft_today_prompt_emits_events_and_trace() -> None:
    seen, meta, text = _run_once("bugün plan yap")

    joined = " > ".join(seen)
    assert joined.find(EventType.ACK.value) != -1
    assert joined.find(EventType.PROGRESS.value) > joined.find(EventType.ACK.value)
    assert joined.find(EventType.RESULT.value) > joined.find(EventType.PROGRESS.value)

    trace = meta.get("trace")
    assert isinstance(trace, dict)
    slots = trace.get("slots")
    assert isinstance(slots, dict)
    assert slots.get("plan_window") == "today"
    assert slots.get("item_count") == 4

    assert meta.get("plan_window") == "today"
    assert meta.get("item_count") == 4
    assert "Plan taslağı" in text


def test_plandraft_tomorrow_morning_prompt_emits_events_and_trace() -> None:
    seen, meta, text = _run_once("yarın sabah plan yap")

    trace = meta.get("trace")
    assert isinstance(trace, dict)
    slots = trace.get("slots")
    assert isinstance(slots, dict)
    assert slots.get("plan_window") == "tomorrow_morning"
    assert slots.get("item_count") == 4

    assert meta.get("plan_window") == "tomorrow_morning"
    assert meta.get("item_count") == 4
    assert "yarın" in text.lower()
