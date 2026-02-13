from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
import os

from bantz.google.calendar_cache import cache_created_event, get_merged_events


DEFAULT_CALENDAR_ID = "primary"
READONLY_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
WRITE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _to_local_iso(iso_str: str | None) -> str | None:
    """Convert an ISO datetime string to local timezone.

    Google Calendar API may return UTC timestamps (e.g. '2026-02-13T18:00:00Z').
    This converts to local timezone (e.g. '2026-02-13T21:00:00+03:00') so that
    downstream consumers (summarizer, finalizer) display correct local times.
    """
    if not isinstance(iso_str, str) or "T" not in iso_str:
        return iso_str
    try:
        # Python 3.10 fromisoformat doesn't support "Z" suffix
        clean = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is not None:
            local_dt = dt.astimezone()
            return local_dt.replace(microsecond=0).isoformat()
        return iso_str
    except (ValueError, TypeError):
        return iso_str


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_rfc3339(value: str) -> str:
    """Normalize a datetime string to RFC3339 with seconds.

    LLMs often emit ISO strings without seconds (e.g. 2026-01-28T17:00+03:00).
    Google Calendar APIs are strict and can reject these with HTTP 400.
    """

    dt = _parse_rfc3339(value)
    return dt.replace(microsecond=0).isoformat()


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


def _validate_time_range(*, time_min: str, time_max: str) -> None:
    """Validate that a time window is logically ordered.

    This is intentionally strict to fail fast before hitting Google APIs.
    """

    min_dt = _parse_rfc3339(time_min)
    max_dt = _parse_rfc3339(time_max)
    if min_dt >= max_dt:
        raise ValueError("time_min must be < time_max")


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


# RRULE Helper Functions (Issue #165)


def build_rrule_daily(*, count: Optional[int] = None, until: Optional[str] = None) -> str:
    """Build RRULE for daily recurring events.

    Args:
        count: Number of occurrences (e.g., 10 for 10 days)
        until: End date in RFC3339 format (e.g., "20260301T000000Z")

    Returns:
        RRULE string (e.g., "RRULE:FREQ=DAILY;COUNT=10")

    Examples:
        >>> build_rrule_daily(count=10)
        'RRULE:FREQ=DAILY;COUNT=10'
        >>> build_rrule_daily(until="20260301T000000Z")
        'RRULE:FREQ=DAILY;UNTIL=20260301T000000Z'
    """
    if count is None and until is None:
        raise ValueError("Either count or until must be provided")
    if count is not None and until is not None:
        raise ValueError("Cannot specify both count and until")
    
    parts = ["RRULE:FREQ=DAILY"]
    if count is not None:
        parts.append(f"COUNT={int(count)}")
    elif until is not None:
        parts.append(f"UNTIL={until}")
    return ";".join(parts)


def build_rrule_weekly(
    *,
    byday: Optional[list[str]] = None,
    count: Optional[int] = None,
    until: Optional[str] = None,
    interval: int = 1,
) -> str:
    """Build RRULE for weekly recurring events.

    Args:
        byday: List of weekdays (MO, TU, WE, TH, FR, SA, SU)
        count: Number of occurrences
        until: End date in RFC3339 format
        interval: Repeat every N weeks (default: 1)

    Returns:
        RRULE string (e.g., "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=10")

    Examples:
        >>> build_rrule_weekly(byday=["MO"], count=10)
        'RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10'
        >>> build_rrule_weekly(byday=["MO", "WE", "FR"], until="20260301T000000Z")
        'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20260301T000000Z'
    """
    if not byday:
        raise ValueError("byday must be provided for weekly recurrence")
    if count is None and until is None:
        raise ValueError("Either count or until must be provided")
    if count is not None and until is not None:
        raise ValueError("Cannot specify both count and until")
    
    parts = ["RRULE:FREQ=WEEKLY"]
    if interval > 1:
        parts.append(f"INTERVAL={int(interval)}")
    if byday:
        valid_days = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
        days_upper = [d.upper() for d in byday]
        for day in days_upper:
            if day not in valid_days:
                raise ValueError(f"Invalid BYDAY value: {day}")
        parts.append(f"BYDAY={','.join(days_upper)}")
    if count is not None:
        parts.append(f"COUNT={int(count)}")
    elif until is not None:
        parts.append(f"UNTIL={until}")
    return ";".join(parts)


