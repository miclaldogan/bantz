"""
SQLiteGraphStore — Lightweight graph backend backed by SQLite.

Schema
------
- **nodes** (id, label, properties JSON, created_at, updated_at)
- **edges** (id, source_id, target_id, relation, properties JSON,
  weight, created_at)

Good for ≤100 K nodes on a single-user local machine.  Zero
external dependencies beyond the stdlib ``sqlite3`` module.

Usage::

    store = SQLiteGraphStore("/path/to/graph.db")
    await store.initialise()
    node = await store.upsert_node("Person", {"name": "Ali"})
    await store.close()
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from bantz.data.graph_store import GraphEdge, GraphNode, GraphStore

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path.home() / ".bantz" / "data" / "graph.db"


class SQLiteGraphStore(GraphStore):
    """SQLite-backed graph store — the default MVP backend."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB)
        self._local = threading.local()
        self._initialised = False

    # ── connection management (thread-local) ──

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    # ── lifecycle ──

    async def initialise(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id          TEXT PRIMARY KEY,
                label       TEXT NOT NULL,
                properties  TEXT NOT NULL DEFAULT '{}',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);

            CREATE TABLE IF NOT EXISTS edges (
                id          TEXT PRIMARY KEY,
                source_id   TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                relation    TEXT NOT NULL,
                properties  TEXT NOT NULL DEFAULT '{}',
                weight      REAL NOT NULL DEFAULT 1.0,
                created_at  REAL NOT NULL,
                FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_triple
                ON edges(source_id, target_id, relation);
        """)
        conn.commit()
        self._initialised = True
        logger.info("SQLiteGraphStore initialised at %s", self._db_path)

    async def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None
        self._initialised = False

    # ── helpers ──

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            id=row["id"],
            label=row["label"],
            properties=json.loads(row["properties"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation=row["relation"],
            properties=json.loads(row["properties"]),
            weight=row["weight"],
            created_at=row["created_at"],
        )

    # ── nodes ──

    async def upsert_node(
        self,
        label: str,
        properties: Dict[str, Any],
        unique_key: str = "id",
    ) -> GraphNode:
        conn = self._conn()
        now = time.time()
        ukey_val = properties.get(unique_key)

        # Try to find an existing node by unique_key
        if ukey_val is not None:
            row = conn.execute(
                "SELECT * FROM nodes WHERE label = ? AND json_extract(properties, ?) = ?",
                (label, f"$.{unique_key}", json.dumps(ukey_val) if isinstance(ukey_val, (dict, list)) else ukey_val),
            ).fetchone()
            if row:
                existing = json.loads(row["properties"])
                merged = {**existing, **properties}
                conn.execute(
                    "UPDATE nodes SET properties = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(merged, ensure_ascii=False), now, row["id"]),
                )
                conn.commit()
                return GraphNode(
                    id=row["id"],
                    label=label,
                    properties=merged,
                    created_at=row["created_at"],
                    updated_at=now,
                )

        # Insert new
        node_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO nodes (id, label, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (node_id, label, json.dumps(properties, ensure_ascii=False), now, now),
        )
        conn.commit()
        return GraphNode(
            id=node_id, label=label, properties=properties,
            created_at=now, updated_at=now,
        )

    async def get_node(self, node_id: str) -> Optional[GraphNode]:
        row = self._conn().execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return self._row_to_node(row) if row else None

    async def search_nodes(
        self,
        label: Optional[str] = None,
        limit: int = 50,
        **filters: Any,
    ) -> List[GraphNode]:
        conn = self._conn()
        clauses: list[str] = []
        params: list[Any] = []

        if label:
            clauses.append("label = ?")
            params.append(label)

        for key, val in filters.items():
            clauses.append("json_extract(properties, ?) = ?")
            params.append(f"$.{key}")
            params.append(val)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM nodes {where} LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_node(r) for r in rows]

    async def delete_node(self, node_id: str) -> bool:
        conn = self._conn()
        # Cascade via FK, but also explicitly for clarity
        conn.execute(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
            (node_id, node_id),
        )
        cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        conn.commit()
        return cur.rowcount > 0

    # ── edges ──

    async def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        properties: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
    ) -> GraphEdge:
        conn = self._conn()
        props = properties or {}
        now = time.time()

        # Check for existing triple
        row = conn.execute(
            "SELECT * FROM edges WHERE source_id = ? AND target_id = ? AND relation = ?",
            (source_id, target_id, relation),
        ).fetchone()

        if row:
            existing = json.loads(row["properties"])
            merged = {**existing, **props}
            conn.execute(
                "UPDATE edges SET properties = ?, weight = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), weight, row["id"]),
            )
            conn.commit()
            return GraphEdge(
                id=row["id"], source_id=source_id, target_id=target_id,
                relation=relation, properties=merged, weight=weight,
                created_at=row["created_at"],
            )

        edge_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, relation, properties, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (edge_id, source_id, target_id, relation,
             json.dumps(props, ensure_ascii=False), weight, now),
        )
        conn.commit()
        return GraphEdge(
            id=edge_id, source_id=source_id, target_id=target_id,
            relation=relation, properties=props, weight=weight,
            created_at=now,
        )

    async def get_neighbors(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "both",
        max_depth: int = 1,
        min_weight: float = 0.0,
    ) -> List[GraphNode]:
        conn = self._conn()
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}
        result_ids: list[str] = []

        for _depth in range(max_depth):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for nid in frontier:
                rows: list[sqlite3.Row] = []
                if direction in ("out", "both"):
                    sql = "SELECT target_id AS neighbour FROM edges WHERE source_id = ? AND weight >= ?"
                    params: list[Any] = [nid, min_weight]
                    if relation:
                        sql += " AND relation = ?"
                        params.append(relation)
                    rows.extend(conn.execute(sql, params).fetchall())

                if direction in ("in", "both"):
                    sql = "SELECT source_id AS neighbour FROM edges WHERE target_id = ? AND weight >= ?"
                    params = [nid, min_weight]
                    if relation:
                        sql += " AND relation = ?"
                        params.append(relation)
                    rows.extend(conn.execute(sql, params).fetchall())

                for row in rows:
                    nb = row["neighbour"]
                    if nb not in visited:
                        visited.add(nb)
                        next_frontier.add(nb)
                        result_ids.append(nb)
            frontier = next_frontier

        if not result_ids:
            return []

        placeholders = ",".join("?" * len(result_ids))
        node_rows = conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({placeholders})", result_ids
        ).fetchall()

        node_map = {r["id"]: self._row_to_node(r) for r in node_rows}
        return [node_map[nid] for nid in result_ids if nid in node_map]

    async def get_edges(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "both",
    ) -> List[GraphEdge]:
        conn = self._conn()
        results: List[GraphEdge] = []

        if direction in ("out", "both"):
            sql = "SELECT * FROM edges WHERE source_id = ?"
            params: list[Any] = [node_id]
            if relation:
                sql += " AND relation = ?"
                params.append(relation)
            results.extend(self._row_to_edge(r) for r in conn.execute(sql, params))

        if direction in ("in", "both"):
            sql = "SELECT * FROM edges WHERE target_id = ?"
            params = [node_id]
            if relation:
                sql += " AND relation = ?"
                params.append(relation)
            results.extend(self._row_to_edge(r) for r in conn.execute(sql, params))

        return results

    async def get_edges_by_id(self, edge_id: str) -> List[GraphEdge]:
        row = self._conn().execute(
            "SELECT * FROM edges WHERE id = ?", (edge_id,)
        ).fetchone()
        return [self._row_to_edge(row)] if row else []

    async def update_edge_weight(self, edge_id: str, weight: float) -> bool:
        cur = self._conn().execute(
            "UPDATE edges SET weight = ? WHERE id = ?", (weight, edge_id)
        )
        self._conn().commit()
        return cur.rowcount > 0

    async def delete_edge(self, edge_id: str) -> bool:
        cur = self._conn().execute(
            "DELETE FROM edges WHERE id = ?", (edge_id,)
        )
        self._conn().commit()
        return cur.rowcount > 0

    # ── stats ──

    async def stats(self) -> Dict[str, int]:
        conn = self._conn()
        nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        # Label distribution
        labels: Dict[str, int] = {}
        for row in conn.execute("SELECT label, COUNT(*) FROM nodes GROUP BY label"):
            labels[row[0]] = row[1]

        # Relation distribution
        relations: Dict[str, int] = {}
        for row in conn.execute("SELECT relation, COUNT(*) FROM edges GROUP BY relation"):
            relations[row[0]] = row[1]

        return {
            "nodes": nodes,
            "edges": edges,
            "labels": labels,
            "relations": relations,
        }
