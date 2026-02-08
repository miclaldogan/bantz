"""Tests for Issue #521 — Memory trace + 2-turn anaphora golden test.

Covers:
  - MemoryBudgetConfig: env-based configuration
  - MemoryTraceRecord: injection + trim trace lines
  - EnhancedSummary: key-entity preservation
  - MemoryTracer: multi-turn lifecycle
  - 2-turn anaphora golden test: "yarın toplantılarım ne?" → "ilkini iptal et"
"""

from __future__ import annotations

import os
from unittest import mock

import pytest


# ═══════════════════════════════════════════════════════════════
# MemoryBudgetConfig
# ═══════════════════════════════════════════════════════════════

class TestMemoryBudgetConfig:
    def test_defaults(self):
        from bantz.brain.memory_trace import MemoryBudgetConfig
        cfg = MemoryBudgetConfig()
        assert cfg.max_tokens == 800
        assert cfg.max_turns == 10
        assert cfg.pii_filter is True

    def test_from_env_defaults(self):
        """No env vars → defaults."""
        from bantz.brain.memory_trace import MemoryBudgetConfig
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = MemoryBudgetConfig.from_env()
        assert cfg.max_tokens == 800
        assert cfg.max_turns == 10
        assert cfg.pii_filter is True

    def test_from_env_custom(self):
        from bantz.brain.memory_trace import MemoryBudgetConfig
        env = {
            "BANTZ_MEMORY_MAX_TOKENS": "1200",
            "BANTZ_MEMORY_MAX_TURNS": "20",
            "BANTZ_MEMORY_PII_FILTER": "false",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = MemoryBudgetConfig.from_env()
        assert cfg.max_tokens == 1200
        assert cfg.max_turns == 20
        assert cfg.pii_filter is False

    def test_from_env_invalid_int_fallback(self):
        """Non-numeric → falls back to defaults."""
        from bantz.brain.memory_trace import MemoryBudgetConfig
        env = {
            "BANTZ_MEMORY_MAX_TOKENS": "abc",
            "BANTZ_MEMORY_MAX_TURNS": "xyz",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = MemoryBudgetConfig.from_env()
        assert cfg.max_tokens == 800
        assert cfg.max_turns == 10

    def test_from_env_pii_variants(self):
        """PII filter accepts 0, false, no as disable."""
        from bantz.brain.memory_trace import MemoryBudgetConfig
        for val in ("0", "false", "no", "False", "NO"):
            with mock.patch.dict(os.environ, {"BANTZ_MEMORY_PII_FILTER": val}, clear=True):
                cfg = MemoryBudgetConfig.from_env()
            assert cfg.pii_filter is False, f"Expected False for '{val}'"

        for val in ("1", "true", "yes", "True"):
            with mock.patch.dict(os.environ, {"BANTZ_MEMORY_PII_FILTER": val}, clear=True):
                cfg = MemoryBudgetConfig.from_env()
            assert cfg.pii_filter is True, f"Expected True for '{val}'"


# ═══════════════════════════════════════════════════════════════
# MemoryTraceRecord
# ═══════════════════════════════════════════════════════════════

class TestMemoryTraceRecord:
    def test_defaults(self):
        from bantz.brain.memory_trace import MemoryTraceRecord
        rec = MemoryTraceRecord()
        assert rec.turn_number == 0
        assert rec.memory_injected is False
        assert rec.was_trimmed is False

    def test_to_trace_line_no_injection(self):
        from bantz.brain.memory_trace import MemoryTraceRecord
        rec = MemoryTraceRecord(turn_number=1, memory_injected=False, memory_tokens=0, memory_turns_count=0)
        line = rec.to_trace_line()
        assert "[memory]" in line
        assert "injected=False" in line

    def test_to_trace_line_injected(self):
        from bantz.brain.memory_trace import MemoryTraceRecord
        rec = MemoryTraceRecord(
            turn_number=3,
            memory_injected=True,
            memory_tokens=142,
            memory_turns_count=2,
        )
        line = rec.to_trace_line()
        assert "injected=True" in line
        assert "tokens=142" in line
        assert "turns=2" in line
        assert "TRIMMED" not in line

    def test_to_trace_line_trimmed(self):
        from bantz.brain.memory_trace import MemoryTraceRecord
        rec = MemoryTraceRecord(
            turn_number=5,
            memory_injected=True,
            memory_tokens=0,
            memory_turns_count=0,
            was_trimmed=True,
            original_tokens=450,
            after_trim_tokens=0,
            trim_reason="token_budget",
        )
        line = rec.to_trace_line()
        assert "TRIMMED" in line
        assert "original=450" in line
        assert "after=0" in line
        assert "reason=token_budget" in line


# ═══════════════════════════════════════════════════════════════
# EnhancedSummary
# ═══════════════════════════════════════════════════════════════

class TestEnhancedSummary:
    def test_basic_prompt_block(self):
        from bantz.brain.memory_trace import EnhancedSummary
        s = EnhancedSummary(
            turn_number=1,
            user_intent="asked about calendar",
            action_taken="listed events",
        )
        block = s.to_prompt_block()
        assert "Turn 1" in block
        assert "asked about calendar" in block
        assert "listed events" in block

    def test_prompt_block_with_entities(self):
        from bantz.brain.memory_trace import EnhancedSummary
        s = EnhancedSummary(
            turn_number=2,
            user_intent="asked about tomorrow's meetings",
            action_taken="listed calendar events",
            key_entities=["Ali", "toplantı", "14:00"],
            result_count=3,
            tool_used="calendar.list_events",
        )
        block = s.to_prompt_block()
        assert "Key data: Ali, toplantı, 14:00" in block
        assert "(3 results)" in block
        assert "[tool: calendar.list_events]" in block

    def test_prompt_block_with_pending(self):
        from bantz.brain.memory_trace import EnhancedSummary
        s = EnhancedSummary(
            turn_number=3,
            user_intent="requested deletion",
            action_taken="asked for confirmation",
            pending_items=["waiting for user confirmation"],
        )
        block = s.to_prompt_block()
        assert "Pending:" in block
        assert "waiting for user confirmation" in block

    def test_empty_entities_no_key_data(self):
        from bantz.brain.memory_trace import EnhancedSummary
        s = EnhancedSummary(turn_number=1, user_intent="greeted", action_taken="greeted back")
        block = s.to_prompt_block()
        assert "Key data" not in block


# ═══════════════════════════════════════════════════════════════
# MemoryTracer
# ═══════════════════════════════════════════════════════════════

class TestMemoryTracer:
    def test_full_lifecycle(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()

        tracer.begin_turn(1)
        tracer.record_injection("Turn 1: User greeted", turns_count=1)
        rec = tracer.end_turn()

        assert rec is not None
        assert rec.turn_number == 1
        assert rec.memory_injected is True
        assert rec.memory_tokens > 0
        assert rec.was_trimmed is False

    def test_no_injection_empty_text(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        tracer.begin_turn(1)
        tracer.record_injection("", turns_count=0)
        rec = tracer.end_turn()
        assert rec.memory_injected is False
        assert rec.memory_tokens == 0

    def test_whitespace_only_not_injected(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        tracer.begin_turn(1)
        tracer.record_injection("   ", turns_count=0)
        rec = tracer.end_turn()
        assert rec.memory_injected is False

    def test_trim_recording(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        tracer.begin_turn(1)
        tracer.record_injection("some text", turns_count=1)
        tracer.record_trim(original_tokens=450, after_tokens=0, reason="token_budget")
        rec = tracer.end_turn()
        assert rec.was_trimmed is True
        assert rec.original_tokens == 450
        assert rec.after_trim_tokens == 0
        assert rec.trim_reason == "token_budget"

    def test_multiple_turns(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()

        for i in range(1, 4):
            tracer.begin_turn(i)
            tracer.record_injection(f"Turn {i} summary text here", turns_count=i)
            tracer.end_turn()

        assert len(tracer.records) == 3
        assert tracer.last.turn_number == 3

    def test_custom_token_estimator(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        tracer.begin_turn(1)
        tracer.record_injection("hello world", turns_count=1, token_estimator=lambda s: 42)
        rec = tracer.end_turn()
        assert rec.memory_tokens == 42

    def test_clear(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        tracer.begin_turn(1)
        tracer.record_injection("text", turns_count=1)
        tracer.end_turn()
        assert len(tracer.records) == 1

        tracer.clear()
        assert len(tracer.records) == 0
        assert tracer.last is None

    def test_begin_turn_without_end_discards(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        tracer.begin_turn(1)
        tracer.record_injection("text", turns_count=1)
        # Don't call end_turn — start new turn
        tracer.begin_turn(2)
        tracer.record_injection("text2", turns_count=2)
        rec = tracer.end_turn()
        # Only turn 2 is finalized; turn 1 was overwritten
        assert rec.turn_number == 2
        # Only 1 record (turn 2), turn 1 was never ended
        assert len(tracer.records) == 1

    def test_record_without_begin_is_noop(self):
        from bantz.brain.memory_trace import MemoryTracer
        tracer = MemoryTracer()
        # No begin_turn called
        tracer.record_injection("text", turns_count=1)
        tracer.record_trim(100, 50)
        rec = tracer.end_turn()
        assert rec is None
        assert len(tracer.records) == 0

    def test_budget_config_passthrough(self):
        from bantz.brain.memory_trace import MemoryBudgetConfig, MemoryTracer
        cfg = MemoryBudgetConfig(max_tokens=1200, max_turns=20, pii_filter=False)
        tracer = MemoryTracer(budget=cfg)
        assert tracer.budget.max_tokens == 1200
        assert tracer.budget.max_turns == 20


# ═══════════════════════════════════════════════════════════════
# 2-Turn Anaphora Golden Test
# ═══════════════════════════════════════════════════════════════

class TestTwoTurnAnaphoraGolden:
    """Golden test: 'yarın toplantılarım ne?' → 'ilkini iptal et'.

    Simulates 2-turn memory flow where the second turn references
    the first turn's results via anaphora ('ilkini' = the first one).

    This validates that:
    1. EnhancedSummary preserves key entities from turn 1
    2. MemoryTracer records injection of turn 1 context into turn 2
    3. The memory prompt block contains enough context for the
       3B router to resolve 'ilkini' → first event from turn 1
    """

    def test_two_turn_anaphora_flow(self):
        """End-to-end: turn1 list events → turn2 'ilkini iptal et'."""
        from bantz.brain.memory_trace import (
            EnhancedSummary,
            MemoryBudgetConfig,
            MemoryTracer,
        )

        budget = MemoryBudgetConfig(max_tokens=800, max_turns=10)
        tracer = MemoryTracer(budget=budget)

        # ── Turn 1: "yarın toplantılarım ne?" ────────────────────
        tracer.begin_turn(1)

        # Simulate: no prior memory (first turn)
        tracer.record_injection("", turns_count=0)

        turn1_summary = EnhancedSummary(
            turn_number=1,
            user_intent="asked about tomorrow's meetings",
            action_taken="listed calendar events",
            key_entities=["Proje Toplantısı 10:00", "Öğle Yemeği 12:30", "1:1 Ali 15:00"],
            result_count=3,
            tool_used="calendar.list_events",
        )
        rec1 = tracer.end_turn()
        assert rec1.memory_injected is False  # First turn: no prior memory

        # ── Turn 2: "ilkini iptal et" ────────────────────────────
        tracer.begin_turn(2)

        # Now memory includes turn 1 summary
        memory_text = turn1_summary.to_prompt_block()
        tracer.record_injection(memory_text, turns_count=1)

        rec2 = tracer.end_turn()
        assert rec2.memory_injected is True
        assert rec2.memory_tokens > 0
        assert rec2.memory_turns_count == 1

        # Verify the memory prompt block contains enough context
        # for the 3B router to resolve "ilkini"
        assert "Proje Toplantısı 10:00" in memory_text
        assert "Öğle Yemeği 12:30" in memory_text
        assert "1:1 Ali 15:00" in memory_text
        assert "3 results" in memory_text
        assert "calendar.list_events" in memory_text

        # The trace should show 2 records
        assert len(tracer.records) == 2

    def test_anaphora_memory_block_format(self):
        """Verify memory block is suitable for DIALOG_SUMMARY injection."""
        from bantz.brain.memory_trace import EnhancedSummary

        summary = EnhancedSummary(
            turn_number=1,
            user_intent="asked about tomorrow's meetings",
            action_taken="listed calendar events",
            key_entities=["Standup 09:00", "Design Review 14:00"],
            result_count=2,
            tool_used="calendar.list_events",
        )
        block = summary.to_prompt_block()

        # Must contain structured data the 3B router can parse
        assert "Turn 1" in block
        assert "Standup 09:00" in block
        assert "Design Review 14:00" in block
        assert "(2 results)" in block

    def test_anaphora_with_trim_warning(self):
        """When memory is trimmed, trace records the warning."""
        from bantz.brain.memory_trace import MemoryTracer

        tracer = MemoryTracer()

        # Turn 1
        tracer.begin_turn(1)
        tracer.record_injection("", turns_count=0)
        tracer.end_turn()

        # Turn 2 — memory was too large, got trimmed
        tracer.begin_turn(2)
        tracer.record_injection("trimmed text", turns_count=1)
        tracer.record_trim(original_tokens=450, after_tokens=200, reason="token_budget")
        rec = tracer.end_turn()

        assert rec.was_trimmed is True
        line = rec.to_trace_line()
        assert "TRIMMED" in line
        assert "original=450" in line
        assert "after=200" in line

    def test_memory_budget_increase_800(self):
        """Issue #521: Budget default increased from 500 → 800 tokens."""
        from bantz.brain.memory_trace import MemoryBudgetConfig
        cfg = MemoryBudgetConfig()
        assert cfg.max_tokens == 800, "Default budget should be 800 (increased from 500)"