def build_rrule_monthly(
    *,
    byday: Optional[str] = None,
    bymonthday: Optional[int] = None,
    count: Optional[int] = None,
    until: Optional[str] = None,
) -> str:
    """Build RRULE for monthly recurring events.

    Args:
        byday: Weekday with position (e.g., "1MO" for first Monday, "-1FR" for last Friday)
        bymonthday: Day of month (1-31)
        count: Number of occurrences
        until: End date in RFC3339 format

    Returns:
        RRULE string (e.g., "RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12")

    Examples:
        >>> build_rrule_monthly(byday="1FR", count=12)  # First Friday of each month
        'RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12'
        >>> build_rrule_monthly(bymonthday=15, count=6)  # 15th of each month
        'RRULE:FREQ=MONTHLY;BYMONTHDAY=15;COUNT=6'
    """
    if byday is None and bymonthday is None:
        raise ValueError("Either byday or bymonthday must be provided for monthly recurrence")
    if byday is not None and bymonthday is not None:
        raise ValueError("Cannot specify both byday and bymonthday")
    if count is None and until is None:
        raise ValueError("Either count or until must be provided")
    if count is not None and until is not None:
        raise ValueError("Cannot specify both count and until")
    
    parts = ["RRULE:FREQ=MONTHLY"]
    if byday is not None:
        parts.append(f"BYDAY={byday}")
    elif bymonthday is not None:
        if not (1 <= int(bymonthday) <= 31):
            raise ValueError("bymonthday must be between 1 and 31")
        parts.append(f"BYMONTHDAY={int(bymonthday)}")
    if count is not None:
        parts.append(f"COUNT={int(count)}")
    elif until is not None:
        parts.append(f"UNTIL={until}")
    return ";".join(parts)


def _parse_hhmm(value: Optional[str], *, default: time) -> tuple[time, bool]:
    """Parse an HH:MM string into a time.

    Returns (t, is_24h_end) where is_24h_end is True only for the special
    end value "24:00".
    """

    if value is None:
        return default, False
    v = str(value).strip()
    if not v:
        return default, False
    if v == "24:00":
        return time(0, 0), True
    parts = v.split(":")
    if len(parts) != 2:
        raise ValueError("invalid_hhmm")
    h = int(parts[0])
    m = int(parts[1])
    if h < 0 or h > 23 or m < 0 or m > 59:
        raise ValueError("invalid_hhmm")
    return time(h, m), False


def _sleep_busy_intervals(
    *,
    window_start: datetime,
    window_end: datetime,
    preferred_start: time,
    preferred_end: time,
    preferred_end_is_24: bool,
) -> list[tuple[datetime, datetime]]:
    """Generate synthetic busy intervals outside preferred hours.

    Default intent: prevent suggestions like 00:00–02:00 by treating sleep
    hours as busy.
    """

    if window_end <= window_start:
        return []

    if not preferred_end_is_24 and preferred_end <= preferred_start:
        # Overnight preferred windows (e.g. 22:30–02:00) are out of scope for P0.
        raise ValueError("preferred_end_must_be_after_preferred_start")

    tzinfo = window_start.tzinfo or timezone.utc
    if not isinstance(tzinfo, timezone):
        tzinfo = timezone.utc

    day_cursor = datetime.combine(window_start.date(), time(0, 0), tzinfo=tzinfo)
    intervals: list[tuple[datetime, datetime]] = []

    while day_cursor < window_end:
        day_start = day_cursor
        day_end = day_start + timedelta(days=1)

        allowed_start = datetime.combine(day_start.date(), preferred_start, tzinfo=tzinfo)
        allowed_end = day_end if preferred_end_is_24 else datetime.combine(day_start.date(), preferred_end, tzinfo=tzinfo)

        # Busy before allowed_start.
        if allowed_start > day_start:
            intervals.append((day_start, allowed_start))
        # Busy after allowed_end.
        if allowed_end < day_end:
            intervals.append((allowed_end, day_end))

        day_cursor = day_end

    # Clip to the requested window.
    clipped: list[tuple[datetime, datetime]] = []
    for s, e in intervals:
        if e <= window_start or s >= window_end:
            continue
        clipped.append((max(s, window_start), min(e, window_end)))

    return _merge_intervals(clipped)


