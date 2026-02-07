"""Persistent memory store for DialogSummaryManager (Issue #413).

Provides SQLite-backed persistence so that dialog summaries survive
across session restarts.

Features:
  - SQLite storage (thread-safe, single file)
  - Session-aware: each boot creates a new session_id
  - Configurable via ``MemoryStoreConfig``
  - PII filter applied before persist
  - Boot reload: load last N sessions' summaries
  - JSONL export/import for backup & migration

Usage:
    >>> store = SQLiteMemoryStore.from_config(MemoryStoreConfig())
    >>> store.save_turn(session_id, summary)
    >>> summaries = store.load_recent(max_sessions=3)

Design:
    - One row per ``CompactSummary`` turn
    - ``sessions`` table tracks session metadata
    - ``turns`` table stores individual turn data
    - ``store.close()`` or context-manager for cleanup
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from bantz.brain.memory_lite import CompactSummary, PIIFilter

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryStoreConfig",
    "SQLiteMemoryStore",
    "PersistentDialogSummaryManager",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryStoreConfig:
    """Configuration for persistent memory store.

    Attributes:
        db_path: Path to SQLite database file.
        max_sessions: Max number of past sessions to load on boot.
        max_turns_per_session: Max turns to keep per session.
        pii_filter_enabled: Apply PII filter before persisting.
    """

    db_path: str = "~/.bantz/memory.db"
    max_sessions: int = 5
    max_turns_per_session: int = 20
    pii_filter_enabled: bool = True

    @classmethod
    def from_env(cls) -> "MemoryStoreConfig":
        """Create config from environment variables.

        Env vars:
          BANTZ_MEMORY_DB_PATH: path to SQLite DB (default: ~/.bantz/memory.db)
          BANTZ_MEMORY_MAX_SESSIONS: max sessions to load (default: 5)
          BANTZ_MEMORY_MAX_TURNS: max turns per session (default: 20)
          BANTZ_MEMORY_PII_FILTER: "0" to disable (default: enabled)
        """
        db_path = os.getenv("BANTZ_MEMORY_DB_PATH", "~/.bantz/memory.db").strip()
        max_sessions = int(os.getenv("BANTZ_MEMORY_MAX_SESSIONS", "5"))
        max_turns = int(os.getenv("BANTZ_MEMORY_MAX_TURNS", "20"))
        pii_str = os.getenv("BANTZ_MEMORY_PII_FILTER", "1").strip().lower()
        pii = pii_str not in {"0", "false", "no", "off"}
        return cls(
            db_path=db_path,
            max_sessions=max(1, max_sessions),
            max_turns_per_session=max(1, max_turns),
            pii_filter_enabled=pii,
        )


# ---------------------------------------------------------------------------
# SQLite Memory Store
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    turn_count  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    turn_number     INTEGER NOT NULL,
    user_intent     TEXT NOT NULL,
    action_taken    TEXT NOT NULL,
    pending_items   TEXT NOT NULL DEFAULT '[]',
    timestamp       TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_created ON turns(created_at);
"""


