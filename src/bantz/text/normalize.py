"""Text normalization for user-facing calendar and assistant messages.

Issue #241: UX improvement for Turkish titles, quotes, and punctuation.

This module provides normalization utilities for:
- Trimming whitespace
- Collapsing multiple whitespace to single space
- Quote normalization (double to single, curly to straight)
- Trailing punctuation fixes
- Turkish-specific text handling

Apply to:
- Confirmation prompts
- Result SAY messages
- Tool episodic logs (PII safe)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class NormalizeLevel(Enum):
    """Normalization strictness levels."""
    MINIMAL = "minimal"  # Just trim and collapse whitespace
    STANDARD = "standard"  # Trim, collapse, quote fix
    STRICT = "strict"  # All normalizations including Turkish-specific


@dataclass(frozen=True)
class NormalizeResult:
    """Result of text normalization."""
    original: str
    normalized: str
    changes_made: list[str]
    
    @property
    def was_changed(self) -> bool:
        """Check if any changes were made."""
        return self.original != self.normalized
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "original": self.original,
            "normalized": self.normalized,
            "changes_made": self.changes_made,
            "was_changed": self.was_changed,
        }


# Quote characters to normalize
QUOTE_CHARS = {
    '\u201c': '"',  # left double quote "
    '\u201d': '"',  # right double quote "
    '\u201e': '"',  # low double quote „
    '\u201f': '"',  # double high-reversed-9 quote ‟
    '\u00ab': '"',  # left-pointing double angle quote «
    '\u00bb': '"',  # right-pointing double angle quote »
    '\u2018': "'",  # left single quote '
    '\u2019': "'",  # right single quote '
    '\u201a': "'",  # single low-9 quote ‚
    '\u201b': "'",  # single high-reversed-9 quote ‛
    '`': "'",       # backtick to single quote
}

# Double quote patterns to single
DOUBLE_QUOTE_PATTERN = re.compile(r'"{2,}')

# Multiple whitespace pattern
MULTI_WHITESPACE_PATTERN = re.compile(r'\s{2,}')

# Trailing punctuation patterns
MULTI_DOT_PATTERN = re.compile(r'\.{2,}$')  # .. or more at end
MULTI_DOT_ANYWHERE = re.compile(r'\.{4,}')  # .... or more anywhere (keep ... ellipsis)

# Leading/trailing punctuation issues
# Only remove leading simple punctuation, not ellipsis
LEADING_PUNCT_PATTERN = re.compile(r'^[,;:!?]+\s*')

# Mixed quote pattern (opening without closing or vice versa)
UNBALANCED_QUOTE_PATTERN = re.compile(r'^["\']|["\']$')


def _trim(text: str) -> tuple[str, bool]:
    """Trim leading and trailing whitespace."""
    result = text.strip()
    return result, result != text


def _collapse_whitespace(text: str) -> tuple[str, bool]:
    """Collapse multiple whitespace to single space."""
    result = MULTI_WHITESPACE_PATTERN.sub(' ', text)
    return result, result != text


def _normalize_quotes(text: str) -> tuple[str, list[str]]:
    """Normalize various quote characters to standard straight quotes."""
    result = text
    changes = []
    
    # Replace curly/fancy quotes with straight quotes
    for fancy, straight in QUOTE_CHARS.items():
        if fancy in result:
            result = result.replace(fancy, straight)
            changes.append(f"quote_{fancy}_to_{straight}")
    
    # Collapse double quotes to single
    if DOUBLE_QUOTE_PATTERN.search(result):
        result = DOUBLE_QUOTE_PATTERN.sub('"', result)
        changes.append("collapse_double_quotes")
    
    return result, changes


def _fix_trailing_punctuation(text: str) -> tuple[str, list[str]]:
    """Fix trailing punctuation issues."""
    result = text
    changes = []
    
    # Fix multiple dots at end (but keep ellipsis ... as is)
    if MULTI_DOT_PATTERN.search(result):
        # If 2 dots, remove to single. If 3+, keep as ellipsis or reduce to 3.
        match = MULTI_DOT_PATTERN.search(result)
        if match:
            dot_count = len(match.group())
            if dot_count == 2:
                result = result[:-1]  # Remove one dot
                changes.append("fix_double_dot")
            elif dot_count > 3:
                result = result[:-(dot_count - 3)]  # Reduce to 3 dots
                changes.append("reduce_ellipsis")
    
    # Fix very long dot sequences anywhere
    if MULTI_DOT_ANYWHERE.search(result):
        result = MULTI_DOT_ANYWHERE.sub('...', result)
        changes.append("normalize_long_ellipsis")
    
    # Remove leading punctuation
    if LEADING_PUNCT_PATTERN.match(result):
        result = LEADING_PUNCT_PATTERN.sub('', result)
        changes.append("remove_leading_punct")
    
    # Fix trailing comma or semicolon (common typos)
    if result.endswith(',') or result.endswith(';'):
        result = result[:-1] + '.'
        changes.append("fix_trailing_comma_semicolon")
    
    return result, changes


def _fix_turkish_specifics(text: str) -> tuple[str, list[str]]:
    """Apply Turkish-specific text normalizations."""
    result = text
    changes = []
    
    # Turkish uses different quote conventions sometimes
    # In Turkish, tırnak işareti is preferred as « » or " " 
    # We normalize all to straight quotes for consistency
    
    # Fix common Turkish typos in calendar context
    # "de/da" after time expressions
    common_fixes = {
        'saat da': 'saatte',
        'saat de': 'saatte',
        ' da ': ' de ',  # Context-sensitive, simplified rule
    }
    
    for typo, fix in common_fixes.items():
        if typo in result.lower():
            # Preserve case of first character
            idx = result.lower().find(typo)
            if idx != -1:
                result = result[:idx] + fix + result[idx + len(typo):]
                changes.append(f"turkish_fix_{typo.strip()}")
    
    # Normalize Unicode characters
    # Turkish İ/ı should be preserved, but we normalize other chars
    result_normalized = unicodedata.normalize('NFC', result)
    if result_normalized != result:
        result = result_normalized
        changes.append("unicode_nfc")
    
    return result, changes


def _remove_redundant_spaces_around_quotes(text: str) -> tuple[str, bool]:
    """Remove redundant spaces inside quotes (after opening, before closing).
    
    Note: This only removes spaces immediately inside quotes, not after closing quotes.
    """
    result = text
    
    # Remove space right after opening quote (e.g., '" hello' -> '"hello')
    # Match quote at start of string or after whitespace, followed by space
    result = re.sub(r'(^["\'])\s+', r'\1', result)  # At start of string
    result = re.sub(r'(\s["\'])\s+', r'\1', result)  # After whitespace
    
    # Remove space right before closing quote (e.g., 'hello "' -> 'hello"')
    # Match space followed by quote at end of string or before whitespace
    result = re.sub(r'\s+(["\']$)', r'\1', result)  # At end of string
    result = re.sub(r'\s+(["\'])\s', r'\1 ', result)  # Before whitespace (keep one space after)
    
    return result, result != text


def _capitalize_first(text: str) -> tuple[str, bool]:
    """Ensure first character is capitalized (Turkish-aware)."""
    if not text:
        return text, False
    
    # Skip if starts with quote, handle content inside
    if text[0] in '"\'':
        if len(text) > 1:
            # Capitalize the character after the quote
            inner = text[1].upper() if text[1].isalpha() else text[1]
            result = text[0] + inner + text[2:]
            return result, result != text
        return text, False
    
    # Turkish İ handling - Python's upper() handles this correctly
    result = text[0].upper() + text[1:] if text[0].isalpha() else text
    return result, result != text


def normalize_text(
    text: str,
    *,
    level: NormalizeLevel = NormalizeLevel.STANDARD,
    capitalize_first: bool = False,
    preserve_ellipsis: bool = True,
) -> NormalizeResult:
    """Normalize text for user-facing display.
    
    Args:
        text: Input text to normalize.
        level: Normalization strictness level.
        capitalize_first: Whether to capitalize first character.
        preserve_ellipsis: Whether to preserve ... ellipsis.
    
    Returns:
        NormalizeResult with original, normalized text, and changes.
    """
    if not text:
        return NormalizeResult(original="", normalized="", changes_made=[])
    
    original = text
    result = text
    all_changes: list[str] = []
    
    # Always: trim and collapse whitespace
    result, changed = _trim(result)
    if changed:
        all_changes.append("trim")
    
    result, changed = _collapse_whitespace(result)
    if changed:
        all_changes.append("collapse_whitespace")
    
    if level in (NormalizeLevel.STANDARD, NormalizeLevel.STRICT):
        # Quote normalization
        result, quote_changes = _normalize_quotes(result)
        all_changes.extend(quote_changes)
        
        # Fix spacing around quotes
        result, changed = _remove_redundant_spaces_around_quotes(result)
        if changed:
            all_changes.append("fix_quote_spacing")
        
        # Punctuation fixes
        result, punct_changes = _fix_trailing_punctuation(result)
        all_changes.extend(punct_changes)
    
    if level == NormalizeLevel.STRICT:
        # Turkish-specific fixes
        result, turkish_changes = _fix_turkish_specifics(result)
        all_changes.extend(turkish_changes)
    
    # Optional: capitalize first character
    if capitalize_first:
        result, changed = _capitalize_first(result)
        if changed:
            all_changes.append("capitalize_first")
    
    return NormalizeResult(
        original=original,
        normalized=result,
        changes_made=all_changes,
    )


def normalize_calendar_title(title: str) -> str:
    """Normalize a calendar event title.
    
    Applies standard normalization + capitalizes first char.
    
    Args:
        title: Event title to normalize.
    
    Returns:
        Normalized title string.
    """
    result = normalize_text(title, level=NormalizeLevel.STANDARD, capitalize_first=True)
    return result.normalized


def normalize_calendar_message(message: str) -> str:
    """Normalize a calendar-related message (SAY, confirmation).
    
    Applies standard normalization.
    
    Args:
        message: Message to normalize.
    
    Returns:
        Normalized message string.
    """
    result = normalize_text(message, level=NormalizeLevel.STANDARD)
    return result.normalized


def normalize_log_entry(entry: str) -> str:
    """Normalize an episodic log entry (PII-safe context).
    
    Applies minimal normalization to preserve original intent while
    cleaning up whitespace.
    
    Args:
        entry: Log entry to normalize.
    
    Returns:
        Normalized log entry string.
    """
    result = normalize_text(entry, level=NormalizeLevel.MINIMAL)
    return result.normalized


# Convenience function for quick normalization
def quick_normalize(text: str) -> str:
    """Quick normalize with standard settings.
    
    Args:
        text: Text to normalize.
    
    Returns:
        Normalized text.
    """
    return normalize_text(text, level=NormalizeLevel.STANDARD).normalized


# Batch normalization
def normalize_batch(
    texts: list[str],
    *,
    level: NormalizeLevel = NormalizeLevel.STANDARD,
) -> list[NormalizeResult]:
    """Normalize a batch of texts.
    
    Args:
        texts: List of texts to normalize.
        level: Normalization level to apply.
    
    Returns:
        List of NormalizeResult objects.
    """
    return [normalize_text(t, level=level) for t in texts]


# Stats helper
def get_normalization_stats(results: list[NormalizeResult]) -> dict:
    """Get statistics about normalization results.
    
    Args:
        results: List of NormalizeResult objects.
    
    Returns:
        Dictionary with stats.
    """
    total = len(results)
    changed = sum(1 for r in results if r.was_changed)
    
    change_counts: dict[str, int] = {}
    for r in results:
        for change in r.changes_made:
            change_counts[change] = change_counts.get(change, 0) + 1
    
    return {
        "total": total,
        "changed": changed,
        "unchanged": total - changed,
        "change_rate": changed / total if total > 0 else 0.0,
        "change_counts": change_counts,
    }
