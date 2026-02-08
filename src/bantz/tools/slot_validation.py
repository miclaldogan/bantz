"""
Calendar Slot Validation — Issue #433.

Pre-validation for tool calls before execution:
- required_slots metadata per tool
- Validate slots BEFORE calling the tool
- On failure: skip tool, return clarification question in Turkish
- Prevents Google API errors from missing slots

Usage::

    from bantz.tools.slot_validation import (
        validate_tool_slots,
        SlotValidationResult,
        TOOL_REQUIRED_SLOTS,
    )
    result = validate_tool_slots("calendar.create_event", {"title": "Toplantı"})
    if not result.valid:
        # result.question → "Etkinlik saatini söyler misiniz efendim?"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Slot definitions
# ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SlotRequirement:
    """A required slot or group of alternative slots for a tool."""
    name: str
    alternatives: Tuple[str, ...] = ()  # Any one of these can satisfy
    question_tr: str = ""  # Turkish clarification question

    @property
    def all_names(self) -> Tuple[str, ...]:
        """All slot names that can satisfy this requirement."""
        return (self.name,) + self.alternatives


# ─────────────────────────────────────────────────────────────────
# Per-tool required slots
# ─────────────────────────────────────────────────────────────────

# calendar.create_event: title required, time OR window_hint OR date required
_CREATE_EVENT_SLOTS = [
    SlotRequirement(
        name="title",
        question_tr="Etkinlik adı ne olsun efendim?",
    ),
    SlotRequirement(
        name="time",
        alternatives=("date", "window_hint"),
        question_tr="Etkinlik ne zaman olsun efendim? Tarih veya saat belirtir misiniz?",
    ),
]

# calendar.update_event: at least an event identifier + something to update
_UPDATE_EVENT_SLOTS = [
    SlotRequirement(
        name="title",
        alternatives=("event_id", "query"),
        question_tr="Hangi etkinliği güncellemek istiyorsunuz efendim?",
    ),
]

# calendar.delete_event: need to know which event
_DELETE_EVENT_SLOTS = [
    SlotRequirement(
        name="title",
        alternatives=("event_id", "query"),
        question_tr="Hangi etkinliği silmek istiyorsunuz efendim?",
    ),
]

# gmail.send: need recipient + body
_GMAIL_SEND_SLOTS = [
    SlotRequirement(
        name="to",
        alternatives=("recipient",),
        question_tr="E-postayı kime göndermemi istiyorsunuz efendim?",
    ),
    SlotRequirement(
        name="body",
        alternatives=("message", "content"),
        question_tr="E-posta içeriği ne olsun efendim?",
    ),
]

# gmail.generate_reply: need message to reply to
_GMAIL_REPLY_SLOTS = [
    SlotRequirement(
        name="message_id",
        alternatives=("thread_id", "query"),
        question_tr="Hangi e-postaya yanıt vermemi istiyorsunuz efendim?",
    ),
]


# Master registry: tool_name → list of SlotRequirements
TOOL_REQUIRED_SLOTS: Dict[str, List[SlotRequirement]] = {
    "calendar.create_event": _CREATE_EVENT_SLOTS,
    "calendar.update_event": _UPDATE_EVENT_SLOTS,
    "calendar.delete_event": _DELETE_EVENT_SLOTS,
    "gmail.send": _GMAIL_SEND_SLOTS,
    "gmail.generate_reply": _GMAIL_REPLY_SLOTS,
}


# ─────────────────────────────────────────────────────────────────
# Validation Result
# ─────────────────────────────────────────────────────────────────


@dataclass
class SlotValidationResult:
    """Result of pre-validation for a tool call."""

    tool_name: str
    valid: bool
    missing_slots: List[str] = field(default_factory=list)
    question: Optional[str] = None  # Turkish clarification question
    ask_user: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "tool": self.tool_name,
            "valid": self.valid,
        }
        if self.missing_slots:
            d["missing_slots"] = self.missing_slots
        if self.question:
            d["question"] = self.question
        if self.ask_user:
            d["ask_user"] = True
        return d


# ─────────────────────────────────────────────────────────────────
# Validation logic
# ─────────────────────────────────────────────────────────────────


def _slot_present(slots: Dict[str, Any], name: str) -> bool:
    """Check if a slot is present and non-empty."""
    val = slots.get(name)
    if val is None:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    return True


def validate_tool_slots(
    tool_name: str,
    slots: Dict[str, Any],
    *,
    required_slots: Optional[List[SlotRequirement]] = None,
) -> SlotValidationResult:
    """
    Validate that all required slots are present before calling a tool.

    Args:
        tool_name: The tool to validate for.
        slots: The slots/parameters extracted by the router/LLM.
        required_slots: Override the default required slots (for testing).

    Returns:
        SlotValidationResult — if .valid is False, .question has the
        Turkish clarification to ask the user.
    """
    reqs = required_slots or TOOL_REQUIRED_SLOTS.get(tool_name)

    # No requirements defined → always valid
    if not reqs:
        return SlotValidationResult(tool_name=tool_name, valid=True)

    missing: List[str] = []
    first_question: Optional[str] = None

    for req in reqs:
        # Check if the primary slot or any alternative is present
        satisfied = any(_slot_present(slots, n) for n in req.all_names)
        if not satisfied:
            missing.append(req.name)
            if first_question is None and req.question_tr:
                first_question = req.question_tr

    if missing:
        logger.info(
            "[SLOT_VALIDATION] Tool '%s' missing slots: %s",
            tool_name,
            ", ".join(missing),
        )
        return SlotValidationResult(
            tool_name=tool_name,
            valid=False,
            missing_slots=missing,
            question=first_question,
            ask_user=True,
        )

    return SlotValidationResult(tool_name=tool_name, valid=True)


def get_clarification_question(tool_name: str, slots: Dict[str, Any]) -> Optional[str]:
    """
    Convenience: returns the Turkish clarification question if slots are
    incomplete, or None if everything is fine.
    """
    result = validate_tool_slots(tool_name, slots)
    return result.question if not result.valid else None


def get_required_slot_names(tool_name: str) -> List[str]:
    """Return the list of primary required slot names for a tool."""
    reqs = TOOL_REQUIRED_SLOTS.get(tool_name, [])
    return [r.name for r in reqs]
