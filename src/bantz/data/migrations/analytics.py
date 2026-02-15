"""Analytics migrations — analytics.db."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: analytics events and corrections
    CREATE TABLE IF NOT EXISTS events (
        id         TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        data       TEXT NOT NULL DEFAULT '{}',
        source     TEXT,
        created_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS corrections (
        id              TEXT PRIMARY KEY,
        original_text   TEXT NOT NULL,
        corrected_text  TEXT NOT NULL,
        correction_type TEXT,
        source          TEXT,
        created_at      REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_events_type    ON events(event_type);
    CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
    CREATE INDEX IF NOT EXISTS idx_corr_type      ON corrections(correction_type);
    """,
}
