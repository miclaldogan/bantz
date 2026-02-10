"""Finalizer guard module for no-new-facts guarantee.

Issue #231: Ensures that the finalizer LLM does not invent new numeric/temporal
facts beyond what is provided in the source context.

This module provides:
- DiffGuard: Compares finalizer output against source data
- NumericPreservation: Validates numeric data preservation
- TimePreservation: Validates time/date data preservation
- FinalizerGuard: Main guard class combining all checks
"""

from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class ViolationType(Enum):
    """Types of no-new-facts violations."""
    NEW_NUMBER = "new_number"
    NEW_TIME = "new_time"
    NEW_DATE = "new_date"
    ALTERED_NUMBER = "altered_number"
    ALTERED_TIME = "altered_time"
    ALTERED_DATE = "altered_date"
    CURRENCY_INVENTED = "currency_invented"
    PERCENTAGE_INVENTED = "percentage_invented"


@dataclass
class Violation:
    """A single violation of the no-new-facts policy."""
    type: ViolationType
    value: str
    context: str = ""
    severity: str = "high"  # high, medium, low
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "value": self.value,
            "context": self.context,
            "severity": self.severity,
        }


@dataclass
class GuardResult:
    """Result of a finalizer guard check."""
    passed: bool
    violations: List[Violation] = field(default_factory=list)
    allowed_numbers: Set[str] = field(default_factory=set)
    allowed_times: Set[str] = field(default_factory=set)
    allowed_dates: Set[str] = field(default_factory=set)
    candidate_numbers: Set[str] = field(default_factory=set)
    candidate_times: Set[str] = field(default_factory=set)
    candidate_dates: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "violation_count": len(self.violations),
            "allowed_numbers_count": len(self.allowed_numbers),
            "candidate_numbers_count": len(self.candidate_numbers),
        }


# Regex patterns for extraction
_DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_SLASH_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_DATE_DOT_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
_TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}(?:[:.]\d{2})?\b")
_TIME_AMPM_RE = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|AM|PM|öğleden\s+sonra|sabah|akşam|gece)\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_CURRENCY_RE = re.compile(r"[\$€£₺]\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:TL|USD|EUR|GBP|dolar|euro|lira)\b", re.IGNORECASE)
_PERCENTAGE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*%")
_DURATION_RE = re.compile(r"\b\d+\s*(?:saat|dakika|gün|hafta|ay|yıl|saniye|hour|minute|day|week|month|year|second)s?\b", re.IGNORECASE)

# Turkish number words
TURKISH_NUMBERS: Dict[str, int] = {
    "sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4,
    "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
    "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50,
    "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90,
    "yüz": 100, "bin": 1000, "milyon": 1000000, "milyar": 1000000000,
    "buçuk": 0.5, "çeyrek": 0.25, "yarım": 0.5,
}

# List markers to ignore
_LIST_MARKER_RE = re.compile(r"^\s*(\d{1,2})([.\)\-:])\s+")


def _normalize_number(s: str) -> str:
    """Normalize a number string for comparison."""
    # Replace comma with dot for decimal
    n = s.replace(",", ".")
    # Remove leading zeros but keep "0" and "0.x"
    if "." in n:
        parts = n.split(".")
        parts[0] = str(int(parts[0])) if parts[0] else "0"
        n = ".".join(parts)
    else:
        try:
            n = str(int(n))
        except ValueError:
            pass
    return n


def _normalize_time(s: str) -> str:
    """Normalize a time string for comparison."""
    # Replace dot with colon
    t = s.replace(".", ":")
    # Ensure HH:MM format
    parts = t.split(":")
    if len(parts) >= 2:
        h = parts[0].zfill(2)
        m = parts[1].zfill(2)
        return f"{h}:{m}"
    return t


