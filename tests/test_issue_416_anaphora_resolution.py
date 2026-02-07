"""Tests for Issue #416: Anaphora resolution — multi-turn reference problem.

Verifies:
  - ReferenceTable.from_tool_results() extraction from calendar, email, contacts, etc.
  - ReferenceTable.to_prompt_block() format and token budget
  - ReferenceTable.resolve_reference() with Turkish ordinals, #N, positional
  - Edge cases: empty results, failures, malformed data
  - Integration: reference table stored on OrchestratorState
  - Integration: reference table injected into LLM context
"""

from __future__ import annotations

import json
import pytest

from bantz.brain.anaphora import (
    ReferenceItem,
    ReferenceTable,
    extract_references,
    _extract_calendar_events,
    _extract_emails,
    _extract_contacts,
    _extract_free_slots,
    _extract_generic_list,
    _format_time,
)
from bantz.brain.orchestrator_state import OrchestratorState


# ===================================================================
# Fixtures: Realistic tool results
# ===================================================================


@pytest.fixture
def calendar_events_result():
    """Realistic calendar.list_events result."""
    return {
        "tool": "calendar.list_events",
        "success": True,
        "result": {
            "events": [
                {
                    "id": "evt_001",
                    "summary": "Standup Toplantısı",
                    "start": {"dateTime": "2025-01-20T09:00:00+03:00"},
                    "end": {"dateTime": "2025-01-20T09:30:00+03:00"},
                },
                {
                    "id": "evt_002",
                    "summary": "Öğle Yemeği",
                    "start": {"dateTime": "2025-01-20T12:00:00+03:00"},
                    "end": {"dateTime": "2025-01-20T13:00:00+03:00"},
                },
                {
                    "id": "evt_003",
                    "summary": "Sprint Review",
                    "start": {"dateTime": "2025-01-20T14:00:00+03:00"},
                    "end": {"dateTime": "2025-01-20T15:00:00+03:00"},
                },
            ]
        },
    }


@pytest.fixture
def gmail_list_result():
    """Realistic gmail.list_messages result."""
    return {
        "tool": "gmail.list_messages",
        "success": True,
        "result": {
            "messages": [
                {
                    "id": "msg_001",
                    "from": "Ali Veli",
                    "subject": "Proje güncelleme",
                    "snippet": "Merhaba, proje hakkında...",
                },
                {
                    "id": "msg_002",
                    "from": "Ayşe Yılmaz",
                    "subject": "Toplantı notları",
                    "snippet": "Bugünkü toplantının...",
                },
                {
                    "id": "msg_003",
                    "from": "HR Departmanı",
                    "subject": "İzin onayı",
                    "snippet": "İzin talebiniz onaylandı",
                },
            ]
        },
    }


@pytest.fixture
def contacts_result():
    """Realistic contacts.list result."""
    return {
        "tool": "contacts.list_contacts",
        "success": True,
        "result": {
            "contacts": [
                {"name": "Mehmet Öz", "phone": "+905551234567"},
                {"name": "Zeynep Demir", "phone": "+905559876543"},
                {"name": "Ahmet Kaya", "email": "ahmet@example.com"},
            ]
        },
    }


@pytest.fixture
def free_slots_result():
    """Realistic calendar.get_free_slots result."""
    return {
        "tool": "calendar.get_free_slots",
        "success": True,
        "result": {
            "slots": [
                {"start": "2025-01-20T10:00:00+03:00", "end": "2025-01-20T11:00:00+03:00"},
                {"start": "2025-01-20T15:00:00+03:00", "end": "2025-01-20T17:00:00+03:00"},
            ]
        },
    }


# ===================================================================
# Tests: ReferenceItem
# ===================================================================


class TestReferenceItem:
    def test_to_short(self):
        item = ReferenceItem(index=1, item_type="event", label="Toplantı — 14:00")
        assert item.to_short() == "#1: Toplantı — 14:00"

    def test_to_short_with_index(self):
        item = ReferenceItem(index=5, item_type="email", label="Ali: Merhaba")
        assert item.to_short() == "#5: Ali: Merhaba"

    def test_details_default_empty(self):
        item = ReferenceItem(index=1, item_type="generic", label="test")
        assert item.details == {}

    def test_details_populated(self):
        item = ReferenceItem(
            index=1, item_type="event", label="Meeting",
            details={"event_id": "evt_001"},
        )
        assert item.details["event_id"] == "evt_001"


