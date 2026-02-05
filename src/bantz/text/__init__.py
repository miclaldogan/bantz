"""Text normalization package for Bantz.

Issue #241: UX improvement for Turkish titles, quotes, and punctuation.
"""

from bantz.text.normalize import (
    NormalizeLevel,
    NormalizeResult,
    normalize_text,
    normalize_calendar_title,
    normalize_calendar_message,
    normalize_log_entry,
    quick_normalize,
    normalize_batch,
    get_normalization_stats,
)

__all__ = [
    "NormalizeLevel",
    "NormalizeResult",
    "normalize_text",
    "normalize_calendar_title",
    "normalize_calendar_message",
    "normalize_log_entry",
    "quick_normalize",
    "normalize_batch",
    "get_normalization_stats",
]
