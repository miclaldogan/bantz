"""Dismiss / stop intent detection (Issue #293).

Local intent classification — fast regex-based, no LLM call.
Detects Turkish dismiss phrases and returns a polite goodbye.

Example flow::

    User: "Teşekkürler şimdilik"
    Bantz: "Size iyi çalışmalar efendim. İhtiyacınız olursa buradayım."
    FSM → WAKE_ONLY
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "DismissIntentDetector",
    "DismissResult",
    "DISMISS_PHRASES",
    "DISMISS_RESPONSES",
]

# ── Turkish dismiss phrases (regex patterns) ──────────────────

DISMISS_PHRASES: List[str] = [
    # Explicit dismiss
    r"teşekkür(ler)?\s*(ederim)?\s*(şimdilik|artık)?",
    r"şimdilik\s*(sana)?\s*ihtiyacım?\s*yok",
    r"görüşürüz",
    r"hoşça\s*kal",
    r"kapat\s*(kendini)?",
    r"sus\s*artık",
    r"tamam\s*(bu\s*kadar)?",
    r"yeter\s*(bu\s*kadar)?",
    r"iyi\s*çalışmalar",
    # Polite dismiss
    r"sağ\s*ol\s*(bantz)?",
    r"eyvallah",
    r"güle\s*güle",
    # Short forms
    r"bay\s*bay",
    r"hadi\s*görüşürüz",
    r"sonra\s*görüşürüz",
]

# Compiled patterns (case-insensitive)
_COMPILED_PHRASES = [re.compile(p, re.IGNORECASE) for p in DISMISS_PHRASES]

# ── Polite goodbye responses ──────────────────────────────────

DISMISS_RESPONSES: List[str] = [
    "Size iyi çalışmalar efendim. İhtiyacınız olursa buradayım.",
    "Görüşmek üzere efendim.",
    "Anlaşıldı efendim, beklemedeyim.",
    "Tabii efendim, iyi günler.",
    "İyi çalışmalar efendim.",
    "Anlaşıldı, ihtiyacınız olursa buradayım efendim.",
]


# ── Result dataclass ──────────────────────────────────────────

@dataclass
class DismissResult:
    """Result of dismiss intent detection."""

    is_dismiss: bool
    confidence: float
    matched_phrase: Optional[str] = None
    response: Optional[str] = None


# ── Intent detector ───────────────────────────────────────────

class DismissIntentDetector:
    """Local regex-based dismiss intent detector.

    Parameters
    ----------
    phrases:
        Override default dismiss phrases (compiled regex list).
    responses:
        Override default goodbye responses.
    confirmation_threshold:
        Confidence range [low, high) that requires user confirmation.
    """

    def __init__(
        self,
        phrases: Optional[List[re.Pattern]] = None,
        responses: Optional[List[str]] = None,
        confirmation_threshold: Tuple[float, float] = (0.5, 0.8),
    ) -> None:
        self._phrases = phrases or _COMPILED_PHRASES
        self._responses = responses or DISMISS_RESPONSES
        self._conf_low, self._conf_high = confirmation_threshold

    def detect(self, text: str) -> DismissResult:
        """Detect dismiss intent in user text.

        Parameters
        ----------
        text:
            User utterance (Turkish).

        Returns
        -------
        DismissResult with is_dismiss, confidence, matched phrase, response.
        """
        if not text or not text.strip():
            return DismissResult(is_dismiss=False, confidence=0.0)

        cleaned = text.strip().lower()

        for pattern in self._phrases:
            match = pattern.search(cleaned)
            if match:
                matched = match.group(0)
                # Full-sentence match → high confidence
                # Partial match → medium confidence
                ratio = len(matched) / max(len(cleaned), 1)
                confidence = min(1.0, 0.6 + ratio * 0.4)

                response = random.choice(self._responses)
                logger.info(
                    "[dismiss] detected: '%s' (conf=%.2f) in '%s'",
                    matched, confidence, cleaned,
                )
                return DismissResult(
                    is_dismiss=True,
                    confidence=confidence,
                    matched_phrase=matched,
                    response=response,
                )

        return DismissResult(is_dismiss=False, confidence=0.0)

    def needs_confirmation(self, confidence: float) -> bool:
        """Check if confidence requires user confirmation.

        Returns True when confidence is in the ambiguous zone.
        """
        return self._conf_low < confidence < self._conf_high

    def pick_response(self) -> str:
        """Pick a random goodbye response."""
        return random.choice(self._responses)
