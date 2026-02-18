"""
Graph Bridge — Connects tool results to the knowledge graph.

Sits alongside the IngestBridge and feeds structured tool results
into the AutoLinker, which extracts entities and relationships
and stores them in the GraphStore.

Usage in the orchestrator::

    from bantz.data.graph_bridge import GraphBridge
    bridge = await GraphBridge.create_default()
    await bridge.on_tool_result("gmail", params, result)

The bridge is optional — if the GraphStore fails to initialise, all
methods gracefully no-op so the assistant continues working.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from bantz.data.auto_linker import AutoLinker
from bantz.data.graph_store import GraphStore

logger = logging.getLogger(__name__)


def _get_event_bus_safe():
    """Get the EventBus singleton without import-time side effects."""
    try:
        from bantz.core.events import get_event_bus
        return get_event_bus()
    except Exception:
        return None

# Tool name → source category mapping
_TOOL_SOURCE_MAP: Dict[str, str] = {
    # Gmail tools (legacy underscore)
    "gmail_list_messages": "gmail",
    "gmail_get_message": "gmail",
    "gmail_send": "gmail",
    "gmail_reply": "gmail",
    "gmail_search": "gmail",
    # Gmail tools (current dotted)
    "gmail.list_messages": "gmail",
    "gmail.get_message": "gmail",
    "gmail.send": "gmail",
    "gmail.generate_reply": "gmail",
    "gmail.smart_search": "gmail",
    "gmail.query_from_nl": "gmail",
    # Calendar tools (legacy underscore)
    "calendar_list_events": "calendar",
    "calendar_get_event": "calendar",
    "calendar_create_event": "calendar",
    "calendar_update_event": "calendar",
    "calendar_find_free_slots": "calendar",
    # Calendar tools (current dotted)
    "calendar.list_events": "calendar",
    "calendar.get_event": "calendar",
    "calendar.create_event": "calendar",
    "calendar.update_event": "calendar",
    "calendar.delete_event": "calendar",
    "calendar.find_free_slots": "calendar",
    # Contacts
    "contacts_list": "contacts",
    "contacts_search": "contacts",
    "contacts_get": "contacts",
    "contacts.list": "contacts",
    "contacts.search": "contacts",
    "contacts.get": "contacts",
    # Tasks
    "tasks_list": "tasks",
    "tasks_create": "tasks",
    "tasks_update": "tasks",
    "tasks.list": "tasks",
    "tasks.create": "tasks",
    "tasks.update": "tasks",
    # Classroom
    "google.classroom.courses": "classroom",
    "google.classroom.coursework": "classroom",
    "google.classroom.submissions": "classroom",
}


def _resolve_source_from_tool_name(tool_name: str) -> Optional[str]:
    """Resolve canonical source category from tool name.

    Supports both legacy underscore names (``gmail_list_messages``)
    and current dotted names (``gmail.list_messages``).
    """
    if not tool_name:
        return None

    if tool_name in _TOOL_SOURCE_MAP:
        return _TOOL_SOURCE_MAP[tool_name]

    normalized = tool_name.replace(".", "_")
    if normalized in _TOOL_SOURCE_MAP:
        return _TOOL_SOURCE_MAP[normalized]

    prefix = tool_name.split(".", 1)[0]
    if prefix in {"gmail", "calendar", "contacts", "tasks", "classroom"}:
        return prefix
    if tool_name.startswith("google.classroom."):
        return "classroom"
    return None


class GraphBridge:
    """Bridge between tool execution and the knowledge graph.

    Automatically links structured tool results into the graph
    via the AutoLinker.  Designed to run alongside IngestBridge.
    """

    def __init__(self, store: GraphStore, linker: AutoLinker) -> None:
        self._store = store
        self._linker = linker
        self._edges_created: int = 0
        self._enabled = True

    @classmethod
    async def create_default(
        cls,
        db_path: Optional[str] = None,
    ) -> "GraphBridge":
        """Create with default SQLiteGraphStore."""
        try:
            from bantz.data.graph_backends.sqlite_backend import SQLiteGraphStore
            store = SQLiteGraphStore(db_path)
            await store.initialise()
            linker = AutoLinker(store)
            return cls(store, linker)
        except Exception as e:
            logger.warning("[GraphBridge] Failed to init: %s — disabled", e)
            instance = cls.__new__(cls)
            instance._store = None  # type: ignore[assignment]
            instance._linker = None  # type: ignore[assignment]
            instance._edges_created = 0
            instance._enabled = False
            return instance

    async def on_tool_result(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
    ) -> int:
        """Process a tool result and link entities into the graph.

        Returns the number of edges created/updated.
        """
        if not self._enabled:
            return 0

        source = _resolve_source_from_tool_name(tool_name)
        if not source:
            return 0

        # Normalise result into linkable dicts
        items = self._extract_items(result)
        total_edges = 0

        for item in items:
            edges = await self._linker.link(source, item)
            total_edges += edges

        if total_edges > 0:
            self._edges_created += total_edges
            logger.debug(
                "[GraphBridge] %s: %d items → %d edges",
                tool_name, len(items), total_edges,
            )

            # Emit event for observability
            bus = _get_event_bus_safe()
            if bus is not None:
                try:
                    bus.publish(
                        event_type="graph.entity_linked",
                        data={
                            "tool": tool_name,
                            "source": source,
                            "items": len(items),
                            "edges_created": total_edges,
                            "total_edges": self._edges_created,
                        },
                        source="graph_bridge",
                    )
                except Exception:
                    pass

        return total_edges

    @property
    def total_edges_created(self) -> int:
        return self._edges_created

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def close(self) -> None:
        """Shut down the graph store."""
        if self._store:
            await self._store.close()

    # ── internal ──

    @staticmethod
    def _extract_items(result: Any) -> list[Dict[str, Any]]:
        """Normalise tool result into a list of dicts for linking."""
        if isinstance(result, dict):
            # Could be a single item or a wrapper with items/messages/events
            for key in ("items", "messages", "events", "results", "contacts", "tasks"):
                if key in result and isinstance(result[key], list):
                    return [
                        item for item in result[key]
                        if isinstance(item, dict)
                    ]
            return [result]
        elif isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []
