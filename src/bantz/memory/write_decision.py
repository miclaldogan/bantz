"""Memory write-policy engine (Issue #449).

Decides whether a piece of information from a conversation turn should
be persisted to long-term memory.

Categories
----------
- **ALWAYS** — user preferences, learned facts, important task results
- **ASK**    — personal info (address, phone) that *might* be useful
- **NEVER**  — passwords, tokens, credit cards, raw PII

The engine also performs **deduplication** (content-hash check) and
**sensitivity classification** (via :mod:`bantz.memory.sensitivity`).

Usage::

    engine = WriteDecisionEngine()
    decision = engine.evaluate(
        content="Doğum günüm 15 Mart",
        turn_context={"route": "smalltalk"},
    )
    if decision.should_write:
        store.write(...)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from bantz.memory.sensitivity import (
    SensitivityLevel,
    classify_sensitivity,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryWriteDecision",
    "WriteDecisionEngine",
]


@dataclass
class MemoryWriteDecision:
    """Result of the write-policy evaluation.

    Attributes
    ----------
    should_write:
        ``True`` if the content should be persisted.
    category:
        ``"always"`` | ``"ask"`` | ``"never"``.
    reason:
        Human-readable (Turkish) explanation.
    sensitivity:
        ``"none"`` | ``"low"`` | ``"medium"`` | ``"high"``.
    content_hash:
        SHA-256 hex digest for dedup.
    """

    should_write: bool = False
    category: str = "never"
    reason: str = ""
    sensitivity: str = "none"
    content_hash: str = ""


# -----------------------------------------------------------------------
# Keyword / pattern lists
# -----------------------------------------------------------------------

# Patterns that indicate high-value content (ALWAYS write)
_ALWAYS_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(?:tercih|sevdiğ|favorit?|beğen|alışkanlık)"),
    re.compile(r"(?i)(?:doğum\s*gün|yaş\s*gün)"),
    re.compile(r"(?i)(?:hatırla|unutma|not\s*et|kaydet)"),
    re.compile(r"(?i)(?:öğrendim|öğrendin|biliyorsun)"),
]

# Route / context signals for ALWAYS
_ALWAYS_ROUTES: set[str] = {
    "calendar.create_event",
    "calendar.delete_event",
    "gmail.send",
    "gmail.reply",
    "task_completed",
}

# Patterns for ASK category
_ASK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)\b(?:adres(?:im)?|ev(?:im)?)\b"),
    re.compile(r"(?i)\b(?:telefon|numara)\b"),
    re.compile(r"(?i)\b(?:maaş|gelir|bütçe|borç)\b"),
    re.compile(r"(?i)\b(?:sağlık|ilaç|doktor|hastalık)\b"),
]

# Low-value smalltalk patterns (NEVER)
_SMALLTALK_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)^(?:merhaba|selam|hey|naber|nasılsın|günaydın|iyi geceler)[\s!?.]*$"),
    re.compile(r"(?i)^(?:tamam|ok|evet|hayır|teşekkür|sağ ol|eyvallah)[\s!?.]*$"),
    re.compile(r"(?i)^(?:haha|lol|:[\)D]|😀|👍)[\s]*$"),
]


class WriteDecisionEngine:
    """Evaluate whether a turn's content should be written to memory.

    Parameters
    ----------
    seen_hashes:
        Optional pre-loaded set of content hashes for dedup.
    """

    def __init__(self, seen_hashes: Optional[Set[str]] = None) -> None:
        self._seen: Set[str] = seen_hashes or set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        content: str,
        turn_context: Optional[Dict[str, Any]] = None,
    ) -> MemoryWriteDecision:
        """Evaluate a piece of content for persistence.

        Parameters
        ----------
        content:
            The text to evaluate (user turn or assistant reply).
        turn_context:
            Context dict — may contain ``route``, ``tool_name``,
            ``is_task_result``, etc.

        Returns
        -------
        MemoryWriteDecision
        """
        ctx = turn_context or {}
        content_hash = self._hash(content)

        # 1. Sensitivity check
        sens = classify_sensitivity(content)
        sensitivity_str = sens.level.value

        # HIGH sensitivity → NEVER
        if sens.level == SensitivityLevel.HIGH:
            return MemoryWriteDecision(
                should_write=False,
                category="never",
                reason="Hassas veri tespit edildi: " + ", ".join(
                    p[0] for p in sens.matched_patterns
                ),
                sensitivity=sensitivity_str,
                content_hash=content_hash,
            )

        # 2. Dedup check
        if content_hash in self._seen:
            return MemoryWriteDecision(
                should_write=False,
                category="never",
                reason="Bu bilgi zaten kayıtlı (dedup).",
                sensitivity=sensitivity_str,
                content_hash=content_hash,
            )

        # 3. Smalltalk check (low-value → NEVER)
        if self._is_smalltalk(content):
            return MemoryWriteDecision(
                should_write=False,
                category="never",
                reason="Düşük değerli sohbet (smalltalk).",
                sensitivity=sensitivity_str,
                content_hash=content_hash,
            )

        # 4. ALWAYS patterns
        route = ctx.get("route", "")
        if route in _ALWAYS_ROUTES or ctx.get("is_task_result"):
            self._seen.add(content_hash)
            return MemoryWriteDecision(
                should_write=True,
                category="always",
                reason="Görev sonucu veya önemli işlem.",
                sensitivity=sensitivity_str,
                content_hash=content_hash,
            )

        for pat in _ALWAYS_PATTERNS:
            if pat.search(content):
                self._seen.add(content_hash)
                return MemoryWriteDecision(
                    should_write=True,
                    category="always",
                    reason="Kullanıcı tercihi veya önemli bilgi tespit edildi.",
                    sensitivity=sensitivity_str,
                    content_hash=content_hash,
                )

        # 5. ASK patterns (medium sensitivity or personal info)
        if sens.level == SensitivityLevel.MEDIUM:
            return MemoryWriteDecision(
                should_write=False,
                category="ask",
                reason="Kişisel bilgi tespit edildi — kullanıcı onayı gerekli.",
                sensitivity=sensitivity_str,
                content_hash=content_hash,
            )

        for pat in _ASK_PATTERNS:
            if pat.search(content):
                return MemoryWriteDecision(
                    should_write=False,
                    category="ask",
                    reason="Kişisel/hassas bilgi — kullanıcı onayı gerekli.",
                    sensitivity=sensitivity_str,
                    content_hash=content_hash,
                )

        # 6. Default — low-sensitivity general content: ALWAYS (if substantial)
        if len(content.strip()) > 15:
            self._seen.add(content_hash)
            return MemoryWriteDecision(
                should_write=True,
                category="always",
                reason="Yeterli uzunlukta genel bilgi.",
                sensitivity=sensitivity_str,
                content_hash=content_hash,
            )

        # Too short and not matching anything → skip
        return MemoryWriteDecision(
            should_write=False,
            category="never",
            reason="Çok kısa veya düşük değerli içerik.",
            sensitivity=sensitivity_str,
            content_hash=content_hash,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.strip().lower().encode()).hexdigest()

    @staticmethod
    def _is_smalltalk(content: str) -> bool:
        text = content.strip()
        return any(p.match(text) for p in _SMALLTALK_PATTERNS)

    def reset_seen(self) -> None:
        """Clear the dedup hash set."""
        self._seen.clear()
