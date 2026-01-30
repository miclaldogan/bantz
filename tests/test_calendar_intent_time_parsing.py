from __future__ import annotations

from bantz.brain.calendar_intent import parse_hhmm


def test_parse_hhmm_accepts_dot_comma_and_space() -> None:
    assert parse_hhmm("23:50") == "23:50"
    assert parse_hhmm("23.50") == "23:50"
    assert parse_hhmm("23,50") == "23:50"
    assert parse_hhmm("23 50") == "23:50"
