"""Quality degradation status tracking (Issue #658).

Tracks recent quality→fast fallbacks for /status visibility and telemetry.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


_quality_degradation_count = 0
_quality_degradation_last: Optional[Dict[str, Any]] = None


def record_quality_degradation(reason: str, **details: Any) -> Dict[str, Any]:
    """Record a quality degradation event and return the stored payload."""
    global _quality_degradation_count, _quality_degradation_last

    _quality_degradation_count += 1
    payload = {
        "reason": str(reason or "unknown"),
        "ts": int(time.time()),
    }
    payload.update(details)
    _quality_degradation_last = payload
    return payload


def get_quality_degradation_status() -> Dict[str, Any]:
    """Return degradation stats for /status output."""
    return {
        "count": _quality_degradation_count,
        "last": _quality_degradation_last,
    }
