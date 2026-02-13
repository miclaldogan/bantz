"""Rule-based Gmail intent detection for Turkish (Issue #422).

When the 3B model returns gmail_intent='none' or misroutes 'mail at' vs 'mail oku',
this module provides a keyword-based fallback that resolves the intent from the
user's original Turkish text.

Keyword patterns:
- send: gönder, at, yolla, yaz (mail context)
- read: oku, aç, göster, bak
- list: listele, sırala, göster (without specific email target)
- search: ara, bul, filtrele
"""

from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Keyword → intent mapping (ordered by specificity) ───────────────────────

# Send indicators (Turkish conjugation-aware)
_SEND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:gönder|yolla|ilet)\b", re.IGNORECASE),
    # "mail at" / "e-posta at" — "at" is ambiguous (also "throw"), but with mail context it means send
    re.compile(r"\b(?:mail|e-?posta|mesaj)\b.*\b(?:at|atıver)\b", re.IGNORECASE),
    re.compile(r"\b(?:at|atıver)\b.*\b(?:mail|e-?posta|mesaj)\b", re.IGNORECASE),
    # "X'e yaz" (write to X) — when in gmail context
    re.compile(r"\b(?:mail|e-?posta)\b.*\byaz\b", re.IGNORECASE),
    re.compile(r"\byaz\b.*\b(?:mail|e-?posta)\b", re.IGNORECASE),
    # "reply" / "cevap ver" / "cevapla"
    re.compile(r"\bcevap(?:la|lar|layın|lasın)?\b", re.IGNORECASE),
    re.compile(r"\bcevap\s+ver\b", re.IGNORECASE),
    re.compile(r"\byanıtla\b", re.IGNORECASE),
]

# Read indicators
_READ_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:mail|e-?posta|mesaj)\w*\s+oku\b", re.IGNORECASE),
    re.compile(r"\boku\w*\s+(?:mail|e-?posta|mesaj)\b", re.IGNORECASE),
    re.compile(r"\b(?:mail|e-?posta|mesaj)\w*\s+aç\b", re.IGNORECASE),
    re.compile(r"\baç\w*\s+(?:mail|e-?posta|mesaj)\b", re.IGNORECASE),
    # "maili göster" / "maile bak"
    re.compile(r"\b(?:mail|e-?posta|mesaj)\w*\s+(?:göster|bak)\b", re.IGNORECASE),
    # "son maili oku" / "gelen maili aç"
    re.compile(r"\b(?:son|gelen|yeni)\s+(?:mail|e-?posta)\w*\b.*\b(?:oku|aç|göster|bak)\b", re.IGNORECASE),
]

# Search indicators
_SEARCH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:mail|e-?posta|mesaj)\w*\s+(?:ara|bul)\b", re.IGNORECASE),
    re.compile(r"\b(?:ara|bul)\w*\s+(?:mail|e-?posta|mesaj)\b", re.IGNORECASE),
    re.compile(r"\b(?:mail|e-?posta)\w*\s+filtrele\b", re.IGNORECASE),
    # Implicit search: "linkedin maili", "amazon siparişi maili"
    re.compile(r"\b\w+\s+(?:maili|mailini|maillerini)\b", re.IGNORECASE),
    # "X'den gelen mail"
    re.compile(r"\b\w+['\u2019]?(?:den|dan|ten|tan)\s+(?:gelen|gönderilen)\s+(?:mail|e-?posta)\b", re.IGNORECASE),
]

