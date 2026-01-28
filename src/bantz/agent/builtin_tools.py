from __future__ import annotations

from .tools import Tool, ToolRegistry


def build_default_registry() -> ToolRegistry:
    """Tools available to the agent planner.

    These tool names intentionally match existing router intents so the planned
    steps can be executed by the Router queue runner.
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
            description="Create a calendar event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event summary/title"},
                    "start": {"type": "string", "description": "RFC3339 start datetime (with timezone)"},
                    "end": {"type": "string", "description": "RFC3339 end datetime (optional if duration_minutes provided)"},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes (optional if end provided)"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "description": {"type": "string", "description": "Optional description"},
                    "location": {"type": "string", "description": "Optional location"},
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
            description="Update/move a calendar event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID"},
                    "start": {"type": "string", "description": "RFC3339 start datetime (with timezone)"},
                    "end": {"type": "string", "description": "RFC3339 end datetime (with timezone)"},
                    "summary": {"type": "string", "description": "Optional new summary/title"},
                    "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                    "description": {"type": "string", "description": "Optional description"},
                    "location": {"type": "string", "description": "Optional location"},
                },
                "required": ["event_id", "start", "end"],
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
                    "calendar_id": {"type": "string"},
                },
                "required": ["ok", "id", "start", "end", "calendar_id"],
            },
            risk_level="MED",
            requires_confirmation=True,
            function=google_calendar_update_event,
        )
    )

    return reg
