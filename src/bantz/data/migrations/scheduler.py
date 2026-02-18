"""Scheduler migrations — scheduler.db."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: reminders and checkins
    CREATE TABLE IF NOT EXISTS reminders (
        id              TEXT PRIMARY KEY,
        text            TEXT NOT NULL,
        remind_at       REAL NOT NULL,
        created_at      REAL NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',
        repeat_interval TEXT,
        snoozed_until   REAL
    );

    CREATE TABLE IF NOT EXISTS checkins (
        id            TEXT PRIMARY KEY,
        prompt        TEXT NOT NULL,
        schedule      TEXT NOT NULL,
        next_run_at   REAL NOT NULL,
        status        TEXT NOT NULL DEFAULT 'active',
        created_at    REAL NOT NULL,
        last_fired_at REAL
    );

    CREATE INDEX IF NOT EXISTS idx_rem_status ON reminders(status);
    CREATE INDEX IF NOT EXISTS idx_rem_remind ON reminders(remind_at);
    CREATE INDEX IF NOT EXISTS idx_chk_status ON checkins(status);
    CREATE INDEX IF NOT EXISTS idx_chk_next   ON checkins(next_run_at);
    """,
}
