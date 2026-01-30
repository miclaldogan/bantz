from __future__ import annotations

from datetime import datetime, timezone

from bantz.planning.executor import apply_plan_draft, plan_events_from_draft
from bantz.planning.plan_draft import PlanDraft, PlanItem, plan_draft_to_dict


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def test_plan_events_from_draft_basic_sequence():
    draft = PlanDraft(
        title="Yarın planı (sabah)",
        goal=None,
        day_hint="tomorrow",
        time_of_day="morning",
        items=[
            PlanItem(label="Spor", duration_minutes=30),
            PlanItem(label="Okuma", duration_minutes=60),
        ],
    )

    time_min = _iso(datetime(2026, 1, 30, 9, 0, 0))
    time_max = _iso(datetime(2026, 1, 30, 12, 0, 0))

    res = plan_events_from_draft(draft=plan_draft_to_dict(draft), time_min=time_min, time_max=time_max)
    assert res["ok"] is True
    assert res["count"] == 2

    events = res["events"]
    assert isinstance(events, list)
    assert events[0]["summary"] == "Spor"
    assert events[0]["start"] == time_min
    assert events[0]["end"].endswith("09:30:00+00:00")
    assert events[1]["summary"] == "Okuma"
    assert events[1]["start"].endswith("09:30:00+00:00")
    assert events[1]["end"].endswith("10:30:00+00:00")


def test_apply_plan_draft_dry_run_never_writes():
    draft = PlanDraft(
        title="Bugün planı",
        goal=None,
        day_hint="today",
        time_of_day=None,
        items=[PlanItem(label="Yürüyüş", duration_minutes=30)],
    )
    raw = plan_draft_to_dict(draft)

    time_min = _iso(datetime(2026, 1, 30, 18, 0, 0))
    time_max = _iso(datetime(2026, 1, 30, 19, 0, 0))

    def _should_not_be_called(**_):
        raise AssertionError("create_event_fn should not be called in dry_run")

    res = apply_plan_draft(
        draft=raw,
        time_min=time_min,
        time_max=time_max,
        dry_run=True,
        calendar_id="primary",
        create_event_fn=_should_not_be_called,
    )

    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["created_count"] == 0
    assert isinstance(res["events"], list)
    assert len(res["events"]) == 1


def test_apply_plan_draft_stops_on_first_failure():
    draft = PlanDraft(
        title="Bugün planı",
        goal=None,
        day_hint="today",
        time_of_day=None,
        items=[
            PlanItem(label="A", duration_minutes=30),
            PlanItem(label="B", duration_minutes=30),
            PlanItem(label="C", duration_minutes=30),
        ],
    )
    raw = plan_draft_to_dict(draft)

    time_min = _iso(datetime(2026, 1, 30, 9, 0, 0))
    time_max = _iso(datetime(2026, 1, 30, 12, 0, 0))

    calls: list[str] = []

    def _stub_create_event(**params):
        calls.append(str(params.get("summary")))
        if len(calls) == 2:
            return {"ok": False, "error": "boom"}
        return {"ok": True, "id": f"id-{len(calls)}"}

    res = apply_plan_draft(
        draft=raw,
        time_min=time_min,
        time_max=time_max,
        dry_run=False,
        calendar_id="primary",
        create_event_fn=_stub_create_event,
    )

    assert res["ok"] is False
    assert res["failed_index"] == 2
    assert res["created_count"] == 1
    assert calls == ["A", "B"]
