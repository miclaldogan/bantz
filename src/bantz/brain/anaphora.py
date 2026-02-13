"""Anaphora resolution: Extract and inject referenceable items (Issue #416).

Solves multi-turn reference problems like:
  1. User: "Bugün ne var?" → calendar.list_events → [Meeting 14:00, Lunch 12:00]
  2. User: "İlkini sil" → needs to resolve "İlkini" → Meeting 14:00

Strategy:
  - After tool execution, extract referenceable items (events, emails, contacts)
  - Build a compact REFERENCE_TABLE for the next LLM prompt
  - 3B router can then resolve "#1", "ilkini", "sonuncusu" via the table
  - Token-budget-friendly: ≤200 tokens for the reference table

Usage:
    >>> table = ReferenceTable.from_tool_results(tool_results)
    >>> prompt_block = table.to_prompt_block()
    >>> # Inject into LLM context
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ReferenceItem",
    "ReferenceTable",
    "extract_references",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ReferenceItem:
    """A single referenceable item extracted from tool results.

    Attributes:
        index: 1-based index (displayed as #1, #2, ...)
        item_type: "event" | "email" | "contact" | "file" | "generic"
        label: Short display label (e.g. "Toplantı 14:00")
        details: Optional extra detail dict (e.g. event_id, email_id)
    """

    index: int
    item_type: str
    label: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_short(self) -> str:
        """Compact one-liner for reference table."""
        return f"#{self.index}: {self.label}"


@dataclass
class ReferenceTable:
    """Table of referenceable items from last tool execution.

    Injected into the LLM prompt so that the 3B router can resolve
    anaphoric references like 'ilkini', 'sonuncusu', '#2'.
    """

    items: list[ReferenceItem] = field(default_factory=list)
    source_tool: str = ""
    max_items: int = 10

    @classmethod
    def from_tool_results(
        cls,
        tool_results: list[dict[str, Any]],
        *,
        max_items: int = 10,
    ) -> "ReferenceTable":
        """Extract referenceable items from tool execution results.

        Scans tool results for lists of events, emails, contacts, etc.
        Returns a ReferenceTable with indexed items.
        """
        table = cls(max_items=max_items)

        for tr in tool_results:
            tool_name = str(tr.get("tool", tr.get("tool_name", "")))
            result = tr.get("result", tr.get("result_summary", None))
            success = tr.get("success", tr.get("status", "ok"))

            if not result or success in (False, "fail", "error"):
                continue

            items = _extract_items(tool_name, result)
            if items:
                table.source_tool = tool_name
                for i, item in enumerate(items[:max_items], start=1):
                    item.index = i
                    table.items.append(item)
                break  # Use first tool with items

        if table.items:
            logger.info(
                "[ANAPHORA] Extracted %d items from %s",
                len(table.items), table.source_tool,
            )
        return table

    def to_prompt_block(self) -> str:
        """Generate REFERENCE_TABLE block for LLM prompt injection.

        Returns:
            Compact reference table string, or empty string if no items.

        Example:
            REFERENCE_TABLE (from calendar.list_events):
              #1: Toplantı — 14:00
              #2: Öğle yemeği — 12:00
              #3: Doktor — 16:00
            Kullanıcı '#1', 'ilkini', 'sonuncusu' gibi referanslar kullanabilir.
        """
        if not self.items:
            return ""

        lines = [f"REFERENCE_TABLE (from {self.source_tool}):"]
        for item in self.items:
            lines.append(f"  {item.to_short()}")
        lines.append(
            "Kullanıcı '#1', 'ilkini', 'ikincisini', 'sonuncusu' "
            "gibi referanslar kullanabilir."
        )
        return "\n".join(lines)

    def resolve_reference(self, text: str) -> Optional[ReferenceItem]:
        """Try to resolve a Turkish anaphoric reference to an item.

        Supports:
          - Numeric: "#1", "#2", "1.", "1'inci"
          - Ordinal Turkish: "ilkini", "birincisini", "ikincisini", ...
          - Positional: "sonuncusu", "son", "ilk"

        Returns:
            Matching ReferenceItem, or None.
        """
        if not self.items:
            return None

        # Turkish-aware lowering: İ→i, I→ı handled manually
        text_lower = _turkish_lower(text.strip())

        # Direct index: "#1", "#2"
        m = re.search(r"#(\d+)", text)
        if m:
            idx = int(m.group(1))
            return self._get_by_index(idx)

        # Positional "son/sonuncu" FIRST (before ordinal map to avoid
        # "onuncu" in "sonuncusu" false positive)
        if "sonuncu" in text_lower or re.search(r"\bson\b", text_lower):
            return self.items[-1] if self.items else None

        # Turkish ordinals
        ordinal_map = {
            "ilk": 1, "birinci": 1, "ilkini": 1, "birincisini": 1,
            "ikinci": 2, "ikincisini": 2, "ikincisi": 2,
            "üçüncü": 3, "üçüncüsünü": 3, "üçüncüsü": 3,
            "dördüncü": 4, "dördüncüsünü": 4,
            "beşinci": 5, "beşincisini": 5,
            "altıncı": 6, "yedinci": 7, "sekizinci": 8,
            "dokuzuncu": 9, "onuncu": 10,
        }

        for word, idx in ordinal_map.items():
            if word in text_lower:
                return self._get_by_index(idx)

        # Digit: "1", "2" at word boundary
        m = re.search(r"\b(\d{1,2})\b", text)
        if m:
            idx = int(m.group(1))
            return self._get_by_index(idx)

        return None

    def _get_by_index(self, idx: int) -> Optional[ReferenceItem]:
        """Get item by 1-based index."""
        if 1 <= idx <= len(self.items):
            return self.items[idx - 1]
        return None

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)


# ---------------------------------------------------------------------------
# Item extractors per tool type
# ---------------------------------------------------------------------------


def _extract_items(tool_name: str, result: Any) -> list[ReferenceItem]:
    """Dispatch to the right extractor based on tool name."""
    tool_lower = tool_name.lower()

    if "calendar" in tool_lower and "list" in tool_lower:
        return _extract_calendar_events(result)
    if "calendar" in tool_lower and "free" in tool_lower:
        return _extract_free_slots(result)
    if "gmail" in tool_lower and ("list" in tool_lower or "search" in tool_lower):
        return _extract_emails(result)
    if "contacts" in tool_lower and "list" in tool_lower:
        return _extract_contacts(result)

    # Generic list fallback
    if isinstance(result, list):
        return _extract_generic_list(result)

    return []


def _extract_calendar_events(result: Any) -> list[ReferenceItem]:
    """Extract events from calendar.list_events result."""
    events = []
    items_list = None

    if isinstance(result, dict):
        items_list = result.get("events", result.get("items", []))
    elif isinstance(result, list):
        items_list = result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
            return _extract_calendar_events(parsed)
        except (json.JSONDecodeError, TypeError):
            return []

    if not items_list or not isinstance(items_list, list):
        return []

    for i, event in enumerate(items_list):
        if not isinstance(event, dict):
            continue
        title = event.get("summary", event.get("title", "Etkinlik"))
        start = event.get("start", {})
        if isinstance(start, dict):
            time_str = start.get("dateTime", start.get("date", ""))
        elif isinstance(start, str):
            time_str = start
        else:
            time_str = ""

        # Parse time for display
        display_time = _format_time(time_str)
        label = f"{title} — {display_time}" if display_time else title

        events.append(ReferenceItem(
            index=i + 1,
            item_type="event",
            label=label,
            details={
                "event_id": event.get("id", ""),
                "title": title,
                "start": time_str,
            },
        ))
    return events


def _extract_free_slots(result: Any) -> list[ReferenceItem]:
    """Extract free time slots."""
    slots_list = []
    if isinstance(result, dict):
        slots_list = result.get("slots", result.get("free_slots", []))
    elif isinstance(result, list):
        slots_list = result

    items = []
    for i, slot in enumerate(slots_list):
        if isinstance(slot, dict):
            start = slot.get("start", "")
            end = slot.get("end", "")
            label = f"{_format_time(start)} - {_format_time(end)}"
        elif isinstance(slot, str):
            label = slot
        else:
            continue
        items.append(ReferenceItem(
            index=i + 1, item_type="slot", label=label,
        ))
    return items


def _extract_emails(result: Any) -> list[ReferenceItem]:
    """Extract email items from gmail.list_messages result."""
    emails = []
    items_list = None

    if isinstance(result, dict):
        items_list = result.get("messages", result.get("emails", result.get("items", [])))
    elif isinstance(result, list):
        items_list = result

    if not items_list or not isinstance(items_list, list):
        return []

    for i, email in enumerate(items_list):
        if not isinstance(email, dict):
            continue
        subject = email.get("subject", email.get("snippet", ""))[:60]
        sender = email.get("from", email.get("sender", ""))
        if isinstance(sender, str) and len(sender) > 30:
            sender = sender[:30]
        label = f"{subject}"
        if sender:
            label = f"{sender}: {subject}"

        emails.append(ReferenceItem(
            index=i + 1,
            item_type="email",
            label=label,
            details={"message_id": email.get("id", ""), "subject": subject},
        ))
    return emails


def _extract_contacts(result: Any) -> list[ReferenceItem]:
    """Extract contacts from contacts.list result."""
    contacts = []
    items_list = result if isinstance(result, list) else []
    if isinstance(result, dict):
        items_list = result.get("contacts", result.get("items", []))

    for i, contact in enumerate(items_list):
        if isinstance(contact, dict):
            name = contact.get("name", contact.get("display_name", ""))
            label = name
        elif isinstance(contact, str):
            label = contact
        else:
            continue
        contacts.append(ReferenceItem(
            index=i + 1, item_type="contact", label=label,
            details={"name": label},
        ))
    return contacts


def _extract_generic_list(result: list) -> list[ReferenceItem]:
    """Fallback: extract items from any list."""
    items = []
    for i, item in enumerate(result):
        if isinstance(item, dict):
            label = item.get("name", item.get("title", item.get("summary", str(item)[:60])))
        elif isinstance(item, str):
            label = item[:60]
        else:
            label = str(item)[:60]
        items.append(ReferenceItem(
            index=i + 1, item_type="generic", label=label,
        ))
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_time(time_str: str) -> str:
    """Format ISO time string to HH:MM for display."""
    if not time_str:
        return ""
    try:
        if "T" in time_str:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        if len(time_str) == 10:  # "2025-01-15" (date only)
            return time_str
        return time_str[:16] if len(time_str) > 16 else time_str
    except (ValueError, TypeError):
        return time_str[:16]


def _turkish_lower(text: str) -> str:
    """Turkish-aware lowercase: İ→i, I→ı, Ş→ş, Ç→ç, Ğ→ğ, Ö→ö, Ü→ü.

    Python's str.lower() converts İ to 'i̇' (i + combining dot above)
    which breaks substring matching. This function handles it properly.
    """
    # Replace Turkish-specific uppercase chars first
    result = text.replace("İ", "i").replace("I", "ı")
    # Then standard lower for the rest
    return result.lower()


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def extract_references(
    tool_results: list[dict[str, Any]],
    *,
    max_items: int = 10,
) -> ReferenceTable:
    """Convenience: extract references from tool results."""
    return ReferenceTable.from_tool_results(tool_results, max_items=max_items)
