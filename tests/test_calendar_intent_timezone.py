from __future__ import annotations

from bantz.brain.calendar_intent import build_intent, iso_from_date_hhmm_in_timezone


def test_build_intent_extracts_timezone_city() -> None:
    intent = build_intent("15:45 koşu ekle 30 dk New York")
    assert intent.type == "create_event"
    assert intent.params.get("timezone") == "America/New_York"


def test_build_intent_extracts_timezone_abbrev() -> None:
    intent = build_intent("yarın 09:00 toplantı ekle 30 dk PST")
    assert intent.type == "create_event"
    assert intent.params.get("timezone") == "America/Los_Angeles"


def test_build_intent_timezone_is_none_when_absent() -> None:
    intent = build_intent("15:45 koşu ekle 30 dk")
    assert intent.type == "create_event"
    assert intent.params.get("timezone") is None


def test_iso_from_date_hhmm_in_timezone_iana() -> None:
    iso = iso_from_date_hhmm_in_timezone(
        date_iso="2026-01-28",
        hhmm="15:45",
        tz_name="America/New_York",
    )
    assert iso.startswith("2026-01-28T15:45:00")
    assert iso.endswith("-05:00")


def test_iso_from_date_hhmm_in_timezone_fixed_offset() -> None:
    iso = iso_from_date_hhmm_in_timezone(
        date_iso="2026-01-28",
        hhmm="15:45",
        tz_name="GMT+05:30",
    )
    assert iso.startswith("2026-01-28T15:45:00")
    assert iso.endswith("+05:30")
