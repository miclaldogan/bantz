"""Snippet Store migrations — snippets.db."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: snippet store
    CREATE TABLE IF NOT EXISTS snippets (
        id            TEXT PRIMARY KEY,
        content       TEXT NOT NULL,
        snippet_type  TEXT NOT NULL,
        source        TEXT,
        timestamp     REAL NOT NULL,
        confidence    REAL NOT NULL DEFAULT 1.0,
        ttl_seconds   REAL,
        tags          TEXT,
        metadata      TEXT,
        access_count  INTEGER NOT NULL DEFAULT 0,
        last_accessed REAL
    );

    CREATE INDEX IF NOT EXISTS idx_snip_type   ON snippets(snippet_type);
    CREATE INDEX IF NOT EXISTS idx_snip_source ON snippets(source);
    """,
}