class SQLiteMemoryStore:
    """SQLite-backed persistent memory store for dialog summaries.

    Thread-safe via ``check_same_thread=False`` and WAL journal mode.
    """

    def __init__(self, db_path: str):
        """Initialize store and create schema.

        Args:
            db_path: Path to SQLite database file. ``~`` is expanded.
                     Parent directories are created automatically.
        """
        self._db_path = str(Path(db_path).expanduser())
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level="DEFERRED",
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("[MEMORY_STORE] Opened SQLite store at %s", self._db_path)

    @classmethod
    def from_config(cls, config: MemoryStoreConfig) -> "SQLiteMemoryStore":
        """Create from config."""
        return cls(db_path=config.db_path)

    # ---- session management -------------------------------------------

    def create_session(self) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())[:12]
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO sessions (session_id, started_at) VALUES (?, ?)",
            (session_id, now),
        )
        self._conn.commit()
        logger.info("[MEMORY_STORE] Created session %s", session_id)
        return session_id

    def end_session(self, session_id: str) -> None:
        """Mark a session as ended."""
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        self._conn.commit()

    # ---- turn persistence ---------------------------------------------

    def save_turn(
        self,
        session_id: str,
        summary: CompactSummary,
        *,
        pii_filter: bool = True,
    ) -> None:
        """Persist a single turn summary.

        Args:
            session_id: Current session ID.
            summary: The turn summary to save.
            pii_filter: Apply PII filter before saving.
        """
        user_intent = summary.user_intent
        action_taken = summary.action_taken
        pending = list(summary.pending_items)

        if pii_filter:
            user_intent = PIIFilter.filter(user_intent)
            action_taken = PIIFilter.filter(action_taken)
            pending = [PIIFilter.filter(p) for p in pending]

        self._conn.execute(
            """INSERT INTO turns
               (session_id, turn_number, user_intent, action_taken, pending_items, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                summary.turn_number,
                user_intent,
                action_taken,
                json.dumps(pending, ensure_ascii=False),
                summary.timestamp.isoformat(),
            ),
        )
        self._conn.execute(
            "UPDATE sessions SET turn_count = turn_count + 1 WHERE session_id = ?",
            (session_id,),
        )
        self._conn.commit()

    # ---- loading ------------------------------------------------------

    def load_session_turns(self, session_id: str) -> list[CompactSummary]:
        """Load all turns for a specific session."""
        cursor = self._conn.execute(
            """SELECT turn_number, user_intent, action_taken, pending_items, timestamp
               FROM turns WHERE session_id = ? ORDER BY turn_number ASC""",
            (session_id,),
        )
        return [self._row_to_summary(row) for row in cursor.fetchall()]

    def load_recent(
        self,
        max_sessions: int = 5,
        max_turns_per_session: int = 20,
    ) -> list[tuple[str, list[CompactSummary]]]:
        """Load recent sessions with their turns.

        Returns list of ``(session_id, [summaries])`` ordered by most recent first.
        """
        cursor = self._conn.execute(
            """SELECT session_id FROM sessions
               ORDER BY started_at DESC LIMIT ?""",
            (max_sessions,),
        )
        sessions = [row[0] for row in cursor.fetchall()]

        result: list[tuple[str, list[CompactSummary]]] = []
        for sid in sessions:
            turns_cursor = self._conn.execute(
                """SELECT turn_number, user_intent, action_taken, pending_items, timestamp
                   FROM turns WHERE session_id = ?
                   ORDER BY turn_number ASC LIMIT ?""",
                (sid, max_turns_per_session),
            )
            turns = [self._row_to_summary(row) for row in turns_cursor.fetchall()]
            if turns:
                result.append((sid, turns))
        return result

    def load_all_turns_flat(
        self,
        max_sessions: int = 5,
        max_turns_per_session: int = 20,
    ) -> list[CompactSummary]:
        """Load all recent turns as a flat list (oldest first).

        Useful for bootstrapping DialogSummaryManager at boot.
        """
        sessions = self.load_recent(max_sessions, max_turns_per_session)
        # Reverse so oldest sessions come first
        all_turns: list[CompactSummary] = []
        for _sid, turns in reversed(sessions):
            all_turns.extend(turns)
        return all_turns

    # ---- maintenance --------------------------------------------------

    def prune_old_sessions(self, keep_sessions: int = 10) -> int:
        """Delete old sessions beyond keep limit.

        Returns number of sessions deleted.
        """
        cursor = self._conn.execute(
            """SELECT session_id FROM sessions
               ORDER BY started_at DESC LIMIT -1 OFFSET ?""",
            (keep_sessions,),
        )
        old_ids = [row[0] for row in cursor.fetchall()]
        if not old_ids:
            return 0

        placeholders = ",".join("?" * len(old_ids))
        self._conn.execute(
            f"DELETE FROM turns WHERE session_id IN ({placeholders})", old_ids
        )
        self._conn.execute(
            f"DELETE FROM sessions WHERE session_id IN ({placeholders})", old_ids
        )
        self._conn.commit()
        logger.info("[MEMORY_STORE] Pruned %d old sessions", len(old_ids))
        return len(old_ids)

    def session_count(self) -> int:
        """Count total sessions in store."""
        cursor = self._conn.execute("SELECT COUNT(*) FROM sessions")
        return cursor.fetchone()[0]

    def turn_count(self, session_id: Optional[str] = None) -> int:
        """Count turns, optionally filtered by session."""
        if session_id:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)
            )
        else:
            cursor = self._conn.execute("SELECT COUNT(*) FROM turns")
        return cursor.fetchone()[0]

    # ---- JSONL export/import -----------------------------------------

    def export_jsonl(self, file_path: str) -> int:
        """Export all turns as JSONL for backup.

        Returns number of records exported.
        """
        path = Path(file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        cursor = self._conn.execute(
            """SELECT t.session_id, t.turn_number, t.user_intent,
                      t.action_taken, t.pending_items, t.timestamp,
                      s.started_at
               FROM turns t JOIN sessions s ON t.session_id = s.session_id
               ORDER BY s.started_at ASC, t.turn_number ASC"""
        )
        count = 0
        with open(path, "w", encoding="utf-8") as f:
            for row in cursor:
                record = {
                    "session_id": row[0],
                    "turn_number": row[1],
                    "user_intent": row[2],
                    "action_taken": row[3],
                    "pending_items": json.loads(row[4]),
                    "timestamp": row[5],
                    "session_started_at": row[6],
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        logger.info("[MEMORY_STORE] Exported %d records to %s", count, path)
        return count

    def import_jsonl(self, file_path: str) -> int:
        """Import turns from JSONL backup.

        Returns number of records imported.
        """
        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"JSONL file not found: {path}")

        count = 0
        seen_sessions: set[str] = set()
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                sid = record["session_id"]

                # Create session if not seen
                if sid not in seen_sessions:
                    existing = self._conn.execute(
                        "SELECT 1 FROM sessions WHERE session_id = ?", (sid,)
                    ).fetchone()
                    if not existing:
                        self._conn.execute(
                            "INSERT INTO sessions (session_id, started_at) VALUES (?, ?)",
                            (sid, record.get("session_started_at", datetime.now().isoformat())),
                        )
                    seen_sessions.add(sid)

                self._conn.execute(
                    """INSERT INTO turns
                       (session_id, turn_number, user_intent, action_taken, pending_items, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        record["turn_number"],
                        record["user_intent"],
                        record["action_taken"],
                        json.dumps(record.get("pending_items", []), ensure_ascii=False),
                        record["timestamp"],
                    ),
                )
                count += 1

        self._conn.commit()
        logger.info("[MEMORY_STORE] Imported %d records from %s", count, path)
        return count

    # ---- cleanup ------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            logger.info("[MEMORY_STORE] Closed SQLite store")

    def __enter__(self) -> "SQLiteMemoryStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _row_to_summary(row: tuple) -> CompactSummary:
        """Convert a DB row to CompactSummary."""
        turn_number, user_intent, action_taken, pending_json, ts = row
        try:
            pending = json.loads(pending_json)
        except (json.JSONDecodeError, TypeError):
            pending = []
        try:
            timestamp = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            timestamp = datetime.now()
        return CompactSummary(
            turn_number=turn_number,
            user_intent=user_intent,
            action_taken=action_taken,
            pending_items=pending,
            timestamp=timestamp,
        )


