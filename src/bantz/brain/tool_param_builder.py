"""Tool parameter builder (extracted from orchestrator_loop.py).

Issue #941: Extracted to reduce orchestrator_loop.py from 2434 lines.
Contains: build_tool_params with field aliasing logic.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from bantz.brain.llm_router import OrchestratorOutput

logger = logging.getLogger(__name__)

# Valid gmail parameter names (Issue #365)
# Issue #1171: Include known aliases so they survive early filtering
# before remap. Aliases are remapped to canonical names below.
GMAIL_VALID_PARAMS = frozenset({
    "to", "name", "subject", "body", "cc", "bcc",
    "label", "category", "query", "search_term", "natural_query",
    "message_id", "max_results", "unread_only", "prefer_unread",
    "page_token",
    # Aliases (remapped in build_tool_params)
    "recipient", "email", "address", "emails", "to_address",
    "message", "text", "content", "message_body",
    "title",
})


# Issue #1213: Turkish patterns for extracting Gmail query from user input.
# Matches: "X'dan gelen", "X'den gelen", "Xdan gelen", "Xden gelen"
# Also: "X hakkında", "X ile ilgili", "X konulu"
_SENDER_PATTERN = re.compile(
    r"([a-zçğıöşüA-ZÇĞİÖŞÜ0-9_.@-]+)[''ʼ]?(?:dan|den|tan|ten)\s+gelen",
    re.IGNORECASE,
)
_SUBJECT_PATTERNS = [
    re.compile(r"([a-zçğıöşüA-ZÇĞİÖŞÜ0-9_.@\s-]+?)\s+(?:hakkında|hakkındaki)", re.IGNORECASE),
    re.compile(r"([a-zçğıöşüA-ZÇĞİÖŞÜ0-9_.@\s-]+?)\s+(?:ile\s+ilgili)", re.IGNORECASE),
    re.compile(r"([a-zçğıöşüA-ZÇĞİÖŞÜ0-9_.@\s-]+?)\s+konulu", re.IGNORECASE),
]


def _extract_gmail_query_from_input(user_input: str) -> str:
    """Extract a Gmail search query from Turkish user input.

    Issue #1213: Parses patterns like:
    - 'tübitaktan gelen mailleri listele' → 'from:tübitak'
    - 'github hakkındaki mailler' → 'github'
    - 'linkedinden gelen mesajlar' → 'from:linkedin'
    """
    text = (user_input or "").strip()
    if not text:
        return ""

    # Try sender pattern first: "Xdan/Xden gelen"
    m = _SENDER_PATTERN.search(text)
    if m:
        sender = m.group(1).strip().rstrip("'ʼ'")
        if sender and len(sender) >= 2:
            return f"from:{sender}"

    # Try subject/topic patterns
    for pat in _SUBJECT_PATTERNS:
        m = pat.search(text)
        if m:
            topic = m.group(1).strip()
            if topic and len(topic) >= 2:
                return topic

    return ""


def build_tool_params(
    tool_name: str,
    slots: dict[str, Any],
    output: Optional[OrchestratorOutput] = None,
    *,
    user_input: Optional[str] = None,
    original_user_input: Optional[str] = None,
) -> dict[str, Any]:
    """Build tool parameters from orchestrator slots.

    Maps orchestrator slots to tool-specific parameters.
    Handles nested objects like gmail: {to, subject, body}.

    Issue #340: Applies field aliasing for common LLM variations.
    Issue #1244: When ``original_user_input`` differs from ``user_input``
    (bridge translated), content params (title, body, description) are
    restored from the original Turkish text so the LLM's EN translations
    don't leak into user-facing data.
    """
    # Issue #1244: Determine if bridge is active (inputs differ)
    _bridge_active = (
        original_user_input is not None
        and user_input is not None
        and original_user_input != user_input
    )

    params: dict[str, Any] = {}

    if tool_name.startswith("gmail."):
        # First check slots.gmail (legacy)
        gmail_params = slots.get("gmail")
        if isinstance(gmail_params, dict):
            for key, val in gmail_params.items():
                if key in GMAIL_VALID_PARAMS and val is not None:
                    params[key] = val

        # Issue #903: Check top-level slots for gmail params
        for key, val in slots.items():
            if key in GMAIL_VALID_PARAMS and val is not None and key not in params:
                params[key] = val

        # Then check output.gmail (Issue #317) — highest priority
        if output is not None:
            gmail_obj = getattr(output, "gmail", None) or {}
            if isinstance(gmail_obj, dict):
                for key, val in gmail_obj.items():
                    if key in GMAIL_VALID_PARAMS and val is not None:
                        params[key] = val

        # Issue #340: Apply field aliasing for gmail.send
        if tool_name == "gmail.send":
            for alias in ["recipient", "email", "address", "emails", "to_address"]:
                if alias in params and "to" not in params:
                    params["to"] = params.pop(alias)
                    break

            for alias in ["message", "text", "content", "message_body"]:
                if alias in params and "body" not in params:
                    params["body"] = params.pop(alias)
                    break

            if "title" in params and "subject" not in params:
                params["subject"] = params.pop("title")

            # Issue #1209: Ensure subject always present (required field).
            # LLM often returns subject=null which gets dropped by null-filter.
            if "subject" not in params:
                params["subject"] = ""

        # Minimal aliasing for gmail.send_to_contact
        if tool_name == "gmail.send_to_contact":
            if "name" not in params and "to" in params:
                params["name"] = params.get("to")

        # Issue #1200: Aliasing for gmail.query_from_nl
        # LLM outputs natural_query / search_term / query but the tool
        # function signature requires `text`.
        if tool_name == "gmail.query_from_nl":
            if "text" not in params:
                for alias in ["natural_query", "search_term", "query"]:
                    if alias in params:
                        params["text"] = params.pop(alias)
                        break
            # Fallback: use user_input as text when no alias matched
            if "text" not in params and user_input:
                params["text"] = user_input

        # Aliasing for gmail.smart_search
        # LLM may put the query into search_term/query instead of natural_query,
        # or may not provide it at all.  Fallback to user_input.
        if tool_name == "gmail.smart_search":
            if "natural_query" not in params:
                for alias in ["search_term", "query"]:
                    if alias in params:
                        params["natural_query"] = params.pop(alias)
                        break
            if "natural_query" not in params and user_input:
                params["natural_query"] = user_input

        # Issue #1213: Gmail list_messages query extraction from user input.
        # When LLM calls gmail.list_messages without a query but the user
        # input contains Turkish sender/keyword patterns, extract a Gmail
        # query to avoid returning unfiltered results.
        if tool_name == "gmail.list_messages" and user_input:
            if not params.get("query"):
                extracted_query = _extract_gmail_query_from_input(user_input)
                if extracted_query:
                    params["query"] = extracted_query
                    logger.info(
                        "[Issue #1213] Extracted gmail query '%s' from user input",
                        extracted_query,
                    )

    else:
        params = dict(slots)

    # Issue #1212: Strip fields that don't belong to the tool schema.
    # LLM often sends calendar_intent, duration, etc. to tools that don't
    # accept them, causing safety guard validation failures.
    _CALENDAR_LIST_VALID = frozenset({
        "date", "window_hint", "query", "max_results", "title",
    })
    _CALENDAR_CREATE_VALID = frozenset({
        "title", "date", "time", "duration", "window_hint",
    })
    _CALENDAR_UPDATE_VALID = frozenset({
        "event_id", "title", "date", "time", "duration",
        "location", "description",
    })
    _CALENDAR_DELETE_VALID = frozenset({"event_id"})
    # Gmail read-only tools: strip compose-only fields (to, body, etc.)
    # so stray LLM values like to:"dostum" don't hit the email sanitizer.
    _GMAIL_LIST_VALID = frozenset({
        "query", "max_results", "unread_only", "prefer_unread",
        "label", "category", "page_token",
    })
    _GMAIL_SEARCH_VALID = frozenset({
        "natural_query", "max_results", "unread_only",
    })
    _TOOL_VALID_FIELDS: dict[str, frozenset[str]] = {
        "calendar.list_events": _CALENDAR_LIST_VALID,
        "calendar.find_event": _CALENDAR_LIST_VALID,
        "calendar.find_free_slots": frozenset({
            "duration", "window_hint", "date", "suggestions",
        }),
        "calendar.create_event": _CALENDAR_CREATE_VALID,
        "calendar.update_event": _CALENDAR_UPDATE_VALID,
        "calendar.delete_event": _CALENDAR_DELETE_VALID,
        "gmail.list_messages": _GMAIL_LIST_VALID,
        "gmail.smart_search": _GMAIL_SEARCH_VALID,
    }
    valid_fields = _TOOL_VALID_FIELDS.get(tool_name)
    if valid_fields is not None:
        params = {k: v for k, v in params.items() if k in valid_fields}

    # Issue #1244: Content param restoration — when bridge translated
    # the user input to EN, the LLM may have set content params (title,
    # body, description) in English.  Restore them from original TR text.
    _CONTENT_PARAMS = {"title", "summary", "description"}
    if _bridge_active and tool_name.startswith("calendar."):
        _original = (original_user_input or "").strip()
        for _cp in _CONTENT_PARAMS:
            if _cp in params and params[_cp] and _original:
                _slot_val = str(params[_cp]).strip().lower()
                _orig_lower = _original.lower()
                # If the slot value looks like it came from the EN canonical
                # (i.e. it appears in the EN text but not in the original TR),
                # try to extract the TR content from the original input.
                if (
                    user_input
                    and _slot_val in user_input.lower()
                    and _slot_val not in _orig_lower
                ):
                    _tr_title = _extract_tr_content_from_input(
                        _original, tool_name,
                    )
                    if _tr_title:
                        logger.info(
                            "[Issue #1244] Restored %s from TR: %r → %r",
                            _cp, params[_cp], _tr_title,
                        )
                        params[_cp] = _tr_title

    return params


# Issue #1244: Turkish content extraction patterns for calendar events
_TR_TITLE_PATTERNS = [
    # "X ekle/oluştur/kaydet" — content before action verb
    re.compile(
        r"(?:takvime?\s+)?(.+?)\s+(?:ekle|oluştur|kaydet|koy|yaz|planla)",
        re.IGNORECASE,
    ),
    # "X için etkinlik/toplantı" — content before event type
    re.compile(
        r"(.+?)\s+(?:için\s+)?(?:etkinlik|toplantı|randevu)",
        re.IGNORECASE,
    ),
    # Fallback: extract content words (skip time/date/action words)
]

_TR_NOISE_WORDS = frozenset({
    "yarın", "bugün", "sabah", "akşam", "öğle", "gece",
    "saat", "da", "de", "tam", "için", "bir", "takvime",
    "takvimime", "ekle", "oluştur", "kaydet", "koy", "yaz",
    "planla", "bak", "bana", "benim", "lütfen",
})


def _extract_tr_content_from_input(original: str, tool_name: str) -> str:
    """Extract Turkish content (title/description) from original user input.

    Issue #1244: When bridge translates input, LLM may produce EN slot values.
    This function extracts the TR content from the original text.
    """
    text = original.strip()
    if not text:
        return ""

    # Try patterns
    for pat in _TR_TITLE_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip()
            # Remove time-like tokens
            candidate = re.sub(r"\b\d{1,2}[:.]\d{2}\b", "", candidate).strip()
            candidate = re.sub(r"\bsaat\s*\d+\b", "", candidate, flags=re.IGNORECASE).strip()
            # Remove date words (yarın, bugün, etc.)
            _date_words = {"yarın", "bugün", "dün", "pazartesi", "salı", "çarşamba",
                           "perşembe", "cuma", "cumartesi", "pazar", "sabah", "akşam",
                           "öğle", "öğlen", "gece"}
            candidate_words = candidate.split()
            candidate_words = [w for w in candidate_words if w.lower() not in _date_words]
            candidate = " ".join(candidate_words).strip()
            if candidate and len(candidate) >= 2:
                return candidate

    # Fallback: extract non-noise content words
    words = re.split(r"\s+", text.lower())
    content_words = [w for w in words if w not in _TR_NOISE_WORDS and len(w) >= 2
                     and not re.match(r"\d", w)]
    if content_words:
        return " ".join(content_words)

    return ""
