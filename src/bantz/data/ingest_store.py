"""
Ingest Store — TTL-cached, fingerprint-deduped data layer for Bantz.

Every tool result, API response, and structured data payload flows through
the Ingest Store.  Items are classified into one of three data classes:

    EPHEMERAL   24 h   mail listings, search results, API responses
    SESSION      7 d   in-session decisions, active context fragments
    PERSISTENT   ∞     contacts, user preferences, learned knowledge

Duplicate detection is SHA-256 fingerprint based: if the same canonical
content from the same source arrives twice, only ``accessed_at`` is bumped.

Usage::

    store = IngestStore()                       # ~/.bantz/data/ingest.db
    rid = store.ingest({"subject": "hi"},
                       source="gmail",
                       data_class=DataClass.EPHEMERAL)
    record = store.get(rid)
    store.close()

The TTL sweeper can be run as a one-shot or as an asyncio background task
(see :func:`ttl_sweep_once` and :func:`start_ttl_sweeper`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ── Data-class / lifecycle enum ──────────────────────────────────

class DataClass(str, Enum):
    """Lifecycle category for ingested data."""
    EPHEMERAL  = "EPHEMERAL"    # TTL 24 h — mail listings, search results
    SESSION    = "SESSION"      # TTL 7 d  — session decisions, active context
    PERSISTENT = "PERSISTENT"   # TTL ∞    — contacts, preferences, learned facts

# Default TTL values in seconds
_TTL_MAP: Dict[DataClass, Optional[float]] = {
    DataClass.EPHEMERAL:  24 * 3600,        # 24 hours
    DataClass.SESSION:    7 * 24 * 3600,    # 7 days
    DataClass.PERSISTENT: None,              # never expires
}


# ── IngestRecord data-class ──────────────────────────────────────

@dataclass
class IngestRecord:
    """A single record stored in the Ingest Store."""
    id: str
    fingerprint: str
    data_class: DataClass
    source: str
    content: Dict[str, Any]
    summary: Optional[str] = None
    created_at: float = 0.0
    expires_at: Optional[float] = None
    accessed_at: float = 0.0
    access_count: int = 0
    meta: Optional[Dict[str, Any]] = None

    # ── helpers ───────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "fingerprint": self.fingerprint,
            "data_class": self.data_class.value,
            "source": self.source,
            "content": self.content,
            "summary": self.summary,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
            "meta": self.meta,
        }


# ── Fingerprinting ───────────────────────────────────────────────

def fingerprint(content: Any, source: str) -> str:
    """Deterministic SHA-256 fingerprint of canonical (source, content).

    Same content from the same source always produces the same hash.
    """
    if isinstance(content, (dict, list)):
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False)
    else:
        canonical = str(content)
    raw = f"{source}:{canonical}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── SQLite schema ────────────────────────────────────────────────

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS ingest_store (
    id              TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL UNIQUE,
    data_class      TEXT NOT NULL DEFAULT 'EPHEMERAL',
    source          TEXT NOT NULL,
    content         TEXT NOT NULL,
    summary         TEXT,
    created_at      REAL NOT NULL,
    expires_at      REAL,
    accessed_at     REAL,
    access_count    INTEGER NOT NULL DEFAULT 0,
    meta            TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_class   ON ingest_store(data_class);
CREATE INDEX IF NOT EXISTS idx_ingest_source  ON ingest_store(source);
CREATE INDEX IF NOT EXISTS idx_ingest_expires ON ingest_store(expires_at);
CREATE INDEX IF NOT EXISTS idx_ingest_fp      ON ingest_store(fingerprint);
"""


# ── IngestStore ──────────────────────────────────────────────────

