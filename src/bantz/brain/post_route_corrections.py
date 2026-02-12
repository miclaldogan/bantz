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
    """Extract recipient name from Turkish email patterns (e.g. Ali'ye mail)."""
    t = text or ""
    m = re.search(
        r"\b([A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü][\wÇĞİÖŞÜçğıöşü]+)*)\s*'?\s*(?:ye|ya)\s+(?:bir\s+)?(?:mail|e-?posta)\b",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    name = str(m.group(1) or "").strip()
    return name or None


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

    email_in_body = re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", body)
    if email_in_body and email_in_body.start() == 0:
        body = body[email_in_body.end():].strip(" \t\n\r,;:-")

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
    if _route not in ("unknown", "smalltalk", ""):
        # LLM routed to calendar/system/etc. — unlikely email, skip correction
        return output

    gmail_obj = dict(getattr(output, "gmail", None) or {})
    slots = dict(getattr(output, "slots", None) or {})

    gmail_obj.setdefault("subject", "")

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
