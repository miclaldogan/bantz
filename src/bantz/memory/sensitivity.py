"""Sensitivity classifier for memory content (Issue #449).

Detects PII and sensitive data in text using regex patterns:
- Email addresses
- Phone numbers (Turkish +90 and generic)
- Turkish ID numbers (TC Kimlik)
- Credit card numbers
- Passwords / tokens / secrets
- IBAN numbers

Returns a :class:`SensitivityResult` with level and matched patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple


class SensitivityLevel(Enum):
    """How sensitive the detected content is."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class SensitivityResult:
    """Result of sensitivity classification.

    Attributes
    ----------
    level:
        Overall sensitivity level (worst-case of all matches).
    matched_patterns:
        List of ``(pattern_name, matched_text)`` tuples.
    """

    level: SensitivityLevel = SensitivityLevel.NONE
    matched_patterns: List[Tuple[str, str]] = field(default_factory=list)


# -----------------------------------------------------------------------
# Pattern definitions — (name, regex, sensitivity_level)
# -----------------------------------------------------------------------

_PATTERNS: List[Tuple[str, re.Pattern, SensitivityLevel]] = [
    # HIGH — never store
    (
        "credit_card",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        SensitivityLevel.HIGH,
    ),
    (
        "password_keyword",
        re.compile(
            r"(?i)(?:[Şş]ifre|parola|password|passwd|secret|token|api[_-]?key"
            r"|private[_-]?key|auth[_-]?token)\w*\s*[:=]\s*\S+",
            re.UNICODE,
        ),
        SensitivityLevel.HIGH,
    ),
    (
        "tc_kimlik",
        re.compile(r"\b[1-9]\d{10}\b"),
        SensitivityLevel.HIGH,
    ),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{2,4}\b"),
        SensitivityLevel.HIGH,
    ),
    # MEDIUM — ask before storing
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        SensitivityLevel.MEDIUM,
    ),
    (
        "phone_tr",
        re.compile(r"(?:\+90|0)\s*5\d{2}\s*\d{3}\s*\d{2}\s*\d{2}"),
        SensitivityLevel.MEDIUM,
    ),
    (
        "phone_generic",
        re.compile(r"\+\d{1,3}\s?\d{3,4}\s?\d{3,4}\s?\d{2,4}"),
        SensitivityLevel.MEDIUM,
    ),
    # LOW — fine to store but flag
    (
        "address_keyword",
        re.compile(
            r"(?i)\b(?:adres(?:im)?|ev(?:im)?|mahalle|sokak|cadde|apt)\b",
        ),
        SensitivityLevel.LOW,
    ),
]

# Severity ordering for worst-case
_LEVEL_ORDER = {
    SensitivityLevel.NONE: 0,
    SensitivityLevel.LOW: 1,
    SensitivityLevel.MEDIUM: 2,
    SensitivityLevel.HIGH: 3,
}


def classify_sensitivity(text: str) -> SensitivityResult:
    """Classify the sensitivity of *text*.

    Returns a :class:`SensitivityResult` whose ``level`` is the maximum
    severity among all matched patterns.
    """
    matched: List[Tuple[str, str]] = []
    max_level = SensitivityLevel.NONE

    for name, pattern, level in _PATTERNS:
        for m in pattern.finditer(text):
            matched.append((name, m.group()))
            if _LEVEL_ORDER[level] > _LEVEL_ORDER[max_level]:
                max_level = level

    return SensitivityResult(level=max_level, matched_patterns=matched)