def extract_numbers(text: str) -> Set[str]:
    """Extract normalized numeric tokens from text."""
    if not text or not text.strip():
        return set()
    
    numbers: Set[str] = set()
    
    # First scrub dates to avoid double-counting
    scrub = _DATE_ISO_RE.sub(" ", text)
    scrub = _DATE_SLASH_RE.sub(" ", scrub)
    
    # Only scrub valid times (hours 0-23, minutes 0-59)
    def replace_valid_time(m: re.Match) -> str:
        t = m.group(0)
        parts = re.split(r'[.:]', t)
        if len(parts) == 2:
            try:
                h, m = int(parts[0]), int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    return " "  # Valid time, scrub it
            except ValueError:
                pass
        return t  # Not a valid time, keep it
    
    scrub = _TIME_RE.sub(replace_valid_time, scrub)
    scrub = _TIME_AMPM_RE.sub(" ", scrub)
    
    for m in _NUMBER_RE.finditer(scrub):
        token = _normalize_number(m.group(0))
        numbers.add(token)
    
    # Extract list markers to exclude
    lines = text.splitlines() or [text]
    list_markers: Set[str] = set()
    for line in lines:
        mm = _LIST_MARKER_RE.match(line)
        if mm:
            list_markers.add(str(int(mm.group(1))))
    
    # Filter out list markers
    return {n for n in numbers if n not in list_markers}


def extract_times(text: str) -> Set[str]:
    """Extract normalized time tokens from text."""
    if not text or not text.strip():
        return set()
    
    times: Set[str] = set()
    
    for m in _TIME_RE.finditer(text):
        token = _normalize_time(m.group(0))
        times.add(token)
    
    for m in _TIME_AMPM_RE.finditer(text):
        # Extract just the time part
        token = m.group(0)
        time_part = re.match(r"\d{1,2}(?:[:.]\d{2})?", token)
        if time_part:
            times.add(_normalize_time(time_part.group(0)))
    
    return times


def extract_dates(text: str) -> Set[str]:
    """Extract date tokens from text."""
    if not text or not text.strip():
        return set()
    
    dates: Set[str] = set()
    
    for m in _DATE_ISO_RE.finditer(text):
        dates.add(m.group(0))
    
    for m in _DATE_SLASH_RE.finditer(text):
        dates.add(m.group(0))
    
    for m in _DATE_DOT_RE.finditer(text):
        # Normalize to slash format
        d = m.group(0).replace(".", "/")
        dates.add(d)
    
    return dates


def extract_currencies(text: str) -> Set[str]:
    """Extract currency expressions from text."""
    if not text or not text.strip():
        return set()
    
    currencies: Set[str] = set()
    for m in _CURRENCY_RE.finditer(text):
        # Normalize: extract just the number
        num = re.search(r"\d+(?:[.,]\d+)?", m.group(0))
        if num:
            currencies.add(_normalize_number(num.group(0)))
    
    return currencies


def extract_percentages(text: str) -> Set[str]:
    """Extract percentage expressions from text."""
    if not text or not text.strip():
        return set()
    
    percentages: Set[str] = set()
    for m in _PERCENTAGE_RE.finditer(text):
        num = re.search(r"\d+(?:[.,]\d+)?", m.group(0))
        if num:
            percentages.add(_normalize_number(num.group(0)))
    
    return percentages


def extract_durations(text: str) -> Set[str]:
    """Extract duration expressions from text."""
    if not text or not text.strip():
        return set()
    
    durations: Set[str] = set()
    for m in _DURATION_RE.finditer(text):
        num = re.search(r"\d+", m.group(0))
        if num:
            durations.add(num.group(0))
    
    return durations


def extract_turkish_numbers(text: str) -> Set[str]:
    """Extract Turkish word numbers and convert to digits."""
    if not text or not text.strip():
        return set()
    
    numbers: Set[str] = set()
    text_lower = text.lower()
    
    for word, value in TURKISH_NUMBERS.items():
        if word in text_lower:
            if isinstance(value, float):
                numbers.add(str(value))
            else:
                numbers.add(str(value))
    
    return numbers


