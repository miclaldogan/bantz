"""Self-Reflection — Tool Result Verification (Issue #1277).

After tool execution and mechanical retry (verify_results), this module
performs *semantic* evaluation: "Does this result actually satisfy the
user's request?"

Reflection is triggered only when heuristics detect a likely problem:
  1. Tool returned an error (success=False)
  2. Tool result is empty/meaningless AND tool is not in valid_empty_tools
  3. Planner confidence < threshold (default 0.7)

When triggered, the planner LLM receives a short reflection prompt and
returns a structured verdict:
  {satisfied, reason, corrective_action}

If not satisfied, the result is annotated and (if ReAct is active) a
re-plan iteration is triggered.  Otherwise, the finalizer receives the
reflection reason so it can produce a more informative user response.

Feature gate: ``BANTZ_REFLECTION_ENABLED=1`` (default: enabled)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Environment / feature gate ───────────────────────────────

_REFLECTION_ENABLED = os.getenv("BANTZ_REFLECTION_ENABLED", "1").strip() not in ("0", "false", "no", "")

# ── Configuration ────────────────────────────────────────────


@dataclass(frozen=True)
class ReflectionConfig:
    """Tuneable parameters for the reflection pass."""

    enabled: bool = _REFLECTION_ENABLED
    confidence_threshold: float = 0.7
    # Issue #1322: Aligned with build_reflection_prompt max_chars=800.
    # Turkish text ≈ 3-4 chars/token → 800 chars ≈ 200-270 tokens.
    # 512 tokens leaves headroom for the template chrome.
    max_prompt_tokens: int = 512
    max_response_tokens: int = 300
    temperature: float = 0.0

    # Tools for which an empty result is valid (no data ≠ error)
    valid_empty_tools: frozenset[str] = frozenset({
        "calendar.list_events",
        "calendar.find_free_slots",
        "gmail.list_messages",
        "gmail.smart_search",
        "gmail.list_drafts",
        "gmail.list_labels",
        "contacts.list",
    })


# ── Result dataclass ─────────────────────────────────────────


@dataclass
class ReflectionResult:
    """Outcome of the reflection pass."""

    triggered: bool = False         # was reflection actually run?
    satisfied: bool = True          # does the result satisfy the user?
    reason: str = ""                # human-readable explanation
    corrective_action: str = ""     # hint for re-plan or finalizer
    trigger_cause: str = ""         # why reflection was triggered
    elapsed_ms: int = 0             # wall-clock time for the LLM call

    def to_trace_dict(self) -> dict[str, Any]:
        """Compact trace record for telemetry."""
        d: dict[str, Any] = {"triggered": self.triggered}
        if self.triggered:
            d["satisfied"] = self.satisfied
            d["reason"] = self.reason[:200]
            if self.corrective_action:
                d["corrective_action"] = self.corrective_action[:200]
            d["trigger_cause"] = self.trigger_cause
            d["elapsed_ms"] = self.elapsed_ms
        return d


# ── Trigger heuristic ────────────────────────────────────────

def _is_empty_result(result: dict[str, Any]) -> bool:
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


def _is_error_result(result: dict[str, Any]) -> bool:
    """Check whether a tool result indicates an error."""
    if result.get("success") is False:
        return True
    if result.get("error"):
        return True
    return False


def should_reflect(
    tool_results: list[dict[str, Any]],
    confidence: float,
    config: Optional[ReflectionConfig] = None,
) -> tuple[bool, str]:
    """Decide whether a reflection pass is needed.

    Returns ``(should_trigger, cause_description)``.
    """
    cfg = config or ReflectionConfig()
    if not cfg.enabled:
        return False, ""

    if not tool_results:
        return False, ""

    # Condition 1: any tool returned an error
    error_tools = [
        r.get("tool", "?")
        for r in tool_results
        if _is_error_result(r)
    ]
    if error_tools:
        return True, f"tool_error:{','.join(error_tools)}"

    # Condition 2: any tool returned empty AND is not in valid_empty_tools
    for r in tool_results:
        tool_name = r.get("tool", "")
        if _is_empty_result(r) and tool_name not in cfg.valid_empty_tools:
            return True, f"empty_result:{tool_name}"

    # Condition 3: low planner confidence
    if confidence < cfg.confidence_threshold:
        return True, f"low_confidence:{confidence:.2f}"

    return False, ""


# ── Prompt construction ──────────────────────────────────────

_REFLECTION_SYSTEM = (
    "Sen bir doğrulama asistanısın. Kullanıcının isteğini ve araç sonucunu "
    "karşılaştır. Sonuç isteği karşılıyor mu? Kısa ve net JSON yanıt ver."
)

_REFLECTION_TEMPLATE = """\
KULLANICI İSTEĞİ: {user_input}
ÇALIŞTIRILAN ARAÇ: {tool_name}
ARAÇ SONUCU: {tool_summary}
HATA: {error_info}

