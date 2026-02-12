"""Post-route corrections (extracted from orchestrator_loop.py).

Issue #941: Extracted to reduce orchestrator_loop.py from 2434 lines.
Contains: email-send post-route correction and its helper methods.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from bantz.brain.llm_router import OrchestratorOutput

logger = logging.getLogger(__name__)


def looks_like_email_send_intent(text: str) -> bool:
    """Heuristic check for email-send intent in Turkish text."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return bool(
        re.search(r"\b(mail|e-?posta)\b\s*(gönder|at|yaz|yolla|ilet)\b", t)
        or re.search(r"\b(mail|e-?posta)\b.*\b(gönder|at|yaz|yolla|ilet)\b", t)
    )


def extract_first_email(text: str) -> str | None:
    """Extract the first email address from text."""
    m = re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", text or "")
    return str(m.group(0)).strip() if m else None


def extract_recipient_name(text: str) -> str | None:
    """Extract recipient name from Turkish email patterns.

    Issue #1006: Now handles both apostrophe and non-apostrophe forms:
    - "Ali'ye mail gönder"  (apostrophe dative)
    - "Aliye mail gönder"   (no apostrophe, fused dative)
    - "Ahmet Bey'e bir mail at" (multi-word + apostrophe)
    """
    t = text or ""
    _NAME = r"[A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü]+"
    _MULTI = rf"{_NAME}(?:\s+{_NAME})*"
    _MAIL = r"(?:bir\s+)?(?:mail|e-?posta)\b"

    # Pattern 1: Name + apostrophe + dative + mail keyword
    # "Ali'ye mail gönder", "Ahmet'e mail at", "Ahmet Bey'e bir mail at"
    m = re.search(
        rf"\b({_MULTI})\s*'\s*[yY]?[eEaA]\s+{_MAIL}",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip() or None

    # Pattern 2: Name (vowel-ending) + fused dative (ye/ya) + mail keyword
    # "Aliye mail gönder" → name ends in vowel, buffer-y + vowel follows
    _VOWELS = "aeıioöuüAEIİOÖUÜ"
    m = re.search(
        rf"\b([A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü]*[{_VOWELS}])[yY][eEaA]\s+{_MAIL}",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip() or None

    # Pattern 3: mail keyword + name ("mail gönder Ahmet'e")
    m = re.search(
        rf"\b(?:mail|e-?posta)\b.*?\b({_NAME})\s*'?\s*[yY]?[eEaA]\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip() or None

    return None


def extract_subject_hint(text: str) -> str | None:
    """Extract potential subject from user input.

    Issue #1006: Looks for 'hakkında', 'konulu', 'ile ilgili' patterns.
    """
    t = (text or "").strip()
    # "toplantı hakkında mail gönder" → subject = "toplantı"
    m = re.search(
        r"\b(.{2,60})\s+(?:hakkında|konulu|ile\s+ilgili|konusunda)\s+(?:bir\s+)?(?:mail|e-?posta)\b",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        return str(m.group(1)).strip()

    # "mail gönder konu: proje güncellemesi"
    m2 = re.search(
        r"\bkonu\s*:\s*(.{2,80})$",
        t,
        flags=re.IGNORECASE,
    )
    if m2:
        return str(m2.group(1)).strip()

    return None


def extract_message_body_hint(text: str) -> str | None:
    """Extract potential message body from user input."""
    t = (text or "").strip()
    m = re.search(
        r"\b(?:mail|e-?posta)\b\s*(?:gönder|at|yaz|yolla|ilet)\b\s*(.+)$",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    body = str(m.group(1) or "").strip()

    # Issue #1006: Strip email addresses anywhere in the body, not just at pos 0
    body = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "", body).strip(" \t\n\r,;:-")

    return body or None


def post_route_correction_email_send(
    user_input: str,
    output: OrchestratorOutput,
    *,
    debug: bool = False,
) -> OrchestratorOutput:
    """Correct obvious email-send intents that the router misclassifies.

    Issue #607: Original post-route correction for email sending.
    Issue #945: Only run when LLM route is unknown/smalltalk (misroute).
    If LLM already returned route=gmail with gmail_intent=send, trust it.
    """
    if not looks_like_email_send_intent(user_input):
        return output

    # Issue #945: Trust the LLM when it already routed correctly.
    # Only apply regex correction for likely misroutes.
    _route = getattr(output, "route", "") or ""
    _gmail_intent = getattr(output, "gmail_intent", "") or ""
    if _route == "gmail" and _gmail_intent == "send":
        # LLM got it right — do not override its (likely better) slot extraction
        if debug:
            logger.debug(
                "[POST_ROUTE_CORRECTION] email_send: LLM already route=gmail/send, skipping override"
            )
        return output
    if _route not in ("unknown", "smalltalk", "calendar", "system", ""):
        # Issue #1006: Also catch calendar/system misroutes for email-send
        return output

    gmail_obj = dict(getattr(output, "gmail", None) or {})
    slots = dict(getattr(output, "slots", None) or {})

    # Issue #1006: Extract subject from user input instead of empty default
    subject_hint = extract_subject_hint(user_input)
    gmail_obj.setdefault("subject", subject_hint or "")

    if not gmail_obj.get("to"):
        email = extract_first_email(user_input)
        if email:
            gmail_obj["to"] = email
        else:
            name = extract_recipient_name(user_input)
            if name:
                gmail_obj["to"] = name

    if not gmail_obj.get("body"):
        body_hint = extract_message_body_hint(user_input)
        if body_hint:
            gmail_obj["body"] = body_hint

    to_val = str(gmail_obj.get("to") or "").strip()
    body_val = str(gmail_obj.get("body") or "").strip()

    ask_user = bool(getattr(output, "ask_user", False))
    question = str(getattr(output, "question", "") or "")
    tool_plan: list[str] = list(getattr(output, "tool_plan", None) or [])

    if not to_val:
        ask_user = True
        question = "Kime göndermek istiyorsunuz efendim? (e-posta adresi veya kayıtlı kişi adı)"
        tool_plan = []
    elif not body_val:
        ask_user = True
        question = "Mailde ne yazmamı istersiniz efendim?"
        tool_plan = []
    else:
        if "@" in to_val:
            tool_plan = tool_plan or ["gmail.send"]
        else:
            gmail_obj.setdefault("name", to_val)
            tool_plan = tool_plan or ["gmail.send_to_contact"]

    if "to" not in slots and to_val:
        slots["to"] = to_val
    if "subject" not in slots and gmail_obj.get("subject") is not None:
        slots["subject"] = str(gmail_obj.get("subject") or "")
    if "name" not in slots and gmail_obj.get("name"):
        slots["name"] = str(gmail_obj.get("name") or "")

    corrected = replace(
        output,
        route="gmail",
        calendar_intent="none",
        gmail_intent="send",
        gmail=gmail_obj,
        slots=slots,
        ask_user=ask_user,
        question=question,
        tool_plan=tool_plan,
    )

    if debug and (
        corrected.route != output.route
        or corrected.gmail_intent != getattr(output, "gmail_intent", "none")
    ):
        logger.debug(
            "[POST_ROUTE_CORRECTION] email_send: route=%s->%s gmail_intent=%s tool_plan=%s ask_user=%s",
            output.route,
            corrected.route,
            corrected.gmail_intent,
            corrected.tool_plan,
            corrected.ask_user,
        )

    return corrected