# ===================================================================
# Tests: ReferenceTable.from_tool_results
# ===================================================================


class TestFromToolResults:
    def test_calendar_events(self, calendar_events_result):
        table = ReferenceTable.from_tool_results([calendar_events_result])
        assert len(table) == 3
        assert table.source_tool == "calendar.list_events"
        assert table.items[0].item_type == "event"
        assert "Standup" in table.items[0].label
        assert "09:00" in table.items[0].label
        assert table.items[0].details["event_id"] == "evt_001"

    def test_gmail_messages(self, gmail_list_result):
        table = ReferenceTable.from_tool_results([gmail_list_result])
        assert len(table) == 3
        assert table.source_tool == "gmail.list_messages"
        assert table.items[0].item_type == "email"
        assert "Ali Veli" in table.items[0].label
        assert "Proje güncelleme" in table.items[0].label

    def test_contacts(self, contacts_result):
        table = ReferenceTable.from_tool_results([contacts_result])
        assert len(table) == 3
        assert table.source_tool == "contacts.list_contacts"
        assert table.items[0].item_type == "contact"
        assert "Mehmet Öz" in table.items[0].label

    def test_free_slots(self, free_slots_result):
        table = ReferenceTable.from_tool_results([free_slots_result])
        assert len(table) == 2
        assert table.source_tool == "calendar.get_free_slots"
        assert table.items[0].item_type == "slot"
        assert "10:00" in table.items[0].label

    def test_empty_tool_results(self):
        table = ReferenceTable.from_tool_results([])
        assert len(table) == 0
        assert not table
        assert table.to_prompt_block() == ""

    def test_failed_tool_result(self):
        """Failed tool results should be skipped."""
        results = [{"tool": "calendar.list_events", "success": False, "result": {"events": []}}]
        table = ReferenceTable.from_tool_results(results)
        assert len(table) == 0

    def test_none_result(self):
        """None result should be skipped."""
        results = [{"tool": "calendar.list_events", "success": True, "result": None}]
        table = ReferenceTable.from_tool_results(results)
        assert len(table) == 0

    def test_max_items_limit(self):
        """Should respect max_items."""
        events = [{"summary": f"Event {i}", "start": {"dateTime": f"2025-01-20T{i+8:02d}:00:00+03:00"}}
                  for i in range(20)]
        results = [{"tool": "calendar.list_events", "success": True, "result": {"events": events}}]
        table = ReferenceTable.from_tool_results(results, max_items=5)
        assert len(table) == 5
        assert table.items[-1].index == 5

    def test_first_matching_tool_wins(self, calendar_events_result, gmail_list_result):
        """Should use the first tool that has items."""
        table = ReferenceTable.from_tool_results([calendar_events_result, gmail_list_result])
        assert table.source_tool == "calendar.list_events"
        assert len(table) == 3

    def test_generic_list_fallback(self):
        """Unknown tool with list result should use generic extractor."""
        results = [{
            "tool": "some.unknown_tool",
            "success": True,
            "result": ["item A", "item B", "item C"],
        }]
        table = ReferenceTable.from_tool_results(results)
        assert len(table) == 3
        assert table.items[0].label == "item A"
        assert table.items[0].item_type == "generic"

    def test_error_status_string(self):
        """String 'error' status should be skipped."""
        results = [{"tool": "calendar.list_events", "status": "error", "result": {"events": []}}]
        table = ReferenceTable.from_tool_results(results)
        assert len(table) == 0

    def test_result_summary_fallback(self):
        """Should try result_summary if result is missing."""
        results = [{
            "tool": "calendar.list_events",
            "success": True,
            "result_summary": {
                "events": [{"summary": "Meeting", "start": {"dateTime": "2025-01-20T14:00:00+03:00"}}]
            },
        }]
        table = ReferenceTable.from_tool_results(results)
        assert len(table) == 1


# ===================================================================
# Tests: ReferenceTable.to_prompt_block
# ===================================================================


