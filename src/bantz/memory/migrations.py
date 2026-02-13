"""Schema migrations for persistent memory database (Issue #448).

Simple version-based migration system.  Each migration is a plain SQL
string keyed by its target version number.  :func:`migrate` applies any
outstanding migrations in order.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Migration registry — version → SQL
# -----------------------------------------------------------------------

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: initial schema (Issue #448)
    CREATE TABLE IF NOT EXISTS schema_version (
        version   INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_profile (
        id         TEXT PRIMARY KEY,
        key        TEXT NOT NULL UNIQUE,
        value      TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS session (
        id          TEXT PRIMARY KEY,
        start_time  TEXT NOT NULL,
        end_time    TEXT,
        summary     TEXT NOT NULL DEFAULT '',
        turn_count  INTEGER NOT NULL DEFAULT 0,
        metadata    TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS memory_item (
        id               TEXT PRIMARY KEY,
        session_id       TEXT,
        type             TEXT NOT NULL DEFAULT 'episodic',
        content          TEXT NOT NULL DEFAULT '',
        embedding_vector TEXT,
        importance       REAL NOT NULL DEFAULT 0.5,
        created_at       TEXT NOT NULL,
        accessed_at      TEXT NOT NULL,
        access_count     INTEGER NOT NULL DEFAULT 0,
        tags             TEXT NOT NULL DEFAULT '[]',
        metadata         TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (session_id) REFERENCES session(id)
    );

    CREATE TABLE IF NOT EXISTS tool_trace (
        id              TEXT PRIMARY KEY,
        session_id      TEXT,
        tool_name       TEXT NOT NULL DEFAULT '',
        args_hash       TEXT NOT NULL DEFAULT '',
        result_summary  TEXT NOT NULL DEFAULT '',
        success         INTEGER NOT NULL DEFAULT 1,
        latency_ms      REAL NOT NULL DEFAULT 0.0,
        created_at      TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES session(id)
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_memory_item_session ON memory_item(session_id);
    CREATE INDEX IF NOT EXISTS idx_memory_item_type    ON memory_item(type);
    CREATE INDEX IF NOT EXISTS idx_memory_item_importance ON memory_item(importance);
    CREATE INDEX IF NOT EXISTS idx_tool_trace_session  ON tool_trace(session_id);
    CREATE INDEX IF NOT EXISTS idx_tool_trace_tool     ON tool_trace(tool_name);
    CREATE INDEX IF NOT EXISTS idx_user_profile_key    ON user_profile(key);
    """,
}

LATEST_VERSION = max(MIGRATIONS.keys())


def _current_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version (0 if fresh database)."""
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        # schema_version table doesn't exist yet → version 0
        return 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all outstanding migrations and return the new version.

    Parameters
    ----------
    conn:
        An open SQLite connection (WAL mode recommended).

    Returns
    -------
    int
        The schema version after migration.
    """
    current = _current_version(conn)
    if current >= LATEST_VERSION:
        logger.debug("[migrate] Schema already at v%d — nothing to do.", current)
        return current

    for version in sorted(MIGRATIONS.keys()):
        if version <= current:
            continue
        logger.info("[migrate] Applying migration v%d …", version)
        conn.executescript(MIGRATIONS[version])
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.utcnow().isoformat()),
        )
        conn.commit()
        logger.info("[migrate] Migration v%d applied.", version)

    new_version = _current_version(conn)
    return new_version
