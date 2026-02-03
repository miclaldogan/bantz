from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Optional


_FIXED_OFFSET_TZ_RE = re.compile(r"^(UTC|GMT)\s*([+-])\s*(\d{1,2})(?::(\d{2}))?$", re.IGNORECASE)


@dataclass(frozen=True)
class CalendarEventRef:
    kind: str  # index | id
    index: Optional[int] = None
    event_id: Optional[str] = None
    summary: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None


@dataclass(frozen=True)
class CalendarIntent:
    type: str
    params: dict[str, Any]
    confidence: float
    missing: list[str]
    source_text: str
    event_ref: Optional[CalendarEventRef] = None


# Accept common Turkish time separators: 23:50, 23.50, 23,50, 23 50
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3])\s*[:., ]\s*([0-5]\d)\b")
_HASH_REF_RE = re.compile(r"#\s*(\d+)\b")


def parse_hhmm(text: str) -> Optional[str]:
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    try:
        hh = int(m.group(1))
        mm = int(m.group(2))
    except Exception:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def parse_duration_minutes(text: str) -> Optional[int]:
    t = (text or "").lower()
    m = re.search(r"\b(\d{1,3})\s*(dk|dakika)\b", t)
    if m:
        try:
            val = int(m.group(1))
            return val if 1 <= val <= 24 * 60 else None
        except Exception:
            return None
    if re.search(r"\b1\s*saat\b", t):
        return 60
    m = re.search(r"\b(\d{1,2})\s*saat\b", t)
    if m:
        try:
            val = int(m.group(1))
            mins = val * 60
            return mins if 1 <= mins <= 24 * 60 else None
        except Exception:
            return None
    return None


def parse_offset_minutes(text: str) -> Optional[int]:
    """Parse offsets like '1 saat ileri', '30 dk geri'."""
    t = (text or "").lower()
    sign = None
    if any(k in t for k in ["ileri", "sonra", "erte", "ertele"]):
        sign = 1
    if any(k in t for k in ["geri", "once", "önce"]):
        sign = -1
    if sign is None:
        return None

    m = re.search(r"\b(\d{1,3})\s*(dk|dakika)\b", t)
    if m:
        return sign * int(m.group(1))

    m = re.search(r"\b(\d{1,2})\s*saat\b", t)
    if m:
        return sign * (int(m.group(1)) * 60)

    if "1 saat" in t:
        return sign * 60

    return None