Bu sonuç kullanıcının isteğini karşılıyor mu?
Yanıt (sadece JSON):
{{"satisfied": true/false, "reason": "...", "corrective_action": "..." veya null}}"""


def build_reflection_prompt(
    user_input: str,
    tool_results: list[dict[str, Any]],
    max_chars: int = 600,
) -> str:
    """Build a compact reflection prompt for the LLM.

    Summarises the most relevant tool result to stay within token budget.
    """
    # Pick the most "problematic" result — errors first, then empties
    target = tool_results[-1]  # default: last result
    for r in tool_results:
        if _is_error_result(r):
            target = r
            break
        if _is_empty_result(r):
            target = r

    tool_name = target.get("tool", "unknown")
    summary = target.get("result_summary", "")
    if not summary:
        try:
            summary = json.dumps(
                target.get("raw_result") or target.get("result", ""),
                ensure_ascii=False, default=str,
            )
        except Exception:
            summary = str(target.get("result", ""))

    # Truncate summary to keep prompt small
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "…"

    error_info = str(target.get("error", "")) or "yok"

    prompt = f"{_REFLECTION_SYSTEM}\n\n{_REFLECTION_TEMPLATE.format(user_input=user_input, tool_name=tool_name, tool_summary=summary, error_info=error_info)}"
    return prompt


# ── Response parsing ─────────────────────────────────────────

def parse_reflection_response(raw: str) -> ReflectionResult:
    """Parse the LLM's reflection response into a ReflectionResult.

    Tolerant parser: extracts JSON from markdown fences, handles
    partial/malformed output gracefully.
    """
    text = raw.strip()

    # Issue #1322: Strip markdown code fences (opening + closing together)
    import re as _re
    text = _re.sub(r"```\w*\n?(.*?)```", r"\1", text, flags=_re.DOTALL).strip()

    # Try JSON parse
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Issue #1322: Use balanced-brace parser for nested JSON
        try:
            from bantz.brain.json_protocol import extract_first_json_object
            data = extract_first_json_object(text)
        except Exception:
            data = None

    if not isinstance(data, dict):
        # Could not parse — assume satisfied (don't block on parse failure)
        logger.debug("[Reflection] Could not parse LLM response: %s", text[:200])
        return ReflectionResult(
            triggered=True,
            satisfied=True,
            reason="reflection_parse_failed",
        )

    satisfied = data.get("satisfied", True)
    if isinstance(satisfied, str):
        satisfied = satisfied.lower() in ("true", "1", "yes", "evet")

    return ReflectionResult(
        triggered=True,
        satisfied=bool(satisfied),
        reason=str(data.get("reason", ""))[:300],
        corrective_action=str(data.get("corrective_action") or "")[:300],
    )


# ── Main reflection entry point ──────────────────────────────

def reflect(
    user_input: str,
    tool_results: list[dict[str, Any]],
    confidence: float,
    llm: Any,
    config: Optional[ReflectionConfig] = None,
) -> ReflectionResult:
    """Run the full reflection pipeline: trigger check → prompt → LLM → parse.

    Parameters
    ----------
    user_input : str
        The user's original request.
    tool_results : list
        Tool execution results from the execute phase.
    confidence : float
        Planner confidence score (0.0–1.0).
    llm : Any
        LLM client with ``complete_text(prompt, temperature, max_tokens)`` method.
    config : ReflectionConfig, optional
        Override default configuration.

    Returns
    -------
    ReflectionResult
        Reflection outcome. If ``triggered=False``, the pass was skipped.
    """
    cfg = config or ReflectionConfig()

    trigger, cause = should_reflect(tool_results, confidence, cfg)
    if not trigger:
        return ReflectionResult(triggered=False)

    logger.info(
        "[Reflection] Triggered: cause=%s, confidence=%.2f, tools=%d",
        cause, confidence, len(tool_results),
    )

    prompt = build_reflection_prompt(user_input, tool_results)

    t0 = time.monotonic()
    try:
        raw_response = llm.complete_text(
            prompt=prompt,
            temperature=cfg.temperature,
            max_tokens=cfg.max_response_tokens,
        )
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning("[Reflection] LLM call failed: %s", exc)
        return ReflectionResult(
            triggered=True,
            satisfied=True,  # don't block on LLM failure
            reason=f"reflection_llm_error: {type(exc).__name__}",
            trigger_cause=cause,
            elapsed_ms=elapsed,
        )

    elapsed = int((time.monotonic() - t0) * 1000)
    result = parse_reflection_response(raw_response)
    result.trigger_cause = cause
    result.elapsed_ms = elapsed

    logger.info(
        "[Reflection] Result: satisfied=%s reason=%s elapsed=%dms",
        result.satisfied, result.reason[:80], elapsed,
    )
    return result
