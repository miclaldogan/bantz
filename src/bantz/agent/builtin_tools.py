"""Agent planner tool catalog — schema definitions for LLM tool-call generation.

Architecture (Issue #633)
─────────────────────────
Bantz has TWO tool registries that serve different purposes:

  ┌──────────────────────────────────────────────────────────────┐
  │  registry.py  → build_default_registry()                     │
  │  "Runtime registry" — 15 tools with REAL handlers            │
  │  Used by: runtime_factory.py, terminal_jarvis.py             │
  │  Purpose: OrchestratorLoop calls tool.function(**params)      │
  │  Handlers: bantz.tools.* wrappers (Turkish date parsing,     │
  │            idempotency, error wrapping over bantz.google.*)   │
  └──────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────┐
  │  builtin_tools.py  → build_planner_registry()                │
  │  "Planner catalog" — 69 tools with full JSON schemas         │
  │  Used by: router/engine.py, agent/controller.py              │
  │  Purpose: LLM reads tool descriptions to generate plans;     │
  │           planned steps are dispatched as router intents      │
  │  Handlers: bantz.google.* raw functions (attached for        │
  │            optional direct execution, NOT primary path)       │
  └──────────────────────────────────────────────────────────────┘

The 10 overlapping tool names (calendar.*, gmail core) intentionally
share names so agent-planned steps map directly to router intents.

For the overlapping tools, the canonical handler lives in registry.py
(the wrapper version with Turkish NL support).  This module provides
the full Google API schemas for richer agent planning.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from .tools import Tool, ToolRegistry

if TYPE_CHECKING:
    pass


def build_planner_registry() -> ToolRegistry:
    """Build the planner tool catalog — schemas for LLM tool-call generation.

    Returns a ``ToolRegistry`` with 69 tools.  Most have ``function=``
    handlers attached (via ``bantz.google.*`` imports), but the primary
    consumer (``router/engine.py``, ``agent/controller.py``) only reads
    tool schemas to compose LLM prompts — it never calls
    ``tool.function()`` directly.

    For the 10 tools that overlap with :func:`registry.build_default_registry`,
    this catalog provides the full Google Calendar / Gmail API schemas
    (RFC3339 timestamps, ``calendar_id``, ``page_token`` etc.) while
    ``registry.py`` provides orchestrator-friendly schemas
    (``date``, ``time``, ``window_hint``).

    See Also
    --------
    bantz.agent.registry.build_default_registry :
        The *runtime* registry whose tools are actually executed by
        :class:`~bantz.brain.orchestrator_loop.OrchestratorLoop`.
    """

    reg = ToolRegistry()

    # ─────────────────────────────────────────────────────────────────
    # Browser Tools
    # ─────────────────────────────────────────────────────────────────
    reg.register(
        Tool(
            name="browser_open",
            description="Open a site or URL in Firefox (via extension bridge).",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Site name (youtube) or full URL"}
                },
                "required": ["url"],
            },
        )
    )

    reg.register(
        Tool(
            name="browser_scan",
            description="Scan current page and list clickable elements.",
            parameters={"type": "object", "properties": {}},
        )
    )

    reg.register(
        Tool(
            name="browser_click",
            description="Click an element by index (preferred) or by text.",
            parameters={
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                },
            },
        )
    )

    reg.register(
        Tool(
            name="browser_type",
            description="Type text into the page (optionally into an element index).",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "index": {"type": "integer"},
                },
                "required": ["text"],
            },
        )
    )

    reg.register(
        Tool(
            name="browser_back",
            description="Navigate back in browser history.",
            parameters={"type": "object", "properties": {}},
        )
    )

    reg.register(
        Tool(
            name="browser_info",
            description="Get current page info (title/url/site).",
            parameters={"type": "object", "properties": {}},
        )
    )

    reg.register(
        Tool(
            name="browser_detail",
            description="Get detailed info about a scanned element by index.",
            parameters={
                "type": "object",
                "properties": {"index": {"type": "integer"}},
                "required": ["index"],
            },
        )
    )

    reg.register(
        Tool(
            name="browser_wait",
            description="Wait for a few seconds (1-30).",
            parameters={
                "type": "object",
                "properties": {"seconds": {"type": "integer"}},
                "required": ["seconds"],
            },
        )
    )

    reg.register(
        Tool(
            name="browser_search",
            description="Search within the current site/page context (e.g., YouTube search box).",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    )

    reg.register(
        Tool(
            name="browser_scroll_down",
            description="Scroll down on the page.",
            parameters={"type": "object", "properties": {}},
        )
    )

    reg.register(
        Tool(
            name="browser_scroll_up",
            description="Scroll up on the page.",
            parameters={"type": "object", "properties": {}},
        )
    )

    reg.register(
        Tool(
            name="pc_hotkey",
            description="Press a safe hotkey combo (policy may require confirmation).",
            parameters={
                "type": "object",
                "properties": {"combo": {"type": "string", "description": "e.g. alt+tab"}},
                "required": ["combo"],
            },
            requires_confirmation=True,
        )
    )

    reg.register(
        Tool(
            name="pc_mouse_move",
            description="Move mouse to screen coordinate.",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "duration_ms": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        )
    )

    reg.register(
        Tool(
            name="pc_mouse_click",
            description="Mouse click (optionally at x,y).",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string"},
                    "double": {"type": "boolean"},
                },
            },
            requires_confirmation=True,
        )
    )

    reg.register(
        Tool(
            name="pc_mouse_scroll",
            description="Scroll mouse wheel.",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "description": "up|down"},
                    "amount": {"type": "integer"},
                },
                "required": ["direction"],
            },
        )
    )

    reg.register(
        Tool(
            name="clipboard_set",
            description="Copy text to clipboard.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            requires_confirmation=True,
        )
    )

    reg.register(
        Tool(
            name="clipboard_get",
            description="Read current clipboard text.",
            parameters={"type": "object", "properties": {}},
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Coding Agent Tools (Issue #4)
    # ─────────────────────────────────────────────────────────────────
    
    # File operations
    reg.register(
        Tool(
            name="file_read",
            description="Read contents of a file. Can read specific line ranges.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "start_line": {"type": "integer", "description": "Starting line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line (inclusive)"},
                },
                "required": ["path"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="file_write",
            description="Write content to a file. Creates backup automatically.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
        )
    )
    
    reg.register(
        Tool(
            name="file_edit",
            description="Replace a specific string in a file. Include enough context for unique match.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Exact text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="file_create",
            description="Create a new file with optional initial content.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Initial content"},
                },
                "required": ["path"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="file_undo",
            description="Undo the last edit to a file by restoring from backup.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="file_search",
            description="Search for files by name pattern, optionally matching content.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
                    "content": {"type": "string", "description": "Search within file content (regex)"},
                },
                "required": ["pattern"],
            },
        )
    )
    
    # Terminal operations
    reg.register(
        Tool(
            name="terminal_run",
            description="Run a shell command. Some commands require confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        )
    )
    
    reg.register(
        Tool(
            name="terminal_background",
            description="Start a command in background. For servers, watch, etc.",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="terminal_background_list",
            description="List all running background processes.",
            parameters={"type": "object", "properties": {}},
        )
    )
    
    reg.register(
        Tool(
            name="terminal_background_kill",
            description="Kill a background process by ID.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
        )
    )
    
    # Code editing
    reg.register(
        Tool(
            name="code_format",
            description="Format code using appropriate formatter (black, prettier, etc.).",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="code_replace_function",
            description="Replace an entire function in a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "function_name": {"type": "string"},
                    "new_code": {"type": "string"},
                },
                "required": ["path", "function_name", "new_code"],
            },
        )
    )
    
    # Project context
    reg.register(
        Tool(
            name="project_info",
            description="Get project information (type, name, dependencies).",
            parameters={"type": "object", "properties": {}},
        )
    )
    
    reg.register(
        Tool(
            name="project_tree",
            description="Get project file tree structure.",
            parameters={
                "type": "object",
                "properties": {"max_depth": {"type": "integer"}},
            },
        )
    )
    
    reg.register(
        Tool(
            name="project_symbols",
            description="Get symbols (functions, classes) from a file.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
    )
    
    reg.register(
        Tool(
            name="project_search_symbol",
            description="Search for a symbol across the project.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name (partial match)"},
                    "type": {"type": "string", "description": "Filter by type (function, class)"},
                },
                "required": ["name"],
            },
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Calendar Tools (Google)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.calendar import list_events as google_calendar_list_events
    except Exception:  # pragma: no cover
        google_calendar_list_events = None

    reg.register(
        Tool(
            name="calendar.list_events",
            description="List upcoming events from Google Calendar.",
            parameters={
                "type": "object",
                "properties": {
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "max_results": {"type": "integer", "description": "Max results (default: 10)"},
                    "time_min": {"type": "string", "description": "RFC3339 timeMin (default: now)"},
                    "time_max": {"type": "string", "description": "RFC3339 timeMax"},
                    "query": {"type": "string", "description": "Free-text search query"},
                    "single_events": {"type": "boolean", "description": "Expand recurring events"},
                    "show_deleted": {"type": "boolean", "description": "Include deleted events"},
                    "order_by": {"type": "string", "description": "Order (default: startTime)"},
                },
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "calendar_id": {"type": "string"},
                    "count": {"type": "integer"},
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "summary": {"type": "string"},
                                "start": {"type": "string"},
                                "end": {"type": "string"},
                                "location": {"type": "string"},
                                "htmlLink": {"type": "string"},
                                "status": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["ok", "calendar_id", "count", "events"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_calendar_list_events,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Read-only (Issue #170)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail import gmail_list_messages as google_gmail_list_messages
    except Exception:  # pragma: no cover
        google_gmail_list_messages = None

    reg.register(
        Tool(
            name="gmail.list_messages",
            description="List messages from Gmail inbox (read-only).",
            parameters={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max results (default: 10)"},
                    "unread_only": {"type": "boolean", "description": "Only unread messages (default: false)"},
                    "page_token": {"type": "string", "description": "Pagination token (nextPageToken)"},
                },
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "query": {"type": "string"},
                    "estimated_count": {"type": ["integer", "null"]},
                    "next_page_token": {"type": ["string", "null"]},
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "from": {"type": ["string", "null"]},
                                "subject": {"type": ["string", "null"]},
                                "snippet": {"type": "string"},
                                "date": {"type": ["string", "null"]},
                            },
                            "required": ["id", "snippet"],
                        },
                    },
                },
                "required": ["ok", "query", "messages", "estimated_count", "next_page_token"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_list_messages,
        )
    )

    try:
        from bantz.google.gmail import gmail_unread_count as google_gmail_unread_count
    except Exception:  # pragma: no cover
        google_gmail_unread_count = None

    reg.register(
        Tool(
            name="gmail.unread_count",
            description="Get estimated unread count from Gmail (read-only).",
            parameters={"type": "object", "properties": {}},
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "unread_count_estimate": {"type": "integer"},
                },
                "required": ["ok", "unread_count_estimate"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_unread_count,
        )
    )

    try:
        from bantz.google.gmail import gmail_get_message as google_gmail_get_message
    except Exception:  # pragma: no cover
        google_gmail_get_message = None

    reg.register(
        Tool(
            name="gmail.get_message",
            description="Read a Gmail message body and detect attachments (read-only).",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                    "expand_thread": {"type": "boolean", "description": "Also fetch full thread (default: false)"},
                    "max_thread_messages": {"type": "integer", "description": "Max thread messages to return (default: 25)"},
                },
                "required": ["message_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message": {"type": ["object", "null"]},
                    "thread": {"type": ["object", "null"]},
                },
                "required": ["ok", "message", "thread"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_get_message,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Attachment Download (Issue #176)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail import gmail_download_attachment as google_gmail_download_attachment
    except Exception:  # pragma: no cover
        google_gmail_download_attachment = None

    reg.register(
        Tool(
            name="gmail.download_attachment",
            description="Download a Gmail attachment to disk. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                    "attachment_id": {"type": "string", "description": "Attachment id (from gmail.get_message attachments)"},
                    "save_path": {"type": "string", "description": "File path to save to"},
                    "overwrite": {"type": "boolean", "description": "Overwrite existing file (default: false)"},
                },
                "required": ["message_id", "attachment_id", "save_path"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_id": {"type": "string"},
                    "attachment_id": {"type": "string"},
                    "saved_path": {"type": "string"},
                    "filename": {"type": "string"},
                    "mimeType": {"type": ["string", "null"]},
                    "declared_size_bytes": {"type": ["integer", "null"]},
                    "size_bytes": {"type": ["integer", "null"]},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "saved_path"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_gmail_download_attachment,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Smart Search (Issue #175)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail_query import gmail_query_from_nl as google_gmail_query_from_nl
    except Exception:  # pragma: no cover
        google_gmail_query_from_nl = None

    reg.register(
        Tool(
            name="gmail.query_from_nl",
            description="Convert natural language into a Gmail search query string (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Natural language query"},
                    "reference_date": {
                        "type": "string",
                        "description": "Optional ISO date (YYYY-MM-DD) used for relative phrases (tests)",
                    },
                    "inbox_only": {"type": "boolean", "description": "Default true; prepends in:inbox"},
                },
                "required": ["text"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "query": {"type": "string"},
                    "parts": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "query", "parts"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_query_from_nl,
        )
    )

    try:
        from bantz.google.gmail_smart_search import gmail_smart_search as google_gmail_smart_search
    except Exception:  # pragma: no cover
        google_gmail_smart_search = None

    reg.register(
        Tool(
            name="gmail.smart_search",
            description="Search Gmail using natural-language filters (SAFE, read-only).",
            parameters={
                "type": "object",
                "properties": {
                    "query_nl": {"type": "string", "description": "Natural language query"},
                    "max_results": {"type": "integer", "description": "Max results (default: 10)"},
                    "page_token": {"type": "string", "description": "Pagination token"},
                    "inbox_only": {"type": "boolean", "description": "Default true; includes in:inbox"},
                    "template_name": {"type": "string", "description": "Optional saved template name"},
                    "reference_date": {"type": "string", "description": "Optional ISO date for relative phrases"},
                },
                "required": ["query_nl"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "query": {"type": "string"},
                    "estimated_count": {"type": ["integer", "null"]},
                    "next_page_token": {"type": ["string", "null"]},
                    "messages": {"type": "array"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "query", "estimated_count", "next_page_token", "messages"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_smart_search,
        )
    )

    try:
        from bantz.google.gmail_search_templates import (
            templates_delete as google_gmail_templates_delete,
            templates_get as google_gmail_templates_get,
            templates_list as google_gmail_templates_list,
            templates_upsert as google_gmail_templates_upsert,
        )
    except Exception:  # pragma: no cover
        google_gmail_templates_upsert = None
        google_gmail_templates_get = None
        google_gmail_templates_list = None
        google_gmail_templates_delete = None

    reg.register(
        Tool(
            name="gmail.search_template_upsert",
            description="Save a Gmail search template (name → query). SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Template name"},
                    "query": {"type": "string", "description": "Gmail query string (q=)"},
                },
                "required": ["name", "query"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "template": {"type": "object"},
                    "key": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["ok", "template", "key", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_templates_upsert,
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
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "template": {"type": "object"},
                    "key": {"type": "string"},
                    "path": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "key", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_templates_get,
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
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "templates": {"type": "array"},
                    "path": {"type": "string"},
                },
                "required": ["ok", "templates", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_templates_list,
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
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "deleted": {"type": "boolean"},
                    "key": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["ok", "deleted", "key", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_templates_delete,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Labels & Archive (Issue #174)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail import gmail_list_labels as google_gmail_list_labels
    except Exception:  # pragma: no cover
        google_gmail_list_labels = None

    reg.register(
        Tool(
            name="gmail.list_labels",
            description="List Gmail labels (SAFE).",
            parameters={"type": "object", "properties": {}},
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "labels": {"type": "array"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "labels"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_list_labels,
        )
    )

    try:
        from bantz.google.gmail import gmail_add_label as google_gmail_add_label
    except Exception:  # pragma: no cover
        google_gmail_add_label = None

    reg.register(
        Tool(
            name="gmail.add_label",
            description="Add a label to a Gmail message (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                    "label": {"type": "string", "description": "Label name or id"},
                },
                "required": ["message_id", "label"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_id": {"type": "string"},
                    "added": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "message_id", "added"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_add_label,
        )
    )

    try:
        from bantz.google.gmail import gmail_remove_label as google_gmail_remove_label
    except Exception:  # pragma: no cover
        google_gmail_remove_label = None

    reg.register(
        Tool(
            name="gmail.remove_label",
            description="Remove a label from a Gmail message (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                    "label": {"type": "string", "description": "Label name or id"},
                },
                "required": ["message_id", "label"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_id": {"type": "string"},
                    "removed": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "message_id", "removed"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_remove_label,
        )
    )

    try:
        from bantz.google.gmail import gmail_archive as google_gmail_archive
    except Exception:  # pragma: no cover
        google_gmail_archive = None

    reg.register(
        Tool(
            name="gmail.archive",
            description="Archive a Gmail message (removes INBOX). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                },
                "required": ["message_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_id": {"type": "string"},
                    "archived": {"type": "boolean"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "message_id", "archived"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_gmail_archive,
        )
    )

    try:
        from bantz.google.gmail import gmail_mark_read as google_gmail_mark_read
    except Exception:  # pragma: no cover
        google_gmail_mark_read = None

    reg.register(
        Tool(
            name="gmail.mark_read",
            description="Mark a Gmail message as read (removes UNREAD). SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                },
                "required": ["message_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_id": {"type": "string"},
                    "read": {"type": "boolean"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "message_id", "read"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_mark_read,
        )
    )

    try:
        from bantz.google.gmail import gmail_mark_unread as google_gmail_mark_unread
    except Exception:  # pragma: no cover
        google_gmail_mark_unread = None

    reg.register(
        Tool(
            name="gmail.mark_unread",
            description="Mark a Gmail message as unread (adds UNREAD). SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                },
                "required": ["message_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_id": {"type": "string"},
                    "unread": {"type": "boolean"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "message_id", "unread"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_mark_unread,
        )
    )

    try:
        from bantz.google.gmail import gmail_batch_modify as google_gmail_batch_modify
    except Exception:  # pragma: no cover
        google_gmail_batch_modify = None

    reg.register(
        Tool(
            name="gmail.batch_modify",
            description="Batch add/remove labels across messages. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "message_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of Gmail message ids",
                    },
                    "add_labels": {"type": "array", "items": {"type": "string"}, "description": "Label names or ids to add"},
                    "remove_labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Label names or ids to remove",
                    },
                },
                "required": ["message_ids"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "message_ids": {"type": "array", "items": {"type": "string"}},
                    "added": {"type": "array", "items": {"type": "string"}},
                    "removed": {"type": "array", "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "message_ids", "added", "removed"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_gmail_batch_modify,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Send (Issue #172)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail import gmail_send as google_gmail_send
    except Exception:  # pragma: no cover
        google_gmail_send = None

    reg.register(
        Tool(
            name="gmail.send",
            description="Send an email via Gmail (compose & send). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email(s). Comma/semicolon separated supported.",
                    },
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Plain-text email body"},
                    "cc": {
                        "type": "string",
                        "description": "CC recipient(s). Comma/semicolon separated.",
                    },
                    "bcc": {
                        "type": "string",
                        "description": "BCC recipient(s). Comma/semicolon separated.",
                    },
                },
                "required": ["to", "subject", "body"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "cc": {"type": ["array", "null"], "items": {"type": "string"}},
                    "bcc": {"type": ["array", "null"], "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "message_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "label_ids": {"type": ["array", "null"], "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "to", "subject", "message_id", "thread_id", "label_ids"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_gmail_send,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Contacts (local) - name → email (Issue: contacts shortcuts)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.contacts.store import (
            contacts_delete as contacts_delete_fn,
            contacts_list as contacts_list_fn,
            contacts_resolve as contacts_resolve_fn,
            contacts_upsert as contacts_upsert_fn,
        )
    except Exception:  # pragma: no cover
        contacts_upsert_fn = None
        contacts_resolve_fn = None
        contacts_list_fn = None
        contacts_delete_fn = None

    reg.register(
        Tool(
            name="contacts.upsert",
            description="Save a contact mapping (name → email). SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Contact name (e.g., 'Ali')"},
                    "email": {"type": "string", "description": "Email address"},
                    "notes": {"type": "string", "description": "Optional notes"},
                },
                "required": ["name", "email"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "contact": {"type": "object"},
                    "path": {"type": "string"},
                },
                "required": ["ok", "contact", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=contacts_upsert_fn,
        )
    )

    reg.register(
        Tool(
            name="contacts.resolve",
            description="Resolve a contact name to an email. SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Contact name"},
                },
                "required": ["name"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "name": {"type": "string"},
                    "key": {"type": "string"},
                    "email": {"type": "string"},
                    "notes": {"type": ["string", "null"]},
                    "path": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "key", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=contacts_resolve_fn,
        )
    )

    reg.register(
        Tool(
            name="contacts.list",
            description="List saved contacts. SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Optional name prefix filter"},
                    "limit": {"type": "integer", "description": "Max results (default: 50)"},
                },
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "contacts": {"type": "array"},
                    "path": {"type": "string"},
                },
                "required": ["ok", "contacts", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=contacts_list_fn,
        )
    )

    reg.register(
        Tool(
            name="contacts.delete",
            description="Delete a saved contact. SAFE.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Contact name"},
                },
                "required": ["name"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "deleted": {"type": "boolean"},
                    "key": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["ok", "deleted", "key", "path"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=contacts_delete_fn,
        )
    )

    # Convenience wrapper: send email to a saved contact name.
    try:
        from bantz.contacts.store import contacts_resolve as _contacts_resolve
        from bantz.google.gmail import gmail_send as _gmail_send

        def gmail_send_to_contact(*, name: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None):
            resolved = _contacts_resolve(name=name)
            if not resolved.get("ok"):
                return {
                    "ok": False,
                    "error": f"contact_not_found: {name}",
                    "name": name,
                }
            return _gmail_send(to=str(resolved.get("email") or ""), subject=subject, body=body, cc=cc, bcc=bcc)

    except Exception:  # pragma: no cover
        gmail_send_to_contact = None

    reg.register(
        Tool(
            name="gmail.send_to_contact",
            description="Send an email to a saved contact name via Gmail. Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Saved contact name"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "cc": {"type": "string", "description": "Optional CC emails"},
                    "bcc": {"type": "string", "description": "Optional BCC emails"},
                },
                "required": ["name", "subject", "body"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "error": {"type": "string"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "message_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "label_ids": {"type": ["array", "null"], "items": {"type": "string"}},
                },
                "required": ["ok"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=gmail_send_to_contact,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Drafts (Issue #173)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail import gmail_create_draft as google_gmail_create_draft
    except Exception:  # pragma: no cover
        google_gmail_create_draft = None

    reg.register(
        Tool(
            name="gmail.create_draft",
            description="Create a Gmail draft (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email(s)"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Plain-text body"},
                },
                "required": ["to", "subject", "body"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "draft_id": {"type": "string"},
                    "message_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "draft_id", "message_id", "thread_id", "to", "subject"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_create_draft,
        )
    )

    try:
        from bantz.google.gmail import gmail_list_drafts as google_gmail_list_drafts
    except Exception:  # pragma: no cover
        google_gmail_list_drafts = None

    reg.register(
        Tool(
            name="gmail.list_drafts",
            description="List Gmail drafts with basic metadata (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max results (default: 10)"},
                    "page_token": {"type": "string", "description": "Pagination token"},
                },
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "drafts": {"type": "array"},
                    "estimated_count": {"type": ["integer", "null"]},
                    "next_page_token": {"type": ["string", "null"]},
                    "error": {"type": "string"},
                },
                "required": ["ok", "drafts", "estimated_count", "next_page_token"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_list_drafts,
        )
    )

    try:
        from bantz.google.gmail import gmail_update_draft as google_gmail_update_draft
    except Exception:  # pragma: no cover
        google_gmail_update_draft = None

    reg.register(
        Tool(
            name="gmail.update_draft",
            description="Update a Gmail draft (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "description": "Draft id"},
                    "updates": {"type": "object", "description": "Fields to update (to, subject, body, cc, bcc)"},
                },
                "required": ["draft_id", "updates"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "draft_id": {"type": "string"},
                    "message_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "draft_id", "message_id", "thread_id"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_update_draft,
        )
    )

    try:
        from bantz.google.gmail import gmail_send_draft as google_gmail_send_draft
    except Exception:  # pragma: no cover
        google_gmail_send_draft = None

    reg.register(
        Tool(
            name="gmail.send_draft",
            description="Send a Gmail draft (MODERATE, confirmation required).",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "description": "Draft id"},
                },
                "required": ["draft_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "draft_id": {"type": "string"},
                    "message_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "label_ids": {"type": ["array", "null"], "items": {"type": "string"}},
                    "error": {"type": "string"},
                },
                "required": ["ok", "draft_id", "message_id", "thread_id", "label_ids"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_gmail_send_draft,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Gmail Tools (Google) - Auto Reply (Issue #177)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.google.gmail_reply import gmail_generate_reply as google_gmail_generate_reply
    except Exception:  # pragma: no cover
        google_gmail_generate_reply = None

    reg.register(
        Tool(
            name="gmail.generate_reply",
            description=(
                "Generate 3 reply suggestions (short/medium/detailed) for a Gmail message and create a reply draft. "
                "MODERATE (creates draft), confirmation required."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id to reply to"},
                    "user_intent": {"type": "string", "description": "What the user wants to reply (natural language)"},
                    "base": {
                        "type": "string",
                        "description": "Reply base/style: default|formal|friendly (default: default)",
                    },
                    "reply_all": {
                        "type": ["boolean", "null"],
                        "description": "Override reply-all detection (true/false). If null, auto-detect.",
                    },
                    "include_quote": {
                        "type": "boolean",
                        "description": "If true, append a quoted original-message block to the reply.",
                        "default": False,
                    },
                },
                "required": ["message_id", "user_intent"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "error": {"type": "string"},
                    "message_id": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "draft_id": {"type": "string"},
                    "base": {"type": "string"},
                    "reply_all": {"type": "boolean"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "cc": {"type": ["array", "null"], "items": {"type": "string"}},
                    "include_quote": {"type": "boolean"},
                    "options": {"type": "array"},
                    "selected_style": {"type": "string"},
                    "preview": {"type": "string"},
                    "llm_backend": {"type": "string"},
                    "llm_model": {"type": "string"},
                },
                "required": ["ok", "message_id", "thread_id", "draft_id", "options"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_gmail_generate_reply,
        )
    )

    try:
        from bantz.google.gmail import gmail_delete_draft as google_gmail_delete_draft
    except Exception:  # pragma: no cover
        google_gmail_delete_draft = None

    reg.register(
        Tool(
            name="gmail.delete_draft",
            description="Delete a Gmail draft (SAFE).",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "string", "description": "Draft id"},
                },
                "required": ["draft_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "draft_id": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["ok", "draft_id"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_gmail_delete_draft,
        )
    )

    try:
        from bantz.google.calendar import find_free_slots as google_calendar_find_free_slots
    except Exception:  # pragma: no cover
        google_calendar_find_free_slots = None

    reg.register(
        Tool(
            name="calendar.find_free_slots",
            description="Find free time slots between time_min and time_max for a given duration.",
            parameters={
                "type": "object",
                "properties": {
                    "time_min": {"type": "string", "description": "RFC3339 window start"},
                    "time_max": {"type": "string", "description": "RFC3339 window end"},
                    "duration_minutes": {"type": "integer", "description": "Required duration in minutes"},
                    "suggestions": {"type": "integer", "description": "How many slots to return (default: 3)"},
                    "preferred_start": {"type": "string", "description": "Preferred day start HH:MM (default: 07:30)"},
                    "preferred_end": {"type": "string", "description": "Preferred day end HH:MM (default: 22:30; supports 24:00)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                },
                "required": ["time_min", "time_max", "duration_minutes"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "slots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "string"},
                                "end": {"type": "string"},
                            },
                            "required": ["start", "end"],
                        },
                    },
                },
                "required": ["ok", "slots"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=google_calendar_find_free_slots,
        )
    )

    try:
        from bantz.google.calendar import create_event as google_calendar_create_event
    except Exception:  # pragma: no cover
        google_calendar_create_event = None

    reg.register(
        Tool(
            name="calendar.create_event",
            description=(
                "Create a calendar event (write). Supports time-based, all-day, and recurring events. "
                "For all-day events (Issue #164), set all_day=true and use YYYY-MM-DD format. "
                "For recurring events (Issue #165), provide recurrence list with RRULE strings. "
                "Requires confirmation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event summary/title"},
                    "start": {
                        "type": "string",
                        "description": (
                            "Start datetime (RFC3339 with timezone) or date (YYYY-MM-DD for all-day events)"
                        ),
                    },
                    "end": {
                        "type": "string",
                        "description": (
                            "End datetime (RFC3339) or date (YYYY-MM-DD). "
                            "Optional if duration_minutes provided (time-based events) or "
                            "for single-day all-day events."
                        ),
                    },
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes (ignored for all-day events)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "description": {"type": "string", "description": "Optional description"},
                    "location": {"type": "string", "description": "Optional location"},
                    "all_day": {
                        "type": "boolean",
                        "description": (
                            "If true, creates an all-day event. "
                            "Start and end must be YYYY-MM-DD format. "
                            "End is exclusive (e.g., 2026-02-23 to 2026-02-26 = Feb 23-25)."
                        ),
                    },
                    "recurrence": {
                        "type": "array",
                        "description": (
                            "List of RRULE strings for recurring events (RFC5545 format). "
                            "Example: ['RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10'] for weekly Monday meetings, 10 times. "
                            "Supports: FREQ=DAILY/WEEKLY/MONTHLY/YEARLY, BYDAY=MO/TU/WE/TH/FR/SA/SU, "
                            "COUNT=number, UNTIL=dateTime, INTERVAL=number."
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": ["summary", "start"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "id": {"type": "string"},
                    "htmlLink": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "recurrence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["ok", "id", "start", "end", "summary"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_calendar_create_event,
        )
    )

    try:
        from bantz.google.calendar import delete_event as google_calendar_delete_event
    except Exception:  # pragma: no cover
        google_calendar_delete_event = None

    reg.register(
        Tool(
            name="calendar.delete_event",
            description="Delete a calendar event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                },
                "required": ["event_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                },
                "required": ["ok", "id", "calendar_id"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_calendar_delete_event,
        )
    )

    try:
        from bantz.google.calendar import update_event as google_calendar_update_event
    except Exception:  # pragma: no cover
        google_calendar_update_event = None

    reg.register(
        Tool(
            name="calendar.update_event",
            description=(
                "Update a calendar event with partial updates (write). Requires confirmation. "
                "Only specified fields are modified. "
                "Examples: change title only, change location only, change time only, or combine multiple changes. "
                "If start is provided, end must also be provided."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID (required)"},
                    "summary": {"type": "string", "description": "New event title/summary (optional)"},
                    "start": {"type": "string", "description": "RFC3339 start datetime with timezone (optional, requires end)"},
                    "end": {"type": "string", "description": "RFC3339 end datetime with timezone (optional, requires start)"},
                    "location": {"type": "string", "description": "Event location (optional)"},
                    "description": {"type": "string", "description": "Event description (optional)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                },
                "required": ["event_id"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "id": {"type": "string"},
                    "htmlLink": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                    "calendar_id": {"type": "string"},
                },
                "required": ["ok", "id", "calendar_id"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_calendar_update_event,
        )
    )

    # ─────────────────────────────────────────────────────────────────
    # Planning Tools (Jarvis-Calendar)
    # ─────────────────────────────────────────────────────────────────
    try:
        from bantz.planning.executor import apply_plan_draft as _apply_plan_draft
        from bantz.planning.executor import plan_events_from_draft as _plan_events_from_draft
    except Exception:  # pragma: no cover
        _apply_plan_draft = None
        _plan_events_from_draft = None

    reg.register(
        Tool(
            name="calendar.plan_events_from_draft",
            description="Create a deterministic event plan from a PlanDraft (dry-run, no writes).",
            parameters={
                "type": "object",
                "properties": {
                    "draft": {"type": "object", "description": "PlanDraft dict"},
                    "time_min": {"type": "string", "description": "RFC3339 window start"},
                    "time_max": {"type": "string", "description": "RFC3339 window end"},
                },
                "required": ["draft", "time_min", "time_max"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "count": {"type": "integer"},
                    "events": {"type": "array"},
                    "warnings": {"type": "array"},
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                },
                "required": ["ok"],
            },
            risk_level="LOW",
            requires_confirmation=False,
            function=_plan_events_from_draft,
        )
    )

    def _apply_plan_draft_with_google_backend(**params):
        if _apply_plan_draft is None:
            return {"ok": False, "error": "planner_not_available"}
        dry_run = bool(params.get("dry_run"))
        draft = params.get("draft")
        time_min = params.get("time_min")
        time_max = params.get("time_max")
        calendar_id = str(params.get("calendar_id") or "primary")
        return _apply_plan_draft(
            draft=draft,
            time_min=time_min,
            time_max=time_max,
            dry_run=dry_run,
            calendar_id=calendar_id,
            create_event_fn=google_calendar_create_event,
        )

    reg.register(
        Tool(
            name="calendar.apply_plan_draft",
            description="Apply a PlanDraft by creating calendar events (supports dry-run). Requires confirmation if writing.",
            parameters={
                "type": "object",
                "properties": {
                    "draft": {"type": "object", "description": "PlanDraft dict"},
                    "time_min": {"type": "string", "description": "RFC3339 window start"},
                    "time_max": {"type": "string", "description": "RFC3339 window end"},
                    "dry_run": {"type": "boolean", "description": "If true, do not write; return planned events"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                },
                "required": ["draft", "time_min", "time_max"],
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "dry_run": {"type": "boolean"},
                    "created_count": {"type": "integer"},
                    "failed_index": {"type": "integer"},
                    "events": {"type": "array"},
                    "created": {"type": "array"},
                    "error": {"type": "string"},
                    "warnings": {"type": "array"},
                },
                "required": ["ok"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=_apply_plan_draft_with_google_backend,
        )
    )

    return reg


# ─────────────────────────────────────────────────────────────────────
# Backward-compatible alias (Issue #633)
# ─────────────────────────────────────────────────────────────────────
def build_default_registry() -> ToolRegistry:
    """**Deprecated** — use :func:`build_planner_registry` instead.

    This alias exists so that existing callers (tests, scripts) keep
    working after the rename.  It emits a ``DeprecationWarning`` to
    nudge callers toward the canonical name.
    """
    warnings.warn(
        "builtin_tools.build_default_registry() is deprecated; "
        "use build_planner_registry() instead (Issue #633)",
        DeprecationWarning,
        stacklevel=2,
    )
    return build_planner_registry()
