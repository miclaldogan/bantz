from __future__ import annotations

import re
from typing import Iterable, Tuple


_DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_SLASH_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_TIME_RE = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_LIST_MARKER_RE = re.compile(r"^\s*(\d{1,2})([\.)-])\s+")


def extract_numeric_facts(text: str) -> set[str]:
    """Extract a normalized set of number/date/time tokens from text.

    This is intentionally heuristic and conservative. It is meant for guardrails,
    not for strict parsing.
    """

    t = str(text or "")
    if not t.strip():
        return set()

    facts: set[str] = set()

    for m in _DATE_ISO_RE.finditer(t):
        facts.add(m.group(0))

    for m in _DATE_SLASH_RE.finditer(t):
        facts.add(m.group(0))

    for m in _TIME_RE.finditer(t):
        token = m.group(0).replace(".", ":")
        facts.add(token)

    # Remove date/time occurrences before extracting generic numbers.
    scrub = _DATE_ISO_RE.sub(" ", t)
    scrub = _DATE_SLASH_RE.sub(" ", scrub)
    scrub = _TIME_RE.sub(" ", scrub)

    for m in _NUMBER_RE.finditer(scrub):
        token = m.group(0)
        # Normalize decimal comma to dot for stable comparisons.
        token = token.replace(",", ".")
        facts.add(token)

    # Drop obvious list numbering markers like "1. " / "2) ".
    cleaned: set[str] = set()
    lines = t.splitlines() or [t]
    list_markers: set[str] = set()
    for ln in lines:
        mm = _LIST_MARKER_RE.match(ln)
        if mm:
            list_markers.add(str(int(mm.group(1))))

    for f in facts:
        if f in list_markers:
            continue
        cleaned.add(f)

    return cleaned


def find_new_numeric_facts(*, allowed_texts: Iterable[str], candidate_text: str) -> Tuple[bool, set[str]]:
    """Return (violates, new_tokens)."""

    allowed: set[str] = set()
    for a in allowed_texts:
        allowed |= extract_numeric_facts(str(a or ""))

    cand = extract_numeric_facts(candidate_text)
    new = {x for x in cand if x not in allowed}

    # Ignore harmless single-digit list-ish additions if they appear as standalone.
    # (A second protection beyond line-start detection.)
    new2: set[str] = set()
    for x in new:
        if len(x) == 1 and x.isdigit():
            continue
        new2.add(x)

    violates = bool(new2)
    return violates, new2
