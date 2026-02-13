"""Gmail extended runtime tool handlers — wrappers over bantz.google.gmail.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
These tools were previously only in the planner catalog with raw
bantz.google.gmail function references. This module provides proper
runtime wrappers with error handling for OrchestratorLoop.

Tools provided:
  - gmail.list_labels
  - gmail.add_label / gmail.remove_label
  - gmail.mark_read / gmail.mark_unread
  - gmail.archive
  - gmail.batch_modify
  - gmail.download_attachment
  - gmail.create_draft / gmail.list_drafts / gmail.update_draft
  - gmail.send_draft / gmail.delete_draft
  - gmail.generate_reply
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _safe_call(fn, **kwargs) -> Dict[str, Any]:
    """Call a gmail function with error wrapping."""
    if fn is None:
        return {"ok": False, "error": "function_not_available"}
    try:
        return fn(**kwargs)
    except Exception as e:
        logger.error(f"[Gmail] {fn.__name__} error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


# ── gmail.list_labels ───────────────────────────────────────────────

def gmail_list_labels_tool(**_: Any) -> Dict[str, Any]:
    """List Gmail labels."""
    try:
        from bantz.google.gmail import gmail_list_labels
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_list_labels)


# ── gmail.add_label ─────────────────────────────────────────────────

def gmail_add_label_tool(*, message_id: str = "", label: str = "", **_: Any) -> Dict[str, Any]:
    """Add a label to a Gmail message."""
    if not message_id or not label:
        return {"ok": False, "error": "message_id_and_label_required"}
    try:
        from bantz.google.gmail import gmail_add_label
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_add_label, message_id=message_id, label=label)


# ── gmail.remove_label ──────────────────────────────────────────────

def gmail_remove_label_tool(*, message_id: str = "", label: str = "", **_: Any) -> Dict[str, Any]:
    """Remove a label from a Gmail message."""
    if not message_id or not label:
        return {"ok": False, "error": "message_id_and_label_required"}
    try:
        from bantz.google.gmail import gmail_remove_label
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_remove_label, message_id=message_id, label=label)


# ── gmail.mark_read ─────────────────────────────────────────────────

def gmail_mark_read_tool(*, message_id: str = "", **_: Any) -> Dict[str, Any]:
    """Mark a Gmail message as read."""
    if not message_id:
        return {"ok": False, "error": "message_id_required"}
    try:
        from bantz.google.gmail import gmail_mark_read
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_mark_read, message_id=message_id)


# ── gmail.mark_unread ───────────────────────────────────────────────

def gmail_mark_unread_tool(*, message_id: str = "", **_: Any) -> Dict[str, Any]:
    """Mark a Gmail message as unread."""
    if not message_id:
        return {"ok": False, "error": "message_id_required"}
    try:
        from bantz.google.gmail import gmail_mark_unread
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_mark_unread, message_id=message_id)


# ── gmail.archive ───────────────────────────────────────────────────

def gmail_archive_tool(*, message_id: str = "", **_: Any) -> Dict[str, Any]:
    """Archive a Gmail message (remove INBOX label)."""
    if not message_id:
        return {"ok": False, "error": "message_id_required"}
    try:
        from bantz.google.gmail import gmail_archive
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_archive, message_id=message_id)


# ── gmail.batch_modify ──────────────────────────────────────────────

def gmail_batch_modify_tool(
    *,
    message_ids: list[str] | None = None,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
    **_: Any,
) -> Dict[str, Any]:
    """Batch add/remove labels across messages."""
    if not message_ids:
        return {"ok": False, "error": "message_ids_required"}
    try:
        from bantz.google.gmail import gmail_batch_modify
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(
        gmail_batch_modify,
        message_ids=message_ids,
        add_labels=add_labels or [],
        remove_labels=remove_labels or [],
    )


# ── gmail.download_attachment ───────────────────────────────────────

def gmail_download_attachment_tool(
    *,
    message_id: str = "",
    attachment_id: str = "",
    save_path: str = "",
    overwrite: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Download a Gmail attachment to disk."""
    if not message_id or not attachment_id or not save_path:
        return {"ok": False, "error": "message_id_attachment_id_save_path_required"}
    try:
        from bantz.google.gmail import gmail_download_attachment
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(
        gmail_download_attachment,
        message_id=message_id,
        attachment_id=attachment_id,
        save_path=save_path,
        overwrite=overwrite,
    )