class TestToPromptBlock:
    def test_format(self, calendar_events_result):
        table = ReferenceTable.from_tool_results([calendar_events_result])
        block = table.to_prompt_block()

        assert "REFERENCE_TABLE" in block
        assert "calendar.list_events" in block
        assert "#1:" in block
        assert "#2:" in block
        assert "#3:" in block
        assert "Standup" in block
        assert "referanslar" in block  # Turkish help text

    def test_empty_block(self):
        table = ReferenceTable()
        assert table.to_prompt_block() == ""

    def test_token_budget(self, calendar_events_result):
        """Reference table should be under ~200 tokens (~800 chars)."""
        table = ReferenceTable.from_tool_results([calendar_events_result])
        block = table.to_prompt_block()
        # 200 tokens ≈ 800 chars (rough estimate)
        assert len(block) < 1000, f"Block too long: {len(block)} chars"

    def test_large_result_budget(self):
        """Even 10 events should stay within token budget."""
        events = [
            {"summary": f"Etkinlik {i}", "start": {"dateTime": f"2025-01-20T{i+8:02d}:00:00+03:00"}}
            for i in range(10)
        ]
        results = [{"tool": "calendar.list_events", "success": True, "result": {"events": events}}]
        table = ReferenceTable.from_tool_results(results)
        block = table.to_prompt_block()
        # 10 items + header + footer ≈ 12 lines × ~50 chars ≈ 600 chars
        assert len(block) < 1500, f"Block too long: {len(block)} chars"

    def test_block_lines(self, calendar_events_result):
        table = ReferenceTable.from_tool_results([calendar_events_result])
        block = table.to_prompt_block()
        lines = block.strip().split("\n")
        # Header + 3 items + footer = 5 lines
        assert len(lines) == 5


# ===================================================================
# Tests: ReferenceTable.resolve_reference — Turkish ordinals
# ===================================================================


class TestResolveReference:
    @pytest.fixture(autouse=True)
    def setup_table(self, calendar_events_result):
        self.table = ReferenceTable.from_tool_results([calendar_events_result])
        assert len(self.table) == 3

    # --- #N notation ---

    @pytest.mark.parametrize("text,expected_idx", [
        ("#1", 1),
        ("#2", 2),
        ("#3", 3),
        ("bunu sil #1", 1),
        ("#2'yi iptal et", 2),
    ])
    def test_hash_notation(self, text, expected_idx):
        item = self.table.resolve_reference(text)
        assert item is not None
        assert item.index == expected_idx

    # --- Turkish ordinals ---

    @pytest.mark.parametrize("text,expected_idx", [
        ("ilkini sil", 1),
        ("İlkini iptal et", 1),
        ("birincisini sil", 1),
        ("ikincisini değiştir", 2),
        ("ikinci etkinliği sil", 2),
        ("üçüncüsünü iptal et", 3),
        ("üçüncü toplantı", 3),
    ])
    def test_turkish_ordinals(self, text, expected_idx):
        item = self.table.resolve_reference(text)
        assert item is not None, f"Failed to resolve: {text}"
        assert item.index == expected_idx

    # --- Positional ---

    @pytest.mark.parametrize("text", [
        "sonuncusu",
        "sonuncusunu sil",
        "son etkinliği iptal et",
    ])
    def test_last_item(self, text):
        item = self.table.resolve_reference(text)
        assert item is not None, f"Failed to resolve: {text}"
        assert item.index == 3  # Last of 3

    @pytest.mark.parametrize("text", [
        "ilk",
        "ilkini",
        "İlk etkinlik",
    ])
    def test_first_item(self, text):
        item = self.table.resolve_reference(text)
        assert item is not None, f"Failed to resolve: {text}"
        assert item.index == 1

    # --- Digit matching ---

    @pytest.mark.parametrize("text,expected_idx", [
        ("1", 1),
        ("2", 2),
        ("3", 3),
        ("etkinlik 2", 2),
    ])
    def test_digit_matching(self, text, expected_idx):
        item = self.table.resolve_reference(text)
        assert item is not None
        assert item.index == expected_idx

    # --- Out of range ---

    def test_out_of_range_hash(self):
        item = self.table.resolve_reference("#10")
        assert item is None

    def test_out_of_range_digit(self):
        item = self.table.resolve_reference("99")
        assert item is None

    # --- No match ---

    def test_no_match(self):
        item = self.table.resolve_reference("bugünkü hava nasıl")
        assert item is None

    # --- Empty table ---

    def test_empty_table(self):
        table = ReferenceTable()
        assert table.resolve_reference("#1") is None
        assert table.resolve_reference("ilkini") is None
        assert table.resolve_reference("sonuncusu") is None


# ===================================================================
# Tests: Individual extractors
# ===================================================================


