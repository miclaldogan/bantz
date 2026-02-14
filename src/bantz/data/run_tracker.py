"""
RunTracker — Observability layer for Bantz runs, tool calls, and artifacts.

Records every user interaction (run), every tool invocation (tool_call),
and any produced artifacts (summaries, transcripts, drafts) into a local
SQLite database for debugging, metrics, and replay.

Usage::

    tracker = RunTracker()
    await tracker.initialise()

    async with tracker.track_run("yarınki toplantıları göster") as run:
        run.route = "calendar"
        run.intent = "list_events"

        async with run.track_tool("calendar.list_events", {"date": "tomorrow"}) as tc:
            result = await call_tool(...)
            tc.set_result(result)

        run.final_output = "Yarın 3 toplantın var..."
        run.model = "qwen2.5-3b"
        run.total_tokens = 420

Default DB location: ``~/.bantz/data/observability.db``
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── SQL Schema ────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    user_input  TEXT NOT NULL,
    route       TEXT,
    intent      TEXT,
    final_output TEXT,
    model       TEXT,
    total_tokens INTEGER,
    latency_ms  INTEGER,
    status      TEXT DEFAULT 'pending',
    error       TEXT,
    session_id  TEXT,
    created_at  REAL NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_runs_session   ON runs(session_id);
CREATE INDEX IF NOT EXISTS idx_runs_created   ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_status    ON runs(status);
CREATE INDEX IF NOT EXISTS idx_tc_run         ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tc_tool        ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tc_status      ON tool_calls(status);
CREATE INDEX IF NOT EXISTS idx_tc_created     ON tool_calls(created_at);
CREATE INDEX IF NOT EXISTS idx_art_run        ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_art_type       ON artifacts(type);
"""

# ── Defaults ──────────────────────────────────────────────────────

DEFAULT_DB_PATH = os.path.join(
    os.environ.get("BANTZ_DATA_DIR", os.path.expanduser("~/.bantz/data")),
    "observability.db",
)


# ── Data Classes ──────────────────────────────────────────────────


@dataclass
class Run:
    """In-flight run being tracked.  Fields are filled during the run."""

    run_id: str
    user_input: str
    session_id: Optional[str] = None
    route: Optional[str] = None
    intent: Optional[str] = None
    final_output: Optional[str] = None
    model: Optional[str] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    status: str = "pending"
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    _tool_calls: List["ToolCall"] = field(default_factory=list, repr=False)
    _tracker: Optional["RunTracker"] = field(default=None, repr=False)
    _start: float = field(default_factory=time.monotonic, repr=False)

    def track_tool(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        confirmation: str = "auto",
    ) -> "_ToolCallContext":
        """Return an async context manager that tracks a single tool call."""
        return _ToolCallContext(self, tool_name, params, confirmation)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_input": self.user_input,
            "route": self.route,
            "intent": self.intent,
            "final_output": self.final_output,
            "model": self.model,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error": self.error,
            "session_id": self.session_id,
            "created_at": self.created_at,
        }


@dataclass
class ToolCall:
    """Recorded tool invocation (immutable after save)."""

    call_id: str
    run_id: str
    tool_name: str
    params: Optional[str] = None  # JSON
    result_hash: Optional[str] = None
    result_summary: Optional[str] = None
    latency_ms: Optional[int] = None
    status: str = "pending"
    error: Optional[str] = None
    confirmation: str = "auto"
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "run_id": self.run_id,
            "tool_name": self.tool_name,
            "params": self.params,
            "result_hash": self.result_hash,
            "result_summary": self.result_summary,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error": self.error,
            "confirmation": self.confirmation,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
        }


@dataclass
class Artifact:
    """Produced artifact (summary, transcript, report, etc.)."""

    artifact_id: str
    run_id: Optional[str] = None
    type: str = "summary"  # summary|transcript|report|draft|attachment
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    embedding: Optional[bytes] = None
    source_ref: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "source_ref": self.source_ref,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }


# ── Tool Call Context Manager ─────────────────────────────────────


