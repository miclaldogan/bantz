from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo


def evening_window(d: date, tz: tzinfo) -> tuple[str, str]:
    """Return an evening time window for the given date.

    Definition (deterministic): 18:00–24:00 in the provided timezone.

    Returns RFC3339 datetimes (ISO 8601 with timezone offset).
    """

    if tz is None:
        raise ValueError("tz_required")

    start_dt = datetime.combine(d, time(18, 0), tzinfo=tz).replace(microsecond=0)
    end_dt = datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=tz).replace(microsecond=0)
    return start_dt.isoformat(), end_dt.isoformat()
