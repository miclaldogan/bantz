"""Static plan verification for LLM router output (Issue #907).

Catches logical errors that JSON-repair cannot detect:
  - Unknown tool names
  - Missing required slots
  - Route↔tool prefix mismatch
  - Tool plan present when input has no tool indicators
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Route → allowed tool prefixes ────────────────────────────────────
_ROUTE_TOOL_PREFIXES: dict[str, tuple[str, ...]] = {
    "calendar": ("calendar.", "time.", "contacts."),
    "gmail": ("gmail.", "contacts.", "time."),
    "system": ("system.", "time."),
    "smalltalk": ("time.",),
    "unknown": ("time.",),
}

# ── Required slots per intent ────────────────────────────────────────
_REQUIRED_SLOTS: dict[str, list[str]] = {
    "create_event": ["title"],
    "update_event": ["title"],
    "delete_event": ["title"],
}

_GMAIL_REQUIRED_FIELDS: dict[str, list[str]] = {
    "send": ["to"],
    "create_draft": ["to"],
    "generate_reply": [],
}

# ── Simple keyword heuristics for tool indicators ────────────────────
_TOOL_INDICATOR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(oluştur|ekle|yarat|create|add)\b", re.IGNORECASE),
    re.compile(r"\b(sil|kaldır|delete|remove|cancel)\b", re.IGNORECASE),
    re.compile(r"\b(güncelle|değiştir|update|change|modify|move)\b", re.IGNORECASE),
    re.compile(r"\b(listele|göster|bak|list|show)\b", re.IGNORECASE),
    re.compile(r"\b(gönder|yolla|send|mail|e-?posta)\b", re.IGNORECASE),
    re.compile(r"\b(oku|read|aç|open)\b", re.IGNORECASE),
    re.compile(r"\b(takvim|calendar|toplantı|meeting|randevu)\b", re.IGNORECASE),
    re.compile(r"\b(saat kaç|what time|tarih|date)\b", re.IGNORECASE),
]


def _has_tool_indicators(user_input: str) -> bool:
    """Return True if user input contains keywords hinting at a tool action."""
    return any(p.search(user_input) for p in _TOOL_INDICATOR_PATTERNS)


def verify_plan(
    plan: dict[str, Any],
    user_input: str,
    valid_tools: frozenset[str],
) -> tuple[bool, list[str]]:
    """Statically validate an LLM-produced plan.

    Args:
        plan: Parsed orchestrator output dict (route, tool_plan, slots, etc.).
        user_input: The raw user utterance.
        valid_tools: Set of registered tool names (e.g. ``LLMRouter._VALID_TOOLS``).

    Returns:
        ``(is_valid, errors)`` — *is_valid* is ``True`` when no errors found.
    """
    errors: list[str] = []
    tool_plan: list[Any] = plan.get("tool_plan") or []
    route: str = plan.get("route", "unknown")

    # ── 1. Tool name check ───────────────────────────────────────────
    for item in tool_plan:
        tool_name = item if isinstance(item, str) else (item.get("tool") if isinstance(item, dict) else str(item))
        if tool_name and tool_name not in valid_tools:
            errors.append(f"unknown_tool:{tool_name}")

    # ── 2. Route ↔ tool prefix coherence ─────────────────────────────
    allowed_prefixes = _ROUTE_TOOL_PREFIXES.get(route, ())
    if allowed_prefixes:
        for item in tool_plan:
            tool_name = item if isinstance(item, str) else (item.get("tool") if isinstance(item, dict) else str(item))
            if tool_name and not any(tool_name.startswith(pfx) for pfx in allowed_prefixes):
                errors.append(f"route_tool_mismatch:{route}→{tool_name}")

    # ── 3. Required slots (calendar) ─────────────────────────────────
    if route == "calendar":
        intent = plan.get("calendar_intent", "none")
        required = _REQUIRED_SLOTS.get(intent, [])
        slots = plan.get("slots") or {}
        for slot in required:
            if not slots.get(slot):
                errors.append(f"missing_slot:{slot}")

    # ── 4. Required gmail fields ─────────────────────────────────────
    if route == "gmail":
        gmail_intent = plan.get("gmail_intent", "none")
        required = _GMAIL_REQUIRED_FIELDS.get(gmail_intent, [])
        gmail = plan.get("gmail") or {}
        for field in required:
            if not gmail.get(field):
                errors.append(f"missing_gmail_field:{field}")

    # ── 5. Tool plan without tool indicators in input ────────────────
    if tool_plan and not _has_tool_indicators(user_input):
        # Soft warning — don't block, just flag
        errors.append("tool_plan_no_indicators")

    if errors:
        logger.warning(
            "[PLAN_VERIFIER] route=%s errors=%s input=%.60s",
            route, errors, user_input,
        )
    else:
        logger.debug("[PLAN_VERIFIER] plan OK route=%s tools=%d", route, len(tool_plan))

    return (not errors), errors
