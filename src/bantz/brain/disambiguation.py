"""Context-Aware Disambiguation Dialog (Issue #875).

When tool results return multiple items (calendar events, emails,
contacts, free slots, etc.), automatically builds a context-rich
question asking the user which item they meant.

Integrates with:
- ``anaphora.ReferenceTable`` for item extraction and ``#N`` resolution
- ``OrchestratorState.disambiguation_pending`` for state tracking
- ``OrchestratorOutput.ask_user`` / ``.question`` for the response path
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bantz.brain.anaphora import ReferenceItem, ReferenceTable, extract_references

logger = logging.getLogger(__name__)

# Minimum items required to trigger disambiguation
MIN_ITEMS_FOR_DISAMBIGUATION = 2

# Intents that operate on a single target (destructive / modify)
DISAMBIGUATION_INTENTS = frozenset({
    "calendar_delete_event",
    "calendar_update_event",
    "calendar_reschedule",
    "gmail_delete",
    "gmail_reply",
    "gmail_forward",
    "gmail_mark_read",
    "contacts_delete",
    "contacts_update",
    "file_delete",
    "file_open",
    "generic_select",
})

# Turkish emoji + type labels
TYPE_EMOJI: Dict[str, str] = {
    "event": "📅",
    "email": "📧",
    "contact": "👤",
    "slot": "🕐",
    "generic": "📋",
}

TYPE_LABEL: Dict[str, str] = {
    "event": "etkinlik",
    "email": "e-posta",
    "contact": "kişi",
    "slot": "boş zaman",
    "generic": "öğe",
}


@dataclass
class DisambiguationRequest:
    """Pending disambiguation request stored in OrchestratorState."""

    reference_table: ReferenceTable
    question_text: str
    original_intent: str
    source_tool: str
    item_count: int = 0


@dataclass
class DisambiguationResult:
    """Result of resolving a disambiguation response."""

    resolved: bool = False
    selected_item: Optional[ReferenceItem] = None
    selected_index: Optional[int] = None
    error: str = ""


class DisambiguationDialog:
    """Builds and resolves context-aware disambiguation dialogs.

    Usage::

        dialog = DisambiguationDialog()

        # After tool execution, check if disambiguation is needed
        request = dialog.check_tool_results(tool_results, intent="calendar_delete_event")

        if request:
            # Store in state, return ask_user=True + question
            state.disambiguation_pending = request
            output.ask_user = True
            output.question = request.question_text
            return

        # On next turn, resolve user's answer
        result = dialog.resolve_response(user_input, state.disambiguation_pending)
        if result.resolved:
            selected = result.selected_item
            # Re-execute tool with specific item
    """

    def __init__(self, min_items: int = MIN_ITEMS_FOR_DISAMBIGUATION):
        self._min_items = min_items

    def check_tool_results(
        self,
        tool_results: List[Dict[str, Any]],
        intent: str = "",
        *,
        max_items: int = 10,
    ) -> Optional[DisambiguationRequest]:
        """Check if tool results need disambiguation.

        Returns a ``DisambiguationRequest`` if:
        1. There are ≥ ``min_items`` reference-able items
        2. The intent is one that operates on a single target

        Args:
            tool_results: List of tool result dicts from execution phase.
            intent: The detected intent (e.g. ``calendar_delete_event``).
            max_items: Maximum items to extract for the reference table.

        Returns:
            DisambiguationRequest if disambiguation is needed, else None.
        """
        if not tool_results:
            return None

        # Issue #1008: Empty/unknown intent should NOT trigger disambiguation.
        # An undetected intent needs re-route or clarification, not item selection.
        if not intent:
            return None

        # Only trigger for intents that target a single item
        if intent not in DISAMBIGUATION_INTENTS:
            return None

        try:
            ref_table = extract_references(tool_results, max_items=max_items)
        except (TypeError, AttributeError, KeyError) as exc:
            logger.warning("[DISAMBIGUATION] extract_references failed: %s", exc)
            return None

        if len(ref_table) < self._min_items:
            return None

        question = self._build_question(ref_table, intent)

        return DisambiguationRequest(
            reference_table=ref_table,
            question_text=question,
            original_intent=intent,
            source_tool=ref_table.source_tool,
            item_count=len(ref_table),
        )

    def resolve_response(
        self,
        user_input: str,
        pending: Optional[DisambiguationRequest],
    ) -> DisambiguationResult:
        """Resolve the user's response to a disambiguation question.

        Uses ``ReferenceTable.resolve_reference()`` which handles:
        - ``#1``, ``#2`` style references
        - Turkish anaphora: ``ilkini``, ``ikincisini``, ``sonuncusu``
        - Bare digits: ``1``, ``2``

        Args:
            user_input: The user's response text.
            pending: The pending disambiguation request from state.

        Returns:
            DisambiguationResult with resolved item or error.
        """
        if not pending or not pending.reference_table:
            return DisambiguationResult(error="Bekleyen seçim isteği yok.")

        item = pending.reference_table.resolve_reference(user_input)

        if item is None:
            return DisambiguationResult(
                error=f"Anlayamadım. Lütfen 1-{pending.item_count} arası bir numara girin.",
            )

        return DisambiguationResult(
            resolved=True,
            selected_item=item,
            selected_index=item.index,
        )

    def _build_question(self, ref_table: ReferenceTable, intent: str) -> str:
        """Build a context-rich Turkish disambiguation question.

        Example output::

            Takvimde 3 etkinlik buldum:
              #1 📅 Pazartesi 14:00 — Proje görüşmesi
              #2 📅 Salı 10:00 — 1-1 toplantı
              #3 📅 Çarşamba 09:00 — Sprint planning
            Hangisini silmemi istersin?
        """
        items = ref_table.items
        if not items:
            return "Seçenek bulunamadı."

        # Detect item type from first item
        item_type = items[0].item_type
        emoji = TYPE_EMOJI.get(item_type, "📋")
        type_label = TYPE_LABEL.get(item_type, "öğe")
        count = len(items)

        # Header
        source_label = self._source_label(ref_table.source_tool)
        header = f"{source_label}{count} {type_label} buldum:"

        # Item lines
        lines = [header]
        for item in items:
            lines.append(f"  #{item.index} {emoji} {item.label}")

        # Action prompt based on intent
        action = self._intent_action(intent)
        lines.append(f"Hangisini {action}?")

        return "\n".join(lines)

    @staticmethod
    def _source_label(source_tool: str) -> str:
        """Generate a Turkish source prefix."""
        mapping = {
            "calendar.list_events": "Takvimde ",
            "calendar.free_slots": "Takvimde ",
            "gmail.list_messages": "Gmail'de ",
            "gmail.smart_search": "Gmail'de ",
            "contacts.list": "Rehberde ",
        }
        return mapping.get(source_tool, "")

    @staticmethod
    def _intent_action(intent: str) -> str:
        """Map intent to Turkish action verb."""
        mapping = {
            "calendar_delete_event": "silmemi istersin",
            "calendar_update_event": "güncellememi istersin",
            "calendar_reschedule": "ertelememi istersin",
            "gmail_delete": "silmemi istersin",
            "gmail_reply": "yanıtlamamı istersin",
            "gmail_forward": "iletmemi istersin",
            "gmail_mark_read": "okundu işaretlememi istersin",
            "contacts_delete": "silmemi istersin",
            "contacts_update": "güncellememi istersin",
            "file_delete": "silmemi istersin",
            "file_open": "açmamı istersin",
        }
        return mapping.get(intent, "seçmemi istersin")


def create_disambiguation_dialog(
    min_items: int = MIN_ITEMS_FOR_DISAMBIGUATION,
) -> DisambiguationDialog:
    """Factory for creating a DisambiguationDialog."""
    return DisambiguationDialog(min_items=min_items)
