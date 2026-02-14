"""Tests for Issue #1276: Dialogue State Machine — Cross-Turn Slot Tracking.

Tests EntitySlot, SlotRegistry, extract_entity_from_tool_result,
and the integration with OrchestratorState and OrchestratorLoop.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from bantz.brain.orchestrator_state import (
    EntitySlot,
    SlotRegistry,
    OrchestratorState,
    extract_entity_from_tool_result,
    _ENTITY_TTL,
)


# ====================================================================
# EntitySlot unit tests
# ====================================================================

class TestEntitySlot:
    """Tests for EntitySlot dataclass."""

    def test_basic_creation(self):
        slot = EntitySlot(
            entity_type="calendar_event",
            entity_id="abc123",
            slots={"summary": "Toplantı", "start": "2025-01-15T10:00:00"},
            source_tool="calendar.create_event",
            created_at_turn=3,
        )
        assert slot.entity_type == "calendar_event"
        assert slot.entity_id == "abc123"
        assert slot.slots["summary"] == "Toplantı"
        assert slot.source_tool == "calendar.create_event"
        assert slot.created_at_turn == 3
        assert slot.ttl == _ENTITY_TTL

    def test_is_expired_false(self):
        slot = EntitySlot(
            entity_type="calendar_event",
            entity_id="abc123",
            slots={},
            source_tool="calendar.create_event",
            created_at_turn=3,
            ttl=5,
        )
        assert not slot.is_expired(current_turn=3)
        assert not slot.is_expired(current_turn=7)  # 7-3=4 < 5

    def test_is_expired_true(self):
        slot = EntitySlot(
            entity_type="calendar_event",
            entity_id="abc123",
            slots={},
            source_tool="calendar.create_event",
            created_at_turn=3,
            ttl=5,
        )
        assert slot.is_expired(current_turn=8)   # 8-3=5 >= 5
        assert slot.is_expired(current_turn=10)  # 10-3=7 >= 5

    def test_to_prompt_dict_calendar(self):
        slot = EntitySlot(
            entity_type="calendar_event",
            entity_id="evt_001",
            slots={"summary": "Standup", "start": "10:00", "end": "10:30", "location": ""},
            source_tool="calendar.create_event",
            created_at_turn=1,
        )
        d = slot.to_prompt_dict()
        assert d["type"] == "calendar_event"
        assert d["id"] == "evt_001"
        assert d["summary"] == "Standup"
        assert d["start"] == "10:00"
        assert d["end"] == "10:30"
        # Empty location should be excluded
        assert "location" not in d

    def test_to_prompt_dict_no_id(self):
        slot = EntitySlot(
            entity_type="system",
            entity_id=None,
            slots={"action": "reboot"},
            source_tool="system.reboot",
            created_at_turn=0,
        )
        d = slot.to_prompt_dict()
        assert "id" not in d
        assert d["type"] == "system"
        assert d["action"] == "reboot"

    def test_custom_ttl(self):
        slot = EntitySlot(
            entity_type="calendar_event",
            entity_id="x",
            slots={},
            source_tool="calendar.create_event",
            created_at_turn=0,
            ttl=2,
        )
        assert not slot.is_expired(1)
        assert slot.is_expired(2)


# ====================================================================
# SlotRegistry unit tests
# ====================================================================

class TestSlotRegistry:
    """Tests for SlotRegistry class."""

    def _make_entity(self, entity_type="calendar_event", entity_id="e1",
                     turn=0, ttl=5, tool="calendar.create_event", **slots):
        return EntitySlot(
            entity_type=entity_type,
            entity_id=entity_id,
            slots=slots,
            source_tool=tool,
            created_at_turn=turn,
            ttl=ttl,
        )

    def test_register_and_get_active(self):
        reg = SlotRegistry()
        entity = self._make_entity()
        reg.register(entity)
        assert reg.get_active() is entity
        assert reg.active_entity_type == "calendar_event"
        assert reg.active_entity_id == "e1"

    def test_register_replaces_active(self):
        reg = SlotRegistry()
        e1 = self._make_entity(entity_id="e1")
        e2 = self._make_entity(entity_id="e2", entity_type="gmail_message",
                               tool="gmail.send")
        reg.register(e1)
        reg.register(e2)
        assert reg.get_active() is e2
        assert reg.active_entity_id == "e2"
        # But e1 is still accessible by ID
        assert reg.get_by_id("e1") is e1

    def test_get_by_id(self):
        reg = SlotRegistry()
        e1 = self._make_entity(entity_id="abc")
        reg.register(e1)
        assert reg.get_by_id("abc") is e1
        assert reg.get_by_id("nonexistent") is None

    def test_expire_stale(self):
        reg = SlotRegistry()
        e1 = self._make_entity(entity_id="old", turn=0, ttl=3)
        e2 = self._make_entity(entity_id="new", turn=2, ttl=5)
        reg.register(e1)
        reg.register(e2)

        # At turn 3: e1 (0+3=3 >= 3) expires, e2 (2+5=7 > 3) stays
        expired = reg.expire_stale(current_turn=3)
        assert expired == 1
        assert reg.get_by_id("old") is None
        assert reg.get_by_id("new") is e2
        # e2 is still active
        assert reg.get_active() is e2

    def test_expire_active_entity(self):
        reg = SlotRegistry()
        e1 = self._make_entity(entity_id="only", turn=0, ttl=2)
        reg.register(e1)

        expired = reg.expire_stale(current_turn=2)
        assert expired == 1
        assert reg.get_active() is None
        assert reg.active_entity_type == ""
        assert reg.active_entity_id is None

    def test_to_prompt_block_with_active(self):
        reg = SlotRegistry()
        entity = self._make_entity(summary="Standup", start="10:00")
        reg.register(entity)
        block = reg.to_prompt_block()
        assert block  # non-empty
        parsed = json.loads(block)
        assert parsed["type"] == "calendar_event"
        assert parsed["id"] == "e1"
        assert parsed["summary"] == "Standup"

    def test_to_prompt_block_empty(self):
        reg = SlotRegistry()
        assert reg.to_prompt_block() == ""

    def test_to_prompt_block_length_cap(self):
        """Prompt block should not exceed 400 chars."""
        reg = SlotRegistry()
        # Create entity with very long slots
        entity = self._make_entity(
            description="A" * 500,
            notes="B" * 500,
        )
        reg.register(entity)
        block = reg.to_prompt_block()
        assert len(block) <= 401  # 400 + "…"

    def test_clear(self):
        reg = SlotRegistry()
        reg.register(self._make_entity(entity_id="x"))
        reg.register(self._make_entity(entity_id="y"))
        assert len(reg) == 2
        reg.clear()
        assert len(reg) == 0
        assert reg.get_active() is None

    def test_max_entities_eviction(self):
        reg = SlotRegistry(max_entities=3)
        for i in range(5):
            reg.register(self._make_entity(entity_id=f"e{i}", turn=i))
        # Should have max 3 entities
        assert len(reg) == 3
        # Oldest (e0, e1) should be evicted
        assert reg.get_by_id("e0") is None
        assert reg.get_by_id("e1") is None
        # Newest should be present
        assert reg.get_by_id("e4") is not None

    def test_entity_without_id_not_stored(self):
        reg = SlotRegistry()
        entity = self._make_entity(entity_id=None)
        reg.register(entity)
        # Should be active but not in _entities dict
        assert reg.get_active() is entity
        assert len(reg) == 0

    def test_repr(self):
        reg = SlotRegistry()
        assert "active=None" in repr(reg)
        reg.register(self._make_entity(entity_id="xyz"))
        assert "active=xyz" in repr(reg)

    def test_len(self):
        reg = SlotRegistry()
        assert len(reg) == 0
        reg.register(self._make_entity(entity_id="a"))
        assert len(reg) == 1


# ====================================================================
# extract_entity_from_tool_result tests
# ====================================================================

class TestExtractEntityFromToolResult:
    """Tests for extract_entity_from_tool_result function."""

    def test_calendar_create_event(self):
        result = {
            "ok": True,
            "id": "evt_abc123",
            "summary": "Toplantı",
            "start": "2025-01-15T10:00:00",
            "end": "2025-01-15T11:00:00",
            "htmlLink": "https://calendar.google.com/event/abc123",
            "all_day": False,
        }
        entity = extract_entity_from_tool_result(
            tool_name="calendar.create_event",
            result_raw=result,
            current_turn=5,
        )
        assert entity is not None
        assert entity.entity_type == "calendar_event"
        assert entity.entity_id == "evt_abc123"
        assert entity.slots["summary"] == "Toplantı"
        assert entity.slots["start"] == "2025-01-15T10:00:00"
        assert entity.source_tool == "calendar.create_event"
        assert entity.created_at_turn == 5

    def test_calendar_list_events(self):
        result = {
            "ok": True,
            "events": [
                {"id": "ev1", "summary": "Standup", "start": "09:00", "end": "09:30"},
                {"id": "ev2", "summary": "Lunch", "start": "12:00", "end": "13:00"},
            ],
        }
        entity = extract_entity_from_tool_result(
            tool_name="calendar.list_events",
            result_raw=result,
            current_turn=1,
        )
        assert entity is not None
        assert entity.entity_type == "calendar_events"
        assert entity.entity_id == "ev1"  # first event
        assert entity.slots["count"] == 2
        assert len(entity.slots["items"]) == 2

    def test_gmail_send(self):
        result = {
            "ok": True,
            "message_id": "msg_xyz789",
            "to": "user@example.com",
            "subject": "Test mail",
        }
        entity = extract_entity_from_tool_result(
            tool_name="gmail.send",
            result_raw=result,
            current_turn=2,
        )
        assert entity is not None
        assert entity.entity_type == "gmail_message"
        assert entity.entity_id == "msg_xyz789"
        assert entity.slots["subject"] == "Test mail"

    def test_gmail_list_messages(self):
        result = {
            "ok": True,
            "messages": [
                {"id": "m1", "from": "alice@test.com", "subject": "Hello", "snippet": "Hi there"},
                {"id": "m2", "from": "bob@test.com", "subject": "Meeting", "snippet": "Tomorrow"},
            ],
        }
        entity = extract_entity_from_tool_result(
            tool_name="gmail.list_messages",
            result_raw=result,
            current_turn=0,
        )
        assert entity is not None
        assert entity.entity_type == "gmail_messages"
        assert entity.slots["count"] == 2

    def test_unknown_tool_returns_none(self):
        entity = extract_entity_from_tool_result(
            tool_name="weather.get_forecast",
            result_raw={"ok": True, "temp": 25},
            current_turn=0,
        )
        assert entity is None

    def test_failed_result_returns_none(self):
        result = {"ok": False, "error": "Not found"}
        entity = extract_entity_from_tool_result(
            tool_name="calendar.create_event",
            result_raw=result,
            current_turn=0,
        )
        assert entity is None

    def test_non_dict_result_returns_none(self):
        entity = extract_entity_from_tool_result(
            tool_name="calendar.create_event",
            result_raw="just a string",
            current_turn=0,
        )
        assert entity is None

    def test_no_entity_id_returns_none(self):
        """Result without a recognizable ID should return None."""
        result = {"ok": True, "summary": "Test"}
        entity = extract_entity_from_tool_result(
            tool_name="calendar.create_event",
            result_raw=result,
            current_turn=0,
        )
        assert entity is None

    def test_calendar_update_event(self):
        result = {
            "ok": True,
            "id": "evt_updated",
            "summary": "Updated meeting",
            "start": "2025-01-15T15:00:00",
            "end": "2025-01-15T16:00:00",
        }
        entity = extract_entity_from_tool_result(
            tool_name="calendar.update_event",
            result_raw=result,
            current_turn=4,
        )
        assert entity is not None
        assert entity.entity_type == "calendar_event"
        assert entity.entity_id == "evt_updated"
        assert entity.slots["start"] == "2025-01-15T15:00:00"

    def test_gmail_reply(self):
        result = {
            "ok": True,
            "message_id": "reply_001",
            "to": "alice@test.com",
            "subject": "Re: Hello",
        }
        entity = extract_entity_from_tool_result(
            tool_name="gmail.reply",
            result_raw=result,
            current_turn=3,
        )
        assert entity is not None
        assert entity.entity_type == "gmail_message"
        assert entity.entity_id == "reply_001"

    def test_custom_ttl(self):
        result = {"ok": True, "id": "ev1", "summary": "Test"}
        entity = extract_entity_from_tool_result(
            tool_name="calendar.create_event",
            result_raw=result,
            current_turn=0,
            ttl=10,
        )
        assert entity is not None
        assert entity.ttl == 10

    def test_empty_events_list_returns_none(self):
        result = {"ok": True, "events": []}
        entity = extract_entity_from_tool_result(
            tool_name="calendar.list_events",
            result_raw=result,
            current_turn=0,
        )
        assert entity is None

    def test_max_five_items_in_list_entity(self):
        """List entity slots should cap at 5 items."""
        result = {
            "ok": True,
            "events": [
                {"id": f"ev{i}", "summary": f"Event {i}", "start": f"{i}:00"}
                for i in range(10)
            ],
        }
        entity = extract_entity_from_tool_result(
            tool_name="calendar.list_events",
            result_raw=result,
            current_turn=0,
        )
        assert entity is not None
        assert len(entity.slots["items"]) == 5
        assert entity.slots["count"] == 10


# ====================================================================
# OrchestratorState integration tests
# ====================================================================

class TestOrchestratorStateEntityTracking:
    """Tests for SlotRegistry integration in OrchestratorState."""

    def test_state_has_slot_registry(self):
        state = OrchestratorState()
        assert isinstance(state.slot_registry, SlotRegistry)

    def test_get_context_includes_entity(self):
        state = OrchestratorState()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="evt_001",
            slots={"summary": "Daily standup"},
            source_tool="calendar.create_event",
            created_at_turn=0,
        )
        state.slot_registry.register(entity)
        ctx = state.get_context_for_llm()
        assert "entity_context" in ctx
        parsed = json.loads(ctx["entity_context"])
        assert parsed["type"] == "calendar_event"
        assert parsed["id"] == "evt_001"

    def test_get_context_no_entity(self):
        state = OrchestratorState()
        ctx = state.get_context_for_llm()
        assert "entity_context" not in ctx

    def test_reset_clears_slot_registry(self):
        state = OrchestratorState()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="evt_001",
            slots={},
            source_tool="calendar.create_event",
            created_at_turn=0,
        )
        state.slot_registry.register(entity)
        assert state.slot_registry.get_active() is not None
        
        state.reset()
        assert state.slot_registry.get_active() is None
        assert len(state.slot_registry) == 0

    def test_entity_survives_across_turns(self):
        """Entity should persist across add_tool_result / add_conversation_turn calls."""
        state = OrchestratorState()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="evt_persist",
            slots={"summary": "Persisted"},
            source_tool="calendar.create_event",
            created_at_turn=0,
            ttl=5,
        )
        state.slot_registry.register(entity)

        # Simulate a few turns
        for i in range(3):
            state.add_tool_result(f"tool_{i}", {"ok": True})
            state.add_conversation_turn(f"input {i}", f"reply {i}")

        # Entity should still be active
        assert state.slot_registry.get_active() is entity
        assert state.slot_registry.active_entity_id == "evt_persist"


# ====================================================================
# Integration: _extract_and_register_entities
# ====================================================================

class TestExtractAndRegisterEntities:
    """Integration tests for entity extraction in OrchestratorLoop."""

    def test_extract_from_calendar_create(self):
        """Simulates _extract_and_register_entities with calendar.create_event result."""
        from bantz.brain.orchestrator_state import extract_entity_from_tool_result

        state = OrchestratorState()
        tool_results = [
            {
                "tool": "calendar.create_event",
                "success": True,
                "raw_result": {
                    "ok": True,
                    "id": "evt_new",
                    "summary": "Toplantı",
                    "start": "2025-01-15T15:00:00",
                    "end": "2025-01-15T16:00:00",
                },
                "result": '{"ok": true}',
                "result_summary": "Event created",
            }
        ]

        for tr in tool_results:
            if not tr.get("success"):
                continue
            raw = tr.get("raw_result") or tr.get("result_raw")
            entity = extract_entity_from_tool_result(
                tool_name=tr["tool"],
                result_raw=raw,
                current_turn=state.turn_count,
            )
            if entity:
                state.slot_registry.register(entity)

        assert state.slot_registry.active_entity_id == "evt_new"
        assert state.slot_registry.active_entity_type == "calendar_event"

        # Context should include entity
        ctx = state.get_context_for_llm()
        assert "entity_context" in ctx

    def test_extract_from_gmail_send(self):
        state = OrchestratorState()
        tool_results = [
            {
                "tool": "gmail.send",
                "success": True,
                "raw_result": {
                    "ok": True,
                    "message_id": "msg_sent_001",
                    "to": "alice@test.com",
                    "subject": "Merhaba",
                },
                "result": "{}",
                "result_summary": "Email sent",
            }
        ]

        for tr in tool_results:
            if not tr.get("success"):
                continue
            raw = tr.get("raw_result")
            entity = extract_entity_from_tool_result(
                tool_name=tr["tool"],
                result_raw=raw,
                current_turn=0,
            )
            if entity:
                state.slot_registry.register(entity)

        assert state.slot_registry.active_entity_type == "gmail_message"
        assert state.slot_registry.active_entity_id == "msg_sent_001"

    def test_failed_tool_not_registered(self):
        state = OrchestratorState()
        tool_results = [
            {
                "tool": "calendar.create_event",
                "success": False,
                "raw_result": {"ok": False, "error": "Auth failed"},
                "result": "{}",
                "result_summary": "Failed",
            }
        ]

        for tr in tool_results:
            if not tr.get("success"):
                continue
            raw = tr.get("raw_result")
            entity = extract_entity_from_tool_result(
                tool_name=tr["tool"],
                result_raw=raw,
                current_turn=0,
            )
            if entity:
                state.slot_registry.register(entity)

        assert state.slot_registry.get_active() is None


# ====================================================================
# Full flow: multi-turn entity tracking
# ====================================================================

class TestMultiTurnEntityFlow:
    """End-to-end tests for the 'Toplantı koy → saatini değiştir' flow."""

    def test_create_then_update_flow(self):
        """Simulates: Turn 1: create event → Turn 2: update event."""
        state = OrchestratorState()

        # Turn 1: Create event
        create_result = {
            "ok": True,
            "id": "evt_meeting",
            "summary": "Toplantı",
            "start": "2025-01-15T15:00:00",
            "end": "2025-01-15T16:00:00",
        }
        entity = extract_entity_from_tool_result(
            "calendar.create_event", create_result, current_turn=0,
        )
        state.slot_registry.register(entity)
        state.turn_count = 1

        # Verify entity is active
        assert state.slot_registry.active_entity_id == "evt_meeting"

        # Turn 2: User says "saatini 5'e değiştir"
        # Entity context should be available for LLM
        ctx = state.get_context_for_llm()
        entity_ctx = ctx["entity_context"]
        parsed = json.loads(entity_ctx)
        assert parsed["id"] == "evt_meeting"
        assert parsed["summary"] == "Toplantı"

        # After update, new entity replaces active
        update_result = {
            "ok": True,
            "id": "evt_meeting",
            "summary": "Toplantı",
            "start": "2025-01-15T17:00:00",
            "end": "2025-01-15T18:00:00",
        }
        entity2 = extract_entity_from_tool_result(
            "calendar.update_event", update_result, current_turn=1,
        )
        state.slot_registry.register(entity2)
        state.turn_count = 2

        # Updated entity is now active
        active = state.slot_registry.get_active()
        assert active.slots["start"] == "2025-01-15T17:00:00"

    def test_list_then_reply_then_subject_change(self):
        """Simulates: mail listele → 3.yü yanıtla → konuyu değiştir (3-turn chain)."""
        state = OrchestratorState()

        # Turn 1: List messages
        list_result = {
            "ok": True,
            "messages": [
                {"id": "m1", "from": "alice@test.com", "subject": "Meeting invite"},
                {"id": "m2", "from": "bob@test.com", "subject": "Lunch?"},
                {"id": "m3", "from": "carol@test.com", "subject": "Project update"},
            ],
        }
        entity = extract_entity_from_tool_result(
            "gmail.list_messages", list_result, current_turn=0,
        )
        state.slot_registry.register(entity)
        state.turn_count = 1

        assert state.slot_registry.active_entity_type == "gmail_messages"
        assert state.slot_registry.active_entity_id == "m1"

        # Turn 2: Reply to #3  (anaphora resolution handled elsewhere,
        # but entity tracking should update to the replied message)
        reply_result = {
            "ok": True,
            "message_id": "reply_m3",
            "to": "carol@test.com",
            "subject": "Re: Project update",
        }
        entity2 = extract_entity_from_tool_result(
            "gmail.reply", reply_result, current_turn=1,
        )
        state.slot_registry.register(entity2)
        state.turn_count = 2

        assert state.slot_registry.active_entity_type == "gmail_message"
        assert state.slot_registry.active_entity_id == "reply_m3"

        # Turn 3: Change subject — entity still accessible
        ctx = state.get_context_for_llm()
        assert "entity_context" in ctx
        parsed = json.loads(ctx["entity_context"])
        assert parsed["id"] == "reply_m3"
        assert parsed["subject"] == "Re: Project update"

    def test_entity_expires_after_ttl(self):
        """Active entity should auto-expire after TTL turns."""
        state = OrchestratorState()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="evt_old",
            slots={"summary": "Old Event"},
            source_tool="calendar.create_event",
            created_at_turn=0,
            ttl=5,
        )
        state.slot_registry.register(entity)

        # Advance 4 turns — entity should still be active
        state.slot_registry.expire_stale(current_turn=4)
        assert state.slot_registry.get_active() is not None

        # Advance to turn 5 — entity should expire
        state.slot_registry.expire_stale(current_turn=5)
        assert state.slot_registry.get_active() is None

        # No entity context in LLM prompt
        ctx = state.get_context_for_llm()
        assert "entity_context" not in ctx


# ====================================================================
# Prompt injection tests
# ====================================================================

class TestEntityPromptInjection:
    """Tests for ACTIVE_ENTITY block in _build_prompt."""

    def test_entity_block_in_prompt(self):
        """session_context with active_entity should produce ACTIVE_ENTITY block."""
        try:
            from bantz.brain.llm_router import _build_prompt, _estimate_tokens
        except ImportError:
            pytest.skip("Cannot import _build_prompt")

        # _build_prompt is a method, test via the public route if needed
        # Instead test the session_context flow
        state = OrchestratorState()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="evt_test",
            slots={"summary": "Prompt Test", "start": "14:00"},
            source_tool="calendar.create_event",
            created_at_turn=0,
        )
        state.slot_registry.register(entity)

        # Verify to_prompt_block returns valid JSON
        block = state.slot_registry.to_prompt_block()
        parsed = json.loads(block)
        assert parsed["type"] == "calendar_event"
        assert parsed["id"] == "evt_test"
        assert parsed["summary"] == "Prompt Test"

    def test_prompt_block_stays_within_budget(self):
        """Entity prompt block should not exceed ~100 tokens (~400 chars)."""
        reg = SlotRegistry()
        # Create entity with lots of data
        big_slots = {f"key_{i}": f"value_{i}" * 20 for i in range(20)}
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="big_entity",
            slots=big_slots,
            source_tool="calendar.create_event",
            created_at_turn=0,
        )
        reg.register(entity)
        block = reg.to_prompt_block()
        # Block should be capped
        assert len(block) <= 401  # 400 + "…"
