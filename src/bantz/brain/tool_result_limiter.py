"""Tool result size limiting and truncation (Issue #1221).

Prevents oversized tool results from overflowing the context window
or causing OOM in the finalization pipeline.

Strategy:
- Soft limit (default 8 KB): log a warning
- Hard limit (default 32 KB): truncate with a sentinel message
- Per-result and aggregate limits
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "truncate_tool_result",
    "enforce_result_size_limits",
    "TOOL_RESULT_SOFT_LIMIT",
    "TOOL_RESULT_HARD_LIMIT",
]

# Size limits in characters (not bytes)
TOOL_RESULT_SOFT_LIMIT = 8_000   # ~8 KB — warn
TOOL_RESULT_HARD_LIMIT = 32_000  # ~32 KB — truncate


def _estimate_size(obj: Any) -> int:
    """Estimate the string size of a JSON-serializable object."""
    if isinstance(obj, str):
        return len(obj)
    try:
        return len(json.dumps(obj, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(obj))


def truncate_tool_result(
    result: Any,
    *,
    hard_limit: int = TOOL_RESULT_HARD_LIMIT,
    tool_name: str = "",
    trace_id: str = "",
) -> Any:
    """Truncate a single tool result if it exceeds *hard_limit*.

    Returns the (possibly truncated) result.  If truncation occurs,
    the result is replaced with a dict containing a summary and a
    truncation notice.
    """
    size = _estimate_size(result)
    if size <= hard_limit:
        return result

    logger.warning(
        "[Issue #1221] Tool result truncated: tool=%s size=%d limit=%d trace_id=%s",
        tool_name, size, hard_limit, trace_id,
    )

    # Try to preserve structure for dicts/lists
    if isinstance(result, dict):
        # Keep keys but truncate large values
        truncated: Dict[str, Any] = {}
        remaining = hard_limit - 200  # reserve for wrapper
        for key, val in result.items():
            val_size = _estimate_size(val)
            if remaining <= 0:
                truncated[key] = "…(truncated)"
                break
            if val_size > remaining:
                if isinstance(val, str):
                    truncated[key] = val[:remaining] + "…"
                elif isinstance(val, list):
                    truncated[key] = val[: max(1, int(len(val) * remaining / val_size))]
                else:
                    truncated[key] = "…(truncated)"
                remaining = 0
            else:
                truncated[key] = val
                remaining -= val_size
        truncated["_truncated"] = True
        truncated["_original_size"] = size
        return truncated

    if isinstance(result, str):
        return result[:hard_limit] + f"\n…(truncated, original {size} chars)"

    if isinstance(result, list):
        # Keep first N items that fit
        kept: List[Any] = []
        remaining = hard_limit - 200
        for item in result:
            item_size = _estimate_size(item)
            if remaining <= 0:
                break
            kept.append(item)
            remaining -= item_size
        return kept

    # Fallback: stringify and truncate
    s = str(result)
    return s[:hard_limit] + f"\n…(truncated, original {size} chars)"


def enforce_result_size_limits(
    tool_results: List[Dict[str, Any]],
    *,
    soft_limit: int = TOOL_RESULT_SOFT_LIMIT,
    hard_limit: int = TOOL_RESULT_HARD_LIMIT,
    trace_id: str = "",
) -> List[Dict[str, Any]]:
    """Enforce size limits on a list of tool results.

    Modifies *tool_results* in place and returns it.

    For results exceeding *soft_limit*, a warning is logged.
    For results exceeding *hard_limit*, the result is truncated.
    """
    for r in tool_results:
        tool_name = r.get("tool") or ""
        for result_key in ("result", "raw_result", "result_summary"):
            if result_key not in r:
                continue
            val = r[result_key]
            size = _estimate_size(val)
            if size > soft_limit:
                logger.warning(
                    "[Issue #1221] Large tool result: tool=%s key=%s size=%d trace_id=%s",
                    tool_name, result_key, size, trace_id,
                )
            if size > hard_limit:
                r[result_key] = truncate_tool_result(
                    val, hard_limit=hard_limit, tool_name=tool_name,
                    trace_id=trace_id,
                )
    return tool_results
