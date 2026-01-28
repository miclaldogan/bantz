from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
import os


DEFAULT_CALENDAR_ID = "primary"
READONLY_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
WRITE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_rfc3339(value: str) -> datetime:
    v = (value or "").strip()
    if not v:
        raise ValueError("empty_datetime")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(value: str) -> date:
    v = (value or "").strip()
    if not v:
        raise ValueError("empty_date")
    return date.fromisoformat(v)


def _to_all_day_range(d: date, *, tz: timezone) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time(0, 0), tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def _extract_busy_intervals(
    events: list[dict[str, Any]],
    *,
    tz: timezone,
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue

        s = ev.get("start")
        e = ev.get("end")
        if not isinstance(s, str) or not isinstance(e, str):
            continue

        # All-day events show up as YYYY-MM-DD.
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            try:
                sd = _parse_date(s)
                # Calendar API often returns end date as next day for all-day.
                ed = _parse_date(e)
                start_dt, _ = _to_all_day_range(sd, tz=tz)
                end_dt, _ = _to_all_day_range(ed, tz=tz)
                intervals.append((start_dt, end_dt))
            except Exception:
                continue
            continue

        try:
            start_dt = _parse_rfc3339(s)
            end_dt = _parse_rfc3339(e)
        except Exception:
            continue

        if end_dt <= start_dt:
            continue
        intervals.append((start_dt, end_dt))

    intervals.sort(key=lambda t: t[0])
    return intervals


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    merged: list[tuple[datetime, datetime]] = []
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            if e > cur_e:
                cur_e = e
            continue
        merged.append((cur_s, cur_e))
        cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def _compute_free_slots(
    *,
    events: list[dict[str, Any]],
    time_min: str,
    time_max: str,
    duration_minutes: int,
    suggestions: int,
) -> list[dict[str, str]]:
    if duration_minutes <= 0:
        raise ValueError("duration_minutes_must_be_positive")
    if suggestions <= 0:
        return []

    window_start = _parse_rfc3339(time_min)
    window_end = _parse_rfc3339(time_max)
    if window_end <= window_start:
        raise ValueError("time_max_must_be_after_time_min")

    tzinfo = window_start.tzinfo or timezone.utc
    if not isinstance(tzinfo, timezone):
        # Keep behavior predictable.
        tzinfo = timezone.utc

    busy = _merge_intervals(_extract_busy_intervals(events, tz=tzinfo))

    # Clip busy intervals to the window.
    clipped: list[tuple[datetime, datetime]] = []
    for s, e in busy:
        if e <= window_start or s >= window_end:
            continue
        clipped.append((max(s, window_start), min(e, window_end)))
    clipped = _merge_intervals(clipped)

    required = timedelta(minutes=int(duration_minutes))
    slots: list[dict[str, str]] = []

    cursor = window_start
    for s, e in clipped:
        if s > cursor and (s - cursor) >= required:
            slot_end = cursor + required
            slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
            if len(slots) >= suggestions:
                return slots
        if e > cursor:
            cursor = e

    if window_end > cursor and (window_end - cursor) >= required:
        slot_end = cursor + required
        slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})

    return slots[:suggestions]


