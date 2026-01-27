"""
Log Redaction for V2-5 (Issue #37).

Automatically redact sensitive information from logs:
- Email addresses
- API keys
- Bearer tokens
- Passwords
- Credit card numbers
- SSN
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Pattern, Set, Union


class SensitivityLevel(Enum):
    """Level of data sensitivity."""
    
    LOW = "low"         # Generally safe
    MEDIUM = "medium"   # Should be masked
    HIGH = "high"       # Must always be masked
    CRITICAL = "critical"  # Never log, even masked


@dataclass
class RedactionPattern:
    """A pattern for detecting sensitive data."""
    
    name: str
    pattern: Pattern[str]
    sensitivity: SensitivityLevel
    replacement: str = "[REDACTED]"
    
    @classmethod
    def from_regex(
        cls,
        name: str,
        regex: str,
        sensitivity: SensitivityLevel = SensitivityLevel.HIGH,
        replacement: Optional[str] = None
    ) -> "RedactionPattern":
        """Create pattern from regex string."""
        if replacement is None:
            replacement = f"[{name.upper()}]"
        return cls(
            name=name,
            pattern=re.compile(regex, re.IGNORECASE),
            sensitivity=sensitivity,
            replacement=replacement
        )


# Default redaction patterns
DEFAULT_PATTERNS: List[RedactionPattern] = [
    # Email addresses
    RedactionPattern.from_regex(
        name="email",
        regex=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        sensitivity=SensitivityLevel.MEDIUM,
        replacement="[EMAIL]"
    ),
    
    # API keys (various formats)
    RedactionPattern.from_regex(
        name="api_key",
        regex=r"(?:api[_-]?key|apikey)[\"']?\s*[:=]\s*[\"']?([a-zA-Z0-9_-]{20,})",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[API_KEY]"
    ),
    
    # Bearer tokens
    RedactionPattern.from_regex(
        name="bearer",
        regex=r"[Bb]earer\s+[a-zA-Z0-9._~+/=-]+",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[BEARER_TOKEN]"
    ),
    
    # Authorization headers
    RedactionPattern.from_regex(
        name="auth_header",
        regex=r"[Aa]uthorization[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9._~+/=-]+",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[AUTH_HEADER]"
    ),
    
    # Passwords
    RedactionPattern.from_regex(
        name="password",
        regex=r"(?:password|passwd|pwd)[\"']?\s*[:=]\s*[\"']?[^\s,\"'}{]+",
        sensitivity=SensitivityLevel.CRITICAL,
        replacement="[PASSWORD]"
    ),
    
    # Secret keys
    RedactionPattern.from_regex(
        name="secret_key",
        regex=r"(?:secret[_-]?key|secretkey)[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9_-]{16,}",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[SECRET_KEY]"
    ),
    
    # Private keys
    RedactionPattern.from_regex(
        name="private_key",
        regex=r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
        sensitivity=SensitivityLevel.CRITICAL,
        replacement="[PRIVATE_KEY]"
    ),
    
    # Credit card numbers (basic pattern)
    RedactionPattern.from_regex(
        name="credit_card",
        regex=r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        sensitivity=SensitivityLevel.CRITICAL,
        replacement="[CREDIT_CARD]"
    ),
    
    # SSN
    RedactionPattern.from_regex(
        name="ssn",
        regex=r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        sensitivity=SensitivityLevel.CRITICAL,
        replacement="[SSN]"
    ),
    
    # Turkish ID (TC Kimlik No)
    RedactionPattern.from_regex(
        name="tc_kimlik",
        regex=r"\b[1-9]\d{10}\b",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[TC_KIMLIK]"
    ),
    
    # Phone numbers
    RedactionPattern.from_regex(
        name="phone",
        regex=r"(?:\+\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}",
        sensitivity=SensitivityLevel.MEDIUM,
        replacement="[PHONE]"
    ),
    
    # AWS access key
    RedactionPattern.from_regex(
        name="aws_key",
        regex=r"(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[AWS_KEY]"
    ),
    
    # GitHub token
    RedactionPattern.from_regex(
        name="github_token",
        regex=r"gh[pousr]_[A-Za-z0-9_]{36,}",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[GITHUB_TOKEN]"
    ),
    
    # Generic token patterns
    RedactionPattern.from_regex(
        name="generic_token",
        regex=r"(?:token|access_token|refresh_token)[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9._~+/=-]{20,}",
        sensitivity=SensitivityLevel.HIGH,
        replacement="[TOKEN]"
    ),
]


# Keys that should always be redacted in dicts
SENSITIVE_KEYS: Set[str] = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "bearer",
    "authorization",
    "auth",
    "private_key",
    "secret_key",
    "credentials",
    "ssn",
    "credit_card",
    "cc_number",
}


class LogRedactor:
    """
    Redact sensitive information from logs.
    
    Uses pattern matching to detect and mask sensitive data.
    """
    
    def __init__(
        self,
        patterns: Optional[List[RedactionPattern]] = None,
        sensitive_keys: Optional[Set[str]] = None,
        min_sensitivity: SensitivityLevel = SensitivityLevel.MEDIUM
    ):
        """
        Initialize redactor.
        
        Args:
            patterns: Redaction patterns to use. Defaults to DEFAULT_PATTERNS.
            sensitive_keys: Dictionary keys to always redact. Defaults to SENSITIVE_KEYS.
            min_sensitivity: Minimum sensitivity level to redact
        """
        self._patterns = patterns if patterns is not None else DEFAULT_PATTERNS.copy()
        self._sensitive_keys = sensitive_keys if sensitive_keys is not None else SENSITIVE_KEYS.copy()
        self._min_sensitivity = min_sensitivity
        
        # Pre-compute sensitivity order for comparison
        self._sensitivity_order = {
            SensitivityLevel.LOW: 0,
            SensitivityLevel.MEDIUM: 1,
            SensitivityLevel.HIGH: 2,
            SensitivityLevel.CRITICAL: 3,
        }
    
    def _should_redact(self, sensitivity: SensitivityLevel) -> bool:
        """Check if sensitivity level should be redacted."""
        return (
            self._sensitivity_order[sensitivity] >= 
            self._sensitivity_order[self._min_sensitivity]
        )
    
    def redact(self, text: str) -> str:
        """
        Redact sensitive information from text.
        
        Args:
            text: Text to redact
            
        Returns:
            Redacted text
        """
        result = text
        
        for pattern in self._patterns:
            if self._should_redact(pattern.sensitivity):
                result = pattern.pattern.sub(pattern.replacement, result)
        
        return result
    
    def redact_dict(
        self,
        data: Dict[str, Any],
        recursive: bool = True
    ) -> Dict[str, Any]:
        """
        Redact sensitive information from dictionary.
        
        Args:
            data: Dictionary to redact
            recursive: Whether to recurse into nested dicts
            
        Returns:
            Redacted dictionary (new copy)
        """
        result = {}
        
        for key, value in data.items():
            # Check if key is sensitive
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in self._sensitive_keys):
                result[key] = "[REDACTED]"
            elif isinstance(value, dict) and recursive:
                result[key] = self.redact_dict(value, recursive=True)
            elif isinstance(value, list) and recursive:
                result[key] = [
                    self.redact_dict(item, recursive=True) if isinstance(item, dict)
                    else self.redact(str(item)) if isinstance(item, str)
                    else item
                    for item in value
                ]
            elif isinstance(value, str):
                result[key] = self.redact(value)
            else:
                result[key] = value
        
        return result
    
    def add_pattern(self, pattern: RedactionPattern) -> None:
        """Add a redaction pattern."""
        self._patterns.append(pattern)
    
    def add_sensitive_key(self, key: str) -> None:
        """Add a sensitive dictionary key."""
        self._sensitive_keys.add(key.lower())
    
    def remove_pattern(self, name: str) -> bool:
        """Remove a pattern by name."""
        for i, pattern in enumerate(self._patterns):
            if pattern.name == name:
                self._patterns.pop(i)
                return True
        return False
    
    def list_patterns(self) -> List[str]:
        """List all pattern names."""
        return [p.name for p in self._patterns]


def create_log_redactor(
    min_sensitivity: SensitivityLevel = SensitivityLevel.MEDIUM,
    additional_patterns: Optional[List[RedactionPattern]] = None
) -> LogRedactor:
    """
    Factory for creating log redactor.
    
    Args:
        min_sensitivity: Minimum sensitivity level to redact
        additional_patterns: Additional patterns to add
        
    Returns:
        Configured LogRedactor
    """
    redactor = LogRedactor(min_sensitivity=min_sensitivity)
    
    if additional_patterns:
        for pattern in additional_patterns:
            redactor.add_pattern(pattern)
    
    return redactor
