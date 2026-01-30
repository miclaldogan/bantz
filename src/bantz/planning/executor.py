from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from bantz.planning.plan_draft import PlanDraft, PlanItem, plan_draft_from_dict


@dataclass(frozen=True)
class PlannedEvent:
    summary: str
    start: str
    end: str
    location: Optional[str] = None


def plan_events_from_draft(
    *,
    draft: dict[str, Any],
    time_min: str,
    time_max: str,
) -> dict[str, Any]:
    """Create a deterministic list of events from a PlanDraft within a window.

    This does not call external services.
    """

    if not isinstance(draft, dict):
        return {"ok": False, "error": "invalid_draft"}
    if not isinstance(time_min, str) or not isinstance(time_max, str) or not time_min or not time_max:
        return {"ok": False, "error": "invalid_window"}

    plan = plan_draft_from_dict(draft)

    try:
        w_start = _parse_iso(time_min)
        w_end = _parse_iso(time_max)
    except Exception:
        return {"ok": False, "error": "invalid_window"}

    cursor = w_start
    events: list[dict[str, Any]] = []
    warnings: list[str] = []

    for idx, item in enumerate(plan.items):
        if not isinstance(item, PlanItem):
            continue

        dur = _duration_minutes(item)
        start = cursor
        end = start + timedelta(minutes=dur)

        if end > w_end:
            warnings.append(f"item_{idx+1}_exceeds_window")
            break

        events.append(
            {
                "summary": str(item.label or "").strip() or "(etkinlik)",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "location": str(item.location or "").strip() or None,
            }
        )
        cursor = end

    return {
        "ok": True,
        "count": len(events),
        "events": events,
        "warnings": warnings,
        "time_min": time_min,
        "time_max": time_max,
    }


def apply_plan_draft(
    *,
    draft: dict[str, Any],
    time_min: str,
    time_max: str,
    dry_run: bool = False,
    calendar_id: str = "primary",
    create_event_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Apply a PlanDraft by creating calendar events.

    - If dry_run=True, returns the proposed events and performs no writes.
    - If a create fails, stops and returns which item failed.
    """

    planned = plan_events_from_draft(draft=draft, time_min=time_min, time_max=time_max)
    if not planned.get("ok"):
        return {"ok": False, "error": planned.get("error") or "plan_failed"}

    events = planned.get("events")
    if not isinstance(events, list):
        events = []

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "created_count": 0,
            "events": events,
            "warnings": planned.get("warnings") if isinstance(planned.get("warnings"), list) else [],
        }

    if create_event_fn is None:
        return {"ok": False, "error": "missing_create_event_fn"}

    created: list[dict[str, Any]] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        try:
            res = create_event_fn(
                summary=str(ev.get("summary") or "").strip() or "(etkinlik)",
                start=str(ev.get("start") or "").strip(),
                end=str(ev.get("end") or "").strip(),
                location=str(ev.get("location") or "").strip() or None,
                calendar_id=calendar_id,
            )
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_index": idx + 1,
                "created_count": len(created),
                "created": created,
            }

        if not isinstance(res, dict) or res.get("ok") is not True:
            return {
                "ok": False,
                "error": (res.get("error") if isinstance(res, dict) else None) or "create_failed",
                "failed_index": idx + 1,
                "created_count": len(created),
                "created": created,
                "last_result": res,
            }

        created.append(res)

    return {
        "ok": True,
        "dry_run": False,
        "created_count": len(created),
        "events": events,
        "created": created,
        "warnings": planned.get("warnings") if isinstance(planned.get("warnings"), list) else [],
    }


def _duration_minutes(item: PlanItem) -> int:
    try:
        dm = int(item.duration_minutes) if item.duration_minutes is not None else 0
    except Exception:
        dm = 0
    if dm <= 0:
        return 30
    return max(5, min(24 * 60, dm))


def _parse_iso(s: str) -> datetime:
    t = str(s or "").strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t)