def list_events(
    *,
    calendar_id: Optional[str] = None,
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    single_events: bool = True,
    show_deleted: bool = False,
    order_by: str = "startTime",
) -> dict[str, Any]:
    """List upcoming events from Google Calendar.

    Notes:
    - Requires OAuth client_secret.json and a cached token.
    - Returns a JSON-serializable dict.
    """

    cal_id = (
        calendar_id
        or os.getenv("BANTZ_GOOGLE_CALENDAR_ID")
        or DEFAULT_CALENDAR_ID
    )

    # Get creds first (this will also validate secret file presence).
    from bantz.google.auth import get_credentials
    creds = get_credentials(scopes=READONLY_SCOPES)

    # Lazy import to keep base installs light.
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google calendar dependencies are not installed. Install with: "
            "pip install -e '.[calendar]'"
        ) from e

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    tmn = time_min or _now_rfc3339()
    params: dict[str, Any] = {
        "calendarId": cal_id,
        "timeMin": tmn,
        "maxResults": int(max_results),
        "singleEvents": bool(single_events),
        "showDeleted": bool(show_deleted),
        "orderBy": order_by,
    }
    if time_max:
        params["timeMax"] = time_max
    if query:
        params["q"] = query

    resp = service.events().list(**params).execute()
    items = resp.get("items") or []

    events: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        start = (it.get("start") or {}) if isinstance(it.get("start"), dict) else {}
        end = (it.get("end") or {}) if isinstance(it.get("end"), dict) else {}

        events.append(
            {
                "id": it.get("id"),
                "summary": it.get("summary"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": it.get("location"),
                "htmlLink": it.get("htmlLink"),
                "status": it.get("status"),
            }
        )

    return {
        "ok": True,
        "calendar_id": cal_id,
        "count": len(events),
        "events": events,
    }


def find_free_slots(
    *,
    time_min: str,
    time_max: str,
    duration_minutes: int,
    suggestions: int = 3,
    calendar_id: Optional[str] = None,
) -> dict[str, Any]:
    """Find free time slots within a window.

    MVP behavior:
    - Treats all-day events as busy.
    - Uses Google Calendar events list with singleEvents=True.
    - Returns the first N slots that fit duration.
    """

    resp = list_events(
        calendar_id=calendar_id,
        max_results=250,
        time_min=time_min,
        time_max=time_max,
        query=None,
        single_events=True,
        show_deleted=False,
        order_by="startTime",
    )
    events = resp.get("events") if isinstance(resp, dict) else None
    if not isinstance(events, list):
        events = []

    slots = _compute_free_slots(
        events=[e for e in events if isinstance(e, dict)],
        time_min=time_min,
        time_max=time_max,
        duration_minutes=int(duration_minutes),
        suggestions=int(suggestions),
    )

    return {
        "ok": True,
        "slots": slots,
    }


def create_event(
    *,
    summary: str,
    start: str,
    end: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    calendar_id: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> dict[str, Any]:
    """Create a calendar event (write).

    - `start` and `end` must be RFC3339 strings (timezone offset recommended).
    - If `end` is not provided, `duration_minutes` must be provided.
    """

    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary_required")

    start_dt = _parse_rfc3339(start)

    if end is not None and str(end).strip():
        end_dt = _parse_rfc3339(end)
    else:
        if duration_minutes is None:
            raise ValueError("end_or_duration_required")
        if int(duration_minutes) <= 0:
            raise ValueError("duration_minutes_must_be_positive")
        end_dt = start_dt + timedelta(minutes=int(duration_minutes))

    if end_dt <= start_dt:
        raise ValueError("end_must_be_after_start")

    cal_id = (
        calendar_id
        or os.getenv("BANTZ_GOOGLE_CALENDAR_ID")
        or DEFAULT_CALENDAR_ID
    )

    from bantz.google.auth import get_credentials
    creds = get_credentials(scopes=WRITE_SCOPES)

    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google calendar dependencies are not installed. Install with: "
            "pip install -e '.[calendar]'"
        ) from e

    body: dict[str, Any] = {
        "summary": summary.strip(),
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    if description:
        body["description"] = str(description)
    if location:
        body["location"] = str(location)

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    created = service.events().insert(calendarId=cal_id, body=body).execute()
    if not isinstance(created, dict):
        raise RuntimeError("calendar_insert_failed")

    start_obj = created.get("start") if isinstance(created.get("start"), dict) else {}
    end_obj = created.get("end") if isinstance(created.get("end"), dict) else {}

    return {
        "ok": True,
        "id": created.get("id"),
        "htmlLink": created.get("htmlLink"),
        "summary": created.get("summary") or summary.strip(),
        "start": start_obj.get("dateTime") or start_obj.get("date") or start_dt.isoformat(),
        "end": end_obj.get("dateTime") or end_obj.get("date") or end_dt.isoformat(),
    }
