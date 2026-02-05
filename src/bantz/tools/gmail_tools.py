from __future__ import annotations

from typing import Any, Optional

from bantz.google.gmail import (
    gmail_get_message,
    gmail_list_messages,
    gmail_send,
    gmail_unread_count,
)


def gmail_unread_count_tool(**_: Any) -> dict[str, Any]:
    """Read-only: return unread count."""
    try:
        return gmail_unread_count(interactive=False)
    except Exception as e:
        return {"ok": False, "error": str(e), "unread": None}


def gmail_list_messages_tool(
    *,
    max_results: int = 5,
    unread_only: bool = False,
    query: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Read-only: list recent inbox messages with optional search query.

    Args:
        max_results: Max number of messages to return (default 5).
        unread_only: If True, only return unread messages.
        query: Gmail search query (from:, subject:, after:, label:, etc.).
               Examples:
               - "from:linkedin" → LinkedIn emails
               - "from:amazon subject:sipariş" → Amazon orders
               - "after:2026/02/01" → Emails after date
               - "label:CATEGORY_UPDATES" → Updates category
    
    Issue #285: Added query parameter support.
    """
    try:
        return gmail_list_messages(
            max_results=int(max_results),
            unread_only=bool(unread_only),
            query=query.strip() if query else None,
            interactive=False,
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "messages": []}


def gmail_get_message_tool(
    *,
    message_id: Optional[str] = None,
    prefer_unread: bool = True,
    **_: Any,
) -> dict[str, Any]:
    """Read-only: get a message by id, or fall back to the most recent inbox message.

    This is intentionally forgiving because the router often cannot provide a message id.
    """

    msg_id = (message_id or "").strip()
    if not msg_id:
        # Best-effort: pick the most recent message.
        try:
            listing = gmail_list_messages(max_results=1, unread_only=bool(prefer_unread), interactive=False)
        except Exception as e:
            return {"ok": False, "error": str(e)}

        msgs = listing.get("messages") if isinstance(listing, dict) else None
        if not isinstance(msgs, list) or not msgs:
            # Try non-unread inbox as fallback.
            try:
                listing = gmail_list_messages(max_results=1, unread_only=False, interactive=False)
            except Exception as e:
                return {"ok": False, "error": str(e)}

            msgs = listing.get("messages") if isinstance(listing, dict) else None

        if isinstance(msgs, list) and msgs:
            first = msgs[0] if isinstance(msgs[0], dict) else {}
            msg_id = str(first.get("id") or "").strip()

    if not msg_id:
        return {"ok": False, "error": "No message found to read"}

    try:
        return gmail_get_message(message_id=msg_id, interactive=False)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def gmail_send_tool(
    *,
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    """Send an email via Gmail.

    Note: This is non-interactive; run `/auth gmail send` first.
    """

    try:
        return gmail_send(
            to=str(to or ""),
            subject=str(subject or ""),
            body=str(body or ""),
            cc=str(cc) if cc is not None else None,
            bcc=str(bcc) if bcc is not None else None,
            interactive=False,
        )
    except Exception as e:
        msg = str(e)
        if "yetkilendirmesi gerekli" in msg.lower() or "oauth" in msg.lower():
            msg = f"{msg} (Önce '/auth gmail send' çalıştırın.)"
        return {"ok": False, "error": msg}