# ── gmail.create_draft ──────────────────────────────────────────────

def gmail_create_draft_tool(*, to: str = "", subject: str = "", body: str = "", **_: Any) -> Dict[str, Any]:
    """Create a Gmail draft."""
    if not to or not subject or not body:
        return {"ok": False, "error": "to_subject_body_required"}
    try:
        from bantz.google.gmail import gmail_create_draft
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    result = _safe_call(gmail_create_draft, to=to, subject=subject, body=body)
    # Issue #1225: Display hint for draft creation
    if isinstance(result, dict) and result.get("ok"):
        result["display_hint"] = f"📝 Taslak oluşturuldu: {to} — {subject}"
    return result


# ── gmail.list_drafts ───────────────────────────────────────────────

def gmail_list_drafts_tool(*, max_results: int = 10, page_token: str | None = None, **_: Any) -> Dict[str, Any]:
    """List Gmail drafts."""
    try:
        from bantz.google.gmail import gmail_list_drafts
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    kwargs: dict[str, Any] = {"max_results": max_results}
    if page_token:
        kwargs["page_token"] = page_token
    return _safe_call(gmail_list_drafts, **kwargs)


# ── gmail.update_draft ──────────────────────────────────────────────

def gmail_update_draft_tool(*, draft_id: str = "", updates: dict | None = None, **_: Any) -> Dict[str, Any]:
    """Update a Gmail draft."""
    if not draft_id:
        return {"ok": False, "error": "draft_id_required"}
    try:
        from bantz.google.gmail import gmail_update_draft
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_update_draft, draft_id=draft_id, updates=updates or {})


# ── gmail.send_draft ────────────────────────────────────────────────

def gmail_send_draft_tool(*, draft_id: str = "", **_: Any) -> Dict[str, Any]:
    """Send a Gmail draft."""
    if not draft_id:
        return {"ok": False, "error": "draft_id_required"}
    try:
        from bantz.google.gmail import gmail_send_draft
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_send_draft, draft_id=draft_id)


# ── gmail.delete_draft ──────────────────────────────────────────────

def gmail_delete_draft_tool(*, draft_id: str = "", **_: Any) -> Dict[str, Any]:
    """Delete a Gmail draft."""
    if not draft_id:
        return {"ok": False, "error": "draft_id_required"}
    try:
        from bantz.google.gmail import gmail_delete_draft
    except ImportError:
        return {"ok": False, "error": "gmail_module_not_available"}
    return _safe_call(gmail_delete_draft, draft_id=draft_id)


# ── gmail.generate_reply ────────────────────────────────────────────

def gmail_generate_reply_tool(
    *,
    message_id: str = "",
    user_intent: str = "",
    base: str = "default",
    reply_all: bool | None = None,
    include_quote: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Generate reply suggestions and create a reply draft."""
    if not message_id or not user_intent:
        return {"ok": False, "error": "message_id_and_user_intent_required"}
    try:
        from bantz.google.gmail_reply import gmail_generate_reply
    except ImportError:
        return {"ok": False, "error": "gmail_reply_module_not_available"}
    kwargs: dict[str, Any] = {
        "message_id": message_id,
        "user_intent": user_intent,
        "base": base,
        "include_quote": include_quote,
    }
    if reply_all is not None:
        kwargs["reply_all"] = reply_all
    return _safe_call(gmail_generate_reply, **kwargs)
