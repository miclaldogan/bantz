# SPDX-License-Identifier: MIT
"""Issue #654: Calendar slots should not be injected into Gmail tool schemas."""

from bantz.agent.registry import build_default_registry


_CALENDAR_SLOTS = {"date", "time", "duration", "title", "window_hint"}


def _get_properties(tool):
    params = tool.parameters or {}
    return params.get("properties", {}) or {}


def test_gmail_tools_do_not_include_calendar_slots():
    reg = build_default_registry()
    gmail_tools = [
        "gmail.unread_count",
        "gmail.list_messages",
        "gmail.smart_search",
        "gmail.get_message",
        "gmail.send",
    ]

    for name in gmail_tools:
        tool = reg.get(name)
        assert tool is not None, f"Missing tool: {name}"
        props = _get_properties(tool)
        leaked = _CALENDAR_SLOTS.intersection(props.keys())
        assert not leaked, f"Gmail tool '{name}' leaked calendar slots: {sorted(leaked)}"


def test_calendar_tools_still_include_calendar_slots():
    reg = build_default_registry()
    calendar_tools = [
        "calendar.list_events",
        "calendar.find_free_slots",
        "calendar.create_event",
        "calendar.update_event",
        "calendar.delete_event",
    ]

    for name in calendar_tools:
        tool = reg.get(name)
        assert tool is not None, f"Missing tool: {name}"
        props = _get_properties(tool)
        # At least one calendar slot should exist in each calendar tool schema
        assert _CALENDAR_SLOTS.intersection(props.keys()), (
            f"Calendar tool '{name}' missing expected calendar slots"
        )
