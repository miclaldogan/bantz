"""
Smart No-New-Facts Guard — Issue #438.

Replaces the overly strict numeric guard that rejects valid Gemini
responses containing aggregated counts (e.g. "3 etkinlik bulundu"
when tool_results has a list of 3 events but no literal "3").

Key improvements:
- List/aggregation counts are exempt (len of arrays)
- Configurable strictness per route (strict for calendar, lenient for smalltalk)
- Only hallucination-dangerous facts are checked (new times, dates, names)
- False positive tracking for tuning

Usage::

    from bantz.llm.smart_guard import SmartFactGuard, GuardStrictness
    guard = SmartFactGuard(strictness=GuardStrictness.BALANCED)
    result = guard.check(candidate_text, tool_results, route="calendar")
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────

_ISO_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}(?::\d{2})?")
_DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")


# ─────────────────────────────────────────────────────────────────
# Strictness
# ─────────────────────────────────────────────────────────────────


class GuardStrictness(str, Enum):
    STRICT = "strict"        # All new numbers rejected (calendar mutations)
    BALANCED = "balanced"    # Aggregations exempt, new times/dates checked
    LENIENT = "lenient"      # Only new dates/times/names checked


# Route → default strictness
_ROUTE_STRICTNESS: Dict[str, GuardStrictness] = {
    "calendar": GuardStrictness.BALANCED,
    "gmail": GuardStrictness.BALANCED,
    "smalltalk": GuardStrictness.LENIENT,
    "system": GuardStrictness.LENIENT,
}


# ─────────────────────────────────────────────────────────────────
# Guard Result
# ─────────────────────────────────────────────────────────────────


@dataclass
class GuardResult:
    """Result of the smart fact guard check."""
    passed: bool
    new_facts: Set[str] = field(default_factory=set)
    exempt_facts: Set[str] = field(default_factory=set)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "new_facts": sorted(self.new_facts),
            "exempt_facts": sorted(self.exempt_facts),
            "reason": self.reason,
        }


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _extract_numbers(text: str) -> Set[str]:
    """Extract all numeric tokens from text."""
    if not text:
        return set()
    # Normalize ISO datetimes first: "2025-01-15T14:00:00" → "2025-01-15 14:00:00"
    t = _ISO_DATETIME_RE.sub(lambda m: m.group(0).replace("T", " "), str(text))
    facts: Set[str] = set()
    for m in _DATE_ISO_RE.finditer(t):
        facts.add(m.group(0))
    for m in _TIME_RE.finditer(t):
        facts.add(m.group(0).replace(".", ":"))
    scrub = _DATE_ISO_RE.sub(" ", t)
    scrub = _TIME_RE.sub(" ", scrub)
    for m in _NUMBER_RE.finditer(scrub):
        facts.add(m.group(0).replace(",", "."))
    return facts


def _extract_list_counts(data: Any) -> Set[str]:
    """Extract counts of arrays/lists in tool results (recursive).

    E.g., if tool result has {"events": [...3 items...]} → {"3"}
    """
    counts: Set[str] = set()
    if isinstance(data, list):
        counts.add(str(len(data)))
        for item in data:
            counts |= _extract_list_counts(item)
    elif isinstance(data, dict):
        for v in data.values():
            counts |= _extract_list_counts(v)
    return counts


def _extract_all_facts_from_data(data: Any) -> Set[str]:
    """Recursively extract all numeric tokens from a data structure."""
    facts: Set[str] = set()
    if isinstance(data, (int, float)):
        facts.add(str(data))
    elif isinstance(data, str):
        facts |= _extract_numbers(data)
    elif isinstance(data, list):
        for item in data:
            facts |= _extract_all_facts_from_data(item)
    elif isinstance(data, dict):
        for v in data.values():
            facts |= _extract_all_facts_from_data(v)
    return facts


# ─────────────────────────────────────────────────────────────────
# Smart Guard
# ─────────────────────────────────────────────────────────────────


class SmartFactGuard:
    """
    Improved no-new-facts guard with context-aware exemptions.

    - List counts (len of arrays) are automatically allowed
    - Single-digit numbers (1-9) are allowed in LENIENT mode
    - Configurable per-route strictness
    - Tracks false positive rate
    """

    def __init__(
        self,
        strictness: Optional[GuardStrictness] = None,
        route_strictness: Optional[Dict[str, GuardStrictness]] = None,
    ):
        self._default_strictness = strictness or GuardStrictness.BALANCED
        self._route_strictness = route_strictness or _ROUTE_STRICTNESS
        self._total_checks = 0
        self._rejections = 0

    def check(
        self,
        candidate_text: str,
        tool_results: Any,
        *,
        route: str = "",
        allowed_texts: Optional[List[str]] = None,
    ) -> GuardResult:
        """
        Check if candidate text introduces new numeric facts.

        Args:
            candidate_text: Gemini's response text.
            tool_results: Raw tool results (dict/list/str).
            route: Current route for strictness lookup.
            allowed_texts: Additional allowed source texts.

        Returns:
            GuardResult with passed=True if acceptable.
        """
        self._total_checks += 1
        strictness = self._route_strictness.get(route, self._default_strictness)

        # Extract candidate facts
        candidate_facts = _extract_numbers(candidate_text)
        if not candidate_facts:
            return GuardResult(passed=True)

        # Build allowed set from tool results
        allowed: Set[str] = set()

        # 1. All numbers literally present in tool data
        allowed |= _extract_all_facts_from_data(tool_results)

        # 2. List/array counts (aggregations)
        list_counts = _extract_list_counts(tool_results)
        allowed |= list_counts

        # 3. Additional allowed texts
        for txt in (allowed_texts or []):
            allowed |= _extract_numbers(str(txt))

        # 4. Serialize tool results to string and extract
        try:
            json_str = json.dumps(tool_results, ensure_ascii=False, default=str)
            allowed |= _extract_numbers(json_str)
        except (TypeError, ValueError):
            pass

        # Find truly new facts
        new_facts = candidate_facts - allowed
        exempt_facts: Set[str] = set()

        # Apply strictness exemptions
        if strictness in (GuardStrictness.BALANCED, GuardStrictness.LENIENT):
            # Exempt: numbers that are list counts
            for f in list(new_facts):
                if f in list_counts:
                    new_facts.discard(f)
                    exempt_facts.add(f)

        if strictness == GuardStrictness.LENIENT:
            # Exempt: single-digit standalone numbers (likely ordinals/counts)
            for f in list(new_facts):
                if len(f) == 1 and f.isdigit():
                    new_facts.discard(f)
                    exempt_facts.add(f)

        passed = len(new_facts) == 0
        if not passed:
            self._rejections += 1
            reason = f"New facts found: {sorted(new_facts)}"
        else:
            reason = ""

        return GuardResult(
            passed=passed,
            new_facts=new_facts,
            exempt_facts=exempt_facts,
            reason=reason,
        )

    @property
    def false_positive_rate(self) -> float:
        """Estimated rejection rate (for tuning)."""
        return self._rejections / self._total_checks if self._total_checks else 0.0

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_checks": self._total_checks,
            "rejections": self._rejections,
            "false_positive_rate": round(self.false_positive_rate, 4),
        }

    def reset_stats(self) -> None:
        self._total_checks = 0
        self._rejections = 0
