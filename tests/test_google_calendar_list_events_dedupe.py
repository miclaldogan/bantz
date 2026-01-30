from __future__ import annotations

from bantz.google import calendar as cal


def test_dedupe_normalized_events_by_id_or_key():
    events = [
        {
            "id": "evt-1",
            "summary": "Bantz Test",
            "start": "2026-01-28T18:00:00+03:00",
            "end": "2026-01-28T19:00:00+03:00",
        },
        {
            "id": "evt-1",
            "summary": "Bantz Test",
            "start": "2026-01-28T18:00:00+03:00",
            "end": "2026-01-28T19:00:00+03:00",
        },
        {
            "id": None,
            "summary": "Bantz Key",
            "start": "2026-01-28T20:00:00+03:00",
            "end": "2026-01-28T20:30:00+03:00",
        },
        {
            "id": None,
            "summary": "Bantz Key",
            "start": "2026-01-28T20:00:00+03:00",
            "end": "2026-01-28T20:30:00+03:00",
        },
    ]

    deduped = cal._dedupe_normalized_events(events)
    assert len(deduped) == 2