class _ToolCallContext:
    """Async context manager wrapping a single tool invocation."""

    def __init__(
        self,
        run: Run,
        tool_name: str,
        params: Optional[Dict[str, Any]],
        confirmation: str,
    ) -> None:
        self._run = run
        self._tool_name = tool_name
        self._params = params
        self._confirmation = confirmation
        self._tc: Optional[ToolCall] = None
        self._start: float = 0.0

    async def __aenter__(self) -> "ToolCallHandle":
        self._start = time.monotonic()
        self._tc = ToolCall(
            call_id=str(uuid4()),
            run_id=self._run.run_id,
            tool_name=self._tool_name,
            params=json.dumps(self._params, default=str) if self._params else None,
            confirmation=self._confirmation,
        )
        return ToolCallHandle(self._tc)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        tc = self._tc
        assert tc is not None
        tc.latency_ms = int((time.monotonic() - self._start) * 1000)
        if exc_type is not None:
            tc.status = "error"
            tc.error = f"{exc_type.__name__}: {exc_val}"
        elif tc.status == "pending":
            tc.status = "success"
        self._run._tool_calls.append(tc)
        # Save immediately if tracker available
        tracker = self._run._tracker
        if tracker is not None:
            await tracker._save_tool_call(tc)
        return False  # Don't suppress exceptions


class ToolCallHandle:
    """User-facing handle yielded by track_tool() context manager."""

    __slots__ = ("_tc",)

    def __init__(self, tc: ToolCall) -> None:
        self._tc = tc

    @property
    def call_id(self) -> str:
        return self._tc.call_id

    def set_result(self, result: Any, summary: Optional[str] = None) -> None:
        """Record a successful result.  Computes hash, optional summary."""
        raw = json.dumps(result, default=str) if not isinstance(result, str) else result
        self._tc.result_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if summary:
            self._tc.result_summary = summary[:500]
        elif len(raw) <= 500:
            self._tc.result_summary = raw
        else:
            self._tc.result_summary = raw[:497] + "..."

    def set_error(self, error: str) -> None:
        """Manually mark the call as failed."""
        self._tc.status = "error"
        self._tc.error = error

    def set_skipped(self, reason: str = "") -> None:
        """Mark the call as skipped (e.g. user denied)."""
        self._tc.status = "skipped"
        self._tc.error = reason or None

    def set_confirmation(self, value: str) -> None:
        """Record approval status: auto|user_approved|user_denied."""
        self._tc.confirmation = value

    def increment_retry(self) -> None:
        self._tc.retry_count += 1


# ── RunTracker ────────────────────────────────────────────────────