class TestCalendarEventExtractor:
    def test_dict_with_events_key(self):
        result = {"events": [{"summary": "Test", "start": {"dateTime": "2025-01-20T10:00:00+03:00"}}]}
        items = _extract_calendar_events(result)
        assert len(items) == 1
        assert items[0].label == "Test — 10:00"

    def test_dict_with_items_key(self):
        result = {"items": [{"summary": "Test", "start": {"dateTime": "2025-01-20T10:00:00"}}]}
        items = _extract_calendar_events(result)
        assert len(items) == 1

    def test_list_input(self):
        result = [{"summary": "A"}, {"summary": "B"}]
        items = _extract_calendar_events(result)
        assert len(items) == 2

    def test_json_string_input(self):
        data = {"events": [{"summary": "Parsed", "start": {"dateTime": "2025-01-20T14:00:00"}}]}
        result = json.dumps(data)
        items = _extract_calendar_events(result)
        assert len(items) == 1
        assert "Parsed" in items[0].label

    def test_invalid_json_string(self):
        items = _extract_calendar_events("not json at all")
        assert items == []

    def test_date_only_start(self):
        result = [{"summary": "All Day", "start": {"date": "2025-01-20"}}]
        items = _extract_calendar_events(result)
        assert len(items) == 1
        assert "2025-01-20" in items[0].label

    def test_string_start(self):
        result = [{"summary": "Quick", "start": "14:00"}]
        items = _extract_calendar_events(result)
        assert len(items) == 1

    def test_no_summary_fallback(self):
        result = [{"start": {"dateTime": "2025-01-20T10:00:00"}}]
        items = _extract_calendar_events(result)
        assert len(items) == 1
        assert "Etkinlik" in items[0].label

    def test_non_dict_item_skipped(self):
        result = [{"summary": "Real"}, "not a dict", 42]
        items = _extract_calendar_events(result)
        assert len(items) == 1

    def test_empty_events_list(self):
        result = {"events": []}
        items = _extract_calendar_events(result)
        assert items == []

    def test_none_items_list(self):
        result = {"events": None}
        items = _extract_calendar_events(result)
        assert items == []


class TestEmailExtractor:
    def test_messages_key(self):
        result = {"messages": [
            {"id": "m1", "from": "Ali", "subject": "Merhaba"},
            {"id": "m2", "from": "Veli", "subject": "Selam"},
        ]}
        items = _extract_emails(result)
        assert len(items) == 2
        assert "Ali" in items[0].label
        assert "Merhaba" in items[0].label

    def test_emails_key(self):
        result = {"emails": [{"from": "Test", "subject": "Subject"}]}
        items = _extract_emails(result)
        assert len(items) == 1

    def test_list_input(self):
        result = [{"from": "A", "subject": "B"}]
        items = _extract_emails(result)
        assert len(items) == 1

    def test_long_sender_truncated(self):
        result = [{"from": "A" * 50, "subject": "Test"}]
        items = _extract_emails(result)
        assert len(items[0].label) < 100  # Sender truncated to 30

    def test_no_sender(self):
        result = [{"subject": "Only subject"}]
        items = _extract_emails(result)
        assert len(items) == 1
        assert items[0].label == "Only subject"


class TestContactExtractor:
    def test_contacts_key(self):
        result = {"contacts": [{"name": "Ali"}, {"name": "Veli"}]}
        items = _extract_contacts(result)
        assert len(items) == 2
        assert items[0].label == "Ali"

    def test_list_input(self):
        result = [{"name": "Ali"}]
        items = _extract_contacts(result)
        assert len(items) == 1

    def test_string_contacts(self):
        result = ["Ali Veli", "Mehmet Öz"]
        items = _extract_contacts(result)
        assert len(items) == 2
        assert items[0].label == "Ali Veli"

    def test_display_name_fallback(self):
        result = [{"display_name": "Zeynep"}]
        items = _extract_contacts(result)
        assert len(items) == 1
        assert items[0].label == "Zeynep"


class TestFreeSlotsExtractor:
    def test_dict_with_slots(self):
        result = {"slots": [
            {"start": "2025-01-20T10:00:00+03:00", "end": "2025-01-20T11:00:00+03:00"},
        ]}
        items = _extract_free_slots(result)
        assert len(items) == 1
        assert "10:00" in items[0].label
        assert "11:00" in items[0].label

    def test_list_input(self):
        result = [
            {"start": "2025-01-20T10:00:00", "end": "2025-01-20T12:00:00"},
        ]
        items = _extract_free_slots(result)
        assert len(items) == 1

    def test_string_slots(self):
        result = ["10:00 - 11:00", "14:00 - 15:00"]
        items = _extract_free_slots(result)
        assert len(items) == 2
        assert items[0].label == "10:00 - 11:00"

    def test_free_slots_key(self):
        result = {"free_slots": [
            {"start": "2025-01-20T15:00:00", "end": "2025-01-20T17:00:00"},
        ]}
        items = _extract_free_slots(result)
        assert len(items) == 1


