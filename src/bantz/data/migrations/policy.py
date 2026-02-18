"""Policy decisions migrations — policy.db (EPIC #1291)."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: policy decision audit log (EPIC #1291)
    CREATE TABLE IF NOT EXISTS policy_decisions (
        id          TEXT PRIMARY KEY,
        run_id      TEXT,
        tool_name   TEXT,
        intent      TEXT,
        pattern     TEXT,
        decision    TEXT NOT NULL,
        reason      TEXT NOT NULL,
        user_action TEXT,
        risk_level  TEXT,
        created_at  REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_pd_run      ON policy_decisions(run_id);
    CREATE INDEX IF NOT EXISTS idx_pd_decision ON policy_decisions(decision);
    CREATE INDEX IF NOT EXISTS idx_pd_tool     ON policy_decisions(tool_name);
    CREATE INDEX IF NOT EXISTS idx_pd_created  ON policy_decisions(created_at);
    """,
}