class NumericPreservation:
    """Validates that numeric data is preserved from source to output."""
    
    @staticmethod
    def check(source_texts: List[str], candidate_text: str) -> Tuple[bool, Set[str]]:
        """Check if candidate contains only numbers from source.
        
        Returns:
            (passed, new_numbers): True if no new numbers, set of new numbers if any
        """
        allowed: Set[str] = set()
        for src in source_texts:
            allowed |= extract_numbers(str(src or ""))
            allowed |= extract_turkish_numbers(str(src or ""))
        
        candidate_nums = extract_numbers(candidate_text)
        candidate_nums |= extract_turkish_numbers(candidate_text)
        
        new_nums = candidate_nums - allowed
        
        return (len(new_nums) == 0, new_nums)


class TimePreservation:
    """Validates that time/date data is preserved from source to output."""
    
    @staticmethod
    def check_times(source_texts: List[str], candidate_text: str) -> Tuple[bool, Set[str]]:
        """Check if candidate contains only times from source."""
        allowed: Set[str] = set()
        for src in source_texts:
            allowed |= extract_times(str(src or ""))
        
        candidate_times = extract_times(candidate_text)
        new_times = candidate_times - allowed
        
        return (len(new_times) == 0, new_times)
    
    @staticmethod
    def check_dates(source_texts: List[str], candidate_text: str) -> Tuple[bool, Set[str]]:
        """Check if candidate contains only dates from source."""
        allowed: Set[str] = set()
        for src in source_texts:
            allowed |= extract_dates(str(src or ""))
        
        candidate_dates = extract_dates(candidate_text)
        new_dates = candidate_dates - allowed
        
        return (len(new_dates) == 0, new_dates)


class DiffGuard:
    """Compares finalizer output against source context for fact validation."""
    
    def __init__(self, strict_mode: bool = True):
        """Initialize DiffGuard.
        
        Args:
            strict_mode: If True, any new numeric/temporal fact fails the check
        """
        self.strict_mode = strict_mode
    
    def check(
        self,
        source_texts: List[str],
        candidate_text: str,
        check_currencies: bool = True,
        check_percentages: bool = True,
    ) -> GuardResult:
        """Perform full diff guard check.
        
        Args:
            source_texts: List of source texts (user input, tool results, etc.)
            candidate_text: The finalizer output to validate
            check_currencies: Whether to check currency expressions
            check_percentages: Whether to check percentage expressions
        
        Returns:
            GuardResult with pass/fail and any violations
        """
        violations: List[Violation] = []
        
        # Collect allowed facts from sources
        allowed_numbers: Set[str] = set()
        allowed_times: Set[str] = set()
        allowed_dates: Set[str] = set()
        allowed_currencies: Set[str] = set()
        allowed_percentages: Set[str] = set()
        
        for src in source_texts:
            src_text = str(src or "")
            allowed_numbers |= extract_numbers(src_text)
            allowed_numbers |= extract_turkish_numbers(src_text)
            allowed_times |= extract_times(src_text)
            allowed_dates |= extract_dates(src_text)
            if check_currencies:
                allowed_currencies |= extract_currencies(src_text)
            if check_percentages:
                allowed_percentages |= extract_percentages(src_text)
        
        # Extract facts from candidate
        candidate_numbers = extract_numbers(candidate_text)
        candidate_numbers |= extract_turkish_numbers(candidate_text)
        candidate_times = extract_times(candidate_text)
        candidate_dates = extract_dates(candidate_text)
        
        # Check for new numbers
        new_numbers = candidate_numbers - allowed_numbers
        # Filter harmless single digits only if they are simple list-like items
        # Keep single digits if they appear in meaningful context
        for num in new_numbers:
            violations.append(Violation(
                type=ViolationType.NEW_NUMBER,
                value=num,
                severity="high" if len(num) > 1 else "medium",
            ))
        
        # Check for new times
        new_times = candidate_times - allowed_times
        for t in new_times:
            violations.append(Violation(
                type=ViolationType.NEW_TIME,
                value=t,
                severity="high",
            ))
        
        # Check for new dates
        new_dates = candidate_dates - allowed_dates
        for d in new_dates:
            violations.append(Violation(
                type=ViolationType.NEW_DATE,
                value=d,
                severity="high",
            ))
        
        # Check currencies if enabled
        if check_currencies:
            candidate_currencies = extract_currencies(candidate_text)
            new_currencies = candidate_currencies - allowed_currencies - allowed_numbers
            for c in new_currencies:
                violations.append(Violation(
                    type=ViolationType.CURRENCY_INVENTED,
                    value=c,
                    severity="high",
                ))
        
        # Check percentages if enabled
        if check_percentages:
            candidate_percentages = extract_percentages(candidate_text)
            new_percentages = candidate_percentages - allowed_percentages - allowed_numbers
            for p in new_percentages:
                violations.append(Violation(
                    type=ViolationType.PERCENTAGE_INVENTED,
                    value=p,
                    severity="medium",
                ))
        
        passed = len(violations) == 0
        
        return GuardResult(
            passed=passed,
            violations=violations,
            allowed_numbers=allowed_numbers,
            allowed_times=allowed_times,
            allowed_dates=allowed_dates,
            candidate_numbers=candidate_numbers,
            candidate_times=candidate_times,
            candidate_dates=candidate_dates,
        )


