"""PII redaction for cloud-bound text (Issue #299).

Removes or masks personally identifiable information before
sending text to external services (Gemini, web search, etc.).

Patterns are tuned for Turkish users:
- Turkish ID numbers (11-digit TC Kimlik No)
- Phone numbers (Turkish formats)
- Email addresses
- Credit card numbers
- IBAN numbers

Usage::

    from bantz.privacy.redaction import redact_pii
    safe = redact_pii("Aramam gereken numara 05321234567")
    # → "Aramam gereken numara [TELEFON]"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)

__all__ = ["redact_pii", "REDACTION_PATTERNS", "RedactionStats"]


# ─────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────

# (regex, replacement, description)
REDACTION_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Phone numbers — Turkish mobile +90 5XX XXX XX XX or 05XX...
    # Must be before TC Kimlik (also 11 digits) to match correctly.
    (
        re.compile(
            r"(?:\+90[\s.-]?)?0?5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}"
        ),
        "[TELEFON]",
        "Turkish phone",
    ),
    # International phone numbers — require + prefix to avoid TC Kimlik clash
    (re.compile(r"\+\d{10,15}"), "[TELEFON]", "International phone"),
    # Turkish ID number — 11-digit TC Kimlik No
    # Rules: first digit 1-9, last digit even, exactly 11 digits.
    # Negative lookahead excludes phone-like patterns (0XXX prefix was
    # already consumed by the phone pattern above, but standalone
    # 11-digit numbers starting with 0 are not valid TC Kimlik anyway).
    (re.compile(r"\b[1-9]\d{9}[02468]\b"), "[TC_KIMLIK]", "Turkish ID (TC Kimlik)"),
    # Email addresses
    (
        re.compile(r"\b[\w.+-]+@[\w.-]+\.\w{2,}\b"),
        "[EMAIL]",
        "Email address",
    ),
    # Credit card numbers — 4 groups of 4 digits with valid BIN prefixes
    # Only match cards starting with 4 (Visa), 5 (MC), 3 (Amex/Diners),
    # 6 (Discover), or 9 (Turkish domestic) to avoid false positives on
    # arbitrary 16-digit sequences.
    (
        re.compile(
            r"\b[3-6,9]\d{3}[\s.-]?\d{4}[\s.-]?\d{4}[\s.-]?\d{4}\b"
        ),
        "[KART]",
        "Credit card number",
    ),
    # IBAN — TR followed by digits
    (
        re.compile(r"\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b", re.IGNORECASE),
        "[IBAN]",
        "IBAN number",
    ),
    # IP addresses — validate each octet is 0-255, reject version strings
    # by requiring that the match is NOT preceded by a letter/dot
    (
        re.compile(
            r"(?<![.\w])"
            r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\."
            r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
            r"(?![.\w])"
        ),
        "[IP]",
        "IP address",
    ),
]


# ─────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────


@dataclass
class RedactionStats:
    """Statistics about a redaction operation."""

    total_redactions: int = 0
    patterns_matched: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.patterns_matched is None:
            self.patterns_matched = []


# ─────────────────────────────────────────────────────────────────
# Main function
# ─────────────────────────────────────────────────────────────────


def redact_pii(
    text: str,
    *,
    extra_patterns: List[Tuple[re.Pattern, str, str]] | None = None,
    collect_stats: bool = False,
) -> str | Tuple[str, RedactionStats]:
    """Redact PII from text before sending to cloud.

    Parameters
    ----------
    text:
        Input text (may contain PII).
    extra_patterns:
        Additional (pattern, replacement, description) tuples.
    collect_stats:
        If True, returns ``(redacted_text, stats)`` tuple.

    Returns
    -------
    str or (str, RedactionStats):
        Redacted text, optionally with statistics.
    """
    if not text:
        if collect_stats:
            return text, RedactionStats()
        return text

    result = str(text)
    stats = RedactionStats() if collect_stats else None
    patterns = list(REDACTION_PATTERNS)
    if extra_patterns:
        patterns.extend(extra_patterns)

    for pattern, replacement, description in patterns:
        new_result, count = pattern.subn(replacement, result)
        if count > 0:
            logger.debug("PII redacted: %s (%d match(es))", description, count)
            if stats:
                stats.total_redactions += count
                stats.patterns_matched.append(description)
            result = new_result

    if collect_stats:
        return result, stats
    return result