class TestGenericListExtractor:
    def test_dict_items(self):
        result = [{"name": "A"}, {"title": "B"}, {"summary": "C"}]
        items = _extract_generic_list(result)
        assert len(items) == 3
        assert items[0].label == "A"
        assert items[1].label == "B"
        assert items[2].label == "C"

    def test_string_items(self):
        result = ["foo", "bar", "baz"]
        items = _extract_generic_list(result)
        assert len(items) == 3
        assert items[0].label == "foo"

    def test_mixed_items(self):
        result = [{"name": "A"}, "B", 42]
        items = _extract_generic_list(result)
        assert len(items) == 3

    def test_long_string_truncated(self):
        result = ["x" * 200]
        items = _extract_generic_list(result)
        assert len(items[0].label) == 60


# ===================================================================
# Tests: _format_time helper
# ===================================================================


class TestFormatTime:
    def test_iso_datetime(self):
        assert _format_time("2025-01-20T14:30:00+03:00") == "14:30"

    def test_iso_datetime_utc(self):
        assert _format_time("2025-01-20T11:00:00Z") == "11:00"

    def test_date_only(self):
        assert _format_time("2025-01-20") == "2025-01-20"

    def test_empty_string(self):
        assert _format_time("") == ""

    def test_plain_time(self):
        assert _format_time("14:00") == "14:00"

    def test_invalid_iso(self):
        result = _format_time("not-a-time-but-very-long-string-here")
        assert len(result) <= 16  # Truncated fallback


# ===================================================================
# Tests: extract_references convenience function
# ===================================================================


class TestExtractReferences:
    def test_convenience_function(self, calendar_events_result):
        table = extract_references([calendar_events_result])
        assert len(table) == 3
        assert isinstance(table, ReferenceTable)

    def test_convenience_max_items(self):
        events = [{"summary": f"E{i}", "start": "2025-01-20"} for i in range(20)]
        results = [{"tool": "calendar.list_events", "success": True, "result": {"events": events}}]
        table = extract_references(results, max_items=3)
        assert len(table) == 3


# ===================================================================
# Tests: OrchestratorState integration
# ===================================================================


class TestOrchestratorStateIntegration:
    def test_reference_table_default_none(self):
        state = OrchestratorState()
        assert state.reference_table is None

    def test_reference_table_can_be_set(self, calendar_events_result):
        state = OrchestratorState()
        table = ReferenceTable.from_tool_results([calendar_events_result])
        state.reference_table = table
        assert state.reference_table is not None
        assert len(state.reference_table) == 3

    def test_reference_table_reset(self, calendar_events_result):
        state = OrchestratorState()
        state.reference_table = ReferenceTable.from_tool_results([calendar_events_result])
        state.reset()
        assert state.reference_table is None

    def test_reference_table_resolve_after_set(self, calendar_events_result):
        """Full flow: set table, resolve reference."""
        state = OrchestratorState()
        state.reference_table = ReferenceTable.from_tool_results([calendar_events_result])

        item = state.reference_table.resolve_reference("ilkini sil")
        assert item is not None
        assert "Standup" in item.label

        item = state.reference_table.resolve_reference("sonuncusu")
        assert item is not None
        assert "Sprint Review" in item.label


# ===================================================================
# Tests: Context injection (simulate orchestrator_loop behavior)
# ===================================================================


