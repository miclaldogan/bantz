from __future__ import annotations

import hashlib
import logging
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Any, Optional

from bantz.google.gmail import (
    gmail_get_message,
    gmail_list_messages,
    gmail_send,
    gmail_unread_count,
)
from bantz.google.gmail_labels import (
    GmailLabel,
    build_smart_query,
    detect_label_from_text,
    format_labels_summary,
    get_category_labels,
)

logger = logging.getLogger(__name__)

# ── Issue #870: Türkçe hata mesajı çevirici ─────────────────────────
_GMAIL_ERROR_TR_MAP: list[tuple[str, str]] = [
    ("Google client secret not found", "Google hesap bilgileri bulunamadı. Lütfen BANTZ_GOOGLE_CLIENT_SECRET ayarını yapın."),
    ("Gmail dependencies are not installed", "Gmail bağımlılıkları yüklü değil. pip install -e '.[google]' ile yükleyin."),
    ("HttpError 401", "Gmail yetkilendirmesi başarısız. Lütfen tekrar giriş yapın."),
    ("HttpError 403", "Gmail erişim izni yok. Lütfen izinleri kontrol edin."),
    ("HttpError 404", "Belirtilen e-posta bulunamadı."),
    ("HttpError 429", "Gmail API istek limiti aşıldı. Lütfen biraz bekleyin."),
    ("timeout", "Gmail bağlantı zaman aşımına uğradı."),
    ("ConnectionError", "Gmail'e bağlanılamadı. İnternet bağlantınızı kontrol edin."),
    ("token", "Gmail oturum süresi dolmuş. Lütfen tekrar giriş yapın."),
]


def _tr_gmail_error(e: Exception) -> str:
    """Return a user-friendly Turkish error message for Gmail exceptions."""
    raw = str(e)
    for pattern, tr_msg in _GMAIL_ERROR_TR_MAP:
        if pattern.lower() in raw.lower():
            return tr_msg
    logger.error("[GMAIL] Unhandled error: %s", raw)
    return f"Gmail işlemi başarısız oldu: {raw}"

# ─────────────────────────────────────────────────────────────────────
# Gmail send duplicate guard (Issue #663)
# ─────────────────────────────────────────────────────────────────────
_GMAIL_SEND_WINDOW = 60  # seconds
_gmail_send_log: dict[str, float] = {}  # key → timestamp
_gmail_send_lock = threading.Lock()


def _gmail_send_dedup_key(to: str, subject: str) -> str:
    norm = f"{to.strip().lower()}|{subject.strip().lower()}"
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def _gmail_check_duplicate(to: str, subject: str) -> bool:
    """Return True if this to+subject was sent within the last N seconds."""
    key = _gmail_send_dedup_key(to, subject)
    now = _time.time()
    with _gmail_send_lock:
        # Clean expired
        expired = [k for k, ts in _gmail_send_log.items() if now - ts > _GMAIL_SEND_WINDOW]
        for k in expired:
            del _gmail_send_log[k]
        return key in _gmail_send_log


def _gmail_record_send(to: str, subject: str) -> None:
    key = _gmail_send_dedup_key(to, subject)
    with _gmail_send_lock:
        _gmail_send_log[key] = _time.time()


def _now_local() -> datetime:
    return datetime.now().astimezone()


_RELATIVE_WINDOWS: dict[str, str] = {
    "today": "today",
    "bugün": "today",
    "yesterday": "yesterday",
    "dün": "yesterday",
    "this_week": "this_week",
    "bu hafta": "this_week",
    "week": "this_week",
}


def _contains_date_filter(query: str) -> bool:
    q = (query or "").lower()
    return any(x in q for x in ("after:", "before:", "newer_than:"))


def _date_filter_for_window(window: str) -> str:
    now = _now_local()
    w = _RELATIVE_WINDOWS.get((window or "").strip().lower(), "")

    if w == "today":
        return f"after:{now.strftime('%Y/%m/%d')}"

    if w == "yesterday":
        today = now.date()
        yday = today - timedelta(days=1)
        return f"after:{yday.strftime('%Y/%m/%d')} before:{today.strftime('%Y/%m/%d')}"

    if w == "this_week":
        week_start = now.date() - timedelta(days=now.date().weekday())
        return f"after:{week_start.strftime('%Y/%m/%d')}"

    return ""


