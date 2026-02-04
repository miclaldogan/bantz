"""Gmail auto-reply & smart reply suggestions (Issue #177).

Core idea:
- Fetch the original email (full format)
- Detect reply targets (reply vs reply-all)
- Use a *quality* LLM client (Gemini preferred via create_quality_client)
- Generate 3 reply options (short/medium/detailed)
- Create a Gmail draft (never sends)

This module is intentionally dependency-free.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Any, Optional

from bantz.google.gmail_auth import GMAIL_SEND_SCOPES, authenticate_gmail
from bantz.llm import LLMMessage, create_quality_client
from bantz.llm.base import LLMClientProtocol
from bantz.llm.json_repair import extract_json_from_text


REPLY_BASES: dict[str, str] = {
    "default": "Dil: doğal, nazik, profesyonel. Gereksiz uzatma.",
    "formal": "Dil: resmi, ciddi ve çok profesyonel. Argo/emoji yok.",
    "friendly": "Dil: sıcak ve samimi (ama saygılı). Kısa cümleler.",
}


@dataclass(frozen=True)
class ReplyTargets:
    reply_all: bool
    to_addrs: list[str]
    cc_addrs: list[str]


def _b64url_decode(data: str) -> bytes:
    raw = (data or "").strip()
    if not raw:
        return b""
    pad = (-len(raw)) % 4
    if pad:
        raw += "=" * pad
    return base64.urlsafe_b64decode(raw.encode("ascii"))


def _get_header(payload: dict[str, Any], name: str) -> Optional[str]:
    headers = payload.get("headers") if isinstance(payload, dict) else None
    if not isinstance(headers, list):
        return None

    target = name.strip().lower()
    for h in headers:
        if not isinstance(h, dict):
            continue
        n = str(h.get("name") or "").strip().lower()
        if n == target:
            v = h.get("value")
            return str(v) if v is not None else None

    return None


def _strip_html(html: str) -> str:
    h = str(html or "")
    h = re.sub(r"<script[\s\S]*?</script>", " ", h, flags=re.IGNORECASE)
    h = re.sub(r"<style[\s\S]*?</style>", " ", h, flags=re.IGNORECASE)
    h = re.sub(r"<[^>]+>", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def _collect_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts = payload.get("parts") if isinstance(payload, dict) else None
    if not isinstance(parts, list):
        return []
    return [p for p in parts if isinstance(p, dict)]


def _extract_best_body_text(payload: dict[str, Any]) -> str:
    plain_chunks: list[str] = []
    html_chunks: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType") or "")
        body = part.get("body") if isinstance(part.get("body"), dict) else {}
        data = body.get("data")

        if mime == "text/plain" and isinstance(data, str) and data:
            plain_chunks.append(_b64url_decode(data).decode("utf-8", errors="replace"))
        elif mime == "text/html" and isinstance(data, str) and data:
            html_chunks.append(_b64url_decode(data).decode("utf-8", errors="replace"))

        for child in _collect_parts(part):
            walk(child)

    walk(payload)

    plain = "\n".join([c for c in plain_chunks if c.strip()]).strip()
    if plain:
        return plain

    html = "\n".join([c for c in html_chunks if c.strip()]).strip()
    if html:
        return _strip_html(html)

    return ""


def _parse_addrs(header_value: Optional[str]) -> list[str]:
    raw = str(header_value or "").strip()
    if not raw:
        return []
    addrs = [addr.strip() for _name, addr in getaddresses([raw]) if addr and str(addr).strip()]

    # De-dup while preserving order
    out: list[str] = []
    seen: set[str] = set()
    for a in addrs:
        key = a.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _get_my_email(*, service: Any) -> Optional[str]:
    try:
        prof = service.users().getProfile(userId="me").execute() or {}
        email_addr = str(prof.get("emailAddress") or "").strip()
        return email_addr.casefold() if email_addr else None
    except Exception:
        return None


def _detect_reply_targets(
    *,
    payload: dict[str, Any],
    my_email: Optional[str],
    reply_all: Optional[bool],
) -> ReplyTargets:
    from_header = _get_header(payload, "From")
    reply_to_header = _get_header(payload, "Reply-To")
    to_header = _get_header(payload, "To")
    cc_header = _get_header(payload, "Cc")

    sender_addrs = _parse_addrs(reply_to_header) or _parse_addrs(from_header)
    sender = sender_addrs[0] if sender_addrs else ""

    to_addrs = _parse_addrs(to_header)
    cc_addrs = _parse_addrs(cc_header)

    me = (my_email or "").casefold().strip()

    def not_me(addr: str) -> bool:
        return not me or addr.casefold() != me

    others = [a for a in (to_addrs + cc_addrs) if not_me(a)]
    others_no_sender = [a for a in others if not sender or a.casefold() != sender.casefold()]

    inferred_reply_all = bool(cc_addrs) or len([a for a in to_addrs if not_me(a)]) > 1
    use_reply_all = inferred_reply_all if reply_all is None else bool(reply_all)

    to_out: list[str] = [sender] if sender else []
    cc_out: list[str] = others_no_sender if use_reply_all else []

    # De-dup cc
    cc_dedup: list[str] = []
    seen: set[str] = set()
    for a in cc_out:
        k = a.casefold()
        if k in seen:
            continue
        seen.add(k)
        cc_dedup.append(a)

    return ReplyTargets(reply_all=use_reply_all, to_addrs=to_out, cc_addrs=cc_dedup)


def _quote_block(*, payload: dict[str, Any], body_text: str) -> str:
    from_header = _get_header(payload, "From") or ""
    date_header = _get_header(payload, "Date") or ""
    subject_header = _get_header(payload, "Subject") or ""
    to_header = _get_header(payload, "To") or ""
    cc_header = _get_header(payload, "Cc") or ""

    lines = [
        "",
        "----- Orijinal Mesaj -----",
        f"From: {from_header}",
        f"Date: {date_header}",
        f"Subject: {subject_header}",
        f"To: {to_header}",
    ]
    if cc_header.strip():
        lines.append(f"Cc: {cc_header}")
    lines.append("")

    bt = str(body_text or "").strip()
    if bt:
        lines.extend(["> " + ln for ln in bt.splitlines()])

    return "\n".join(lines).strip("\n")


def _reply_subject(original_subject: str) -> str:
    subj = str(original_subject or "").strip()
    if not subj:
        return "Re:"
    if subj.lower().startswith("re:"):
        return subj
    return f"Re: {subj}"


def _parse_suggestions(raw_text: str, fallback_subject: str) -> dict[str, dict[str, str]]:
    text = str(raw_text or "").strip()
    if not text:
        return {
            "short": {"subject": fallback_subject, "body": ""},
            "medium": {"subject": fallback_subject, "body": ""},
            "detailed": {"subject": fallback_subject, "body": ""},
        }

    json_text = extract_json_from_text(text) or text
    try:
        obj = json.loads(json_text)
    except Exception:
        obj = None

    if isinstance(obj, dict):
        out: dict[str, dict[str, str]] = {}
        for key in ("short", "medium", "detailed"):
            v = obj.get(key)
            if isinstance(v, dict):
                subj = str(v.get("subject") or fallback_subject).strip() or fallback_subject
                body = str(v.get("body") or "").strip()
            else:
                subj = fallback_subject
                body = ""
            out[key] = {"subject": subj, "body": body}
        return out

    # Fallback: treat entire output as medium body.
    return {
        "short": {"subject": fallback_subject, "body": ""},
        "medium": {"subject": fallback_subject, "body": text},
        "detailed": {"subject": fallback_subject, "body": ""},
    }


def _build_prompt(
    *,
    original_from: str,
    original_subject: str,
    original_date: str,
    original_body: str,
    user_intent: str,
    include_quote: bool,
    quote_block: str,
    reply_all: bool,
    base: str,
) -> list[LLMMessage]:
    base_key = str(base or "default").strip().lower() or "default"
    base_hint = REPLY_BASES.get(base_key) or REPLY_BASES["default"]

    system = (
        "Sen bir e-posta asistanısın. Görev: Kullanıcının niyetine göre Türkçe e-posta cevabı yaz.\n"
        f"Base: {base_key}. {base_hint}\n"
        "Kurallar:\n"
        "- Yalnızca e-posta gövdesi üret (imza gerekiyorsa basit ve kısa).\n"
        "- Uydurma bilgi ekleme; tarih/sayı/vaat icat etme.\n"
        "- Kısa/Orta/Detaylı olmak üzere 3 seçenek üret.\n"
        "- Çıktı SADECE JSON object olsun; Markdown yok.\n"
        "JSON Şema:\n"
        "{\n"
        "  \"short\": {\"subject\": string, \"body\": string},\n"
        "  \"medium\": {\"subject\": string, \"body\": string},\n"
        "  \"detailed\": {\"subject\": string, \"body\": string}\n"
        "}\n"
    )

    quote_note = "EVET" if include_quote else "HAYIR"
    reply_all_note = "EVET" if reply_all else "HAYIR"

    user = (
        "ORIGINAL EMAIL:\n"
        f"From: {original_from}\n"
        f"Date: {original_date}\n"
        f"Subject: {original_subject}\n\n"
        f"Body:\n{original_body}\n\n"
        f"USER_INTENT:\n{str(user_intent or '').strip()}\n\n"
        f"INCLUDE_QUOTE: {quote_note}\n"
        f"REPLY_ALL: {reply_all_note}\n"
    )
    if include_quote and quote_block.strip():
        user += f"\nQUOTE_BLOCK (append to the end of the reply body exactly as-is after a blank line):\n{quote_block}\n"

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def gmail_generate_reply(
    *,
    message_id: str,
    user_intent: str,
    base: str = "default",
    reply_all: Optional[bool] = None,
    include_quote: bool = False,
    llm: Optional[LLMClientProtocol] = None,
    service: Any = None,
) -> dict[str, Any]:
    """Generate reply suggestions and create a reply draft (Issue #177).

    Policy:
      - MODERATE: creates a draft (no sending)

    Args:
        message_id: Gmail message ID to reply to
        user_intent: Natural-language intent for the reply
        reply_all: Optional override for reply-all behavior
        include_quote: If True, append an "original message" quoted block
        llm: Optional injected LLM client (defaults to create_quality_client)
        service: Optional injected Gmail API service for testing

    Returns:
        Tool-friendly dict with draft_id, options, and routing metadata.
    """

    mid = str(message_id or "").strip()
    if not mid:
        raise ValueError("message_id must be non-empty")

    intent = str(user_intent or "").strip()
    if not intent:
        raise ValueError("user_intent must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute() or {}

        payload = msg.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        original_from = _get_header(payload, "From") or ""
        original_subject = _get_header(payload, "Subject") or ""
        original_date = _get_header(payload, "Date") or ""
        original_body = _extract_best_body_text(payload) or str(msg.get("snippet") or "")
        thread_id = str(msg.get("threadId") or "").strip() or None

        my_email = _get_my_email(service=svc)
        targets = _detect_reply_targets(payload=payload, my_email=my_email, reply_all=reply_all)

        subj = _reply_subject(original_subject)
        quote = _quote_block(payload=payload, body_text=original_body) if include_quote else ""

        llm_client = llm or create_quality_client()
        prompt_messages = _build_prompt(
            original_from=original_from,
            original_subject=original_subject,
            original_date=original_date,
            original_body=original_body,
            user_intent=intent,
            include_quote=bool(include_quote),
            quote_block=quote,
            reply_all=targets.reply_all,
            base=base,
        )

        raw = llm_client.chat(prompt_messages, temperature=0.4, max_tokens=900)
        suggestions = _parse_suggestions(raw, fallback_subject=subj)

        # Draft: use medium by default.
        selected = suggestions.get("medium") or {"subject": subj, "body": ""}
        body_out = str(selected.get("body") or "")
        if include_quote and quote.strip():
            # Ensure quote exists even if the LLM forgot.
            if quote not in body_out:
                body_out = (body_out.rstrip() + "\n\n" + quote).strip("\n")

        msg_out = EmailMessage()
        if targets.to_addrs:
            msg_out["To"] = ", ".join(targets.to_addrs)
        if targets.cc_addrs:
            msg_out["Cc"] = ", ".join(targets.cc_addrs)
        msg_out["Subject"] = str(selected.get("subject") or subj).strip() or subj

        # Threading headers (best-effort).
        orig_msgid = (_get_header(payload, "Message-ID") or "").strip()
        orig_refs = (_get_header(payload, "References") or "").strip()
        if orig_msgid:
            msg_out["In-Reply-To"] = orig_msgid
            msg_out["References"] = (orig_refs + " " + orig_msgid).strip() if orig_refs else orig_msgid

        msg_out.set_content(body_out)
        raw_out = base64.urlsafe_b64encode(msg_out.as_bytes()).decode("utf-8")

        create_body: dict[str, Any] = {"message": {"raw": raw_out}}
        if thread_id:
            create_body["message"]["threadId"] = thread_id

        resp = svc.users().drafts().create(userId="me", body=create_body).execute() or {}
        draft_id = str(resp.get("id") or "")
        draft_msg = resp.get("message") if isinstance(resp.get("message"), dict) else {}

        # Normalize options for return payload.
        options = [
            {"style": "short", **suggestions.get("short", {"subject": subj, "body": ""})},
            {"style": "medium", **suggestions.get("medium", {"subject": subj, "body": ""})},
            {"style": "detailed", **suggestions.get("detailed", {"subject": subj, "body": ""})},
        ]

        return {
            "ok": True,
            "message_id": mid,
            "thread_id": str(draft_msg.get("threadId") or thread_id or ""),
            "draft_id": draft_id,
            "base": str(base or "default"),
            "reply_all": targets.reply_all,
            "to": targets.to_addrs,
            "cc": targets.cc_addrs or None,
            "include_quote": bool(include_quote),
            "options": options,
            "selected_style": "medium",
            "preview": (body_out[:200] + "…") if len(body_out) > 200 else body_out,
            "llm_backend": getattr(llm_client, "backend_name", "") or "",
            "llm_model": getattr(llm_client, "model_name", "") or "",
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "message_id": mid,
            "draft_id": "",
            "thread_id": "",
            "options": [],
        }
