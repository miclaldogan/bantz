from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
import unicodedata
from datetime import datetime
from datetime import datetime
from typing import Any, Protocol, Optional, Literal, Union

from bantz.core.events import EventBus, EventType, get_event_bus
from bantz.agent.tools import ToolRegistry
from bantz.voice_style import JarvisVoice
from bantz.brain.calendar_intent import (
    add_days_keep_time,
    add_minutes,
    build_intent,
    iso_from_date_hhmm,
    parse_day_hint,
    parse_duration_minutes,
    parse_hash_ref_index,
    parse_hhmm,
)
from bantz.planning.plan_draft import (
    apply_plan_edit_instruction,
    build_plan_draft_from_text,
    looks_like_planning_prompt,
    plan_draft_from_dict,
    plan_draft_to_dict,
)

logger = logging.getLogger(__name__)


_PENDING_ACTION_KEY = "_policy_pending_action"
_POLICY_CONFIRM_NOTE_KEY = "_policy_last_confirmation_note"
_PENDING_CHOICE_KEY = "_dialog_pending_choice"
_DIALOG_STATE_KEY = "_dialog_state"
_REPROMPT_COUNT_KEY = "_dialog_reprompt_count"

_CALENDAR_PENDING_INTENT_KEY = "_calendar_pending_intent"
_CALENDAR_LAST_EVENTS_KEY = "_calendar_last_events"

_TRACE_KEY = "_dialog_trace"
_DIALOG_SUMMARY_KEY = "_dialog_summary"

_PLANNING_PENDING_DRAFT_KEY = "_planning_pending_plan_draft"
_PLANNING_CONFIRMED_DRAFT_KEY = "_planning_confirmed_plan_draft"


def _render_plan_confirm_menu() -> str:
    return (
        "Planı onaylayayım mı?\n"
        "1) Onayla\n"
        "2) Değiştir (örn: 'şunu 30 dk yap')\n"
        "0) İptal"
    ).strip()


def _render_plan_apply_confirm(*, count: int) -> str:
    n = int(count) if isinstance(count, int) else 0
    n = max(0, min(50, n))
    if n <= 0:
        return "Planı takvime uygulayayım mı? (1/0)"
    if n == 1:
        return "1 etkinlik oluşturacağım. Uygulayayım mı? (1/0)"
    return f"{n} etkinlik oluşturacağım. Uygulayayım mı? (1/0)"


def _is_plan_accept(user_text: str) -> bool:
    t = _normalize_text_for_match(user_text)
    if not t:
        return False
    if t.strip() == "1":
        return True
    return any(w in t for w in ["onayla", "onaylıyorum", "tamam", "evet", "devam", "uygula"])


def _is_plan_cancel(user_text: str) -> bool:
    t = _normalize_text_for_match(user_text)
    if not t:
        return False
    if t.strip() == "0":
        return True
    return any(w in t for w in ["iptal", "vazgec", "vazgeç", "bosver", "boşver"])


def _plan_edit_instruction(user_text: str) -> Optional[str]:
    t = str(user_text or "").strip()
    if not t:
        return None
    nt = _normalize_text_for_match(t)
    if nt.strip() == "2":
        return ""
    # Explicit edit commands.
    for k in ["degistir", "değiştir", "duzenle", "düzenle", "revize", "guncelle", "güncelle"]:
        if k in nt:
            parts = re.split(r"[:\-]", t, maxsplit=1)
            if len(parts) == 2:
                return parts[1].strip()
            return ""
    # Implicit edit: includes a duration expression.
    if re.search(r"\b\d{1,3}\s*(dk|dakika|saat|sa)\b", nt):
        return t
    return None


def _action_type_from_tool_name(tool_name: str) -> str:
    """Map a tool name like 'calendar.create_event' -> 'create_event'."""
    t = str(tool_name or "").strip()
    if not t:
        return ""
    if "." in t:
        return t.split(".", 1)[1]
    return t


def _std_metadata(
    *,
    ctx: dict[str, Any],
    state: dict[str, Any],
    menu_id: Optional[str] = None,
    options: Optional[dict[str, str]] = None,
    action_type: Optional[str] = None,
    requires_confirmation: Optional[bool] = None,
    reprompt_for: Optional[str] = None,
) -> dict[str, Any]:
    """Stable metadata for tests/clients (persona-independent)."""

    meta: dict[str, Any] = {}

    trace = ctx.get("trace")
    if isinstance(trace, dict) and trace:
        # Short, structured, testable trace (never chain-of-thought).
        meta["trace"] = dict(trace)

    route = str(ctx.get("route") or "").strip()
    if route:
        meta["route"] = route

    dialog_state = str(state.get(_DIALOG_STATE_KEY) or "").strip()
    if dialog_state:
        meta["state"] = dialog_state

    mid = str(menu_id or "").strip()
    if mid:
        meta["menu_id"] = mid

    if isinstance(options, dict):
        meta["options"] = dict(options)

    at = str(action_type or "").strip()
    if at:
        meta["action_type"] = at

    if requires_confirmation is not None:
        meta["requires_confirmation"] = bool(requires_confirmation)

    rf = str(reprompt_for or "").strip()
    if rf:
        meta["reprompt_for"] = rf

    return meta


def _parse_menu_choice(user_text: str, *, allowed: set[str], default: str = "0") -> str:
    t = (user_text or "").strip()
    if not t:
        return default
    m = re.search(r"\b(\d+)\b", t)
    if not m:
        return default
    choice = m.group(1)
    return choice if choice in allowed else default


def _map_choice_from_text(*, menu_id: str, user_text: str) -> Optional[str]:
    """Map natural-language replies to menu choices.

    Jarvis UX rule: when a menu is pending, the user may answer with a short
    phrase instead of a number.
    """

    t = _normalize_text_for_match(user_text)
    mid = str(menu_id or "").strip()
    if not t or not mid:
        return None

    def has_any(*frags: str) -> bool:
        return any(f in t for f in frags)

    if mid == "smalltalk_stage1":
        if has_any("iptal", "vazgec", "bosver"):
            return "0"
        if has_any("dokunma", "elleme", "kalsin"):
            return "1"
        if has_any("hafiflet", "azalt", "kolaylastir"):
            return "2"
        return None

    if mid == "smalltalk_stage2":
        if has_any("iptal", "vazgec", "bosver"):
            return "0"
        if has_any("yarin kaydir", "yarina at", "erte", "ertele"):
            return "1"
        if has_any("kisalt", "60 dk", "1 saat", "sureyi azalt"):
            return "2"
        if has_any("bosluk", "uygun saat", "en erken"):
            return "3"
        return None

    if mid == "free_slots":
        if has_any("iptal", "vazgec", "bosver"):
            return "0"
        if has_any("60 dk", "1 saat", "sureyi 60", "sureyi altmis"):
            return "9"
        if has_any("bir", "ilk"):
            return "1"
        if has_any("iki", "ikinci"):
            return "2"
        if has_any("uc", "ucuncu"):
            return "3"
        return None

    if mid == "event_pick":
        if has_any("iptal", "vazgec", "bosver"):
            return "0"
        if has_any("bir", "ilk"):
            return "1"
        if has_any("iki", "ikinci"):
            return "2"
        if has_any("uc", "ucuncu"):
            return "3"
        return None

    if mid == "unknown":
        if has_any("iptal", "vazgec", "bosver"):
            return "0"
        # If the user already asks a calendar question, assume calendar.
        if has_any(
            "takvim",
            "ajanda",
            "plan",
            "program",
            "randevu",
            "etkinlik",
            "toplanti",
            "musait",
            "uygun",
            "bosluk",
            "bugun",
            "yarin",
            "aksam",
            "sabah",
        ):
            return "1"
        # Otherwise, common smalltalk openings.
        if has_any("nasil", "nasilsin", "naber", "selam", "merhaba"):
            return "2"
        return None

    return None


