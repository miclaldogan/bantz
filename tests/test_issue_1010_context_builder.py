"""Tests for ContextBuilder (Issue #1010).

Validates the extracted context-building logic behaves identically
to the inline version that was in orchestrator_loop._llm_planning_phase.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.context_builder import ContextBuilder, ContextBuildResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(prompt_block: str | None = None, length: int = 0):
    """Minimal DialogSummaryManager mock."""
    mem = MagicMock()
    mem.to_prompt_block.return_value = prompt_block
    mem.__len__ = MagicMock(return_value=length)
    mem.turn_count = length
    return mem


def _make_state():
    """Minimal OrchestratorState mock with trace + reference_table."""
    state = MagicMock()
    state.trace = {}
    state.reference_table = None
    return state


def _make_user_memory(facts=None, profile="", memories=None):
    um = MagicMock()
    um.on_turn_start.return_value = {
        "profile_context": profile,
        "facts": facts or {},
        "memories": memories or [],
    }
    return um


def _make_personality_injector(block="Jarvis personality block"):
    pi = MagicMock()
    pi.build_router_block.return_value = block
    pi.update_user_name = MagicMock()
    return pi


# ---------------------------------------------------------------------------
# Tests: Basic build
# ---------------------------------------------------------------------------

class TestContextBuilderBasic:
    """Basic ContextBuilder.build() smoke tests."""

    def test_empty_memory_returns_none(self):
        builder = ContextBuilder(memory=_make_memory(None))
        result = builder.build(
            user_input="merhaba",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert isinstance(result, ContextBuildResult)
        assert result.enhanced_summary is None
        assert result.dialog_summary is None

    def test_dialog_summary_included(self):
        builder = ContextBuilder(memory=_make_memory("Turn 1 summary"))
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert result.dialog_summary == "Turn 1 summary"
        assert "Turn 1 summary" in result.enhanced_summary

    def test_conversation_history_injected(self):
        builder = ContextBuilder(memory=_make_memory("mem"))
        history = [
            {"user": "merhaba", "assistant": "Merhaba!"},
            {"user": "saat kaç", "assistant": "14:30"},
        ]
        result = builder.build(
            user_input="test",
            conversation_history=history,
            tool_results=[],
            state=_make_state(),
        )
        assert "RECENT_CONVERSATION:" in result.enhanced_summary
        assert "U: merhaba" in result.enhanced_summary
        assert "A: 14:30" in result.enhanced_summary

    def test_tool_results_injected(self):
        builder = ContextBuilder(memory=_make_memory("mem"))
        tools = [
            {"tool": "calendar.list_events", "result_summary": "3 events found", "success": True},
        ]
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=tools,
            state=_make_state(),
        )
        assert "LAST_TOOL_RESULTS:" in result.enhanced_summary
        assert "calendar.list_events (ok)" in result.enhanced_summary

    def test_failed_tool_status(self):
        builder = ContextBuilder(memory=_make_memory("mem"))
        tools = [
            {"tool": "gmail.send", "result_summary": "auth error", "success": False},
        ]
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=tools,
            state=_make_state(),
        )
        assert "gmail.send (fail)" in result.enhanced_summary

    def test_returns_context_build_result_type(self):
        builder = ContextBuilder(memory=_make_memory("mem"))
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert isinstance(result, ContextBuildResult)
        assert result.enhanced_summary is not None


# ---------------------------------------------------------------------------
# Tests: User profile + personality
# ---------------------------------------------------------------------------

class TestContextBuilderProfile:
    """User profile and personality injection."""

    def test_user_profile_injected(self):
        um = _make_user_memory(
            profile="Name: Ali, Preference: formal",
            facts={"name": "Ali"},
        )
        builder = ContextBuilder(
            memory=_make_memory("mem"),
            user_memory=um,
        )
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert "USER_PROFILE:" in result.enhanced_summary
        assert "Ali" in result.enhanced_summary

    def test_user_profile_skipped_for_smalltalk(self):
        um = _make_user_memory(profile="Name: Ali")
        builder = ContextBuilder(
            memory=_make_memory("mem"),
            user_memory=um,
        )
        result = builder.build(
            user_input="merhaba",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
            is_smalltalk=True,
        )
        um.on_turn_start.assert_not_called()
        assert "USER_PROFILE:" not in (result.enhanced_summary or "")

    def test_personality_block_injected(self):
        pi = _make_personality_injector("I am Jarvis")
        builder = ContextBuilder(
            memory=_make_memory("mem"),
            personality_injector=pi,
        )
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert "PERSONALITY:" in result.enhanced_summary
        assert "I am Jarvis" in result.enhanced_summary

    def test_personality_block_cached(self):
        pi = _make_personality_injector("Jarvis")
        builder = ContextBuilder(
            memory=_make_memory("mem"),
            personality_injector=pi,
        )
        # First call builds
        builder.build(
            user_input="t1",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        # Second call uses cache
        builder.build(
            user_input="t2",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert pi.build_router_block.call_count == 1

    def test_long_term_memory_snippets(self):
        um = _make_user_memory(
            memories=["Ali likes coffee", "Prefers morning meetings"],
        )
        builder = ContextBuilder(
            memory=_make_memory("mem"),
            user_memory=um,
        )
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert "LONG_TERM_MEMORY:" in result.enhanced_summary
        assert "Ali likes coffee" in result.enhanced_summary

    def test_personality_injector_receives_user_name(self):
        pi = _make_personality_injector("Block")
        um = _make_user_memory(facts={"name": "Mehmet"})
        builder = ContextBuilder(
            memory=_make_memory("mem"),
            user_memory=um,
            personality_injector=pi,
        )
        builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        pi.update_user_name.assert_called_once_with("Mehmet")


# ---------------------------------------------------------------------------
# Tests: PII redaction
# ---------------------------------------------------------------------------

class TestContextBuilderPII:
    """PII filtering and caching."""

    @patch("bantz.brain.context_builder.logger")
    def test_pii_filter_applied_to_dialog_summary(self, _mock_logger):
        with patch(
            "bantz.privacy.redaction.redact_pii",
            side_effect=lambda s: s.replace("Ali", "[REDACTED]"),
        ):
            builder = ContextBuilder(
                memory=_make_memory("Ali said hello"),
                pii_filter=True,
            )
            result = builder.build(
                user_input="test",
                conversation_history=[],
                tool_results=[],
                state=_make_state(),
            )
            assert "[REDACTED]" in result.dialog_summary
            assert "Ali" not in result.dialog_summary

    @patch("bantz.brain.context_builder.logger")
    def test_pii_cache_hit(self, _mock_logger):
        with patch(
            "bantz.privacy.redaction.redact_pii",
            side_effect=lambda s: s.replace("Ali", "[R]"),
        ) as mock_redact:
            mem = _make_memory("Ali said hello")
            builder = ContextBuilder(memory=mem, pii_filter=True)

            # First build — redaction called
            builder.build(
                user_input="t1",
                conversation_history=[],
                tool_results=[],
                state=_make_state(),
            )
            assert mock_redact.call_count >= 1
            first_count = mock_redact.call_count

            # Second build with same summary — cache hit, no extra call
            builder.build(
                user_input="t2",
                conversation_history=[],
                tool_results=[],
                state=_make_state(),
            )
            # Only conversation_history / tool_results may call redact, not dialog_summary
            # The dialog_summary redact should be cached
            assert mock_redact.call_count == first_count

    def test_pii_filter_applied_to_conversation_history(self):
        with patch(
            "bantz.privacy.redaction.redact_pii",
            side_effect=lambda s: s.replace("secret", "[R]"),
        ):
            builder = ContextBuilder(
                memory=_make_memory("mem"),
                pii_filter=True,
            )
            result = builder.build(
                user_input="test",
                conversation_history=[
                    {"user": "my secret number", "assistant": "ok secret"}
                ],
                tool_results=[],
                state=_make_state(),
            )
            assert "secret" not in result.enhanced_summary
            assert "[R]" in result.enhanced_summary


# ---------------------------------------------------------------------------
# Tests: Token budget trimming
# ---------------------------------------------------------------------------

class TestContextBuilderTokenBudget:
    """Token budget enforcement for dialog summary."""

    def test_long_summary_trimmed(self):
        # Create a very long summary (>1000 tokens ≈ 4000 chars)
        long_summary = "x" * 8000
        builder = ContextBuilder(
            memory=_make_memory(long_summary),
            memory_max_tokens=500,
        )
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        # Should be trimmed to ~500*4=2000 chars
        assert len(result.dialog_summary) <= 2100

    def test_short_summary_not_trimmed(self):
        short_summary = "short dialog"
        builder = ContextBuilder(
            memory=_make_memory(short_summary),
            memory_max_tokens=1000,
        )
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
        )
        assert result.dialog_summary == short_summary


# ---------------------------------------------------------------------------
# Tests: Memory tracer integration
# ---------------------------------------------------------------------------

class TestContextBuilderTracer:
    """Memory tracer lifecycle (begin_turn, record_trim, record_injection)."""

    def test_tracer_begin_turn_called(self):
        tracer = MagicMock()
        tracer.budget = MagicMock()
        tracer.budget.max_tokens = 1000
        mem = _make_memory("summary", length=3)
        builder = ContextBuilder(memory=mem)
        builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
            memory_tracer=tracer,
        )
        tracer.begin_turn.assert_called_once()

    def test_tracer_record_injection_called(self):
        tracer = MagicMock()
        tracer.budget = MagicMock()
        tracer.budget.max_tokens = 1000
        builder = ContextBuilder(memory=_make_memory("summary"))
        builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
            memory_tracer=tracer,
        )
        tracer.record_injection.assert_called_once()

    def test_tracer_record_trim_called_on_overflow(self):
        tracer = MagicMock()
        tracer.budget = MagicMock()
        tracer.budget.max_tokens = 10  # Very small budget
        builder = ContextBuilder(
            memory=_make_memory("x" * 1000),
            memory_max_tokens=10,
        )
        builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=_make_state(),
            memory_tracer=tracer,
        )
        tracer.record_trim.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Anaphora reference table
# ---------------------------------------------------------------------------

class TestContextBuilderAnaphora:
    """REFERENCE_TABLE injection for anaphora resolution."""

    def test_reference_table_injected(self):
        mock_table = MagicMock()
        mock_table.to_prompt_block.return_value = "REFERENCE_TABLE:\n#1: Event A"

        with patch(
            "bantz.brain.anaphora.ReferenceTable",
        ) as MockRT:
            MockRT.from_tool_results.return_value = mock_table

            builder = ContextBuilder(memory=_make_memory("mem"))
            state = _make_state()
            result = builder.build(
                user_input="test",
                conversation_history=[],
                tool_results=[{"tool": "cal", "result_summary": "ok"}],
                state=state,
            )
            assert "REFERENCE_TABLE:" in result.enhanced_summary
            assert state.reference_table is mock_table

    def test_no_reference_table_without_tool_results(self):
        builder = ContextBuilder(memory=_make_memory("mem"))
        state = _make_state()
        result = builder.build(
            user_input="test",
            conversation_history=[],
            tool_results=[],
            state=state,
        )
        assert state.reference_table is None


# ---------------------------------------------------------------------------
# Tests: Full integration (all sources combined)
# ---------------------------------------------------------------------------

class TestContextBuilderIntegration:
    """Full build with all sources active."""

    def test_all_sections_present(self):
        mock_table = MagicMock()
        mock_table.to_prompt_block.return_value = "REFERENCE_TABLE:\n#1: test"

        with patch(
            "bantz.brain.anaphora.ReferenceTable"
        ) as MockRT:
            MockRT.from_tool_results.return_value = mock_table

            builder = ContextBuilder(
                memory=_make_memory("Dialog block"),
                user_memory=_make_user_memory(
                    profile="Name: Ali",
                    facts={"name": "Ali"},
                    memories=["Likes tea"],
                ),
                personality_injector=_make_personality_injector("Jarvis style"),
            )
            result = builder.build(
                user_input="saat kaç",
                conversation_history=[
                    {"user": "merhaba", "assistant": "Selam!"},
                ],
                tool_results=[
                    {"tool": "time.now", "result_summary": "14:30", "success": True},
                ],
                state=_make_state(),
            )

            summary = result.enhanced_summary
            assert "Dialog block" in summary
            assert "USER_PROFILE:" in summary
            assert "LONG_TERM_MEMORY:" in summary
            assert "PERSONALITY:" in summary
            assert "RECENT_CONVERSATION:" in summary
            assert "LAST_TOOL_RESULTS:" in summary
            assert "REFERENCE_TABLE:" in summary

    def test_sections_separated_by_double_newline(self):
        builder = ContextBuilder(
            memory=_make_memory("Dialog block"),
            personality_injector=_make_personality_injector("Jarvis"),
        )
        result = builder.build(
            user_input="test",
            conversation_history=[
                {"user": "hi", "assistant": "hello"},
            ],
            tool_results=[],
            state=_make_state(),
        )
        # Each section separated by \n\n
        parts = result.enhanced_summary.split("\n\n")
        assert len(parts) >= 3  # dialog + personality + conversation
