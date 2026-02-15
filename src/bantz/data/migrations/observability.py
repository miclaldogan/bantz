"""Observability migrations — observability.db (EPIC #1290)."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: initial schema (EPIC #1290)
    CREATE TABLE IF NOT EXISTS runs (
        run_id       TEXT PRIMARY KEY,
        user_input   TEXT NOT NULL,
        route        TEXT,
        intent       TEXT,
        final_output TEXT,
        model        TEXT,
        total_tokens INTEGER,
        latency_ms   INTEGER,
        status       TEXT DEFAULT 'pending',
        error        TEXT,
        session_id   TEXT,
        created_at   REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tool_calls (
        call_id        TEXT PRIMARY KEY,
        run_id         TEXT NOT NULL REFERENCES runs(run_id),
        tool_name      TEXT NOT NULL,
        params         TEXT,
        result_hash    TEXT,
        result_summary TEXT,
        latency_ms     INTEGER,
        status         TEXT DEFAULT 'pending',
        error          TEXT,
        confirmation   TEXT DEFAULT 'auto',
        retry_count    INTEGER DEFAULT 0,
        created_at     REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS artifacts (
        artifact_id TEXT PRIMARY KEY,
        run_id      TEXT REFERENCES runs(run_id),
        type        TEXT NOT NULL,
        title       TEXT,
        content     TEXT,
        summary     TEXT,
        embedding   BLOB,
        source_ref  TEXT,
        mime_type   TEXT,
        size_bytes  INTEGER,
        created_at  REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id);
    CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
    CREATE INDEX IF NOT EXISTS idx_runs_status  ON runs(status);
    CREATE INDEX IF NOT EXISTS idx_tc_run       ON tool_calls(run_id);
    CREATE INDEX IF NOT EXISTS idx_tc_tool      ON tool_calls(tool_name);
    CREATE INDEX IF NOT EXISTS idx_tc_status    ON tool_calls(status);
    CREATE INDEX IF NOT EXISTS idx_tc_created   ON tool_calls(created_at);
    CREATE INDEX IF NOT EXISTS idx_art_run      ON artifacts(run_id);
    CREATE INDEX IF NOT EXISTS idx_art_type     ON artifacts(type);
    """,
}