def _get_reprompt_count(state: dict[str, Any]) -> int:
    try:
        return int(state.get(_REPROMPT_COUNT_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def _render_reprompt(menu_id: str, seed: str = "default") -> str:
    """Gentle reprompt for unclear menu input (first attempt)."""
    return JarvisVoice.format_reprompt(menu_id, seed)


def _render_smalltalk_stage1(seed: str = "default") -> str:
    return JarvisVoice.format_stage1_menu(seed)


def _render_smalltalk_stage2(seed: str = "default") -> str:
    return JarvisVoice.format_stage2_menu(seed)


def _render_calendar_free_slots(
    *,
    result: dict[str, Any],
    tz_name: Optional[str],
    duration_minutes: int,
    seed: str = "default",
) -> str:
    if not isinstance(result, dict) or not result.get("ok"):
        return "Boşlukları şu an bulamadım. Tekrar deneyeyim mi?"

    slots = result.get("slots")
    if not isinstance(slots, list):
        slots = []

    if not slots:
        return "Bu aralıkta uygun boşluk görünmüyor."

    # Format slots as (start, end) tuples
    slot_times: list[tuple[str, str]] = []
    for s in slots[:3]:
        if not isinstance(s, dict):
            continue
        start = str(s.get("start") or "")
        end = str(s.get("end") or "")
        sh = _format_hhmm(start, tz_name=tz_name)
        eh = _format_hhmm(end, tz_name=tz_name)
        slot_times.append((sh, eh))

    return JarvisVoice.format_free_slots_menu(slot_times, duration_minutes, seed)


def _render_calendar_create_event_result(
    *,
    obs: dict[str, Any],
    tz_name: Optional[str],
    dry_run: bool,
    fallback_params: Optional[dict[str, Any]] = None,
) -> str:
    if not isinstance(obs, dict) or obs.get("ok") is not True:
        err = str(obs.get("error") or "unknown_error").strip()
        return f"Ekleyemedim: {err}"

    result = obs.get("result")
    if not isinstance(result, dict) or not result.get("ok"):
        return "Ekleme sonucu belirsiz."

    fb = fallback_params if isinstance(fallback_params, dict) else {}

    summary = str(result.get("summary") or fb.get("summary") or fb.get("title") or "(etkinlik)").strip() or "(etkinlik)"
    start = str(result.get("start") or fb.get("start") or "").strip()
    end = str(result.get("end") or fb.get("end") or "").strip()

    sh = _format_hhmm(start, tz_name=tz_name)
    eh = _format_hhmm(end, tz_name=tz_name)

    if dry_run or bool(result.get("dry_run")):
        return JarvisVoice.format_dry_run(summary, sh, eh)

    return JarvisVoice.format_event_added(summary, sh, eh)


def _render_calendar_apply_plan_draft_result(
    *,
    obs: dict[str, Any],
    tz_name: Optional[str],
) -> str:
    if not isinstance(obs, dict) or obs.get("ok") is not True:
        err = str(obs.get("error") or "unknown_error").strip()
        return f"Planı uygulayamadım: {err}"

    result = obs.get("result")
    if not isinstance(result, dict) or result.get("ok") is not True:
        err = str((result or {}).get("error") or "unknown_error").strip()
        return f"Planı uygulayamadım: {err}"

    dry_run = bool(result.get("dry_run"))
    events = result.get("events")
    if not isinstance(events, list):
        events = []

    if dry_run:
        lines: list[str] = []
        lines.append(f"Dry-run: {len(events)} etkinlik önerisi")
        for i, ev in enumerate([e for e in events if isinstance(e, dict)][:5], start=1):
            summary = str(ev.get("summary") or "(etkinlik)").strip() or "(etkinlik)"
            sh = _format_hhmm(str(ev.get("start") or ""), tz_name=tz_name)
            eh = _format_hhmm(str(ev.get("end") or ""), tz_name=tz_name)
            when = f"{sh}–{eh}" if sh and eh else ""
            lines.append(f"{i}. {when} | {summary}".strip(" |"))
        if len(events) > 5:
            lines.append(f"… (+{len(events) - 5} daha)")
        return "\n".join([l for l in lines if str(l).strip()]).strip()

    created_count = result.get("created_count")
    try:
        cc = int(created_count) if created_count is not None else 0
    except Exception:
        cc = 0
    if cc <= 0:
        return "Planı uyguladım, ama etkinlik oluşturulmadı."
    if cc == 1:
        return "Planı takvime uyguladım: 1 etkinlik oluşturuldu."
    return f"Planı takvime uyguladım: {cc} etkinlik oluşturuldu."


def _parse_user_confirmation(text: str) -> tuple[Optional[Literal["confirm", "deny"]], str]:
    """Parse a user reply to a confirmation prompt.

    Returns (decision, note). `note` is any trailing text after the confirm keyword,
    useful for "evet ama 3:45 olsun" style replies.
    """

    raw = (text or "").strip()
    t = raw.lower()
    if not t:
        return None, ""

    nt = _normalize_text_for_match(raw)
    # Robust handling for common typos/variants.
    if "onay" in nt:
        return "confirm", ""

    confirm_prefixes = [
        "1",
        "evet",
        "tamam",
        "tamamdır",
        "tamamdir",
        "olur",
        "peki",
        "yap",
        "ekle",
        "uygula",
        "onay",
        "onayla",
        "onaylıyorum",
        "onayliyorum",
        "hadi",
        "devam",
        "yes",
        "y",
        "ok",
        "okay",
    ]
    deny_prefixes = [
        "0",
        "hayır",
        "hayir",
        "iptal",
        "kalsın",
        "kalsin",
        "vazgeç",
        "vazgec",
        "şimdi değil",
        "simdi degil",
        "şimdi degil",
        "değil",
        "degil",
        "dur",
        "stop",
        "no",
        "n",
    ]

    for prefix in deny_prefixes:
        if t == prefix or t.startswith(prefix + " "):
            return "deny", ""

    for prefix in confirm_prefixes:
        if t == prefix or t.startswith(prefix + " "):
            note = raw[len(prefix) :].strip()
            note = note.lstrip(" ,.:;-—")
            return "confirm", note

    return None, ""


def _normalize_text_for_match(text: str) -> str:
    t = (text or "").lower().strip()
    # Normalize away combining marks (e.g. "İ" -> "i" + combining dot).
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    # Minimal TR folding to reduce false negatives.
    t = (
        t.replace("ç", "c")
        .replace("ğ", "g")
        .replace("ı", "i")
        .replace("ö", "o")
        .replace("ş", "s")
        .replace("ü", "u")
    )
    out = []
    for ch in t:
        if ch.isalnum() or ch.isspace():
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def _looks_like_user_echo(*, user_text: str, question: str) -> bool:
    u = _normalize_text_for_match(user_text)
    q = _normalize_text_for_match(question)
    if not u or not q:
        return False

    # Strong signal: the question contains the user's sentence verbatim-ish.
    if len(u) >= 12 and u in q:
        return True
    if len(q) >= 12 and q in u:
        return True

    u_words = [w for w in u.split() if w]
    q_words = [w for w in q.split() if w]
    if len(u_words) < 4:
        return False

    u_set = set(u_words)
    q_set = set(q_words)
    overlap = len(u_set & q_set) / max(1, len(u_set))
    return overlap >= 0.8


def _looks_like_role_confused_question(question: str) -> bool:
    q = _normalize_text_for_match(question)
    if not q:
        return False
    bad_fragments = [
        "sizin icin",
        "benim icin",
        "hangi zaman",
        "hangi slot",
        "slot",
        "ne oneriyorum",
    ]
    return any(frag in q for frag in bad_fragments)


def _role_sanitize_text(text: str) -> str:
    """Prevent common 1st-person role confusion from leaking to the user."""

    t = str(text or "")
    # Ordered replacements (more specific first).
    replacements = [
        ("planımda", "takviminizde"),
        ("takvimimde", "takviminizde"),
        ("benim takvimim", "takviminiz"),
        ("benim planım", "planınız"),
        ("takvimim", "takviminiz"),
        ("planım", "planınız"),
    ]
    for src, dst in replacements:
        t = t.replace(src, dst)
        t = t.replace(src.capitalize(), dst)
    return t


ALLOWED_TYPES: set[str] = {"SAY", "CALL_TOOL", "ASK_USER", "FAIL"}


def _coerce_action_dict(raw: Any) -> dict[str, Any]:
    """Hard validator/coercer for LLM actions.

    Keeps the loop safe even if the adapter leaks invalid objects.
    """

    fallback_say = {
        "type": "SAY",
        "text": "Efendim, tam anlayamadım. Tekrar eder misiniz?",
    }

    if isinstance(raw, str):
        s = raw.strip()
        if not (s.startswith("{") and s.endswith("}")):
            return fallback_say
        try:
            raw = json.loads(s)
        except Exception:
            return {
                "type": "SAY",
                "text": "Efendim, netleştirebilir misiniz? (1) Yarın bak (0) İptal",
            }

    if not isinstance(raw, dict):
        return fallback_say

    typ = str(raw.get("type") or "").strip().upper()
    if typ not in ALLOWED_TYPES:
        return {
            "type": "SAY",
            "text": "Efendim, netleştirebilir misiniz? (1) Yarın bak (0) İptal",
        }

    if typ == "SAY":
        txt = raw.get("text")
        if not isinstance(txt, str) or not txt.strip():
            return {
                "type": "SAY",
                "text": "Efendim, bir sorun oldu. Tekrar eder misiniz?",
            }
        return {"type": "SAY", "text": txt}

    if typ == "FAIL":
        err = raw.get("error")
        if not isinstance(err, str) or not err.strip():
            err = "unknown_error"
        return {"type": "FAIL", "error": err}

    if typ == "ASK_USER":
        q = raw.get("question")
        if not isinstance(q, str) or not q.strip():
            q = "Nasıl ilerleyelim efendim?"
        choices = raw.get("choices")
        if not isinstance(choices, list):
            choices = None
        default = raw.get("default")
        if not isinstance(default, str) or not default.strip():
            default = "0"
        out: dict[str, Any] = {"type": "ASK_USER", "question": q}
        if choices is not None:
            out["choices"] = choices
            out["default"] = default
        return out

    # CALL_TOOL
    name = raw.get("name")
    params = raw.get("params")
    if not isinstance(name, str) or not name.strip() or not isinstance(params, dict):
        return {
            "type": "SAY",
            "text": "Efendim, tool çağrısını anlayamadım. Tekrar deneyelim mi?",
        }
    return {"type": "CALL_TOOL", "name": name.strip(), "params": params}


def _render_ask_user(question: str, *, choices: Optional[list[dict[str, Any]]] = None, default: str = "0") -> str:
    q = str(question or "").strip() or "Nasıl ilerleyelim efendim?"
    if not choices:
        return q

    lines: list[str] = [q]
    rendered_any = False
    for c in choices[:3]:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        label = str(c.get("label") or "").strip()
        if not cid or not label:
            continue
        lines.append(f"- {cid}) {label}")
        rendered_any = True
    if rendered_any:
        lines.append(f"(Varsayılan: {default or '0'})")
    return "\n".join(lines)


def _detect_time_intent_simple(user_text: str) -> Optional[str]:
    t = _normalize_text_for_match(user_text)
    has_evening = "aksam" in t
    has_tomorrow = "yarin" in t
    has_morning = "sabah" in t
    has_today = "bugun" in t
    if has_evening and has_tomorrow:
        return "tomorrow"
    if has_evening:
        return "evening"
    if has_tomorrow:
        return "tomorrow"
    if has_morning:
        return "morning"
    if has_today:
        return "today"
    return None


def _format_hhmm(dt_str: str, *, tz_name: Optional[str] = None) -> str:
    s = str(dt_str or "").strip()
    if not s:
        return "?"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if tz_name:
            try:
                from zoneinfo import ZoneInfo

                dt = dt.astimezone(ZoneInfo(tz_name))
            except Exception:
                pass
        return dt.strftime("%H:%M")
    except Exception:
        return s


def _render_calendar_list_events(
    *,
    result: dict[str, Any],
    intent: Optional[str],
    tz_name: Optional[str],
) -> str:
    if not isinstance(result, dict) or not result.get("ok"):
        return "Takvimi şu an kontrol edemedim. Tekrar deneyeyim mi?"
    count = result.get("count")
    try:
        n = int(count)
    except Exception:
        n = 0

    if n <= 0:
        if intent == "evening":
            return "Bu akşam için plan görünmüyor."
        return "Bu aralıkta plan görünmüyor."

    events = result.get("events")
    if not isinstance(events, list):
        events = []

    # Format events as (start, end, summary) tuples
    event_tuples: list[tuple[str, str, str]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        summary = str(ev.get("summary") or "(etkinlik)").strip()
        start = ev.get("start")
        end = ev.get("end")
        sh = _format_hhmm(str(start or ""), tz_name=tz_name)
        eh = _format_hhmm(str(end or ""), tz_name=tz_name)
        event_tuples.append((sh, eh, summary))

    return JarvisVoice.format_list_events(n, event_tuples, intent)


_ROUTE_CALENDAR_QUERY = "calendar_query"
_ROUTE_CALENDAR_MODIFY = "calendar_modify"
_ROUTE_CALENDAR_CREATE = "calendar_create"
_ROUTE_CALENDAR_CANCEL = "calendar_cancel"
_ROUTE_SMALLTALK = "smalltalk"
_ROUTE_UNKNOWN = "unknown"


def _is_calendar_route(route: Optional[str]) -> bool:
    r = str(route or "").strip().lower()
    return r in {
        _ROUTE_CALENDAR_QUERY,
        _ROUTE_CALENDAR_MODIFY,
        _ROUTE_CALENDAR_CREATE,
        _ROUTE_CALENDAR_CANCEL,
    }


_CALENDAR_STRONG_KEYWORDS = {
    "takvim",
    "plan",
    "randevu",
    "etkinlik",
    "toplantı",
    "boşluk",
    "müsait",
    "uygun",
    "program",
    "ekle",
    "koy",
    "iptal",
    "sil",
    "taşı",
    "ertele",
}


def _calendar_route_from_text(user_text: str) -> str:
    t = str(user_text or "").lower()
    if any(k in t for k in ["iptal", "sil", "kaldır", "kaldirin", "kaldırın"]):
        return _ROUTE_CALENDAR_CANCEL
    if any(k in t for k in ["ekle", "koy", "planla", "ayarla", "oluştur", "olustur"]):
        return _ROUTE_CALENDAR_CREATE
    # "#2'yi yarın 09:30'a al" style: treat as modify.
    if "#" in t and re.search(r"\b(al|alin|alın)\b", t):
        return _ROUTE_CALENDAR_MODIFY
    if any(k in t for k in _CALENDAR_MODIFY_KEYWORDS):
        return _ROUTE_CALENDAR_MODIFY
    return _ROUTE_CALENDAR_QUERY


def _window_from_ctx(ctx: dict[str, Any], *, day_hint: Optional[str]) -> Optional[dict[str, Any]]:
    if day_hint == "today":
        w = ctx.get("today_window")
        return w if isinstance(w, dict) else None
    if day_hint == "day_after_tomorrow":
        w = ctx.get("day_after_tomorrow_window")
        return w if isinstance(w, dict) else None
    if day_hint == "tomorrow" or day_hint == "morning":
        w = ctx.get("tomorrow_window")
        if isinstance(w, dict):
            return w
        w = ctx.get("morning_tomorrow_window")
        return w if isinstance(w, dict) else None
    if day_hint == "afternoon":
        w = ctx.get("tomorrow_window")
        return w if isinstance(w, dict) else None
    if day_hint == "evening":
        w = ctx.get("evening_window")
        if isinstance(w, dict):
            return w
        w = ctx.get("today_window")
        return w if isinstance(w, dict) else None
    w = ctx.get("today_window")
    return w if isinstance(w, dict) else None


def _date_and_offset_from_window(window: Optional[dict[str, Any]]) -> tuple[Optional[str], str]:
    if not isinstance(window, dict):
        return None, "+00:00"
    tm = window.get("time_min")
    if not isinstance(tm, str) or len(tm) < 10:
        return None, "+00:00"
    date_iso = tm[:10]
    offset = "+00:00"
    if len(tm) >= 6 and ("+" in tm[-6:] or "-" in tm[-6:]):
        offset = tm[-6:]
    return date_iso, offset


def _render_event_pick_menu(events: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    options: dict[str, str] = {}
    lines = ["Hangisini kastettiniz?"]
    for i, ev in enumerate(events[:3], start=1):
        summary = str(ev.get("summary") or "(etkinlik)").strip()
        start = str(ev.get("start") or "").strip()
        end = str(ev.get("end") or "").strip()
        label = f"{summary}"
        if start and end:
            label = f"{start}–{end} | {summary}"
        options[str(i)] = label
        lines.append(f"{i}. {label}")
    options["0"] = "Vazgeç"
    lines.append("0. Vazgeç")
    return "\n".join(lines), options


def _pick_event_from_text(user_text: str, events: list[dict[str, Any]]) -> Optional[int]:
    """Best-effort match of a user utterance to one of the recent events.

    Returns a 0-based index into `events` when a single strong candidate exists.
    """

    if not isinstance(events, list) or not events:
        return None

    # 1) Explicit #N reference.
    try:
        ref = parse_hash_ref_index(user_text)
        if isinstance(ref, int) and ref > 0:
            idx = ref - 1
            if 0 <= idx < len(events):
                return idx
    except Exception:
        pass

    t = _normalize_text_for_match(user_text)
    if not t:
        return None

    # 0) Ordinal-only selection.
    if "ikinci" in t:
        return 1 if len(events) >= 2 else None
    if "ucuncu" in t:
        return 2 if len(events) >= 3 else None
    if "ilk" in t or "bir" in t:
        return 0 if len(events) >= 1 else None

    # 2) Time match (HH:MM) is a strong signal.
    hhmm = None
    try:
        hhmm = parse_hhmm(user_text)
    except Exception:
        hhmm = None

    best_idx: Optional[int] = None
    best_score = 0
    tied = False

    for i, ev in enumerate([e for e in events if isinstance(e, dict)]):
        score = 0
        summary = _normalize_text_for_match(str(ev.get("summary") or ""))
        if summary:
            # Token overlap from summary into user text.
            toks = [w for w in re.split(r"\s+", summary) if len(w) >= 4]
            score += sum(1 for w in toks if w in t)

        if hhmm:
            start = str(ev.get("start") or "")
            try:
                ev_hhmm = parse_hhmm(start)
            except Exception:
                ev_hhmm = None
            if ev_hhmm and ev_hhmm == hhmm:
                score += 5

        if score > best_score:
            best_score = score
            best_idx = i
            tied = False
        elif score == best_score and score != 0:
            tied = True

    if tied:
        return None
    if best_score >= 2 or best_score >= 5:
        return best_idx
    return None


_CALENDAR_MODIFY_KEYWORDS = {
    "tasi",
    "taşı",
    "degistir",
    "değiştir",
    "kisalt",
    "kısalt",
    "uzat",
    "yarina al",
    "yarına al",
    "iptal et",
    "sil",
    "kaldir",
    "kaldır",
}


_SMALLTALK_KEYWORDS = {
    "uykuluyum",
    "yorgunum",
    "moral",
    "canım",
    "sıkıldım",
    "bunaldım",
    "gitmek istemiyorum",
    "istemiyorum",
    "gidemeyeceğim",
    "hasta",
    "keyifsiz",
    "stres",
    "of",
    "nasılsın",
    "nasilsin",
}


def _cleanup_after_calendar_write(state: dict[str, Any]) -> None:
    """Reset dialog state after a completed calendar write.

    Next user turn should be treated as fresh: no pending menus, no calendar lock-in.
    """

    try:
        state.pop(_PENDING_CHOICE_KEY, None)
        state.pop(_PENDING_ACTION_KEY, None)
        state.pop(_CALENDAR_PENDING_INTENT_KEY, None)
        state.pop(_REPROMPT_COUNT_KEY, None)
        state.pop(_CALENDAR_SOFT_EXIT_COUNT_KEY, None)
        state[_DIALOG_STATE_KEY] = "IDLE"
        state["last_intent"] = None
        state["last_tool_used"] = None
    except Exception:
        pass


_CALENDAR_EXIT_KEYWORDS = {
    "bosver",
    "boşver",
    "vazgec",
    "vazgeç",
    "konu degistir",
    "konu değiştir",
    "sohbete don",
    "sohbete dön",
    "takvimi birak",
    "takvimi bırak",
    "takvimi kapat",
    "takvimi kapat",
    "takvimden cik",
    "takvimden çık",
}

_CALENDAR_SOFT_EXIT_PHRASES = {
    "tamam tamam",
    "peki",
    "neyse",
}

_CALENDAR_SOFT_EXIT_COUNT_KEY = "_calendar_soft_exit_count"


def _is_calendar_exit_phrase(user_text: str) -> bool:
    t = str(user_text or "").strip().lower()
    if not t:
        return False
    # Exact, short exits.
    if t in {"iptal", "iptal et"}:
        return True
    # Avoid hijacking real calendar cancels/moves like "Dersi iptal et" or "#2'yi iptal et".
    if t.startswith("iptal"):
        return False
    if any(k in t for k in _CALENDAR_EXIT_KEYWORDS):
        return True
    return False


def _is_calendar_soft_exit_phrase(user_text: str) -> bool:
    t = str(user_text or "").strip().lower()
    if not t:
        return False
    return t in _CALENDAR_SOFT_EXIT_PHRASES


def _has_smalltalk_clause(user_text: str) -> bool:
    t = str(user_text or "").strip().lower()
    if not t:
        return False
    return any(k in t for k in _SMALLTALK_KEYWORDS)


_TIME_HHMM_RE = re.compile(r"\b([01]?\d|2[0-3])\s*[:., ]\s*([0-5]\d)\b")


def _hard_lock_calendar_route(state: dict[str, Any]) -> Optional[str]:
    """Return a calendar route if dialog state implies we must stay in calendar.

    This is the deterministic ownership guarantee: pending intents/actions/menus
    must not fall back to smalltalk/unknown.
    """

    try:
        if isinstance(state.get(_CALENDAR_PENDING_INTENT_KEY), dict):
            return _ROUTE_CALENDAR_QUERY
        pending_action = state.get(_PENDING_ACTION_KEY)
        if isinstance(pending_action, dict):
            action = pending_action.get("action")
            tool_name = str((action or {}).get("name") or "").strip()
            if tool_name.startswith("calendar."):
                return _ROUTE_CALENDAR_QUERY
        pending_choice = state.get(_PENDING_CHOICE_KEY)
        if isinstance(pending_choice, dict):
            menu_id = str(pending_choice.get("menu_id") or "").strip()
            if menu_id in {"event_pick", "free_slots", "calendar_next"}:
                return _ROUTE_CALENDAR_QUERY
    except Exception:
        return None
    return None


def _detect_route(
    user_text: str,
    *,
    last_intent: Optional[str] = None,
    last_tool_used: Optional[str] = None,
) -> str:
    """Deterministic domain router.

    Minimal calendar triggers only.

    Smalltalk/unknown (and other grey areas) are intentionally NOT handled here;
    they should go to an LLM classifier when enabled.
    """

    t = str(user_text or "").strip().lower()
    if not t:
        return _ROUTE_UNKNOWN

    nt = _normalize_text_for_match(user_text)

    has_time = bool(_TIME_HHMM_RE.search(user_text or ""))
    # Include common time-of-day hints so queries like "bu akşam planım var mı"
    # can be routed deterministically without requiring an LLM.
    has_date = any(w in nt for w in ["bugun", "yarin", "obur gun", "aksam", "sabah"])
    has_time_or_date = bool(has_time or has_date)

    strong_nouns = {"takvim", "calendar", "ajanda"}
    soft_nouns = {"program", "plan"}
    has_calendar_object_strong = any(w in nt for w in strong_nouns)
    has_calendar_object_soft = any(w in nt for w in soft_nouns)

    create_verbs = {"ekle", "olustur", "oluştur", "koy", "ayarla", "planla", "hatirlat", "hatırlat"}
    cancel_verbs = {"iptal", "iptal et", "sil", "kaldir", "kaldır"}
    modify_verbs = {"tasi", "taşı", "kaydir", "ertele", "guncelle", "güncelle", "degistir", "değiştir"}
    query_verbs = {"bak", "listele", "goster", "göster"}

    has_create = any(v in nt for v in create_verbs)
    has_cancel = any(v in nt for v in cancel_verbs)
    has_modify = any(v in nt for v in modify_verbs)
    has_query = any(v in nt for v in query_verbs)
    has_any_cal_verb = bool(has_create or has_cancel or has_modify or has_query)

    has_calendar_context = bool(
        has_calendar_object_strong
        or (has_calendar_object_soft and has_time_or_date)
        or has_time_or_date
        or _is_calendar_route(last_intent)
        or (isinstance(last_tool_used, str) and last_tool_used.startswith("calendar."))
    )

    has_ref = bool(re.search(r"#\s*\d+\b", user_text or "")) or any(w in nt for w in ["birinci", "ikinci", "ucuncu"])
    has_ref_move_al = bool("#" in (user_text or "") and re.search(r"\b(al|alin)\b", nt))

    # Strong reference rule: (#N or ordinal) + (cancel/modify) => calendar.
    if has_ref and (has_cancel or has_modify or has_ref_move_al):
        if has_cancel:
            return _ROUTE_CALENDAR_CANCEL
        return _ROUTE_CALENDAR_MODIFY

    # Strong calendar objects imply calendar query.
    if has_calendar_object_strong and not has_any_cal_verb:
        return _ROUTE_CALENDAR_QUERY

    # Soft objects like "plan/program" require time/date or an explicit query verb.
    if has_calendar_object_soft and not has_any_cal_verb and has_time_or_date:
        return _ROUTE_CALENDAR_QUERY

    # Verb + calendar context => calendar.
    if has_any_cal_verb and has_calendar_context:
        if has_cancel:
            return _ROUTE_CALENDAR_CANCEL
        if has_modify:
            return _ROUTE_CALENDAR_MODIFY
        if has_create:
            return _ROUTE_CALENDAR_CREATE
        return _ROUTE_CALENDAR_QUERY

    return _ROUTE_UNKNOWN


def _render_smalltalk_menu(user_text: str) -> str:
    # Back-compat alias for earlier tests/usages.
    _ = user_text
    return _render_smalltalk_stage1()


def _render_unknown_menu(seed: str = "default") -> str:
    return JarvisVoice.format_unknown_menu(seed)


class LLMClient(Protocol):
    """Minimal adapter interface for BrainLoop.

    Implementations should return a JSON-serializable object that matches the
    BrainLoop protocol (see `LLMOutput`).
    """

    def complete_json(
        self, *, messages: list[dict[str, str]], schema_hint: str
    ) -> dict[str, Any]: ...


# ─────────────────────────────────────────────────────────────────
# LLM protocol (Issue #84)
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Say:
    type: Literal["SAY"]
    text: str


@dataclass(frozen=True)
class AskUser:
    type: Literal["ASK_USER"]
    question: str


@dataclass(frozen=True)
class Fail:
    type: Literal["FAIL"]
    error: str


@dataclass(frozen=True)
class CallTool:
    type: Literal["CALL_TOOL"]
    name: str
    params: dict[str, Any]


LLMOutput = Union[Say, AskUser, Fail, CallTool]


def _parse_llm_output(raw: Any) -> tuple[Optional[LLMOutput], str]:
    if not isinstance(raw, dict):
        return None, "llm_output_not_object"

    typ = str(raw.get("type") or "").strip().upper()
    if typ == "SAY":
        return Say(type="SAY", text=str(raw.get("text") or "").strip()), "ok"
    if typ == "ASK_USER":
        return AskUser(
            type="ASK_USER", question=str(raw.get("question") or "").strip()
        ), "ok"
    if typ == "FAIL":
        err = str(raw.get("error") or "unknown_error").strip()
        return Fail(type="FAIL", error=err), "ok"
    if typ == "CALL_TOOL":
        name = str(raw.get("name") or "").strip()
        params = raw.get("params")
        if not isinstance(params, dict):
            params = {}
        return CallTool(type="CALL_TOOL", name=name, params=params), "ok"

    return None, "unknown_type"


@dataclass(frozen=True)
class BrainLoopConfig:
    max_steps: int = 8
    debug: bool = False


@dataclass(frozen=True)
class BrainResult:
    kind: str  # say | ask_user | fail
    text: str
    steps_used: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BrainTranscriptTurn:
    step: int
    messages: list[dict[str, str]]
    schema: dict[str, Any]
    output: dict[str, Any]


def _extract_first_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from text.

    This is intentionally lightweight for the skeleton milestone (#84). The
    robust validator/repair loop is tracked in #86.
    """

    text = (text or "").strip()
    if not text:
        raise ValueError("empty_output")

    if text.startswith("{"):
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        raise ValueError("json_not_object")

    start = text.find("{")
    if start < 0:
        raise ValueError("no_json_object")

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : idx + 1]
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
                raise ValueError("json_not_object")

    raise ValueError("unbalanced_json")


class BrainLoop:
    """LLM-first brain loop.

    Minimal usage:

        tools = ToolRegistry()
        tools.register(Tool(name="add", description="...", parameters={...}, function=add))

        loop = BrainLoop(llm=my_llm_adapter, tools=tools, config=BrainLoopConfig(debug=True))
        result = loop.run(turn_input="2 ile 3 topla", session_context={...}, policy={...})

    Contract:
    - Uses `ToolRegistry` as the tool catalog and executor.
    - Emits minimal events (ACK/PROGRESS/FOUND/RESULT/QUESTION/ERROR) via EventBus.
    - Stops on SAY / ASK_USER / FAIL or on max_steps.

    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        event_bus: Optional[EventBus] = None,
        config: Optional[BrainLoopConfig] = None,
        router: Optional[Any] = None,
    ):
        self._llm = llm
        self._tools = tools
        self._events = event_bus or get_event_bus()
        self._config = config or BrainLoopConfig()
        self._router = router

    def run(
        self,
        *,
        turn_input: str,
        session_context: Optional[dict[str, Any]] = None,
        policy: Any = None,
        context: Optional[dict[str, Any]] = None,
    ) -> BrainResult:
        user_text = (turn_input or "").strip()
        if not user_text:
            # Early return - no dialog summary update needed for empty input
            return BrainResult(
                kind="fail", text="empty_input", steps_used=0, metadata={}
            )

        # State container (mutated to keep pending actions across turns).
        state: dict[str, Any] = context if isinstance(context, dict) else {}

        # Backward compatible alias: older callers may pass `context=`.
        ctx: dict[str, Any] = {}
        if isinstance(state, dict):
            ctx.update(state)
        if isinstance(session_context, dict):
            ctx.update(session_context)

        session_id = str(
            (ctx.get("session_id") or ctx.get("user") or "default")
        ).strip() or "default"

        def _emit_ack(text: str = "Anladım efendim.") -> None:
            try:
                self._events.publish(EventType.ACK.value, {"text": text}, source="brain")
            except Exception:
                pass

        def _emit_progress(*, tool_name: str) -> None:
            try:
                self._events.publish(
                    EventType.PROGRESS.value,
                    {"message": f"Tool çalıştırılıyor: {tool_name}"},
                    source="brain",
                )
            except Exception:
                pass

        def _emit_found(*, tool_name: str) -> None:
            try:
                self._events.publish(EventType.FOUND.value, {"tool": tool_name}, source="brain")
            except Exception:
                pass

        def _emit_summarizing(status: str) -> None:
            try:
                self._events.publish(EventType.SUMMARIZING.value, {"status": status}, source="brain")
            except Exception:
                pass

        def _ensure_trace() -> dict[str, Any]:
            existing = state.get(_TRACE_KEY) if isinstance(state, dict) else None
            trace: dict[str, Any] = existing if isinstance(existing, dict) else {}
            # Freeze user_goal across follow-ups when we have a pending calendar intent/action.
            frozen_goal: Optional[str] = None
            try:
                pending_intent = state.get(_CALENDAR_PENDING_INTENT_KEY) if isinstance(state, dict) else None
                if isinstance(pending_intent, dict):
                    frozen_goal = str(pending_intent.get("source_text") or "").strip() or None
            except Exception:
                frozen_goal = None
            if not frozen_goal:
                try:
                    pending_action = state.get(_PENDING_ACTION_KEY) if isinstance(state, dict) else None
                    if isinstance(pending_action, dict):
                        frozen_goal = str(pending_action.get("original_user_input") or "").strip() or None
                except Exception:
                    frozen_goal = None

            trace["user_goal"] = frozen_goal or str(user_text or "").strip()
            ctx["trace"] = trace
            if isinstance(state, dict):
                state[_TRACE_KEY] = trace
            return trace

        def _update_dialog_summary(
            *,
            user_input: str,
            result_kind: str,
            result_text: str,
            tool_calls: Optional[list[str]] = None,
        ) -> None:
            """Update rolling dialog summary (memory layer).
            
            Keeps last N turns in 1-2 sentence format.
            Format: "User asked X. Assistant did Y. Tool Z returned W."
            """
            try:
                if not isinstance(state, dict):
                    return

                # Get existing summary
                existing = state.get(_DIALOG_SUMMARY_KEY)
                summary_lines: list[str] = []
                if isinstance(existing, str) and existing.strip():
                    summary_lines = [line.strip() for line in existing.strip().split("\n") if line.strip()]

                # Build new turn summary
                turn_summary = f"User: {user_input[:80]}"
                if tool_calls:
                    turn_summary += f" | Tools: {', '.join(tool_calls)}"
                turn_summary += f" | Result: {result_kind}"

                # Keep last 3 turns
                summary_lines.append(turn_summary)
                summary_lines = summary_lines[-3:]

                state[_DIALOG_SUMMARY_KEY] = "\n".join(summary_lines)
            except Exception as e:
                logger.debug(f"Dialog summary update failed: {e}")

        def _route_reason_tokens(
            *,
            user_text_in: str,
            normalized_text: str,
            last_intent_in: Optional[str],
            last_tool_in: Optional[str],
        ) -> list[str]:
            reasons: list[str] = []
            if _TIME_HHMM_RE.search(user_text_in or ""):
                reasons.append("explicit_time")
            if any(w in normalized_text for w in ["bugun", "yarin", "obur gun"]):
                reasons.append("date_word")
            if any(w in normalized_text for w in ["takvim", "calendar", "ajanda"]):
                reasons.append("calendar_noun")
            if any(w in normalized_text for w in ["plan", "program"]):
                reasons.append("plan_noun")
            if any(w in normalized_text for w in ["ekle", "olustur", "koy", "ayarla", "planla", "hatirlat"]):
                reasons.append("create_verb")
            if any(w in normalized_text for w in ["iptal", "sil", "kaldir"]):
                reasons.append("cancel_verb")
            if any(w in normalized_text for w in ["tasi", "kaydir", "ertele", "guncelle", "degistir"]):
                reasons.append("modify_verb")
            if any(w in normalized_text for w in ["bak", "listele", "goster"]):
                reasons.append("query_verb")
            if bool(re.search(r"#\s*\d+\b", user_text_in or "")):
                reasons.append("ref_hash")
            if any(w in normalized_text for w in ["birinci", "ikinci", "ucuncu"]):
                reasons.append("ref_ordinal")
            if _is_calendar_route(last_intent_in):
                reasons.append("context_last_intent")
            if isinstance(last_tool_in, str) and last_tool_in.startswith("calendar."):
                reasons.append("context_last_tool")

            seen: set[str] = set()
            out: list[str] = []
            for r in reasons:
                if r not in seen:
                    seen.add(r)
                    out.append(r)
            return out

        # LLM Router: If router is configured, call it first for route classification + trace.
        router_output: Optional[Any] = None
        if self._router is not None:
            try:
                # Get dialog summary for context
                dialog_summary = state.get(_DIALOG_SUMMARY_KEY) if isinstance(state, dict) else None
                if not isinstance(dialog_summary, str):
                    dialog_summary = ""
                
                # Call router
                router_output = self._router.route(
                    user_input=user_text,
                    dialog_summary=dialog_summary,
                    session_context=ctx,
                )
                
                # If debug, log router decision
                if self._config.debug:
                    logger.info(f"[Router] route={router_output.route}, intent={router_output.calendar_intent}, "
                               f"confidence={router_output.confidence:.2f}, tool_plan={router_output.tool_plan}")
            except Exception as e:
                logger.warning(f"Router failed: {e}")
                router_output = None

        trace = _ensure_trace()
        
        # If router provided output, update trace with router decision
        if router_output is not None:
            trace["llm_router_route"] = router_output.route
            trace["llm_router_intent"] = router_output.calendar_intent
            trace["llm_router_confidence"] = router_output.confidence
            trace["llm_router_tool_plan"] = router_output.tool_plan
            trace["llm_router_slots"] = router_output.slots
            
            # If router provides assistant reply, store it for potential use
            if router_output.assistant_reply:
                trace["llm_router_reply"] = router_output.assistant_reply


        def _llm_route_classifier(user_text_in: str) -> tuple[str, str, float]:
            """Return (route, calendar_intent, confidence) using the LLM."""

            schema = {
                "route": "calendar|smalltalk|unknown",
                "calendar_intent": "create|modify|cancel|query|none",
                "confidence": 0.0,
            }
            try:
                prompt = (
                    "Sen bir router sınıflandırıcısısın. SADECE şu JSON'u döndür:\n"
                    + json.dumps(schema, ensure_ascii=False)
                    + "\n\nKurallar:\n"
                    + "- route sadece calendar|smalltalk|unknown\n"
                    + "- calendar_intent sadece create|modify|cancel|query|none\n"
                    + "- confidence 0.0-1.0 arası\n"
                    + "- Ek alan ekleme, açıklama yazma.\n"
                )
                raw = self._llm.complete_json(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": str(user_text_in or "").strip()},
                    ],
                    schema_hint=json.dumps(schema, ensure_ascii=False),
                )
            except Exception:
                return _ROUTE_UNKNOWN, "none", 0.0

            if not isinstance(raw, dict):
                return _ROUTE_UNKNOWN, "none", 0.0

            route_out = str(raw.get("route") or "").strip().lower()
            intent_out = str(raw.get("calendar_intent") or "").strip().lower()
            conf_raw = raw.get("confidence")

            try:
                conf = float(conf_raw)
            except Exception:
                conf = 0.0
            conf = max(0.0, min(1.0, conf))

            if route_out not in {"calendar", "smalltalk", "unknown"}:
                route_out = "unknown"
            if intent_out not in {"create", "modify", "cancel", "query", "none"}:
                intent_out = "none"

            if route_out == "smalltalk":
                return _ROUTE_SMALLTALK, "none", conf
            if route_out == "unknown":
                return _ROUTE_UNKNOWN, "none", conf

            # calendar
            if intent_out == "create":
                return _ROUTE_CALENDAR_CREATE, intent_out, conf
            if intent_out == "cancel":
                return _ROUTE_CALENDAR_CANCEL, intent_out, conf
            if intent_out == "modify":
                return _ROUTE_CALENDAR_MODIFY, intent_out, conf
            return _ROUTE_CALENDAR_QUERY, intent_out, conf

        def _llm_calendar_planner(user_text_in: str) -> tuple[dict[str, Any], str]:
            """Extract a calendar plan/slots for trace + deterministic slot-filling.

            This is intentionally NOT a tool-calling interface.
            """

            schema = {
                "intent": "create|modify|cancel|query|none",
                "slots": {
                    "day_hint": "today|tomorrow|day_after_tomorrow|this_week|none",
                    "start_time": "HH:MM|none",
                    "duration_min": 0,
                    "title": "",
                    "ref": "#N|ordinal|none",
                },
            }

            try:
                prompt = (
                    "Sen bir takvim istek çözücüsüsün. SADECE şu JSON'u döndür:\n"
                    + json.dumps(schema, ensure_ascii=False)
                    + "\n\nKurallar:\n"
                    + "- intent sadece create|modify|cancel|query|none\n"
                    + "- day_hint sadece today|tomorrow|day_after_tomorrow|this_week|none\n"
                    + "- start_time HH:MM formatında ya da none\n"
                    + "- duration_min sayı ya da 0\n"
                    + "- ref '#2' ya da 'ordinal' ya da 'none'\n"
                    + "- Ek alan ekleme, açıklama yazma.\n"
                )
                raw = self._llm.complete_json(
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": str(user_text_in or "").strip()},
                    ],
                    schema_hint=json.dumps(schema, ensure_ascii=False),
                )
            except Exception:
                return {}, "planner_llm_error"

            if not isinstance(raw, dict):
                return {}, "planner_not_object"

            intent_out = str(raw.get("intent") or "").strip().lower()
            if intent_out not in {"create", "modify", "cancel", "query", "none"}:
                intent_out = "none"

            slots_raw = raw.get("slots")
            slots = slots_raw if isinstance(slots_raw, dict) else {}

            day_hint = str(slots.get("day_hint") or "").strip().lower()
            if day_hint not in {"today", "tomorrow", "day_after_tomorrow", "this_week", "none"}:
                day_hint = "none"

            start_time = str(slots.get("start_time") or "").strip()
            if start_time.lower() == "none":
                start_time = ""
            if start_time and not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", start_time):
                start_time = ""

            dur_raw = slots.get("duration_min")
            try:
                duration_min = int(dur_raw)
            except Exception:
                duration_min = 0
            duration_min = max(0, min(24 * 60, duration_min))

            title = str(slots.get("title") or "").strip()
            ref = str(slots.get("ref") or "").strip()
            if ref.lower() in {"none", ""}:
                ref = "none"
            if ref != "none" and ref != "ordinal" and not re.match(r"^#\d+$", ref):
                ref = "none"

            plan = {
                "intent": intent_out,
                "slots": {
                    "day_hint": day_hint,
                    "start_time": start_time or "none",
                    "duration_min": duration_min,
                    "title": title,
                    "ref": ref,
                },
            }
            return plan, "ok"

        # Issue #116: PlanDraft confirmation/edit loop.
        # If a plan is pending, handle accept/edit/cancel deterministically
        # to avoid falling into unknown menus.
        pending_plan = state.get(_PLANNING_PENDING_DRAFT_KEY) if isinstance(state, dict) else None
        if isinstance(pending_plan, dict) and not looks_like_planning_prompt(user_text):
            raw_draft = pending_plan.get("draft")
            draft = plan_draft_from_dict(raw_draft) if isinstance(raw_draft, dict) else None

            if _is_plan_cancel(user_text):
                try:
                    if isinstance(state, dict):
                        state.pop(_PLANNING_PENDING_DRAFT_KEY, None)
                        state.pop(_PLANNING_CONFIRMED_DRAFT_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                except Exception:
                    pass
                _emit_ack()
                text = "Peki efendim, planı iptal ediyorum."
                try:
                    self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                except Exception:
                    pass
                return BrainResult(
                    kind="say",
                    text=text,
                    steps_used=0,
                    metadata=_std_metadata(ctx=ctx, state=state, action_type="plan_cancel", requires_confirmation=False),
                )

            if _is_plan_accept(user_text):
                try:
                    if isinstance(state, dict) and isinstance(raw_draft, dict):
                        state[_PLANNING_CONFIRMED_DRAFT_KEY] = dict(pending_plan)
                        state.pop(_PLANNING_PENDING_DRAFT_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                except Exception:
                    pass

                # Issue #117: On accept, run a dry-run apply preview (no writes),
                # then queue a pending apply action that requires explicit confirmation.
                tool_name = "calendar.apply_plan_draft"
                w_day_hint: Optional[str] = None
                try:
                    if draft is not None:
                        day = str(draft.day_hint or "").strip() or None
                        tod = str(draft.time_of_day or "").strip() or None
                        # Map {tomorrow+morning} -> 'morning' window, etc.
                        if (day == "tomorrow" and tod == "morning") or (day is None and tod == "morning"):
                            w_day_hint = "morning"
                        elif (day == "today" and tod == "evening") or (day is None and tod == "evening"):
                            w_day_hint = "evening"
                        else:
                            w_day_hint = day
                except Exception:
                    w_day_hint = None

                window = _window_from_ctx(ctx, day_hint=w_day_hint)
                time_min = str((window or {}).get("time_min") or "").strip()
                time_max = str((window or {}).get("time_max") or "").strip()
                if not (time_min and time_max):
                    try:
                        time_min = str(pending_plan.get("time_min") or "").strip()
                        time_max = str(pending_plan.get("time_max") or "").strip()
                    except Exception:
                        time_min = time_min
                        time_max = time_max

                _emit_ack()
                if not (isinstance(raw_draft, dict) and time_min and time_max):
                    text = "Tamam efendim. Ama plan penceresini belirleyemedim. (Bugün/yayın sabah gibi bir zaman aralığı söyleyin.)"
                    try:
                        self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                    except Exception:
                        pass
                    return BrainResult(
                        kind="say",
                        text=text,
                        steps_used=0,
                        metadata=_std_metadata(ctx=ctx, state=state, action_type="plan_accept", requires_confirmation=False),
                    )

                # Dry-run preview.
                obs: dict[str, Any] = {"tool": tool_name, "ok": False, "error": "tool_not_executable"}
                try:
                    tool = self._tools.get(tool_name)
                    if tool is not None and tool.function is not None:
                        params_preview = {
                            "draft": raw_draft,
                            "time_min": time_min,
                            "time_max": time_max,
                            "dry_run": True,
                            "calendar_id": "primary",
                        }
                        ok, why = self._tools.validate_call(tool_name, params_preview)
                        if ok:
                            _emit_progress(tool_name=tool_name)
                            result = tool.function(**params_preview)
                            _emit_found(tool_name=tool_name)
                            obs = {"tool": tool_name, "ok": True, "result": result}
                        else:
                            obs = {"tool": tool_name, "ok": False, "error": why}
                except Exception as e:
                    obs = {"tool": tool_name, "ok": False, "error": str(e)}

                tz_name = str(ctx.get("tz_name") or "") or None
                preview_text = _render_calendar_apply_plan_draft_result(obs=obs, tz_name=tz_name)
                preview_text = _role_sanitize_text(preview_text)
                try:
                    self._events.publish(EventType.RESULT.value, {"text": preview_text}, source="brain")
                except Exception:
                    pass

                # Queue the real apply as a pending confirmation (writes).
                apply_params = {
                    "draft": raw_draft,
                    "time_min": time_min,
                    "time_max": time_max,
                    "dry_run": False,
                    "calendar_id": "primary",
                }
                try:
                    if isinstance(state, dict):
                        state[_PENDING_ACTION_KEY] = {
                            "action": {"type": "CALL_TOOL", "name": tool_name, "params": apply_params},
                            "decision": {"risk_level": "MED"},
                            "original_user_input": "plan_apply",
                        }
                        state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                except Exception:
                    pass

                # Trace evidence: queued confirmation payload.
                try:
                    trace = _ensure_trace()
                    trace["intent"] = "calendar.apply_plan_draft"
                    trace["next_action"] = "ask_confirm_apply"
                    trace["pending_confirmation"] = {
                        "queued": True,
                        "tool": tool_name,
                        "time_min": time_min,
                        "time_max": time_max,
                        "dry_run": False,
                        "item_count": len(getattr(draft, "items", []) or []) if draft is not None else None,
                    }
                except Exception:
                    pass

                count = 0
                try:
                    if isinstance(obs, dict) and obs.get("ok") is True and isinstance(obs.get("result"), dict):
                        res = obs.get("result")
                        events = res.get("events")
                        if isinstance(events, list):
                            count = len(events)
                except Exception:
                    count = 0
                q = _render_plan_apply_confirm(count=count)
                try:
                    self._events.publish(EventType.QUESTION.value, {"question": q}, source="brain")
                except Exception:
                    pass

                # UI fallback: return both preview and prompt together.
                combined = (str(preview_text).rstrip() + "\n\n" + str(q).strip()).strip()
                return BrainResult(
                    kind="ask_user",
                    text=combined,
                    steps_used=0,
                    metadata=_std_metadata(ctx=ctx, state=state, menu_id="plan_apply", requires_confirmation=True),
                )

            instruction = _plan_edit_instruction(user_text)
            if instruction is not None and draft is not None:
                if instruction.strip():
                    draft = apply_plan_edit_instruction(draft, instruction)
                    try:
                        if isinstance(state, dict):
                            pending_plan["draft"] = plan_draft_to_dict(draft)
                            state[_PLANNING_PENDING_DRAFT_KEY] = pending_plan
                    except Exception:
                        pass
                else:
                    # Ask for the edit instruction.
                    _emit_ack()
                    q = "Ne değiştireyim efendim? Örn: 'şunu 30 dk yap'"
                    try:
                        self._events.publish(EventType.QUESTION.value, {"question": q}, source="brain")
                    except Exception:
                        pass
                    return BrainResult(
                        kind="ask_user",
                        text=q,
                        steps_used=0,
                        metadata=_std_metadata(ctx=ctx, state=state, menu_id="plan_edit", requires_confirmation=False),
                    )

            # Default: re-render the confirm menu + current preview.
            if draft is not None:
                preview = draft.render_preview_tr()
                # Keep trace slots updated for tests.
                try:
                    trace["intent"] = "calendar.plan_draft"
                    trace["slots"] = {
                        "plan_window": draft.plan_window(),
                        "item_count": len(draft.items) if isinstance(draft.items, list) else 0,
                    }
                    trace["missing"] = []
                    trace["next_action"] = "ask_confirm"
                    trace["safety"] = []
                except Exception:
                    pass
                _emit_ack()
                rendered = _render_plan_confirm_menu()
                try:
                    self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                except Exception:
                    pass
                preview = _role_sanitize_text(preview)
                try:
                    self._events.publish(EventType.RESULT.value, {"text": preview}, source="brain")
                except Exception:
                    pass
                return BrainResult(
                    kind="say",
                    text=preview,
                    steps_used=0,
                    metadata={
                        **_std_metadata(ctx=ctx, state=state, action_type="plan_draft", requires_confirmation=False),
                        "plan_window": draft.plan_window(),
                        "item_count": len(draft.items) if isinstance(draft.items, list) else 0,
                    },
                )

        # Deterministic state machine: confirmation > choice > router.
        # If we have a pending confirmation, do NOT consume pending choice menus.
        if (
            isinstance(ctx, dict)
            and bool(ctx.get("deterministic_render"))
            and isinstance(state, dict)
            and not isinstance(state.get(_PENDING_ACTION_KEY), dict)
        ):
            pending_choice = state.get(_PENDING_CHOICE_KEY)
            if isinstance(pending_choice, dict):
                # Global exit: user can always cancel out of a menu.
                if _is_calendar_exit_phrase(user_text):
                    try:
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state.pop(_CALENDAR_PENDING_INTENT_KEY, None)
                        state.pop(_REPROMPT_COUNT_KEY, None)
                        state.pop(_CALENDAR_SOFT_EXIT_COUNT_KEY, None)
                        state["last_intent"] = None
                        state["last_tool_used"] = None
                        state[_DIALOG_STATE_KEY] = "IDLE"
                    except Exception:
                        pass
                    text = "İptal ediyorum efendim."
                    try:
                        self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                    except Exception:
                        pass
                    return BrainResult(
                        kind="say",
                        text=text,
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="calendar_exit",
                            action_type="exit_calendar",
                            requires_confirmation=False,
                        ),
                    )

                menu_id = str(pending_choice.get("menu_id") or "").strip()
                default = str(pending_choice.get("default") or "0").strip() or "0"

                if menu_id == "smalltalk_stage1":
                    mapped = _map_choice_from_text(menu_id=menu_id, user_text=user_text)
                    parsed = _parse_menu_choice(user_text, allowed={"0", "1", "2"}, default="")
                    is_explicit = mapped is not None or parsed != ""
                    choice = mapped if isinstance(mapped, str) and mapped in {"0", "1", "2"} else (parsed if parsed in {"0", "1", "2"} else default)

                    # 2-stage reprompt: if unclear, first reprompt, then apply default
                    if not is_explicit:
                        count = _get_reprompt_count(state)
                        if count < 1:
                            state[_REPROMPT_COUNT_KEY] = count + 1
                            reprompt = _render_reprompt(menu_id)
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": reprompt}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=reprompt,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=menu_id,
                                    options=JarvisVoice.MENU_STAGE1,
                                    reprompt_for=menu_id,
                                ),
                            )
                        # second unclear → apply default (0=İptal)

                    state.pop(_PENDING_CHOICE_KEY, None)
                    state.pop(_REPROMPT_COUNT_KEY, None)
                    state[_DIALOG_STATE_KEY] = "IDLE"
                    if choice == "1":
                        return BrainResult(
                            kind="say",
                            text="Tamam, sadece hatırlatacağım.",
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="smalltalk_stage1",
                                options=JarvisVoice.MENU_STAGE1,
                            ),
                        )
                    if choice == "2":
                        state[_PENDING_CHOICE_KEY] = {"menu_id": "smalltalk_stage2", "default": "0"}
                        state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                        rendered = _render_smalltalk_stage2()
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=rendered,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="smalltalk_stage2",
                                options=JarvisVoice.MENU_STAGE2,
                            ),
                        )
                    return BrainResult(
                        kind="say",
                        text="Vazgeçtim.",
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="smalltalk_stage1",
                            options=JarvisVoice.MENU_STAGE1,
                        ),
                    )

                if menu_id == "smalltalk_stage2":
                    mapped = _map_choice_from_text(menu_id=menu_id, user_text=user_text)
                    parsed = _parse_menu_choice(user_text, allowed={"0", "1", "2", "3"}, default="")
                    is_explicit = mapped is not None or parsed != ""
                    choice = mapped if isinstance(mapped, str) and mapped in {"0", "1", "2", "3"} else (parsed if parsed in {"0", "1", "2", "3"} else default)

                    # 2-stage reprompt: if unclear, first reprompt, then apply default
                    if not is_explicit:
                        count = _get_reprompt_count(state)
                        if count < 1:
                            state[_REPROMPT_COUNT_KEY] = count + 1
                            reprompt = _render_reprompt(menu_id)
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": reprompt}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=reprompt,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=menu_id,
                                    options=JarvisVoice.MENU_STAGE2,
                                    reprompt_for=menu_id,
                                ),
                            )
                        # second unclear → apply default (0=İptal)

                    state.pop(_PENDING_CHOICE_KEY, None)
                    state.pop(_REPROMPT_COUNT_KEY, None)
                    state[_DIALOG_STATE_KEY] = "IDLE"
                    if choice == "0":
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="smalltalk_stage2",
                                options=JarvisVoice.MENU_STAGE2,
                            ),
                        )

                    # Route into a deterministic calendar read: find suitable free slots.
                    duration = 30
                    window = None
                    if choice == "2":
                        duration = 60
                        window = ctx.get("morning_tomorrow_window")
                    elif choice == "1":
                        window = ctx.get("morning_tomorrow_window")
                    elif choice == "3":
                        window = ctx.get("today_window")

                    if not isinstance(window, dict):
                        window = ctx.get("tomorrow_window") if isinstance(ctx.get("tomorrow_window"), dict) else None
                    if not isinstance(window, dict):
                        return BrainResult(kind="say", text="Uygun zaman aralığı belirleyemedim.", steps_used=0, metadata={})

                    time_min = window.get("time_min")
                    time_max = window.get("time_max")
                    if not isinstance(time_min, str) or not isinstance(time_max, str) or not time_min or not time_max:
                        return BrainResult(kind="say", text="Zaman aralığı eksik.", steps_used=0, metadata={})

                    tool = self._tools.get("calendar.find_free_slots")
                    if tool is None or tool.function is None:
                        return BrainResult(kind="say", text="Boşluk arama aracı hazır değil.", steps_used=0, metadata={})

                    try:
                        result = tool.function(
                            time_min=time_min,
                            time_max=time_max,
                            duration_minutes=int(duration),
                            suggestions=3,
                            preferred_start="07:30",
                            preferred_end="22:30",
                        )
                    except Exception as e:
                        return BrainResult(kind="say", text=f"Boşluk ararken hata: {e}", steps_used=0, metadata={})

                    tz_name = str(ctx.get("tz_name") or "") or None
                    rendered = _render_calendar_free_slots(result=result if isinstance(result, dict) else {"ok": False}, tz_name=tz_name, duration_minutes=int(duration))
                    # Save pending slots menu for follow-up selection.
                    slots = []
                    if isinstance(result, dict) and isinstance(result.get("slots"), list):
                        slots = [s for s in result.get("slots") if isinstance(s, dict)]
                    state[_PENDING_CHOICE_KEY] = {
                        "menu_id": "free_slots",
                        "default": "0",
                        "duration": int(duration),
                        "time_min": time_min,
                        "time_max": time_max,
                        "slots": slots[:3],
                    }
                    state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                    try:
                        self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                    except Exception:
                        pass
                    options: dict[str, str] = {"9": JarvisVoice.MENU_FREE_SLOTS["9"], "0": JarvisVoice.MENU_FREE_SLOTS["0"]}
                    try:
                        for idx, s in enumerate(slots[:3], start=1):
                            st = str(s.get("start") or "").strip()
                            en = str(s.get("end") or "").strip()
                            if st and en:
                                options[str(idx)] = f"{st}–{en}"
                    except Exception:
                        pass
                    return BrainResult(
                        kind="ask_user",
                        text=rendered,
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="free_slots",
                            options=options,
                        ),
                    )

                if menu_id == "free_slots":
                    # Slot selection -> optional duration toggle or create_event confirmation.
                    allowed = {"0", "1", "2", "3", "9"}
                    mapped = _map_choice_from_text(menu_id=menu_id, user_text=user_text)
                    parsed = _parse_menu_choice(user_text, allowed=allowed, default="")
                    is_explicit = mapped is not None or parsed != ""
                    choice = mapped if isinstance(mapped, str) and mapped in allowed else (parsed if parsed in allowed else default)

                    # 2-stage reprompt: if unclear, first reprompt, then apply default
                    if not is_explicit:
                        count = _get_reprompt_count(state)
                        if count < 1:
                            state[_REPROMPT_COUNT_KEY] = count + 1
                            reprompt = _render_reprompt(menu_id)
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": reprompt}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=reprompt,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=menu_id,
                                    options=JarvisVoice.MENU_FREE_SLOTS,
                                    reprompt_for=menu_id,
                                ),
                            )
                        # second unclear → apply default (0=İptal)

                    state.pop(_REPROMPT_COUNT_KEY, None)
                    time_min = pending_choice.get("time_min")
                    time_max = pending_choice.get("time_max")
                    slots = pending_choice.get("slots")
                    if not isinstance(time_min, str) or not isinstance(time_max, str):
                        state.pop(_PENDING_CHOICE_KEY, None)
                        return BrainResult(kind="say", text="Boşluk menüsü bağlamı kaybolmuş.", steps_used=0, metadata={})
                    if not isinstance(slots, list):
                        slots = []

                    if choice == "0":
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="free_slots",
                                options=JarvisVoice.MENU_FREE_SLOTS,
                            ),
                        )

                    if choice == "9":
                        # Re-run free slots with 60 minutes.
                        tool = self._tools.get("calendar.find_free_slots")
                        if tool is None or tool.function is None:
                            return BrainResult(kind="say", text="Boşluk arama aracı hazır değil.", steps_used=0, metadata={})
                        try:
                            result = tool.function(
                                time_min=time_min,
                                time_max=time_max,
                                duration_minutes=60,
                                suggestions=3,
                                preferred_start="07:30",
                                preferred_end="22:30",
                            )
                        except Exception as e:
                            return BrainResult(kind="say", text=f"Boşluk ararken hata: {e}", steps_used=0, metadata={})
                        tz_name = str(ctx.get("tz_name") or "") or None
                        rendered = _render_calendar_free_slots(result=result if isinstance(result, dict) else {"ok": False}, tz_name=tz_name, duration_minutes=60)
                        new_slots = []
                        if isinstance(result, dict) and isinstance(result.get("slots"), list):
                            new_slots = [s for s in result.get("slots") if isinstance(s, dict)]
                        state[_PENDING_CHOICE_KEY] = {
                            "menu_id": "free_slots",
                            "default": "0",
                            "duration": 60,
                            "time_min": time_min,
                            "time_max": time_max,
                            "slots": new_slots[:3],
                        }
                        state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                        except Exception:
                            pass
                        options: dict[str, str] = {"9": JarvisVoice.MENU_FREE_SLOTS["9"], "0": JarvisVoice.MENU_FREE_SLOTS["0"]}
                        try:
                            if isinstance(new_slots, list):
                                for idx, s in enumerate(new_slots[:3], start=1):
                                    st = str(s.get("start") or "").strip()
                                    en = str(s.get("end") or "").strip()
                                    if st and en:
                                        options[str(idx)] = f"{st}–{en}"
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=rendered,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="free_slots",
                                options=options,
                            ),
                        )

                    # Slot picked -> prepare a create_event confirmation (never write without explicit confirm).
                    idx = int(choice) - 1
                    if idx < 0 or idx >= len(slots):
                        # Invalid index -> default cancel.
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="free_slots",
                                options=JarvisVoice.MENU_FREE_SLOTS,
                            ),
                        )
                    slot = slots[idx] if isinstance(slots[idx], dict) else {}
                    start = str(slot.get("start") or "").strip()
                    end = str(slot.get("end") or "").strip()
                    if not start:
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                        return BrainResult(kind="say", text="Seçilen boşluk geçersiz.", steps_used=0, metadata={})

                    # Clear pending choice, move into pending confirmation.
                    state.pop(_PENDING_CHOICE_KEY, None)
                    state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                    pending_action = {"type": "CALL_TOOL", "name": "calendar.create_event", "params": {"summary": "Mola", "start": start, "end": end}}
                    try:
                        state[_PENDING_ACTION_KEY] = {
                            "action": pending_action,
                            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
                            "original_user_input": user_text,
                        }
                    except Exception:
                        pass

                    tz_name = str(ctx.get("tz_name") or "") or None
                    sh = _format_hhmm(start, tz_name=tz_name)
                    eh = _format_hhmm(end, tz_name=tz_name)
                    prompt = JarvisVoice.format_confirmation("Mola", sh, eh)
                    try:
                        self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                    except Exception:
                        pass
                    return BrainResult(
                        kind="ask_user",
                        text=prompt,
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="pending_confirmation",
                            action_type="create_event",
                            requires_confirmation=True,
                        ),
                    )

                if menu_id == "event_pick":
                    allowed = {"0", "1", "2", "3"}
                    mapped = _map_choice_from_text(menu_id=menu_id, user_text=user_text)
                    parsed = _parse_menu_choice(user_text, allowed=allowed, default="")
                    is_explicit = mapped is not None or parsed != ""
                    choice = mapped if isinstance(mapped, str) and mapped in allowed else (parsed if parsed in allowed else default)

                    if not is_explicit:
                        count = _get_reprompt_count(state)
                        if count < 1:
                            state[_REPROMPT_COUNT_KEY] = count + 1
                            reprompt = _render_reprompt(menu_id)
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": reprompt}, source="brain")
                            except Exception:
                                pass
                            opts = pending_choice.get("options")
                            return BrainResult(
                                kind="ask_user",
                                text=reprompt,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=menu_id,
                                    options=opts if isinstance(opts, dict) else None,
                                    reprompt_for=menu_id,
                                ),
                            )
                        # second unclear -> default

                    state.pop(_REPROMPT_COUNT_KEY, None)
                    events = pending_choice.get("events")
                    if not isinstance(events, list):
                        events = []
                    events = [e for e in events if isinstance(e, dict)]

                    if choice == "0":
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(ctx=ctx, state=state, menu_id="event_pick"),
                        )

                    idx = int(choice) - 1
                    if idx < 0 or idx >= len(events):
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(ctx=ctx, state=state, menu_id="event_pick"),
                        )

                    ev = events[idx]
                    ev_id = str(ev.get("id") or "").strip()
                    if not ev_id:
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "IDLE"
                        return BrainResult(kind="say", text="Etkinlik kimliğini bulamadım.", steps_used=0, metadata={})

                    op = str(pending_choice.get("op") or "").strip()
                    params = pending_choice.get("params")
                    if not isinstance(params, dict):
                        params = {}

                    tz_name = str(ctx.get("tz_name") or "") or None
                    summary = str(ev.get("summary") or "(etkinlik)").strip()
                    start = str(ev.get("start") or "").strip()
                    end = str(ev.get("end") or "").strip()

                    if op == "cancel_event":
                        sh = _format_hhmm(start, tz_name=tz_name) if start else ""
                        eh = _format_hhmm(end, tz_name=tz_name) if end else ""
                        preview = f"{sh}–{eh} | {summary}" if sh and eh else summary
                        prompt = f"\"{preview}\" iptal edeyim mi? (1/0)"
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                        try:
                            state[_PENDING_ACTION_KEY] = {
                                "action": {"type": "CALL_TOOL", "name": "calendar.delete_event", "params": {"event_id": ev_id}},
                                "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
                                "original_user_input": user_text,
                            }
                        except Exception:
                            pass
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=prompt,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="pending_confirmation",
                                action_type="delete_event",
                                requires_confirmation=True,
                            ),
                        )

                    if op == "move_event":
                        offset_minutes = params.get("offset_minutes")
                        day_hint = params.get("day_hint")
                        if offset_minutes is None and str(day_hint or "") != "tomorrow":
                            # Keep the intent pending; ask for offset.
                            state.pop(_PENDING_CHOICE_KEY, None)
                            q = "Ne kadar kaydırayım efendim? (örn. 30 dk ileri / 1 saat geri / yarına al)"
                            try:
                                state[_CALENDAR_PENDING_INTENT_KEY] = {
                                    "type": "move_event",
                                    "source_text": user_text,
                                    "missing": ["offset_or_target"],
                                }
                            except Exception:
                                pass
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": q}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=q,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id="calendar_slot_fill",
                                    action_type="move_event",
                                    requires_confirmation=True,
                                ),
                            )
                        if not start or not end:
                            state.pop(_PENDING_CHOICE_KEY, None)
                            state[_DIALOG_STATE_KEY] = "IDLE"
                            return BrainResult(kind="say", text="Etkinliğin saat bilgisi eksik.", steps_used=0, metadata={})
                        try:
                            if offset_minutes is not None:
                                off = int(offset_minutes)
                                new_start = add_minutes(start, off)
                                new_end = add_minutes(end, off)
                            else:
                                new_start = add_days_keep_time(start, 1)
                                new_end = add_days_keep_time(end, 1)
                        except Exception:
                            state.pop(_PENDING_CHOICE_KEY, None)
                            state[_DIALOG_STATE_KEY] = "IDLE"
                            return BrainResult(kind="say", text="Yeni zamanı hesaplayamadım.", steps_used=0, metadata={})

                        osh = _format_hhmm(start, tz_name=tz_name)
                        oeh = _format_hhmm(end, tz_name=tz_name)
                        nsh = _format_hhmm(new_start, tz_name=tz_name)
                        neh = _format_hhmm(new_end, tz_name=tz_name)
                        prompt = f"\"{summary}\" etkinliğini {osh}–{oeh} → {nsh}–{neh} olarak taşıyayım mı? (1/0)"
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                        try:
                            state[_PENDING_ACTION_KEY] = {
                                "action": {"type": "CALL_TOOL", "name": "calendar.update_event", "params": {"event_id": ev_id, "start": new_start, "end": new_end}},
                                "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
                                "original_user_input": user_text,
                            }
                        except Exception:
                            pass
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=prompt,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="pending_confirmation",
                                action_type="update_event",
                                requires_confirmation=True,
                            ),
                        )

                    # Unknown op -> cancel.
                    state.pop(_PENDING_CHOICE_KEY, None)
                    state[_DIALOG_STATE_KEY] = "IDLE"
                    return BrainResult(kind="say", text="Vazgeçtim.", steps_used=0, metadata=_std_metadata(ctx=ctx, state=state, menu_id="event_pick"))

                if menu_id == "calendar_next":
                    allowed = {"0", "1", "2"}
                    parsed = _parse_menu_choice(user_text, allowed=allowed, default="")
                    is_explicit = parsed != ""
                    choice = parsed if parsed in allowed else default

                    if not is_explicit:
                        count = _get_reprompt_count(state)
                        if count < 1:
                            state[_REPROMPT_COUNT_KEY] = count + 1
                            reprompt = _render_reprompt(menu_id)
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": reprompt}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=reprompt,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=menu_id,
                                    options={"1": "Yarın bak", "2": "Sabah için boşluk ara", "0": "İptal"},
                                    reprompt_for=menu_id,
                                ),
                            )
                        # second unclear -> default

                    state.pop(_REPROMPT_COUNT_KEY, None)
                    state.pop(_PENDING_CHOICE_KEY, None)
                    state[_DIALOG_STATE_KEY] = "IDLE"

                    if choice == "0":
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(ctx=ctx, state=state, menu_id="calendar_next"),
                        )

                    if choice == "1":
                        window = ctx.get("tomorrow_window") if isinstance(ctx, dict) else None
                        if not isinstance(window, dict):
                            return BrainResult(kind="say", text="Yarın penceresini bulamadım.", steps_used=0, metadata={})
                        time_min = window.get("time_min")
                        time_max = window.get("time_max")
                        if not isinstance(time_min, str) or not isinstance(time_max, str):
                            return BrainResult(kind="say", text="Yarın aralığı geçersiz.", steps_used=0, metadata={})

                        tool = self._tools.get("calendar.list_events")
                        if tool is None or tool.function is None:
                            return BrainResult(kind="say", text="Takvim aracına erişemiyorum.", steps_used=0, metadata={})
                        try:
                            _emit_ack()
                            _emit_progress(tool_name="calendar.list_events")
                            res = tool.function(time_min=time_min, time_max=time_max)
                            _emit_found(tool_name="calendar.list_events")
                        except Exception:
                            res = {"ok": False}
                        tz_name = str(ctx.get("tz_name") or "") or None
                        text = _render_calendar_list_events(result=res if isinstance(res, dict) else {"ok": False}, intent="tomorrow", tz_name=tz_name)
                        text = _role_sanitize_text(text)
                        _emit_summarizing("started")
                        # Save recent events for deterministic disambiguation.
                        try:
                            evs = res.get("events") if isinstance(res, dict) and isinstance(res.get("events"), list) else []
                            evs = [e for e in evs if isinstance(e, dict)]
                            if isinstance(state, dict):
                                state[_CALENDAR_LAST_EVENTS_KEY] = evs[:10]
                                state["last_tool_used"] = "calendar.list_events"
                                state[_DIALOG_STATE_KEY] = "AFTER_CALENDAR_STATUS"
                        except Exception:
                            pass
                        try:
                            self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                        except Exception:
                            pass
                        _emit_summarizing("complete")
                        return BrainResult(
                            kind="say",
                            text=text,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="calendar_next",
                                action_type="list_events",
                                requires_confirmation=False,
                            ),
                        )

                    # choice == "2": morning free slots
                    window = ctx.get("morning_tomorrow_window") if isinstance(ctx, dict) else None
                    if not isinstance(window, dict):
                        return BrainResult(kind="say", text="Sabah penceresini bulamadım.", steps_used=0, metadata={})
                    time_min = window.get("time_min")
                    time_max = window.get("time_max")
                    if not isinstance(time_min, str) or not isinstance(time_max, str):
                        return BrainResult(kind="say", text="Sabah aralığı geçersiz.", steps_used=0, metadata={})

                    tool = self._tools.get("calendar.find_free_slots")
                    if tool is None or tool.function is None:
                        return BrainResult(kind="say", text="Boşluk arama aracına erişemiyorum.", steps_used=0, metadata={})

                    dur = 30
                    try:
                        dur = int(((ctx.get("human_hours") or {}) if isinstance(ctx, dict) else {}).get("duration_minutes") or 30)
                    except Exception:
                        dur = 30

                    params = {"time_min": time_min, "time_max": time_max, "duration_minutes": dur}
                    try:
                        _emit_ack()
                        _emit_progress(tool_name="calendar.find_free_slots")
                        res = tool.function(**params)
                        _emit_found(tool_name="calendar.find_free_slots")
                    except Exception:
                        res = {"ok": False}

                    tz_name = str(ctx.get("tz_name") or "") or None
                    rendered = _render_calendar_free_slots(result=res if isinstance(res, dict) else {"ok": False}, tz_name=tz_name, duration_minutes=dur)
                    rendered = _role_sanitize_text(rendered)

                    # Save pending slots menu for follow-up selection.
                    slots = []
                    if isinstance(res, dict) and isinstance(res.get("slots"), list):
                        slots = [s for s in res.get("slots") if isinstance(s, dict)]
                    try:
                        if isinstance(state, dict):
                            state[_PENDING_CHOICE_KEY] = {
                                "menu_id": "free_slots",
                                "default": "0",
                                "duration": dur,
                                "time_min": time_min,
                                "time_max": time_max,
                                "slots": slots[:3],
                            }
                            state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                            state["last_tool_used"] = "calendar.find_free_slots"
                    except Exception:
                        pass
                    try:
                        self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                    except Exception:
                        pass
                    options: dict[str, str] = {"9": JarvisVoice.MENU_FREE_SLOTS["9"], "0": JarvisVoice.MENU_FREE_SLOTS["0"]}
                    try:
                        for idx, s in enumerate(slots[:3], start=1):
                            st = str(s.get("start") or "").strip()
                            en = str(s.get("end") or "").strip()
                            if st and en:
                                options[str(idx)] = f"{st}–{en}"
                    except Exception:
                        pass
                    return BrainResult(
                        kind="ask_user",
                        text=rendered,
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="free_slots",
                            options=options,
                            action_type="free_slots",
                            requires_confirmation=True,
                        ),
                    )

                if menu_id == "unknown":
                    allowed = {"0", "1", "2"}
                    mapped = _map_choice_from_text(menu_id=menu_id, user_text=user_text)
                    parsed = _parse_menu_choice(user_text, allowed=allowed, default="")
                    is_explicit = mapped is not None or parsed != ""
                    choice = (
                        mapped
                        if isinstance(mapped, str) and mapped in allowed
                        else (parsed if parsed in allowed else default)
                    )

                    # UX: if the user already asked a calendar question while this
                    # disambiguation menu is pending, don't force an extra turn.
                    if (
                        choice == "1"
                        and parsed == ""
                        and (user_text or "").strip() not in allowed
                    ):
                        try:
                            last_intent = state.get("last_intent") if isinstance(state, dict) else None
                            last_tool = state.get("last_tool_used") if isinstance(state, dict) else None
                            guess_route = _detect_route(
                                user_text,
                                last_intent=str(last_intent) if last_intent is not None else None,
                                last_tool_used=str(last_tool) if last_tool is not None else None,
                            )
                        except Exception:
                            guess_route = _ROUTE_UNKNOWN

                        if _is_calendar_route(guess_route):
                            state.pop(_PENDING_CHOICE_KEY, None)
                            state.pop(_REPROMPT_COUNT_KEY, None)
                            state[_DIALOG_STATE_KEY] = "IDLE"
                            return self.run(
                                turn_input=user_text,
                                session_context=session_context,
                                policy=policy,
                                context=state,
                            )

                    # 2-stage reprompt: if unclear, first reprompt, then apply default
                    if not is_explicit:
                        count = _get_reprompt_count(state)
                        if count < 1:
                            state[_REPROMPT_COUNT_KEY] = count + 1
                            reprompt = _render_reprompt(menu_id)
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": reprompt}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=reprompt,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=menu_id,
                                    options=JarvisVoice.MENU_UNKNOWN,
                                    reprompt_for=menu_id,
                                ),
                            )
                        # second unclear → apply default (0=İptal)

                    state.pop(_PENDING_CHOICE_KEY, None)
                    state.pop(_REPROMPT_COUNT_KEY, None)
                    state[_DIALOG_STATE_KEY] = "IDLE"
                    if choice == "0":
                        return BrainResult(
                            kind="say",
                            text="Vazgeçtim.",
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="unknown",
                                options=JarvisVoice.MENU_UNKNOWN,
                            ),
                        )
                    if choice == "1":
                        # User chose calendar - ask them for their calendar query
                        return BrainResult(
                            kind="ask_user",
                            text="Takvim için ne sormak istersin?",
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="calendar_query",
                            ),
                        )
                    if choice == "2":
                        # Re-route to smalltalk
                        state[_PENDING_CHOICE_KEY] = {"menu_id": "smalltalk_stage1", "default": "0"}
                        state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                        rendered = _render_smalltalk_stage1()
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=rendered,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="smalltalk_stage1",
                                options=JarvisVoice.MENU_STAGE1,
                            ),
                        )

        # Deterministic dialog policy routing (demo-mode hardening).
        # Only calendar route is allowed to reach the LLM/tool layer.
        if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
            last_intent = None
            last_tool_used = None
            try:
                if isinstance(state, dict):
                    last_intent = state.get("last_intent")
                    last_tool_used = state.get("last_tool_used")
            except Exception:
                last_intent = None
                last_tool_used = None

            calendar_flow_active = _is_calendar_route(last_intent) or (
                isinstance(last_tool_used, str)
                and last_tool_used.startswith("calendar.")
            )

            # Calendar flow hard-exit: user can always drop the topic.
            if calendar_flow_active and _is_calendar_exit_phrase(user_text):
                try:
                    if isinstance(state, dict):
                        state.pop(_PENDING_CHOICE_KEY, None)
                        state.pop(_CALENDAR_PENDING_INTENT_KEY, None)
                        state.pop(_REPROMPT_COUNT_KEY, None)
                        state.pop(_PENDING_ACTION_KEY, None)
                        state.pop(_CALENDAR_SOFT_EXIT_COUNT_KEY, None)
                        state["last_intent"] = None
                        state["last_tool_used"] = None
                        state[_DIALOG_STATE_KEY] = "IDLE"
                except Exception:
                    pass

                text = "Anlaşıldı efendim, takvim konusunu kapatıyorum."
                try:
                    self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                except Exception:
                    pass
                return BrainResult(
                    kind="say",
                    text=text,
                    steps_used=0,
                    metadata=_std_metadata(
                        ctx=ctx,
                        state=state,
                        menu_id="calendar_exit",
                        action_type="exit_calendar",
                        requires_confirmation=False,
                    ),
                )

            # Soft-exit: second "tamam tamam / peki / neyse" exits calendar flow.
            if calendar_flow_active and _is_calendar_soft_exit_phrase(user_text):
                count = 0
                try:
                    if isinstance(state, dict):
                        count = int(state.get(_CALENDAR_SOFT_EXIT_COUNT_KEY) or 0)
                except Exception:
                    count = 0
                count += 1
                try:
                    if isinstance(state, dict):
                        state[_CALENDAR_SOFT_EXIT_COUNT_KEY] = count
                except Exception:
                    pass
                if count >= 2:
                    try:
                        if isinstance(state, dict):
                            state.pop(_PENDING_CHOICE_KEY, None)
                            state.pop(_CALENDAR_PENDING_INTENT_KEY, None)
                            state.pop(_REPROMPT_COUNT_KEY, None)
                            state.pop(_PENDING_ACTION_KEY, None)
                            state.pop(_CALENDAR_SOFT_EXIT_COUNT_KEY, None)
                            state["last_intent"] = None
                            state["last_tool_used"] = None
                            state[_DIALOG_STATE_KEY] = "IDLE"
                    except Exception:
                        pass
                    text = "Peki efendim."
                    try:
                        self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                    except Exception:
                        pass
                    return BrainResult(
                        kind="say",
                        text=text,
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="calendar_exit",
                            action_type="exit_calendar",
                            requires_confirmation=False,
                        ),
                    )

            locked = _hard_lock_calendar_route(state) if isinstance(state, dict) else None
            route = ""
            if isinstance(locked, str) and locked:
                trace["route_reason"] = ["hard_lock"]
                route = locked
            else:
                # If we have recent calendar events cached, interpret cancel/modify follow-ups
                # as calendar intents (avoid bouncing to unknown/LLM).
                try:
                    last_events = state.get(_CALENDAR_LAST_EVENTS_KEY) if isinstance(state, dict) else None
                    tnorm = _normalize_text_for_match(user_text)
                    if (
                        isinstance(last_events, list)
                        and len(last_events) > 0
                        and (
                            any(k in tnorm for k in ["iptal", "sil", "kaldir", "tasi", "kaydir", "ertele", "guncelle", "degistir"])
                            or bool(re.search(r"#\s*\d+\b", user_text or ""))
                            or any(w in tnorm for w in ["birinci", "ikinci", "ucuncu"])
                        )
                    ):
                        trace["route_reason"] = ["last_events_guard"]
                        route = _calendar_route_from_text(user_text)
                except Exception:
                    route = ""

            if not route:
                route = _detect_route(
                user_text,
                last_intent=str(last_intent) if isinstance(last_intent, str) else None,
                last_tool_used=str(last_tool_used) if isinstance(last_tool_used, str) else None,
            )
            if route == _ROUTE_UNKNOWN:
                llm_route, _llm_intent, llm_conf = _llm_route_classifier(user_text)
                trace["route_reason"] = ["llm_classifier"]
                trace["classifier"] = {"route": llm_route, "calendar_intent": _llm_intent, "confidence": llm_conf}
                if llm_conf >= 0.65:
                    route = llm_route
                else:
                    route = _ROUTE_UNKNOWN
            else:
                try:
                    nt = _normalize_text_for_match(user_text)
                except Exception:
                    nt = ""
                trace["route_reason"] = _route_reason_tokens(
                    user_text_in=user_text,
                    normalized_text=nt,
                    last_intent_in=(str(last_intent) if isinstance(last_intent, str) else None),
                    last_tool_in=(str(last_tool_used) if isinstance(last_tool_used, str) else None),
                )
            ctx["route"] = route
            try:
                if isinstance(state, dict):
                    state["last_intent"] = route
            except Exception:
                pass

            # If we are waiting for a confirmation, never divert to routing menus.
            pending_action = None
            try:
                if isinstance(state, dict):
                    pending_action = state.get(_PENDING_ACTION_KEY)
            except Exception:
                pending_action = None

            # Deterministic calendar ownership (write ops): create/move/cancel.
            # List/query can still be handled by the LLM, but writes must be deterministic
            # and always require confirmation.
            pending_intent = None
            try:
                if isinstance(state, dict):
                    pending_intent = state.get(_CALENDAR_PENDING_INTENT_KEY)
            except Exception:
                pending_intent = None
            pending_intent_type = None
            try:
                if isinstance(pending_intent, dict):
                    pending_intent_type = str(pending_intent.get("type") or "").strip()
            except Exception:
                pending_intent_type = None
            has_pending_write_intent = pending_intent_type in {"create_event", "cancel_event", "move_event"}

            if not isinstance(pending_action, dict) and (
                route in {_ROUTE_CALENDAR_CREATE, _ROUTE_CALENDAR_CANCEL, _ROUTE_CALENDAR_MODIFY}
                or has_pending_write_intent
            ):

                planner_plan: Optional[dict[str, Any]] = None
                try:
                    planner_enabled = bool(ctx.get("enable_calendar_planner"))
                except Exception:
                    planner_enabled = False
                # Planner is only allowed when we're not already in a pending intent (hard-lock).
                if planner_enabled and not isinstance(pending_intent, dict):
                    plan, status = _llm_calendar_planner(user_text)
                    if status == "ok" and isinstance(plan, dict):
                        planner_plan = plan
                        trace["planner"] = plan

                follow_text = user_text
                base_text = user_text
                if isinstance(pending_intent, dict):
                    prior = str(pending_intent.get("source_text") or "").strip()
                    prior_type = str(pending_intent.get("type") or "").strip()
                    if prior:
                        # For create_event slot-filling, keep the title/source frozen from the first intent.
                        # Follow-ups like "1 saat" or "30 dk" must not pollute the title.
                        if prior_type == "create_event":
                            base_text = prior
                        else:
                            base_text = f"{prior} {user_text}".strip()

                intent = build_intent(base_text)

                def _ask_slot_fill(missing_key: str, *, missing_list: Optional[list[str]] = None) -> BrainResult:
                    prompt = ""
                    if missing_key == "start_time":
                        prompt = "Hangi saat olsun efendim? (örn. 15:45)"
                    elif missing_key == "duration_minutes":
                        prompt = "Süre ne olsun efendim? (örn. 30 dk / 1 saat)"
                    elif missing_key == "summary":
                        prompt = "Başlık ne olsun efendim?"
                    elif missing_key == "day_hint":
                        prompt = "Hangi gün efendim? (Bugün/Yarın/Öbür gün)"
                    elif missing_key == "event_ref":
                        prompt = "Hangi etkinlik efendim? (#1/#2 gibi yazabilirsiniz.)"
                    elif missing_key == "offset_or_target":
                        prompt = "Ne kadar kaydırayım efendim? (örn. 30 dk ileri / 1 saat geri / yarına al)"
                    else:
                        prompt = "Eksik bir bilgi var efendim, netleştirebilir misiniz?"

                    try:
                        if isinstance(state, dict):
                            missing_to_store = list(missing_list) if isinstance(missing_list, list) else list(intent.missing)
                            pending_snapshot: dict[str, Any] = {
                                "type": intent.type,
                                "source_text": base_text,
                                "missing": missing_to_store,
                            }
                            if intent.type == "create_event":
                                title = None
                                try:
                                    title = str((intent.params or {}).get("summary") or "").strip() or None
                                except Exception:
                                    title = None
                                if title:
                                    pending_snapshot["title"] = title
                                try:
                                    dh = (intent.params or {}).get("day_hint")
                                    if isinstance(dh, str) and dh:
                                        pending_snapshot["day_hint"] = dh
                                except Exception:
                                    pass
                                try:
                                    sh = (intent.params or {}).get("start_hhmm")
                                    if isinstance(sh, str) and sh:
                                        pending_snapshot["start_hhmm"] = sh
                                except Exception:
                                    pass
                                try:
                                    dm = (intent.params or {}).get("duration_minutes")
                                    if dm is not None:
                                        pending_snapshot["duration_minutes"] = dm
                                except Exception:
                                    pass
                            state[_CALENDAR_PENDING_INTENT_KEY] = pending_snapshot
                    except Exception:
                        pass

                    # Trace for slot fill prompt.
                    try:
                        missing_to_trace = list(missing_list) if isinstance(missing_list, list) else list(intent.missing)
                    except Exception:
                        missing_to_trace = []
                    if intent.type == "create_event":
                        trace["intent"] = "calendar.create"
                        trace["safety"] = ["write_requires_confirmation"]
                        slots: dict[str, Any] = {}
                        try:
                            snap = state.get(_CALENDAR_PENDING_INTENT_KEY) if isinstance(state, dict) else None
                            if isinstance(snap, dict):
                                slots["date"] = str(snap.get("day_hint") or "none") or "none"
                                slots["start_time"] = str(snap.get("start_hhmm") or "none") or "none"
                                slots["duration_min"] = snap.get("duration_minutes")
                                slots["title"] = str(snap.get("title") or "")
                        except Exception:
                            slots = {}
                        trace["slots"] = slots
                    elif intent.type == "cancel_event":
                        trace["intent"] = "calendar.cancel"
                        trace["safety"] = ["write_requires_confirmation"]
                    elif intent.type == "move_event":
                        trace["intent"] = "calendar.modify"
                        trace["safety"] = ["write_requires_confirmation"]
                    else:
                        trace["intent"] = "calendar.unknown"
                        trace["safety"] = []
                    trace["missing"] = missing_to_trace
                    trace["next_action"] = "ask_slot_fill"

                    try:
                        self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                    except Exception:
                        pass

                    return BrainResult(
                        kind="ask_user",
                        text=prompt,
                        steps_used=0,
                        metadata={
                            **_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="calendar_slot_fill",
                                action_type=intent.type,
                                requires_confirmation=(intent.type != "list_events"),
                            ),
                            "missing": (list(missing_list) if isinstance(missing_list, list) else list(intent.missing)),
                            "pending_intent": (state.get(_CALENDAR_PENDING_INTENT_KEY) if isinstance(state, dict) else None),
                        },
                    )

                # ── CREATE ───────────────────────────────────────────────
                if intent.type == "create_event":
                    frozen_title = None
                    frozen_day_hint = None
                    frozen_start_hhmm = None
                    frozen_duration = None
                    if isinstance(pending_intent, dict):
                        try:
                            frozen_title = str(pending_intent.get("title") or "").strip() or None
                        except Exception:
                            frozen_title = None
                        try:
                            frozen_day_hint = str(pending_intent.get("day_hint") or "").strip() or None
                        except Exception:
                            frozen_day_hint = None
                        try:
                            frozen_start_hhmm = str(pending_intent.get("start_hhmm") or "").strip() or None
                        except Exception:
                            frozen_start_hhmm = None
                        try:
                            frozen_duration = pending_intent.get("duration_minutes")
                        except Exception:
                            frozen_duration = None

                    # Fill missing slots from follow-up text without polluting the title.
                    day_hint = intent.params.get("day_hint")
                    if not isinstance(day_hint, str) or not day_hint:
                        day_hint = frozen_day_hint
                    if (not isinstance(day_hint, str) or not day_hint) and isinstance(planner_plan, dict):
                        try:
                            pslots = planner_plan.get("slots")
                            if isinstance(pslots, dict):
                                ph = str(pslots.get("day_hint") or "").strip()
                                if ph and ph != "none":
                                    day_hint = ph
                        except Exception:
                            pass
                    if not isinstance(day_hint, str) or not day_hint:
                        try:
                            day_hint = parse_day_hint(follow_text)
                        except Exception:
                            day_hint = None

                    hhmm = str(intent.params.get("start_hhmm") or "").strip() or None
                    if not hhmm:
                        hhmm = frozen_start_hhmm
                    if not hhmm and isinstance(planner_plan, dict):
                        try:
                            pslots = planner_plan.get("slots")
                            if isinstance(pslots, dict):
                                pst = str(pslots.get("start_time") or "").strip()
                                if pst and pst != "none":
                                    hhmm = pst
                        except Exception:
                            pass
                    if not hhmm:
                        try:
                            hhmm = parse_hhmm(base_text)
                        except Exception:
                            hhmm = None
                    if not hhmm:
                        try:
                            hhmm = parse_hhmm(follow_text)
                        except Exception:
                            hhmm = None

                    dur = intent.params.get("duration_minutes")
                    if dur is None:
                        dur = frozen_duration
                    if dur is None and isinstance(planner_plan, dict):
                        try:
                            pslots = planner_plan.get("slots")
                            if isinstance(pslots, dict):
                                pd = pslots.get("duration_min")
                                if pd is not None:
                                    dur = int(pd)
                        except Exception:
                            pass
                    if dur is None:
                        try:
                            dur = parse_duration_minutes(follow_text)
                        except Exception:
                            dur = None

                    summary = frozen_title
                    if not summary:
                        summary = str(intent.params.get("summary") or "").strip() or None
                    if not summary and isinstance(planner_plan, dict):
                        try:
                            pslots = planner_plan.get("slots")
                            if isinstance(pslots, dict):
                                pt = str(pslots.get("title") or "").strip()
                                if pt:
                                    summary = pt
                        except Exception:
                            pass

                    missing_now: list[str] = []
                    if str(day_hint or "") == "this_week":
                        missing_now.append("day_hint")
                    if not hhmm:
                        missing_now.append("start_time")
                    if dur is None:
                        missing_now.append("duration_minutes")
                    if not summary:
                        missing_now.append("summary")

                    if missing_now:
                        # Persist frozen intent state; do not append follow-up into source_text.
                        try:
                            if isinstance(state, dict):
                                state[_CALENDAR_PENDING_INTENT_KEY] = {
                                    "type": "create_event",
                                    "source_text": base_text,
                                    "missing": list(missing_now),
                                    "title": summary,
                                    "day_hint": day_hint,
                                    "start_hhmm": hhmm,
                                    "duration_minutes": dur,
                                }
                        except Exception:
                            pass
                        # Ask only the first missing slot.
                        trace["intent"] = "calendar.create"
                        trace["slots"] = {
                            "date": str(day_hint or "none") or "none",
                            "start_time": str(hhmm or "none") or "none",
                            "duration_min": (int(dur) if dur is not None else 0),
                            "title": str(summary or "").strip(),
                        }
                        trace["missing"] = list(missing_now)
                        trace["next_action"] = "ask_slot_fill"
                        trace["safety"] = ["write_requires_confirmation"]
                        return _ask_slot_fill(missing_now[0], missing_list=missing_now)

                    # Clear pending intent.
                    try:
                        if isinstance(state, dict):
                            state.pop(_CALENDAR_PENDING_INTENT_KEY, None)
                    except Exception:
                        pass

                    hhmm = str(hhmm or "").strip()
                    summary = str(summary or "(etkinlik)").strip()

                    window = _window_from_ctx(ctx, day_hint=str(day_hint) if isinstance(day_hint, str) else None)
                    date_iso, offset = _date_and_offset_from_window(window)
                    if not date_iso or not hhmm:
                        return _ask_slot_fill("start_time", missing_list=["start_time"])
                    try:
                        duration_minutes = int(dur)
                    except Exception:
                        duration_minutes = 30

                    start = iso_from_date_hhmm(date_iso=date_iso, hhmm=hhmm, offset=offset)
                    end = add_minutes(start, int(duration_minutes))

                    trace["intent"] = "calendar.create"
                    trace["slots"] = {
                        "date": str(day_hint or "none") or "none",
                        "start_time": str(hhmm or "none") or "none",
                        "duration_min": int(duration_minutes),
                        "title": summary,
                    }
                    trace["missing"] = []
                    trace["next_action"] = "ask_confirmation"
                    trace["safety"] = ["write_requires_confirmation"]

                    # Save pending action for the next user turn.
                    try:
                        state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                        state[_PENDING_ACTION_KEY] = {
                            "action": {
                                "type": "CALL_TOOL",
                                "name": "calendar.create_event",
                                "params": {"summary": summary, "start": start, "end": end},
                            },
                            "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
                            "original_user_input": base_text,
                        }
                    except Exception:
                        pass

                    tz_name = str(ctx.get("tz_name") or "") or None
                    sh = _format_hhmm(start, tz_name=tz_name)
                    eh = _format_hhmm(end, tz_name=tz_name)
                    prompt = JarvisVoice.format_confirmation(summary, sh, eh)

                    trace["intent"] = "calendar.create"
                    trace["slots"] = {
                        "date": str(day_hint or "none") or "none",
                        "start_time": hhmm or "none",
                        "duration_min": int(duration_minutes),
                        "title": summary,
                    }
                    trace["missing"] = []
                    trace["next_action"] = "ask_confirmation"
                    trace["safety"] = ["write_requires_confirmation"]
                    try:
                        self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                    except Exception:
                        pass
                    return BrainResult(
                        kind="ask_user",
                        text=prompt,
                        steps_used=0,
                        metadata=_std_metadata(
                            ctx=ctx,
                            state=state,
                            menu_id="pending_confirmation",
                            action_type="create_event",
                            requires_confirmation=True,
                        ),
                    )

                # ── CANCEL / MOVE (needs an event selection) ─────────────
                if intent.type in {"cancel_event", "move_event"}:
                    last_events = []
                    try:
                        if isinstance(state, dict):
                            last_events = state.get(_CALENDAR_LAST_EVENTS_KEY) or []
                    except Exception:
                        last_events = []
                    if not isinstance(last_events, list):
                        last_events = []
                    last_events = [e for e in last_events if isinstance(e, dict)]

                    # Best-effort fuzzy match: if the user mentions a title or a time,
                    # pick the single strong candidate without opening a menu.
                    if intent.missing and "event_ref" in intent.missing and last_events:
                        picked = _pick_event_from_text(base_text, last_events[:3])
                        if isinstance(picked, int) and 0 <= picked < len(last_events[:3]):
                            try:
                                # Replace missing event_ref by synthesizing an index ref.
                                intent = build_intent(f"{base_text} #{picked+1}")
                            except Exception:
                                pass

                    if intent.missing and "event_ref" in intent.missing:
                        if last_events:
                            rendered, options = _render_event_pick_menu(last_events)
                            try:
                                if isinstance(state, dict):
                                    state[_PENDING_CHOICE_KEY] = {
                                        "menu_id": "event_pick",
                                        "default": "0",
                                        "events": last_events[:3],
                                        "op": intent.type,
                                        "params": dict(intent.params) if isinstance(intent.params, dict) else {},
                                        "options": options,
                                    }
                                    state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                            except Exception:
                                pass
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=rendered,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id="event_pick",
                                    options=options,
                                    action_type=intent.type,
                                    requires_confirmation=True,
                                ),
                            )
                        return _ask_slot_fill("event_ref")

                    # If we have an explicit #N reference, try to execute directly.
                    idx = None
                    try:
                        if intent.event_ref is not None and intent.event_ref.kind == "index":
                            idx = int(intent.event_ref.index or 0) - 1
                    except Exception:
                        idx = None

                    if idx is None or idx < 0 or idx >= len(last_events):
                        if last_events:
                            rendered, options = _render_event_pick_menu(last_events)
                            try:
                                if isinstance(state, dict):
                                    state[_PENDING_CHOICE_KEY] = {
                                        "menu_id": "event_pick",
                                        "default": "0",
                                        "events": last_events[:3],
                                        "op": intent.type,
                                        "params": dict(intent.params) if isinstance(intent.params, dict) else {},
                                        "options": options,
                                    }
                                    state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                            except Exception:
                                pass
                            try:
                                self._events.publish(EventType.QUESTION.value, {"question": rendered}, source="brain")
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=rendered,
                                steps_used=0,
                                metadata=_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id="event_pick",
                                    options=options,
                                    action_type=intent.type,
                                    requires_confirmation=True,
                                ),
                            )
                        return _ask_slot_fill("event_ref")

                    ev = last_events[idx]
                    ev_id = str(ev.get("id") or "").strip()
                    if not ev_id:
                        return BrainResult(kind="say", text="Etkinlik kimliğini bulamadım efendim.", steps_used=0, metadata={})

                    # Defer actual write via confirmation.
                    if intent.type == "cancel_event":
                        summary = str(ev.get("summary") or "(etkinlik)").strip()
                        start = str(ev.get("start") or "").strip()
                        end = str(ev.get("end") or "").strip()
                        tz_name = str(ctx.get("tz_name") or "") or None
                        sh = _format_hhmm(start, tz_name=tz_name) if start else ""
                        eh = _format_hhmm(end, tz_name=tz_name) if end else ""
                        preview = f"{sh}–{eh} | {summary}" if sh and eh else summary
                        prompt = f"\"{preview}\" iptal edeyim mi? (1/0)"
                        try:
                            state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                            state[_PENDING_ACTION_KEY] = {
                                "action": {"type": "CALL_TOOL", "name": "calendar.delete_event", "params": {"event_id": ev_id}},
                                "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
                                "original_user_input": base_text,
                            }
                        except Exception:
                            pass
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=prompt,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="pending_confirmation",
                                action_type="delete_event",
                                requires_confirmation=True,
                            ),
                        )

                    if intent.type == "move_event":
                        offset_minutes = intent.params.get("offset_minutes")
                        day_hint = intent.params.get("day_hint")
                        target_hhmm = str(intent.params.get("target_hhmm") or "").strip() or None
                        if offset_minutes is None and not target_hhmm and str(day_hint or "") not in {"tomorrow", "day_after_tomorrow"}:
                            return _ask_slot_fill("offset_or_target")
                        start = str(ev.get("start") or "").strip()
                        end = str(ev.get("end") or "").strip()
                        if not start or not end:
                            return BrainResult(kind="say", text="Etkinliğin saat bilgisi eksik efendim.", steps_used=0, metadata={})
                        try:
                            if offset_minutes is not None:
                                off = int(offset_minutes)
                                new_start = add_minutes(start, off)
                                new_end = add_minutes(end, off)
                            elif target_hhmm is not None:
                                # Move to a specific time on a specific day, preserving duration.
                                window = _window_from_ctx(ctx, day_hint=str(day_hint) if isinstance(day_hint, str) else None)
                                date_iso, offset = _date_and_offset_from_window(window)
                                if not date_iso:
                                    return _ask_slot_fill("day_hint")
                                new_start = iso_from_date_hhmm(date_iso=date_iso, hhmm=target_hhmm, offset=offset)
                                try:
                                    sdt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                                    edt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                                    dur = edt - sdt
                                    nst = datetime.fromisoformat(new_start.replace("Z", "+00:00"))
                                    new_end = (nst + dur).isoformat()
                                except Exception:
                                    # Fallback: keep original duration in minutes (approx).
                                    new_end = add_minutes(new_start, 60)
                            else:
                                # Default: move to tomorrow/next day keeping time.
                                days = 1
                                if str(day_hint or "") == "day_after_tomorrow":
                                    days = 2
                                new_start = add_days_keep_time(start, days)
                                new_end = add_days_keep_time(end, days)
                        except Exception:
                            return BrainResult(kind="say", text="Yeni zamanı hesaplayamadım efendim.", steps_used=0, metadata={})
                        summary = str(ev.get("summary") or "(etkinlik)").strip()
                        tz_name = str(ctx.get("tz_name") or "") or None
                        osh = _format_hhmm(start, tz_name=tz_name)
                        oeh = _format_hhmm(end, tz_name=tz_name)
                        nsh = _format_hhmm(new_start, tz_name=tz_name)
                        neh = _format_hhmm(new_end, tz_name=tz_name)
                        prompt = f"\"{summary}\" etkinliğini {osh}–{oeh} → {nsh}–{neh} olarak taşıyayım mı? (1/0)"
                        try:
                            state[_DIALOG_STATE_KEY] = "PENDING_CONFIRMATION"
                            state[_PENDING_ACTION_KEY] = {
                                "action": {
                                    "type": "CALL_TOOL",
                                    "name": "calendar.update_event",
                                    "params": {"event_id": ev_id, "start": new_start, "end": new_end},
                                },
                                "decision": {"risk_level": "MED", "requires_confirmation": True, "allowed": False},
                                "original_user_input": base_text,
                            }
                        except Exception:
                            pass
                        try:
                            self._events.publish(EventType.QUESTION.value, {"question": prompt}, source="brain")
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=prompt,
                            steps_used=0,
                            metadata=_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="pending_confirmation",
                                action_type="update_event",
                                requires_confirmation=True,
                            ),
                        )

            # Deterministic calendar read: for common list-events queries with an
            # explicit time hint, bypass the LLM and call the tool directly.
            if route == _ROUTE_CALENDAR_QUERY and not isinstance(pending_action, dict):
                intent_hint = _detect_time_intent_simple(user_text)
                if intent_hint:
                    window = _window_from_ctx(ctx, day_hint=intent_hint)
                    time_min = window.get("time_min") if isinstance(window, dict) else None
                    time_max = window.get("time_max") if isinstance(window, dict) else None

                    if (
                        isinstance(time_min, str)
                        and isinstance(time_max, str)
                        and time_min
                        and time_max
                    ):
                        tool = self._tools.get("calendar.list_events")
                        if tool is not None and tool.function is not None:
                            try:
                                _emit_ack()
                                _emit_progress(tool_name="calendar.list_events")
                                res = tool.function(time_min=time_min, time_max=time_max)
                                _emit_found(tool_name="calendar.list_events")
                            except Exception:
                                res = {"ok": False}

                            tz_name = str(ctx.get("tz_name") or "") or None
                            text = _render_calendar_list_events(
                                result=res if isinstance(res, dict) else {"ok": False},
                                intent=intent_hint,
                                tz_name=tz_name,
                            )

                            # Trace for auditability/tests.
                            try:
                                trace["intent"] = "calendar.query"
                                trace["slots"] = {"date": (str(intent_hint or "none") or "none")}
                                trace["missing"] = []
                                trace["next_action"] = "say_result"
                                trace["safety"] = []
                            except Exception:
                                pass

                            mini_ack = False
                            if _has_smalltalk_clause(user_text):
                                mini_ack = True
                                text = (str(text).rstrip() + "\n\nİsterseniz bununla ilgili konuşabiliriz.").strip()

                            text = _role_sanitize_text(text)

                            # Save recent events for deterministic disambiguation in later turns.
                            try:
                                evs = res.get("events") if isinstance(res, dict) and isinstance(res.get("events"), list) else []
                                evs = [e for e in evs if isinstance(e, dict)]
                                if isinstance(state, dict):
                                    state[_CALENDAR_LAST_EVENTS_KEY] = evs[:10]
                            except Exception:
                                pass

                            try:
                                if isinstance(state, dict):
                                    state[_DIALOG_STATE_KEY] = "AFTER_CALENDAR_STATUS"
                                    state["last_tool_used"] = "calendar.list_events"
                            except Exception:
                                pass

                            _emit_summarizing("started")
                            try:
                                self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                            except Exception:
                                pass
                            _emit_summarizing("complete")

                            count_val = None
                            try:
                                if isinstance(res, dict):
                                    count_val = int(res.get("count") or 0)
                            except Exception:
                                count_val = None
                            shown = None
                            more = None
                            try:
                                if isinstance(count_val, int):
                                    shown = min(3, max(0, count_val))
                                    more = max(0, count_val - shown)
                            except Exception:
                                shown = None
                                more = None

                            return BrainResult(
                                kind="say",
                                text=text,
                                steps_used=0,
                                metadata={
                                    **_std_metadata(
                                        ctx=ctx,
                                        state=state,
                                        action_type="list_events",
                                        requires_confirmation=False,
                                    ),
                                    "mini_ack": bool(mini_ack),
                                    "events_count": count_val,
                                    "events_shown": shown,
                                    "events_more": more,
                                },
                            )

            # Issue #115: PlanDraft proposal. For planning prompts, produce a
            # structured plan preview without writing to the calendar.
            if not isinstance(pending_action, dict) and looks_like_planning_prompt(user_text):
                plan = build_plan_draft_from_text(user_text, ctx=ctx)
                preview = plan.render_preview_tr()

                # Resolve a concrete window now (so follow-up turns don't need session_context).
                w_day_hint: Optional[str] = None
                try:
                    day = str(plan.day_hint or "").strip() or None
                    tod = str(plan.time_of_day or "").strip() or None
                    if (day == "tomorrow" and tod == "morning") or (day is None and tod == "morning"):
                        w_day_hint = "morning"
                    elif (day == "today" and tod == "evening") or (day is None and tod == "evening"):
                        w_day_hint = "evening"
                    else:
                        w_day_hint = day
                except Exception:
                    w_day_hint = None
                window = _window_from_ctx(ctx, day_hint=w_day_hint)
                time_min = str((window or {}).get("time_min") or "").strip()
                time_max = str((window or {}).get("time_max") or "").strip()

                # Store pending plan draft for #116 confirmation/edit loop.
                try:
                    if isinstance(state, dict):
                        state[_PLANNING_PENDING_DRAFT_KEY] = {
                            "id": str(uuid.uuid4()),
                            "created_at": float(time.time()),
                            "draft": plan_draft_to_dict(plan),
                            "time_min": time_min or None,
                            "time_max": time_max or None,
                        }
                        state[_DIALOG_STATE_KEY] = "PENDING_PLAN_DRAFT"
                except Exception:
                    pass

                # Trace for auditability/tests (never chain-of-thought).
                try:
                    trace["intent"] = "calendar.plan_draft"
                    trace["slots"] = {
                        "plan_window": plan.plan_window(),
                        "item_count": len(plan.items) if isinstance(plan.items, list) else 0,
                    }
                    trace["missing"] = []
                    trace["next_action"] = "say_result"
                    trace["safety"] = []
                except Exception:
                    pass

                _emit_ack()
                _emit_progress(tool_name="planner.plan_draft")
                try:
                    self._events.publish(
                        EventType.QUESTION.value, {"question": _render_plan_confirm_menu()}, source="brain"
                    )
                except Exception:
                    pass
                preview = _role_sanitize_text(preview)
                try:
                    self._events.publish(EventType.RESULT.value, {"text": preview}, source="brain")
                except Exception:
                    pass

                return BrainResult(
                    kind="say",
                    text=preview,
                    steps_used=0,
                    metadata={
                        **_std_metadata(
                            ctx=ctx,
                            state=state,
                            action_type="plan_draft",
                            requires_confirmation=False,
                        ),
                        "plan_window": plan.plan_window(),
                        "item_count": len(plan.items) if isinstance(plan.items, list) else 0,
                        "plan_confidence": float(getattr(plan, "confidence", 0.0) or 0.0),
                    },
                )

            if route == _ROUTE_SMALLTALK and not isinstance(pending_action, dict):
                rendered = _render_smalltalk_stage1()
                try:
                    if isinstance(state, dict):
                        state[_PENDING_CHOICE_KEY] = {"menu_id": "smalltalk_stage1", "default": "0"}
                        state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                except Exception:
                    pass
                try:
                    self._events.publish(
                        EventType.QUESTION.value, {"question": rendered}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="ask_user",
                    text=rendered,
                    steps_used=0,
                    metadata=_std_metadata(
                        ctx=ctx,
                        state=state,
                        menu_id="smalltalk_stage1",
                        options=JarvisVoice.MENU_STAGE1,
                    ),
                )

            if route == _ROUTE_UNKNOWN and not isinstance(pending_action, dict):
                state[_PENDING_CHOICE_KEY] = {"menu_id": "unknown", "default": "0"}
                state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                rendered = _render_unknown_menu()
                try:
                    self._events.publish(
                        EventType.QUESTION.value, {"question": rendered}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="ask_user",
                    text=rendered,
                    steps_used=0,
                    metadata=_std_metadata(
                        ctx=ctx,
                        state=state,
                        menu_id="unknown",
                        options=JarvisVoice.MENU_UNKNOWN,
                    ),
                )

        # Conversation messages for the adapter.
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Sen Bantz'sın. Türkçe konuş. Tool çağırman gerekirse STRICT JSON döndür. "
                    "İzin/onay gerektiren işlerde kullanıcıdan soru sor."
                ),
            },
            {"role": "user", "content": user_text},
        ]

        observations: list[dict[str, Any]] = []

        # If we have a pending action from a previous turn, handle user confirm/deny.
        pending = state.get(_PENDING_ACTION_KEY) if isinstance(state, dict) else None
        if isinstance(pending, dict):
            pending_action = pending.get("action")
            pending_decision = pending.get("decision")

            decision, note = _parse_user_confirmation(user_text)

            # Trace evidence: pending confirmation was seen and parsed.
            try:
                trace = _ensure_trace()
                trace["pending_confirmation"] = {
                    "seen": True,
                    "tool": str((pending_action or {}).get("name") or "").strip() or None,
                    "decision": decision,
                }
            except Exception:
                pass

            # Jarvis safety rule: destructive calendar writes require strict yes/no.
            if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
                try:
                    tool_name = str((pending_action or {}).get("name") or "").strip()
                    t = str(user_text or "").strip().lower()
                    if tool_name in {"calendar.delete_event", "calendar.update_event"}:
                        # Allow deny via existing parser (0/hayır/iptal/vazgeç etc), but confirmations must be strict.
                        strict_confirm = (
                            t == "1"
                            or t.startswith("1 ")
                            or t == "evet"
                            or t.startswith("evet ")
                        )
                        if decision == "confirm" and not strict_confirm:
                            decision = None
                            note = ""
                except Exception:
                    pass

            # Jarvis-mode hard rule: while waiting for confirmation, only accept yes/no.
            if (
                isinstance(ctx, dict)
                and bool(ctx.get("deterministic_render"))
                and decision is None
            ):
                session_id = str(ctx.get("session_id") or "default")
                prompt = JarvisVoice.confirm_reprompt(session_id)
                try:
                    self._events.publish(
                        EventType.QUESTION.value, {"question": prompt}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="ask_user",
                    text=prompt,
                    steps_used=0,
                    metadata=_std_metadata(
                        ctx=ctx,
                        state=state,
                        menu_id="pending_confirmation",
                        action_type=_action_type_from_tool_name(
                            str((pending_action or {}).get("name") or "")
                        ),
                        requires_confirmation=True,
                        reprompt_for="pending_confirmation",
                    ),
                )

            if decision == "deny":
                try:
                    state.pop(_PENDING_ACTION_KEY, None)
                except Exception:
                    pass
                try:
                    state.pop(_CALENDAR_PENDING_INTENT_KEY, None)
                    state.pop(_REPROMPT_COUNT_KEY, None)
                except Exception:
                    pass
                try:
                    if isinstance(state, dict):
                        state[_DIALOG_STATE_KEY] = "IDLE"
                except Exception:
                    pass
                return BrainResult(
                    kind="say",
                    text="İptal ediyorum efendim.",
                    steps_used=0,
                    metadata=_std_metadata(
                        ctx=ctx,
                        state=state,
                        menu_id="pending_confirmation",
                        action_type=_action_type_from_tool_name(
                            str((pending_action or {}).get("name") or "")
                        ),
                        requires_confirmation=True,
                    ),
                )

            if decision == "confirm" and isinstance(pending_action, dict):
                # Clear pending first to avoid loops if tool fails.
                try:
                    state.pop(_PENDING_ACTION_KEY, None)
                except Exception:
                    pass

                # Preserve trailing note for slot-filling style followups.
                if note:
                    try:
                        state[_POLICY_CONFIRM_NOTE_KEY] = note
                    except Exception:
                        pass

                tool_name = str(pending_action.get("name") or "").strip()
                params = pending_action.get("params")
                if not isinstance(params, dict):
                    params = {}

                # Record confirmation for MED-risk (remember session).
                try:
                    if policy is not None and hasattr(policy, "confirm") and isinstance(pending_decision, dict):
                        risk = str(pending_decision.get("risk_level") or "LOW").strip().upper()
                        if risk in {"LOW", "MED", "HIGH"}:
                            policy.confirm(session_id=session_id, tool_name=tool_name, risk_level=risk)  # type: ignore
                except Exception:
                    pass

                # Execute tool once, then let LLM produce a final SAY.
                ok, why = self._tools.validate_call(tool_name, params)
                if not ok:
                    observations.append({"tool": tool_name, "ok": False, "error": why})
                else:
                    tool = self._tools.get(tool_name)
                    if tool is None or tool.function is None:
                        observations.append({"tool": tool_name, "ok": False, "error": "tool_not_executable"})
                    else:
                        try:
                            _emit_ack()
                            _emit_progress(tool_name=tool_name)
                            result = tool.function(**params)
                            observations.append({"tool": tool_name, "ok": True, "result": result})
                            _emit_found(tool_name=tool_name)
                        except Exception as e:
                            observations.append({"tool": tool_name, "ok": False, "error": str(e)})

                # If a calendar write succeeded, clean up dialog state so the next turn is fresh.
                try:
                    obs_last = observations[-1] if observations else None
                    if (
                        isinstance(state, dict)
                        and tool_name in {"calendar.create_event", "calendar.update_event", "calendar.delete_event", "calendar.apply_plan_draft"}
                        and isinstance(obs_last, dict)
                        and obs_last.get("ok") is True
                    ):
                        _cleanup_after_calendar_write(state)
                        # Planning apply: also clear confirmed draft.
                        if tool_name == "calendar.apply_plan_draft":
                            try:
                                res = obs_last.get("result")
                                if isinstance(res, dict) and res.get("ok") is True and not bool(res.get("dry_run")):
                                    state.pop(_PLANNING_CONFIRMED_DRAFT_KEY, None)
                            except Exception:
                                pass
                except Exception:
                    pass

                # Demo/Jarvis deterministic renderer: bypass LLM.
                if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
                    obs = observations[-1] if observations else {"ok": False, "error": "no_observation"}
                    tz_name = str(ctx.get("tz_name") or "") or None
                    dry_run = bool(ctx.get("dry_run"))
                    if tool_name == "calendar.create_event":
                        text = _render_calendar_create_event_result(
                            obs=obs,
                            tz_name=tz_name,
                            dry_run=dry_run,
                            fallback_params=params if isinstance(params, dict) else None,
                        )
                    elif tool_name == "calendar.apply_plan_draft":
                        text = _render_calendar_apply_plan_draft_result(obs=obs, tz_name=tz_name)
                    else:
                        # Fallback deterministic summary.
                        text = "Efendim, tamamdır." if isinstance(obs, dict) and obs.get("ok") is True else "Efendim, işlem başarısız oldu."
                    mini_ack = False
                    try:
                        original_user = str(pending.get("original_user_input") or "").strip()
                        if _has_smalltalk_clause(original_user):
                            mini_ack = True
                            text = (str(text).rstrip() + "\n\nİsterseniz bununla ilgili konuşabiliriz.").strip()
                    except Exception:
                        mini_ack = False
                    text = _role_sanitize_text(text)
                    _emit_summarizing("started")
                    try:
                        self._events.publish(
                            EventType.RESULT.value, {"text": text}, source="brain"
                        )
                    except Exception:
                        pass
                    _emit_summarizing("complete")
                    return BrainResult(
                        kind="say",
                        text=text,
                        steps_used=0,
                        metadata={
                            **_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id="pending_confirmation",
                                action_type=_action_type_from_tool_name(tool_name),
                                requires_confirmation=True,
                            ),
                            "mini_ack": bool(mini_ack),
                            "dry_run": bool(dry_run),
                        },
                    )

                # Rebuild messages so LLM sees the tool + observation context.
                original_user = str(pending.get("original_user_input") or "").strip() or "(previous request)"

                note_line = f"\nKullanıcı notu: {note}" if note else ""
                messages = [
                    messages[0],
                    {"role": "user", "content": original_user},
                    {"role": "assistant", "content": json.dumps(pending_action, ensure_ascii=False)},
                    {
                        # Important: do NOT present tool output as a user message.
                        "role": "system",
                        "content": "TOOL_OBSERVATION: "
                        + json.dumps(observations[-1], ensure_ascii=False)
                        + note_line
                        + "\n\nŞimdi sadece kısa bir SAY ile sonucu özetle.",
                    },
                ]

        transcript: list[BrainTranscriptTurn] = []

        # Emit quick ACK.
        try:
            self._events.publish(
                EventType.ACK.value, {"text": "Anladım efendim."}, source="brain"
            )
        except Exception:
            pass

        for step_idx in range(1, int(self._config.max_steps) + 1):
            schema_obj = {
                "protocol": {
                    "type": "SAY|CALL_TOOL|ASK_USER|FAIL",
                    "SAY": {"text": "..."},
                    "ASK_USER": {"question": "..."},
                    "CALL_TOOL": {"name": "tool_name", "params": {}},
                    "FAIL": {"error": "..."},
                },
                "tools": self._tools.as_llm_catalog(format="short"),
                "policy_summary": _summarize_policy(policy),
                "session_context": _shorten_jsonable(ctx, max_chars=1200),
                "conversation_context": _short_conversation(
                    messages, max_messages=12, max_chars=1200
                ),
                "observations": observations[-6:],
            }
            schema_hint = json.dumps(schema_obj, ensure_ascii=False)

            out_raw = self._llm.complete_json(messages=messages, schema_hint=schema_hint)
            out_raw = _coerce_action_dict(out_raw)
            action, status = _parse_llm_output(out_raw)

            if self._config.debug:
                masked_turn = BrainTranscriptTurn(
                    step=step_idx,
                    messages=_mask_messages(messages[-12:]),
                    schema=_mask_jsonable(schema_obj),
                    output=_mask_jsonable(
                        out_raw if isinstance(out_raw, dict) else {"_raw": str(out_raw)}
                    ),
                )
                transcript.append(masked_turn)
                try:
                    logger.debug(
                        "[BrainLoop] turn=%s trace=%s",
                        step_idx,
                        json.dumps(
                            {
                                "step": masked_turn.step,
                                "messages": masked_turn.messages,
                                "schema": masked_turn.schema,
                                "output": masked_turn.output,
                            },
                            ensure_ascii=False,
                        ),
                    )
                except Exception:
                    pass

            if action is None:
                if status == "llm_output_not_object":
                    return BrainResult(
                        kind="fail",
                        text="llm_output_not_object",
                        steps_used=step_idx,
                        metadata=_meta(transcript),
                    )

                # Unknown type: ask LLM to restate.
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(out_raw, ensure_ascii=False),
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "Geçersiz type. Sadece SAY|CALL_TOOL|ASK_USER|FAIL döndür.",
                    }
                )
                continue

            if isinstance(action, Say):
                text = _role_sanitize_text(action.text)
                try:
                    self._events.publish(
                        EventType.RESULT.value, {"text": text}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="say",
                    text=text,
                    steps_used=step_idx,
                    metadata=_meta(transcript, raw=out_raw),
                )

            if isinstance(action, AskUser):
                q = _role_sanitize_text(action.question)

                # Demo-mode hard rule: BrainLoop owns ASK_USER. Ignore LLM-authored
                # questions and render deterministic menus based on the route.
                if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
                    route = str(ctx.get("route") or "").strip() or _detect_route(user_text)
                    menu_id = ""
                    options: Optional[dict[str, str]] = None
                    if route == _ROUTE_SMALLTALK:
                        menu_id = "smalltalk_stage1"
                        options = JarvisVoice.MENU_STAGE1
                        rendered = _render_smalltalk_stage1()
                        try:
                            if isinstance(state, dict):
                                state[_PENDING_CHOICE_KEY] = {"menu_id": "smalltalk_stage1", "default": "0"}
                                state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                        except Exception:
                            pass
                    elif route == _ROUTE_UNKNOWN:
                        menu_id = "unknown"
                        options = JarvisVoice.MENU_UNKNOWN
                        rendered = _render_unknown_menu()
                        try:
                            if isinstance(state, dict):
                                state[_PENDING_CHOICE_KEY] = {"menu_id": "unknown", "default": "0"}
                                state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                        except Exception:
                            pass
                    else:
                        menu_id = "calendar_next"
                        options = {"1": "Yarın bak", "2": "Sabah için boşluk ara", "0": "İptal"}
                        rendered = _render_ask_user(
                            "Nasıl ilerleyelim efendim?",
                            choices=[
                                {"id": "1", "label": "Yarın bak"},
                                {"id": "2", "label": "Sabah için boşluk ara"},
                                {"id": "0", "label": "İptal"},
                            ],
                            default="0",
                        )
                        try:
                            if isinstance(state, dict):
                                state[_PENDING_CHOICE_KEY] = {"menu_id": "calendar_next", "default": "0"}
                                state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                        except Exception:
                            pass
                    try:
                        self._events.publish(
                            EventType.QUESTION.value, {"question": rendered}, source="brain"
                        )
                    except Exception:
                        pass
                    return BrainResult(
                        kind="ask_user",
                        text=rendered,
                        steps_used=step_idx,
                        metadata={
                            **_meta(transcript, raw=out_raw),
                            **_std_metadata(
                                ctx=ctx,
                                state=state,
                                menu_id=menu_id,
                                options=options,
                            ),
                        },
                    )

                if _looks_like_user_echo(user_text=user_text, question=q):
                    # Deterministic guardrail: avoid role-confusion / parroting.
                    text = "Efendim, netleştirebilir misiniz? (1) Yarın bak (2) Haftalık (0) İptal"
                    try:
                        self._events.publish(
                            EventType.RESULT.value, {"text": text}, source="brain"
                        )
                    except Exception:
                        pass
                    return BrainResult(
                        kind="say",
                        text=text,
                        steps_used=step_idx,
                        metadata=_meta(transcript, raw=out_raw),
                    )

                # Optional structured choices.
                choices = out_raw.get("choices") if isinstance(out_raw, dict) else None
                default = out_raw.get("default") if isinstance(out_raw, dict) else "0"
                if not isinstance(choices, list):
                    choices = None
                if not isinstance(default, str):
                    default = "0"

                # Demo-only clamp: always present a small menu, and kill vague/role-confused questions.
                if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
                    if _looks_like_role_confused_question(q) or not q.strip():
                        q = "Nasıl ilerleyelim efendim?"
                    if choices is None:
                        choices = [
                            {"id": "1", "label": "Yarın bak"},
                            {"id": "2", "label": "Sabah için boşluk ara"},
                            {"id": "0", "label": "İptal"},
                        ]
                        default = "0"

                rendered = _render_ask_user(q, choices=choices, default=default)
                try:
                    self._events.publish(
                        EventType.QUESTION.value, {"question": rendered}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="ask_user",
                    text=rendered,
                    steps_used=step_idx,
                    metadata=_meta(transcript, raw=out_raw),
                )

            if isinstance(action, Fail):
                err = action.error
                try:
                    self._events.publish(
                        EventType.ERROR.value, {"error": err}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="fail",
                    text=err,
                    steps_used=step_idx,
                    metadata=_meta(transcript, raw=out_raw),
                )

            if isinstance(action, CallTool):
                name = action.name
                params = action.params

                # Demo-mode hard rule: non-calendar routes must not execute tools.
                if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
                    route = str(ctx.get("route") or "").strip() or _detect_route(user_text)
                    if not _is_calendar_route(route):
                        rendered = (
                            _render_smalltalk_menu(user_text)
                            if route == _ROUTE_SMALLTALK
                            else _render_unknown_menu()
                        )
                        try:
                            self._events.publish(
                                EventType.QUESTION.value,
                                {"question": rendered},
                                source="brain",
                            )
                        except Exception:
                            pass
                        return BrainResult(
                            kind="ask_user",
                            text=rendered,
                            steps_used=step_idx,
                            metadata={
                                **_meta(transcript, raw=out_raw),
                                **_std_metadata(
                                    ctx=ctx,
                                    state=state,
                                    menu_id=(
                                        "smalltalk_stage1" if route == _ROUTE_SMALLTALK else "unknown"
                                    ),
                                    options=(
                                        JarvisVoice.MENU_STAGE1 if route == _ROUTE_SMALLTALK else JarvisVoice.MENU_UNKNOWN
                                    ),
                                ),
                            },
                        )

                    # Even on calendar routes, enforce allowlist.
                    if not str(name).startswith("calendar."):
                        text = "Efendim, bu komutu Jarvis modunda çalıştıramam."
                        try:
                            self._events.publish(
                                EventType.RESULT.value, {"text": text}, source="brain"
                            )
                        except Exception:
                            pass
                        return BrainResult(
                            kind="say",
                            text=text,
                            steps_used=step_idx,
                            metadata=_meta(transcript, raw=out_raw),
                        )

                ok, why = self._tools.validate_call(name, params)
                if not ok:
                    observations.append({"tool": name, "ok": False, "error": why})
                    messages.append(
                        {
                            "role": "assistant",
                            "content": json.dumps(out_raw, ensure_ascii=False),
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Tool çağrısı geçersiz: {why}. Geçerli JSON ile tekrar dene.",
                        }
                    )
                    continue

                # Policy guardrail: gate tool execution.
                try:
                    tool_obj = self._tools.get(name)
                    risk = "LOW"
                    requires_conf = False
                    if tool_obj is not None:
                        if tool_obj.risk_level is not None:
                            risk = str(tool_obj.risk_level).upper()
                        else:
                            risk = "HIGH" if bool(tool_obj.requires_confirmation) else "LOW"
                        requires_conf = bool(tool_obj.requires_confirmation)

                    # Special-case: plan dry-run is read-only.
                    try:
                        if name == "calendar.apply_plan_draft" and isinstance(params, dict) and bool(params.get("dry_run")):
                            risk = "LOW"
                            requires_conf = False
                    except Exception:
                        pass

                    if policy is not None and hasattr(policy, "check"):
                        prompt = "Bu işlemi onaylıyor musun? (1/0)"
                        if name == "calendar.create_event":
                            title = str(
                                params.get("summary")
                                or params.get("title")
                                or "(etkinlik)"
                            ).strip()
                            if len(title) > 120:
                                title = title[:119] + "…"
                            start = str(params.get("start") or "").strip()
                            end = str(params.get("end") or "").strip()
                            tz_name = str(ctx.get("tz_name") or "") or None
                            sh = _format_hhmm(start, tz_name=tz_name) if start else ""
                            eh = _format_hhmm(end, tz_name=tz_name) if end else ""
                            if sh and eh:
                                prompt = JarvisVoice.format_confirmation(title, sh, eh)
                            else:
                                prompt = f'"{title}" ekleyeyim mi? (1/0)'
                        elif name == "calendar.apply_plan_draft":
                            if isinstance(params, dict) and bool(params.get("dry_run")):
                                prompt = "Dry-run yapıyorum. (Onay gerekmez)"
                            else:
                                prompt = "Planı takvime uygulayayım mı? (1/0)"

                        decision = policy.check(
                            session_id=session_id,
                            tool_name=name,
                            params=params,
                            risk_level=risk,
                            requires_confirmation=requires_conf,
                            prompt_to_user=prompt,
                        )

                        if getattr(decision, "requires_confirmation", False) and not getattr(decision, "allowed", False):
                            # Save pending action for the next user turn.
                            try:
                                state[_PENDING_ACTION_KEY] = {
                                    "action": {"type": "CALL_TOOL", "name": name, "params": params},
                                    "decision": getattr(decision, "to_dict", lambda: {})(),
                                    "original_user_input": user_text,
                                }
                            except Exception:
                                pass

                            q = str(getattr(decision, "prompt_to_user", "") or "Onaylıyor musun? (1/0)").strip()
                            try:
                                self._events.publish(
                                    EventType.QUESTION.value, {"question": q}, source="brain"
                                )
                            except Exception:
                                pass
                            return BrainResult(
                                kind="ask_user",
                                text=q,
                                steps_used=step_idx,
                                metadata={
                                    **_meta(transcript, raw=out_raw),
                                    **_std_metadata(
                                        ctx=ctx,
                                        state=state,
                                        menu_id="pending_confirmation",
                                        action_type=_action_type_from_tool_name(name),
                                        requires_confirmation=True,
                                    ),
                                },
                            )
                except Exception:
                    # Policy must never crash the loop.
                    pass

                try:
                    self._events.publish(
                        EventType.PROGRESS.value,
                        {"message": f"Tool çalıştırılıyor: {name}", "step": step_idx},
                        source="brain",
                    )
                except Exception:
                    pass

                tool = self._tools.get(name)
                if tool is None or tool.function is None:
                    observations.append(
                        {"tool": name, "ok": False, "error": "tool_not_executable"}
                    )
                else:
                    try:
                        result = tool.function(**params)
                        observations.append(
                            {"tool": name, "ok": True, "result": result}
                        )
                    except Exception as e:
                        observations.append(
                            {"tool": name, "ok": False, "error": str(e)}
                        )

                try:
                    self._events.publish(
                        EventType.FOUND.value, {"tool": name}, source="brain"
                    )
                except Exception:
                    pass

                # Demo-only deterministic renderer: bypass LLM summarization.
                try:
                    if isinstance(ctx, dict) and bool(ctx.get("deterministic_render")):
                        obs = observations[-1]
                        if name == "calendar.list_events" and isinstance(obs, dict) and obs.get("ok") is True:
                            res = obs.get("result")
                            if isinstance(res, dict):
                                intent = _detect_time_intent_simple(user_text)
                                tz_name = None
                                if isinstance(ctx, dict):
                                    tz_name = str(ctx.get("tz_name") or "") or None
                                text = _render_calendar_list_events(result=res, intent=intent, tz_name=tz_name)

                                _emit_summarizing("started")

                                # Trace for auditability/tests.
                                try:
                                    trace["intent"] = "calendar.query"
                                    trace["slots"] = {"date": (str(intent or "none") or "none")}
                                    trace["missing"] = []
                                    trace["next_action"] = "say_result"
                                    trace["safety"] = []
                                except Exception:
                                    pass
                                mini_ack = False
                                if _has_smalltalk_clause(user_text):
                                    mini_ack = True
                                    text = (str(text).rstrip() + "\n\nİsterseniz bununla ilgili konuşabiliriz.").strip()
                                text = _role_sanitize_text(text)
                                # Save recent events for deterministic disambiguation in later turns.
                                try:
                                    evs = res.get("events") if isinstance(res.get("events"), list) else []
                                    evs = [e for e in evs if isinstance(e, dict)]
                                    if isinstance(state, dict):
                                        state[_CALENDAR_LAST_EVENTS_KEY] = evs[:10]
                                except Exception:
                                    pass
                                try:
                                    if isinstance(state, dict):
                                        state[_DIALOG_STATE_KEY] = "AFTER_CALENDAR_STATUS"
                                        state["last_tool_used"] = name
                                except Exception:
                                    pass
                                try:
                                    self._events.publish(
                                        EventType.RESULT.value, {"text": text}, source="brain"
                                    )
                                except Exception:
                                    pass
                                _emit_summarizing("complete")
                                count_val = None
                                try:
                                    if isinstance(res, dict):
                                        count_val = int(res.get("count") or 0)
                                except Exception:
                                    count_val = None
                                shown = None
                                more = None
                                try:
                                    if isinstance(count_val, int):
                                        shown = min(3, max(0, count_val))
                                        more = max(0, count_val - shown)
                                except Exception:
                                    shown = None
                                    more = None
                                return BrainResult(
                                    kind="say",
                                    text=text,
                                    steps_used=step_idx,
                                    metadata={
                                        **_meta(transcript, raw=out_raw),
                                        **_std_metadata(
                                            ctx=ctx,
                                            state=state,
                                            action_type="list_events",
                                            requires_confirmation=False,
                                        ),
                                        "mini_ack": bool(mini_ack),
                                        "events_count": count_val,
                                        "events_shown": shown,
                                        "events_more": more,
                                    },
                                )

                        if name == "calendar.find_free_slots" and isinstance(obs, dict) and obs.get("ok") is True:
                            res = obs.get("result")
                            if isinstance(res, dict):
                                tz_name = None
                                if isinstance(ctx, dict):
                                    tz_name = str(ctx.get("tz_name") or "") or None
                                dur = 30
                                try:
                                    dur = int(params.get("duration_minutes") or 30)
                                except Exception:
                                    dur = 30
                                rendered = _render_calendar_free_slots(result=res, tz_name=tz_name, duration_minutes=dur)
                                rendered = _role_sanitize_text(rendered)
                                # Save pending slots menu for follow-up selection.
                                slots = []
                                if isinstance(res.get("slots"), list):
                                    slots = [s for s in res.get("slots") if isinstance(s, dict)]
                                try:
                                    if isinstance(state, dict):
                                        state[_PENDING_CHOICE_KEY] = {
                                            "menu_id": "free_slots",
                                            "default": "0",
                                            "duration": dur,
                                            "time_min": params.get("time_min"),
                                            "time_max": params.get("time_max"),
                                            "slots": slots[:3],
                                        }
                                        state[_DIALOG_STATE_KEY] = "PENDING_CHOICE"
                                        state["last_tool_used"] = name
                                except Exception:
                                    pass
                                try:
                                    self._events.publish(
                                        EventType.QUESTION.value, {"question": rendered}, source="brain"
                                    )
                                except Exception:
                                    pass
                                options: dict[str, str] = {"9": JarvisVoice.MENU_FREE_SLOTS["9"], "0": JarvisVoice.MENU_FREE_SLOTS["0"]}
                                try:
                                    for idx, s in enumerate(slots[:3], start=1):
                                        st = str(s.get("start") or "").strip()
                                        en = str(s.get("end") or "").strip()
                                        if st and en:
                                            options[str(idx)] = f"{st}–{en}"
                                except Exception:
                                    pass
                                return BrainResult(
                                    kind="ask_user",
                                    text=rendered,
                                    steps_used=step_idx,
                                    metadata={
                                        **_meta(transcript, raw=out_raw),
                                        **_std_metadata(
                                            ctx=ctx,
                                            state=state,
                                            menu_id="free_slots",
                                            options=options,
                                        ),
                                    },
                                )
                except Exception:
                    pass

                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(out_raw, ensure_ascii=False),
                    }
                )
                messages.append(
                    {
                        # Important: do NOT present tool output as a user message.
                        "role": "system",
                        "content": "TOOL_OBSERVATION: "
                        + json.dumps(observations[-1], ensure_ascii=False),
                    }
                )
                continue

        return BrainResult(
            kind="fail",
            text="max_steps_exceeded",
            steps_used=self._config.max_steps,
            metadata=_meta(transcript),
        )


