from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PlanItem:
    label: str
    duration_minutes: Optional[int] = None
    location: Optional[str] = None


@dataclass
class PlanDraft:
    title: str
    goal: Optional[str]
    day_hint: Optional[str]
    time_of_day: Optional[str]
    items: list[PlanItem]
    confidence: float = 0.6

    def plan_window(self) -> str:
        day = str(self.day_hint or "").strip()
        tod = str(self.time_of_day or "").strip()
        if day and tod:
            return f"{day}_{tod}"
        if day:
            return day
        if tod:
            return tod
        return "unspecified"

    def render_preview_tr(self) -> str:
        window = self.plan_window()
        header = f"Plan taslağı ({_format_window_tr(window)})"
        lines: list[str] = [header]
        for i, item in enumerate(self.items, start=1):
            label = str(item.label or "").strip() or "(madde)"
            dur = item.duration_minutes
            if isinstance(dur, int) and dur > 0:
                lines.append(f"{i}. {label} — {dur} dk")
            else:
                lines.append(f"{i}. {label}")
        return "\n".join(lines).strip()


def plan_draft_to_dict(draft: PlanDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "goal": draft.goal,
        "day_hint": draft.day_hint,
        "time_of_day": draft.time_of_day,
        "confidence": float(draft.confidence or 0.0),
        "items": [
            {
                "label": i.label,
                "duration_minutes": i.duration_minutes,
                "location": i.location,
            }
            for i in (draft.items or [])
            if isinstance(i, PlanItem)
        ],
    }


def plan_draft_from_dict(raw: dict[str, Any]) -> PlanDraft:
    if not isinstance(raw, dict):
        return PlanDraft(title="Gün planı", goal=None, day_hint=None, time_of_day=None, items=[])

    items_raw = raw.get("items")
    items: list[PlanItem] = []
    if isinstance(items_raw, list):
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label") or "").strip()
            if not label:
                continue
            dur = it.get("duration_minutes")
            try:
                duration_minutes = int(dur) if dur is not None else None
            except Exception:
                duration_minutes = None
            location = str(it.get("location") or "").strip() or None
            items.append(PlanItem(label=label, duration_minutes=duration_minutes, location=location))

    conf = raw.get("confidence")
    try:
        confidence = float(conf) if conf is not None else 0.6
    except Exception:
        confidence = 0.6

    return PlanDraft(
        title=str(raw.get("title") or "Gün planı").strip() or "Gün planı",
        goal=str(raw.get("goal") or "").strip() or None,
        day_hint=str(raw.get("day_hint") or "").strip() or None,
        time_of_day=str(raw.get("time_of_day") or "").strip() or None,
        items=items,
        confidence=confidence,
    )


def apply_plan_edit_instruction(draft: PlanDraft, instruction: str) -> PlanDraft:
    """Deterministic minimal editor.

    Supported edits:
    - "şunu 30 dk yap" -> set first item's duration to 30
    """

    if not isinstance(draft, PlanDraft):
        return draft

    t = _norm(instruction)
    new_dur = _extract_single_duration_minutes(t)
    if new_dur is None:
        return draft
    if not isinstance(draft.items, list) or not draft.items:
        return draft

    updated_items: list[PlanItem] = []
    for idx, it in enumerate(draft.items):
        if not isinstance(it, PlanItem):
            continue
        if idx == 0:
            updated_items.append(
                PlanItem(label=it.label, duration_minutes=int(new_dur), location=it.location)
            )
        else:
            updated_items.append(it)

    return PlanDraft(
        title=draft.title,
        goal=draft.goal,
        day_hint=draft.day_hint,
        time_of_day=draft.time_of_day,
        items=updated_items,
        confidence=float(draft.confidence or 0.0),
    )


_DURATION_RE = re.compile(
    r"(?P<num>\d{1,3})\s*(?P<unit>saat|sa|dk|dakika)\b",
    re.IGNORECASE,
)


def looks_like_planning_prompt(user_text: str) -> bool:
    t = _norm(user_text)
    if not t:
        return False

    # Explicit planning commands.
    if "schedule my day" in t:
        return True

    has_plan_word = "plan" in t
    has_plan_verb = any(v in t for v in [" plan yap", " planla", " plan olustur", " plan oluştur", " plan hazirla", " plan hazırla"])
    if has_plan_word and has_plan_verb:
        return True

    # Heuristic: multiple duration items + "ekle" or plus-sign => likely planning.
    dur_count = len(list(_DURATION_RE.finditer(t)))
    if dur_count >= 2 and ("+" in t or " ekle" in t):
        return True

    return False


