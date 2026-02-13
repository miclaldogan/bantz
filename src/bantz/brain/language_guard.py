# SPDX-License-Identifier: MIT
"""
Language Guard — Post-validation for LLM output language (Issue #653).

The 3B Qwen model occasionally ignores the "SADECE TÜRKÇE konuş" system
prompt and returns Chinese (CJK), English, or mixed-language output.

This module provides a lightweight, zero-dependency language validation
layer that catches non-Turkish text *after* LLM generation so the caller
can retry or fall back to a deterministic Turkish message.

Design principles:
  - Pure functions, no LLM calls, no external deps
  - < 1 ms per call (regex + char counting)
  - Conservative: only reject text that is clearly non-Turkish
  - Turkish special chars (ıİğĞüÜşŞöÖçÇ) are considered valid
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple


# ============================================================================
# Unicode ranges
# ============================================================================

# CJK Unified Ideographs + Extensions + Compatibility
_CJK_RANGES = (
    ("\u4e00", "\u9fff"),  # CJK Unified Ideographs
    ("\u3400", "\u4dbf"),  # CJK Extension A
    ("\u2e80", "\u2eff"),  # CJK Radicals Supplement
    ("\u3000", "\u303f"),  # CJK Symbols & Punctuation
    ("\uf900", "\ufaff"),  # CJK Compatibility Ideographs
    ("\U00020000", "\U0002a6df"),  # CJK Extension B
)

# Japanese Hiragana + Katakana
_JAPANESE_RANGES = (
    ("\u3040", "\u309f"),  # Hiragana
    ("\u30a0", "\u30ff"),  # Katakana
    ("\u31f0", "\u31ff"),  # Katakana Phonetic Extensions
)

# Korean Hangul
_KOREAN_RANGES = (
    ("\uac00", "\ud7af"),  # Hangul Syllables
    ("\u1100", "\u11ff"),  # Hangul Jamo
    ("\u3130", "\u318f"),  # Hangul Compatibility Jamo
)

# Cyrillic
_CYRILLIC_RANGES = (
    ("\u0400", "\u04ff"),  # Cyrillic
    ("\u0500", "\u052f"),  # Cyrillic Supplement
)

# Arabic / Hebrew
_ARABIC_HEBREW_RANGES = (
    ("\u0600", "\u06ff"),  # Arabic
    ("\u0590", "\u05ff"),  # Hebrew
)

# Turkish-specific Latin characters (beyond ASCII)
_TURKISH_EXTRA_CHARS = set("ıİğĞüÜşŞöÖçÇâÂîÎûÛ")

# Common Turkish words that confirm the text is Turkish
_TURKISH_MARKERS = re.compile(
    r"\b(bir|ve|bu|de|da|için|ile|var|yok|değil|evet|hayır|"
    r"tamam|efendim|oldu|yapıldı|açıyorum|kapatıyorum|"
    r"oluşturdum|arama|sonuçları|hatırlatma|"
    r"merhaba|günaydın|iyi|nasıl|ne|nerede|ama|veya|"
    r"şey|çok|biraz|sonra|önce|şimdi)\b",
    re.IGNORECASE,
)


# ============================================================================
# Detection helpers
# ============================================================================


def _in_ranges(ch: str, ranges: tuple) -> bool:
    """Check if a character falls within any of the given Unicode ranges."""
    for lo, hi in ranges:
        if lo <= ch <= hi:
            return True
    return False


def _char_category(ch: str) -> str:
    """Classify a single character.

    Returns one of: 'cjk', 'japanese', 'korean', 'cyrillic',
    'arabic_hebrew', 'turkish_latin', 'latin', 'digit', 'space',
    'punctuation', 'other'.
    """
    if ch in _TURKISH_EXTRA_CHARS:
        return "turkish_latin"
    if _in_ranges(ch, _CJK_RANGES):
        return "cjk"
    if _in_ranges(ch, _JAPANESE_RANGES):
        return "japanese"
    if _in_ranges(ch, _KOREAN_RANGES):
        return "korean"
    if _in_ranges(ch, _CYRILLIC_RANGES):
        return "cyrillic"
    if _in_ranges(ch, _ARABIC_HEBREW_RANGES):
        return "arabic_hebrew"

    cat = unicodedata.category(ch)
    if cat.startswith("L"):
        # Any other letter character (ASCII Latin, extended Latin, etc.)
        return "latin"
    if cat.startswith("N"):
        return "digit"
    if cat.startswith("Z"):
        return "space"
    if cat.startswith("P") or cat.startswith("S"):
        return "punctuation"
    return "other"


# ============================================================================
# Public API
# ============================================================================


def count_language_chars(text: str) -> dict[str, int]:
    """Count characters by language category.

    Returns a dict like ``{"cjk": 12, "latin": 40, "turkish_latin": 5, …}``.
    """
    counts: dict[str, int] = {}
    for ch in text:
        cat = _char_category(ch)
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def has_cjk(text: str, threshold: int = 2) -> bool:
    """Return True if text contains ≥ *threshold* CJK/Japanese/Korean chars."""
    count = 0
    for ch in text:
        if _in_ranges(ch, _CJK_RANGES) or _in_ranges(ch, _JAPANESE_RANGES) or _in_ranges(ch, _KOREAN_RANGES):
            count += 1
            if count >= threshold:
                return True
    return False


def has_arabic_hebrew(text: str, threshold: int = 2) -> bool:
    """Return True if text contains ≥ *threshold* Arabic/Hebrew chars.

    Issue #1017: Dedicated fast-path detection for Arabic/Hebrew script,
    mirroring the existing ``has_cjk`` function pattern.
    """
    count = 0
    for ch in text:
        if _in_ranges(ch, _ARABIC_HEBREW_RANGES):
            count += 1
            if count >= threshold:
                return True
    return False


def cjk_ratio(text: str) -> float:
    """Fraction of non-whitespace characters that are CJK/J/K."""
    non_ws = [ch for ch in text if not ch.isspace()]
    if not non_ws:
        return 0.0
    cjk_count = sum(
        1 for ch in non_ws
        if _in_ranges(ch, _CJK_RANGES) or _in_ranges(ch, _JAPANESE_RANGES) or _in_ranges(ch, _KOREAN_RANGES)
    )
    return cjk_count / len(non_ws)


def turkish_confidence(text: str) -> float:
    """Estimate 0-1 confidence that text is Turkish.

    Heuristics:
    - Turkish marker words boost score
    - Turkish-specific chars (ı, ğ, ş, ç, ö, ü) boost score
    - CJK chars heavily penalise
    - Pure ASCII with no Turkish markers → low confidence
    """
    if not text or not text.strip():
        return 0.0

    counts = count_language_chars(text)
    total_letters = (
        counts.get("latin", 0)
        + counts.get("turkish_latin", 0)
        + counts.get("cjk", 0)
        + counts.get("japanese", 0)
        + counts.get("korean", 0)
        + counts.get("cyrillic", 0)
        + counts.get("arabic_hebrew", 0)
    )
    if total_letters == 0:
        return 0.5  # Digits / punctuation only — neutral

    # Base score from letter composition
    turkish_letters = counts.get("turkish_latin", 0)
    latin_letters = counts.get("latin", 0)
    cjk_letters = counts.get("cjk", 0) + counts.get("japanese", 0) + counts.get("korean", 0)
    foreign_letters = counts.get("cyrillic", 0) + counts.get("arabic_hebrew", 0)

    # Issue #999: Pure ASCII text (only latin letters, no Turkish-specific
    # chars) starts at a lower base score so that English text without any
    # Turkish markers is correctly flagged as non-Turkish.
    if turkish_letters == 0 and foreign_letters == 0 and cjk_letters == 0:
        # Pure ASCII latin — likely English
        score = 0.3
    else:
        score = 0.5

    # Turkish specific chars strongly boost
    if turkish_letters > 0:
        score += min(0.3, turkish_letters / total_letters)

    # Turkish marker words boost
    marker_matches = len(_TURKISH_MARKERS.findall(text))
    if marker_matches > 0:
        score += min(0.25, marker_matches * 0.05)

    # CJK heavily penalise
    if cjk_letters > 0:
        cjk_frac = cjk_letters / total_letters
        score -= min(0.8, cjk_frac * 1.5)

    # Foreign scripts penalise
    if foreign_letters > 0:
        score -= min(0.4, (foreign_letters / total_letters) * 0.8)

    return max(0.0, min(1.0, score))


def detect_language_issue(text: str) -> Optional[str]:
    """Detect language problems in LLM output.

    Returns a short reason string if the text is problematic,
    or ``None`` if the text looks acceptable (Turkish or neutral).

    Possible return values:
    - ``"cjk_detected"``  — Chinese/Japanese/Korean characters found
    - ``"cyrillic_detected"`` — Cyrillic script detected
    - ``"arabic_hebrew_detected"`` — Arabic/Hebrew script detected
    - ``"low_turkish_confidence"`` — text is likely non-Turkish
    - ``None`` — text appears Turkish or is too short to judge
    """
    if not text or len(text.strip()) < 3:
        return None  # Too short to judge

    # --- Fast path: CJK detection (most common Qwen failure mode) ---
    if has_cjk(text, threshold=2):
        return "cjk_detected"

    # --- Issue #1017: Arabic/Hebrew fast path (before full char scan) ---
    if has_arabic_hebrew(text, threshold=2):
        return "arabic_hebrew_detected"

    # --- Cyrillic detection ---
    counts = count_language_chars(text)
    if counts.get("cyrillic", 0) >= 3:
        return "cyrillic_detected"

    # --- Turkish confidence check ---
    # Only flag if text is long enough and has letters
    total_letters = (
        counts.get("latin", 0)
        + counts.get("turkish_latin", 0)
    )
    if total_letters >= 10:
        # Issue #999: Skip confidence check for URLs and code-like strings
        # — these are technical content, not human language to translate.
        _url_or_code = (
            "://" in text
            or text.strip().startswith("http")
            or "(" in text and ")" in text  # function call pattern
        )
        if _url_or_code:
            return None

        conf = turkish_confidence(text)
        # Issue #999: Raised threshold from 0.35 to 0.45 and lowered
        # base score for pure-ASCII text so that English sentences
        # like "Please schedule a meeting" are correctly detected.
        if conf < 0.45 and not _TURKISH_MARKERS.search(text):
            return "low_turkish_confidence"

    return None


def validate_turkish(
    text: str,
    fallback: str = "Efendim, isteğiniz işleniyor.",
) -> Tuple[str, bool]:
    """Validate that text is Turkish; return fallback if not.

    Args:
        text: LLM-generated text to validate.
        fallback: Deterministic Turkish message to return if validation
                  fails.

    Returns:
        Tuple of ``(validated_text, was_valid)``.
        If valid, ``validated_text == text`` and ``was_valid == True``.
        If invalid, ``validated_text == fallback`` and ``was_valid == False``.
    """
    issue = detect_language_issue(text)
    if issue is None:
        return text, True
    return fallback, False
