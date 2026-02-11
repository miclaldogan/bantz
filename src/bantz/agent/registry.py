"""Shared runtime tool registry — single source of truth for executable tools.

Architecture (Issue #633, extended by Issue #845)
─────────────────────────────────────────────────
This module provides the **runtime** tool registry whose tools are
directly executed by :class:`~bantz.brain.orchestrator_loop.OrchestratorLoop`
via ``tool.function(**params)``.

Every tool registered here has a real ``function=`` handler from
``bantz.tools.*`` (wrapper modules that add Turkish date parsing,
idempotency, error wrapping over the raw ``bantz.google.*`` functions).

Issue #845 expanded coverage from 17 → 67 runtime tools:
  - Browser (11): browser_open, scan, click, type, back, info, detail,
    wait, search, scroll_down, scroll_up — via ExtensionBridge
  - PC Control (6): pc_hotkey, mouse_move, mouse_click, mouse_scroll,
    clipboard_set, clipboard_get — via xdotool/xclip
  - File System (6): file_read, write, edit, create, undo, search — sandboxed
  - Terminal (4): terminal_run, background, background_list, background_kill
    — policy.json enforced
  - Code/Project (6): code_format, code_replace_function, project_info,
    project_tree, project_symbols, project_search_symbol
  - Gmail Extended (13): labels, archive, mark_read/unread, batch_modify,
    download_attachment, drafts (CRUD), generate_reply
  - Contacts (4): upsert, resolve, list, delete
  - Gmail Send-to-Contact (1)

Callers
~~~~~~~
- ``brain/runtime_factory.py`` — builds the production runtime
- ``scripts/terminal_jarvis.py`` — terminal REPL

See Also
~~~~~~~~
- ``agent/builtin_tools.py`` → ``build_planner_registry()``
  The **planner** catalog (69 tools, schema-only usage) used by
  ``router/engine.py`` and ``agent/controller.py`` for LLM prompting.
  Its overlapping tool names intentionally match so agent-planned
  steps map to router intents.
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

# Issue #845: New tool imports ────────────────────────────────────────
from bantz.tools.browser_tools import (
    browser_back_tool,
    browser_click_tool,
    browser_detail_tool,
    browser_info_tool,
    browser_open_tool,
    browser_scan_tool,
    browser_scroll_down_tool,
    browser_scroll_up_tool,
    browser_search_tool,
    browser_type_tool,
    browser_wait_tool,
)
from bantz.tools.pc_tools import (
    clipboard_get_tool,
    clipboard_set_tool,
    pc_hotkey_tool,
    pc_mouse_click_tool,
    pc_mouse_move_tool,
    pc_mouse_scroll_tool,
)
from bantz.tools.file_tools import (
    file_create_tool,
    file_edit_tool,
    file_read_tool,
    file_search_tool,
    file_undo_tool,
    file_write_tool,
)
from bantz.tools.terminal_tools import (
    terminal_background_kill_tool,
    terminal_background_list_tool,
    terminal_background_tool,
    terminal_run_tool,
)
from bantz.tools.code_tools import (
    code_format_tool,
    code_replace_function_tool,
    project_info_tool,
    project_search_symbol_tool,
    project_symbols_tool,
    project_tree_tool,
)
from bantz.tools.gmail_extended_tools import (
    gmail_add_label_tool,
    gmail_archive_tool,
    gmail_batch_modify_tool,
    gmail_create_draft_tool,
    gmail_delete_draft_tool,
    gmail_download_attachment_tool,
    gmail_generate_reply_tool,
    gmail_list_drafts_tool,
    gmail_list_labels_tool,
    gmail_mark_read_tool,
    gmail_mark_unread_tool,
    gmail_remove_label_tool,
    gmail_send_draft_tool,
    gmail_update_draft_tool,
)


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

    # Calendar-only orchestrator slots (Issue #654, #663): strict typed schemas.
    # These must NOT be injected into Gmail tool schemas.
    calendar_slot_props = {
        "date": {"type": "string", "description": "Date in YYYY-MM-DD or relative (bugün/yarın/dün)"},
        "time": {"type": "string", "description": "Time in HH:MM format"},
        "duration": {"type": "integer", "description": "Duration in minutes"},
        "title": {"type": "string", "description": "Event title / summary"},
        "window_hint": {"type": "string", "description": "Relative window: today/tomorrow/yesterday/morning/evening/week"},
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
                    "max_results": {"type": "integer", "description": "Max events to return (default 10)"},
                    "query": {"type": "string", "description": "Free-text search query"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=calendar_list_events_tool,
        )
    )

    # Phantom tool aliases (Issue #663): calendar.find_event and calendar.get_event
    # are referenced in scenarios/tests but were missing from the runtime registry.
    reg.register(
        Tool(
            name="calendar.find_event",
            description="Google Calendar: find events by query (alias for list_events)",
            parameters={
                "type": "object",
                "properties": {
                    **calendar_slot_props,
                    "max_results": {"type": "integer", "description": "Max events to return"},
                    "query": {"type": "string", "description": "Free-text search query"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=calendar_list_events_tool,
        )
    )
    reg.register(
        Tool(
            name="calendar.get_event",
            description="Google Calendar: get a single event by query (alias for list_events)",
            parameters={
                "type": "object",
                "properties": {
                    **calendar_slot_props,
                    "max_results": {"type": "integer", "description": "Max events to return"},
                    "query": {"type": "string", "description": "Free-text search query"},
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
                    "suggestions": {"type": "integer", "description": "Number of suggestions (default 3)"},
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
                    "location": {"type": "string", "description": "Event location"},
                    "description": {"type": "string", "description": "Event description"},
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

    # ════════════════════════════════════════════════════════════════
    # Issue #845: 50 new runtime tools — close planner-runtime gap
    # ════════════════════════════════════════════════════════════════

    # ── Browser tools (11) ──────────────────────────────────────────
    reg.register(
        Tool(
            name="browser_open",
            description="Open a site or URL in Firefox (via extension bridge)",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Site name (youtube) or full URL"}},
                "required": ["url"],
            },
            function=browser_open_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_scan",
            description="Scan current page and list clickable elements",
            parameters={"type": "object", "properties": {}},
            function=browser_scan_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_click",
            description="Click an element by index (preferred) or by text",
            parameters={
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                },
            },
            function=browser_click_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_type",
            description="Type text into the page (optionally into an element index)",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "index": {"type": "integer"},
                    "submit": {"type": "boolean"},
                },
                "required": ["text"],
            },
            function=browser_type_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_back",
            description="Navigate back in browser history",
            parameters={"type": "object", "properties": {}},
            function=browser_back_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_info",
            description="Get current page info (title/url)",
            parameters={"type": "object", "properties": {}},
            function=browser_info_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_detail",
            description="Get detailed info about a scanned element by index",
            parameters={
                "type": "object",
                "properties": {"index": {"type": "integer"}},
                "required": ["index"],
            },
            function=browser_detail_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_wait",
            description="Wait for a few seconds (1-30)",
            parameters={
                "type": "object",
                "properties": {"seconds": {"type": "integer"}},
                "required": ["seconds"],
            },
            function=browser_wait_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_search",
            description="Search within the current site/page context",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            function=browser_search_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_scroll_down",
            description="Scroll down on the page",
            parameters={"type": "object", "properties": {}},
            function=browser_scroll_down_tool,
        )
    )
    reg.register(
        Tool(
            name="browser_scroll_up",
            description="Scroll up on the page",
            parameters={"type": "object", "properties": {}},
            function=browser_scroll_up_tool,
        )
    )

    # ── PC Control tools (6) ────────────────────────────────────────
    reg.register(
        Tool(
            name="pc_hotkey",
            description="Press a safe hotkey combo (e.g. alt+tab)",
            parameters={
                "type": "object",
                "properties": {"combo": {"type": "string", "description": "e.g. alt+tab"}},
                "required": ["combo"],
            },
            function=pc_hotkey_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="pc_mouse_move",
            description="Move mouse to screen coordinate",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "duration_ms": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
            function=pc_mouse_move_tool,
        )
    )
    reg.register(
        Tool(
            name="pc_mouse_click",
            description="Mouse click (optionally at x,y)",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string"},
                    "double": {"type": "boolean"},
                },
            },
            function=pc_mouse_click_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="pc_mouse_scroll",
            description="Scroll mouse wheel",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "description": "up|down"},
                    "amount": {"type": "integer"},
                },
                "required": ["direction"],
            },
            function=pc_mouse_scroll_tool,
        )
    )
    reg.register(
        Tool(
            name="clipboard_set",
            description="Copy text to clipboard",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            function=clipboard_set_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="clipboard_get",
            description="Read current clipboard text",
            parameters={"type": "object", "properties": {}},
            function=clipboard_get_tool,
        )
    )

    # ── File System tools (6) ───────────────────────────────────────
    reg.register(
        Tool(
            name="file_read",
            description="Read contents of a file (sandboxed). Can read specific line ranges.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "start_line": {"type": "integer", "description": "Starting line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line (inclusive)"},
                },
                "required": ["path"],
            },
            function=file_read_tool,
        )
    )
    reg.register(
        Tool(
            name="file_write",
            description="Write content to a file (sandboxed, auto-backup)",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
            function=file_write_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="file_edit",
            description="Replace a specific string in a file (unique match required)",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Exact text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
            function=file_edit_tool,
        )
    )
    reg.register(
        Tool(
            name="file_create",
            description="Create a new file with optional initial content",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Initial content"},
                },
                "required": ["path"],
            },
            function=file_create_tool,
        )
    )
    reg.register(
        Tool(
            name="file_undo",
            description="Undo the last edit to a file by restoring from backup",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            function=file_undo_tool,
        )
    )
    reg.register(
        Tool(
            name="file_search",
            description="Search for files by name pattern, optionally matching content",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
                    "content": {"type": "string", "description": "Search within file content (regex)"},
                },
                "required": ["pattern"],
            },
            function=file_search_tool,
        )
    )

    # ── Terminal tools (4) ──────────────────────────────────────────
    reg.register(
        Tool(
            name="terminal_run",
            description="Run a shell command (policy.json enforced)",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": ["command"],
            },
            function=terminal_run_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="terminal_background",
            description="Start a command in background (for servers, watch, etc.)",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            function=terminal_background_tool,
        )
    )
    reg.register(
        Tool(
            name="terminal_background_list",
            description="List all running background processes",
            parameters={"type": "object", "properties": {}},
            function=terminal_background_list_tool,
        )
    )
    reg.register(
        Tool(
            name="terminal_background_kill",
            description="Kill a background process by ID",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
            function=terminal_background_kill_tool,
        )
    )

    # ── Code / Project tools (6) ────────────────────────────────────
    reg.register(
        Tool(
            name="code_format",
            description="Format code using appropriate formatter (black, prettier, etc.)",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            function=code_format_tool,
        )
    )
    reg.register(
        Tool(
            name="code_replace_function",
            description="Replace an entire function in a Python file",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "function_name": {"type": "string"},
                    "new_code": {"type": "string"},
                },
                "required": ["path", "function_name", "new_code"],
            },
            function=code_replace_function_tool,
        )
    )
    reg.register(
        Tool(
            name="project_info",
            description="Get project information (type, name, dependencies)",
            parameters={"type": "object", "properties": {}},
            function=project_info_tool,
        )
    )
    reg.register(
        Tool(
            name="project_tree",
            description="Get project file tree structure",
            parameters={
                "type": "object",
                "properties": {"max_depth": {"type": "integer"}},
            },
            function=project_tree_tool,
        )
    )
    reg.register(
        Tool(
            name="project_symbols",
            description="Get symbols (functions, classes) from a Python file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            function=project_symbols_tool,
        )
    )
    reg.register(
        Tool(
            name="project_search_symbol",
            description="Search for a symbol across the project",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name (partial match)"},
                    "type": {"type": "string", "description": "Filter by type (function, class)"},
                },
                "required": ["name"],
            },
            function=project_search_symbol_tool,
        )
    )

    # ── Gmail Extended tools (13) ───────────────────────────────────
    reg.register(
        Tool(
            name="gmail.list_labels",
            description="Gmail: list labels (read-only)",
            parameters={"type": "object", "properties": {}},
            function=gmail_list_labels_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.add_label",
            description="Gmail: add a label to a message",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["message_id", "label"],
            },
            function=gmail_add_label_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.remove_label",
            description="Gmail: remove a label from a message",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["message_id", "label"],
            },
            function=gmail_remove_label_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.mark_read",
            description="Gmail: mark a message as read",
            parameters={
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
            function=gmail_mark_read_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.mark_unread",
            description="Gmail: mark a message as unread",
            parameters={
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
            function=gmail_mark_unread_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.archive",
            description="Gmail: archive a message (remove INBOX label). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
            function=gmail_archive_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="gmail.batch_modify",
            description="Gmail: batch add/remove labels across messages. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "message_ids": {"type": "array", "items": {"type": "string"}},
                    "add_labels": {"type": "array", "items": {"type": "string"}},
                    "remove_labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["message_ids"],
            },
            function=gmail_batch_modify_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="gmail.download_attachment",
            description="Gmail: download an attachment. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "save_path": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["message_id", "attachment_id", "save_path"],
            },
            function=gmail_download_attachment_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="gmail.create_draft",
            description="Gmail: create a draft",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
            function=gmail_create_draft_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.list_drafts",
            description="Gmail: list drafts (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer"},
                    "page_token": {"type": "string"},
                },
            },
            function=gmail_list_drafts_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.update_draft",
            description="Gmail: update a draft",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string"},
                    "updates": {"type": "object"},
                },
                "required": ["draft_id", "updates"],
            },
            function=gmail_update_draft_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.send_draft",
            description="Gmail: send a draft. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {"draft_id": {"type": "string"}},
                "required": ["draft_id"],
            },
            function=gmail_send_draft_tool,
            requires_confirmation=True,
        )
    )
    reg.register(
        Tool(
            name="gmail.delete_draft",
            description="Gmail: delete a draft",
            parameters={
                "type": "object",
                "properties": {"draft_id": {"type": "string"}},
                "required": ["draft_id"],
            },
            function=gmail_delete_draft_tool,
        )
    )

    # ── Gmail Generate Reply (1) ────────────────────────────────────
    reg.register(
        Tool(
            name="gmail.generate_reply",
            description="Gmail: generate reply suggestions and create reply draft. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "user_intent": {"type": "string"},
                    "base": {"type": "string"},
                    "reply_all": {"type": "boolean"},
                    "include_quote": {"type": "boolean"},
                },
                "required": ["message_id", "user_intent"],
            },
            function=gmail_generate_reply_tool,
            requires_confirmation=True,
        )
    )

    # ── Contacts tools (4) + send_to_contact (1) ───────────────────
    try:
        from bantz.contacts.store import (
            contacts_delete as _contacts_delete,
            contacts_list as _contacts_list,
            contacts_resolve as _contacts_resolve,
            contacts_upsert as _contacts_upsert,
        )
    except Exception:  # pragma: no cover
        _contacts_upsert = None
        _contacts_resolve = None
        _contacts_list = None
        _contacts_delete = None

    reg.register(
        Tool(
            name="contacts.upsert",
            description="Save a contact mapping (name → email)",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name", "email"],
            },
            function=_contacts_upsert,
        )
    )
    reg.register(
        Tool(
            name="contacts.resolve",
            description="Resolve a contact name to an email",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            function=_contacts_resolve,
        )
    )
    reg.register(
        Tool(
            name="contacts.list",
            description="List saved contacts",
            parameters={
                "type": "object",
                "properties": {
                    "prefix": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            function=_contacts_list,
        )
    )
    reg.register(
        Tool(
            name="contacts.delete",
            description="Delete a saved contact",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            function=_contacts_delete,
        )
    )

    # Convenience: send email to a saved contact
    try:
        from bantz.contacts.store import contacts_resolve as _cr
        from bantz.google.gmail import gmail_send as _gs

        def _gmail_send_to_contact(*, name: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None):
            resolved = _cr(name=name)
            if not resolved.get("ok"):
                return {"ok": False, "error": f"contact_not_found: {name}", "name": name}
            return _gs(to=str(resolved.get("email") or ""), subject=subject, body=body, cc=cc, bcc=bcc)
    except Exception:  # pragma: no cover
        _gmail_send_to_contact = None  # type: ignore[assignment]

    reg.register(
        Tool(
            name="gmail.send_to_contact",
            description="Gmail: send email to a saved contact name. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                    "bcc": {"type": "string"},
                },
                "required": ["name", "subject", "body"],
            },
            function=_gmail_send_to_contact,
            requires_confirmation=True,
        )
    )

    # ── Gmail query_from_nl + search templates (Issue #874 sync) ─────
    try:
        from bantz.google.gmail_query import gmail_query_from_nl as _gmail_query_from_nl
    except Exception:  # pragma: no cover
        _gmail_query_from_nl = None  # type: ignore[assignment]

    reg.register(
        Tool(
            name="gmail.query_from_nl",
            description="Convert natural language into a Gmail search query string (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Natural language query"},
                    "reference_date": {"type": "string", "description": "Optional ISO date (YYYY-MM-DD)"},
                    "inbox_only": {"type": "boolean", "description": "Default true; prepends in:inbox"},
                },
                "required": ["text"],
                "additionalProperties": True,
            },
            function=_gmail_query_from_nl,
        )
    )

    try:
        from bantz.google.gmail_search_templates import (
            templates_delete as _templates_delete,
            templates_get as _templates_get,
            templates_list as _templates_list,
            templates_upsert as _templates_upsert,
        )
    except Exception:  # pragma: no cover
        _templates_upsert = None  # type: ignore[assignment]
        _templates_get = None  # type: ignore[assignment]
        _templates_list = None  # type: ignore[assignment]
        _templates_delete = None  # type: ignore[assignment]

    reg.register(
        Tool(
            name="gmail.search_template_upsert",
            description="Save a Gmail search template (name → query). SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Template name"},
                    "query": {"type": "string", "description": "Gmail query string"},
                },
                "required": ["name", "query"],
                "additionalProperties": True,
            },
            function=_templates_upsert,
        )
    )
    reg.register(
        Tool(
            name="gmail.search_template_get",
            description="Get a saved Gmail search template. SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Template name"},
                },
                "required": ["name"],
                "additionalProperties": True,
            },
            function=_templates_get,
        )
    )
    reg.register(
        Tool(
            name="gmail.search_template_list",
            description="List saved Gmail search templates. SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Optional name prefix"},
                    "limit": {"type": "integer", "description": "Max results (default: 50)"},
                },
                "additionalProperties": True,
            },
            function=_templates_list,
        )
    )
    reg.register(
        Tool(
            name="gmail.search_template_delete",
            description="Delete a saved Gmail search template. SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Template name"},
                },
                "required": ["name"],
                "additionalProperties": True,
            },
            function=_templates_delete,
        )
    )

    # ── Calendar plan/draft tools ───────────────────────────────────
    try:
        from bantz.planning.executor import (
            apply_plan_draft as _apply_plan_draft,
            plan_events_from_draft as _plan_events_from_draft,
        )
    except Exception:  # pragma: no cover
        _apply_plan_draft = None  # type: ignore[assignment]
        _plan_events_from_draft = None  # type: ignore[assignment]

    reg.register(
        Tool(
            name="calendar.plan_events_from_draft",
            description="Parse a multi-event draft text into structured event list (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "draft_text": {"type": "string", "description": "Multi-event draft text"},
                    "reference_date": {"type": "string", "description": "Optional ISO date"},
                },
                "required": ["draft_text"],
                "additionalProperties": True,
            },
            function=_plan_events_from_draft,
        )
    )

    def _apply_plan_draft_runtime(**params):
        """Wrapper that injects Google Calendar backend."""
        if _apply_plan_draft is None:
            return {"ok": False, "error": "planning.executor not available"}
        try:
            from bantz.tools.calendar_tools import _get_calendar_service
            svc = _get_calendar_service()
        except Exception:
            svc = None
        return _apply_plan_draft(calendar_service=svc, **params)

    reg.register(
        Tool(
            name="calendar.apply_plan_draft",
            description="Apply a planned event draft to Google Calendar (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "Plan ID from plan_events_from_draft"},
                    "dry_run": {"type": "boolean", "description": "If true, validate only"},
                },
                "required": ["plan_id"],
                "additionalProperties": True,
            },
            function=_apply_plan_draft_runtime,
            requires_confirmation=True,
        )
    )

    return reg
