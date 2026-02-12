"""Memory-lite: Rolling dialog summary without CoT storage (Issue #141).

Provides:
- Compact summary (1-2 sentences per turn)
- PII filtering (email, phone, SSN, etc.)
- Rolling window (max 500 tokens)
- Prompt injection for orchestrator

Design:
- No raw CoT storage
- Last 5 turns kept in memory
- Evict oldest if over token limit
- Filter PII before storage
"""

from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

__all__ = [
    "CompactSummary",
    "PIIFilter",
    "DialogSummaryManager",
]


# =============================================================================
# Compact Summary
# =============================================================================

@dataclass
class CompactSummary:
    """Compact summary of a single conversation turn.
    
    Memory-lite design: Store only essential information in 1-2 sentences.
    """
    
    turn_number: int
    user_intent: str  # "asked about calendar" | "greeting" | "task request"
    action_taken: str  # "listed events" | "greeted back" | "created meeting"
    pending_items: list[str] = field(default_factory=list)  # ["waiting for confirmation"]
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_prompt_block(self) -> str:
        """Convert to compact prompt format.
        
        Example:
            Turn 1: User asked about calendar, I listed events.
            Turn 2: User requested meeting, I created event. Pending: confirmation
        """
        line = f"Turn {self.turn_number}: User {self.user_intent}, I {self.action_taken}."
        
        if self.pending_items:
            pending_str = ", ".join(self.pending_items)
            line += f" Pending: {pending_str}"
        
        return line
    
    def __str__(self) -> str:
        return self.to_prompt_block()


# =============================================================================
# PII Filter
# =============================================================================

class PIIFilter:
    """Filter Personally Identifiable Information from summaries.
    
    Supports both international and Turkish-specific PII patterns.
    
    International patterns:
    - Email: user@example.com → <EMAIL>
    - Phone (US): 555-123-4567 → <PHONE>
    - Credit Card: 1234-5678-9012-3456 → <CREDIT_CARD>
    - SSN: 123-45-6789 → <SSN>
    - Address (EN): 123 Main Street → <ADDRESS>
    - URL: https://example.com → <URL>
    
    Turkish patterns (Issue #414):
    - TC Kimlik No: 11 haneli rakam → <TC_KIMLIK>
    - TR Phone: +90 5xx xxx xx xx → <TR_PHONE>
    - IBAN: TR + 24 rakam → <IBAN>
    - Turkish Address: Mahalle/Cadde/Sokak → <TR_ADDRESS>
    - License Plate: 34 ABC 123 → <PLAKA>
    """
    
    # ── International patterns ────────────────────────────────────────
    PATTERNS = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone": r'\b(\+?\d{1,3}[\s-])?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b',
        "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "address": r'\b\d+\s+[A-Za-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln)\b',
        "url": r'https?://[^\s]+',
    }

    # ── Turkish-specific patterns (Issue #414) ────────────────────────
    TR_PATTERNS = {
        # TC Kimlik: exactly 11 digits at word boundary
        # (must start with non-zero, exactly 11 digits)
        # Issue #892: Regex-only matching causes false positives on event IDs,
        # timestamps, phone numbers etc. Actual redaction uses _is_valid_tc()
        # checksum validation (see filter() method).
        "tc_kimlik": r'\b[1-9]\d{10}\b',
        # TR Phone: +90 5xx or 05xx with various separators
        "tr_phone": r'(?:\+90[\s.-]?|0)5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}\b',
        # IBAN: TR + 2 check digits + 5 bank code + 16 account
        "iban": r'\bTR\s?\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b',
        # Turkish address: Mahalle, Cadde, Sokak, Bulvar patterns
        "tr_address": (
            r'\b\w+\s+'
            r'(?:Mahallesi|Mah\.|Caddesi|Cad\.|Sokak|Sok\.|Sokağı|Bulvarı|Blv\.)'
            r'(?:\s+[^,\n]{1,60})?'
        ),
        # License plate: 2-digit city code + up to 3 letters + up to 4 digits
        # e.g. 34 ABC 123, 06 A 1234, 01 AB 123
        # Negative lookbehind: exclude ISO 8601 timestamps like 2026-02-01T10:00:00
        "plaka": r'(?<![-/])\b(?:0[1-9]|[1-7]\d|8[01])\s?[A-Z]{1,3}\s?\d{1,4}\b',
    }
    
    @staticmethod
    def _is_valid_tc(num_str: str) -> bool:
        """Validate a TC Kimlik number using the official checksum algorithm.

        Issue #892: The 11-digit regex alone matches event IDs, Unix
        timestamps and phone numbers.  The TC Kimlik checksum narrows
        matches to plausible national-ID numbers only.

        Rules:
        - First digit != 0
        - 10th digit = (sum_of_odd_positions * 7 - sum_of_even_positions) % 10
        - 11th digit = sum_of_first_10_digits % 10
        """
        if len(num_str) != 11 or not num_str.isdigit():
            return False
        digits = [int(d) for d in num_str]
        if digits[0] == 0:
            return False
        odd_sum = sum(digits[i] for i in range(0, 9, 2))   # 1st,3rd,5th,7th,9th
        even_sum = sum(digits[i] for i in range(1, 8, 2))   # 2nd,4th,6th,8th
        if (odd_sum * 7 - even_sum) % 10 != digits[9]:
            return False
        if sum(digits[:10]) % 10 != digits[10]:
            return False
        return True

    @classmethod
    def filter(cls, text: str, enabled: bool = True, *, locale: str = "auto") -> str:
        """Replace PII with placeholders.
        
        Args:
            text: Input text potentially containing PII
            enabled: If False, return text unchanged (for debugging)
            locale: ``"auto"`` (detect), ``"tr"`` (Turkish), ``"en"`` (English only)
        
        Returns:
            Filtered text with PII replaced by <TYPE> placeholders
        """
        if not enabled:
            return text
        
        filtered = text

        # Apply Turkish patterns FIRST (IBAN before credit_card to avoid partial matches)
        if locale in ("tr", "auto"):
            for pii_type, pattern in cls.TR_PATTERNS.items():
                if pii_type == "tc_kimlik":
                    # Issue #892: Use checksum validation to avoid false positives
                    filtered = re.sub(
                        pattern,
                        lambda m: "<TC_KIMLIK>" if cls._is_valid_tc(m.group()) else m.group(),
                        filtered,
                    )
                else:
                    filtered = re.sub(pattern, f"<{pii_type.upper()}>", filtered)

        # Then apply international patterns
        for pii_type, pattern in cls.PATTERNS.items():
            filtered = re.sub(pattern, f"<{pii_type.upper()}>", filtered, flags=re.IGNORECASE)
        
        return filtered