def parse_day_hint(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "bu hafta" in t:
        return "this_week"
    if "öbür gün" in t or "obur gun" in t:
        return "day_after_tomorrow"
    if "yarın" in t:
        return "tomorrow"
    if "bugün" in t:
        return "today"
    if "bu sabah" in t or "sabah" in t:
        return "morning"
    if "öğleden sonra" in t or "ogleden sonra" in t:
        return "afternoon"
    if "bu akşam" in t or "akşam" in t:
        return "evening"
    return None


def parse_hash_ref_index(text: str) -> Optional[int]:
    m = _HASH_REF_RE.search(text or "")
    if not m:
        return None
    try:
        idx = int(m.group(1))
        return idx if idx > 0 else None
    except Exception:
        return None


def iso_from_date_hhmm(*, date_iso: str, hhmm: str, offset: str) -> str:
    base = f"{date_iso}T{hhmm}:00{offset}"
    # Validate and normalize
    dt = datetime.fromisoformat(base)
    return dt.isoformat()


def _tzinfo_from_name(tz_name: str):
    name = str(tz_name or "").strip()
    if not name:
        raise ValueError("timezone_name_required")

    m = _FIXED_OFFSET_TZ_RE.match(name)
    if m:
        sign = 1 if m.group(2) == "+" else -1
        hours = int(m.group(3))
        minutes = int(m.group(4) or 0)
        if hours > 23 or minutes > 59:
            raise ValueError("invalid_utc_offset")
        delta = timedelta(hours=hours, minutes=minutes) * sign
        # Preserve a readable %Z in confirmations.
        label = f"{m.group(1).upper()}{m.group(2)}{hours:02d}:{minutes:02d}"
        return timezone(delta, name=label)

    from zoneinfo import ZoneInfo

    return ZoneInfo(name)


def iso_from_date_hhmm_in_timezone(*, date_iso: str, hhmm: str, tz_name: str) -> str:
    """Build an RFC3339 datetime string for a local wall-clock time in a timezone.

    This is used for multi-timezone event creation (Issue #167).
    """

    base = datetime.fromisoformat(f"{date_iso}T{hhmm}:00")
    tzinfo = _tzinfo_from_name(tz_name)
    dt = base.replace(tzinfo=tzinfo).replace(microsecond=0)
    return dt.isoformat()


def add_minutes(iso_dt: str, minutes: int) -> str:
    dt = datetime.fromisoformat(iso_dt)
    return (dt + timedelta(minutes=int(minutes))).isoformat()


def add_days_keep_time(iso_dt: str, days: int) -> str:
    dt = datetime.fromisoformat(iso_dt)
    return (dt + timedelta(days=int(days))).isoformat()


def build_intent(user_text: str) -> CalendarIntent:
    """Deterministic calendar intent builder (minimal v1).

    This is intentionally conservative: it focuses on clear create/move/cancel/list.
    Missing fields are returned via `missing`.
    """

    text = (user_text or "").strip()
    t = text.lower()

    day_hint = parse_day_hint(text)
    hhmm = parse_hhmm(text)
    dur = parse_duration_minutes(text)
    offset = parse_offset_minutes(text)
    ref_idx = parse_hash_ref_index(text)

    tz_name: Optional[str] = None
    try:
        from bantz.nlu.slots import extract_timezone

        tz_slot = extract_timezone(text)
        if tz_slot is not None:
            tz_name = str(tz_slot.iana_name or "").strip() or None
    except Exception:
        tz_name = None

    is_cancel = any(k in t for k in ["iptal", "sil", "kaldır", "kaldirin", "kaldırın"])
    # Treat "#2 ... al" as move when there's an explicit event ref.
    looks_like_take = bool(ref_idx) and bool(re.search(r"\b(al|alin|alın)\b", t))
    is_move = any(k in t for k in ["kaydır", "kaydir", "erte", "ertele", "ileri al", "geri al", "taşı", "tasi"]) or looks_like_take
    is_create = any(k in t for k in ["ekle", "koy", "planla", "ayarla", "oluştur", "olustur"])
    is_list = any(k in t for k in ["ne var", "planım", "planim", "takvim", "randevu", "etkinlik", "toplantı", "toplanti"]) and not (is_create or is_move or is_cancel)

    if is_cancel:
        missing: list[str] = []
        ref = CalendarEventRef(kind="index", index=ref_idx) if ref_idx else None
        if ref is None:
            missing.append("event_ref")
        return CalendarIntent(
            type="cancel_event",
            params={"day_hint": day_hint},
            confidence=0.9 if ref_idx else 0.7,
            missing=missing,
            source_text=text,
            event_ref=ref,
        )

    if is_move:
        missing = []
        ref = CalendarEventRef(kind="index", index=ref_idx) if ref_idx else None
        if ref is None:
            missing.append("event_ref")
        target_hhmm = hhmm
        # If user says "bu hafta" for a write, force clarification.
        if day_hint == "this_week":
            missing.append("day_hint")
        # Need either an offset ("1 saat ileri") OR a concrete target time ("yarın 09:30").
        if offset is None and not target_hhmm and day_hint not in {"tomorrow", "day_after_tomorrow"}:
            missing.append("offset_or_target")
        return CalendarIntent(
            type="move_event",
            params={"day_hint": day_hint, "offset_minutes": offset, "target_hhmm": target_hhmm},
            confidence=0.9 if ref_idx else 0.65,
            missing=missing,
            source_text=text,
            event_ref=ref,
        )

    if is_create:
        missing = []
        # If user says "bu hafta" for a write, force clarification.
        if day_hint == "this_week":
            missing.append("day_hint")
        if not hhmm:
            missing.append("start_time")
        if dur is None:
            missing.append("duration_minutes")
        # summary heuristic: remove common time phrases/verbs/filler and trim.
        summary = text
        summary = re.sub(_TIME_RE, "", summary)
        summary = re.sub(r"\b(\d{1,3})\s*(dk|dakika)\b", "", summary, flags=re.IGNORECASE)
        # Remove verb variations like "ekler misin", "koyar mısın", etc.
        summary = re.sub(r"\b(ekle\w*|koy\w*|planla\w*|ayarla\w*|oluştur\w*|olustur\w*)\b", "", summary, flags=re.IGNORECASE)
        summary = re.sub(r"\b(bugün|yarın|öbür\s*gün|bu\s*akşam|aksam|akşam|sabah|öğleden\s*sonra|ogleden\s*sonra)\b", "", summary, flags=re.IGNORECASE)
        summary = re.sub(r"\b(saat)\b", "", summary, flags=re.IGNORECASE)
        summary = re.sub(r"'\s*(ye|ya|e|a)\b", "", summary, flags=re.IGNORECASE)
        summary = re.sub(
            r"\b(dostum|lütfen|lutfen|rica|acaba|ya|misin|mısın|misiniz|mısınız|miyim|mıyım|mi|mı)\b",
            "",
            summary,
            flags=re.IGNORECASE,
        )
        summary = re.sub(r"\s+", " ", summary).strip(" -:\n\t")
        if not summary:
            missing.append("summary")
        return CalendarIntent(
            type="create_event",
            params={"day_hint": day_hint, "start_hhmm": hhmm, "duration_minutes": dur, "summary": summary, "timezone": tz_name},
            confidence=0.9 if (hhmm and (dur is not None) and summary) else 0.6,
            missing=missing,
            source_text=text,
        )

    # Default: list/query
    return CalendarIntent(
        type="list_events",
        params={"day_hint": day_hint},
        confidence=0.7 if day_hint else 0.55,
        missing=[],
        source_text=text,
    )
