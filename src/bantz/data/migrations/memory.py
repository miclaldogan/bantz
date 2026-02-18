"""Persistent Memory migrations — memory.db.

Absorbs the legacy memory/migrations.py schema and adds dialog_turns
from the brain memory store.
"""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: canonical memory schema
    -- Consolidates memory/migrations.py + brain/memory_store.py

    CREATE TABLE IF NOT EXISTS user_profile (
        id         TEXT PRIMARY KEY,
        key        TEXT NOT NULL UNIQUE,
        value      TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        start_time  REAL NOT NULL,
        end_time    REAL,
        summary     TEXT NOT NULL DEFAULT '',
        turn_count  INTEGER NOT NULL DEFAULT 0,
        metadata    TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS memory_items (
        id               TEXT PRIMARY KEY,
        session_id       TEXT,
        type             TEXT NOT NULL DEFAULT 'episodic',
        content          TEXT NOT NULL DEFAULT '',
        embedding_vector BLOB,
        importance       REAL NOT NULL DEFAULT 0.5,
        created_at       REAL NOT NULL,
        accessed_at      REAL NOT NULL,
        access_count     INTEGER NOT NULL DEFAULT 0,
        tags             TEXT NOT NULL DEFAULT '[]',
        metadata         TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS dialog_turns (
        id         TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        timestamp  REAL NOT NULL,
        tokens     INTEGER,
        metadata   TEXT NOT NULL DEFAULT '{}'
    );

    CREATE INDEX IF NOT EXISTS idx_mi_session    ON memory_items(session_id);
    CREATE INDEX IF NOT EXISTS idx_mi_type       ON memory_items(type);
    CREATE INDEX IF NOT EXISTS idx_mi_importance ON memory_items(importance);
    CREATE INDEX IF NOT EXISTS idx_mi_created    ON memory_items(created_at);
    CREATE INDEX IF NOT EXISTS idx_dt_session    ON dialog_turns(session_id);
    CREATE INDEX IF NOT EXISTS idx_dt_timestamp  ON dialog_turns(timestamp);
    CREATE INDEX IF NOT EXISTS idx_up_key        ON user_profile(key);
    """,
}
