"""Shared tool registry builder — single source of truth for all runtime tools.

Moved from scripts/terminal_jarvis.py so that both the terminal entry point
and runtime_factory.py can import the same registry without importlib hacks.

Issue #575: Tool registry uses fragile importlib hack
"""

from __future__ import annotations

from bantz.agent.tools import Tool, ToolRegistry
from bantz.tools.registry import register_web_tools

from bantz.tools.calendar_tools import (
    calendar_create_event_tool,
    calendar_find_free_slots_tool,
    calendar_list_events_tool,
)
from bantz.tools.gmail_tools import (
    gmail_get_message_tool,
    gmail_list_messages_tool,
    gmail_send_tool,
    gmail_smart_search_tool,
    gmail_unread_count_tool,
)
from bantz.tools.system_tools import system_status
from bantz.tools.time_tools import time_now_tool


def build_default_registry() -> ToolRegistry:
    """Build the canonical ToolRegistry with all runtime tools.

    Returns a registry containing:
      - calendar.* (list_events, find_free_slots, create_event)
      - gmail.* (unread_count, list_messages, smart_search, get_message, send)
      - system.status
      - time.now
      - web.* (search, open — via register_web_tools)
    """
    reg = ToolRegistry()

    # Common orchestrator slots that may be passed through even for non-calendar
    # tools.  Mark these as "known" fields so SafetyGuard doesn't warn, but keep
    # them untyped because orchestrator slots may pass None.
    common_slot_props = {
        "date": {},
        "time": {},
        "duration": {},
        "title": {},
        "window_hint": {},
    }

    # ── Calendar tools ──────────────────────────────────────────────
    reg.register(
        Tool(
            name="calendar.list_events",
            description="Google Calendar: list upcoming events (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "window_hint": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "query": {"type": "string"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=calendar_list_events_tool,
        )
    )
    reg.register(
        Tool(
            name="calendar.find_free_slots",
            description="Google Calendar: find free time slots (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    "duration": {"type": "integer"},
                    "window_hint": {"type": "string"},
                    "date": {"type": "string"},
                    "suggestions": {"type": "integer"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=calendar_find_free_slots_tool,
        )
    )
    reg.register(
        Tool(
            name="calendar.create_event",
            description="Google Calendar: create an event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "duration": {"type": "integer"},
                    "window_hint": {"type": "string"},
                },
                "required": ["time"],
                "additionalProperties": True,
            },
            function=calendar_create_event_tool,
            requires_confirmation=True,
        )
    )

    # ── Gmail tools (read-only) ─────────────────────────────────────
    reg.register(
        Tool(
            name="gmail.unread_count",
            description="Gmail: unread count (read-only)",
            parameters={
                "type": "object",
                "properties": {**common_slot_props},
                "required": [],
                "additionalProperties": True,
            },
            function=gmail_unread_count_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.list_messages",
            description="Gmail: list inbox messages with optional search query and label filtering (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "max_results": {"type": "integer"},
                    "unread_only": {"type": "boolean"},
                    "query": {
                        "type": "string",
                        "description": (
                            "Gmail search query (from:, subject:, after:, label:). "
                            "Examples: 'from:linkedin', 'from:amazon subject:order', "
                            "'label:CATEGORY_UPDATES'"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Gmail category filter (Turkish/English): sosyal, "
                            "promosyonlar, güncellemeler, forumlar, social, "
                            "promotions, updates, forums"
                        ),
                    },
                    "label": {
                        "type": "string",
                        "description": (
                            "Gmail label filter (Turkish/English): gelen kutusu, "
                            "gönderilenler, yıldızlı, önemli, starred, important"
                        ),
                    },
                },
                "required": [],
                "additionalProperties": True,
            },
            function=gmail_list_messages_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.smart_search",
            description=(
                "Gmail: search with Turkish natural language label detection. "
                "Automatically detects 'sosyal', 'promosyonlar', 'güncellemeler', "
                "'yıldızlı' etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "natural_query": {
                        "type": "string",
                        "description": (
                            "Natural language search query in Turkish/English. "
                            "E.g., 'sosyal mailleri', 'promosyonlar kategorisi', "
                            "'yıldızlı mailleri'"
                        ),
                    },
                    "max_results": {"type": "integer"},
                    "unread_only": {"type": "boolean"},
                },
                "required": ["natural_query"],
                "additionalProperties": True,
            },
            function=gmail_smart_search_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.get_message",
            description="Gmail: read a message by id, or the latest one if id missing (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "message_id": {"type": "string"},
                    "prefer_unread": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=gmail_get_message_tool,
        )
    )

    # ── Gmail write ─────────────────────────────────────────────────
    reg.register(
        Tool(
            name="gmail.send",
            description="Gmail: send an email (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                    "bcc": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": True,
            },
            function=gmail_send_tool,
            requires_confirmation=True,
        )
    )

    # ── System / Time ───────────────────────────────────────────────
    reg.register(
        Tool(
            name="system.status",
            description="System health: loadavg, CPU count, memory usage (best-effort)",
            parameters={
                "type": "object",
                "properties": {"include_env": {"type": "boolean"}},
                "required": [],
                "additionalProperties": True,
            },
            function=system_status,
        )
    )
    reg.register(
        Tool(
            name="time.now",
            description="Time: current local time/date (timezone-aware)",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": True,
            },
            function=time_now_tool,
        )
    )

    # ── Web tools ───────────────────────────────────────────────────
    register_web_tools(reg)

    return reg
