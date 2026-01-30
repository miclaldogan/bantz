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

import re
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
    
    Patterns:
    - Email: user@example.com → <EMAIL>
    - Phone: 555-123-4567 → <PHONE>
    - Credit Card: 1234-5678-9012-3456 → <CREDIT_CARD>
    - SSN: 123-45-6789 → <SSN>
    - Address: 123 Main Street → <ADDRESS>
    """
    
    PATTERNS = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone": r'\b(\+?\d{1,3}[\s-])?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b',
        "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "address": r'\b\d+\s+[A-Za-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln)\b',
        "url": r'https?://[^\s]+',
    }
    
    @classmethod
    def filter(cls, text: str, enabled: bool = True) -> str:
        """Replace PII with placeholders.
        
        Args:
            text: Input text potentially containing PII
            enabled: If False, return text unchanged (for debugging)
        
        Returns:
            Filtered text with PII replaced by <TYPE> placeholders
        """
        if not enabled:
            return text
        
        filtered = text
        for pii_type, pattern in cls.PATTERNS.items():
            filtered = re.sub(pattern, f"<{pii_type.upper()}>", filtered, flags=re.IGNORECASE)
        
        return filtered


# =============================================================================
# Dialog Summary Manager
# =============================================================================

class DialogSummaryManager:
    """Manage rolling dialog summary with token limit.
    
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
    
    def add_turn(self, summary: CompactSummary) -> None:
        """Add new turn summary to rolling window.
        
        Automatically:
        - Filters PII if enabled
        - Evicts oldest turns if over token limit
        - Keeps max N turns regardless of token count
        """
        # Filter PII before storing
        if self.pii_filter_enabled:
            summary.user_intent = PIIFilter.filter(summary.user_intent)
            summary.action_taken = PIIFilter.filter(summary.action_taken)
            summary.pending_items = [
                PIIFilter.filter(item) for item in summary.pending_items
            ]
        
        self.summaries.append(summary)
        
        # Enforce max turns limit
        while len(self.summaries) > self.max_turns:
            self.summaries.pop(0)
        
        # Enforce token limit (evict oldest)
        while self._estimate_tokens() > self.max_tokens and len(self.summaries) > 1:
            self.summaries.pop(0)
    
    def _estimate_tokens(self) -> int:
        """Estimate total tokens in all summaries.
        
        Rough approximation: 1 token ≈ 1 word (good enough for Turkish/English)
        """
        text = "\n".join(s.to_prompt_block() for s in self.summaries)
        return len(text.split())
    
    def to_prompt_block(self) -> str:
        """Generate DIALOG_SUMMARY block for orchestrator prompt.
        
        Returns:
            Formatted summary block for injection into LLM prompt.
            Empty string if no summaries.
        
        Example:
            DIALOG_SUMMARY (last few turns):
              Turn 1: User asked about calendar, I listed events.
              Turn 2: User requested meeting, I created event. Pending: confirmation
        """
        if not self.summaries:
            return ""
        
        lines = ["DIALOG_SUMMARY (last few turns):"]
        for summary in self.summaries:
            lines.append(f"  {summary.to_prompt_block()}")
        
        return "\n".join(lines)
    
    def clear(self) -> None:
        """Clear all summaries (e.g., session reset)."""
        self.summaries.clear()
    
    def get_latest(self) -> Optional[CompactSummary]:
        """Get most recent summary."""
        return self.summaries[-1] if self.summaries else None
    
    def __len__(self) -> int:
        """Number of turns in memory."""
        return len(self.summaries)
    
    def __str__(self) -> str:
        return self.to_prompt_block()