# List indicators
_LIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:mail|e-?posta|mesaj)\w*\s+(?:listele|sırala)\b", re.IGNORECASE),
    re.compile(r"\b(?:listele|sırala)\w*\s+(?:mail|e-?posta|mesaj)\b", re.IGNORECASE),
    # "kaç mail var" / "maillerim" / "gelen kutusu"
    re.compile(r"\b(?:kaç|ne\s+kadar)\s+(?:mail|e-?posta|mesaj)\b", re.IGNORECASE),
    re.compile(r"\bgelen\s+kutu(?:su|m)\b", re.IGNORECASE),
    re.compile(r"\bmaillerim\b", re.IGNORECASE),
    # "son mailleri göster" (plural → list, not read single)
    re.compile(r"\b(?:son|tüm|bütün|yeni)\s+(?:mailler|e-?postalar|mesajlar)\w*\b", re.IGNORECASE),
]

# Gmail context detector — does the text mention mail at all?
# Allow Turkish suffixes: maili, maile, mailim, mailini, mailleri, etc.
_GMAIL_CONTEXT_RE = re.compile(
    r"\b(?:mail\w*|e-?posta\w*|gmail|inbox|gelen\s+kutu\w*|mesaj\w*)\b",
    re.IGNORECASE,
)


def detect_gmail_intent(text: str) -> Optional[str]:
    """Detect Gmail intent from Turkish user text using keyword patterns.

    Returns one of: 'send', 'read', 'search', 'list', or None if no
    Gmail intent could be determined.

    Priority order (most specific first):
    1. send — explicit send verbs
    2. read — explicit read/open verbs for a single email
    3. search — explicit search/find verbs
    4. list — plural listing verbs or inbox queries
    """
    if not text:
        return None

    text = text.strip()

    # Must have some gmail context
    if not _GMAIL_CONTEXT_RE.search(text):
        return None

    # ── Check for plural indicators first (list takes priority over read
    #    when the noun is plural: mailleri, mailler, e-postaları, mesajları)
    _plural_re = re.compile(r"\b(?:mailler\w*|e-?postalar\w*|mesajlar\w*)\b", re.IGNORECASE)
    is_plural = bool(_plural_re.search(text))

    # Check in priority order
    for pattern in _SEND_PATTERNS:
        if pattern.search(text):
            logger.debug("[gmail_intent] detected 'send' from: %s", text[:60])
            return "send"

    # If plural noun → list before read
    if is_plural:
        for pattern in _LIST_PATTERNS:
            if pattern.search(text):
                logger.debug("[gmail_intent] detected 'list' (plural) from: %s", text[:60])
                return "list"

    for pattern in _READ_PATTERNS:
        if pattern.search(text):
            logger.debug("[gmail_intent] detected 'read' from: %s", text[:60])
            return "read"

    for pattern in _SEARCH_PATTERNS:
        if pattern.search(text):
            logger.debug("[gmail_intent] detected 'search' from: %s", text[:60])
            return "search"

    for pattern in _LIST_PATTERNS:
        if pattern.search(text):
            logger.debug("[gmail_intent] detected 'list' from: %s", text[:60])
            return "list"

    return None


def resolve_gmail_intent(
    *,
    llm_intent: str,
    user_text: str,
    route: str = "",
) -> str:
    """Resolve final Gmail intent, combining LLM output with rule-based fallback.

    Logic:
    1. If LLM returned a valid intent (!= 'none'), trust it.
    2. If LLM returned 'none' or route is 'gmail', use keyword detection.
    3. Return 'none' as last resort.

    Args:
        llm_intent: Intent from LLM output (list|search|read|send|none)
        user_text: Original user text for keyword fallback
        route: LLM route (used to decide if gmail context is implied)

    Returns:
        Resolved intent string.
    """
    # Valid LLM intent → trust it
    if llm_intent in {"list", "search", "read", "send"}:
        return llm_intent

    # Keyword-based fallback
    detected = detect_gmail_intent(user_text)
    if detected:
        logger.info(
            "[gmail_intent] keyword fallback: LLM='%s' → detected='%s'",
            llm_intent,
            detected,
        )
        return detected

    # If route is gmail but no intent could be determined, default to list
    if route == "gmail":
        logger.info("[gmail_intent] route=gmail but no intent detected, defaulting to 'list'")
        return "list"

    return "none"
