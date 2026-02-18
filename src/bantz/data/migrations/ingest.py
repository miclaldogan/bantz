"""Ingest Store migrations — ingest.db (EPIC #1288)."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: initial schema (EPIC #1288)
    CREATE TABLE IF NOT EXISTS ingest_store (
        id           TEXT PRIMARY KEY,
        fingerprint  TEXT NOT NULL UNIQUE,
        data_class   TEXT NOT NULL,
        source       TEXT NOT NULL,
        content      TEXT NOT NULL,
        summary      TEXT,
        created_at   REAL NOT NULL,
        expires_at   REAL,
        accessed_at  REAL NOT NULL,
        access_count INTEGER NOT NULL DEFAULT 0,
        meta         TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ingest_class   ON ingest_store(data_class);
    CREATE INDEX IF NOT EXISTS idx_ingest_source  ON ingest_store(source);
    CREATE INDEX IF NOT EXISTS idx_ingest_expires ON ingest_store(expires_at);
    """,
}
