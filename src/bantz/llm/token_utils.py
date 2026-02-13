"""Unified token estimation utilities (Issue #406).

Previously the codebase had **8 independent copies** of token estimation
with two inconsistent heuristics:

- ``len(text) // 4`` (char-based, 4 chars ≈ 1 token)
- ``len(text.split())`` (word-count, 1 word ≈ 1 token)

This module provides a single ``estimate_tokens()`` function that every
module should use, plus a ``trim_to_tokens()`` helper.

Default method is ``chars4`` (~4 chars per token) which is a reasonable
approximation for Qwen/GPT-style tokenizers on Turkish+English text.
The method can be overridden via ``BANTZ_TOKEN_METHOD`` env var.

Supported methods
-----------------
- ``chars4`` — ``len(text) // 4``  (default, fast, good for mixed content)
- ``chars3`` — ``len(text) // 3``  (conservative, overestimates slightly)
- ``words``  — ``len(text.split())``  (word-count, for very rough estimates)
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

TokenMethod = Literal["chars4", "chars3", "words"]

_DEFAULT_METHOD: TokenMethod = "chars4"


def _get_method() -> TokenMethod:
    """Read method from env, cached on first call."""
    raw = os.getenv("BANTZ_TOKEN_METHOD", "").strip().lower()
    if raw in {"chars4", "chars3", "words"}:
        return raw  # type: ignore[return-value]
    return _DEFAULT_METHOD


def estimate_tokens(text: str | None, *, method: TokenMethod | None = None) -> int:
    """Estimate the number of tokens in *text*.

    Args:
        text: The text to estimate. ``None`` / empty → 0.
        method: Override the estimation method. If ``None``, uses
                ``BANTZ_TOKEN_METHOD`` env var or the default ``chars4``.

    Returns:
        Non-negative estimated token count.
    """
    t = str(text or "")
    if not t:
        return 0

    m = method or _get_method()

    if m == "chars4":
        return max(0, len(t) // 4)
    elif m == "chars3":
        return max(0, len(t) // 3)
    elif m == "words":
        return max(0, len(t.split()))
    else:
        return max(0, len(t) // 4)


def estimate_tokens_json(obj: Any, *, method: TokenMethod | None = None) -> int:
    """Estimate tokens for a JSON-serializable object.

    Serializes *obj* to a compact JSON string and then estimates tokens.
    On serialization failure, falls back to ``str(obj)``.
    """
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(obj)
    return estimate_tokens(text, method=method)


def trim_to_tokens(text: str | None, max_tokens: int, *, method: TokenMethod | None = None) -> str:
    """Trim *text* so that its estimated token count ≤ *max_tokens*.

    Uses a character-level cut (since the estimation is char-based) and
    appends an ellipsis if trimming occurred.
    """
    t = str(text or "")
    if max_tokens <= 0:
        return ""
    if estimate_tokens(t, method=method) <= max_tokens:
        return t

    m = method or _get_method()

    if m == "words":
        words = t.split()
        return " ".join(words[:max_tokens])

    # chars4 / chars3
    chars_per_token = 4 if m != "chars3" else 3
    max_chars = max_tokens * chars_per_token
    if max_chars <= 1:
        return "…"[:max_chars]
    return t[: max(0, max_chars - 1)] + "…"
