"""Plan → Act → Verify loop — tool result validation (Issue #523).

Adds a verification phase between tool execution and finalization.
Validates tool results and optionally retries failed tools once.

Flow::

    process_turn()
      Phase 1: _llm_planning_phase()
      Phase 2: _execute_tools_phase()
      Phase 2.5: _verify_results_phase()  ← NEW
      Phase 3: _llm_finalization_phase()
      Phase 4: _update_state_phase()

Verify checks:
  - Empty result detection (tool returned nothing)
  - Error result detection (success=False)
  - 1x retry for failed tools (configurable)
  - Verified results passed to finalizer

Trace output::

    [verify] verified=true tools_ok=2 tools_retry=0 tools_fail=0
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "VerifyConfig",
    "VerifyResult",
    "VerifyTrace",
    "verify_tool_results",
]


# ── Config ────────────────────────────────────────────────────

@dataclass
class VerifyConfig:
    """Configuration for the verification phase.

    Attributes
    ----------
    max_retries:
        Maximum retry attempts per failed tool (default: 1).
    retry_empty:
        Whether to retry tools that return empty results.
    retry_errors:
        Whether to retry tools that return success=False.
    timeout_seconds:
        Per-tool retry timeout (uses same as original if None).
    retryable_tools:
        Whitelist of tool names safe to retry.  Only these tools
        will be retried; all others are left as-is.  Issue #939:
        replaces blacklisting destructive tools with an explicit
        whitelist of idempotent, non-destructive tools.
    valid_empty_tools:
        Tools for which an empty result (e.g. ``[]``) is a valid
        "no data found" response rather than a failure.  Issue #939.
    """

    max_retries: int = 1
    retry_empty: bool = True
    retry_errors: bool = True
    timeout_seconds: Optional[float] = None
    retryable_tools: frozenset[str] = frozenset({
        "calendar.list_events",
        "calendar.find_free_slots",
        "gmail.list_messages",
        "gmail.unread_count",
        "gmail.get_message",
        "gmail.smart_search",
        "gmail.list_drafts",
        "gmail.list_labels",
        "gmail.query_from_nl",
        "contacts.list",
        "contacts.resolve",
        "time.now",
        "system.status",
    })
    valid_empty_tools: frozenset[str] = frozenset({
        "calendar.list_events",
        "calendar.find_free_slots",
        "gmail.list_messages",
        "gmail.smart_search",
        "gmail.list_drafts",
        "gmail.list_labels",
        "contacts.list",
    })


# ── Single tool verification result ──────────────────────────

@dataclass
class ToolVerification:
    """Verification outcome for a single tool result."""

    tool_name: str = ""
    original_success: bool = True
    is_empty: bool = False
    is_error: bool = False
    retried: bool = False
    retry_success: bool = False
    final_success: bool = True
    error_message: str = ""


# ── Overall verification result ──────────────────────────────

@dataclass
class VerifyResult:
    """Aggregate verification result for all tools in a turn."""

    verified: bool = True
    tools_ok: int = 0
    tools_retry: int = 0
    tools_fail: int = 0
    tool_verifications: List[ToolVerification] = field(default_factory=list)
    verified_results: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0


# ── Trace record ─────────────────────────────────────────────

@dataclass
class VerifyTrace:
    """Trace record for the verify phase."""

    turn_number: int = 0
    result: Optional[VerifyResult] = None

    def to_trace_line(self) -> str:
        if self.result is None:
            return "[verify] skipped (no results)"
        r = self.result
        return (
            f"[verify] verified={r.verified} "
            f"tools_ok={r.tools_ok} tools_retry={r.tools_retry} "
            f"tools_fail={r.tools_fail} elapsed={r.elapsed_ms}ms"
        )


# ── Verification logic ───────────────────────────────────────

def _is_empty_result(result: Dict[str, Any]) -> bool:
    """Check whether a tool result is empty/meaningless."""
    raw = result.get("result") or result.get("raw_result")
    summary = result.get("result_summary", "")

    if raw is None and not summary:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    if isinstance(raw, (list, dict)) and len(raw) == 0:
        return True
    return False


def _is_safety_rejected(result: Dict[str, Any]) -> bool:
    """Check whether a tool result was rejected by the safety guard.

    Issue #939: Checks multiple key patterns so changes to the safety
    guard's rejection format don't silently bypass the check.
    """
    if result.get("safety_rejected"):
        return True
    if result.get("blocked"):
        return True
    error = str(result.get("error") or "")
    if "safety" in error.lower() or "blocked" in error.lower():
        return True
    return False


def _is_error_result(result: Dict[str, Any]) -> bool:
    """Check whether a tool result indicates an error."""
    if result.get("success") is False:
        return True
    if result.get("error"):
        return True
    return False


def verify_tool_results(
    tool_results: List[Dict[str, Any]],
    *,
    config: Optional[VerifyConfig] = None,
    retry_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
) -> VerifyResult:
    """Verify tool results and optionally retry failures.

    Parameters
    ----------
    tool_results:
        List of tool result dicts from _execute_tools_phase().
    config:
        Verification configuration. Defaults are used if None.
    retry_fn:
        Optional callback ``(tool_name, original_result) → new_result``.
        Called for retriable failures if ``config.max_retries > 0``.

    Returns
    -------
    VerifyResult with verified_results (ready for finalization).
    """
    cfg = config or VerifyConfig()
    start = time.time()

    ok = 0
    retried = 0
    failed = 0
    verifications: List[ToolVerification] = []
    verified: List[Dict[str, Any]] = []

    for result in tool_results:
        tool_name = str(result.get("tool", "unknown"))
        tv = ToolVerification(tool_name=tool_name)

        empty = _is_empty_result(result)
        error = _is_error_result(result)
        tv.is_empty = empty
        tv.is_error = error
        tv.original_success = not error

        # Issue #939: Empty is valid for query tools ("no events today" = valid)
        if empty and tool_name in cfg.valid_empty_tools:
            tv.final_success = True
            verified.append(result)
            ok += 1
            verifications.append(tv)
            continue

        # Issue #939: Safety-rejected results must never be retried
        if _is_safety_rejected(result):
            tv.final_success = False
            tv.error_message = "safety_rejected — not retriable"
            verified.append(result)
            failed += 1
            verifications.append(tv)
            continue

        # Issue #939: Only retry tools on the retryable whitelist
        needs_retry = (
            (empty and cfg.retry_empty) or (error and cfg.retry_errors)
        ) and cfg.max_retries > 0 and retry_fn is not None
        can_retry = tool_name in cfg.retryable_tools

        if needs_retry and can_retry:
            tv.retried = True
            retried += 1
            try:
                new_result = retry_fn(tool_name, result)
                new_error = _is_error_result(new_result)
                new_empty = _is_empty_result(new_result)
                if not new_error and not new_empty:
                    tv.retry_success = True
                    tv.final_success = True
                    # Mark the retried result
                    new_result["_retried"] = True
                    verified.append(new_result)
                    ok += 1
                else:
                    tv.retry_success = False
                    tv.final_success = False
                    tv.error_message = str(new_result.get("error", "retry failed"))
                    verified.append(result)  # keep original
                    failed += 1
            except Exception as e:
                tv.retry_success = False
                tv.final_success = False
                tv.error_message = str(e)
                verified.append(result)
                failed += 1
        elif empty or error:
            tv.final_success = False
            tv.error_message = str(result.get("error", "empty result"))
            verified.append(result)
            failed += 1
        else:
            tv.final_success = True
            verified.append(result)
            ok += 1

        verifications.append(tv)

    elapsed = int((time.time() - start) * 1000)
    all_ok = failed == 0

    vr = VerifyResult(
        verified=all_ok,
        tools_ok=ok,
        tools_retry=retried,
        tools_fail=failed,
        tool_verifications=verifications,
        verified_results=verified,
        elapsed_ms=elapsed,
    )

    if all_ok:
        logger.debug(
            "[verify] verified=%s tools_ok=%d tools_retry=%d tools_fail=%d",
            all_ok, ok, retried, failed,
        )
    else:
        logger.warning(
            "[verify] verified=%s tools_ok=%d tools_retry=%d tools_fail=%d",
            all_ok, ok, retried, failed,
        )

    return vr