# ---------------------------------------------------------------------------
# PersistentDialogSummaryManager — extends in-memory with persistence
# ---------------------------------------------------------------------------


class PersistentDialogSummaryManager:
    """DialogSummaryManager with SQLite persistence (Issue #413).

    Drop-in extension: wraps the in-memory DialogSummaryManager and
    mirrors all turns to SQLite.  On boot, loads recent sessions.

    Usage:
        >>> manager = PersistentDialogSummaryManager.create()
        >>> manager.add_turn(summary)  # saves to memory + SQLite
        >>> # On next boot:
        >>> manager2 = PersistentDialogSummaryManager.create()
        >>> # manager2 already has past sessions loaded
    """

    def __init__(
        self,
        store: SQLiteMemoryStore,
        config: MemoryStoreConfig,
        *,
        max_tokens: int = 500,
        max_turns: int = 5,
    ):
        from bantz.brain.memory_lite import DialogSummaryManager

        self._store = store
        self._config = config
        self._session_id = store.create_session()
        self._manager = DialogSummaryManager(
            max_tokens=max_tokens,
            max_turns=max_turns,
            pii_filter_enabled=config.pii_filter_enabled,
        )
        # Boot reload
        self._boot_reload()
        logger.info(
            "[MEMORY_PERSIST] Session %s started, loaded %d past turns",
            self._session_id, len(self._manager),
        )

    @classmethod
    def create(
        cls,
        config: Optional[MemoryStoreConfig] = None,
        *,
        max_tokens: int = 500,
        max_turns: int = 5,
    ) -> "PersistentDialogSummaryManager":
        """Factory: create with config (defaults to env vars)."""
        config = config or MemoryStoreConfig.from_env()
        store = SQLiteMemoryStore.from_config(config)
        return cls(store, config, max_tokens=max_tokens, max_turns=max_turns)

    def _boot_reload(self) -> None:
        """Load summaries from past sessions into in-memory manager."""
        past_turns = self._store.load_all_turns_flat(
            max_sessions=self._config.max_sessions,
            max_turns_per_session=self._config.max_turns_per_session,
        )
        for summary in past_turns:
            # Add directly without re-persisting
            self._manager.add_turn(summary)

    # ---- delegated API (mirrors DialogSummaryManager) -----------------

    @property
    def session_id(self) -> str:
        """Current session ID."""
        return self._session_id

    def add_turn(self, summary: CompactSummary) -> None:
        """Add turn to in-memory manager and persist to SQLite."""
        self._manager.add_turn(summary)
        self._store.save_turn(
            self._session_id, summary,
            pii_filter=self._config.pii_filter_enabled,
        )

    def to_prompt_block(self) -> str:
        """Generate prompt block from in-memory summaries."""
        return self._manager.to_prompt_block()

    def clear(self) -> None:
        """Clear in-memory summaries (SQLite data preserved)."""
        self._manager.clear()

    def get_latest(self) -> Optional[CompactSummary]:
        """Get most recent in-memory summary."""
        return self._manager.get_latest()

    @property
    def store(self) -> SQLiteMemoryStore:
        """Access underlying store for advanced operations."""
        return self._store

    def end_session(self) -> None:
        """End current session in SQLite."""
        self._store.end_session(self._session_id)

    def close(self) -> None:
        """End session and close store."""
        self.end_session()
        self._store.close()

    def __len__(self) -> int:
        return len(self._manager)

    def __str__(self) -> str:
        return self._manager.to_prompt_block()

    def __enter__(self) -> "PersistentDialogSummaryManager":
        return self

    def __exit__(self, *args) -> None:
        self.close()
