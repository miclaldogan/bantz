"""Session context caching with TTL (Issue #417).

Problem: ``build_session_context()`` is called every turn in both planning and
finalization phases, re-computing timezone, datetime, and locale each time.

Solution:
  - Build session context once per turn at the top of ``run_turn()``
  - Cache with a TTL (default 60s) — stale context within the same minute is fine
  - Store on ``OrchestratorState.session_context``
  - All phases read from state instead of rebuilding

Usage:
    >>> cache = SessionContextCache(ttl_seconds=60)
    >>> ctx = cache.get_or_build()
    >>> # 30 seconds later...
    >>> ctx2 = cache.get_or_build()  # returns cached
    >>> assert ctx2 is ctx
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "SessionContextCache",
    "build_session_context_cached",
]


@dataclass
class SessionContextCache:
    """TTL-based cache for session context.

    Attributes:
        ttl_seconds: How long a cached context remains valid (default 60).
        _cached: The cached context dict or None.
        _cached_at: Monotonic timestamp when cache was populated.
    """

    ttl_seconds: float = 60.0
    _cached: Optional[dict[str, Any]] = field(default=None, repr=False)
    _cached_at: float = field(default=0.0, repr=False)

    def get_or_build(
        self,
        *,
        location: Optional[str] = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return cached session context, or build fresh if stale/missing.

        Args:
            location: Optional location override (e.g. "Istanbul").
            force_refresh: If True, ignore cache and rebuild.

        Returns:
            Session context dict with keys like current_datetime, timezone, etc.
        """
        now = time.monotonic()

        if (
            not force_refresh
            and self._cached is not None
            and (now - self._cached_at) < self.ttl_seconds
        ):
            logger.debug("[SESSION_CTX] Cache hit (age=%.1fs)", now - self._cached_at)
            return self._cached

        # Build fresh context
        ctx = _build_context(location=location)
        self._cached = ctx
        self._cached_at = now
        logger.debug("[SESSION_CTX] Cache miss — built fresh context")
        return ctx

    def invalidate(self) -> None:
        """Force cache invalidation."""
        self._cached = None
        self._cached_at = 0.0

    @property
    def is_valid(self) -> bool:
        """Check if cache is currently valid."""
        if self._cached is None:
            return False
        return (time.monotonic() - self._cached_at) < self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        """Age of cached context in seconds, or -1 if no cache."""
        if self._cached is None:
            return -1.0
        return time.monotonic() - self._cached_at


def _build_context(*, location: Optional[str] = None) -> dict[str, Any]:
    """Build session context dict (timezone, datetime, location).

    This is the cached version of ``prompt_engineering.build_session_context``.
    Kept as a standalone function so tests can mock it easily.
    """
    now = datetime.now().astimezone()
    ctx: dict[str, Any] = {
        "current_datetime": now.isoformat(timespec="seconds"),
    }

    loc = (
        location
        or os.getenv("BANTZ_LOCATION")
        or os.getenv("BANTZ_DEFAULT_LOCATION")
        or ""
    ).strip()
    if loc:
        ctx["location"] = loc

    tz = now.tzinfo
    if tz is not None:
        ctx["timezone"] = str(tz)

    session_id = str(os.getenv("BANTZ_SESSION_ID", "")).strip()
    if session_id:
        ctx["session_id"] = session_id

    return ctx


def build_session_context_cached(
    cache: Optional[SessionContextCache] = None,
    *,
    location: Optional[str] = None,
) -> dict[str, Any]:
    """Convenience: build or get cached session context.

    If no cache is provided, builds fresh (equivalent to original behavior).
    """
    if cache is not None:
        return cache.get_or_build(location=location)
    return _build_context(location=location)