def _summarize_policy(policy: Any) -> str:
    if policy is None:
        return ""
    try:
        summary = getattr(policy, "summary", None)
        if callable(summary):
            return str(summary())
    except Exception:
        pass
    try:
        if isinstance(policy, dict):
            return json.dumps(_mask_jsonable(policy), ensure_ascii=False)
    except Exception:
        pass
    return str(policy)


def _short_conversation(
    messages: list[dict[str, str]], *, max_messages: int, max_chars: int
) -> list[dict[str, str]]:
    tail = list(messages[-max_messages:])
    out: list[dict[str, str]] = []
    used = 0
    for m in tail:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        remaining = max(0, max_chars - used)
        if len(content) > remaining:
            content = content[: max(0, remaining - 1)] + "…"
        used += len(content)
        out.append({"role": role, "content": content})
        if used >= max_chars:
            break
    return out


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
    "set-cookie",
}


def _mask_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in _SENSITIVE_KEYS:
                masked[key] = "***"
            else:
                masked[key] = _mask_jsonable(v)
        return masked
    if isinstance(value, list):
        return [_mask_jsonable(v) for v in value]
    if isinstance(value, str):
        return value if len(value) <= 500 else (value[:499] + "…")
    return value


def _mask_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(m.get("role") or ""),
            "content": str(_mask_jsonable(m.get("content") or "")),
        }
        for m in messages
    ]


def _shorten_jsonable(value: Any, *, max_chars: int) -> Any:
    try:
        dumped = json.dumps(value, ensure_ascii=False)
    except Exception:
        dumped = str(value)
    if len(dumped) <= max_chars:
        return value
    return dumped[: max(0, max_chars - 1)] + "…"


def _meta(transcript: list[BrainTranscriptTurn], raw: Any = None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if raw is not None:
        meta["raw"] = raw
    if transcript:
        meta["transcript"] = [
            {
                "step": t.step,
                "messages": t.messages,
                "schema": t.schema,
                "output": t.output,
            }
            for t in transcript
        ]
    return meta
