"""Static plan verification for LLM router output (Issue #907, #1002).

Catches logical errors that JSON-repair cannot detect:
  - Unknown tool names
  - Missing required slots
  - Route↔tool prefix mismatch
  - Tool plan present when input has no tool indicators
  - (Issue #1002) Semantic checks:
    - Smalltalk route with non-empty tool plan
    - Calendar write intent missing time/date slots
    - Gmail send with empty recipient
    - Route↔intent coherence (e.g. gmail route + calendar intent)
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
    # Turkish agglutinative forms: bak→bakalım/bakalom, göster→gösterir
    re.compile(r"\b(listele|göster\w*|bak\w*|list|show)\b", re.IGNORECASE),
    re.compile(r"\b(gönder|yolla|send|e-?posta)\b", re.IGNORECASE),
    re.compile(r"\b(oku|read|aç|open)\b", re.IGNORECASE),
    re.compile(r"\b(takvim|calendar|toplantı\w*|meeting|randevu)\b", re.IGNORECASE),
    # Typo tolerance: "saat kaö" for "saat kaç"
    re.compile(r"\b(saat\s*ka[çö]\w*|what time|tarih|date)\b", re.IGNORECASE),
    # Turkish suffixed forms: planımız/planımı/planım, etkinlik/etkinlikleri
    re.compile(r"\b(kontrol\s*et|plan\w*|etkinlik\w*|ne\s*var)\b", re.IGNORECASE),
    # Temporal / schedule query indicators
    # Turkish suffixed: bugün→bugünkü, yarın→yarınki, dün→dünkü
    re.compile(r"\b(bugün\w*|yarın\w*|dün\w*|bu\s*hafta|bu\s*ay|geçen\s*hafta|gelecek\s*hafta)\b", re.IGNORECASE),
    re.compile(r"\b(neler|ne\s*yapacağız|ne\s*yapıyoruz|program\w*|ajanda)\b", re.IGNORECASE),
    re.compile(r"\b(incele|incel[ea]\w*|gözden\s*geçir)\b", re.IGNORECASE),
    re.compile(r"\b(mailleri?|son\s*mail|gelen\s*kutusu|inbox)\b", re.IGNORECASE),
    re.compile(r"\b(ne\s*yazıyor|ne\s*diyor|ne\s*gelmiş|var\s*mı)\b", re.IGNORECASE),
    re.compile(r"\b(ara|bul|search|find|kontrol)\b", re.IGNORECASE),
    re.compile(r"\b(özetle|özetler?\s*m[iı]s[iı]n|özetl[ea]|summarize|summary)\b", re.IGNORECASE),
    re.compile(r"\b(yaz|yazar?\s*m[iı]s[iı]n|yazd[ıi]r|write|compose|draft)\b", re.IGNORECASE),
    re.compile(r"\b(cevapla|yan[ıi]tla|reply|respond)\b", re.IGNORECASE),
    re.compile(r"\b(hat[ıi]rlat|remind|alarm|bildir)\b", re.IGNORECASE),
    # Common Turkish mail/message words (with suffixes)
    re.compile(r"\bmail[a-zıüöğçş]*\b", re.IGNORECASE),
    # Turkish suffixed: posta→postalar/postalarım, mesaj→mesajları
    re.compile(r"\b(posta\w*|mesaj\w*|ileti\w*)\b", re.IGNORECASE),
    re.compile(r"\b(görüntüle|görüntüleyebil|söyle|söyler?\s*m[iı]s[iı]n)\b", re.IGNORECASE),
    re.compile(r"\b(okunmuş|okunmam[ıi]ş|okunan|okunmayan|unread)\b", re.IGNORECASE),
    re.compile(r"\b(at|atma[nk]?[ıi]?|diyelim|de)\b", re.IGNORECASE),
    re.compile(r"\b(konu|adres[a-zıüöğçş]*)\b", re.IGNORECASE),
    re.compile(r"\b(kontro[lr]|kontorl)\b", re.IGNORECASE),  # common typo tolerance
    # Action verbs missing from original list
    re.compile(r"\b(anlat\w*|anlatır?\s*m[iı]s[iı]n)\b", re.IGNORECASE),
    # Adjectives that imply tool context
    re.compile(r"\b(önemli|acil|yıldızlı|okunmamış)\b", re.IGNORECASE),
    # Cancel/delete with suffixes: iptal→iptal et, iptali
    re.compile(r"\b(iptal\w*|vazgeç\w*)\b", re.IGNORECASE),
    # Follow-up / continuation verbs
    re.compile(r"\b(devam\s*et|detay\w*|ayrıntı\w*)\b", re.IGNORECASE),
    # Number + Turkish suffix for calendar event refs: "9'daki", "3teki"
    re.compile(r"\b\d{1,2}\s*[''']?\s*(?:da|de|ta|te|daki|deki|taki|teki)\w*\b", re.IGNORECASE),
    # Declarative calendar intent: "olacak" (will be/happen)
    re.compile(r"\b(olacak|olacağım|olacağız|var\w*)\b", re.IGNORECASE),
]

# ── Issue #1002: Calendar write intents that should have date/time ───
_CALENDAR_WRITE_INTENTS = {"create", "create_event", "modify", "update", "update_event"}

# ── Issue #1002: Intents that are incoherent with their route ────────
_ROUTE_INTENT_MISMATCH: dict[str, set[str]] = {
    "gmail": {"create", "create_event", "modify", "update_event", "query", "cancel", "delete_event"},
    "calendar": {"send", "list", "search", "read"},
    "smalltalk": {"create", "create_event", "send", "delete_event", "modify"},
}


def _has_tool_indicators(user_input: str) -> bool:
    """Return True if user input contains keywords hinting at a tool action."""
    return any(p.search(user_input) for p in _TOOL_INDICATOR_PATTERNS)


def infer_route_from_tools(tool_plan: list[Any]) -> str | None:
    """Infer the correct route from tool_plan prefixes.

    Returns a route string ("gmail", "calendar", "system") if all tools
    in the plan share the same domain prefix, or ``None`` if the plan is
    empty or ambiguous.
    """
    if not tool_plan:
        return None
    domains: set[str] = set()
    for item in tool_plan:
        name = item if isinstance(item, str) else (
            item.get("tool") if isinstance(item, dict) else str(item)
        )
        if not name:
            continue
        prefix = name.split(".", 1)[0]
        if prefix == "time":
            continue  # time.* is allowed in any route
        domains.add(prefix)
    if len(domains) == 1:
        return domains.pop()
    return None


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

    # ── 6. Semantic: smalltalk with tools (Issue #1002) ──────────────
    if route == "smalltalk" and tool_plan:
        # Smalltalk with tools is almost always a routing error
        # (time. is the only allowed prefix for smalltalk)
        non_time_tools = [
            t for t in tool_plan
            if not (isinstance(t, str) and t.startswith("time."))
        ]
        if non_time_tools:
            errors.append("smalltalk_with_tools")

    # ── 7. Semantic: calendar write without date/time (Issue #1002) ──
    calendar_intent = plan.get("calendar_intent", "none")
    if route == "calendar" and calendar_intent in _CALENDAR_WRITE_INTENTS:
        slots = plan.get("slots") or {}
        has_temporal = bool(slots.get("date") or slots.get("time") or slots.get("window_hint"))
        if not has_temporal:
            errors.append("calendar_write_no_temporal")

    # ── 8. Semantic: route↔intent coherence (Issue #1002) ────────────
    bad_intents = _ROUTE_INTENT_MISMATCH.get(route, set())
    if calendar_intent in bad_intents:
        errors.append(f"route_intent_mismatch:{route}+calendar_intent={calendar_intent}")
    gmail_intent = plan.get("gmail_intent", "none")
    if gmail_intent != "none" and route != "gmail":
        errors.append(f"route_intent_mismatch:{route}+gmail_intent={gmail_intent}")

    if errors:
        logger.warning(
            "[PLAN_VERIFIER] route=%s errors=%s input=%.60s",
            route, errors, user_input,
        )
    else:
        logger.debug("[PLAN_VERIFIER] plan OK route=%s tools=%d", route, len(tool_plan))

    return (not errors), errors


# ── Issue #1229: Error classification ────────────────────────────────
# CRITICAL errors MUST block tool execution.
# WARNING errors are logged but do not block.
_CRITICAL_PREFIXES: frozenset[str] = frozenset({
    "unknown_tool",
    "route_tool_mismatch",
    "smalltalk_with_tools",
    "missing_slot",
    "missing_gmail_field",
    "route_intent_mismatch",
})

_WARNING_PREFIXES: frozenset[str] = frozenset({
    "tool_plan_no_indicators",
    "calendar_write_no_temporal",
})


def classify_errors(
    errors: list[str],
) -> tuple[list[str], list[str]]:
    """Split plan errors into (critical, warnings).

    Critical errors must prevent tool execution.
    Warnings are informational and should be logged only.
    """
    critical: list[str] = []
    warnings: list[str] = []
    for err in errors:
        prefix = err.split(":")[0]
        if prefix in _CRITICAL_PREFIXES:
            critical.append(err)
        else:
            warnings.append(err)
    return critical, warnings
