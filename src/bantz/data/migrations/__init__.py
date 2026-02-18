"""
Bantz Data Platform — Versioned Migration System.

Each database has its own migration module (e.g., ``ingest.py``,
``observability.py``) that defines a ``MIGRATIONS: Dict[int, str]``
registry mapping version numbers to SQL scripts.

The shared :func:`migrate` function applies outstanding migrations
to any SQLite connection.

Usage::

    from bantz.data.migrations import migrate
    from bantz.data.migrations.ingest import MIGRATIONS

    conn = sqlite3.connect("~/.bantz/data/ingest.db")
    new_version = migrate(conn, MIGRATIONS)
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Dict

logger = logging.getLogger(__name__)

# ── Schema-version bootstrap ────────────────────────────────────

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);
"""


def _current_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version (0 if fresh database)."""
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def migrate(conn: sqlite3.Connection, migrations: Dict[int, str]) -> int:
    """Apply all outstanding migrations and return the new version.

    Parameters
    ----------
    conn:
        An open SQLite connection (WAL mode recommended).
    migrations:
        Version → SQL mapping.  Versions must be positive integers.

    Returns
    -------
    int
        The schema version after migration.
    """
    if not migrations:
        return 0

    latest = max(migrations.keys())
    conn.executescript(_SCHEMA_VERSION_DDL)
    current = _current_version(conn)

    if current >= latest:
        logger.debug(
            "[migrate] Schema already at v%d — nothing to do.", current
        )
        return current

    for version in sorted(migrations.keys()):
        if version <= current:
            continue
        logger.info("[migrate] Applying migration v%d …", version)
        conn.executescript(migrations[version])
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, time.time()),
        )
        conn.commit()
        logger.info("[migrate] Migration v%d applied.", version)

    return _current_version(conn)
