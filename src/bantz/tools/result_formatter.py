"""
Tool Result Formatting — Issue #434.

Human-readable Turkish formatting for tool results so the finalizer
doesn't have to interpret raw JSON (reducing hallucination risk).

Supports:
- calendar.list_events → "14:00 Toplantı (1 saat) | 16:00 Doktor (30 dk)"
- calendar.create_event → "Toplantı oluşturuldu: 15 Ocak 14:00"
- gmail.list_messages → "Ali Yılmaz: Proje hakkında (2 dk önce)"
- gmail.send → "E-posta gönderildi: ali@test.com"
- Configurable: human_readable | raw_json

Usage::

    from bantz.tools.result_formatter import format_tool_result, OutputFormat
    formatted = format_tool_result("calendar.list_events", raw_result)
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


class OutputFormat(str, Enum):
    HUMAN_READABLE = "human_readable"
    RAW_JSON = "raw_json"


_MONTH_NAMES_TR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

_DAY_NAMES_TR = {
    0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe",
    4: "Cuma", 5: "Cumartesi", 6: "Pazar",
}


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _parse_iso(dt_str: str) -> Optional[datetime]:
    """Best-effort ISO datetime parse."""
    if not dt_str:
        return None
    try:
        # Handle "2025-01-15T14:00:00+03:00" and "2025-01-15T14:00:00"
        clean = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None


def _format_date_tr(dt: datetime) -> str:
    """Format as '15 Ocak Çarşamba'."""
    month = _MONTH_NAMES_TR.get(dt.month, str(dt.month))
    day_name = _DAY_NAMES_TR.get(dt.weekday(), "")
    return f"{dt.day} {month} {day_name}".strip()


def _format_time_tr(dt: datetime) -> str:
    """Format as 'HH:MM'."""
    return dt.strftime("%H:%M")


def _format_duration(minutes: int) -> str:
    """Format duration in Turkish: '1 saat', '30 dk', '1 saat 30 dk'."""
    if minutes <= 0:
        return ""
    hours = minutes // 60
    mins = minutes % 60
    parts = []
    if hours:
        parts.append(f"{hours} saat")
    if mins:
        parts.append(f"{mins} dk")
    return " ".join(parts)


def _calc_duration_minutes(start: datetime, end: datetime) -> int:
    delta = end - start
    return max(int(delta.total_seconds() / 60), 0)


# ─────────────────────────────────────────────────────────────────
# Calendar formatters
# ─────────────────────────────────────────────────────────────────


def _is_all_day(raw_start: Any) -> bool:
    """Check if the event start value represents an all-day event.

    Google Calendar API uses ``{"date": "YYYY-MM-DD"}`` for all-day
    events and ``{"dateTime": "..."}`` for timed events.
    A bare ``YYYY-MM-DD`` string (10 chars) is also treated as all-day.
    """
    if isinstance(raw_start, dict):
        # Has explicit 'date' key but no 'dateTime' → all-day
        return "date" in raw_start and "dateTime" not in raw_start
    if isinstance(raw_start, str):
        s = raw_start.strip()
        return len(s) == 10 and s[4:5] == "-" and s[7:8] == "-"
    return False


def format_calendar_list_events(result: Dict[str, Any]) -> str:
    """Format calendar.list_events result as Turkish summary.

    Input: {"events": [{"summary": ..., "start": ..., "end": ...}, ...]}
    Output: "14:00 Toplantı (1 saat) | 16:00 Doktor (30 dk)"
    """
    events = result.get("events") or []
    if not events:
        return "Takvimde etkinlik bulunamadı efendim."

    lines: List[str] = []
    for ev in events:
        summary = ev.get("summary") or ev.get("title") or "İsimsiz Etkinlik"
        raw_start = ev.get("start") or ev.get("start_time") or ""
        raw_end = ev.get("end") or ev.get("end_time") or ""

        # Detect all-day events before unwrapping the dict
        all_day = _is_all_day(raw_start)

        # Handle Google Calendar's dateTime / date nested format
        start_str = raw_start
        end_str = raw_end
        if isinstance(start_str, dict):
            start_str = start_str.get("dateTime") or start_str.get("date") or ""
        if isinstance(end_str, dict):
            end_str = end_str.get("dateTime") or end_str.get("date") or ""

        start_dt = _parse_iso(start_str)

        if all_day:
            # All-day event → show "Tüm gün" instead of "00:00"
            if start_dt:
                date_str = _format_date_tr(start_dt)
                lines.append(f"Tüm gün — {summary} ({date_str})")
            else:
                lines.append(f"Tüm gün — {summary}")
        elif start_dt:
            end_dt = _parse_iso(end_str)
            time_str = _format_time_tr(start_dt)
            dur_str = ""
            if end_dt:
                mins = _calc_duration_minutes(start_dt, end_dt)
                if mins > 0:
                    dur_str = f" ({_format_duration(mins)})"
            lines.append(f"{time_str} {summary}{dur_str}")
        else:
            lines.append(summary)

    count = len(lines)
    header = f"{count} etkinlik bulundu efendim:"
    body = " | ".join(lines)
    return f"{header} {body}"


def format_calendar_create_event(result: Dict[str, Any]) -> str:
    """Format calendar.create_event result."""
    if not result.get("ok", True):
        error = result.get("error", "Bilinmeyen hata")
        return f"Etkinlik oluşturulamadı efendim: {error}"

    summary = result.get("summary") or result.get("title") or "Etkinlik"
    start_str = result.get("start") or ""
    if isinstance(start_str, dict):
        start_str = start_str.get("dateTime") or start_str.get("date") or ""

    start_dt = _parse_iso(start_str)
    if start_dt:
        date_str = _format_date_tr(start_dt)
        time_str = _format_time_tr(start_dt)
        return f"'{summary}' oluşturuldu efendim: {date_str} {time_str}"

    return f"'{summary}' oluşturuldu efendim."


def format_calendar_delete_event(result: Dict[str, Any]) -> str:
    """Format calendar.delete_event result."""
    if not result.get("ok", True):
        return f"Etkinlik silinemedi efendim: {result.get('error', 'Bilinmeyen hata')}"
    summary = result.get("summary") or result.get("title") or "Etkinlik"
    return f"'{summary}' silindi efendim."


def format_calendar_update_event(result: Dict[str, Any]) -> str:
    """Format calendar.update_event result."""
    if not result.get("ok", True):
        return f"Etkinlik güncellenemedi efendim: {result.get('error', 'Bilinmeyen hata')}"
    summary = result.get("summary") or result.get("title") or "Etkinlik"
    return f"'{summary}' güncellendi efendim."


# ─────────────────────────────────────────────────────────────────
# Gmail formatters
# ─────────────────────────────────────────────────────────────────


def format_gmail_list_messages(result: Dict[str, Any]) -> str:
    """Format gmail.list_messages as Turkish summary.

    Input: {"messages": [{"from": ..., "subject": ..., "snippet": ...}, ...]}
    Output: "Ali Yılmaz: Proje hakkında | Mehmet: Toplantı notu"
    """
    messages = result.get("messages") or []
    if not messages:
        return "Gelen kutusunda mesaj bulunamadı efendim."

    lines: List[str] = []
    for msg in messages:
        sender = msg.get("from") or msg.get("sender") or "Bilinmeyen"
        # Extract just the name part from "Ali Yılmaz <ali@test.com>"
        if "<" in sender:
            sender = sender.split("<")[0].strip()
        subject = msg.get("subject") or "Konu yok"
        # Truncate long subjects
        if len(subject) > 40:
            subject = subject[:37] + "..."
        lines.append(f"{sender}: {subject}")

    count = len(lines)
    header = f"{count} mesaj bulundu efendim:"
    body = " | ".join(lines)
    return f"{header} {body}"


def format_gmail_send(result: Dict[str, Any]) -> str:
    """Format gmail.send result."""
    if not result.get("ok", True):
        return f"E-posta gönderilemedi efendim: {result.get('error', 'Bilinmeyen hata')}"
    to = result.get("to") or result.get("recipient") or ""
    return f"E-posta gönderildi efendim{': ' + to if to else ''}."


def format_gmail_get_message(result: Dict[str, Any]) -> str:
    """Format gmail.get_message result."""
    sender = result.get("from") or result.get("sender") or "Bilinmeyen"
    if "<" in sender:
        sender = sender.split("<")[0].strip()
    subject = result.get("subject") or "Konu yok"
    snippet = result.get("snippet") or result.get("body") or ""
    if len(snippet) > 100:
        snippet = snippet[:97] + "..."
    return f"Gönderen: {sender} | Konu: {subject} | {snippet}"


# ─────────────────────────────────────────────────────────────────
# System / time formatters
# ─────────────────────────────────────────────────────────────────


def format_time_now(result: Dict[str, Any]) -> str:
    """Format time.now result."""
    time_val = result.get("time") or result.get("now") or result.get("current_time") or ""
    date_val = result.get("date") or result.get("current_date") or ""
    if time_val and date_val:
        return f"Şu an {date_val} {time_val} efendim."
    if time_val:
        return f"Saat {time_val} efendim."
    return str(result)


# ─────────────────────────────────────────────────────────────────
# Additional formatters (Issue #1075)
# ─────────────────────────────────────────────────────────────────


def format_gmail_unread_count(result: Dict[str, Any]) -> str:
    """Format gmail.unread_count result."""
    count = result.get("count") or result.get("unread_count") or result.get("total") or 0
    if count == 0:
        return "Okunmamış mesaj yok efendim."
    return f"{count} okunmamış mesaj var efendim."


def format_gmail_smart_search(result: Dict[str, Any]) -> str:
    """Format gmail.smart_search result."""
    messages = result.get("messages") or result.get("results") or []
    if not messages:
        return "Arama sonucu bulunamadı efendim."

    lines: List[str] = []
    for msg in messages[:10]:
        sender = msg.get("from") or msg.get("sender") or "Bilinmeyen"
        if "<" in sender:
            sender = sender.split("<")[0].strip()
        subject = msg.get("subject") or "Konu yok"
        if len(subject) > 40:
            subject = subject[:37] + "..."
        lines.append(f"{sender}: {subject}")

    count = len(lines)
    header = f"{count} sonuç bulundu efendim:"
    body = " | ".join(lines)
    return f"{header} {body}"


def format_calendar_find_free_slots(result: Dict[str, Any]) -> str:
    """Format calendar.find_free_slots result."""
    slots = result.get("slots") or result.get("free_slots") or result.get("available") or []
    if not slots:
        return "Uygun boş zaman dilimi bulunamadı efendim."

    lines: List[str] = []
    for slot in slots[:8]:
        start_str = slot.get("start") or ""
        end_str = slot.get("end") or ""
        if isinstance(start_str, dict):
            start_str = start_str.get("dateTime") or start_str.get("date") or ""
        if isinstance(end_str, dict):
            end_str = end_str.get("dateTime") or end_str.get("date") or ""
        start_dt = _parse_iso(start_str)
        end_dt = _parse_iso(end_str)
        if start_dt and end_dt:
            dur = _calc_duration_minutes(start_dt, end_dt)
            lines.append(f"{_format_time_tr(start_dt)}-{_format_time_tr(end_dt)} ({_format_duration(dur)})")
        elif start_dt:
            lines.append(_format_time_tr(start_dt))
        else:
            lines.append(str(slot))

    count = len(lines)
    header = f"{count} boş zaman dilimi bulundu efendim:"
    body = " | ".join(lines)
    return f"{header} {body}"


def format_web_search(result: Dict[str, Any]) -> str:
    """Format web.search result."""
    results = result.get("results") or result.get("items") or result.get("hits") or []
    if not results:
        return "Arama sonucu bulunamadı efendim."

    lines: List[str] = []
    for item in results[:5]:
        title = item.get("title") or "Başlıksız"
        snippet = item.get("snippet") or item.get("description") or ""
        if len(title) > 50:
            title = title[:47] + "..."
        if snippet and len(snippet) > 60:
            snippet = snippet[:57] + "..."
        entry = title
        if snippet:
            entry += f" — {snippet}"
        lines.append(entry)

    return f"{len(lines)} sonuç bulundu efendim: " + " | ".join(lines)


def format_system_status(result: Dict[str, Any]) -> str:
    """Format system.status result."""
    status = result.get("status") or result.get("state") or "bilinmiyor"
    uptime = result.get("uptime") or ""
    version = result.get("version") or ""
    parts = [f"Sistem durumu: {status}"]
    if uptime:
        parts.append(f"çalışma süresi: {uptime}")
    if version:
        parts.append(f"versiyon: {version}")
    return ", ".join(parts) + " efendim."


# ─────────────────────────────────────────────────────────────────
# Formatter registry
# ─────────────────────────────────────────────────────────────────

_FORMATTERS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "calendar.list_events": format_calendar_list_events,
    "calendar.create_event": format_calendar_create_event,
    "calendar.delete_event": format_calendar_delete_event,
    "calendar.update_event": format_calendar_update_event,
    "calendar.find_free_slots": format_calendar_find_free_slots,
    "gmail.list_messages": format_gmail_list_messages,
    "gmail.send": format_gmail_send,
    "gmail.get_message": format_gmail_get_message,
    "gmail.unread_count": format_gmail_unread_count,
    "gmail.smart_search": format_gmail_smart_search,
    "web.search": format_web_search,
    "system.status": format_system_status,
    "time.now": format_time_now,
}


def format_tool_result(
    tool_name: str,
    result: Any,
    *,
    output_format: OutputFormat = OutputFormat.HUMAN_READABLE,
) -> Any:
    """
    Format a tool result for user consumption.

    Args:
        tool_name: The tool that produced the result.
        result: Raw tool result (usually dict).
        output_format: HUMAN_READABLE (Turkish text) or RAW_JSON (passthrough).

    Returns:
        Formatted string (human_readable) or original dict (raw_json).
    """
    if output_format == OutputFormat.RAW_JSON:
        return result

    if not isinstance(result, dict):
        return result

    # Check for error
    if result.get("ok") is False and "error" in result:
        error = result["error"]
        return f"İşlem başarısız oldu efendim: {error}"

    formatter = _FORMATTERS.get(tool_name)
    if formatter:
        try:
            return formatter(result)
        except Exception as exc:
            logger.warning("Formatter failed for %s: %s", tool_name, exc)
            return result

    return result


def get_supported_tools() -> List[str]:
    """Return tool names that have human-readable formatters."""
    return sorted(_FORMATTERS.keys())