def gmail_unread_count_tool(**_: Any) -> dict[str, Any]:
    """Read-only: return unread count."""
    try:
        return gmail_unread_count(interactive=False)
    except Exception as e:
        return {"ok": False, "error": _tr_gmail_error(e), "unread": None}


def gmail_list_messages_tool(
    *,
    max_results: int = 5,
    unread_only: bool = False,
    query: str = "",
    date_window: Optional[str] = None,
    category: Optional[str] = None,
    label: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    """Read-only: list recent inbox messages with optional search query and label filtering.

    Args:
        max_results: Max number of messages to return (default 5).
        unread_only: If True, only return unread messages.
        query: Gmail search query (from:, subject:, after:, label:, etc.).
               Examples:
               - "from:linkedin" → LinkedIn emails
               - "from:amazon subject:sipariş" → Amazon orders
               - "after:2026/02/01" → Emails after date
               - "label:CATEGORY_UPDATES" → Updates category
        category: Gmail category filter (Turkish or English).
                  Examples: "sosyal", "promosyonlar", "güncellemeler", "forumlar"
        label: Gmail label filter (Turkish or English).
               Examples: "gelen kutusu", "gönderilenler", "yıldızlı", "önemli"
    
    Issue #285: Added query parameter support.
    Issue #317: Added category and label parameter support with Turkish keywords.
    """
    try:
        # Build query from category/label if provided
        final_query = query.strip() if query else ""
        detected_label = None
        
        # Priority: explicit query > category > label
        if not final_query:
            # Check for category or label hint
            label_hint = category or label
            if label_hint:
                label_match = detect_label_from_text(label_hint)
                if label_match.detected and label_match.label:
                    final_query = label_match.label.query_filter
                    detected_label = label_match.label

        # Deterministic relative-date filtering (Issue #605)
        if date_window and not _contains_date_filter(final_query):
            df = _date_filter_for_window(date_window)
            if df:
                final_query = f"{final_query} {df}".strip() if final_query else df
        
        result = gmail_list_messages(
            max_results=int(max_results),
            unread_only=bool(unread_only),
            query=final_query if final_query else None,
            interactive=False,
        )
        
        # Add detected label info to result
        if detected_label and isinstance(result, dict):
            result["detected_label"] = detected_label.value
            result["detected_label_tr"] = detected_label.display_name_tr

        # Issue #1225: Display hint for deterministic finalizer replies
        if isinstance(result, dict):
            msgs = result.get("messages")
            if isinstance(msgs, list) and msgs:
                lines: list[str] = []
                for i, m in enumerate(msgs, 1):
                    _from = (m.get("from") or m.get("sender") or "")[:30]
                    _subj = (m.get("subject") or "")[:50]
                    _unread = " \u2709\ufe0f" if m.get("unread") else ""
                    lines.append(f"#{i} {_from} — {_subj}{_unread}")
                result["display_hint"] = "\n".join(lines)
                result["message_count"] = len(msgs)
            elif isinstance(msgs, list):
                result["display_hint"] = "Kriterlere uyan e-posta bulunamad\u0131."
                result["message_count"] = 0
        
        return result
    except Exception as e:
        return {"ok": False, "error": _tr_gmail_error(e), "messages": []}


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
            return {"ok": False, "error": _tr_gmail_error(e)}

        msgs = listing.get("messages") if isinstance(listing, dict) else None
        if not isinstance(msgs, list) or not msgs:
            # Try non-unread inbox as fallback.
            try:
                listing = gmail_list_messages(max_results=1, unread_only=False, interactive=False)
            except Exception as e:
                return {"ok": False, "error": _tr_gmail_error(e)}

            msgs = listing.get("messages") if isinstance(listing, dict) else None

        if isinstance(msgs, list) and msgs:
            first = msgs[0] if isinstance(msgs[0], dict) else {}
            msg_id = str(first.get("id") or "").strip()

    if not msg_id:
        return {"ok": False, "error": "No message found to read"}

    try:
        return gmail_get_message(message_id=msg_id, interactive=False)
    except Exception as e:
        return {"ok": False, "error": _tr_gmail_error(e)}


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
        # Duplicate guard (Issue #663)
        if _gmail_check_duplicate(str(to or ""), str(subject or "")):
            logger.warning("[GMAIL] Duplicate send blocked: to=%s subject=%s", to, subject)
            return {
                "ok": False,
                "error": "Bu e-posta az önce gönderildi. Tekrar göndermek için biraz bekleyin.",
                "duplicate": True,
            }

        result = gmail_send(
            to=str(to or ""),
            subject=str(subject or ""),
            body=str(body or ""),
            cc=str(cc) if cc is not None else None,
            bcc=str(bcc) if bcc is not None else None,
            interactive=False,
        )

        # Record successful send for dedup
        if isinstance(result, dict) and result.get("ok", True):
            _gmail_record_send(str(to or ""), str(subject or ""))

        # Issue #1225: Display hint for send confirmation
        if isinstance(result, dict) and result.get("ok"):
            result["display_hint"] = f"\u2709\ufe0f E-posta g\u00f6nderildi: {to} — {subject}"

        return result
    except Exception as e:
        msg = str(e)
        if "yetkilendirmesi gerekli" in msg.lower() or "oauth" in msg.lower():
            msg = f"{msg} (Önce '/auth gmail send' çalıştırın.)"
        return {"ok": False, "error": msg}


def gmail_smart_search_tool(
    *,
    natural_query: str,
    max_results: int = 5,
    unread_only: bool = False,
    date_window: Optional[str] = None,
    **_: Any,
) -> dict[str, Any]:
    """Search Gmail using natural language with Turkish label detection.
    
    Automatically detects Gmail categories/labels from Turkish text.
    
    Args:
        natural_query: Natural language search (Turkish/English).
                       Examples:
                       - "sosyal mailleri göster" → Social category
                       - "promosyonlar kategorisindeki mailler" → Promotions
                       - "güncellemeler kategorisinde ne var" → Updates
                       - "gönderilen mailleri listele" → Sent
                       - "yıldızlı mailleri göster" → Starred
        max_results: Max number of messages to return (default 5).
        unread_only: If True, only return unread messages.
    
    Issue #317: Gmail label/kategori desteği.
    """
    try:
        # Build smart query from natural language
        query, detected_label = build_smart_query(
            natural_query,
            include_unread_only=bool(unread_only),
        )

        # Deterministic relative-date filtering (Issue #605)
        if date_window and not _contains_date_filter(query):
            df = _date_filter_for_window(date_window)
            if df:
                query = f"{query} {df}".strip()
        
        result = gmail_list_messages(
            max_results=int(max_results),
            unread_only=False,  # Already in query if needed
            query=query,
            interactive=False,
        )
        
        # Enhance result with detection info
        if isinstance(result, dict):
            result["natural_query"] = natural_query
            result["gmail_query"] = query
            if detected_label:
                result["detected_label"] = detected_label.value
                result["detected_label_tr"] = detected_label.display_name_tr

            # Issue #1225: Display hint (same format as list_messages)
            msgs = result.get("messages")
            if isinstance(msgs, list) and msgs:
                lines: list[str] = []
                for i, m in enumerate(msgs, 1):
                    _from = (m.get("from") or m.get("sender") or "")[:30]
                    _subj = (m.get("subject") or "")[:50]
                    _unread = " \u2709\ufe0f" if m.get("unread") else ""
                    lines.append(f"#{i} {_from} — {_subj}{_unread}")
                result["display_hint"] = "\n".join(lines)
                result["message_count"] = len(msgs)
            elif isinstance(msgs, list):
                result["display_hint"] = "Kriterlere uyan e-posta bulunamad\u0131."
                result["message_count"] = 0
        
        return result
    except Exception as e:
        return {"ok": False, "error": _tr_gmail_error(e), "messages": []}


def gmail_list_categories_tool(**_: Any) -> dict[str, Any]:
    """List available Gmail categories with Turkish names.
    
    Returns category labels like Sosyal, Promosyonlar, Güncellemeler, Forumlar.
    
    Issue #317: Gmail label/kategori desteği.
    """
    categories = get_category_labels()
    return {
        "ok": True,
        "categories": [
            {
                "id": cat.value,
                "name_tr": cat.display_name_tr,
                "name_en": cat.display_name_en,
                "query_filter": cat.query_filter,
            }
            for cat in categories
        ],
        "summary_tr": format_labels_summary(categories, language="tr"),
    }