class TestContextInjection:
    """Simulate how orchestrator_loop._llm_planning_phase injects reference table."""

    def _build_context_parts(self, tool_results):
        """Simulate the context building from orchestrator_loop."""
        context_parts = []

        # Simulate LAST_TOOL_RESULTS
        if tool_results:
            result_lines = ["LAST_TOOL_RESULTS:"]
            for tr in tool_results[-2:]:
                tool_name = str(tr.get("tool", ""))
                result_str = str(tr.get("result_summary", ""))[:200]
                success = tr.get("success", True)
                status = "ok" if success else "fail"
                result_lines.append(f"  {tool_name} ({status}): {result_str}")
            context_parts.append("\n".join(result_lines))

        # Issue #416: Inject REFERENCE_TABLE
        if tool_results:
            ref_table = ReferenceTable.from_tool_results(tool_results)
            ref_block = ref_table.to_prompt_block()
            if ref_block:
                context_parts.append(ref_block)

        return "\n\n".join(context_parts) if context_parts else None

    def test_reference_table_in_context(self, calendar_events_result):
        context = self._build_context_parts([calendar_events_result])
        assert context is not None
        assert "REFERENCE_TABLE" in context
        assert "#1:" in context
        assert "LAST_TOOL_RESULTS" in context

    def test_no_reference_table_for_empty_results(self):
        context = self._build_context_parts([])
        assert context is None

    def test_no_reference_table_for_failed_tool(self):
        results = [{"tool": "calendar.list_events", "success": False, "result": None}]
        context = self._build_context_parts(results)
        assert context is not None  # LAST_TOOL_RESULTS still there
        assert "REFERENCE_TABLE" not in context

    def test_reference_table_after_tool_results(self, calendar_events_result):
        """REFERENCE_TABLE should appear after LAST_TOOL_RESULTS."""
        context = self._build_context_parts([calendar_events_result])
        idx_tool = context.index("LAST_TOOL_RESULTS")
        idx_ref = context.index("REFERENCE_TABLE")
        assert idx_ref > idx_tool


# ===================================================================
# Tests: Edge cases
# ===================================================================


class TestEdgeCases:
    def test_bool_false_for_empty_table(self):
        table = ReferenceTable()
        assert not table

    def test_bool_true_for_nonempty(self, calendar_events_result):
        table = ReferenceTable.from_tool_results([calendar_events_result])
        assert table

    def test_len(self, calendar_events_result):
        table = ReferenceTable.from_tool_results([calendar_events_result])
        assert len(table) == 3

    def test_items_reindexed(self, calendar_events_result):
        """Items should be reindexed 1..N."""
        table = ReferenceTable.from_tool_results([calendar_events_result])
        for i, item in enumerate(table.items, 1):
            assert item.index == i

    def test_unicode_in_labels(self):
        """Turkish characters should work fine."""
        result = [{"tool": "calendar.list_events", "success": True, "result": {
            "events": [
                {"summary": "Öğle Yemeği", "start": {"dateTime": "2025-01-20T12:00:00+03:00"}},
                {"summary": "Çay Molası", "start": {"dateTime": "2025-01-20T15:00:00+03:00"}},
                {"summary": "Görüşme", "start": {"dateTime": "2025-01-20T16:00:00+03:00"}},
            ]
        }}]
        table = ReferenceTable.from_tool_results(result)
        assert len(table) == 3
        assert "Öğle" in table.items[0].label
        assert "Çay" in table.items[1].label
        assert "Görüşme" in table.items[2].label

    def test_resolve_case_insensitive(self, calendar_events_result):
        """Turkish ordinals should work case-insensitive."""
        table = ReferenceTable.from_tool_results([calendar_events_result])
        # uppercase
        item = table.resolve_reference("İLKİNİ sil")
        assert item is not None
        assert item.index == 1

    def test_multiple_tool_results_only_first_used(self):
        """If multiple tools have results, only the first matching one is used."""
        results = [
            {
                "tool": "calendar.list_events",
                "success": True,
                "result": {"events": [{"summary": "A"}]},
            },
            {
                "tool": "gmail.list_messages",
                "success": True,
                "result": {"messages": [{"subject": "B"}]},
            },
        ]
        table = ReferenceTable.from_tool_results(results)
        assert table.source_tool == "calendar.list_events"
        assert len(table) == 1

    def test_event_with_title_key(self):
        """Some calendar APIs use 'title' instead of 'summary'."""
        result = [{"tool": "calendar.list_events", "success": True, "result": {
            "events": [{"title": "Custom Title", "start": "2025-01-20"}]
        }}]
        table = ReferenceTable.from_tool_results(result)
        assert "Custom Title" in table.items[0].label

    def test_search_gmail_matches(self):
        """gmail.search_messages should also be handled."""
        result = [{"tool": "gmail.search_messages", "success": True, "result": {
            "messages": [{"from": "Test", "subject": "Found"}]
        }}]
        table = ReferenceTable.from_tool_results(result)
        assert len(table) == 1
        assert table.items[0].item_type == "email"
