"""Gmail read-only helpers (Issue #170).

This module intentionally keeps side effects minimal:
- Uses OAuth credentials from `bantz.google.gmail_auth`.
- Read-only operations (list messages, unread count estimate).

Return payloads follow the tool-friendly `{ok: bool, ...}` pattern.
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from typing import Any, Optional

from bantz.google.gmail_auth import GMAIL_MODIFY_SCOPES, GMAIL_READONLY_SCOPES, GMAIL_SEND_SCOPES, authenticate_gmail


_BODY_TRUNCATE_LIMIT = 5000


def gmail_list_labels(*, service: Any = None) -> dict[str, Any]:
    """List available Gmail labels (Issue #174).

    Returns label metadata: id, name, type.
    """

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)
        resp = svc.users().labels().list(userId="me").execute() or {}
        labels = resp.get("labels")
        if not isinstance(labels, list):
            labels = []
        out: list[dict[str, Any]] = []
        for l in labels:
            if not isinstance(l, dict):
                continue
            out.append(
                {
                    "id": str(l.get("id") or ""),
                    "name": str(l.get("name") or ""),
                    "type": str(l.get("type") or ""),
                }
            )
        return {"ok": True, "labels": out}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "labels": []}


def _resolve_label_id(*, label: str, service: Any) -> str:
    raw = str(label or "").strip()
    if not raw:
        raise ValueError("label must be non-empty")

    # System labels are typically used as IDs too.
    system = {"INBOX", "UNREAD", "SENT", "TRASH", "SPAM", "IMPORTANT", "STARRED", "DRAFT", "CATEGORY_PERSONAL"}
    if raw.upper() in system:
        return raw.upper()

    # Heuristic: user label IDs are usually like "Label_123".
    if raw.startswith("Label_"):
        return raw

    # Otherwise resolve by name.
    resp = service.users().labels().list(userId="me").execute() or {}
    labels = resp.get("labels")
    if not isinstance(labels, list):
        labels = []

    target = raw.casefold()
    for l in labels:
        if not isinstance(l, dict):
            continue
        name = str(l.get("name") or "")
        if name.casefold() == target:
            lid = str(l.get("id") or "").strip()
            if lid:
                return lid

    raise ValueError(f"label not found: {raw}")


def gmail_add_label(*, message_id: str, label: str, service: Any = None) -> dict[str, Any]:
    """Add a label to a message (Issue #174)."""

    if not message_id or not str(message_id).strip():
        raise ValueError("message_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_MODIFY_SCOPES)
        label_id = _resolve_label_id(label=label, service=svc)
        resp = (
            svc.users()
            .messages()
            .modify(userId="me", id=str(message_id).strip(), body={"addLabelIds": [label_id]})
            .execute()
            or {}
        )
        return {"ok": True, "message_id": str(resp.get("id") or message_id), "added": [label_id]}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "message_id": str(message_id), "added": []}


def gmail_remove_label(*, message_id: str, label: str, service: Any = None) -> dict[str, Any]:
    """Remove a label from a message (Issue #174)."""

    if not message_id or not str(message_id).strip():
        raise ValueError("message_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_MODIFY_SCOPES)
        label_id = _resolve_label_id(label=label, service=svc)
        resp = (
            svc.users()
            .messages()
            .modify(userId="me", id=str(message_id).strip(), body={"removeLabelIds": [label_id]})
            .execute()
            or {}
        )
        return {"ok": True, "message_id": str(resp.get("id") or message_id), "removed": [label_id]}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "message_id": str(message_id), "removed": []}


def gmail_archive(*, message_id: str, service: Any = None) -> dict[str, Any]:
    """Archive a message by removing the INBOX label (Issue #174)."""

    if not message_id or not str(message_id).strip():
        raise ValueError("message_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_MODIFY_SCOPES)
        resp = (
            svc.users()
            .messages()
            .modify(userId="me", id=str(message_id).strip(), body={"removeLabelIds": ["INBOX"]})
            .execute()
            or {}
        )
        return {"ok": True, "message_id": str(resp.get("id") or message_id), "archived": True}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "message_id": str(message_id), "archived": False}


def gmail_mark_read(*, message_id: str, service: Any = None) -> dict[str, Any]:
    """Mark a message as read by removing UNREAD (Issue #174)."""

    if not message_id or not str(message_id).strip():
        raise ValueError("message_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_MODIFY_SCOPES)
        resp = (
            svc.users()
            .messages()
            .modify(userId="me", id=str(message_id).strip(), body={"removeLabelIds": ["UNREAD"]})
            .execute()
            or {}
        )
        return {"ok": True, "message_id": str(resp.get("id") or message_id), "read": True}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "message_id": str(message_id), "read": False}


def gmail_mark_unread(*, message_id: str, service: Any = None) -> dict[str, Any]:
    """Mark a message as unread by adding UNREAD (Issue #174)."""

    if not message_id or not str(message_id).strip():
        raise ValueError("message_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_MODIFY_SCOPES)
        resp = (
            svc.users()
            .messages()
            .modify(userId="me", id=str(message_id).strip(), body={"addLabelIds": ["UNREAD"]})
            .execute()
            or {}
        )
        return {"ok": True, "message_id": str(resp.get("id") or message_id), "unread": True}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "message_id": str(message_id), "unread": False}


def gmail_batch_modify(
    *,
    message_ids: list[str],
    add_labels: Optional[list[str]] = None,
    remove_labels: Optional[list[str]] = None,
    service: Any = None,
) -> dict[str, Any]:
    """Batch modify messages (Issue #174).

    Uses Gmail `batchModify` to add/remove label IDs across many messages.
    `add_labels` and `remove_labels` may contain label IDs or label names.
    """

    ids = [str(x).strip() for x in (message_ids or []) if str(x).strip()]
    if not ids:
        raise ValueError("message_ids must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_MODIFY_SCOPES)

        add_ids: list[str] = []
        for l in add_labels or []:
            add_ids.append(_resolve_label_id(label=str(l), service=svc))

        remove_ids: list[str] = []
        for l in remove_labels or []:
            remove_ids.append(_resolve_label_id(label=str(l), service=svc))

        # De-dup while preserving order.
        def _dedup(seq: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for s in seq:
                if s in seen:
                    continue
                seen.add(s)
                out.append(s)
            return out

        add_ids = _dedup(add_ids)
        remove_ids = _dedup(remove_ids)

        svc.users().messages().batchModify(
            userId="me",
            body={"ids": ids, "addLabelIds": add_ids, "removeLabelIds": remove_ids},
        ).execute()

        return {
            "ok": True,
            "message_ids": ids,
            "added": add_ids,
            "removed": remove_ids,
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "message_ids": ids,
            "added": [],
            "removed": [],
        }


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

    # NOTE: We intentionally avoid Gmail search `q=` here because the
    # `https://www.googleapis.com/auth/gmail.metadata` scope rejects `q`.
    # Listing by labels works with both `gmail.metadata` and `gmail.readonly`.
    q = "is:unread" if unread_only else "in:inbox"
    label_ids = ["INBOX"]
    if unread_only:
        label_ids.append("UNREAD")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)

        list_kwargs: dict[str, Any] = {
            "userId": "me",
            "labelIds": label_ids,
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
    """Return an estimated unread count.

    We avoid Gmail search queries (`q=`) so this works under the
    `gmail.metadata` scope as well.
    """

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)
        resp = (
            svc.users()
            .messages()
            .list(userId="me", labelIds=["UNREAD"], maxResults=1)
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


def _parse_recipients(value: Optional[str]) -> list[str]:
    """Parse recipient strings into a normalized list.

    Accepts comma/semicolon-separated values. Ignores empty items.
    """

    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    # Allow both comma and semicolon.
    parts = re.split(r"[;,]", raw)
    out: list[str] = []
    for p in parts:
        s = str(p).strip()
        if not s:
            continue
        out.append(s)
    return out


def gmail_send(
    *,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    service: Any = None,
) -> dict[str, Any]:
    """Send a plain-text email via Gmail (Issue #172).

    - RFC2822 MIME message
    - Base64url encoding
    - Supports multiple recipients in to/cc/bcc (comma/semicolon separated)

    Returns a tool-friendly payload.
    """

    to_list = _parse_recipients(to)
    if not to_list:
        raise ValueError("to must be non-empty")

    subj = str(subject or "").strip()
    if not subj:
        raise ValueError("subject must be non-empty")

    try:
        msg = EmailMessage()
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subj

        cc_list = _parse_recipients(cc)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)

        bcc_list = _parse_recipients(bcc)
        if bcc_list:
            msg["Bcc"] = ", ".join(bcc_list)

        msg.set_content(str(body or ""))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)
        resp = (
            svc.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
            or {}
        )

        label_ids = resp.get("labelIds")
        if not isinstance(label_ids, list):
            label_ids = None

        return {
            "ok": True,
            "to": to_list,
            "cc": cc_list or None,
            "bcc": bcc_list or None,
            "subject": subj,
            "message_id": str(resp.get("id") or ""),
            "thread_id": str(resp.get("threadId") or ""),
            "label_ids": label_ids,
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "to": to_list,
            "cc": _parse_recipients(cc) or None,
            "bcc": _parse_recipients(bcc) or None,
            "subject": str(subject or ""),
            "message_id": "",
            "thread_id": "",
            "label_ids": None,
        }


def _draft_message_fields_from_full_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Extract draft fields from a message payload.

    Used to preserve missing fields when updating a draft.
    """

    to_value = _get_header(payload, "To") or ""
    cc_value = _get_header(payload, "Cc") or ""
    bcc_value = _get_header(payload, "Bcc") or ""
    subject_value = _get_header(payload, "Subject") or ""

    plain, html, _attachments = _extract_bodies_and_attachments(payload)
    body_value = plain
    if body_value is None and html is not None:
        body_value = _strip_html(html)

    return {
        "to": to_value,
        "cc": cc_value,
        "bcc": bcc_value,
        "subject": subject_value,
        "body": str(body_value or ""),
    }


def gmail_create_draft(
    *,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    service: Any = None,
) -> dict[str, Any]:
    """Create a Gmail draft (Issue #173)."""

    to_list = _parse_recipients(to)
    if not to_list:
        raise ValueError("to must be non-empty")

    subj = str(subject or "").strip()
    if not subj:
        raise ValueError("subject must be non-empty")

    try:
        msg = EmailMessage()
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subj

        cc_list = _parse_recipients(cc)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)

        bcc_list = _parse_recipients(bcc)
        if bcc_list:
            msg["Bcc"] = ", ".join(bcc_list)

        msg.set_content(str(body or ""))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)
        resp = (
            svc.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
            or {}
        )

        message = resp.get("message") if isinstance(resp.get("message"), dict) else {}
        return {
            "ok": True,
            "draft_id": str(resp.get("id") or ""),
            "message_id": str(message.get("id") or ""),
            "thread_id": str(message.get("threadId") or ""),
            "to": to_list,
            "subject": subj,
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "draft_id": "",
            "message_id": "",
            "thread_id": "",
            "to": to_list,
            "subject": subj,
        }


def gmail_list_drafts(
    *,
    max_results: int = 10,
    page_token: Optional[str] = None,
    service: Any = None,
) -> dict[str, Any]:
    """List Gmail drafts with basic metadata (Issue #173)."""

    if not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)
        list_kwargs: dict[str, Any] = {"userId": "me", "maxResults": max_results}
        if page_token:
            list_kwargs["pageToken"] = page_token

        list_resp = svc.users().drafts().list(**list_kwargs).execute() or {}

        refs = list_resp.get("drafts")
        if not isinstance(refs, list):
            refs = []

        next_page_token = list_resp.get("nextPageToken")
        estimated_count = list_resp.get("resultSizeEstimate")
        if not isinstance(estimated_count, int):
            estimated_count = None

        out: list[dict[str, Any]] = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            did = ref.get("id")
            if not did:
                continue
            draft = (
                svc.users()
                .drafts()
                .get(
                    userId="me",
                    id=str(did),
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
                or {}
            )
            msg = draft.get("message") if isinstance(draft.get("message"), dict) else {}
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}

            out.append(
                {
                    "draft_id": str(draft.get("id") or did),
                    "message_id": str(msg.get("id") or ""),
                    "from": _get_header(payload, "From"),
                    "to": _get_header(payload, "To"),
                    "subject": _get_header(payload, "Subject"),
                    "date": _get_header(payload, "Date"),
                    "snippet": str(msg.get("snippet") or ""),
                }
            )

        return {
            "ok": True,
            "drafts": out,
            "estimated_count": estimated_count,
            "next_page_token": str(next_page_token) if next_page_token else None,
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "drafts": [],
            "estimated_count": None,
            "next_page_token": None,
        }


