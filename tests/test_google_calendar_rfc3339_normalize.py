from __future__ import annotations

import re

from bantz.google import calendar


def test_normalize_rfc3339_adds_seconds_and_preserves_offset() -> None:
    # LLMs often emit timestamps without seconds.
    v = "2026-01-28T17:00+03:00"
    out = calendar._normalize_rfc3339(v)
    assert out == "2026-01-28T17:00:00+03:00"
    assert re.search(r"T\d{2}:\d{2}:\d{2}", out)


def test_normalize_rfc3339_accepts_z_suffix() -> None:
    v = "2026-01-28T17:00Z"
    out = calendar._normalize_rfc3339(v)
    assert out == "2026-01-28T17:00:00+00:00"
    assert out.endswith("+00:00")


def test_time_range_validation_requires_min_lt_max() -> None:
    tmn = calendar._normalize_rfc3339("2026-01-28T17:00+03:00")
    tmx = calendar._normalize_rfc3339("2026-01-28T17:00+03:00")

    try:
        calendar._validate_time_range(time_min=tmn, time_max=tmx)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert str(e) == "time_min must be < time_max"
