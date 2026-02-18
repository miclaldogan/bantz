"""
GraphStore — Backend-agnostic graph storage interface for Bantz.

Defines the abstract contract for all graph backends.  Concrete
implementations live under ``bantz.data.graph_backends``:

- **InMemoryGraphStore** — dict-based, zero deps, for unit tests
- **SQLiteGraphStore**   — lightweight MVP, no external services
- *(future)* Neo4jGraphStore, MemgraphStore, …

Node labels and edge relation types follow the canonical schema
defined in the issue spec (Person, Org, Event, Email, Task, …).

Usage::

    from bantz.data.graph_backends.sqlite_backend import SQLiteGraphStore
    store = SQLiteGraphStore("/tmp/graph.db")
    await store.initialise()
    node = await store.upsert_node("Person", {"name": "Ali", "email": "ali@x.com"})
    await store.close()
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Canonical node / edge labels ────────────────────────────────

NODE_LABELS = frozenset({
    "Person", "Org", "Project", "Document",
    "Event", "Email", "Task", "Topic",
})

EDGE_RELATIONS = frozenset({
    "SENT", "RECEIVED", "ATTENDS", "OWNS",
    "MEMBER_OF", "ASSIGNED_TO", "MENTIONS",
    "REPLY_TO", "RELATED_TO", "SCHEDULED_FOR",
    "BLOCKS", "FOLLOWS_UP", "LINKED_TO",
    "AUTHORED_BY", "DISCUSSED_IN",
})


# ── Data classes ────────────────────────────────────────────────

@dataclass(frozen=True)
class GraphNode:
    """A node in the knowledge graph."""
    id: str
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GraphEdge:
    """A directed edge between two nodes."""
    id: str
    source_id: str
    target_id: str
    relation: str
    properties: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)


# ── Abstract interface ──────────────────────────────────────────

class GraphStore(ABC):
    """Backend-agnostic graph storage interface.

    All methods are async to support both local (SQLite) and
    remote (Neo4j, Memgraph) backends uniformly.
    """

    # ── lifecycle ────────────────────────────────────────────────

    @abstractmethod
    async def initialise(self) -> None:
        """Create tables / indices / connections.  Idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources.  Safe to call multiple times."""

    # ── nodes ────────────────────────────────────────────────────

    @abstractmethod
    async def upsert_node(
        self,
        label: str,
        properties: Dict[str, Any],
        unique_key: str = "id",
    ) -> GraphNode:
        """Insert a node or update it if ``unique_key`` already exists.

        Parameters
        ----------
        label:
            One of the canonical ``NODE_LABELS``.
        properties:
            Arbitrary key-value pairs.  Must contain ``unique_key``.
        unique_key:
            Property used for dedup.  Defaults to ``"id"``.

        Returns
        -------
        The upserted node, with generated ``id`` if new.
        """

    @abstractmethod
    async def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Fetch a single node by its internal id."""

    @abstractmethod
    async def search_nodes(
        self,
        label: Optional[str] = None,
        limit: int = 50,
        **filters: Any,
    ) -> List[GraphNode]:
        """Return nodes matching *label* and property filters.

        Filters are ``property_name=value`` keyword arguments.
        """

    @abstractmethod
    async def delete_node(self, node_id: str) -> bool:
        """Delete a node **and** all its attached edges.

        Returns ``True`` if the node existed.
        """

    # ── edges ────────────────────────────────────────────────────

    @abstractmethod
    async def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        properties: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
    ) -> GraphEdge:
        """Insert an edge or update it if the same
        ``(source_id, target_id, relation)`` triple exists.
        """

    @abstractmethod
    async def get_neighbors(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "both",
        max_depth: int = 1,
        min_weight: float = 0.0,
    ) -> List[GraphNode]:
        """Traverse from *node_id* up to *max_depth* hops.

        Parameters
        ----------
        direction:
            ``"out"`` (source→target), ``"in"`` (target→source),
            or ``"both"``.
        min_weight:
            Exclude edges with weight below this threshold.
        """

    @abstractmethod
    async def get_edges(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "both",
    ) -> List[GraphEdge]:
        """Return edges attached to *node_id*."""

    @abstractmethod
    async def update_edge_weight(self, edge_id: str, weight: float) -> bool:
        """Set the weight of an existing edge.  Returns ``True`` on success."""

    @abstractmethod
    async def delete_edge(self, edge_id: str) -> bool:
        """Delete a single edge.  Returns ``True`` if it existed."""

    # ── decay & reinforcement ────────────────────────────────────

    async def apply_decay(
        self,
        edge_id: str,
        decay_rate: float = 0.05,
        reference_time: Optional[float] = None,
    ) -> float:
        """Reduce edge weight based on elapsed time.

        ``new_weight = weight × (1 - decay_rate) ^ days_elapsed``

        Returns the new weight.
        """
        edges = await self.get_edges_by_id(edge_id)
        if not edges:
            return 0.0
        edge = edges[0]
        now = reference_time or time.time()
        days = (now - edge.created_at) / 86400
        new_weight = max(edge.weight * ((1 - decay_rate) ** days), 0.01)
        await self.update_edge_weight(edge_id, new_weight)
        return new_weight

    async def reinforce(self, edge_id: str, boost: float = 0.1) -> float:
        """Increase edge weight when the relationship is used again.

        Returns the new weight (capped at 1.0).
        """
        edges = await self.get_edges_by_id(edge_id)
        if not edges:
            return 0.0
        new_weight = min(edges[0].weight + boost, 1.0)
        await self.update_edge_weight(edge_id, new_weight)
        return new_weight

    async def get_edges_by_id(self, edge_id: str) -> List[GraphEdge]:
        """Helper — fetch a single edge by ID.  Backends may override."""
        # Default: scan all edges.  Concrete backends should optimise.
        return []

    # ── stats ────────────────────────────────────────────────────

    @abstractmethod
    async def stats(self) -> Dict[str, int]:
        """Return counts: ``{"nodes": N, "edges": M}``."""
