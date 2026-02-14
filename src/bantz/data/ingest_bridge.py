"""
Ingest Store integration bridge for the orchestrator loop.

Provides a lightweight helper that subscribes to tool result events
and automatically ingests them into the IngestStore.  This module
keeps the orchestrator loop clean by encapsulating all ingest logic.

Usage in OrchestratorLoop.__init__::

    from bantz.data.ingest_bridge import IngestBridge
    self._ingest_bridge = IngestBridge.create_default()

After tool execution::

    self._ingest_bridge.on_tool_result(tool_name, params, result, elapsed_ms)

Query cached results::

    cached = self._ingest_bridge.get_cached(tool_name, params)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from bantz.data.ingest_store import (
    IngestStore,
    DataClass,
    IngestRecord,
    classify_tool_result,
    fingerprint,
)

logger = logging.getLogger(__name__)


class IngestBridge:
    """Bridge between orchestrator tool results and the Ingest Store.

    Responsibility:
    - Classify and ingest tool results automatically
    - Provide cache-hit lookup before tool execution
    - Track ingest statistics per turn
    """

    def __init__(self, store: IngestStore) -> None:
        self._store = store
        self._turn_ingested: int = 0
        self._turn_cache_hits: int = 0

    @classmethod
    def create_default(cls, db_path: str = "~/.bantz/data/ingest.db") -> "IngestBridge":
        """Create with default settings — safe to call even if DB dir doesn't exist."""
        try:
            store = IngestStore(db_path=db_path)
            return cls(store)
        except Exception as e:
            logger.warning("[IngestBridge] Failed to init store: %s — using in-memory fallback", e)
            store = IngestStore(db_path=":memory:")
            return cls(store)

    # ── public API ────────────────────────────────────────────

    def on_tool_result(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        *,
        elapsed_ms: int = 0,
        success: bool = True,
        summary: Optional[str] = None,
    ) -> Optional[str]:
        """Ingest a successful tool result.  Returns record id or None on failure.

        Failed tool results (success=False) are deliberately NOT ingested —
        we don't want to cache error responses.
        """
        if not success:
            return None

        # Don't ingest trivially empty or very small results
        if result is None:
            return None
        if isinstance(result, (dict, list)) and not result:
            return None

        data_class = classify_tool_result(tool_name)

        # Build ingestable content
        content = self._build_content(tool_name, params, result)

        # Build a cache key based solely on tool+params (no result)
        # so we can look up cached results before executing a tool.
        cache_key = fingerprint(
            self._build_content(tool_name, params, placeholder=True),
            tool_name,
        )

        meta = {
            "tool_name": tool_name,
            "params": params,
            "elapsed_ms": elapsed_ms,
            "cache_key": cache_key,
        }

        try:
            record_id = self._store.ingest(
                content=content,
                source=tool_name,
                data_class=data_class,
                summary=summary,
                meta=meta,
            )
            self._turn_ingested += 1
            return record_id
        except Exception as e:
            logger.warning("[IngestBridge] Failed to ingest %s result: %s", tool_name, e)
            return None

    def get_cached(
        self,
        tool_name: str,
        params: Dict[str, Any],
        *,
        max_age: Optional[float] = None,
    ) -> Optional[IngestRecord]:
        """Look up a cached tool result by (tool_name, params) cache key.

        Parameters
        ----------
        tool_name : str
            The tool that produced the result.
        params : dict
            The params that were passed to the tool.
        max_age : float, optional
            Maximum age in seconds.  If the cached record is older it's
            treated as a miss.  *None* accepts any non-expired record.

        Returns
        -------
        IngestRecord or None
        """
        cache_key = fingerprint(
            self._build_content(tool_name, params, placeholder=True),
            tool_name,
        )

        try:
            # Search for the cache_key in the meta field
            records = self._store.search(cache_key, source=tool_name, limit=1)
        except Exception:
            return None

        if not records:
            return None

        record = records[0]

        if max_age is not None:
            import time
            age = time.time() - record.created_at
            if age > max_age:
                return None

        self._turn_cache_hits += 1
        return record

    def reset_turn_stats(self) -> Dict[str, int]:
        """Return and reset per-turn counters."""
        stats = {
            "ingested": self._turn_ingested,
            "cache_hits": self._turn_cache_hits,
        }
        self._turn_ingested = 0
        self._turn_cache_hits = 0
        return stats

    @property
    def store(self) -> IngestStore:
        """Direct access to the underlying store (for queries, stats)."""
        return self._store

    def close(self) -> None:
        self._store.close()

    # ── private helpers ───────────────────────────────────────

    @staticmethod
    def _build_content(
        tool_name: str,
        params: Dict[str, Any],
        result: Any = None,
        *,
        placeholder: bool = False,
    ) -> Dict[str, Any]:
        """Build canonical content dict for fingerprinting and storage.

        When *placeholder* is True, result is excluded — used for
        cache lookups where we only know the tool+params, not the result.
        """
        if placeholder:
            return {"tool": tool_name, "params": _stable_params(params)}
        return {
            "tool": tool_name,
            "params": _stable_params(params),
            "result": result,
        }


def _stable_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of params with unstable keys removed.

    Some params vary between calls but produce identical results
    (e.g. ``page_token``, ``_request_id``).  We strip those so the
    fingerprint is content-stable.
    """
    if not isinstance(params, dict):
        return params
    skip = {"page_token", "_request_id", "_trace_id", "timestamp"}
    return {k: v for k, v in sorted(params.items()) if k not in skip}