class RunTracker:
    """SQLite-backed observability store.

    Thread-safe via ``check_same_thread=False``.
    WAL mode for concurrent reads.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    async def initialise(self) -> None:
        """Create / open the database and ensure schema."""
        path = Path(self._db_path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level="DEFERRED",
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("[RunTracker] DB ready at %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def db_path(self) -> str:
        return self._db_path

    # ── Run tracking ──

    @asynccontextmanager
    async def track_run(
        self,
        user_input: str,
        session_id: Optional[str] = None,
    ):
        """Context manager that yields a :class:`Run` and persists it on exit."""
        run = Run(
            run_id=str(uuid4()),
            user_input=user_input,
            session_id=session_id,
        )
        run._tracker = self
        # Insert with 'pending' status so tool_calls can FK-reference the run_id
        await self._save_run(run)
        try:
            yield run
            if run.status == "pending":
                run.status = "success"
        except Exception as exc:
            run.status = "error"
            run.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            run.latency_ms = int((time.monotonic() - run._start) * 1000)
            await self._save_run(run)

    # ── Artifact ──

    async def save_artifact(
        self,
        run_id: Optional[str],
        artifact_type: str,
        content: str,
        *,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        embedding: Optional[bytes] = None,
        source_ref: Optional[str] = None,
        mime_type: str = "text/plain",
    ) -> Artifact:
        """Create and persist an artifact."""
        art = Artifact(
            artifact_id=str(uuid4()),
            run_id=run_id,
            type=artifact_type,
            title=title,
            content=content,
            summary=summary,
            embedding=embedding,
            source_ref=source_ref,
            mime_type=mime_type,
            size_bytes=len(content.encode()) if content else 0,
        )
        conn = self._ensure_conn()
        conn.execute(
            """INSERT INTO artifacts
               (artifact_id, run_id, type, title, content, summary,
                embedding, source_ref, mime_type, size_bytes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                art.artifact_id, art.run_id, art.type, art.title,
                art.content, art.summary, art.embedding, art.source_ref,
                art.mime_type, art.size_bytes, art.created_at,
            ),
        )
        conn.commit()
        return art

    # ── Query: single run ──

    async def get_run(self, run_id: str) -> Optional[Run]:
        """Fetch a run by ID."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_run(row)

    async def get_tool_calls(self, run_id: str) -> List[ToolCall]:
        """Fetch all tool calls for a run, ordered by time."""
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [self._row_to_tool_call(r) for r in rows]

    async def get_artifacts(self, run_id: str) -> List[Artifact]:
        """Fetch all artifacts for a run."""
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    # ── Query: listing ──

    async def list_runs(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Run]:
        """List runs with optional filters."""
        conn = self._ensure_conn()
        where, params = self._build_where(
            session_id=session_id,
            status=status,
            table="runs",
        )
        sql = f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        return [self._row_to_run(r) for r in rows]

    async def list_tool_calls_by_name(
        self,
        tool_name: str,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[ToolCall]:
        """List tool calls filtered by tool name."""
        conn = self._ensure_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE tool_name = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
                (tool_name, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE tool_name = ? ORDER BY created_at DESC LIMIT ?",
                (tool_name, limit),
            ).fetchall()
        return [self._row_to_tool_call(r) for r in rows]

    # ── Metrics queries ──

    async def run_stats(
        self,
        since: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggregate run statistics."""
        conn = self._ensure_conn()
        where_parts: List[str] = []
        params: List[Any] = []
        if since:
            where_parts.append("created_at >= ?")
            params.append(since)
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        row = conn.execute(
            f"""SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                SUM(CASE WHEN status='timeout' THEN 1 ELSE 0 END) AS timeouts,
                SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) AS cancelled,
                AVG(latency_ms) AS avg_latency,
                MAX(latency_ms) AS max_latency,
                SUM(total_tokens) AS total_tokens
            FROM runs {where}""",
            params,
        ).fetchone()

        total = row[0] or 0
        return {
            "total": total,
            "success": row[1] or 0,
            "errors": row[2] or 0,
            "timeouts": row[3] or 0,
            "cancelled": row[4] or 0,
            "success_rate": round((row[1] or 0) / total * 100, 1) if total else 0.0,
            "avg_latency_ms": round(row[5] or 0, 1),
            "max_latency_ms": row[6] or 0,
            "total_tokens": row[7] or 0,
        }

    async def tool_stats(
        self,
        since: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Per-tool aggregated statistics, sorted by call count desc."""
        conn = self._ensure_conn()
        where = "WHERE created_at >= ?" if since else ""
        params: list = [since] if since else []

        rows = conn.execute(
            f"""SELECT
                tool_name,
                COUNT(*) AS calls,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                AVG(latency_ms) AS avg_latency,
                MAX(latency_ms) AS max_latency,
                AVG(retry_count) AS avg_retries
            FROM tool_calls {where}
            GROUP BY tool_name
            ORDER BY calls DESC""",
            params,
        ).fetchall()

        return [
            {
                "tool_name": r[0],
                "calls": r[1],
                "success": r[2] or 0,
                "errors": r[3] or 0,
                "error_rate": round((r[3] or 0) / r[1] * 100, 1) if r[1] else 0.0,
                "avg_latency_ms": round(r[4] or 0, 1),
                "max_latency_ms": r[5] or 0,
                "avg_retries": round(r[6] or 0, 2),
            }
            for r in rows
        ]

    async def slow_tools(
        self,
        threshold_ms: int = 2000,
        since: Optional[float] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find tools exceeding the latency threshold."""
        conn = self._ensure_conn()
        where_parts = ["latency_ms > ?"]
        params: List[Any] = [threshold_ms]
        if since:
            where_parts.append("created_at >= ?")
            params.append(since)
        where = "WHERE " + " AND ".join(where_parts)

        rows = conn.execute(
            f"""SELECT
                tool_name,
                COUNT(*) AS slow_count,
                AVG(latency_ms) AS avg_latency,
                MAX(latency_ms) AS max_latency
            FROM tool_calls {where}
            GROUP BY tool_name
            ORDER BY avg_latency DESC
            LIMIT ?""",
            (*params, limit),
        ).fetchall()

        return [
            {
                "tool_name": r[0],
                "slow_count": r[1],
                "avg_latency_ms": round(r[2] or 0, 1),
                "max_latency_ms": r[3] or 0,
            }
            for r in rows
        ]

    async def error_breakdown(
        self,
        tool_name: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List error details for failed tool calls."""
        conn = self._ensure_conn()
        where_parts = ["status = 'error'"]
        params: List[Any] = []
        if tool_name:
            where_parts.append("tool_name = ?")
            params.append(tool_name)
        if since:
            where_parts.append("created_at >= ?")
            params.append(since)
        where = "WHERE " + " AND ".join(where_parts)

        rows = conn.execute(
            f"""SELECT call_id, run_id, tool_name, params, error, latency_ms, created_at
            FROM tool_calls {where}
            ORDER BY created_at DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()

        return [
            {
                "call_id": r[0],
                "run_id": r[1],
                "tool_name": r[2],
                "params": r[3],
                "error": r[4],
                "latency_ms": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]

    async def artifact_stats(self, since: Optional[float] = None) -> Dict[str, int]:
        """Count artifacts grouped by type."""
        conn = self._ensure_conn()
        where = "WHERE created_at >= ?" if since else ""
        params: list = [since] if since else []
        rows = conn.execute(
            f"SELECT type, COUNT(*) FROM artifacts {where} GROUP BY type",
            params,
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # ── Internal save methods ─────────────────────────────────────

    async def _save_run(self, run: Run) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, user_input, route, intent, final_output, model,
                total_tokens, latency_ms, status, error, session_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run.run_id, run.user_input, run.route, run.intent,
                run.final_output, run.model, run.total_tokens,
                run.latency_ms, run.status, run.error,
                run.session_id, run.created_at,
            ),
        )
        conn.commit()

    async def _save_tool_call(self, tc: ToolCall) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO tool_calls
               (call_id, run_id, tool_name, params, result_hash,
                result_summary, latency_ms, status, error,
                confirmation, retry_count, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tc.call_id, tc.run_id, tc.tool_name, tc.params,
                tc.result_hash, tc.result_summary, tc.latency_ms,
                tc.status, tc.error, tc.confirmation, tc.retry_count,
                tc.created_at,
            ),
        )
        conn.commit()

    # ── Row mappers ───────────────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("RunTracker not initialised — call initialise() first")
        return self._conn

    @staticmethod
    def _row_to_run(row) -> Run:
        return Run(
            run_id=row[0],
            user_input=row[1],
            route=row[2],
            intent=row[3],
            final_output=row[4],
            model=row[5],
            total_tokens=row[6],
            latency_ms=row[7],
            status=row[8],
            error=row[9],
            session_id=row[10],
            created_at=row[11],
        )

    @staticmethod
    def _row_to_tool_call(row) -> ToolCall:
        return ToolCall(
            call_id=row[0],
            run_id=row[1],
            tool_name=row[2],
            params=row[3],
            result_hash=row[4],
            result_summary=row[5],
            latency_ms=row[6],
            status=row[7],
            error=row[8],
            confirmation=row[9],
            retry_count=row[10],
            created_at=row[11],
        )

    @staticmethod
    def _row_to_artifact(row) -> Artifact:
        return Artifact(
            artifact_id=row[0],
            run_id=row[1],
            type=row[2],
            title=row[3],
            content=row[4],
            summary=row[5],
            embedding=row[6],
            source_ref=row[7],
            mime_type=row[8],
            size_bytes=row[9],
            created_at=row[10],
        )

    @staticmethod
    def _build_where(**kwargs) -> tuple:
        table = kwargs.pop("table", "")
        parts: List[str] = []
        params: List[Any] = []
        for key, val in kwargs.items():
            if val is not None:
                parts.append(f"{key} = ?")
                params.append(val)
        where = ("WHERE " + " AND ".join(parts)) if parts else ""
        return where, params

    # ── Sync API (for orchestrator integration) ───────────────────

    def initialise_sync(self) -> None:
        """Synchronous version of :meth:`initialise`.

        Identical logic but callable from sync code (no event loop needed).
        """
        path = Path(self._db_path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level="DEFERRED",
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("[RunTracker] DB ready at %s (sync)", self._db_path)

    def start_run(
        self,
        user_input: str,
        session_id: Optional[str] = None,
    ) -> Run:
        """Create a pending run row and return the :class:`Run` to fill.

        The caller should populate ``run.route``, ``run.intent``, etc.
        during execution and call :meth:`end_run` when done.
        """
        run = Run(
            run_id=str(uuid4()),
            user_input=user_input,
            session_id=session_id,
        )
        run._tracker = self
        self._save_run_sync(run)
        return run

    def end_run(self, run: Run, *, status: Optional[str] = None) -> None:
        """Finalise a tracked run — compute latency, set status, persist."""
        run.latency_ms = int((time.monotonic() - run._start) * 1000)
        if status:
            run.status = status
        elif run.status == "pending":
            run.status = "success"
        self._save_run_sync(run)

    def record_tool_call(
        self,
        run_id: str,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        result: Any = None,
        result_summary: Optional[str] = None,
        error: Optional[str] = None,
        latency_ms: int = 0,
        confirmation: str = "auto",
        status: Optional[str] = None,
    ) -> ToolCall:
        """Record a completed tool call in one shot (sync).

        Returns the persisted :class:`ToolCall`.
        """
        raw = ""
        if result is not None:
            raw = json.dumps(result, default=str) if not isinstance(result, str) else result
        result_hash = hashlib.sha256(raw.encode()).hexdigest()[:16] if raw else None

        if not result_summary and raw:
            result_summary = raw[:500] if len(raw) <= 500 else raw[:497] + "..."

        tc = ToolCall(
            call_id=str(uuid4()),
            run_id=run_id,
            tool_name=tool_name,
            params=json.dumps(params, default=str) if params else None,
            result_hash=result_hash if not error else None,
            result_summary=result_summary,
            latency_ms=latency_ms,
            status=status or ("error" if error else "success"),
            error=error,
            confirmation=confirmation,
        )
        self._save_tool_call_sync(tc)
        return tc

    def _save_run_sync(self, run: Run) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, user_input, route, intent, final_output, model,
                total_tokens, latency_ms, status, error, session_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run.run_id, run.user_input, run.route, run.intent,
                run.final_output, run.model, run.total_tokens,
                run.latency_ms, run.status, run.error,
                run.session_id, run.created_at,
            ),
        )
        conn.commit()

    def _save_tool_call_sync(self, tc: ToolCall) -> None:
        conn = self._ensure_conn()
        conn.execute(
            """INSERT OR REPLACE INTO tool_calls
               (call_id, run_id, tool_name, params, result_hash,
                result_summary, latency_ms, status, error,
                confirmation, retry_count, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tc.call_id, tc.run_id, tc.tool_name, tc.params,
                tc.result_hash, tc.result_summary, tc.latency_ms,
                tc.status, tc.error, tc.confirmation, tc.retry_count,
                tc.created_at,
            ),
        )
        conn.commit()
