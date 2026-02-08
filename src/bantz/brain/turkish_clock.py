"""Turkish Clock-Time Parsing (Issue #419).

Rule-based parser for Turkish spoken clock-time expressions.

Problem: 3B model inconsistently parses "beşe" as 05:00 vs 17:00.
Solution: Deterministic Python-side parsing with PM default for hours 1–6.

This module converts Turkish word-based clock references to HH:MM:
  "beşe"        → "17:00"  (PM default, hours 1-6)
  "sabah beşte" → "05:00"  (explicit AM)
  "akşam altıda"→ "18:00"  (explicit PM)
  "beş buçukta" → "17:30"  (half past)
  "dokuza"      → "09:00"  (7-12 kept as-is)
  "saat 5"      → "17:00"  (digit + PM default)
"""

from __future__ import annotations

import re
from typing import Optional

# ── Turkish number → int (1-12 for clock hours) ──────────────────────────
_TR_HOUR_WORDS: dict[str, int] = {
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "uc": 3,
    "dört": 4,
    "dort": 4,
    "beş": 5,
    "bes": 5,
    "altı": 6,
    "alti": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "onbir": 11,
    "on bir": 11,
    "oniki": 12,
    "on iki": 12,
}

# ── Explicit inflected-form → hour lookup ─────────────────────────────────
# Turkish has consonant mutations (t→d, k→ğ) and vowel harmony suffixes.
# Instead of complex regex, enumerate ALL real forms.
_INFLECTED_FORMS: dict[str, int] = {}


def _register_forms() -> None:
    """Build lookup from all inflected forms to base hour value."""
    # (base_word, hour, list_of_all_surface_forms)
    entries = [
        ("bir",   1,  ["bir", "bire", "birde", "birden", "biri"]),
        ("iki",   2,  ["iki", "ikiye", "ikide", "ikiden", "ikiyi"]),
        ("üç",    3,  ["üç", "üçe", "üçte", "üçten", "üçü",
                        "uc", "uce", "ucte", "ucten", "ucu"]),
        ("dört",  4,  ["dört", "dörde", "dörtte", "dörtten", "dördü",
                        "dort", "dorde", "dortte", "dortten", "dordu"]),
        ("beş",   5,  ["beş", "beşe", "beşte", "beşten", "beşi",
                        "bes", "bese", "beste", "besten", "besi"]),
        ("altı",  6,  ["altı", "altıya", "altıda", "altıdan", "altıyı",
                        "alti", "altiya", "altida", "altidan", "altiyi"]),
        ("yedi",  7,  ["yedi", "yediye", "yedide", "yediden", "yediyi"]),
        ("sekiz", 8,  ["sekiz", "sekize", "sekizde", "sekizden", "sekizi"]),
        ("dokuz", 9,  ["dokuz", "dokuza", "dokuzda", "dokuzdan", "dokuzu"]),
        ("on",    10, ["on", "ona", "onda", "ondan", "onu"]),
        ("onbir", 11, ["onbir", "onbire", "onbirde", "onbirden", "onbiri",
                        "on bir", "on bire", "on birde", "on birden", "on biri"]),
        ("oniki", 12, ["oniki", "onikiye", "onikide", "onikiden", "onikiyi",
                        "on iki", "on ikiye", "on ikide", "on ikiden", "on ikiyi"]),
    ]
    for _, hour, forms in entries:
        for form in forms:
            _INFLECTED_FORMS[form.lower()] = hour


_register_forms()

# "saat 5", "saat 17"
_SAAT_DIGIT_RE = re.compile(r"saat\s+(\d{1,2})(?:\s+buçuk)?", re.IGNORECASE)

# AM/PM context markers
_AM_MARKERS = re.compile(r"\bsabah\b", re.IGNORECASE)
_PM_MARKERS = re.compile(r"\bakşam\b|\baksam\b|\bgece\b", re.IGNORECASE)

# "buçuk" (half past) detection — also match "buçukta", "buçuktan" etc.
_BUCUK_RE = re.compile(r"\bbuçuk\b|\bbucuk\b|\bbuçukta\b|\bbucukta\b", re.IGNORECASE)

# "çeyrek" (quarter) detection — "üçü çeyrek geçe" = 15:15
_CEYREK_GECE_RE = re.compile(r"\bçeyrek\s*geçe\b|\bceyrek\s*gece\b", re.IGNORECASE)
_CEYREK_KALA_RE = re.compile(r"\bçeyrek\s*kala\b|\bceyrek\s*kala\b", re.IGNORECASE)

# Context words that should NOT be treated as hour references
_CONTEXT_WORDS = frozenset({
    "sabah", "akşam", "aksam", "gece", "saat", "buçuk", "bucuk",
    "buçukta", "bucukta", "çeyrek", "ceyrek", "geçe", "kala",
    "yarın", "yarin", "bugün", "bugun", "toplantı", "toplanti",
    "randevu", "koşu", "kosu", "yemek", "gel", "git", "koy",
    "ekle", "biter", "başla", "basla", "hazır", "hazir", "ol",
    "kadar", "buluş", "bulus", "buluşalım", "bulusulim",
})


def _apply_pm_default(hour: int, text: str) -> int:
    """Apply PM default rule for ambiguous hours 1-6.

    Rules (Issue #312):
    - Hours 1-6 without "sabah" → PM (+12)
    - Hours 1-6 with "sabah"   → AM (as-is)
    - Hours 1-6 with "akşam"   → PM (+12)
    - Hours 7-12               → as-is (no default shift)
    - Hours 13-23              → already 24h, no shift
    """
    if hour > 12:
        return hour  # already 24h

    has_am = bool(_AM_MARKERS.search(text))
    has_pm = bool(_PM_MARKERS.search(text))

    if has_am:
        return hour  # explicit morning
    if has_pm:
        return hour + 12 if hour <= 12 else hour

    # Ambiguous: apply PM default for 1-6 only
    if 1 <= hour <= 6:
        return hour + 12
    return hour  # 7-12 kept as-is


