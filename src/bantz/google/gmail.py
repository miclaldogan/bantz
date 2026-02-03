"""Gmail read-only helpers (Issue #170).

This module intentionally keeps side effects minimal:
- Uses OAuth credentials from `bantz.google.gmail_auth`.
- Read-only operations (list messages, unread count estimate).

Return payloads follow the tool-friendly `{ok: bool, ...}` pattern.
"""

from __future__ import annotations

from typing import Any, Optional

from bantz.google.gmail_auth import authenticate_gmail


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
        svc = service or authenticate_gmail()

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
        svc = service or authenticate_gmail()
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
