from __future__ import annotations

from bantz.google import calendar as cal


def test_compute_free_slots_human_hours_blocks_midnight_by_default():
    slots = cal._compute_free_slots(
        events=[],
        time_min="2026-01-29T00:00:00+03:00",
        time_max="2026-01-29T20:00:00+03:00",
        duration_minutes=120,
        suggestions=3,
    )
    assert slots
    assert slots[0]["start"].startswith("2026-01-29T07:30")
    assert slots[0]["end"].startswith("2026-01-29T09:30")


def test_compute_free_slots_human_hours_respects_custom_preferred_window():
    slots = cal._compute_free_slots(
        events=[],
        time_min="2026-01-29T00:00:00+03:00",
        time_max="2026-01-29T20:00:00+03:00",
        duration_minutes=60,
        suggestions=3,
        preferred_start="10:00",
        preferred_end="12:00",
    )
    assert slots
    assert slots[0]["start"].startswith("2026-01-29T10:00")
    assert slots[0]["end"].startswith("2026-01-29T11:00")
