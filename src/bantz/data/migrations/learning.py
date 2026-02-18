"""Learning storage migrations — learning.db."""

from typing import Dict

MIGRATIONS: Dict[int, str] = {
    1: """
    -- v1: user profiles and learning data
    CREATE TABLE IF NOT EXISTS profiles (
        user_id    TEXT PRIMARY KEY,
        data       TEXT NOT NULL,
        updated_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS learning_data (
        user_id   TEXT NOT NULL,
        data_type TEXT NOT NULL,
        data      TEXT NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY (user_id, data_type)
    );
    """,
}