def parse_hhmm_turkish(text: str) -> Optional[str]:
    """Parse Turkish clock-time expression to HH:MM string.

    This is the main entry point. It handles:
    - Word-based: "beşe", "altıda", "üçte", "onbire"
    - With prefix: "saat beş", "saat 5"
    - Half past: "beş buçuk", "saat beş buçuk"
    - Quarter: "üçü çeyrek geçe" (15:15), "beşe çeyrek kala" (16:45)
    - AM/PM markers: "sabah beşte" → 05:00, "akşam altıda" → 18:00
    - Digit hours: "saat 5" → 17:00 (PM default)

    Returns:
        "HH:MM" string or None if no clock-time found.
    """
    if not text:
        return None

    t = text.strip().lower()

    # ── Try "saat <digit>" first ──────────────────────────────────────
    m = _SAAT_DIGIT_RE.search(t)
    if m:
        raw_hour = int(m.group(1))
        if 0 <= raw_hour <= 23:
            hour = _apply_pm_default(raw_hour, t) if raw_hour <= 12 else raw_hour
            minute = 30 if _BUCUK_RE.search(t) else 0
            hour = hour % 24
            return f"{hour:02d}:{minute:02d}"

    # ── Try "saat <word>" ─────────────────────────────────────────────
    # Scan for "saat" followed by a known Turkish hour word
    saat_match = _match_saat_word(t)
    if saat_match is not None:
        raw_hour = saat_match
        hour = _apply_pm_default(raw_hour, t)
        minute = 30 if _BUCUK_RE.search(t) else 0
        hour = hour % 24
        return f"{hour:02d}:{minute:02d}"

    # ── Try standalone Turkish word (with suffix): "beşe", "altıda" ───
    hour_val = _extract_hour_from_tokens(t)
    if hour_val is not None:
        # Check for "çeyrek geçe" / "çeyrek kala"
        if _CEYREK_GECE_RE.search(t):
            hour = _apply_pm_default(hour_val, t)
            hour = hour % 24
            return f"{hour:02d}:15"
        if _CEYREK_KALA_RE.search(t):
            # "beşe çeyrek kala" → 4:45 (one hour before, +45 min)
            target_hour = _apply_pm_default(hour_val, t)
            target_hour = (target_hour - 1) % 24
            return f"{target_hour:02d}:45"

        hour = _apply_pm_default(hour_val, t)
        minute = 30 if _BUCUK_RE.search(t) else 0
        hour = hour % 24
        return f"{hour:02d}:{minute:02d}"

    return None


def _match_saat_word(text: str) -> Optional[int]:
    """Match 'saat <Turkish-word>' pattern and return hour value."""
    idx = text.find("saat ")
    if idx < 0:
        return None
    rest = text[idx + 5:].strip()
    # Try bigram first ("saat on bir")
    words = rest.split()
    if len(words) >= 2:
        bigram = f"{words[0]} {words[1]}"
        if bigram in _INFLECTED_FORMS:
            return _INFLECTED_FORMS[bigram]
    # Try single word
    if words:
        w = words[0]
        if w in _INFLECTED_FORMS:
            return _INFLECTED_FORMS[w]
    return None


def _extract_hour_from_tokens(text: str) -> Optional[int]:
    """Extract hour value from Turkish tokens in text.

    Uses explicit inflected-form lookup table (handles consonant mutations
    like dört→dörde, üç→üçü correctly).
    """
    words = text.split()

    # First try bigrams (for "on bir", "on iki" and their forms)
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i + 1]}"
        if bigram in _INFLECTED_FORMS:
            return _INFLECTED_FORMS[bigram]

    # Then try single tokens
    for word in words:
        if word in _CONTEXT_WORDS:
            continue
        if word in _INFLECTED_FORMS:
            return _INFLECTED_FORMS[word]

    return None


def post_process_slot_time(
    slot_time: Optional[str],
    user_text: str,
) -> Optional[str]:
    """Post-process the LLM's slot time using rule-based parsing.

    If the LLM returned a slot time, validate it against rule-based parsing.
    If rule-based and LLM disagree on AM/PM for hours 1-6, prefer rule-based.

    If slot_time is None/empty, try rule-based parsing as fallback.

    Args:
        slot_time: The time string from LLM slots (e.g., "05:00", "17:00", None)
        user_text: The original user utterance

    Returns:
        Corrected HH:MM string, or the original slot_time if no correction needed.
    """
    rule_based = parse_hhmm_turkish(user_text)

    if not slot_time:
        return rule_based  # LLM didn't parse → use rule-based

    # If rule-based also found nothing, trust LLM
    if not rule_based:
        return slot_time

    # Both have values — check for AM/PM disagreement
    try:
        llm_hour = int(slot_time.split(":")[0])
        rb_hour = int(rule_based.split(":")[0])
    except (ValueError, IndexError):
        return slot_time

    # If they agree on hour (or differ by <2h), keep LLM
    if abs(llm_hour - rb_hour) <= 1:
        return slot_time

    # Disagree: check if this is a 1-6 AM/PM issue
    # If one is AM and other is PM variant of same base hour, prefer rule-based
    if abs(llm_hour - rb_hour) == 12:
        return rule_based  # Classic AM/PM flip — trust rule-based

    # Otherwise keep rule-based (it's deterministic)
    return rule_based
