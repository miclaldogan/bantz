from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional


@dataclass(frozen=True)
class QueryBuildResult:
    ok: bool
    query: str
    parts: list[str]
    error: str | None = None


_TOKEN_RE = re.compile(r"\b(from|to|subject|after|before|has|in):[^\s]+", re.IGNORECASE)


def _quote_if_needed(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return v
    if any(ch.isspace() for ch in v) or "\"" in v:
        v = v.replace('"', "\\\"")
        return f'"{v}"'
    return v


def _contains_any(text: str, needles: set[str]) -> bool:
    t = text.casefold()
    return any(n in t for n in needles)


def _parse_relative_dates(text: str, *, reference_date: date) -> list[str]:
    parts: list[str] = []

    # Required by acceptance criteria.
    if "geçen hafta" in text.casefold():
        parts.append(f"after:{(reference_date - timedelta(days=7)).isoformat()}")

    # Useful extras (safe, minimal).
    if "bugün" in text.casefold():
        parts.append(f"after:{reference_date.isoformat()}")

    if "dün" in text.casefold():
        parts.append(f"after:{(reference_date - timedelta(days=1)).isoformat()}")

    return parts


_FROM_RE = re.compile(r"(?P<who>[\w@.\-+ğüşöçıİĞÜŞÖÇ ]{2,}?)\s*'?den\b", re.IGNORECASE)
_TO_RE = re.compile(r"(?P<who>[\w@.\-+ğüşöçıİĞÜŞÖÇ ]{2,}?)\s*'?(ye|e)\s+giden\b", re.IGNORECASE)
_SUBJECT_RE = re.compile(r"\b(konu|subject|başlık)\s*[:=]\s*(?P<subj>.+)$", re.IGNORECASE)
_HAKKINDA_RE = re.compile(r"\b(?P<term>[\wğüşöçıİĞÜŞÖÇ]{2,})\s+hakkında\b", re.IGNORECASE)


def nl_to_gmail_query(
    text: str,
    *,
    reference_date: Optional[date] = None,
    inbox_only: bool = True,
) -> QueryBuildResult:
    """Convert Turkish-ish natural language text into a Gmail search query.

    This is intentionally heuristic and SAFE (no side effects).

    Supports:
    - `from:`, `to:`, `subject:`
    - `after:`, `before:` (relative phrases like "geçen hafta")
    - `has:attachment`
    - Multi-criteria composition

    If the input already contains explicit Gmail query tokens (e.g. `from:a@b`),
    they are preserved.
    """

    raw = str(text or "").strip()
    if not raw:
        return QueryBuildResult(ok=False, query="", parts=[], error="text must be non-empty")

    ref = reference_date or date.today()

    parts: list[str] = []

    # Preserve any explicit query tokens already present.
    explicit = _TOKEN_RE.findall(raw)
    if explicit:
        parts.extend([m.group(0) for m in _TOKEN_RE.finditer(raw)])

    # Attachment
    if _contains_any(raw, {"attachment", "ekli", "ek", "dosya", "attaş"}):
        if not any(p.lower().startswith("has:") for p in parts):
            parts.append("has:attachment")

    # Relative dates
    parts.extend(_parse_relative_dates(raw, reference_date=ref))

    # From
    m_from = _FROM_RE.search(raw)
    if m_from and not any(p.lower().startswith("from:") for p in parts):
        who = m_from.group("who").strip()
        parts.append(f"from:{_quote_if_needed(who)}")

    # To
    m_to = _TO_RE.search(raw)
    if m_to and not any(p.lower().startswith("to:") for p in parts):
        who = m_to.group("who").strip()
        parts.append(f"to:{_quote_if_needed(who)}")

    # Subject
    m_subj = _SUBJECT_RE.search(raw)
    if m_subj and not any(p.lower().startswith("subject:") for p in parts):
        subj = m_subj.group("subj").strip()
        if subj:
            parts.append(f"subject:{_quote_if_needed(subj)}")

    m_hakkinda = _HAKKINDA_RE.search(raw)
    if m_hakkinda and not any(p.lower().startswith("subject:") for p in parts):
        term = m_hakkinda.group("term").strip()
        if term:
            parts.append(f"subject:{_quote_if_needed(term)}")

    if inbox_only and not any(p.lower().startswith("in:") for p in parts):
        parts.insert(0, "in:inbox")

    # De-dup while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for p in parts:
        key = p.strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        uniq.append(key)

    query = " ".join(uniq).strip()
    return QueryBuildResult(ok=True, query=query, parts=uniq)


def gmail_query_from_nl(
    *,
    text: str,
    reference_date: Optional[str] = None,
    inbox_only: bool = True,
) -> dict[str, Any]:
    """Tool-friendly wrapper: returns `{ok, query, parts}`.

    `reference_date` is optional ISO date string for determinism in tests.
    """

    ref: Optional[date] = None
    if reference_date:
        ref = date.fromisoformat(str(reference_date))

    res = nl_to_gmail_query(text, reference_date=ref, inbox_only=inbox_only)
    if not res.ok:
        return {"ok": False, "error": res.error or "unknown", "query": "", "parts": []}
    return {"ok": True, "query": res.query, "parts": res.parts}
