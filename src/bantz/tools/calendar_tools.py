from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from typing import Any, Optional

from bantz.google.calendar import create_event, find_free_slots, list_events
from bantz.tools.calendar_idempotency import create_event_with_idempotency


@dataclass(frozen=True)
class TimeWindow:
    time_min: str
    time_max: Optional[str]


def _local_tz():
    return datetime.now().astimezone().tzinfo


_RELATIVE_DATE_TOKENS: dict[str, str] = {
    "today": "today",
    "tomorrow": "tomorrow",
    "yesterday": "yesterday",
    "bugün": "today",
    "yarın": "tomorrow",
    "dün": "yesterday",
}


def _date_yesterday() -> str:
    return (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()


def _resolve_date_token(date_str: str) -> str:
    token = (date_str or "").strip().lower()
    mapped = _RELATIVE_DATE_TOKENS.get(token)
    if mapped == "today":
        return _date_today()
    if mapped == "tomorrow":
        return _date_tomorrow()
    if mapped == "yesterday":
        return _date_yesterday()
    return date_str


def _dt(date_str: str, hhmm: str) -> datetime:
    # date_str: YYYY-MM-DD, hhmm: HH:MM
    date_str = _resolve_date_token(date_str)
    try:
        y, m, d = [int(x) for x in date_str.split("-")]
    except Exception as e:
        raise ValueError(f"invalid_date_format: {date_str!r}") from e
    hh, mm = [int(x) for x in hhmm.split(":")]
    return datetime(y, m, d, hh, mm, tzinfo=_local_tz())


def _date_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _date_tomorrow() -> str:
    return (datetime.now().astimezone().date() + timedelta(days=1)).isoformat()


def _window_from_hint(*, window_hint: Optional[str], date: Optional[str]) -> Optional[TimeWindow]:
    hint = (window_hint or "").strip().lower()
    if not hint:
        return None

    today = _date_today()

    if hint == "today":
        d = _resolve_date_token(date) if date else today
        start = _dt(d, "00:00")
        end = _dt(d, "23:59")
        return TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    if hint == "tomorrow":
        d = _resolve_date_token(date) if date else _date_tomorrow()
        start = _dt(d, "00:00")
        end = _dt(d, "23:59")
        return TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    if hint == "yesterday":
        d = _resolve_date_token(date) if date else _date_yesterday()
        start = _dt(d, "00:00")
        end = _dt(d, "23:59")
        return TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    if hint == "evening":
        d = _resolve_date_token(date) if date else today
        start = _dt(d, "17:00")
        end = _dt(d, "23:59")
        return TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    if hint == "morning":
        # If it's already afternoon, interpret as next morning.
        now = datetime.now().astimezone()
        d = _resolve_date_token(date) if date else None
        if not d:
            d = today if now.time() < dtime(12, 0) else _date_tomorrow()
        start = _dt(d, "07:00")
        end = _dt(d, "12:00")
        return TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    if hint == "week":
        now = datetime.now().astimezone()
        end = now + timedelta(days=7)
        return TimeWindow(time_min=now.isoformat(), time_max=end.isoformat())

    return None


def calendar_list_events_tool(
    *,
    date: Optional[str] = None,
    time: Optional[str] = None,
    window_hint: Optional[str] = None,
    max_results: int = 10,
    query: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    """List calendar events using orchestrator-style slots.

    - If `window_hint` is present, uses a computed time window.
    - Else if `date` is present, lists that day.
    - Else lists upcoming events (Calendar default behavior).
    """

    if date:
        date = _resolve_date_token(date)

    win = _window_from_hint(window_hint=window_hint, date=date)
    if win is None and date:
        start = _dt(date, "00:00")
        end = _dt(date, "23:59")
        win = TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    # If time is provided but no explicit window, anchor to that time onward.
    if win is None and time:
        d = date or _date_today()
        start = _dt(d, time)
        # Default 6h horizon.
        end = start + timedelta(hours=6)
        win = TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    try:
        resp = list_events(
            max_results=int(max_results),
            time_min=win.time_min if win else None,
            time_max=win.time_max if win else None,
            query=query,
            interactive=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "events": [], "window": {"time_min": win.time_min, "time_max": win.time_max} if win else None}

    if isinstance(resp, dict):
        resp.setdefault("window", {"time_min": win.time_min, "time_max": win.time_max} if win else None)
    return resp


def calendar_find_free_slots_tool(
    *,
    duration: Optional[int] = None,
    window_hint: Optional[str] = None,
    date: Optional[str] = None,
    suggestions: int = 3,
    **_: Any,
) -> dict[str, Any]:
    """Find free calendar slots.

    Uses `window_hint` or `date`; defaults to the next 7 days if none.
    """

    dur = int(duration) if duration is not None else 30

    if date:
        date = _resolve_date_token(date)

    win = _window_from_hint(window_hint=window_hint, date=date)
    if win is None and date:
        start = _dt(date, "09:00")
        end = _dt(date, "18:00")
        win = TimeWindow(time_min=start.isoformat(), time_max=end.isoformat())

    if win is None:
        now = datetime.now().astimezone()
        end = now + timedelta(days=7)
        win = TimeWindow(time_min=now.isoformat(), time_max=end.isoformat())

    try:
        return find_free_slots(
            time_min=win.time_min,
            time_max=str(win.time_max),
            duration_minutes=dur,
            suggestions=int(suggestions),
            interactive=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "slots": []}


def calendar_create_event_tool(
    *,
    title: Optional[str] = None,
    date: Optional[str] = None,
    time: Optional[str] = None,
    duration: Optional[int] = None,
    window_hint: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    """Create a calendar event from orchestrator slots.

    Required (best-effort): title + time.
    If date missing, uses today or tomorrow depending on window_hint.
    """

    summary = (title or "").strip() or "Etkinlik"
    hhmm = (time or "").strip()
    if not hhmm:
        return {"ok": False, "error": "Missing time slot (HH:MM)"}

    d = (date or "").strip()
    if not d:
        if (window_hint or "").strip().lower() == "tomorrow":
            d = _date_tomorrow()
        elif (window_hint or "").strip().lower() == "yesterday":
            d = _date_yesterday()
        else:
            d = _date_today()
    else:
        d = _resolve_date_token(d)

    start_dt = _dt(d, hhmm)
    dur = int(duration) if duration is not None else 60
    end_dt = start_dt + timedelta(minutes=dur)

    # Use idempotency wrapper to prevent duplicate events
    def do_create():
        return create_event(
            summary=summary,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            duration_minutes=dur,
            interactive=False,
        )

    try:
        return create_event_with_idempotency(
            title=summary,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            create_fn=do_create,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
