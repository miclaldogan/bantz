from __future__ import annotations

from datetime import date, timedelta, timezone

from bantz.time_windows import evening_window


def test_evening_window_tr_timezone_rfc3339() -> None:
    tz_tr = timezone(timedelta(hours=3))
    start, end = evening_window(date(2026, 1, 28), tz_tr)
    assert start == "2026-01-28T18:00:00+03:00"
    assert end == "2026-01-29T00:00:00+03:00"
