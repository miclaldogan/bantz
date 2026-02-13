"""Register web tools to ToolRegistry (Issue #89)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bantz.agent.tools import ToolRegistry


def register_web_tools(registry: "ToolRegistry") -> None:
    """Register web.search and web.open tools.
    
    Args:
        registry: ToolRegistry instance to register tools to
    """
    from bantz.agent.tools import Tool
    from bantz.tools.web_search import web_search
    from bantz.tools.web_open import web_open
    
    # Register web.search
    registry.register(
        Tool(
            name="web.search",
            description="Search the web for information. Returns list of results with title, URL, and snippet.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5, max: 20)"
                    }
                },
                "required": ["query"]
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "snippet": {"type": "string"}
                            }
                        }
                    },
                    "query": {"type": "string"},
                    "count": {"type": "integer"}
                }
            },
            function=web_search,
        )
    )
    
    # Register web.open
    registry.register(
        Tool(
            name="web.open",
            description="Open a URL and extract readable text content. Returns page title and text.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to open"
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return (default: 20000)"
                    }
                },
                "required": ["url"]
            },
            returns_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "url": {"type": "string"},
                    "error": {"type": "string"}
                }
            },
            function=web_open,
        )
    )
