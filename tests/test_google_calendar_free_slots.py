from __future__ import annotations

from bantz.google import calendar as cal


def test_compute_free_slots_no_events_returns_first_slot():
    slots = cal._compute_free_slots(
        events=[],
        time_min="2026-01-28T18:00:00+03:00",
        time_max="2026-01-28T22:00:00+03:00",
        duration_minutes=60,
        suggestions=3,
    )
    assert slots
    assert slots[0]["start"].startswith("2026-01-28T18:00")


def test_compute_free_slots_merges_overlaps_and_finds_gap():
    events = [
        {"start": "2026-01-28T18:00:00+03:00", "end": "2026-01-28T18:30:00+03:00"},
        {"start": "2026-01-28T18:20:00+03:00", "end": "2026-01-28T19:00:00+03:00"},
        {"start": "2026-01-28T20:00:00+03:00", "end": "2026-01-28T20:30:00+03:00"},
    ]
    slots = cal._compute_free_slots(
        events=events,
        time_min="2026-01-28T18:00:00+03:00",
        time_max="2026-01-28T21:00:00+03:00",
        duration_minutes=30,
        suggestions=3,
    )
    # First free slot is 19:00-19:30
    assert slots[0]["start"].startswith("2026-01-28T19:00")
    assert slots[0]["end"].startswith("2026-01-28T19:30")


def test_compute_free_slots_all_day_event_blocks_day():
    events = [
        {"start": "2026-01-28", "end": "2026-01-29"},
    ]
    slots = cal._compute_free_slots(
        events=events,
        time_min="2026-01-28T09:00:00+03:00",
        time_max="2026-01-28T21:00:00+03:00",
        duration_minutes=30,
        suggestions=3,
    )
    assert slots == []
