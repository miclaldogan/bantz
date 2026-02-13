"""Per-turn metrics collection and JSONL persistence (Issue #302).

Each voice/text turn produces a :class:`TurnMetrics` record that is:
1. Logged at DEBUG level for live observation.
2. Written to JSONL for offline analysis / CI gating.
3. Fed into the :class:`~bantz.core.latency_budget.LatencyTracker` for
   rolling p50/p95 dashboards.

The :class:`TurnMetricsWriter` handles thread-safe JSONL persistence
with configurable file path.

Usage::

    writer = TurnMetricsWriter("artifacts/logs/turn_metrics.jsonl")
    m = TurnMetrics(turn_id="t1", user_input="saat kaç", route="time", ...)
    writer.write(m)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["TurnMetrics", "TurnMetricsWriter"]

# Default output path
DEFAULT_TURN_METRICS_FILE = "artifacts/logs/turn_metrics.jsonl"


@dataclass
class TurnMetrics:
    """Metrics snapshot for a single voice/text turn.

    Follows the schema defined in Issue #302.
    All latency values are in **milliseconds**.
    """

    # Identity
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Input/Output
    user_input: str = ""
    route: str = ""
    intent: str = ""
    tool: Optional[str] = None
    finalizer_tier: str = ""  # "gemini" | "3b" | "default"
    success: bool = True

    # Per-phase latency (ms)
    asr_ms: Optional[float] = None
    router_ms: Optional[float] = None
    tool_ms: Optional[float] = None
    finalize_ms: Optional[float] = None
    tts_ms: Optional[float] = None
    total_ms: float = 0.0

    # Budget violations
    budget_violations: List[str] = field(default_factory=list)

    # Extra context
    error: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)

    def check_budgets(
        self,
        *,
        asr_budget: float = 500.0,
        router_budget: float = 500.0,
        tool_budget: float = 2000.0,
        finalize_budget: float = 2000.0,
        tts_budget: float = 500.0,
        total_budget: float = 5000.0,
    ) -> List[str]:
        """Check each phase against its budget and return violation strings.

        Each violation is formatted as ``"phase:actual>budget"``
        (e.g. ``"router:620>500"``).
        """
        violations: List[str] = []
        checks = [
            ("asr", self.asr_ms, asr_budget),
            ("router", self.router_ms, router_budget),
            ("tool", self.tool_ms, tool_budget),
            ("finalize", self.finalize_ms, finalize_budget),
            ("tts", self.tts_ms, tts_budget),
            ("total", self.total_ms, total_budget),
        ]
        for name, actual, budget in checks:
            if actual is not None and actual > budget:
                violations.append(f"{name}:{actual:.0f}>{budget:.0f}")

        self.budget_violations = violations
        return violations

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict suitable for JSON serialization."""
        d = asdict(self)
        # Remove None latencies for cleaner output
        for key in ("asr_ms", "router_ms", "tool_ms", "finalize_ms", "tts_ms"):
            if d[key] is None:
                del d[key]
        if d.get("error") is None:
            del d["error"]
        if d.get("tool") is None:
            del d["tool"]
        if not d.get("tags"):
            del d["tags"]
        return d

    def to_json(self) -> str:
        """JSON string for JSONL output."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def log_debug(self) -> None:
        """Emit a structured debug log line."""
        violations = self.budget_violations
        v_str = f" ⚠ violations={violations}" if violations else ""
        logger.debug(
            "TurnMetrics[%s] route=%s total=%.0fms router=%.0fms tool=%s finalize=%s%s",
            self.turn_id,
            self.route,
            self.total_ms,
            self.router_ms or 0,
            f"{self.tool_ms:.0f}ms" if self.tool_ms is not None else "-",
            f"{self.finalize_ms:.0f}ms" if self.finalize_ms is not None else "-",
            v_str,
        )


class TurnMetricsWriter:
    """Thread-safe JSONL writer for turn metrics.

    Parameters
    ----------
    path:
        JSONL output file path.  Created automatically if missing.
        Defaults to ``BANTZ_TURN_METRICS_FILE`` env var or
        ``artifacts/logs/turn_metrics.jsonl``.
    enabled:
        If ``False``, :meth:`write` is a no-op.  Controlled by
        ``BANTZ_TURN_METRICS`` env var (``1`` / ``true`` to enable).
    """

    def __init__(
        self,
        path: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self._path = path or os.getenv(
            "BANTZ_TURN_METRICS_FILE", DEFAULT_TURN_METRICS_FILE
        )
        if enabled is not None:
            self._enabled = enabled
        else:
            raw = os.getenv("BANTZ_TURN_METRICS", "1").strip().lower()
            self._enabled = raw in ("1", "true", "yes")
        self._lock = threading.Lock()
        self._count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def count(self) -> int:
        """Number of records written in this session."""
        return self._count

    def write(self, metrics: TurnMetrics) -> bool:
        """Write a single turn metric record to JSONL.

        Returns ``True`` if written successfully, ``False`` otherwise.
        """
        if not self._enabled:
            return False

        line = metrics.to_json() + "\n"
        path = Path(self._path)

        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
                self._count += 1
                return True
            except OSError as exc:
                logger.warning("Failed to write turn metrics: %s", exc)
                return False