def build_plan_draft_from_text(user_text: str, *, ctx: Optional[dict[str, Any]] = None) -> PlanDraft:
    _ = ctx
    t = _norm(user_text)
    day_hint, tod = _detect_window(t)

    parsed_items = _parse_duration_items(t)
    if parsed_items:
        items = parsed_items
        confidence = 0.8
    else:
        items = _default_items(tod=tod)
        confidence = 0.65

    title = "Gün planı"
    goal = None
    if day_hint == "tomorrow":
        title = "Yarın planı"
    elif day_hint == "today":
        title = "Bugün planı"

    if tod == "morning":
        title = (title + " (sabah)").strip()
    elif tod == "evening":
        title = (title + " (akşam)").strip()

    return PlanDraft(
        title=title,
        goal=goal,
        day_hint=day_hint,
        time_of_day=tod,
        items=items,
        confidence=float(confidence),
    )


def _detect_window(t: str) -> tuple[Optional[str], Optional[str]]:
    day_hint: Optional[str] = None
    tod: Optional[str] = None

    if any(w in t for w in ["bugun", "bugün"]):
        day_hint = "today"
    if any(w in t for w in ["yarin", "yarın"]):
        day_hint = "tomorrow"

    if any(w in t for w in ["sabah"]):
        tod = "morning"
    if any(w in t for w in ["aksam", "akşam"]):
        tod = "evening"

    return day_hint, tod


def _parse_duration_items(t: str) -> list[PlanItem]:
    # Examples:
    # - "yarın sabah 2 saat spor + 1 saat okuma ekle"
    # - "2 saat spor ve 30 dk yürüyüş"
    items: list[PlanItem] = []

    matches = list(_DURATION_RE.finditer(t))
    if not matches:
        return items

    for i, m in enumerate(matches):
        num = int(m.group("num"))
        unit = str(m.group("unit") or "").lower()
        minutes = num * 60 if unit.startswith("sa") or unit.startswith("saat") else num

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        chunk = t[start:end]

        # Strip common separators/verbs.
        chunk = chunk.strip()
        chunk = re.sub(r"^[+\-,;:.\s]+", "", chunk)
        chunk = re.sub(r"\b(ekle|koy|koy\s+bakalim|koy\s+bakalım)\b", "", chunk).strip()
        chunk = re.split(r"\b(ve)\b|\+", chunk, maxsplit=1)[0].strip()

        label = chunk.strip()
        if not label:
            continue

        # Light cleanup.
        label = re.sub(r"\s+", " ", label)

        items.append(PlanItem(label=label, duration_minutes=minutes))

    return items


def _default_items(*, tod: Optional[str]) -> list[PlanItem]:
    if tod == "morning":
        return [
            PlanItem(label="Güne hazırlık", duration_minutes=20),
            PlanItem(label="Derin çalışma", duration_minutes=90),
            PlanItem(label="Kısa yürüyüş / mola", duration_minutes=20),
            PlanItem(label="İletişim / mesaj kontrolü", duration_minutes=20),
        ]
    if tod == "evening":
        return [
            PlanItem(label="Günün kapanışı", duration_minutes=15),
            PlanItem(label="Hafif egzersiz", duration_minutes=30),
            PlanItem(label="Okuma / öğrenme", duration_minutes=45),
        ]
    return [
        PlanItem(label="Öncelik belirleme", duration_minutes=10),
        PlanItem(label="Derin çalışma", duration_minutes=120),
        PlanItem(label="Kısa mola", duration_minutes=15),
        PlanItem(label="Gün değerlendirmesi", duration_minutes=10),
    ]


def _format_window_tr(window: str) -> str:
    w = str(window or "").strip()
    if w == "today":
        return "bugün"
    if w == "tomorrow":
        return "yarın"
    if w == "morning":
        return "sabah"
    if w == "evening":
        return "akşam"
    if w == "today_morning":
        return "bugün sabah"
    if w == "today_evening":
        return "bugün akşam"
    if w == "tomorrow_morning":
        return "yarın sabah"
    if w == "tomorrow_evening":
        return "yarın akşam"
    if w == "unspecified":
        return "genel"
    return w


def _norm(s: str) -> str:
    return str(s or "").strip().lower()


def _extract_single_duration_minutes(t: str) -> Optional[int]:
    m = _DURATION_RE.search(t or "")
    if not m:
        return None
    try:
        num = int(m.group("num"))
    except Exception:
        return None
    unit = str(m.group("unit") or "").lower()
    minutes = num * 60 if unit.startswith("sa") or unit.startswith("saat") else num
    if minutes <= 0:
        return None
    return int(minutes)
