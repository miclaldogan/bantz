from __future__ import annotations

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig


class _FailingLLM:
    def complete_json(self, *, messages, schema_hint):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM should not be called in this test")


class _QueueLLM:
    def __init__(self, outputs: list[dict]):
        self.outputs = list(outputs)
        self.calls = 0

    def complete_json(self, *, messages, schema_hint):  # type: ignore[no-untyped-def]
        self.calls += 1
        if not self.outputs:
            return {"type": "FAIL", "error": "no_more_outputs"}
        return self.outputs.pop(0)


def test_smalltalk_routes_to_scripted_menu_and_bypasses_llm_and_tools() -> None:
    tools = ToolRegistry()

    def should_never_run(**params):
        raise AssertionError("tool should not execute")

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=should_never_run,
        )
    )

    llm = _QueueLLM(outputs=[{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="uykuluyum okula gitmek istemiyorum",
        session_context={"deterministic_render": True},
        policy=None,
        context={"session_id": "t"},
    )

    assert llm.calls == 1

    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "smalltalk_stage1"
    assert res.metadata.get("state") == "PENDING_CHOICE"
    opts = res.metadata.get("options")
    assert isinstance(opts, dict)
    assert set(opts.keys()) >= {"0", "1", "2"}


def test_unknown_routes_to_domain_choice_menu_and_bypasses_llm() -> None:
    tools = ToolRegistry()
    llm = _QueueLLM(outputs=[{"route": "unknown", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="asdf qwer",
        session_context={"deterministic_render": True},
        policy=None,
        context={"session_id": "t"},
    )

    assert llm.calls == 1

    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "unknown"
    assert res.metadata.get("state") == "PENDING_CHOICE"
    opts = res.metadata.get("options")
    assert isinstance(opts, dict)
    assert set(opts.keys()) >= {"0", "1", "2"}


def test_calendar_route_allows_llm_and_renders_list_events_deterministically() -> None:
    tools = ToolRegistry()

    def list_events(**params):
        return {"ok": True, "count": 0, "events": []}

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    llm = _QueueLLM(
        outputs=[
            {"route": "calendar", "calendar_intent": "query", "confidence": 0.9},
            {"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}},
        ]
    )
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="Bu akşam planım var mı?",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context={"session_id": "t"},
    )

    assert llm.calls == 2
    assert res.kind == "say"
    assert res.metadata.get("action_type") == "list_events"
    assert res.metadata.get("events_count") == 0

    trace = res.metadata.get("trace")
    assert isinstance(trace, dict)
    assert trace.get("intent") == "calendar.query"
    slots = trace.get("slots")
    assert isinstance(slots, dict)
    assert slots.get("date") in {"evening", "none"}
    assert trace.get("safety") == []


def test_trace_create_event_slot_fill_then_confirmation_is_structured_and_stable() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    r1 = loop.run(
        turn_input="Bugün 23.50'ye kitap okuma saati ekle",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    trace1 = r1.metadata.get("trace")
    assert isinstance(trace1, dict)
    assert trace1.get("intent") == "calendar.create"
    assert trace1.get("next_action") == "ask_slot_fill"
    assert "write_requires_confirmation" in (trace1.get("safety") or [])
    slots1 = trace1.get("slots")
    assert isinstance(slots1, dict)
    assert "23:50" in str(slots1.get("start_time") or "")

    r2 = loop.run(
        turn_input="30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "pending_confirmation"
    trace2 = r2.metadata.get("trace")
    assert isinstance(trace2, dict)
    # user_goal should stay frozen on the original intent across follow-ups.
    assert "kitap" in str(trace2.get("user_goal") or "").lower()
    assert trace2.get("intent") == "calendar.create"
    assert trace2.get("next_action") == "ask_confirmation"
    slots2 = trace2.get("slots")
    assert isinstance(slots2, dict)
    assert "23:50" in str(slots2.get("start_time") or "")
    assert int(slots2.get("duration_min") or 0) == 30
    assert "kitap" in str(slots2.get("title") or "").lower()


def test_calendar_planner_optional_trace_is_emitted_when_enabled() -> None:
    tools = ToolRegistry()
    llm = _QueueLLM(
        outputs=[
            {
                "intent": "create",
                "slots": {"day_hint": "today", "start_time": "23:50", "duration_min": 30, "title": "kitap okuma", "ref": "none"},
            }
        ]
    )
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    res = loop.run(
        turn_input="Bugün 23:50 kitap okuma ekle 30 dk",
        session_context={
            "deterministic_render": True,
            "enable_calendar_planner": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert llm.calls == 1
    assert res.kind == "ask_user"
    trace = res.metadata.get("trace")
    assert isinstance(trace, dict)
    planner = trace.get("planner")
    assert isinstance(planner, dict)
    assert planner.get("intent") == "create"


def test_llm_ask_user_is_ignored_and_replaced_with_brainloop_menu_in_deterministic_mode() -> None:
    tools = ToolRegistry()
    llm = _QueueLLM(
        outputs=[
            {"route": "calendar", "calendar_intent": "query", "confidence": 0.9},
            {"type": "ASK_USER", "question": "Efendim, kaçta okula gitmek istemiyorsun?"},
        ]
    )

    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    res = loop.run(
        turn_input="Bu akşam planım var mı?",
        session_context={"deterministic_render": True},
        policy=None,
        context={"session_id": "t"},
    )

    assert llm.calls == 2

    assert res.kind == "ask_user"
    # Calendar route -> BrainLoop replaces LLM-authored question with deterministic next-step menu.
    assert res.metadata.get("menu_id") == "calendar_next"
    opts = res.metadata.get("options")
    assert isinstance(opts, dict)
    assert set(opts.keys()) >= {"0", "1", "2"}


def test_weak_time_words_do_not_force_calendar_route_when_message_is_smalltalk() -> None:
    tools = ToolRegistry()
    llm = _QueueLLM(outputs=[{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="Yarın okula gitmek istemiyorum",
        session_context={"deterministic_render": True},
        policy=None,
        context={"session_id": "t"},
    )

    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "smalltalk_stage1"
    assert res.metadata.get("route") == "smalltalk"


def test_calendar_keywords_force_calendar_route_even_with_time_words() -> None:
    tools = ToolRegistry()

    def list_events(**params):
        return {"ok": True, "count": 0, "events": []}

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    llm = _QueueLLM(
        outputs=[
            {"route": "calendar", "calendar_intent": "query", "confidence": 0.9},
            {"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}},
        ]
    )
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="Yarın sabah boşluk var mı?",
        session_context={"deterministic_render": True},
        policy=None,
        context={"session_id": "t"},
    )

    assert llm.calls == 2
    assert res.kind == "say"


def test_calendar_create_event_is_deterministic_and_requires_confirmation() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict[str, object] = {"session_id": "t"}
    res = loop.run(
        turn_input="15:45 koşu ekle 30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T10:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "pending_confirmation"
    assert res.metadata.get("action_type") == "create_event"
    assert res.metadata.get("requires_confirmation") is True
    assert isinstance(state.get("_policy_pending_action"), dict)


def test_calendar_cancel_event_without_ref_uses_event_pick_when_last_events_available() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {
        "session_id": "t",
        "_calendar_last_events": [
            {"id": "evt_1", "summary": "Toplantı", "start": "2026-01-28T15:00:00+03:00", "end": "2026-01-28T16:00:00+03:00"},
            {"id": "evt_2", "summary": "Diş", "start": "2026-01-28T17:00:00+03:00", "end": "2026-01-28T17:30:00+03:00"},
        ],
    }

    r1 = loop.run(
        turn_input="Toplantıyı iptal et",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )

    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "event_pick"
    assert r1.metadata.get("state") == "PENDING_CHOICE"
    opts = r1.metadata.get("options")
    assert isinstance(opts, dict)
    assert set(opts.keys()) >= {"0", "1", "2"}


def test_event_pick_accepts_natural_language_ordinal() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {
            "menu_id": "event_pick",
            "default": "0",
            "op": "cancel_event",
            "params": {},
            "events": [
                {"id": "evt_1", "summary": "Toplantı", "start": "2026-01-28T15:00:00+03:00", "end": "2026-01-28T16:00:00+03:00"},
                {"id": "evt_2", "summary": "Diş", "start": "2026-01-28T17:00:00+03:00", "end": "2026-01-28T17:30:00+03:00"},
            ],
        },
    }

    r = loop.run(
        turn_input="ikincisini",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert r.kind == "ask_user"
    assert r.metadata.get("menu_id") == "pending_confirmation"
    assert r.metadata.get("action_type") == "delete_event"
    assert r.metadata.get("requires_confirmation") is True


def test_delete_update_pending_confirmation_does_not_accept_ok() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {"type": "CALL_TOOL", "name": "calendar.delete_event", "params": {"event_id": "evt_1"}},
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "#1'i iptal et",
        },
    }

    r = loop.run(
        turn_input="ok",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )

    assert r.kind == "ask_user"
    assert r.metadata.get("menu_id") == "pending_confirmation"
    assert r.metadata.get("reprompt_for") == "pending_confirmation"


def test_p1_acceptance_create_net_requires_confirmation() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    r1 = loop.run(
        turn_input="Yarın 14:00'te toplantı ekle 30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "tomorrow_window": {"time_min": "2026-01-29T00:00:00+03:00", "time_max": "2026-01-29T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "pending_confirmation"
    assert r1.metadata.get("action_type") == "create_event"
    assert r1.metadata.get("requires_confirmation") is True
    pending = state.get("_policy_pending_action")
    assert isinstance(pending, dict)
    action = pending.get("action")
    assert isinstance(action, dict)
    assert action.get("name") == "calendar.create_event"


def test_p1_acceptance_create_missing_info_asks_single_question() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    r1 = loop.run(
        turn_input="Yarın toplantı ekle",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "tomorrow_window": {"time_min": "2026-01-29T00:00:00+03:00", "time_max": "2026-01-29T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "calendar_slot_fill"
    missing = r1.metadata.get("missing")
    assert isinstance(missing, list)
    assert "start_time" in missing


def test_calendar_slot_fill_continues_even_if_followup_has_no_calendar_keywords() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    # Missing duration -> asks a single question.
    r1 = loop.run(
        turn_input="Bugün 23.50'ye kitap okuma saati ekle",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "calendar_slot_fill"
    missing = r1.metadata.get("missing")
    assert isinstance(missing, list)
    assert "duration_minutes" in missing

    # Follow-up contains no 'ekle' keyword; should still proceed via pending intent.
    r2 = loop.run(
        turn_input="30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "pending_confirmation"
    assert r2.metadata.get("action_type") == "create_event"


def test_p1_calendar_title_freeze_prevents_followup_polluting_summary() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    r1 = loop.run(
        turn_input="Bugün 23.50'ye kitap okuma saati ekle",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "calendar_slot_fill"
    pending_intent = r1.metadata.get("pending_intent")
    assert isinstance(pending_intent, dict)
    assert pending_intent.get("type") == "create_event"
    title = str(pending_intent.get("title") or "")
    assert "kitap" in title.lower()

    r2 = loop.run(
        turn_input="30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "pending_confirmation"
    pending = state.get("_policy_pending_action")
    assert isinstance(pending, dict)
    action = pending.get("action")
    assert isinstance(action, dict)
    params = action.get("params")
    assert isinstance(params, dict)
    summary = str(params.get("summary") or "")
    assert "dk" not in summary.lower()
    assert "30" not in summary


def test_p1_calendar_create_confirmation_accepts_peki_synonym() -> None:
    tools = ToolRegistry()

    def create_event(**params):
        return {"ok": True, "summary": params.get("summary"), "start": params.get("start"), "end": params.get("end")}

    tools.register(
        Tool(
            name="calendar.create_event",
            description="create",
            parameters={"type": "object", "properties": {}},
            function=create_event,
        )
    )

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    r1 = loop.run(
        turn_input="15:45 koşu ekle 30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "pending_confirmation"
    assert isinstance(state.get("_policy_pending_action"), dict)

    r2 = loop.run(
        turn_input="peki",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r2.kind == "say"
    assert state.get("_policy_pending_action") is None


def test_p1_calendar_post_write_cleanup_clears_pending_keys() -> None:
    tools = ToolRegistry()

    def create_event(**params):
        return {"ok": True, "summary": params.get("summary"), "start": params.get("start"), "end": params.get("end")}

    tools.register(
        Tool(
            name="calendar.create_event",
            description="create",
            parameters={"type": "object", "properties": {}},
            function=create_event,
        )
    )

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    _ = loop.run(
        turn_input="15:45 koşu ekle 30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    _ = loop.run(
        turn_input="1",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert state.get("_dialog_pending_choice") is None
    assert state.get("_policy_pending_action") is None
    assert state.get("_calendar_pending_intent") is None
    assert state.get("_dialog_state") == "IDLE"


def test_p1_domain_menu_bypassed_for_time_word_calendar_query() -> None:
    tools = ToolRegistry()

    def list_events(**params):
        return {"ok": True, "count": 0, "events": []}

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    llm = _QueueLLM(
        outputs=[
            {"route": "calendar", "calendar_intent": "query", "confidence": 0.9},
            {"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}},
        ]
    )
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="Yarın sabah müsait miyim?",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context={"session_id": "t"},
    )
    assert res.kind == "say"
    assert res.metadata.get("route") == "calendar_query"


def test_p1_after_calendar_write_smalltalk_does_not_show_calendar_next_menu() -> None:
    tools = ToolRegistry()

    def create_event(**params):
        return {"ok": True, "summary": params.get("summary"), "start": params.get("start"), "end": params.get("end")}

    tools.register(
        Tool(
            name="calendar.create_event",
            description="create",
            parameters={"type": "object", "properties": {}},
            function=create_event,
        )
    )

    llm = _QueueLLM(outputs=[{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    _ = loop.run(
        turn_input="15:45 koşu ekle 30 dk",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )
    _ = loop.run(
        turn_input="1",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "today_window": {"time_min": "2026-01-28T00:00:00+03:00", "time_max": "2026-01-28T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    r3 = loop.run(
        turn_input="uykuluyum",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert r3.kind == "ask_user"
    assert r3.metadata.get("menu_id") == "smalltalk_stage1"


def test_p1_acceptance_list_then_reference_cancel_second() -> None:
    tools = ToolRegistry()

    def list_events(**params):
        return {
            "ok": True,
            "count": 2,
            "events": [
                {"id": "evt_1", "summary": "Toplantı", "start": "2026-01-28T10:00:00+03:00", "end": "2026-01-28T10:30:00+03:00"},
                {"id": "evt_2", "summary": "Diş", "start": "2026-01-28T12:00:00+03:00", "end": "2026-01-28T12:30:00+03:00"},
            ],
        }

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    llm = _QueueLLM(outputs=[{"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    state: dict = {"session_id": "t"}

    r1 = loop.run(
        turn_input="Bugün takvimimde ne var?",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert r1.kind == "say"
    assert r1.metadata.get("action_type") == "list_events"
    assert isinstance(state.get("_calendar_last_events"), list)

    r2 = loop.run(
        turn_input="İkincisini iptal et",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "pending_confirmation"
    assert r2.metadata.get("action_type") == "delete_event"
    pending = state.get("_policy_pending_action")
    assert isinstance(pending, dict)
    action = pending.get("action")
    assert isinstance(action, dict)
    assert action.get("name") == "calendar.delete_event"


def test_p1_acceptance_move_reference_to_tomorrow_target_time() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {
        "session_id": "t",
        "_calendar_last_events": [
            {"id": "evt_1", "summary": "Toplantı", "start": "2026-01-28T10:00:00+03:00", "end": "2026-01-28T10:30:00+03:00"},
            {"id": "evt_2", "summary": "Koşu", "start": "2026-01-28T11:00:00+03:00", "end": "2026-01-28T12:00:00+03:00"},
        ],
        "last_intent": "calendar_query",
        "last_tool_used": "calendar.list_events",
    }

    r1 = loop.run(
        turn_input="#2'yi yarın 09:30'a al",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "tomorrow_window": {"time_min": "2026-01-29T00:00:00+03:00", "time_max": "2026-01-29T23:59:00+03:00"},
        },
        policy=None,
        context=state,
    )

    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "pending_confirmation"
    assert r1.metadata.get("action_type") == "update_event"
    pending = state.get("_policy_pending_action")
    assert isinstance(pending, dict)
    action = pending.get("action")
    assert isinstance(action, dict)
    assert action.get("name") == "calendar.update_event"
    params = action.get("params")
    assert isinstance(params, dict)
    assert params.get("event_id") == "evt_2"
    assert isinstance(params.get("start"), str)
    assert str(params.get("start")).startswith("2026-01-29T09:30")


def test_p1_acceptance_cancel_fuzzy_single_match_no_menu() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {
        "session_id": "t",
        "_calendar_last_events": [
            {"id": "evt_math", "summary": "Matematik dersi", "start": "2026-01-28T09:00:00+03:00", "end": "2026-01-28T10:00:00+03:00"},
        ],
        "last_intent": "calendar_query",
        "last_tool_used": "calendar.list_events",
    }

    r1 = loop.run(
        turn_input="Matematik dersini iptal et",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "pending_confirmation"
    assert r1.metadata.get("action_type") == "delete_event"


def test_p1_acceptance_ambiguity_event_pick_then_ordinal() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {
        "session_id": "t",
        "_calendar_last_events": [
            {"id": "evt_1", "summary": "Ders (Matematik)", "start": "2026-01-28T09:00:00+03:00", "end": "2026-01-28T10:00:00+03:00"},
            {"id": "evt_2", "summary": "Ders (Fizik)", "start": "2026-01-28T11:00:00+03:00", "end": "2026-01-28T12:00:00+03:00"},
        ],
        "last_intent": "calendar_query",
        "last_tool_used": "calendar.list_events",
    }

    r1 = loop.run(
        turn_input="Dersi iptal et",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "event_pick"
    assert r1.metadata.get("state") == "PENDING_CHOICE"

    r2 = loop.run(
        turn_input="ikinci",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "pending_confirmation"
    assert r2.metadata.get("action_type") == "delete_event"


def test_calendar_flow_hard_exit_resets_flow_and_clears_intent() -> None:
    tools = ToolRegistry()
    llm = _QueueLLM(outputs=[{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    state: dict = {"session_id": "t", "last_intent": "calendar_query", "last_tool_used": "calendar.list_events"}
    r1 = loop.run(
        turn_input="konu değiştir",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )

    assert r1.kind == "say"
    assert r1.metadata.get("action_type") == "exit_calendar"
    assert state.get("last_intent") is None
    assert state.get("last_tool_used") is None

    # After exit, smalltalk should route normally.
    r2 = loop.run(
        turn_input="uykuluyum",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "smalltalk_stage1"


def test_calendar_list_events_with_smalltalk_clause_sets_mini_ack_metadata() -> None:
    tools = ToolRegistry()

    def list_events(**params):
        return {"ok": True, "count": 0, "events": []}

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    llm = _QueueLLM(
        outputs=[
            {"route": "calendar", "calendar_intent": "query", "confidence": 0.9},
            {"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}},
        ]
    )
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="Bu akşam planım var mı, bu arada moralim bozuk",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context={"session_id": "t"},
    )

    assert res.kind == "say"
    assert res.metadata.get("action_type") == "list_events"
    assert res.metadata.get("mini_ack") is True


def test_smalltalk_two_stage_menu_then_free_slots_menu() -> None:
    tools = ToolRegistry()

    def find_free_slots(**params):
        return {
            "ok": True,
            "slots": [
                {"start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"},
                {"start": "2026-01-29T10:00:00+03:00", "end": "2026-01-29T10:30:00+03:00"},
                {"start": "2026-01-29T11:00:00+03:00", "end": "2026-01-29T11:30:00+03:00"},
            ],
        }

    tools.register(
        Tool(
            name="calendar.find_free_slots",
            description="free",
            parameters={"type": "object", "properties": {}},
            function=find_free_slots,
        )
    )

    state: dict = {"session_id": "t"}
    llm = _QueueLLM(outputs=[{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))

    r1 = loop.run(
        turn_input="uykuluyum okula gitmek istemiyorum",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "morning_tomorrow_window": {"time_min": "2026-01-29T07:30:00+03:00", "time_max": "2026-01-29T11:30:00+03:00"},
            "today_window": {"time_min": "2026-01-28T21:00:00+03:00", "time_max": "2026-01-28T22:30:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r1.kind == "ask_user"
    assert r1.metadata.get("menu_id") == "smalltalk_stage1"
    assert r1.metadata.get("state") == "PENDING_CHOICE"

    r2 = loop.run(
        turn_input="2",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "morning_tomorrow_window": {"time_min": "2026-01-29T07:30:00+03:00", "time_max": "2026-01-29T11:30:00+03:00"},
            "today_window": {"time_min": "2026-01-28T21:00:00+03:00", "time_max": "2026-01-28T22:30:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r2.kind == "ask_user"
    assert r2.metadata.get("menu_id") == "smalltalk_stage2"
    assert r2.metadata.get("state") == "PENDING_CHOICE"

    r3 = loop.run(
        turn_input="3",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "morning_tomorrow_window": {"time_min": "2026-01-29T07:30:00+03:00", "time_max": "2026-01-29T11:30:00+03:00"},
            "today_window": {"time_min": "2026-01-28T21:00:00+03:00", "time_max": "2026-01-28T22:30:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert r3.kind == "ask_user"
    assert r3.metadata.get("menu_id") == "free_slots"
    assert r3.metadata.get("state") == "PENDING_CHOICE"
    opts = r3.metadata.get("options")
    assert isinstance(opts, dict)
    assert "0" in opts and "9" in opts


def test_free_slots_invalid_input_triggers_reprompt_first_then_cancel() -> None:
    """With 2-stage reprompt, first unclear input triggers reprompt, second cancels."""
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {
            "menu_id": "free_slots",
            "default": "0",
            "duration": 30,
            "time_min": "2026-01-29T07:30:00+03:00",
            "time_max": "2026-01-29T11:30:00+03:00",
            "slots": [{"start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}],
        },
    }
    # First unclear input → reprompt
    res1 = loop.run(
        turn_input="ben bilmem",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert res1.kind == "ask_user"
    assert res1.metadata.get("menu_id") == "free_slots"
    assert res1.metadata.get("reprompt_for") == "free_slots"

    # Second unclear input → cancel (default=0)
    res2 = loop.run(
        turn_input="yine bilmem",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert res2.kind == "say"
    assert res2.metadata.get("menu_id") == "free_slots"


def test_free_slots_pick_slot_transitions_to_pending_confirmation_prompt() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {
            "menu_id": "free_slots",
            "default": "0",
            "duration": 30,
            "time_min": "2026-01-29T07:30:00+03:00",
            "time_max": "2026-01-29T11:30:00+03:00",
            "slots": [
                {"start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}
            ],
        },
    }
    res = loop.run(
        turn_input="1",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "pending_confirmation"
    assert res.metadata.get("action_type") == "create_event"
    assert res.metadata.get("requires_confirmation") is True
    assert "_policy_pending_action" in state


def test_pending_confirmation_deny_takes_precedence_over_router_menus() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {"type": "CALL_TOOL", "name": "calendar.create_event", "params": {"summary": "Mola", "start": "2026-01-29T09:00:00+03:00"}},
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "test",
        },
    }

    res = loop.run(
        turn_input="hayır",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "say"
    assert res.metadata.get("menu_id") == "pending_confirmation"
    assert res.metadata.get("action_type") == "create_event"
    assert res.metadata.get("requires_confirmation") is True


def test_pending_confirmation_random_input_repompts_yes_no() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {"type": "CALL_TOOL", "name": "calendar.create_event", "params": {"summary": "Mola", "start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}},
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "test",
        },
    }

    res = loop.run(
        turn_input="hmm",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "pending_confirmation"
    assert res.metadata.get("action_type") == "create_event"
    assert res.metadata.get("requires_confirmation") is True
    assert res.metadata.get("reprompt_for") == "pending_confirmation"


def test_pending_confirmation_deny_clears_pending_action() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {"type": "CALL_TOOL", "name": "calendar.create_event", "params": {"summary": "Mola", "start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}},
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "test",
        },
    }
    res = loop.run(
        turn_input="hayır",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "say"
    assert "_policy_pending_action" not in state


def test_pending_confirmation_confirm_runs_tool_and_renders_create_event_deterministically() -> None:
    tools = ToolRegistry()
    seen: dict = {}

    def create_event(**params):
        seen.update(params)
        return {
            "ok": True,
            "summary": str(params.get("summary") or ""),
            "start": str(params.get("start") or ""),
            "end": str(params.get("end") or ""),
        }

    tools.register(
        Tool(
            name="calendar.create_event",
            description="create",
            parameters={"type": "object", "properties": {}},
            function=create_event,
            requires_confirmation=True,
            risk_level="MED",
        )
    )

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {
                "type": "CALL_TOOL",
                "name": "calendar.create_event",
                "params": {"summary": "Mola", "start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"},
            },
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "test",
        },
    }

    res = loop.run(
        turn_input="evet",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul", "dry_run": True},
        policy=None,
        context=state,
    )

    assert res.kind == "say"
    assert res.metadata.get("action_type") == "create_event"
    assert res.metadata.get("requires_confirmation") is True
    assert res.metadata.get("dry_run") is True
    assert seen.get("summary") == "Mola"


def test_pending_confirmation_zero_means_deny() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {"type": "CALL_TOOL", "name": "calendar.create_event", "params": {"summary": "Mola", "start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}},
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "test",
        },
    }
    res = loop.run(
        turn_input="0",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "say"
    assert "_policy_pending_action" not in state


def test_pending_confirmation_one_means_confirm() -> None:
    tools = ToolRegistry()

    def create_event(**params):
        return {"ok": True, "summary": "Mola", "start": params.get("start"), "end": params.get("end")}

    tools.register(
        Tool(
            name="calendar.create_event",
            description="create",
            parameters={"type": "object", "properties": {}},
            function=create_event,
            requires_confirmation=True,
            risk_level="MED",
        )
    )

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_policy_pending_action": {
            "action": {
                "type": "CALL_TOOL",
                "name": "calendar.create_event",
                "params": {"summary": "Mola", "start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"},
            },
            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
            "original_user_input": "test",
        },
    }
    res = loop.run(
        turn_input="1",
        session_context={"deterministic_render": True, "dry_run": True},
        policy=None,
        context=state,
    )
    assert res.kind == "say"
    assert res.metadata.get("action_type") == "create_event"
    assert res.metadata.get("requires_confirmation") is True
    assert res.metadata.get("dry_run") is True


def test_pending_choice_smalltalk_stage2_accepts_text_yarin_kaydir() -> None:
    tools = ToolRegistry()

    def find_free_slots(**params):
        return {"ok": True, "slots": [{"start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}]}

    tools.register(
        Tool(
            name="calendar.find_free_slots",
            description="free",
            parameters={"type": "object", "properties": {}},
            function=find_free_slots,
        )
    )

    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {"menu_id": "smalltalk_stage2", "default": "0"},
    }
    res = loop.run(
        turn_input="Yarın kaydır",
        session_context={
            "deterministic_render": True,
            "tz_name": "Europe/Istanbul",
            "morning_tomorrow_window": {"time_min": "2026-01-29T07:30:00+03:00", "time_max": "2026-01-29T11:30:00+03:00"},
            "today_window": {"time_min": "2026-01-28T21:00:00+03:00", "time_max": "2026-01-28T22:30:00+03:00"},
            "tomorrow_window": {"time_min": "2026-01-29T07:30:00+03:00", "time_max": "2026-01-29T22:30:00+03:00"},
        },
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "free_slots"
    opts = res.metadata.get("options")
    assert isinstance(opts, dict)
    assert "0" in opts and "9" in opts


def test_pending_choice_smalltalk_stage1_accepts_text_hafiflet() -> None:
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {"menu_id": "smalltalk_stage1", "default": "0"},
    }
    res = loop.run(
        turn_input="hafiflet",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "smalltalk_stage2"
    opts = res.metadata.get("options")
    assert isinstance(opts, dict)
    assert set(opts.keys()) >= {"0", "1", "2", "3"}


# ─────────────────────────────────────────────────────────────────
# NEW: 2-stage reprompt acceptance tests (Jarvis HMM rule)
# ─────────────────────────────────────────────────────────────────


def test_unclear_input_triggers_reprompt_on_first_attempt() -> None:
    """When user says 'hmm' or unclear text, first attempt should reprompt."""
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {"menu_id": "smalltalk_stage1", "default": "0"},
    }
    res = loop.run(
        turn_input="hmm emin değilim",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "smalltalk_stage1"
    assert res.metadata.get("reprompt_for") == "smalltalk_stage1"
    # Pending choice should still be set
    assert "_dialog_pending_choice" in state


def test_second_unclear_input_applies_default_and_cancels() -> None:
    """When user is unclear twice, apply default (0=İptal)."""
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {"menu_id": "smalltalk_stage1", "default": "0"},
        "_dialog_reprompt_count": 1,  # Already reprompted once
    }
    res = loop.run(
        turn_input="hmm bilmiyorum",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "say"
    assert res.metadata.get("menu_id") == "smalltalk_stage1"
    # Pending choice should be cleared
    assert "_dialog_pending_choice" not in state


def test_unclear_input_on_free_slots_menu_triggers_reprompt() -> None:
    """free_slots menu should also use 2-stage reprompt."""
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {
            "menu_id": "free_slots",
            "default": "0",
            "time_min": "2026-01-29T09:00:00+03:00",
            "time_max": "2026-01-29T12:00:00+03:00",
            "slots": [{"start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T09:30:00+03:00"}],
        },
    }
    res = loop.run(
        turn_input="şey ee",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "free_slots"
    assert res.metadata.get("reprompt_for") == "free_slots"


def test_unknown_menu_processes_choice_1_asks_for_calendar_query() -> None:
    """Unknown menu choice 1 should ask user for their calendar query."""
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {"menu_id": "unknown", "default": "0"},
    }
    res = loop.run(
        turn_input="1",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context=state,
    )
    # Should ask user for their calendar query
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "calendar_query"
    # Pending choice should be cleared
    assert "_dialog_pending_choice" not in state


def test_unknown_menu_choice_2_routes_to_smalltalk_stage1() -> None:
    """Unknown menu choice 2 should show smalltalk stage1 menu."""
    tools = ToolRegistry()
    loop = BrainLoop(llm=_FailingLLM(), tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    state: dict = {
        "session_id": "t",
        "_dialog_pending_choice": {"menu_id": "unknown", "default": "0"},
    }
    res = loop.run(
        turn_input="2",
        session_context={"deterministic_render": True},
        policy=None,
        context=state,
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "smalltalk_stage1"
    assert state.get("_dialog_pending_choice", {}).get("menu_id") == "smalltalk_stage1"


def test_list_events_renderer_shows_plus_more_for_many_events() -> None:
    """list_events with >3 events should show '+N daha' indicator."""
    tools = ToolRegistry()

    def list_events(**params):
        return {
            "ok": True,
            "count": 5,
            "events": [
                {"summary": "Event 1", "start": "2026-01-29T09:00:00+03:00", "end": "2026-01-29T10:00:00+03:00"},
                {"summary": "Event 2", "start": "2026-01-29T10:00:00+03:00", "end": "2026-01-29T11:00:00+03:00"},
                {"summary": "Event 3", "start": "2026-01-29T11:00:00+03:00", "end": "2026-01-29T12:00:00+03:00"},
                {"summary": "Event 4", "start": "2026-01-29T12:00:00+03:00", "end": "2026-01-29T13:00:00+03:00"},
                {"summary": "Event 5", "start": "2026-01-29T13:00:00+03:00", "end": "2026-01-29T14:00:00+03:00"},
            ],
        }

    tools.register(
        Tool(
            name="calendar.list_events",
            description="list",
            parameters={"type": "object", "properties": {}},
            function=list_events,
        )
    )

    llm = _QueueLLM(
        outputs=[
            {"route": "calendar", "calendar_intent": "query", "confidence": 0.9},
            {"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}},
        ]
    )
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=2, debug=False))
    res = loop.run(
        turn_input="Bu akşam planım var mı?",
        session_context={"deterministic_render": True, "tz_name": "Europe/Istanbul"},
        policy=None,
        context={"session_id": "t"},
    )
    assert res.kind == "say"
    assert res.metadata.get("action_type") == "list_events"
    assert res.metadata.get("events_count") == 5
    assert res.metadata.get("events_shown") == 3
    assert res.metadata.get("events_more") == 2


def test_menus_are_concise_without_hint_lines() -> None:
    """Jarvis menus should be short - no long hint lines."""
    tools = ToolRegistry()
    llm = _QueueLLM(outputs=[{"route": "smalltalk", "calendar_intent": "none", "confidence": 0.9}])
    loop = BrainLoop(llm=llm, tools=tools, config=BrainLoopConfig(max_steps=1, debug=False))
    res = loop.run(
        turn_input="uykuluyum",
        session_context={"deterministic_render": True},
        policy=None,
        context={"session_id": "t"},
    )
    assert res.kind == "ask_user"
    assert res.metadata.get("menu_id") == "smalltalk_stage1"
    opts = res.metadata.get("options")
    assert isinstance(opts, dict)
    # Concise contract: stage1 exposes exactly 3 numbered options
    assert set(opts.keys()) == {"0", "1", "2"}


def test_voice_style_module_exists_and_works() -> None:
    """VoiceStyle module provides Jarvis persona consistency."""
    from bantz.voice_style import VoiceStyle, JARVIS

    # Test acknowledge
    assert VoiceStyle.acknowledge("test message").startswith("Efendim")
    assert VoiceStyle.acknowledge("Efendim, already").startswith("Efendim")

    # Test strip_emoji
    assert VoiceStyle.strip_emoji("Hello 😀 World") == "Hello  World"

    # Test limit_sentences
    assert VoiceStyle.limit_sentences("One. Two. Three.", max_sentences=2) == "One. Two."

    # Test format_list_with_more
    items = ["A", "B", "C", "D", "E"]
    result = VoiceStyle.format_list_with_more(items, shown=3)
    assert "- A" in result
    assert "- C" in result
    assert "+2 daha fazla" in result
    assert "- D" not in result

    # Convenience alias
    assert JARVIS is VoiceStyle
