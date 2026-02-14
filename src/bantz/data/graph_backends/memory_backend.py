"""
InMemoryGraphStore — dict-based graph backend for unit tests.

Zero external dependencies.  Not suitable for production — data is
lost when the process exits.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from bantz.data.graph_store import GraphEdge, GraphNode, GraphStore


class InMemoryGraphStore(GraphStore):
    """Pure-Python in-memory graph store (for testing)."""

    def __init__(self) -> None:
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, GraphEdge] = {}
        self._initialised = False

    # ── lifecycle ──

    async def initialise(self) -> None:
        self._initialised = True

    async def close(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._initialised = False

    # ── nodes ──

    async def upsert_node(
        self,
        label: str,
        properties: Dict[str, Any],
        unique_key: str = "id",
    ) -> GraphNode:
        # Find existing by unique_key
        ukey_val = properties.get(unique_key)
        if ukey_val is not None:
            for node in self._nodes.values():
                if node.label == label and node.properties.get(unique_key) == ukey_val:
                    # Update in place (immutable dataclass, so replace)
                    merged = {**node.properties, **properties}
                    updated = GraphNode(
                        id=node.id,
                        label=label,
                        properties=merged,
                        created_at=node.created_at,
                        updated_at=time.time(),
                    )
                    self._nodes[node.id] = updated
                    return updated

        # Insert new
        node_id = str(uuid.uuid4())
        node = GraphNode(
            id=node_id,
            label=label,
            properties=properties,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._nodes[node_id] = node
        return node

    async def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    async def search_nodes(
        self,
        label: Optional[str] = None,
        limit: int = 50,
        **filters: Any,
    ) -> List[GraphNode]:
        results: List[GraphNode] = []
        for node in self._nodes.values():
            if label and node.label != label:
                continue
            if filters:
                match = all(
                    node.properties.get(k) == v for k, v in filters.items()
                )
                if not match:
                    continue
            results.append(node)
            if len(results) >= limit:
                break
        return results

    async def delete_node(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        # Cascade: remove all attached edges
        to_del = [
            eid for eid, e in self._edges.items()
            if e.source_id == node_id or e.target_id == node_id
        ]
        for eid in to_del:
            del self._edges[eid]
        return True

    # ── edges ──

    async def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        properties: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
    ) -> GraphEdge:
        props = properties or {}

        # Find existing (source, target, relation) triple
        for edge in self._edges.values():
            if (edge.source_id == source_id
                    and edge.target_id == target_id
                    and edge.relation == relation):
                merged = {**edge.properties, **props}
                updated = GraphEdge(
                    id=edge.id,
                    source_id=source_id,
                    target_id=target_id,
                    relation=relation,
                    properties=merged,
                    weight=weight,
                    created_at=edge.created_at,
                )
                self._edges[edge.id] = updated
                return updated

        edge_id = str(uuid.uuid4())
        edge = GraphEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            properties=props,
            weight=weight,
            created_at=time.time(),
        )
        self._edges[edge_id] = edge
        return edge

    async def get_neighbors(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "both",
        max_depth: int = 1,
        min_weight: float = 0.0,
    ) -> List[GraphNode]:
        if max_depth < 1:
            return []

        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}
        result_ids: list[str] = []

        for _depth in range(max_depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                for edge in self._edges.values():
                    if edge.weight < min_weight:
                        continue
                    if relation and edge.relation != relation:
                        continue

                    neighbour_id: Optional[str] = None
                    if direction in ("out", "both") and edge.source_id == nid:
                        neighbour_id = edge.target_id
                    if direction in ("in", "both") and edge.target_id == nid:
                        neighbour_id = edge.source_id

                    if neighbour_id and neighbour_id not in visited:
                        visited.add(neighbour_id)
                        next_frontier.add(neighbour_id)
                        result_ids.append(neighbour_id)

            frontier = next_frontier
            if not frontier:
                break

        return [self._nodes[nid] for nid in result_ids if nid in self._nodes]

    async def get_edges(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "both",
    ) -> List[GraphEdge]:
        results: List[GraphEdge] = []
        for edge in self._edges.values():
            if relation and edge.relation != relation:
                continue
            if direction == "out" and edge.source_id == node_id:
                results.append(edge)
            elif direction == "in" and edge.target_id == node_id:
                results.append(edge)
            elif direction == "both" and (
                edge.source_id == node_id or edge.target_id == node_id
            ):
                results.append(edge)
        return results

    async def get_edges_by_id(self, edge_id: str) -> List[GraphEdge]:
        edge = self._edges.get(edge_id)
        return [edge] if edge else []

    async def update_edge_weight(self, edge_id: str, weight: float) -> bool:
        edge = self._edges.get(edge_id)
        if not edge:
            return False
        updated = GraphEdge(
            id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            properties=edge.properties,
            weight=weight,
            created_at=edge.created_at,
        )
        self._edges[edge_id] = updated
        return True

    async def delete_edge(self, edge_id: str) -> bool:
        if edge_id in self._edges:
            del self._edges[edge_id]
            return True
        return False

    # ── stats ──

    async def stats(self) -> Dict[str, int]:
        return {"nodes": len(self._nodes), "edges": len(self._edges)}
