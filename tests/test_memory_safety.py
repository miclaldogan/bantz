from __future__ import annotations

from bantz.memory.safety import safe_tool_episode


def test_safe_tool_episode_avoids_titles_and_masks_emails():
    text = safe_tool_episode(
        tool_name="calendar.create_event",
        params={
            "summary": "Dentist with alice@example.com",
            "location": "Somewhere",
            "start": "2026-02-01T10:00:00",
            "end": "2026-02-01T10:30:00",
        },
        result={"ok": True},
    )

    assert "calendar.create_event" in text
    assert "alice@example.com" not in text
    assert "<EMAIL>" not in text  # summary should not be copied at all
    assert "Dentist" not in text
    assert "Somewhere" not in text
    assert "2026-02-01T10:00:00" in text
    assert "2026-02-01T10:30:00" in text
