"""Shared runtime tool registry — single source of truth for executable tools.

Architecture (Issue #633)
─────────────────────────
This module provides the **runtime** tool registry whose tools are
directly executed by :class:`~bantz.brain.orchestrator_loop.OrchestratorLoop`
via ``tool.function(**params)``.

Every tool registered here has a real ``function=`` handler from
``bantz.tools.*`` (wrapper modules that add Turkish date parsing,
idempotency, error wrapping over the raw ``bantz.google.*`` functions).

Callers
~~~~~~~
- ``brain/runtime_factory.py`` — builds the production runtime
- ``scripts/terminal_jarvis.py`` — terminal REPL

See Also
~~~~~~~~
- ``agent/builtin_tools.py`` → ``build_planner_registry()``
  The **planner** catalog (69 tools, schema-only usage) used by
  ``router/engine.py`` and ``agent/controller.py`` for LLM prompting.
  Its 10 overlapping tool names (calendar.*, gmail core) intentionally
  match so agent-planned steps map to router intents.

Issue #575: Tool registry uses fragile importlib hack
"""

from __future__ import annotations

from bantz.agent.tools import Tool, ToolRegistry
from bantz.tools.registry import register_web_tools

from bantz.tools.calendar_tools import (
    calendar_create_event_tool,
    calendar_delete_event_tool,
    calendar_find_free_slots_tool,
    calendar_list_events_tool,
    calendar_update_event_tool,
)
from bantz.tools.gmail_tools import (
    gmail_get_message_tool,
    gmail_list_messages_tool,
    gmail_send_tool,
    gmail_smart_search_tool,
    gmail_unread_count_tool,
)
from bantz.tools.system_tools import system_screenshot_tool, system_status
from bantz.tools.time_tools import time_now_tool


def build_default_registry() -> ToolRegistry:
    """Build the canonical ToolRegistry with all runtime tools.

    Returns a registry containing:
      - calendar.* (list_events, find_free_slots, create_event, update_event, delete_event)
      - gmail.* (unread_count, list_messages, smart_search, get_message, send)
      - system.status, system.screenshot
      - time.now
      - web.* (search, open — via register_web_tools)
    """
    reg = ToolRegistry()

    # Calendar-only orchestrator slots (Issue #654): these should NOT be
    # injected into Gmail tool schemas to avoid irrelevant slot hallucinations.
    # Keep untyped because orchestrator slots may pass None.
    calendar_slot_props = {
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
                    **calendar_slot_props,
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
                    **calendar_slot_props,
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
                    **calendar_slot_props,
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
    reg.register(
        Tool(
            name="calendar.update_event",
            description="Google Calendar: update an existing event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    **calendar_slot_props,
                    "event_id": {"type": "string", "description": "Google Calendar event ID"},
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "duration": {"type": "integer"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["event_id"],
                "additionalProperties": True,
            },
            function=calendar_update_event_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="calendar.delete_event",
            description="Google Calendar: delete an event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    **calendar_slot_props,
                    "event_id": {"type": "string", "description": "Google Calendar event ID"},
                },
                "required": ["event_id"],
                "additionalProperties": True,
            },
            function=calendar_delete_event_tool,
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
                "properties": {},
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
            name="system.screenshot",
            description="System: capture a screenshot of the screen (vision)",
            parameters={
                "type": "object",
                "properties": {
                    "monitor": {"type": "integer", "description": "Monitor index (0 = primary)"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=system_screenshot_tool,
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