def _normalize_allowed_windows(
    windows: list[tuple[time, time]],
) -> list[tuple[time, time]]:
    """Normalize/merge allowed windows within a single day.

    Windows must be same-day (no overnight). Returns sorted, merged windows.
    """

    cleaned: list[tuple[time, time]] = []
    for s, e in windows:
        if not isinstance(s, time) or not isinstance(e, time):
            continue
        if e <= s:
            raise ValueError("allowed_window_end_must_be_after_start")
        cleaned.append((s, e))
    cleaned.sort(key=lambda t: (t[0].hour, t[0].minute, t[1].hour, t[1].minute))

    merged: list[tuple[time, time]] = []
    for s, e in cleaned:
        if not merged:
            merged.append((s, e))
            continue
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
            continue
        merged.append((s, e))
    return merged


def _busy_outside_allowed_windows(
    *,
    window_start: datetime,
    window_end: datetime,
    allowed_windows: list[tuple[time, time]],
) -> list[tuple[datetime, datetime]]:
    """Synthetic busy intervals outside allowed windows.

    This enables "union" preferred windows (e.g. 08:00–12:00 and 13:00–18:00)
    by marking everything else as busy.
    """

    if window_end <= window_start:
        return []
    normalized = _normalize_allowed_windows(allowed_windows)
    if not normalized:
        return []

    tzinfo = window_start.tzinfo or timezone.utc
    if not isinstance(tzinfo, timezone):
        tzinfo = timezone.utc

    day_cursor = datetime.combine(window_start.date(), time(0, 0), tzinfo=tzinfo)
    intervals: list[tuple[datetime, datetime]] = []

    while day_cursor < window_end:
        day_start = day_cursor
        day_end = day_start + timedelta(days=1)

        cursor = day_start
        for ws, we in normalized:
            ws_dt = datetime.combine(day_start.date(), ws, tzinfo=tzinfo)
            we_dt = datetime.combine(day_start.date(), we, tzinfo=tzinfo)
            if ws_dt > cursor:
                intervals.append((cursor, ws_dt))
            if we_dt > cursor:
                cursor = we_dt

        if cursor < day_end:
            intervals.append((cursor, day_end))

        day_cursor = day_end

    # Clip to the requested window.
    clipped: list[tuple[datetime, datetime]] = []
    for s, e in intervals:
        if e <= window_start or s >= window_end:
            continue
        clipped.append((max(s, window_start), min(e, window_end)))
    return _merge_intervals(clipped)


def _event_interval_with_payload(
    ev: dict[str, Any],
    *,
    tz: timezone,
) -> Optional[tuple[datetime, datetime, dict[str, Any]]]:
    s = ev.get("start")
    e = ev.get("end")
    if not isinstance(s, str) or not isinstance(e, str):
        return None

    # All-day events show up as YYYY-MM-DD.
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            sd = _parse_date(s)
            ed = _parse_date(e)
            start_dt, _ = _to_all_day_range(sd, tz=tz)
            end_dt, _ = _to_all_day_range(ed, tz=tz)
            if end_dt <= start_dt:
                return None
            return start_dt, end_dt, ev
        except Exception:
            return None

    try:
        start_dt = _parse_rfc3339(s)
        end_dt = _parse_rfc3339(e)
    except Exception:
        return None
    if end_dt <= start_dt:
        return None
    return start_dt, end_dt, ev


def detect_conflicting_events(
    *,
    events: list[dict[str, Any]],
    start: str,
    end: str,
    max_conflicts: int = 3,
) -> list[dict[str, Any]]:
    """Return up to N events that overlap the desired [start,end) interval."""

    desired_start = _parse_rfc3339(start)
    desired_end = _parse_rfc3339(end)
    if desired_end <= desired_start:
        return []

    tzinfo = desired_start.tzinfo or timezone.utc
    if not isinstance(tzinfo, timezone):
        tzinfo = timezone.utc

    conflicts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        it = _event_interval_with_payload(ev, tz=tzinfo)
        if it is None:
            continue
        s, e, payload = it
        # Overlap test: [a,b) overlaps [c,d) iff max(a,c) < min(b,d)
        if max(s, desired_start) < min(e, desired_end):
            ev_id = payload.get("id")
            if isinstance(ev_id, str) and ev_id:
                if ev_id in seen_ids:
                    continue
                seen_ids.add(ev_id)
            conflicts.append(payload)
            if len(conflicts) >= int(max_conflicts):
                break
    return conflicts


