"""
ASR Turkish Autocorrect — Issue #430.

Post-processing layer for Whisper ASR output that normalizes
Turkish suffix variations and diacritic inconsistencies.

Problems solved:
- Time suffix variation:  'saat beşe' / 'saat beşte' / 'saat beş de' → 'saat beş'
- Diacritic loss:         'toplanti' → 'toplantı', 'guncelle' → 'güncelle'
- Suffix attachment:      'toplantıyı koy' → 'toplantı koy' (accusative strip)
- Common ASR mishearings: 'bence' → 'bantz' (brand name protection)

Usage::

    from bantz.voice.autocorrect import normalize_asr
    clean = normalize_asr("saat beşe toplanti koy")
    # → "saat beş toplantı koy"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────
# Diacritic Correction Table
# ─────────────────────────────────────────────────────────────────

# Common ASR outputs missing Turkish diacritics → correct form
_DIACRITIC_MAP: Dict[str, str] = {
    # Calendar/scheduling domain
    "toplanti": "toplantı",
    "toplantiyi": "toplantıyı",
    "toplantisi": "toplantısı",
    "etkinlik": "etkinlik",  # already correct — included for completeness
    "guncelle": "güncelle",
    "guncelleme": "güncelleme",
    "olustur": "oluştur",
    "olusturma": "oluşturma",
    "gorusme": "görüşme",
    "gorusmeyi": "görüşmeyi",
    "gorev": "görev",
    "takvim": "takvim",
    "calisma": "çalışma",
    "calis": "çalış",
    "randevu": "randevu",
    "degistir": "değiştir",
    "iptal": "iptal",
    # Numbers (diacritic variants)
    "bes": "beş",
    "uc": "üç",
    "dort": "dört",
    "alti": "altı",
    # Time expressions
    "bugun": "bugün",
    "yarin": "yarın",
    "aksam": "akşam",
    "ogle": "öğle",
    "sabah": "sabah",
    "saat": "saat",
    # Common verbs
    "ekle": "ekle",
    "sil": "sil",
    "goster": "göster",
    "soyle": "söyle",
    "dinle": "dinle",
    "oku": "oku",
    "gonder": "gönder",
    "cevapla": "cevapla",
    # System
    "bilgisayar": "bilgisayar",
    "kapat": "kapat",
    "ac": "aç",
    "acik": "açık",
    "kapali": "kapalı",
}

# Build case-insensitive lookup
_DIACRITIC_LOWER: Dict[str, str] = {k.lower(): v for k, v in _DIACRITIC_MAP.items()}


# ─────────────────────────────────────────────────────────────────
# Turkish Time Suffix Normalization
# ─────────────────────────────────────────────────────────────────

# Turkish numbers for time (1-12 + common large hour numbers)
_TURKISH_NUMBERS = {
    "bir": "bir", "iki": "iki", "üç": "üç", "uc": "üç",
    "dört": "dört", "dort": "dört",
    "beş": "beş", "bes": "beş",
    "altı": "altı", "alti": "altı",
    "yedi": "yedi",
    "sekiz": "sekiz",
    "dokuz": "dokuz",
    "on": "on", "onbir": "on bir", "oniki": "on iki",
}

# Suffixes that Whisper attaches to Turkish time words
# e.g. "beşe", "beşte", "beşten", "beşde", "beş de"
_TIME_SUFFIX_RE = re.compile(
    r"\b(saat\s+)"  # "saat " prefix
    r"(\w+?)"       # number word
    r"(['\u2019]?(?:e|te|de|ten|den|da|ta|ye|a))\b",  # suffix
    re.IGNORECASE,
)

# Digit-based time suffixes: "5'e", "5'te", "5 de", "14:00'de"
_DIGIT_TIME_SUFFIX_RE = re.compile(
    r"\b(saat\s+)"
    r"(\d{1,2}(?::\d{2})?)"   # digits or HH:MM
    r"(['\u2019]?(?:e|te|de|ten|den|da|ta|ye|a))\b",
    re.IGNORECASE,
)

# Standalone suffix strip (without "saat" prefix): "beşte", "üçe"
# More aggressive — only for known number words
_KNOWN_NUMBER_SUFFIX_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in _TURKISH_NUMBERS) + r")"
    r"(['\u2019]?(?:e|te|de|ten|den|da|ta|ye|a))\b",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────
# Accusative Suffix Strip (object marker -yı/-yi/-yu/-yü/-ı/-i)
# ─────────────────────────────────────────────────────────────────

# "toplantıyı koy" → "toplantı koy"
# Only for calendar/scheduling domain nouns
_ACCUSATIVE_NOUNS = {
    "toplantıyı": "toplantı",
    "etkinliği": "etkinlik",
    "görüşmeyi": "görüşme",
    "görevi": "görev",
    "randevuyu": "randevu",
    "toplantısını": "toplantı",
    "maili": "mail",
    "mesajı": "mesaj",
}
_ACCUSATIVE_LOWER: Dict[str, str] = {k.lower(): v for k, v in _ACCUSATIVE_NOUNS.items()}


# ─────────────────────────────────────────────────────────────────
# Brand Name Protection
# ─────────────────────────────────────────────────────────────────

_BRAND_CORRECTIONS: Dict[str, str] = {
    "bence": "bence",  # intentional — don't change common word
    "banc": "bantz",
    "bants": "bantz",
    "banz": "bantz",
    "bants'a": "bantz",
    "bants'ı": "bantz",
}


# ─────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────

@dataclass
class AutocorrectResult:
    """Result of ASR autocorrection."""
    original: str
    corrected: str
    corrections: List[Tuple[str, str]] = field(default_factory=list)  # (old, new)

    @property
    def was_changed(self) -> bool:
        return self.original != self.corrected

    @property
    def correction_count(self) -> int:
        return len(self.corrections)


# ─────────────────────────────────────────────────────────────────
# Main API
# ─────────────────────────────────────────────────────────────────

def normalize_asr(text: str) -> str:
    """
    Normalize Turkish ASR output — convenience wrapper.

    Returns only the corrected text.
    """
    return autocorrect_asr(text).corrected


def autocorrect_asr(text: str) -> AutocorrectResult:
    """
    Full ASR autocorrection with correction tracking.

    Pipeline:
    1. Diacritic correction (word-level)
    2. Time suffix normalization ('saat beşte' → 'saat beş')
    3. Accusative suffix strip ('toplantıyı' → 'toplantı')
    4. Brand name fixes
    5. Whitespace cleanup
    """
    if not text:
        return AutocorrectResult(original="", corrected="")

    original = text
    corrections: List[Tuple[str, str]] = []
    result = text

    # 1. Diacritic correction (word by word)
    result = _fix_diacritics(result, corrections)

    # 2. Time suffix normalization
    result = _fix_time_suffixes(result, corrections)

    # 3. Accusative suffix strip
    result = _fix_accusatives(result, corrections)

    # 4. Brand name fixes
    result = _fix_brand_names(result, corrections)

    # 5. Whitespace cleanup
    result = re.sub(r"\s+", " ", result).strip()

    return AutocorrectResult(original=original, corrected=result, corrections=corrections)


# ─────────────────────────────────────────────────────────────────
# Pipeline Steps
# ─────────────────────────────────────────────────────────────────

def _fix_diacritics(text: str, corrections: List[Tuple[str, str]]) -> str:
    """Fix missing Turkish diacritics word by word."""
    words = text.split()
    out = []
    for w in words:
        lower = w.lower()
        if lower in _DIACRITIC_LOWER and lower != _DIACRITIC_LOWER[lower]:
            fixed = _DIACRITIC_LOWER[lower]
            # Preserve original casing for first char
            if w[0].isupper():
                fixed = fixed[0].upper() + fixed[1:]
            corrections.append((w, fixed))
            out.append(fixed)
        else:
            out.append(w)
    return " ".join(out)


def _fix_time_suffixes(text: str, corrections: List[Tuple[str, str]]) -> str:
    """Strip locative/dative/ablative suffixes from time expressions."""

    def _strip_suffix_word(match: re.Match) -> str:
        prefix = match.group(1)  # "saat "
        number = match.group(2)  # "beş" / "5"
        suffix = match.group(3)  # "te" / "e" / "de"
        # Normalize the number word if it's a known variant
        number_lower = number.lower()
        if number_lower in _TURKISH_NUMBERS:
            number = _TURKISH_NUMBERS[number_lower]
        corrections.append((match.group(0), f"{prefix}{number}"))
        return f"{prefix}{number}"

    result = _TIME_SUFFIX_RE.sub(_strip_suffix_word, text)

    def _strip_digit_suffix(match: re.Match) -> str:
        prefix = match.group(1)
        digits = match.group(2)
        corrections.append((match.group(0), f"{prefix}{digits}"))
        return f"{prefix}{digits}"

    result = _DIGIT_TIME_SUFFIX_RE.sub(_strip_digit_suffix, result)
    return result


def _fix_accusatives(text: str, corrections: List[Tuple[str, str]]) -> str:
    """Strip accusative suffixes from scheduling nouns."""
    words = text.split()
    out = []
    for w in words:
        lower = w.lower()
        if lower in _ACCUSATIVE_LOWER:
            fixed = _ACCUSATIVE_LOWER[lower]
            if w[0].isupper():
                fixed = fixed[0].upper() + fixed[1:]
            corrections.append((w, fixed))
            out.append(fixed)
        else:
            out.append(w)
    return " ".join(out)


def _fix_brand_names(text: str, corrections: List[Tuple[str, str]]) -> str:
    """Fix ASR mishearings of 'Bantz' brand name."""
    words = text.split()
    out = []
    for w in words:
        lower = w.lower()
        if lower in _BRAND_CORRECTIONS and _BRAND_CORRECTIONS[lower] != lower:
            fixed = _BRAND_CORRECTIONS[lower]
            corrections.append((w, fixed))
            out.append(fixed)
        else:
            out.append(w)
    return " ".join(out)