def gmail_update_draft(
    *,
    draft_id: str,
    updates: dict[str, Any],
    service: Any = None,
) -> dict[str, Any]:
    """Update an existing Gmail draft (Issue #173).

    Supports partial updates by reading the current draft when needed.
    Allowed keys: to, subject, body, cc, bcc.
    """

    if not draft_id or not str(draft_id).strip():
        raise ValueError("draft_id must be non-empty")

    if not isinstance(updates, dict) or not updates:
        raise ValueError("updates must be a non-empty dict")

    allowed = {"to", "subject", "body", "cc", "bcc"}
    if not any(k in updates for k in allowed):
        raise ValueError("updates contains no supported fields")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)

        need_existing = any(k not in updates for k in ("to", "subject", "body", "cc", "bcc"))
        existing: dict[str, str] = {}
        if need_existing:
            draft = (
                svc.users().drafts().get(userId="me", id=str(draft_id).strip(), format="full").execute() or {}
            )
            msg = draft.get("message") if isinstance(draft.get("message"), dict) else {}
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
            existing = _draft_message_fields_from_full_payload(payload)

        to_value = str(updates.get("to") if updates.get("to") is not None else existing.get("to") or "").strip()
        subject_value = str(
            updates.get("subject") if updates.get("subject") is not None else existing.get("subject") or ""
        ).strip()
        body_value = str(updates.get("body") if updates.get("body") is not None else existing.get("body") or "")
        cc_value = updates.get("cc") if "cc" in updates else existing.get("cc")
        bcc_value = updates.get("bcc") if "bcc" in updates else existing.get("bcc")

        to_list = _parse_recipients(to_value)
        if not to_list:
            raise ValueError("to must be non-empty")
        if not subject_value:
            raise ValueError("subject must be non-empty")

        msg_out = EmailMessage()
        msg_out["To"] = ", ".join(to_list)
        msg_out["Subject"] = subject_value

        cc_list = _parse_recipients(str(cc_value)) if cc_value is not None else []
        if cc_list:
            msg_out["Cc"] = ", ".join(cc_list)
        bcc_list = _parse_recipients(str(bcc_value)) if bcc_value is not None else []
        if bcc_list:
            msg_out["Bcc"] = ", ".join(bcc_list)

        msg_out.set_content(body_value)
        raw = base64.urlsafe_b64encode(msg_out.as_bytes()).decode("utf-8")

        resp = (
            svc.users()
            .drafts()
            .update(userId="me", id=str(draft_id).strip(), body={"id": str(draft_id).strip(), "message": {"raw": raw}})
            .execute()
            or {}
        )

        message = resp.get("message") if isinstance(resp.get("message"), dict) else {}
        return {
            "ok": True,
            "draft_id": str(resp.get("id") or draft_id),
            "message_id": str(message.get("id") or ""),
            "thread_id": str(message.get("threadId") or ""),
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "draft_id": str(draft_id),
            "message_id": "",
            "thread_id": "",
        }


