"""Persistent SQLite-backed memory store (Issue #448).

Provides :class:`PersistentMemoryStore` — the CRUD + search layer over
``~/.bantz/memory.db`` (or ``$XDG_DATA_HOME/bantz/memory.db``).

Thread-safe via ``threading.Lock`` around every database operation.

Usage::

    store = PersistentMemoryStore()          # uses default path
    store = PersistentMemoryStore(":memory:") # in-memory for tests

    item_id = store.write(MemoryItem(content="merhaba"))
    item = store.read(item_id)
    results = store.search("merhaba", limit=5)
    store.delete(item_id)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bantz.memory.migrations import migrate
from bantz.memory.models import (
    MemoryItem,
    MemoryItemType,
    Session,
    ToolTrace,
    UserProfile,
)

logger = logging.getLogger(__name__)

__all__ = ["PersistentMemoryStore"]


def _default_db_path() -> str:
    """Return the default database file path.

    Follows XDG_DATA_HOME → ``~/.local/share/bantz/memory.db``
    Falls back to ``~/.bantz/memory.db``.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        base = Path(xdg) / "bantz"
    else:
        base = Path.home() / ".bantz"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "memory.db")


class PersistentMemoryStore:
    """SQLite-backed persistent memory store.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Use ``":memory:"`` for tests.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        migrate(self._conn)

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # MemoryItem CRUD
    # ------------------------------------------------------------------

    def write(self, item: MemoryItem) -> str:
        """Persist a :class:`MemoryItem` and return its id."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_item
                    (id, session_id, type, content, embedding_vector,
                     importance, created_at, accessed_at, access_count,
                     tags, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.session_id,
                    item.type.value if isinstance(item.type, MemoryItemType) else item.type,
                    item.content,
                    json.dumps(item.embedding_vector) if item.embedding_vector else None,
                    item.importance,
                    item.created_at.isoformat(),
                    item.accessed_at.isoformat(),
                    item.access_count,
                    json.dumps(item.tags),
                    json.dumps(item.metadata),
                ),
            )
        return item.id

    def read(self, item_id: str) -> Optional[MemoryItem]:
        """Read a :class:`MemoryItem` by id."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_item WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_memory_item(row)

    def search(
        self,
        query: str,
        limit: int = 5,
        type_filter: Optional[str] = None,
    ) -> List[MemoryItem]:
        """Search memory items by keyword matching.

        Parameters
        ----------
        query:
            Space-separated keywords (matched against ``content``).
        limit:
            Maximum number of results.
        type_filter:
            Optional memory type filter (``"episodic"`` / ``"semantic"`` / ``"fact"``).

        Returns
        -------
        list[MemoryItem]
            Matching items sorted by importance descending.
        """
        keywords = [kw.strip().lower() for kw in query.split() if kw.strip()]
        if not keywords:
            return []

        conditions = []
        params: list[Any] = []

        # Keyword matching — each keyword must appear in content
        for kw in keywords:
            conditions.append("LOWER(content) LIKE ?")
            params.append(f"%{kw}%")

        if type_filter:
            conditions.append("type = ?")
            params.append(type_filter)

        where = " AND ".join(conditions)
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memory_item WHERE {where} "
                f"ORDER BY importance DESC, accessed_at DESC LIMIT ?",
                params,
            ).fetchall()

        return [self._row_to_memory_item(r) for r in rows]

    def delete(self, item_id: str) -> bool:
        """Delete a :class:`MemoryItem` by id.  Returns *True* if deleted."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memory_item WHERE id = ?", (item_id,)
            )
            return cur.rowcount > 0

    def list_items(
        self,
        type_filter: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryItem]:
        """List memory items with optional filters."""
        conditions = []
        params: list[Any] = []

        if type_filter:
            conditions.append("type = ?")
            params.append(type_filter)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM memory_item {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()

        return [self._row_to_memory_item(r) for r in rows]

    def update_access(self, item_id: str) -> bool:
        """Bump access count and timestamp for a memory item."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memory_item SET access_count = access_count + 1, "
                "accessed_at = ? WHERE id = ?",
                (now, item_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def create_session(self, metadata: Optional[Dict[str, Any]] = None) -> Session:
        """Create and persist a new session."""
        sess = Session(metadata=metadata or {})
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO session (id, start_time, end_time, summary,
                                     turn_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sess.id,
                    sess.start_time.isoformat(),
                    None,
                    sess.summary,
                    sess.turn_count,
                    json.dumps(sess.metadata),
                ),
            )
        return sess

    def get_session(self, session_id: str) -> Optional[Session]:
        """Read a :class:`Session` by id."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM session WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def close_session(self, session_id: str, summary: str = "") -> bool:
        """Close a session (set end_time and summary)."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE session SET end_time = ?, summary = ? WHERE id = ?",
                (now, summary, session_id),
            )
            return cur.rowcount > 0

    def increment_turn_count(self, session_id: str) -> bool:
        """Increment the turn counter for a session."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE session SET turn_count = turn_count + 1 WHERE id = ?",
                (session_id,),
            )
            return cur.rowcount > 0

    def list_sessions(self, limit: int = 20) -> List[Session]:
        """List recent sessions ordered by start_time descending."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM session ORDER BY start_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    # ------------------------------------------------------------------
    # ToolTrace CRUD
    # ------------------------------------------------------------------

    def write_tool_trace(self, trace: ToolTrace) -> str:
        """Persist a tool trace and return its id."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tool_trace
                    (id, session_id, tool_name, args_hash,
                     result_summary, success, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.id,
                    trace.session_id,
                    trace.tool_name,
                    trace.args_hash,
                    trace.result_summary,
                    1 if trace.success else 0,
                    trace.latency_ms,
                    trace.created_at.isoformat(),
                ),
            )
        return trace.id

    def get_tool_traces(
        self,
        session_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[ToolTrace]:
        """Query tool traces with optional filters."""
        conditions = []
        params: list[Any] = []

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if tool_name:
            conditions.append("tool_name = ?")
            params.append(tool_name)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM tool_trace {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()

        return [self._row_to_tool_trace(r) for r in rows]

    # ------------------------------------------------------------------
    # UserProfile CRUD
    # ------------------------------------------------------------------

    def set_profile(self, key: str, value: str) -> str:
        """Set (upsert) a user-profile entry.  Returns the profile row id."""
        now = datetime.utcnow().isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM user_profile WHERE key = ?", (key,)
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE user_profile SET value = ?, updated_at = ? WHERE key = ?",
                    (value, now, key),
                )
                return row["id"]
            else:
                profile = UserProfile(key=key, value=value)
                self._conn.execute(
                    "INSERT INTO user_profile (id, key, value, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (profile.id, profile.key, profile.value, now),
                )
                return profile.id

    def get_profile(self, key: str) -> Optional[str]:
        """Get a profile value by key."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM user_profile WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def delete_profile(self, key: str) -> bool:
        """Delete a profile entry by key."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM user_profile WHERE key = ?", (key,)
            )
            return cur.rowcount > 0

    def list_profile_keys(self) -> List[str]:
        """Return all profile keys."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key FROM user_profile ORDER BY key"
            ).fetchall()
        return [r["key"] for r in rows]

    # ------------------------------------------------------------------
    # Stats / introspection
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return a summary of the store contents."""
        with self._lock:
            items = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM memory_item"
            ).fetchone()["cnt"]
            sessions = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM session"
            ).fetchone()["cnt"]
            traces = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM tool_trace"
            ).fetchone()["cnt"]
            profiles = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM user_profile"
            ).fetchone()["cnt"]
        return {
            "memory_items": items,
            "sessions": sessions,
            "tool_traces": traces,
            "user_profiles": profiles,
        }

    # ------------------------------------------------------------------
    # Row → model helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_memory_item(row: sqlite3.Row) -> MemoryItem:
        emb_raw = row["embedding_vector"]
        embedding = json.loads(emb_raw) if emb_raw else None
        return MemoryItem(
            id=row["id"],
            session_id=row["session_id"],
            type=MemoryItemType(row["type"]),
            content=row["content"],
            embedding_vector=embedding,
            importance=row["importance"],
            created_at=datetime.fromisoformat(row["created_at"]),
            accessed_at=datetime.fromisoformat(row["accessed_at"]),
            access_count=row["access_count"],
            tags=json.loads(row["tags"]),
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        end = row["end_time"]
        return Session(
            id=row["id"],
            start_time=datetime.fromisoformat(row["start_time"]),
            end_time=datetime.fromisoformat(end) if end else None,
            summary=row["summary"],
            turn_count=row["turn_count"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_tool_trace(row: sqlite3.Row) -> ToolTrace:
        return ToolTrace(
            id=row["id"],
            session_id=row["session_id"],
            tool_name=row["tool_name"],
            args_hash=row["args_hash"],
            result_summary=row["result_summary"],
            success=bool(row["success"]),
            latency_ms=row["latency_ms"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
