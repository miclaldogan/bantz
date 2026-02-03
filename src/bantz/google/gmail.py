"""Gmail read-only helpers (Issue #170).

This module intentionally keeps side effects minimal:
- Uses OAuth credentials from `bantz.google.gmail_auth`.
- Read-only operations (list messages, unread count estimate).

Return payloads follow the tool-friendly `{ok: bool, ...}` pattern.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Optional

from bantz.google.gmail_auth import GMAIL_READONLY_SCOPES, authenticate_gmail


_BODY_TRUNCATE_LIMIT = 5000


def _b64url_decode(data: str) -> bytes:
    """Decode Gmail base64url body data safely."""
    raw = (data or "").strip()
    if not raw:
        return b""
    # Gmail uses URL-safe base64 without padding.
    pad = (-len(raw)) % 4
    if pad:
        raw += "=" * pad
    return base64.urlsafe_b64decode(raw.encode("ascii"))


def _to_text(data: bytes) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def _truncate(text: Optional[str], limit: int = _BODY_TRUNCATE_LIMIT) -> tuple[str, bool]:
    s = str(text or "")
    if len(s) <= limit:
        return s, False
    return s[:limit], True


def _strip_html(html: str) -> str:
    # Keep this dependency-free; only used as a fallback.
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
    out: list[dict[str, Any]] = []
    for p in parts:
        if isinstance(p, dict):
            out.append(p)
    return out


def _extract_bodies_and_attachments(payload: dict[str, Any]) -> tuple[Optional[str], Optional[str], list[dict[str, Any]]]:
    """Extract best-effort plain/html bodies + attachment metadata from full payload."""

    plain_chunks: list[str] = []
    html_chunks: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType") or "")
        filename = str(part.get("filename") or "")
        body = part.get("body") if isinstance(part.get("body"), dict) else {}

        data = body.get("data")
        attachment_id = body.get("attachmentId")
        size = body.get("size")

        if filename or attachment_id:
            # Attachment detection: keep it simple and read-only.
            attachments.append(
                {
                    "filename": filename or None,
                    "mimeType": mime or None,
                    "size": int(size) if isinstance(size, int) else None,
                }
            )

        if mime == "text/plain" and isinstance(data, str) and data:
            plain_chunks.append(_to_text(_b64url_decode(data)))
        elif mime == "text/html" and isinstance(data, str) and data:
            html_chunks.append(_to_text(_b64url_decode(data)))

        for child in _collect_parts(part):
            walk(child)

    walk(payload)

    plain = "\n".join([c for c in plain_chunks if c.strip()]).strip() or None
    html = "\n".join([c for c in html_chunks if c.strip()]).strip() or None
    return plain, html, attachments


def _summarize_full_message(msg: dict[str, Any]) -> dict[str, Any]:
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    plain, html, attachments = _extract_bodies_and_attachments(payload)

    # Provide both. If plain is missing, fall back to HTML-derived text.
    body_text = plain
    body_html = html
    if body_text is None and body_html is not None:
        body_text = _strip_html(body_html)

    body_text_trunc, truncated = _truncate(body_text)
    body_html_trunc, html_truncated = _truncate(body_html)
    truncated = truncated or html_truncated

    return {
        "id": str(msg.get("id") or ""),
        "threadId": str(msg.get("threadId") or ""),
        "from": _get_header(payload, "From"),
        "subject": _get_header(payload, "Subject"),
        "date": _get_header(payload, "Date"),
        "snippet": str(msg.get("snippet") or ""),
        "body_text": body_text_trunc,
        "body_html": body_html_trunc if body_html_trunc else None,
        "attachments": attachments,
        "truncated": bool(truncated),
    }


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


def gmail_list_messages(
    *,
    max_results: int = 10,
    unread_only: bool = False,
    page_token: Optional[str] = None,
    service: Any = None,
) -> dict[str, Any]:
    """List messages from Gmail inbox with basic metadata.

    Args:
        max_results: Max number of messages to return.
        unread_only: If True, query uses `is:unread`.
        page_token: Gmail `nextPageToken` from a previous call.
        service: Optional injected Gmail API service for testing.

    Returns:
        Dict with keys:
        - ok: bool
        - query: str
        - estimated_count: int | None
        - next_page_token: str | None
        - messages: list[{id, from, subject, snippet, date}]
    """

    if not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    q = "is:unread" if unread_only else "in:inbox"

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)

        list_kwargs: dict[str, Any] = {
            "userId": "me",
            "q": q,
            "maxResults": max_results,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token

        list_resp = svc.users().messages().list(**list_kwargs).execute() or {}

        msg_refs = list_resp.get("messages")
        if not isinstance(msg_refs, list):
            msg_refs = []

        next_page_token = list_resp.get("nextPageToken")
        estimated_count = list_resp.get("resultSizeEstimate")
        if not isinstance(estimated_count, int):
            estimated_count = None

        out_messages: list[dict[str, Any]] = []
        for ref in msg_refs:
            if not isinstance(ref, dict):
                continue
            msg_id = ref.get("id")
            if not msg_id:
                continue

            msg = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=str(msg_id),
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
                or {}
            )

            payload = msg.get("payload")
            if not isinstance(payload, dict):
                payload = {}

            out_messages.append(
                {
                    "id": str(msg.get("id") or msg_id),
                    "from": _get_header(payload, "From"),
                    "subject": _get_header(payload, "Subject"),
                    "snippet": str(msg.get("snippet") or ""),
                    "date": _get_header(payload, "Date"),
                }
            )

        return {
            "ok": True,
            "query": q,
            "estimated_count": estimated_count,
            "next_page_token": str(next_page_token) if next_page_token else None,
            "messages": out_messages,
        }

    except Exception as e:  # pragma: no cover (covered via caller tests generally)
        return {
            "ok": False,
            "query": q,
            "error": str(e),
            "messages": [],
            "estimated_count": None,
            "next_page_token": None,
        }


def gmail_unread_count(*, service: Any = None) -> dict[str, Any]:
    """Return an estimated unread count using Gmail search query.

    Uses `q="is:unread"` and reads `resultSizeEstimate`.
    """

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=1)
            .execute()
            or {}
        )
        est = resp.get("resultSizeEstimate")
        return {"ok": True, "unread_count_estimate": int(est) if isinstance(est, int) else 0}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "unread_count_estimate": 0}


def gmail_get_message(
    *,
    message_id: str,
    expand_thread: bool = False,
    max_thread_messages: int = 25,
    service: Any = None,
) -> dict[str, Any]:
    """Get a Gmail message body + attachments, optionally expanding its thread.

    Args:
        message_id: Gmail message id.
        expand_thread: If True, fetch thread and return messages.
        max_thread_messages: Safety cap for thread expansion.
        service: Optional injected Gmail API service for testing.

    Returns:
        Dict with keys:
        - ok: bool
        - message: {id, threadId, from, subject, date, snippet, body_text, body_html, attachments, truncated}
        - thread: {id, messages: [...] } | None
    """

    if not message_id or not str(message_id).strip():
        raise ValueError("message_id must be non-empty")

    if not isinstance(max_thread_messages, int) or max_thread_messages <= 0:
        raise ValueError("max_thread_messages must be a positive integer")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)
        msg = (
            svc.users()
            .messages()
            .get(userId="me", id=str(message_id).strip(), format="full")
            .execute()
            or {}
        )

        message = _summarize_full_message(msg)

        thread_out: Optional[dict[str, Any]] = None
        if expand_thread:
            thread_id = message.get("threadId") or msg.get("threadId")
            if thread_id:
                thread = (
                    svc.users()
                    .threads()
                    .get(userId="me", id=str(thread_id).strip(), format="full")
                    .execute()
                    or {}
                )
                raw_msgs = thread.get("messages")
                messages: list[dict[str, Any]] = []
                if isinstance(raw_msgs, list):
                    for m in raw_msgs[: max_thread_messages]:
                        if isinstance(m, dict):
                            messages.append(_summarize_full_message(m))
                thread_out = {"id": str(thread.get("id") or thread_id), "messages": messages}

        return {"ok": True, "message": message, "thread": thread_out}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "message": None, "thread": None}
