"""Misroute recording integration for orchestrator_loop (Issue #1012).

Provides a lightweight hook that records potential misroutes after each turn.
Controlled by BANTZ_MISROUTE_COLLECT=1 environment variable.

Records are collected when:
- Route is 'unknown' or 'fallback' (router couldn't decide)
- Tool execution had failures (wrong tool selected)
- Confidence is below threshold (uncertain routing)
- Route changed during post-route correction (was misrouted initially)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Enable/disable via env var (off by default to avoid I/O overhead)
MISROUTE_COLLECT_ENABLED = os.getenv("BANTZ_MISROUTE_COLLECT", "").strip() in ("1", "true", "yes")

# Confidence threshold below which we record
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("BANTZ_MISROUTE_CONFIDENCE_THRESHOLD", "0.35"))

# Lazy singleton — created on first use
_dataset: Any = None


def _get_dataset() -> Any:
    """Lazy-init the MisrouteDataset singleton."""
    global _dataset
    if _dataset is None:
        from bantz.router.misroute_collector import MisrouteDataset
        _dataset = MisrouteDataset()
    return _dataset


def record_turn_misroute(
    *,
    user_input: str,
    route: str,
    intent: str,
    confidence: float,
    tool_plan: list,
    tool_results: list[dict[str, Any]],
    original_route: str | None = None,
    session_id: str = "",
    model_name: str = "",
) -> None:
    """Record a potential misroute if collection is enabled.

    Called after each orchestrator turn. Only writes a record if at least
    one misroute signal is detected:
    - Unknown/fallback route
    - Tool execution failure
    - Low confidence
    - Route corrected by post-route heuristics

    Args:
        user_input: The user's original message.
        route: Final resolved route.
        intent: Intent (calendar_intent or gmail_intent).
        confidence: Router confidence score.
        tool_plan: List of planned tool names.
        tool_results: List of tool result dicts.
        original_route: Route before post-route correction (if any).
        session_id: Optional session identifier.
        model_name: LLM model name used for routing.
    """
    if not MISROUTE_COLLECT_ENABLED:
        return

    reason = _classify_misroute(
        route=route,
        confidence=confidence,
        tool_results=tool_results,
        original_route=original_route,
    )

    if reason is None:
        return  # Not a misroute — skip recording

    try:
        from bantz.router.misroute_collector import MisrouteRecord

        record = MisrouteRecord(
            user_text=user_input,
            router_route=route,
            router_intent=intent,
            router_slots={},
            router_confidence=confidence,
            router_raw_output="",
            expected_route=original_route if original_route and original_route != route else None,
            reason=reason,
            notes=_build_notes(tool_plan, tool_results, original_route, route),
            session_id=session_id,
            model_name=model_name,
        )

        _get_dataset().append(record)

        logger.info(
            "[MISROUTE] Recorded %s misroute: route=%s confidence=%.2f reason=%s",
            "potential" if confidence > LOW_CONFIDENCE_THRESHOLD else "likely",
            route, confidence, reason,
        )

    except Exception as exc:
        logger.debug("[MISROUTE] Recording failed: %s", exc)


def _classify_misroute(
    *,
    route: str,
    confidence: float,
    tool_results: list[dict[str, Any]],
    original_route: str | None,
) -> str | None:
    """Classify the type of misroute, or None if no misroute detected."""

    # 1. Fallback/unknown route
    if route in ("unknown", "fallback", ""):
        return "fallback"

    # 2. Route was corrected by post-route heuristics
    if original_route and original_route != route:
        return "wrong_route"

    # 3. Low confidence
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"

    # 4. Tool execution failures
    failed_tools = [
        tr for tr in tool_results
        if isinstance(tr, dict) and tr.get("success") is False
        or isinstance(tr, dict) and tr.get("status") in ("fail", "error")
    ]
    if failed_tools:
        return "wrong_route"

    return None


def _build_notes(
    tool_plan: list,
    tool_results: list[dict[str, Any]],
    original_route: str | None,
    final_route: str,
) -> str:
    """Build human-readable notes for the misroute record."""
    parts: list[str] = []

    if original_route and original_route != final_route:
        parts.append(f"route corrected: {original_route} → {final_route}")

    if tool_plan:
        names = [
            (t.get("name") if isinstance(t, dict) else str(t))
            for t in tool_plan
        ]
        parts.append(f"tools: {', '.join(names)}")

    failed = [
        str(tr.get("tool", "?"))
        for tr in tool_results
        if isinstance(tr, dict) and (
            tr.get("success") is False
            or tr.get("status") in ("fail", "error")
        )
    ]
    if failed:
        parts.append(f"failed: {', '.join(failed)}")

    return "; ".join(parts) if parts else ""