def suggest_alternative_slots(
    *,
    events: list[dict[str, Any]],
    time_min: str,
    duration_minutes: int,
    suggestions: int = 3,
    days: int = 7,
    preferred_windows: Optional[list[tuple[str, str]]] = None,
) -> list[dict[str, str]]:
    """Suggest the next N free slots starting from time_min.

    Unlike `_compute_free_slots` (single window), this supports a union of
    preferred windows (e.g. morning + afternoon).
    """

    if duration_minutes <= 0:
        raise ValueError("duration_minutes_must_be_positive")
    if suggestions <= 0:
        return []
    if days <= 0:
        return []

    window_start = _parse_rfc3339(time_min)
    window_end = window_start + timedelta(days=int(days))

    tzinfo = window_start.tzinfo or timezone.utc
    if not isinstance(tzinfo, timezone):
        tzinfo = timezone.utc

    busy = _merge_intervals(_extract_busy_intervals(events, tz=tzinfo))

    # Preferred union windows (Issue #168): default to 08-12 and 13-18.
    win_pairs = preferred_windows
    if not isinstance(win_pairs, list) or not win_pairs:
        win_pairs = [("08:00", "12:00"), ("13:00", "18:00")]

    allowed: list[tuple[time, time]] = []
    for a, b in win_pairs:
        s_t, _ = _parse_hhmm(a, default=time(8, 0))
        e_t, is_24 = _parse_hhmm(b, default=time(18, 0))
        if is_24:
            raise ValueError("preferred_windows_end_cannot_be_24_for_multi_window")
        allowed.append((s_t, e_t))

    busy.extend(
        _busy_outside_allowed_windows(
            window_start=window_start,
            window_end=window_end,
            allowed_windows=allowed,
        )
    )
    busy.sort(key=lambda t: t[0])
    busy = _merge_intervals(busy)

    # Clip busy intervals to the window.
    clipped: list[tuple[datetime, datetime]] = []
    for s, e in busy:
        if e <= window_start or s >= window_end:
            continue
        clipped.append((max(s, window_start), min(e, window_end)))
    clipped = _merge_intervals(clipped)

    required = timedelta(minutes=int(duration_minutes))
    out: list[dict[str, str]] = []

    cursor = window_start
    for s, e in clipped:
        if s > cursor and (s - cursor) >= required:
            slot_end = cursor + required
            out.append({"start": cursor.replace(microsecond=0).isoformat(), "end": slot_end.replace(microsecond=0).isoformat()})
            if len(out) >= int(suggestions):
                return out
        if e > cursor:
            cursor = e

    if window_end > cursor and (window_end - cursor) >= required:
        slot_end = cursor + required
        out.append({"start": cursor.replace(microsecond=0).isoformat(), "end": slot_end.replace(microsecond=0).isoformat()})

    return out[: int(suggestions)]


