from __future__ import annotations

from .tools import Tool, ToolRegistry


def build_default_registry() -> ToolRegistry:
    """Tools available to the agent planner.

    These tool names intentionally match existing router intents so the planned
    steps can be executed by the Router queue runner.
    """

    reg = ToolRegistry()

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

    return reg
