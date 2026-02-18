"""Graph Memory migrations — graph.db (EPIC #1289)."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: initial schema (EPIC #1289)
    CREATE TABLE IF NOT EXISTS nodes (
        id         TEXT PRIMARY KEY,
        label      TEXT NOT NULL,
        properties TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS edges (
        id         TEXT PRIMARY KEY,
        source_id  TEXT NOT NULL,
        target_id  TEXT NOT NULL,
        relation   TEXT NOT NULL,
        properties TEXT NOT NULL DEFAULT '{}',
        weight     REAL NOT NULL DEFAULT 1.0,
        created_at REAL NOT NULL
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_edge_triple
        ON edges(source_id, target_id, relation);
    CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
    CREATE INDEX IF NOT EXISTS idx_nodes_label  ON nodes(label);
    """,
}