def _dedupe_normalized_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe normalized event dicts.

    Prefers stable `id` when present, otherwise falls back to (start,end,summary).
    """

    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for ev in events:
        ev_id = ev.get("id")
        if isinstance(ev_id, str) and ev_id:
            if ev_id in seen_ids:
                continue
            seen_ids.add(ev_id)
            deduped.append(ev)
            continue

        s = ev.get("start")
        e = ev.get("end")
        summary = ev.get("summary") or ""
        if isinstance(s, str) and isinstance(e, str):
            key = (s, e, str(summary))
            if key in seen_keys:
                continue
            seen_keys.add(key)
        deduped.append(ev)

    return deduped


def _compute_free_slots(
    *,
    events: list[dict[str, Any]],
    time_min: str,
    time_max: str,
    duration_minutes: int,
    suggestions: int,
    preferred_start: Optional[str] = None,
    preferred_end: Optional[str] = None,
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

    # Human hours: treat sleep hours as busy by default.
    pref_start_t, _ = _parse_hhmm(preferred_start, default=time(7, 30))
    pref_end_t, pref_end_is_24 = _parse_hhmm(preferred_end, default=time(22, 30))
    busy.extend(
        _sleep_busy_intervals(
            window_start=window_start,
            window_end=window_end,
            preferred_start=pref_start_t,
            preferred_end=pref_end_t,
            preferred_end_is_24=pref_end_is_24,
        )
    )
    busy = _merge_intervals(busy)

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
    interactive: bool = True,
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
    creds = get_credentials(scopes=READONLY_SCOPES, interactive=interactive)

    # Lazy import to keep base installs light.
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google calendar dependencies are not installed. Install with: "
            "pip install -e '.[calendar]'"
        ) from e

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    tmn = _normalize_rfc3339(time_min) if time_min else _now_rfc3339()
    tmx = _normalize_rfc3339(time_max) if time_max else None
    if tmx is not None:
        _validate_time_range(time_min=tmn, time_max=tmx)
    params: dict[str, Any] = {
        "calendarId": cal_id,
        "timeMin": tmn,
        "maxResults": int(max_results),
        "singleEvents": bool(single_events),
        "showDeleted": bool(show_deleted),
        "orderBy": order_by,
    }
    if tmx is not None:
        params["timeMax"] = tmx
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
                "start": _to_local_iso(start.get("dateTime") or start.get("date")),
                "end": _to_local_iso(end.get("dateTime") or end.get("date")),
                "location": it.get("location"),
                "htmlLink": it.get("htmlLink"),
                "status": it.get("status"),
            }
        )

    events = _dedupe_normalized_events(events)

    # Merge with cached events for immediate visibility of new events (#315)
    events = get_merged_events(
        events,
        time_min=tmn,
        time_max=tmx,
        calendar_id=cal_id,
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
    preferred_start: Optional[str] = None,
    preferred_end: Optional[str] = None,
    interactive: bool = True,
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
        interactive=interactive,
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
        preferred_start=preferred_start,
        preferred_end=preferred_end,
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
    all_day: bool = False,
    recurrence: Optional[list[str]] = None,
    interactive: bool = True,
) -> dict[str, Any]:
    """Create a calendar event (write).

    Time-based events:
    - `start` and `end` must be RFC3339 strings (timezone offset recommended).
    - If `end` is not provided, `duration_minutes` must be provided.

    All-day events (Issue #164):
    - Set `all_day=True`
    - `start` must be a date string in YYYY-MM-DD format
    - `end` is optional; if not provided, creates single-day all-day event
    - `end` is exclusive (e.g., "2026-02-23" to "2026-02-26" = Feb 23-25)
    - `duration_minutes` is ignored for all-day events

    Recurring events (Issue #165):
    - Set `recurrence` to a list of RRULE strings (RFC5545 format)
    - Example: `["RRULE:FREQ=WEEKLY;BYDAY=MO"]` (every Monday)
    - Supports FREQ: DAILY, WEEKLY, MONTHLY, YEARLY
    - Supports BYDAY: MO, TU, WE, TH, FR, SA, SU
    - Supports COUNT: number of occurrences
    - Supports UNTIL: end date (RFC3339 format)

    Examples:
    ```python
    # Time-based event
    create_event(summary="Meeting", start="2026-02-03T14:00:00+03:00", duration_minutes=60)

    # Single-day all-day event
    create_event(summary="Conference", start="2026-02-03", all_day=True)

    # Multi-day all-day event
    create_event(summary="Vacation", start="2026-02-23", end="2026-02-26", all_day=True)

    # Recurring weekly event (every Monday at 10:00, 10 times)
    create_event(
        summary="Standup",
        start="2026-02-03T10:00:00+03:00",
        duration_minutes=30,
        recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10"]
    )

    # Recurring daily event until specific date
    create_event(
        summary="Morning Email Check",
        start="2026-02-03T09:00:00+03:00",
        duration_minutes=15,
        recurrence=["RRULE:FREQ=DAILY;UNTIL=20260301T000000Z"]
    )
    ```
    """

    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary_required")

    # Validate recurrence format if provided
    if recurrence is not None:
        if not isinstance(recurrence, list):
            raise ValueError("recurrence_must_be_list")
        for rule in recurrence:
            if not isinstance(rule, str) or not rule.strip():
                raise ValueError("recurrence_rule_must_be_string")
            # Basic RRULE format validation
            rule_upper = rule.strip().upper()
            if not rule_upper.startswith("RRULE:"):
                raise ValueError("recurrence_rule_must_start_with_rrule")
            # Check for required FREQ parameter
            if "FREQ=" not in rule_upper:
                raise ValueError("recurrence_rule_missing_freq")

    # All-day event handling
    if all_day:
        # Parse start as date
        try:
            start_date = _parse_date(start)
        except ValueError:
            raise ValueError("all_day_start_must_be_date_format")

        # Parse end as date if provided, otherwise next day (single-day event)
        if end is not None and str(end).strip():
            try:
                end_date = _parse_date(end)
            except ValueError:
                raise ValueError("all_day_end_must_be_date_format")
        else:
            # Single-day all-day event: end = start + 1 day (exclusive)
            end_date = start_date + timedelta(days=1)

        # Validate date range
        if end_date <= start_date:
            raise ValueError("end_date_must_be_after_start_date")

        cal_id = (
            calendar_id
            or os.getenv("BANTZ_GOOGLE_CALENDAR_ID")
            or DEFAULT_CALENDAR_ID
        )

        from bantz.google.auth import get_credentials
        creds = get_credentials(scopes=WRITE_SCOPES, interactive=interactive)

        try:
            from googleapiclient.discovery import build  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Google calendar dependencies are not installed. Install with: "
                "pip install -e '.[calendar]'"
            ) from e

        # All-day event body uses "date" instead of "dateTime"
        body: dict[str, Any] = {
            "summary": summary.strip(),
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
        if description:
            body["description"] = str(description)
        if location:
            body["location"] = str(location)
        if recurrence:
            body["recurrence"] = recurrence

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        created = service.events().insert(calendarId=cal_id, body=body).execute()
        if not isinstance(created, dict):
            raise RuntimeError("calendar_insert_failed")

        start_obj = created.get("start") if isinstance(created.get("start"), dict) else {}
        end_obj = created.get("end") if isinstance(created.get("end"), dict) else {}

        event_start = start_obj.get("date") or start_obj.get("dateTime") or start_date.isoformat()
        event_end = end_obj.get("date") or end_obj.get("dateTime") or end_date.isoformat()
        event_id = created.get("id")

        # Cache newly created event for immediate visibility (#315)
        if event_id:
            cache_created_event(
                event_id=event_id,
                summary=created.get("summary") or summary.strip(),
                start=event_start,
                end=event_end,
                location=location,
                description=description,
                calendar_id=cal_id,
            )

        return {
            "ok": True,
            "id": event_id,
            "htmlLink": created.get("htmlLink"),
            "summary": created.get("summary") or summary.strip(),
            "start": event_start,
            "end": event_end,
            "all_day": True,
            "recurrence": created.get("recurrence"),
        }

    # Time-based event handling (original logic)
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
    creds = get_credentials(scopes=WRITE_SCOPES, interactive=interactive)

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
    if recurrence:
        body["recurrence"] = recurrence

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    created = service.events().insert(calendarId=cal_id, body=body).execute()
    if not isinstance(created, dict):
        raise RuntimeError("calendar_insert_failed")

    start_obj = created.get("start") if isinstance(created.get("start"), dict) else {}
    end_obj = created.get("end") if isinstance(created.get("end"), dict) else {}

    event_start = _to_local_iso(start_obj.get("dateTime") or start_obj.get("date")) or start_dt.isoformat()
    event_end = _to_local_iso(end_obj.get("dateTime") or end_obj.get("date")) or end_dt.isoformat()
    event_id = created.get("id")

    # Cache newly created event for immediate visibility (#315)
    if event_id:
        cache_created_event(
            event_id=event_id,
            summary=created.get("summary") or summary.strip(),
            start=event_start,
            end=event_end,
            location=location,
            description=description,
            calendar_id=cal_id,
        )

    return {
        "ok": True,
        "id": event_id,
        "htmlLink": created.get("htmlLink"),
        "summary": created.get("summary") or summary.strip(),
        "start": event_start,
        "end": event_end,
        "all_day": False,
        "recurrence": created.get("recurrence"),
    }


def delete_event(
    *,
    event_id: str,
    calendar_id: Optional[str] = None,
) -> dict[str, Any]:
    """Delete a calendar event (write)."""

    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id_required")

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

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    service.events().delete(calendarId=cal_id, eventId=str(event_id).strip()).execute()

    # Remove from cache if present (#315)
    from bantz.google.calendar_cache import get_calendar_cache
    get_calendar_cache().remove_event(str(event_id).strip())

    return {"ok": True, "id": str(event_id).strip(), "calendar_id": cal_id}


def update_event(
    *,
    event_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    summary: Optional[str] = None,
    calendar_id: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> dict[str, Any]:
    """Update a calendar event (write) with partial updates.

    Supports partial updates - only specified fields are modified.
    If start is provided, end must also be provided (and vice versa).
    
    Args:
        event_id: Google Calendar event ID
        start: Optional RFC3339 start datetime
        end: Optional RFC3339 end datetime
        summary: Optional new event title
        calendar_id: Optional calendar ID (default: primary)
        description: Optional event description
        location: Optional event location
    
    Returns:
        dict with ok, id, htmlLink, summary, start, end, calendar_id
    
    Examples:
        >>> # Update only summary
        >>> update_event(event_id="evt123", summary="New Title")
        
        >>> # Update only location
        >>> update_event(event_id="evt123", location="Zoom")
        
        >>> # Update time (both start and end required)
        >>> update_event(event_id="evt123", start="2026-02-01T15:00:00+03:00", end="2026-02-01T16:00:00+03:00")
        
        >>> # Update multiple fields
        >>> update_event(event_id="evt123", summary="New Title", location="Office 301", start="...", end="...")
    """

    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id_required")
    
    # Validate time range if both provided
    if start is not None and end is not None:
        start_dt = _parse_rfc3339(start)
        end_dt = _parse_rfc3339(end)
        if end_dt <= start_dt:
            raise ValueError("end_must_be_after_start")
    elif start is not None or end is not None:
        # If only one is provided, raise error
        raise ValueError("start_and_end_must_be_provided_together")

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

    # Build update body - only include fields that are provided
    body: dict[str, Any] = {}
    
    if start is not None and end is not None:
        start_dt = _parse_rfc3339(start)
        end_dt = _parse_rfc3339(end)
        body["start"] = {"dateTime": start_dt.replace(microsecond=0).isoformat()}
        body["end"] = {"dateTime": end_dt.replace(microsecond=0).isoformat()}
    
    if summary is not None:
        s = str(summary).strip()
        if s:
            body["summary"] = s
        else:
            raise ValueError("summary_cannot_be_empty")
    
    if description is not None:
        body["description"] = str(description)
    
    if location is not None:
        body["location"] = str(location)
    
    # Check that at least one field is being updated
    if not body:
        raise ValueError("at_least_one_field_must_be_updated")

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    
    try:
        updated = service.events().patch(
            calendarId=cal_id,
            eventId=str(event_id).strip(),
            body=body
        ).execute()
    except Exception as e:
        # Handle common Google API errors
        error_msg = str(e).lower()
        if "not found" in error_msg or "404" in error_msg:
            raise ValueError(f"event_not_found: {event_id}") from e
        raise
    
    if not isinstance(updated, dict):
        raise RuntimeError("calendar_update_failed")

    start_obj = updated.get("start") if isinstance(updated.get("start"), dict) else {}
    end_obj = updated.get("end") if isinstance(updated.get("end"), dict) else {}

    return {
        "ok": True,
        "id": updated.get("id") or str(event_id).strip(),
        "htmlLink": updated.get("htmlLink"),
        "summary": updated.get("summary"),
        "start": _to_local_iso(start_obj.get("dateTime") or start_obj.get("date")),
        "end": _to_local_iso(end_obj.get("dateTime") or end_obj.get("date")),
        "location": updated.get("location"),
        "description": updated.get("description"),
        "calendar_id": cal_id,
    }