class FinalizerGuard:
    """Main guard class combining all no-new-facts checks.
    
    Usage:
        guard = FinalizerGuard()
        result = guard.validate(
            user_input="Yarın saat 14:00'de toplantı koy",
            planner_decision={"slots": {"time": "14:00"}},
            tool_results=[{"success": True}],
            candidate_text="Toplantınızı 14:30'a ayarladım.",
        )
        if not result.passed:
            # Reject or retry
    """
    
    def __init__(
        self,
        strict_mode: bool = True,
        check_currencies: bool = True,
        check_percentages: bool = True,
        max_violations: int = 0,
    ):
        """Initialize FinalizerGuard.
        
        Args:
            strict_mode: If True, any violation fails the check
            check_currencies: Whether to validate currency expressions
            check_percentages: Whether to validate percentage expressions
            max_violations: Maximum allowed violations before failing (0 = none)
        """
        self.strict_mode = strict_mode
        self.check_currencies = check_currencies
        self.check_percentages = check_percentages
        self.max_violations = max_violations
        self.diff_guard = DiffGuard(strict_mode=strict_mode)
    
    def validate(
        self,
        user_input: str,
        planner_decision: Optional[Dict[str, Any]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        dialog_summary: Optional[str] = None,
        candidate_text: str = "",
    ) -> GuardResult:
        """Validate finalizer output against source context.
        
        Args:
            user_input: Original user input
            planner_decision: Planner/router decision dict
            tool_results: List of tool execution results
            dialog_summary: Optional dialog memory summary
            candidate_text: The finalizer output to validate
        
        Returns:
            GuardResult indicating pass/fail and any violations
        """
        if not candidate_text or not candidate_text.strip():
            return GuardResult(passed=True)
        
        # Build source texts list
        source_texts: List[str] = [user_input]
        
        if dialog_summary:
            source_texts.append(dialog_summary)
        
        if planner_decision:
            source_texts.append(json.dumps(planner_decision, ensure_ascii=False))
        
        if tool_results:
            source_texts.append(json.dumps(tool_results, ensure_ascii=False))
        
        # Run diff guard check
        result = self.diff_guard.check(
            source_texts=source_texts,
            candidate_text=candidate_text,
            check_currencies=self.check_currencies,
            check_percentages=self.check_percentages,
        )
        
        # Apply max_violations threshold
        if self.max_violations > 0 and len(result.violations) <= self.max_violations:
            result = GuardResult(
                passed=True,
                violations=result.violations,
                allowed_numbers=result.allowed_numbers,
                allowed_times=result.allowed_times,
                allowed_dates=result.allowed_dates,
                candidate_numbers=result.candidate_numbers,
                candidate_times=result.candidate_times,
                candidate_dates=result.candidate_dates,
            )
        
        return result
    
    def build_retry_prompt(
        self,
        original_prompt: str,
        result: GuardResult,
    ) -> str:
        """Build a retry prompt with stricter constraints.
        
        Args:
            original_prompt: The original finalizer prompt
            result: The failed GuardResult with violations
        
        Returns:
            Modified prompt with explicit constraints
        """
        constraints = [
            "\n\nSTRICT_NO_NEW_FACTS: Önemli kurallar:",
            "- Sadece verilen metinlerde geçen sayı/saat/tarihleri kullan.",
            "- Yeni rakam, saat veya tarih EKLEME.",
            "- Eğer kesin bilgi yoksa, belirsiz ifade kullan.",
        ]
        
        if result.allowed_numbers:
            nums = sorted(result.allowed_numbers)[:10]  # Limit display
            constraints.append(f"- İzin verilen sayılar: {', '.join(nums)}")
        
        if result.allowed_times:
            times = sorted(result.allowed_times)[:5]
            constraints.append(f"- İzin verilen saatler: {', '.join(times)}")
        
        if result.allowed_dates:
            dates = sorted(result.allowed_dates)[:5]
            constraints.append(f"- İzin verilen tarihler: {', '.join(dates)}")
        
        if result.violations:
            bad = [v.value for v in result.violations[:5]]
            constraints.append(f"- YASAK: Şu değerleri KULLANMA: {', '.join(bad)}")
        
        return original_prompt + "\n".join(constraints)


def post_check_diff(
    source_texts: List[str],
    original_output: str,
    candidate_text: str,
) -> Tuple[bool, List[str]]:
    """Post-check to ensure finalizer didn't alter critical facts from router output.
    
    This is a secondary check after the main guard, ensuring that if the router
    already produced good output, the finalizer didn't change the facts.
    
    Args:
        source_texts: Original source texts
        original_output: The router's original output (assistant_reply)
        candidate_text: The finalizer's output
    
    Returns:
        (passed, altered_values): True if no alterations, list of altered values if any
    """
    # Extract facts from original router output
    orig_numbers = extract_numbers(original_output) | extract_turkish_numbers(original_output)
    orig_times = extract_times(original_output)
    orig_dates = extract_dates(original_output)
    
    # If router had specific facts, ensure they're preserved
    altered: List[str] = []
    
    if orig_numbers:
        cand_numbers = extract_numbers(candidate_text) | extract_turkish_numbers(candidate_text)
        missing = orig_numbers - cand_numbers
        for m in missing:
            # Check if it was a critical number (not in source, added by router from tools)
            source_nums: Set[str] = set()
            for src in source_texts:
                source_nums |= extract_numbers(str(src or ""))
            if m not in source_nums:
                # Router added this from tool results, should be preserved
                altered.append(f"number:{m}")
    
    if orig_times:
        cand_times = extract_times(candidate_text)
        missing = orig_times - cand_times
        for m in missing:
            altered.append(f"time:{m}")
    
    if orig_dates:
        cand_dates = extract_dates(candidate_text)
        missing = orig_dates - cand_dates
        for m in missing:
            altered.append(f"date:{m}")
    
    return (len(altered) == 0, altered)


# Convenience function for backward compatibility
def find_new_numeric_facts(
    *,
    allowed_texts: List[str],
    candidate_text: str,
) -> Tuple[bool, Set[str]]:
    """Check for new numeric facts in candidate text.
    
    This is a convenience wrapper matching the old API.
    
    Args:
        allowed_texts: List of source texts containing allowed facts
        candidate_text: Text to check for new facts
    
    Returns:
        (violates, new_tokens): True if violations found, set of new values
    """
    guard = FinalizerGuard(strict_mode=True)
    
    # Build a minimal validation
    result = guard.diff_guard.check(
        source_texts=allowed_texts,
        candidate_text=candidate_text,
    )
    
    new_tokens: Set[str] = set()
    for v in result.violations:
        new_tokens.add(v.value)
    
    return (not result.passed, new_tokens)