class IngestStore:
    """SQLite-backed, thread-safe ingestion cache.

    Parameters
    ----------
    db_path : str | Path
        Path to the SQLite file.  ``":memory:"`` for in-memory store.
    auto_sweep : bool
        If *True*, expired rows are deleted on each :meth:`ingest` call
        when more than ``sweep_interval`` seconds have passed since the
        last sweep.  Set *False* for manual control.
    sweep_interval : int
        Minimum seconds between auto-sweeps (default 3 600 = 1 h).
    """

    def __init__(
        self,
        db_path: str | Path = "~/.bantz/data/ingest.db",
        *,
        auto_sweep: bool = True,
        sweep_interval: int = 3600,
    ) -> None:
        if str(db_path) == ":memory:":
            self._db_path = ":memory:"
        else:
            resolved = Path(str(db_path)).expanduser()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = str(resolved)

        self._auto_sweep = auto_sweep
        self._sweep_interval = sweep_interval
        self._last_sweep: float = 0.0
        self._lock = threading.Lock()

        self._conn = self._connect()
        self._ensure_schema()

    # ── connection helpers ────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ── core API ──────────────────────────────────────────────

    def ingest(
        self,
        content: Any,
        source: str,
        data_class: DataClass = DataClass.EPHEMERAL,
        *,
        summary: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        custom_ttl: Optional[float] = None,
    ) -> str:
        """Store a data payload.  Returns the record id.

        If an identical fingerprint already exists the existing record is
        *touched* (``accessed_at`` bumped, ``access_count`` incremented)
        and its id is returned — no duplicate row is created.

        Parameters
        ----------
        content : dict | list | str | Any
            The data payload (serialised to JSON internally).
        source : str
            Origin identifier, e.g. ``"gmail"``, ``"calendar"``.
        data_class : DataClass
            Lifecycle class — determines default TTL.
        summary : str, optional
            Human-readable summary (for compaction / display).
        meta : dict, optional
            Arbitrary metadata blob.
        custom_ttl : float, optional
            Override the default TTL for this record (seconds).
        """
        # Auto-sweep stale records
        if self._auto_sweep:
            self._maybe_sweep()

        fp = fingerprint(content, source)

        # Check for duplicate
        existing = self._get_by_fingerprint(fp)
        if existing is not None:
            self._touch(existing.id)
            logger.debug("Ingest dedup hit: fp=%s → id=%s", fp[:12], existing.id)
            return existing.id

        now = time.time()
        ttl = custom_ttl if custom_ttl is not None else _TTL_MAP.get(data_class)
        expires_at = (now + ttl) if ttl is not None else None

        record_id = uuid.uuid4().hex

        content_json = json.dumps(content, ensure_ascii=False, default=str)
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None

        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO ingest_store
                   (id, fingerprint, data_class, source, content,
                    summary, created_at, expires_at, accessed_at,
                    access_count, meta)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    record_id,
                    fp,
                    data_class.value,
                    source,
                    content_json,
                    summary,
                    now,
                    expires_at,
                    now,
                    meta_json,
                ),
            )

        logger.debug(
            "Ingested id=%s src=%s class=%s ttl=%s",
            record_id[:12], source, data_class.value,
            f"{ttl}s" if ttl else "∞",
        )
        return record_id

    def get(self, record_id: str) -> Optional[IngestRecord]:
        """Retrieve a record by id.  Returns *None* if not found or expired."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM ingest_store WHERE id = ?", (record_id,))
            row = cur.fetchone()
        if row is None:
            return None
        record = self._row_to_record(row)
        if record.is_expired:
            self._delete_ids([record_id])
            return None
        self._touch(record_id)
        return record

    def get_by_fingerprint(self, fp: str) -> Optional[IngestRecord]:
        """Look up by fingerprint hash.  Expired rows are pruned."""
        record = self._get_by_fingerprint(fp)
        if record is None:
            return None
        if record.is_expired:
            self._delete_ids([record.id])
            return None
        self._touch(record.id)
        return record

    def query(
        self,
        *,
        source: Optional[str] = None,
        data_class: Optional[DataClass] = None,
        limit: int = 50,
        include_expired: bool = False,
    ) -> List[IngestRecord]:
        """Query records with optional filters.

        Results are ordered by ``accessed_at`` descending (most-recently-used
        first).
        """
        clauses: list[str] = []
        params: list[Any] = []

        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if data_class is not None:
            clauses.append("data_class = ?")
            params.append(data_class.value)
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(time.time())

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM ingest_store{where} ORDER BY accessed_at DESC LIMIT ?"
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def search(
        self,
        keyword: str,
        *,
        source: Optional[str] = None,
        limit: int = 20,
    ) -> List[IngestRecord]:
        """Simple keyword search across content, summary and meta fields."""
        clauses = [
            "(content LIKE ? OR summary LIKE ? OR meta LIKE ?)",
            "(expires_at IS NULL OR expires_at > ?)",
        ]
        pattern = f"%{keyword}%"
        params: list[Any] = [pattern, pattern, pattern, time.time()]

        if source is not None:
            clauses.append("source = ?")
            params.append(source)

        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT * FROM ingest_store{where} ORDER BY accessed_at DESC LIMIT ?"
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def update_summary(self, record_id: str, summary: str) -> bool:
        """Set or overwrite the summary for a record."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE ingest_store SET summary = ? WHERE id = ?",
                (summary, record_id),
            )
            return cur.rowcount > 0

    def update_meta(self, record_id: str, meta: Dict[str, Any]) -> bool:
        """Merge new metadata into an existing record."""
        existing = self.get(record_id)
        if existing is None:
            return False
        merged = {**(existing.meta or {}), **meta}
        meta_json = json.dumps(merged, ensure_ascii=False)
        with self._cursor() as cur:
            cur.execute(
                "UPDATE ingest_store SET meta = ? WHERE id = ?",
                (meta_json, record_id),
            )
            return cur.rowcount > 0

    def promote(self, record_id: str, new_class: DataClass) -> bool:
        """Change the data-class of a record (e.g. SESSION → PERSISTENT).

        TTL is recalculated based on the new class.
        """
        record = self.get(record_id)
        if record is None:
            return False
        now = time.time()
        ttl = _TTL_MAP.get(new_class)
        new_expires = (now + ttl) if ttl is not None else None
        with self._cursor() as cur:
            cur.execute(
                "UPDATE ingest_store SET data_class = ?, expires_at = ? WHERE id = ?",
                (new_class.value, new_expires, record_id),
            )
            return cur.rowcount > 0

    def delete(self, record_id: str) -> bool:
        """Delete a single record."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM ingest_store WHERE id = ?", (record_id,))
            return cur.rowcount > 0

    # ── TTL sweeping ──────────────────────────────────────────

    def sweep_expired(self) -> int:
        """Delete all records whose ``expires_at`` has passed.

        Returns the number of rows deleted.
        """
        now = time.time()
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM ingest_store WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,),
            )
            count = cur.rowcount
        self._last_sweep = now
        if count:
            logger.info("TTL sweep: %d expired records deleted", count)
        return count

    # ── statistics ────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return basic store statistics."""
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ingest_store")
            total = cur.fetchone()[0]

            cur.execute(
                "SELECT data_class, COUNT(*) FROM ingest_store GROUP BY data_class"
            )
            by_class = {row[0]: row[1] for row in cur.fetchall()}

            cur.execute(
                "SELECT source, COUNT(*) FROM ingest_store GROUP BY source"
            )
            by_source = {row[0]: row[1] for row in cur.fetchall()}

            cur.execute(
                "SELECT COUNT(*) FROM ingest_store WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (time.time(),),
            )
            expired = cur.fetchone()[0]

        return {
            "total": total,
            "by_class": by_class,
            "by_source": by_source,
            "expired_pending_sweep": expired,
            "db_path": self._db_path,
        }

    # ── lifecycle ─────────────────────────────────────────────

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── private helpers ───────────────────────────────────────

    def _get_by_fingerprint(self, fp: str) -> Optional[IngestRecord]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM ingest_store WHERE fingerprint = ?", (fp,)
            )
            row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def _touch(self, record_id: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE ingest_store SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                (time.time(), record_id),
            )

    def _delete_ids(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._cursor() as cur:
            cur.execute(
                f"DELETE FROM ingest_store WHERE id IN ({placeholders})",
                list(ids),
            )
            return cur.rowcount

    def _maybe_sweep(self) -> None:
        now = time.time()
        if now - self._last_sweep >= self._sweep_interval:
            try:
                self.sweep_expired()
            except Exception as e:
                logger.warning("Auto-sweep failed: %s", e)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> IngestRecord:
        content_raw = row["content"]
        try:
            content = json.loads(content_raw)
        except (json.JSONDecodeError, TypeError):
            content = {"_raw": content_raw}

        meta_raw = row["meta"]
        try:
            meta = json.loads(meta_raw) if meta_raw else None
        except (json.JSONDecodeError, TypeError):
            meta = None

        return IngestRecord(
            id=row["id"],
            fingerprint=row["fingerprint"],
            data_class=DataClass(row["data_class"]),
            source=row["source"],
            content=content,
            summary=row["summary"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            accessed_at=row["accessed_at"],
            access_count=row["access_count"],
            meta=meta,
        )


# ── Async TTL sweeper (for daemon usage) ─────────────────────────

def ttl_sweep_once(store: IngestStore) -> int:
    """Run a single sweep pass (synchronous).  Returns rows deleted."""
    return store.sweep_expired()


async def start_ttl_sweeper(
    store: IngestStore,
    interval: int = 3600,
) -> None:
    """Run the TTL sweeper as an asyncio background task.

    Call with ``asyncio.create_task(start_ttl_sweeper(store))`` from
    the main event loop.  Runs every *interval* seconds (default 1 h).
    """
    logger.info("TTL sweeper started (interval=%ds)", interval)
    while True:
        try:
            deleted = store.sweep_expired()
            if deleted:
                logger.info("TTL sweep pass: %d records removed", deleted)
        except Exception as e:
            logger.error("TTL sweeper error: %s", e)
        await asyncio.sleep(interval)


# ── Convenience: classify tool results ────────────────────────────

# Tool source → default data-class mapping
_TOOL_DATA_CLASS: Dict[str, DataClass] = {
    # Read-only / listing tools → ephemeral
    "gmail.search_email":       DataClass.EPHEMERAL,
    "gmail.list_email":         DataClass.EPHEMERAL,
    "gmail.get_message":        DataClass.EPHEMERAL,
    "calendar.list_events":     DataClass.EPHEMERAL,
    "web.search":               DataClass.EPHEMERAL,
    "web.scrape":               DataClass.EPHEMERAL,
    # Write/action tools → session
    "gmail.send_email":         DataClass.SESSION,
    "gmail.reply_email":        DataClass.SESSION,
    "calendar.create_event":    DataClass.SESSION,
    "calendar.update_event":    DataClass.SESSION,
    "calendar.delete_event":    DataClass.SESSION,
    # Persistent knowledge
    "contacts.search":          DataClass.PERSISTENT,
    "contacts.get":             DataClass.PERSISTENT,
}


def classify_tool_result(tool_name: str) -> DataClass:
    """Return the default DataClass for a given tool's output.

    Falls back to EPHEMERAL for unknown tools.
    """
    return _TOOL_DATA_CLASS.get(tool_name, DataClass.EPHEMERAL)