# =============================================================================
# Dialog Summary Manager
# =============================================================================

class DialogSummaryManager:
    """Manage rolling dialog summary with token limit.
    
    Thread-safe (Issue #415): All mutable operations protected by
    ``threading.Lock`` to prevent race conditions during concurrent
    barge-in or async pipeline access.
    
    Memory-lite strategy:
    - Store last N turns (configurable)
    - Max 500 tokens total (evict oldest if exceeded)
    - Filter PII before storage
    - Generate DIALOG_SUMMARY block for prompt injection
    
    Usage:
        >>> manager = DialogSummaryManager(max_tokens=500)
        >>> summary = CompactSummary(
        ...     turn_number=1,
        ...     user_intent="asked about calendar",
        ...     action_taken="listed events"
        ... )
        >>> manager.add_turn(summary)
        >>> prompt_block = manager.to_prompt_block()
    """
    
    def __init__(
        self,
        max_tokens: int = 500,
        max_turns: int = 5,
        pii_filter_enabled: bool = True,
    ):
        """Initialize dialog summary manager.
        
        Args:
            max_tokens: Maximum tokens for entire summary (evict oldest if exceeded)
            max_turns: Maximum number of turns to keep (even if under token limit)
            pii_filter_enabled: Whether to filter PII from summaries
        """
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.pii_filter_enabled = pii_filter_enabled
        self.summaries: list[CompactSummary] = []
        self._lock = threading.Lock()
    
    def add_turn(self, summary: CompactSummary) -> None:
        """Add new turn summary to rolling window (thread-safe).
        
        Automatically:
        - Filters PII if enabled
        - Evicts oldest turns if over token limit
        - Keeps max N turns regardless of token count
        """
        # Deep-copy so we don't mutate the caller's object and avoid
        # TOCTOU races when two threads share the same CompactSummary.
        summary = copy.deepcopy(summary)

        # Filter PII on private copy (CPU-bound, safe outside lock)
        if self.pii_filter_enabled:
            summary.user_intent = PIIFilter.filter(summary.user_intent)
            summary.action_taken = PIIFilter.filter(summary.action_taken)
            summary.pending_items = [
                PIIFilter.filter(item) for item in summary.pending_items
            ]
        
        with self._lock:
            self.summaries.append(summary)
            
            # Enforce max turns limit
            while len(self.summaries) > self.max_turns:
                self.summaries.pop(0)
            
            # Enforce token limit (evict oldest)
            while self._estimate_tokens_unlocked() > self.max_tokens and len(self.summaries) > 1:
                self.summaries.pop(0)
    
    def _estimate_tokens_unlocked(self) -> int:
        """Estimate total tokens (caller must hold _lock).
        
        Issue #406: Uses unified token estimator (chars4 heuristic).
        """
        from bantz.llm.token_utils import estimate_tokens

        text = "\n".join(s.to_prompt_block() for s in self.summaries)
        return estimate_tokens(text)

    def _estimate_tokens(self) -> int:
        """Estimate total tokens in all summaries (thread-safe)."""
        with self._lock:
            return self._estimate_tokens_unlocked()
    
    def to_prompt_block(self) -> str:
        """Generate DIALOG_SUMMARY block for orchestrator prompt (thread-safe).
        
        Returns:
            Formatted summary block for injection into LLM prompt.
            Empty string if no summaries.
        
        Example:
            DIALOG_SUMMARY (last few turns):
              Turn 1: User asked about calendar, I listed events.
              Turn 2: User requested meeting, I created event. Pending: confirmation
        """
        with self._lock:
            if not self.summaries:
                return ""
            
            lines = ["DIALOG_SUMMARY (last few turns):"]
            for summary in self.summaries:
                lines.append(f"  {summary.to_prompt_block()}")
            
            return "\n".join(lines)
    
    def clear(self) -> None:
        """Clear all summaries (thread-safe)."""
        with self._lock:
            self.summaries.clear()
    
    def get_latest(self) -> Optional[CompactSummary]:
        """Get most recent summary (thread-safe)."""
        with self._lock:
            return self.summaries[-1] if self.summaries else None
    
    def __len__(self) -> int:
        """Number of turns in memory (thread-safe)."""
        with self._lock:
            return len(self.summaries)
    
    def __str__(self) -> str:
        return self.to_prompt_block()