def gmail_send_draft(*, draft_id: str, service: Any = None) -> dict[str, Any]:
    """Send a Gmail draft (Issue #173)."""

    if not draft_id or not str(draft_id).strip():
        raise ValueError("draft_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)
        resp = (
            svc.users()
            .drafts()
            .send(userId="me", body={"id": str(draft_id).strip()})
            .execute()
            or {}
        )

        label_ids = resp.get("labelIds")
        if not isinstance(label_ids, list):
            label_ids = None

        return {
            "ok": True,
            "draft_id": str(draft_id),
            "message_id": str(resp.get("id") or ""),
            "thread_id": str(resp.get("threadId") or ""),
            "label_ids": label_ids,
        }
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "draft_id": str(draft_id),
            "message_id": "",
            "thread_id": "",
            "label_ids": None,
        }


def gmail_delete_draft(*, draft_id: str, service: Any = None) -> dict[str, Any]:
    """Delete a Gmail draft (Issue #173)."""

    if not draft_id or not str(draft_id).strip():
        raise ValueError("draft_id must be non-empty")

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_SEND_SCOPES)
        svc.users().drafts().delete(userId="me", id=str(draft_id).strip()).execute()
        return {"ok": True, "draft_id": str(draft_id)}
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e), "draft_id": str(draft_id)}
