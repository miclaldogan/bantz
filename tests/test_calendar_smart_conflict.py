from __future__ import annotations

from bantz.google import calendar as cal


def test_detect_conflicting_events_respects_half_open_interval() -> None:
    events = [
        {
            "id": "e1",
            "summary": "A",
            "start": "2026-01-28T10:00:00+03:00",
            "end": "2026-01-28T11:00:00+03:00",
        }
    ]

    # Touching at the boundary should not count as overlap.
    assert (
        cal.detect_conflicting_events(
            events=events,
            start="2026-01-28T11:00:00+03:00",
            end="2026-01-28T11:30:00+03:00",
        )
        == []
    )
    assert (
        cal.detect_conflicting_events(
            events=events,
            start="2026-01-28T09:30:00+03:00",
            end="2026-01-28T10:00:00+03:00",
        )
        == []
    )

    # Real overlap.
    conflicts = cal.detect_conflicting_events(
        events=events,
        start="2026-01-28T10:30:00+03:00",
        end="2026-01-28T11:30:00+03:00",
    )
    assert conflicts
    assert conflicts[0].get("id") == "e1"


def test_suggest_alternative_slots_uses_morning_and_afternoon_windows() -> None:
    # Day 1 is fully busy inside preferred windows.
    events = [
        {"start": "2026-01-28T08:00:00+03:00", "end": "2026-01-28T12:00:00+03:00"},
        {"start": "2026-01-28T13:00:00+03:00", "end": "2026-01-28T18:00:00+03:00"},
    ]

    slots = cal.suggest_alternative_slots(
        events=events,
        time_min="2026-01-28T09:00:00+03:00",
        duration_minutes=60,
        suggestions=3,
        days=7,
        preferred_windows=[("08:00", "12:00"), ("13:00", "18:00")],
    )

    assert len(slots) == 3
    assert slots[0]["start"].startswith("2026-01-29T08:00")
    assert slots[1]["start"].startswith("2026-01-29T13:00")
    assert slots[2]["start"].startswith("2026-01-30T08:00")
