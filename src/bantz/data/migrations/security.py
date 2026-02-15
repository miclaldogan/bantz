"""Security storage migrations — security.db."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: encrypted key-value store
    CREATE TABLE IF NOT EXISTS secure_storage (
        key        TEXT PRIMARY KEY,
        value      BLOB NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        expires_at REAL,
        tags       TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ss_expires ON secure_storage(expires_at);
    """,
}
