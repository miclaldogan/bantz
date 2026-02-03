"""VoiceStyle: Jarvis-like persona consistency layer.

This module provides deterministic formatting for Jarvis persona responses.
Key principles:
- "Efendim" max 1x per response (not in every line)
- Empathy before menu (one human sentence)
- Natural, conversational menu labels
- Variation bank with deterministic selection (hash-based, not random)
- Turkish language with warm formality

The module does NOT use LLM - it's a deterministic style engine.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional


def _pick_variant(variants: list[str], seed: str) -> str:
    """Deterministically pick a variant based on seed hash.
    
    Same seed always returns same variant (test-stable).
    Different seeds give variety (no robot feel).
    
    Uses SHA-256 instead of MD5 for better security practices.
    """
    if not variants:
        return ""
    if len(variants) == 1:
        return variants[0]
    # Use SHA-256 instead of MD5 for security best practices
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return variants[h % len(variants)]


class JarvisVoice:
    """Jarvis persona - warm, concise, human."""

    # ─────────────────────────────────────────────────────────────
    # Variation Banks (deterministik seçim için)
    # ─────────────────────────────────────────────────────────────

    # Smalltalk giriş empati cümleleri
    EMPATHY_INTRO = [
        "Anlaşıldı. Enerji düşük gibi.",
        "Tamam. Bugün mod düşük.",
        "Anladım. Uykun ağır basıyor.",
    ]

    # Smalltalk "ne yapalım" sorusu
    WHAT_TO_DO = [
        "Ne yapalım?",
        "Nasıl yardımcı olayım?",
        "Ne tercih edersin?",
    ]

    # İptal/vazgeç varyasyonları
    CANCEL_VARIANTS = [
        "Tamam, vazgeçtim.",
        "Anlaşıldı, iptal.",
        "Peki, bırakıyorum.",
    ]

    # Onay reprompt varyasyonları
    CONFIRM_REPROMPT = [
        "1 mi 0 mı?",
        "Evet için 1, hayır için 0.",
        "Onay mı iptal mi? (1/0)",
    ]

    # ─────────────────────────────────────────────────────────────
    # Menü Label'ları (daha doğal)
    # ─────────────────────────────────────────────────────────────

    MENU_STAGE1 = {
        "1": "Sadece durumumu söyle",
        "2": "Hafifletme öner",
        "0": "Boşver",
    }

    MENU_STAGE2 = {
        "1": "Yarın daha yumuşak yap",
        "2": "60 dk mola ekle",
        "3": "En erken boşluk neresi?",
        "0": "Vazgeç",
    }

    MENU_FREE_SLOTS = {
        "9": "Süre: 60 dk",
        "0": "Vazgeç",
    }

    MENU_UNKNOWN = {
        "1": "Takvim",
        "2": "Sohbet/destek",
        "0": "Boşver",
    }

    # ─────────────────────────────────────────────────────────────
    # Core Formatters
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def empathy_intro(seed: str = "default") -> str:
        """Get an empathy intro line for smalltalk."""
        return _pick_variant(JarvisVoice.EMPATHY_INTRO, seed)

    @staticmethod
    def what_to_do(seed: str = "default") -> str:
        """Get a 'what to do' question."""
        return _pick_variant(JarvisVoice.WHAT_TO_DO, seed)

    @staticmethod
    def cancel_msg(seed: str = "default") -> str:
        """Get a cancel confirmation message."""
        return _pick_variant(JarvisVoice.CANCEL_VARIANTS, seed)

    @staticmethod
    def confirm_reprompt(seed: str = "default") -> str:
        """Get a confirmation reprompt message."""
        return _pick_variant(JarvisVoice.CONFIRM_REPROMPT, seed)

    @staticmethod
    def format_stage1_menu(seed: str = "default") -> str:
        """Format smalltalk stage1 menu with empathy intro."""
        empathy = JarvisVoice.empathy_intro(seed)
        question = JarvisVoice.what_to_do(seed + "_q")
        m = JarvisVoice.MENU_STAGE1
        return "\n".join([
            empathy,
            question,
            f"1. {m['1']}",
            f"2. {m['2']}",
            f"0. {m['0']}",
        ])

    @staticmethod
    def format_stage2_menu(seed: str = "default") -> str:
        """Format smalltalk stage2 menu."""
        m = JarvisVoice.MENU_STAGE2
        return "\n".join([
            "Hangi tür hafifletme?",
            f"1. {m['1']}",
            f"2. {m['2']}",
            f"3. {m['3']}",
            f"0. {m['0']}",
        ])

    @staticmethod
    def format_free_slots_menu(
        slots: list[tuple[str, str]],
        duration_minutes: int,
        seed: str = "default",
    ) -> str:
        """Format free slots menu with time slots."""
        lines = [f"{duration_minutes} dk için uygun boşluklar:"]
        for idx, (start, end) in enumerate(slots[:3], start=1):
            lines.append(f"{idx}. {start}–{end}")
        m = JarvisVoice.MENU_FREE_SLOTS
        lines.append(f"9. {m['9']}")
        lines.append(f"0. {m['0']}")
        return "\n".join(lines)

    @staticmethod
    def format_unknown_menu(seed: str = "default") -> str:
        """Format unknown route menu."""
        m = JarvisVoice.MENU_UNKNOWN
        return "\n".join([
            "Takvim mi sohbet mi?",
            f"1. {m['1']}",
            f"2. {m['2']}",
            f"0. {m['0']}",
        ])

    @staticmethod
    def format_confirmation(
        summary: str,
        start_time: str,
        end_time: str,
        seed: str = "default",
    ) -> str:
        """Format event creation confirmation - Jarvis style."""
        return f'Efendim, takvime {start_time}–{end_time} "{summary}" ekliyorum. Onaylıyor musunuz? (1/0)'

    @staticmethod
    def format_event_added(
        summary: str,
        start_time: str,
        end_time: str,
    ) -> str:
        """Format event added confirmation."""
        return f"Eklendi: {start_time}–{end_time} | {summary}"

    @staticmethod
    def format_dry_run(
        summary: str,
        start_time: str,
        end_time: str,
    ) -> str:
        """Format dry-run confirmation."""
        return f"Dry-run: '{summary}' {start_time}–{end_time} eklenecekti."

    @staticmethod
    def format_list_events(
        count: int,
        events: list[tuple[str, str, str]],  # (start, end, summary)
        intent: Optional[str] = None,
    ) -> str:
        """Format calendar list events result."""
        if count == 0:
            if intent == "evening":
                return "Bu akşam için plan görünmüyor."
            return "Bu aralıkta plan görünmüyor."
        
        lines = [f"{count} plan var:"]
        shown = 3
        for start, end, summary in events[:shown]:
            if start and end:
                lines.append(f"- {start}–{end} | {summary}")
            else:
                lines.append(f"- {summary}")
        hidden = count - shown
        if hidden > 0:
            lines.append(f"(+{hidden} daha)")
        return "\n".join(lines)

    @staticmethod
    def format_reprompt(menu_id: str, seed: str = "default") -> str:
        """Format a gentle reprompt for unclear input."""
        if menu_id == "smalltalk_stage1":
            return "1, 2 veya 0 yazabilir misin?"
        if menu_id == "smalltalk_stage2":
            return "Hangisi? (1/2/3/0)"
        if menu_id == "free_slots":
            return "Hangi boşluk? (1/2/3 veya 0)"
        if menu_id == "unknown":
            return "Takvim için 1, sohbet için 2."
        return "Hangisini tercih edersin?"


# ─────────────────────────────────────────────────────────────
# Legacy VoiceStyle (backward compat)
# ─────────────────────────────────────────────────────────────

class VoiceStyle:
    """Legacy wrapper - delegates to JarvisVoice."""

    PREFIX = "Efendim"
    CANCEL = "Vazgeçtim."
    OK = "Tamam."
    DONE = "Tamamdır."

    @staticmethod
    def strip_emoji(text: str) -> str:
        """Remove emoji from text.
        
        Uses non-overlapping Unicode ranges to avoid CodeQL security warnings.
        Covers most common emoji blocks without character class overlap.
        """
        if not text:
            return ""
        # Use separate patterns to avoid overlapping ranges (CodeQL alerts #21-23)
        # Each block is processed independently
        patterns = [
            r"[\U0001F600-\U0001F64F]",  # Emoticons
            r"[\U0001F300-\U0001F5FF]",  # Symbols & Pictographs
            r"[\U0001F680-\U0001F6FF]",  # Transport & Map
            r"[\U0001F900-\U0001F9FF]",  # Supplemental Symbols
            r"[\U00002702-\U000027B0]",  # Dingbats
        ]
        result = text
        for pattern in patterns:
            result = re.sub(pattern, "", result, flags=re.UNICODE)
        return result.strip()

    @staticmethod
    def limit_sentences(text: str, max_sentences: int = 2) -> str:
        """Limit to N sentences."""
        if not text or max_sentences < 1:
            return text or ""
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(parts) <= max_sentences:
            return text.strip()
        return " ".join(parts[:max_sentences])

    @staticmethod
    def acknowledge(message: str) -> str:
        """Add Efendim prefix if missing."""
        msg = (message or "").strip()
        if not msg:
            return VoiceStyle.PREFIX
        if msg.lower().startswith("efendim"):
            return msg
        return f"Efendim, {msg[0].lower()}{msg[1:]}" if msg else VoiceStyle.PREFIX

    @staticmethod
    def format_list_with_more(items: list[str], shown: int = 3, more_label: str = "daha fazla") -> str:
        """Format list with 'more' indicator."""
        if not items:
            return ""
        visible = items[:shown]
        hidden = len(items) - shown
        result = "\n".join(f"- {item}" for item in visible)
        if hidden > 0:
            result += f"\n(+{hidden} {more_label})"
        return result


# Convenience aliases
JARVIS = JarvisVoice
JARVIS = VoiceStyle
