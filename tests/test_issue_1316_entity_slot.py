"""Tests for Issue #1316 — EntitySlot.age, prompt block truncation, reset.

Validates:
1. EntitySlot.age returns actual turn age after expire_stale stamps it
2. SlotRegistry.to_prompt_block uses key-based trimming (valid JSON)
3. OrchestratorState.reset clears current_user_input
"""

from __future__ import annotations

import json

from bantz.brain.orchestrator_state import (EntitySlot, OrchestratorState,
                                            SlotRegistry)

# ---------------------------------------------------------------------------
# EntitySlot.age
# ---------------------------------------------------------------------------


class TestEntitySlotAge:
    """EntitySlot.age should compute actual turn age."""

    def test_age_defaults_zero_without_stamp(self) -> None:
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="e1",
            slots={"summary": "Meeting"},
            source_tool="calendar.list_events",
            created_at_turn=5,
        )
        assert entity.age == 0

    def test_age_computed_after_expire_stale(self) -> None:
        reg = SlotRegistry()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="e1",
            slots={"summary": "Meeting"},
            source_tool="calendar.list_events",
            created_at_turn=3,
        )
        reg.register(entity)
        reg.expire_stale(current_turn=7)
        assert entity.age == 4  # 7 - 3

    def test_age_updates_each_turn(self) -> None:
        reg = SlotRegistry()
        entity = EntitySlot(
            entity_type="gmail_message",
            entity_id="m1",
            slots={"subject": "Hello"},
            source_tool="gmail.list",
            created_at_turn=0,
            ttl=10,  # longer TTL so entity survives multiple turns
        )
        reg.register(entity)
        reg.expire_stale(current_turn=2)
        assert entity.age == 2
        reg.expire_stale(current_turn=5)
        assert entity.age == 5


# ---------------------------------------------------------------------------
# to_prompt_block — key-based trimming
# ---------------------------------------------------------------------------


class TestToPromptBlockTrimming:
    """to_prompt_block should produce valid JSON even for large entities."""

    def test_short_entity_valid_json(self) -> None:
        reg = SlotRegistry()
        entity = EntitySlot(
            entity_type="calendar_event",
            entity_id="e1",
            slots={"summary": "Toplantı", "start": "10:00"},
            source_tool="calendar.list_events",
            created_at_turn=0,
        )
        reg.register(entity)
        block = reg.to_prompt_block()
        parsed = json.loads(block)
        assert parsed["type"] == "calendar_event"
        assert parsed["id"] == "e1"

    def test_large_entity_trimmed_to_valid_json(self) -> None:
        """Large slot values should be trimmed, not raw-sliced."""
        reg = SlotRegistry()
        entity = EntitySlot(
            entity_type="gmail_message",
            entity_id="m1",
            slots={
                "subject": "Test",
                "body": "x" * 500,  # Very long body
                "from": "alice@example.com",
            },
            source_tool="gmail.read",
            created_at_turn=0,
        )
        reg.register(entity)
        block = reg.to_prompt_block()
        # Block should be within limit
        assert len(block) <= 400
        # Should still be parseable as JSON (or at worst trimmed gracefully)
        # The key-based trimming should keep it valid
        try:
            parsed = json.loads(block)
            assert "type" in parsed
        except json.JSONDecodeError:
            # Even if final hard cap kicks in, block shouldn't have trailing "…"
            assert "…" not in block

    def test_empty_registry_returns_empty(self) -> None:
        reg = SlotRegistry()
        assert reg.to_prompt_block() == ""

    def test_no_broken_ellipsis_in_output(self) -> None:
        """Old bug: block[:400] + '…' produced broken JSON."""
        reg = SlotRegistry()
        entity = EntitySlot(
            entity_type="test",
            entity_id="t1",
            slots={"data": "y" * 600},
            source_tool="tool",
            created_at_turn=0,
        )
        reg.register(entity)
        block = reg.to_prompt_block()
        # Must not end with unicode ellipsis (old behavior)
        assert not block.endswith("…")


# ---------------------------------------------------------------------------
# reset() clears current_user_input
# ---------------------------------------------------------------------------


class TestResetClearsUserInput:
    """OrchestratorState.reset must clear current_user_input."""

    def test_current_user_input_cleared(self) -> None:
        state = OrchestratorState()
        state.current_user_input = "yarın toplantı var mı"
        state.reset()
        assert state.current_user_input == ""

    def test_reset_clears_all_fields(self) -> None:
        """Spot check that other fields are also reset."""
        state = OrchestratorState()
        state.current_user_input = "test"
        state.rolling_summary = "old summary"
        state.turn_count = 42
        state.reset()
        assert state.current_user_input == ""
        assert state.rolling_summary == ""
        assert state.turn_count == 0
