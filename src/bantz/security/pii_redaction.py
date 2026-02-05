"""Cloud PII Redaction Module.

Issue #242: Stronger redact/minimize (PII patterns) + unit coverage.

This module provides comprehensive PII redaction for cloud-bound text:
- Emails, phones, addresses, IDs
- Turkish-specific patterns (TC Kimlik, IBAN)
- Calendar titles (optional mode)
- Two modes: cloud (redact on) vs local (no outbound)

Patterns:
- emails: user@example.com → <EMAIL>
- phones: +90 555 123 4567 → <PHONE>
- addresses: Kadıköy Mah. No:15 → <ADDRESS>
- IDs: Turkish TC, IBAN, credit cards
- calendar_titles: Optional redaction for event names
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Pattern


class RedactionMode(Enum):
    """Redaction mode for cloud operations."""
    LOCAL = "local"    # No outbound, no redaction needed
    CLOUD = "cloud"    # Cloud calls allowed, full redaction


class RedactionLevel(Enum):
    """Redaction strictness level."""
    MINIMAL = "minimal"      # Only critical PII (emails, phones, IDs)
    STANDARD = "standard"    # Minimal + addresses, URLs
    STRICT = "strict"        # Standard + names, calendar titles


@dataclass(frozen=True)
class RedactionPattern:
    """Pattern for PII redaction."""
    name: str
    pattern: str
    replacement: str
    level: RedactionLevel = RedactionLevel.MINIMAL
    flags: int = re.IGNORECASE
    enabled: bool = True
    
    _compiled: Optional[Pattern] = field(default=None, repr=False, compare=False)
    
    def compile(self) -> Pattern:
        """Get compiled regex pattern."""
        if self._compiled is None:
            object.__setattr__(self, '_compiled', re.compile(self.pattern, self.flags))
        return self._compiled  # type: ignore
    
    def redact(self, text: str) -> str:
        """Apply redaction to text."""
        if not self.enabled or not text:
            return text
        return self.compile().sub(self.replacement, text)


@dataclass(frozen=True)
class RedactionResult:
    """Result of PII redaction."""
    original: str
    redacted: str
    patterns_matched: list[str]
    redaction_count: int
    
    @property
    def was_redacted(self) -> bool:
        """Check if any redaction was applied."""
        return self.original != self.redacted
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "original_length": len(self.original),
            "redacted_length": len(self.redacted),
            "patterns_matched": self.patterns_matched,
            "redaction_count": self.redaction_count,
            "was_redacted": self.was_redacted,
        }


# =============================================================================
# PII Patterns - Comprehensive Set
# =============================================================================

# Email patterns
EMAIL_PATTERN = RedactionPattern(
    name="email",
    pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    replacement="<EMAIL>",
    level=RedactionLevel.MINIMAL,
)

# Phone patterns - International and Turkish
PHONE_PATTERNS = [
    # Turkish format: +90 555 123 4567 or 0555 123 4567
    RedactionPattern(
        name="phone_turkish",
        pattern=r"\b(?:\+90\s?|0)?[5][0-9]{2}[\s.-]?[0-9]{3}[\s.-]?[0-9]{4}\b",
        replacement="<PHONE>",
        level=RedactionLevel.MINIMAL,
    ),
    # Turkish landline: 0212 123 4567
    RedactionPattern(
        name="phone_landline_tr",
        pattern=r"\b0?[2-4][0-9]{2}[\s.-]?[0-9]{3}[\s.-]?[0-9]{4}\b",
        replacement="<PHONE>",
        level=RedactionLevel.MINIMAL,
    ),
    # International format: +1 555 123 4567
    RedactionPattern(
        name="phone_intl",
        pattern=r"\b\+?[1-9]\d{0,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
        replacement="<PHONE>",
        level=RedactionLevel.MINIMAL,
    ),
    # Generic phone pattern
    RedactionPattern(
        name="phone_generic",
        pattern=r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b",
        replacement="<PHONE>",
        level=RedactionLevel.MINIMAL,
    ),
]

# ID patterns
ID_PATTERNS = [
    # Turkish TC Kimlik No (11 digits starting with 1-9)
    RedactionPattern(
        name="tc_kimlik",
        pattern=r"\b[1-9]\d{10}\b",
        replacement="<TC_KIMLIK>",
        level=RedactionLevel.MINIMAL,
    ),
    # Turkish IBAN: TR followed by 24 digits
    RedactionPattern(
        name="iban_tr",
        pattern=r"\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b",
        replacement="<IBAN>",
        level=RedactionLevel.MINIMAL,
        flags=re.IGNORECASE,
    ),
    # Generic IBAN
    RedactionPattern(
        name="iban_generic",
        pattern=r"\b[A-Z]{2}\d{2}[\sA-Z0-9]{10,30}\b",
        replacement="<IBAN>",
        level=RedactionLevel.MINIMAL,
    ),
    # Credit card numbers
    RedactionPattern(
        name="credit_card",
        pattern=r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        replacement="<CREDIT_CARD>",
        level=RedactionLevel.MINIMAL,
    ),
    # US SSN
    RedactionPattern(
        name="ssn",
        pattern=r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        replacement="<SSN>",
        level=RedactionLevel.MINIMAL,
    ),
    # Passport numbers (alphanumeric, 6-9 chars)
    RedactionPattern(
        name="passport",
        pattern=r"\b[A-Z]{1,2}\d{6,8}\b",
        replacement="<PASSPORT>",
        level=RedactionLevel.MINIMAL,
    ),
]

# Address patterns
ADDRESS_PATTERNS = [
    # Turkish address: Mahalle/Sokak/Cadde patterns
    RedactionPattern(
        name="address_tr_mahalle",
        pattern=r"\b[\w\s]{2,20}\s+(Mah(?:allesi)?|Mahalle)\.?\s*(?:No)?\.?\s*:?\s*\d+",
        replacement="<ADDRESS>",
        level=RedactionLevel.STANDARD,
    ),
    RedactionPattern(
        name="address_tr_sokak",
        pattern=r"\b[\w\s]{2,20}\s+(Sok(?:ak)?|Sokağı|Cad(?:desi)?|Cadde)\.?\s*(?:No)?\.?\s*:?\s*\d+",
        replacement="<ADDRESS>",
        level=RedactionLevel.STANDARD,
    ),
    # Generic numbered address
    RedactionPattern(
        name="address_numbered",
        pattern=r"\b\d+\s+[A-Za-zğüşıöçĞÜŞİÖÇ]+\s+(Street|St|Avenue|Ave|Road|Rd|Sokak|Sok|Cadde|Cad)\b",
        replacement="<ADDRESS>",
        level=RedactionLevel.STANDARD,
        flags=re.IGNORECASE,
    ),
    # Postal codes - Turkish (5 digits)
    RedactionPattern(
        name="postal_code_tr",
        pattern=r"\b\d{5}\b(?=\s+[A-Za-zğüşıöçĞÜŞİÖÇ])",
        replacement="<POSTAL>",
        level=RedactionLevel.STANDARD,
    ),
]

# URL patterns
URL_PATTERNS = [
    # HTTPS/HTTP URLs
    RedactionPattern(
        name="url",
        pattern=r"https?://[^\s<>\"']+",
        replacement="<URL>",
        level=RedactionLevel.STANDARD,
    ),
    # URLs with credentials
    RedactionPattern(
        name="url_credentials",
        pattern=r"(https?://)[^:@/\s]+:[^@/\s]+@[^\s]+",
        replacement="<URL_WITH_CREDS>",
        level=RedactionLevel.MINIMAL,  # Higher priority
    ),
]

# API/Secret patterns
SECRET_PATTERNS = [
    # API keys
    RedactionPattern(
        name="api_key",
        pattern=r"(?i)(api[_-]?key|apikey|api[_-]?secret)[:\s=]+[\w\-]{16,}",
        replacement=r"<API_KEY>",
        level=RedactionLevel.MINIMAL,
    ),
    # Bearer tokens
    RedactionPattern(
        name="bearer_token",
        pattern=r"(?i)bearer\s+[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*\.?[A-Za-z0-9\-_=]*",
        replacement="<BEARER_TOKEN>",
        level=RedactionLevel.MINIMAL,
    ),
    # Password patterns
    RedactionPattern(
        name="password",
        pattern=r"(?i)(password|şifre|parola|passwd|pwd)[:\s=]+\S+",
        replacement="<PASSWORD>",
        level=RedactionLevel.MINIMAL,
    ),
    # AWS keys
    RedactionPattern(
        name="aws_key",
        pattern=r"(?i)(AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}",
        replacement="<AWS_KEY>",
        level=RedactionLevel.MINIMAL,
    ),
]

# IP Address patterns
IP_PATTERNS = [
    # IPv4
    RedactionPattern(
        name="ipv4",
        pattern=r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        replacement="<IP>",
        level=RedactionLevel.STANDARD,
    ),
    # IPv6 (simplified)
    RedactionPattern(
        name="ipv6",
        pattern=r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
        replacement="<IP>",
        level=RedactionLevel.STANDARD,
    ),
]

# Calendar-specific patterns (for STRICT mode)
CALENDAR_PATTERNS = [
    # Event titles in quotes (optional, strict mode)
    RedactionPattern(
        name="calendar_title_quoted",
        pattern=r'"[^"]{3,50}"',
        replacement="<EVENT_TITLE>",
        level=RedactionLevel.STRICT,
    ),
]

# Date patterns (for context, usually not redacted but can be)
DATE_PATTERNS = [
    # ISO dates
    RedactionPattern(
        name="date_iso",
        pattern=r"\b\d{4}-\d{2}-\d{2}\b",
        replacement="<DATE>",
        level=RedactionLevel.STRICT,
        enabled=False,  # Disabled by default
    ),
]


# =============================================================================
# Combined Pattern Sets
# =============================================================================

def get_minimal_patterns() -> list[RedactionPattern]:
    """Get patterns for minimal redaction (critical PII only)."""
    patterns = [EMAIL_PATTERN]
    patterns.extend(PHONE_PATTERNS)
    patterns.extend(ID_PATTERNS)
    patterns.extend([p for p in URL_PATTERNS if p.level == RedactionLevel.MINIMAL])
    patterns.extend(SECRET_PATTERNS)
    return [p for p in patterns if p.enabled]


def get_standard_patterns() -> list[RedactionPattern]:
    """Get patterns for standard redaction (minimal + addresses, URLs)."""
    patterns = get_minimal_patterns()
    patterns.extend(ADDRESS_PATTERNS)
    patterns.extend([p for p in URL_PATTERNS if p.level == RedactionLevel.STANDARD])
    patterns.extend(IP_PATTERNS)
    return patterns


def get_strict_patterns() -> list[RedactionPattern]:
    """Get patterns for strict redaction (all patterns including calendar)."""
    patterns = get_standard_patterns()
    patterns.extend(CALENDAR_PATTERNS)
    patterns.extend([p for p in DATE_PATTERNS if p.enabled])
    return patterns


def get_patterns_for_level(level: RedactionLevel) -> list[RedactionPattern]:
    """Get patterns for a specific redaction level."""
    if level == RedactionLevel.MINIMAL:
        return get_minimal_patterns()
    elif level == RedactionLevel.STANDARD:
        return get_standard_patterns()
    else:
        return get_strict_patterns()


# =============================================================================
# PII Redactor Class
# =============================================================================

class PIIRedactor:
    """PII redaction engine for cloud-bound text.
    
    Modes:
    - LOCAL: No redaction (no outbound calls)
    - CLOUD: Full redaction before cloud API calls
    
    Levels:
    - MINIMAL: Critical PII only (emails, phones, IDs, secrets)
    - STANDARD: Minimal + addresses, URLs, IPs
    - STRICT: Standard + calendar titles, dates
    """
    
    def __init__(
        self,
        mode: RedactionMode = RedactionMode.CLOUD,
        level: RedactionLevel = RedactionLevel.STANDARD,
        custom_patterns: Optional[list[RedactionPattern]] = None,
    ):
        """Initialize PII redactor.
        
        Args:
            mode: Redaction mode (local/cloud)
            level: Redaction level (minimal/standard/strict)
            custom_patterns: Additional custom patterns
        """
        self.mode = mode
        self.level = level
        self.patterns = get_patterns_for_level(level)
        if custom_patterns:
            self.patterns.extend(custom_patterns)
    
    def redact(self, text: str) -> RedactionResult:
        """Redact PII from text.
        
        Args:
            text: Input text potentially containing PII
        
        Returns:
            RedactionResult with original, redacted, and metadata
        """
        if not text:
            return RedactionResult(
                original="",
                redacted="",
                patterns_matched=[],
                redaction_count=0,
            )
        
        # In local mode, return unchanged
        if self.mode == RedactionMode.LOCAL:
            return RedactionResult(
                original=text,
                redacted=text,
                patterns_matched=[],
                redaction_count=0,
            )
        
        result = text
        patterns_matched: list[str] = []
        redaction_count = 0
        
        for pattern in self.patterns:
            before = result
            result = pattern.redact(result)
            
            if result != before:
                patterns_matched.append(pattern.name)
                # Count replacements
                count = before.count(pattern.replacement) if pattern.replacement in result else 1
                redaction_count += max(1, len(pattern.compile().findall(before)))
        
        return RedactionResult(
            original=text,
            redacted=result,
            patterns_matched=list(set(patterns_matched)),
            redaction_count=redaction_count,
        )
    
    def redact_text(self, text: str) -> str:
        """Convenience method - returns only redacted text."""
        return self.redact(text).redacted
    
    def is_safe(self, text: str) -> bool:
        """Check if text contains no detectable PII."""
        result = self.redact(text)
        return not result.was_redacted
    
    def get_pii_types(self, text: str) -> list[str]:
        """Get list of PII types detected in text."""
        result = self.redact(text)
        return result.patterns_matched


# =============================================================================
# Default Redactor Instance
# =============================================================================

_default_redactor: Optional[PIIRedactor] = None


def get_default_redactor() -> PIIRedactor:
    """Get or create default PII redactor."""
    global _default_redactor
    if _default_redactor is None:
        _default_redactor = PIIRedactor(
            mode=RedactionMode.CLOUD,
            level=RedactionLevel.STANDARD,
        )
    return _default_redactor


def set_default_redactor(redactor: PIIRedactor) -> None:
    """Set the default PII redactor."""
    global _default_redactor
    _default_redactor = redactor


# =============================================================================
# Convenience Functions
# =============================================================================

def redact_for_cloud(text: str) -> str:
    """Redact PII from text for cloud API calls.
    
    Uses default STANDARD level redaction.
    
    Args:
        text: Input text
    
    Returns:
        Redacted text safe for cloud transmission
    """
    return get_default_redactor().redact_text(text)


def redact_strict(text: str) -> str:
    """Redact PII with STRICT level (includes calendar titles).
    
    Args:
        text: Input text
    
    Returns:
        Strictly redacted text
    """
    redactor = PIIRedactor(
        mode=RedactionMode.CLOUD,
        level=RedactionLevel.STRICT,
    )
    return redactor.redact_text(text)


def redact_minimal(text: str) -> str:
    """Redact only critical PII (emails, phones, IDs).
    
    Args:
        text: Input text
    
    Returns:
        Minimally redacted text
    """
    redactor = PIIRedactor(
        mode=RedactionMode.CLOUD,
        level=RedactionLevel.MINIMAL,
    )
    return redactor.redact_text(text)


def is_pii_free(text: str, level: RedactionLevel = RedactionLevel.STANDARD) -> bool:
    """Check if text is free of detectable PII.
    
    Args:
        text: Text to check
        level: Redaction level for detection
    
    Returns:
        True if no PII detected
    """
    redactor = PIIRedactor(mode=RedactionMode.CLOUD, level=level)
    return redactor.is_safe(text)


def detect_pii_types(text: str) -> list[str]:
    """Detect types of PII in text.
    
    Args:
        text: Text to analyze
    
    Returns:
        List of PII type names detected
    """
    redactor = PIIRedactor(mode=RedactionMode.CLOUD, level=RedactionLevel.STRICT)
    return redactor.get_pii_types(text)


# =============================================================================
# Batch Processing
# =============================================================================

def redact_batch(
    texts: list[str],
    level: RedactionLevel = RedactionLevel.STANDARD,
) -> list[RedactionResult]:
    """Redact PII from multiple texts.
    
    Args:
        texts: List of texts to redact
        level: Redaction level
    
    Returns:
        List of RedactionResult objects
    """
    redactor = PIIRedactor(mode=RedactionMode.CLOUD, level=level)
    return [redactor.redact(t) for t in texts]


def get_redaction_stats(results: list[RedactionResult]) -> dict:
    """Get statistics from batch redaction results.
    
    Args:
        results: List of RedactionResult objects
    
    Returns:
        Dictionary with stats
    """
    total = len(results)
    redacted = sum(1 for r in results if r.was_redacted)
    total_redactions = sum(r.redaction_count for r in results)
    
    pattern_counts: dict[str, int] = {}
    for r in results:
        for pattern in r.patterns_matched:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
    
    return {
        "total_texts": total,
        "texts_redacted": redacted,
        "texts_clean": total - redacted,
        "redaction_rate": redacted / total if total > 0 else 0.0,
        "total_redactions": total_redactions,
        "pattern_counts": pattern_counts,
    }
