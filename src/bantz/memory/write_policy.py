"""
Write Policy Engine for V2-4 Memory System (Issue #36).

Controls what can be written to memory:
- Detects sensitive patterns (email, credit card, TC kimlik, passwords)
- Provides ALLOW/DENY/REDACT/ENCRYPT decisions
- Different policies for different memory types

Protects user privacy by filtering sensitive data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Pattern, Tuple

from bantz.memory.snippet import SnippetType


class WriteDecision(Enum):
    """Decision on whether to write memory."""
    
    ALLOW = "allow"       # Write as-is
    DENY = "deny"         # Do not write
    REDACT = "redact"     # Write with sensitive parts removed
    ENCRYPT = "encrypt"   # Write encrypted (future feature)


@dataclass
class PolicyResult:
    """Result of policy check."""
    
    decision: WriteDecision
    reason: Optional[str] = None
    redacted_content: Optional[str] = None
    matched_patterns: List[str] = field(default_factory=list)
    
    @property
    def is_allowed(self) -> bool:
        """Check if write is allowed (directly or with redaction)."""
        return self.decision in (WriteDecision.ALLOW, WriteDecision.REDACT)
    
    @property
    def final_content(self) -> Optional[str]:
        """Get final content to write (redacted if needed)."""
        if self.decision == WriteDecision.REDACT:
            return self.redacted_content
        elif self.decision == WriteDecision.ALLOW:
            return None  # Use original
        return None  # DENY/ENCRYPT don't have content


class SensitivePattern:
    """A sensitive pattern to detect."""
    
    def __init__(
        self,
        name: str,
        pattern: str,
        decision: WriteDecision = WriteDecision.REDACT,
        replacement: str = "[REDACTED]"
    ):
        """
        Initialize pattern.
        
        Args:
            name: Pattern name for reporting
            pattern: Regex pattern
            decision: What to do when matched
            replacement: Replacement text for redaction
        """
        self.name = name
        self.pattern = pattern
        self.regex: Pattern = re.compile(pattern, re.IGNORECASE)
        self.decision = decision
        self.replacement = replacement
    
    def matches(self, content: str) -> List[str]:
        """Find all matches in content."""
        return self.regex.findall(content)
    
    def redact(self, content: str) -> str:
        """Redact matches from content."""
        return self.regex.sub(self.replacement, content)


# Default sensitive patterns
DEFAULT_PATTERNS = [
    # Email addresses
    SensitivePattern(
        name="email",
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        decision=WriteDecision.REDACT,
        replacement="[EMAIL]"
    ),
    # Credit card numbers (16 digits, various formats)
    SensitivePattern(
        name="credit_card",
        pattern=r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        decision=WriteDecision.REDACT,
        replacement="[CREDIT_CARD]"
    ),
    # Turkish TC Kimlik (11 digits)
    SensitivePattern(
        name="tc_kimlik",
        pattern=r"\b\d{11}\b",
        decision=WriteDecision.REDACT,
        replacement="[TC_KIMLIK]"
    ),
    # Phone numbers (Turkish format)
    SensitivePattern(
        name="phone_tr",
        pattern=r"\b(?:\+90|0)?[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b",
        decision=WriteDecision.REDACT,
        replacement="[PHONE]"
    ),
    # Passwords (explicit mentions)
    SensitivePattern(
        name="password",
        pattern=r"(?i)\b(?:password|şifre|parola|sifre)\s*[:=]\s*\S+",
        decision=WriteDecision.DENY,
        replacement=""
    ),
    # API keys / tokens
    SensitivePattern(
        name="api_key",
        pattern=r"(?i)\b(?:api[_-]?key|token|secret)\s*[:=]\s*['\"]?[\w-]{20,}['\"]?",
        decision=WriteDecision.DENY,
        replacement=""
    ),
    # IBAN numbers
    SensitivePattern(
        name="iban",
        pattern=r"\b[A-Z]{2}\d{2}[\s]?(?:\d{4}[\s]?){4,6}\d{0,4}\b",
        decision=WriteDecision.REDACT,
        replacement="[IBAN]"
    ),
]


class WritePolicy:
    """
    Policy engine for memory writes.
    
    Checks content for sensitive patterns and decides whether to:
    - Allow the write
    - Deny the write
    - Redact sensitive parts and allow
    """
    
    def __init__(
        self,
        patterns: Optional[List[SensitivePattern]] = None,
        strict_mode: bool = False
    ):
        """
        Initialize write policy.
        
        Args:
            patterns: List of sensitive patterns. Uses defaults if None.
            strict_mode: If True, DENY on any sensitive pattern
        """
        self._patterns = patterns or DEFAULT_PATTERNS.copy()
        self._strict_mode = strict_mode
    
    def check(
        self,
        content: str,
        snippet_type: SnippetType = SnippetType.SESSION
    ) -> PolicyResult:
        """
        Check content against policy.
        
        Args:
            content: Content to check
            snippet_type: Type of memory (affects strictness)
            
        Returns:
            PolicyResult with decision and optional redacted content
        """
        if not content or not content.strip():
            return PolicyResult(
                decision=WriteDecision.ALLOW,
                reason="Empty content"
            )
        
        matched_patterns: List[str] = []
        should_deny = False
        
        # Check all patterns
        for pattern in self._patterns:
            matches = pattern.matches(content)
            if matches:
                matched_patterns.append(pattern.name)
                
                # Password and API keys always deny
                if pattern.decision == WriteDecision.DENY:
                    should_deny = True
        
        # No sensitive patterns found
        if not matched_patterns:
            return PolicyResult(
                decision=WriteDecision.ALLOW,
                reason="No sensitive patterns detected"
            )
        
        # Strict mode or deny patterns -> DENY
        if should_deny or self._strict_mode:
            return PolicyResult(
                decision=WriteDecision.DENY,
                reason=f"Sensitive content detected: {', '.join(matched_patterns)}",
                matched_patterns=matched_patterns
            )
        
        # Profile type is stricter - deny if sensitive
        if snippet_type == SnippetType.PROFILE and len(matched_patterns) > 0:
            # For profile, we redact instead of deny
            redacted = self.redact_sensitive(content)
            return PolicyResult(
                decision=WriteDecision.REDACT,
                reason=f"Profile memory - sensitive content redacted: {', '.join(matched_patterns)}",
                redacted_content=redacted,
                matched_patterns=matched_patterns
            )
        
        # Default: redact sensitive parts
        redacted = self.redact_sensitive(content)
        return PolicyResult(
            decision=WriteDecision.REDACT,
            reason=f"Sensitive content redacted: {', '.join(matched_patterns)}",
            redacted_content=redacted,
            matched_patterns=matched_patterns
        )
    
    def redact_sensitive(self, content: str) -> str:
        """
        Redact all sensitive patterns from content.
        
        All patterns are applied regardless of their decision type
        (ALLOW, DENY, REDACT, ENCRYPT) — when redacting, the goal is
        to strip every piece of sensitive data.
        
        Args:
            content: Content to redact
            
        Returns:
            Content with sensitive parts replaced
        """
        result = content
        
        for pattern in self._patterns:
            result = pattern.redact(result)
        
        return result
    
    def add_pattern(self, pattern: SensitivePattern) -> None:
        """Add a new sensitive pattern."""
        self._patterns.append(pattern)
    
    def remove_pattern(self, name: str) -> bool:
        """Remove a pattern by name."""
        for i, p in enumerate(self._patterns):
            if p.name == name:
                self._patterns.pop(i)
                return True
        return False
    
    @property
    def patterns(self) -> List[SensitivePattern]:
        """Get all registered patterns."""
        return self._patterns.copy()
    
    @property
    def pattern_names(self) -> List[str]:
        """Get names of all patterns."""
        return [p.name for p in self._patterns]


def create_write_policy(
    strict_mode: bool = False,
    custom_patterns: Optional[List[SensitivePattern]] = None
) -> WritePolicy:
    """
    Factory function for creating write policy.
    
    Args:
        strict_mode: If True, deny on any sensitive pattern
        custom_patterns: Additional patterns to add
        
    Returns:
        WritePolicy instance
    """
    patterns = DEFAULT_PATTERNS.copy()
    
    if custom_patterns:
        patterns.extend(custom_patterns)
    
    return WritePolicy(patterns=patterns, strict_mode=strict_mode)
