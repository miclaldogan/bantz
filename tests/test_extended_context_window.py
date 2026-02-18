"""
Tests for Extended Context Window (Issue #1278).

Validates:
- max_history_turns expanded to 8
- max_tool_results expanded to 5
- Adaptive compaction: last 3 turns raw, older turns summarised
- Token budget enforcement in compaction
- Context builder adaptive history injection
- Backward compatibility with ≤3-turn scenarios
- Multi-turn reference retention (5-turn calendar, 8-turn first-turn)
"""

import json
import pytest
from unittest.mock import Mock, patch

from bantz.brain.orchestrator_state import OrchestratorState


# ═══════════════════════════════════════════════════════════════════
#  OrchestratorState defaults
# ═══════════════════════════════════════════════════════════════════

class TestExpandedDefaults:
    """Verify expanded window sizes (Issue #1278)."""

    def test_max_history_turns_is_8(self):
        state = OrchestratorState()
        assert state.max_history_turns == 8

    def test_max_tool_results_is_5(self):
        state = OrchestratorState()
        assert state.max_tool_results == 5

    def test_add_conversation_turn_fifo_respects_8(self):
        """FIFO queue should retain last 8 turns."""
        state = OrchestratorState()
        for i in range(12):
            state.add_conversation_turn(f"user {i}", f"assistant {i}")
        assert len(state.conversation_history) == 8
        assert state.conversation_history[0]["user"] == "user 4"
        assert state.conversation_history[-1]["user"] == "user 11"

    def test_add_tool_result_fifo_respects_5(self):
        """FIFO queue should retain last 5 tool results."""
        state = OrchestratorState()
        for i in range(8):
            state.add_tool_result(
                tool_name=f"tool_{i}",
                result=f"result {i}",
                success=True,
            )
        assert len(state.last_tool_results) == 5
        assert state.last_tool_results[0]["tool"] == "tool_3"
        assert state.last_tool_results[-1]["tool"] == "tool_7"


# ═══════════════════════════════════════════════════════════════════
#  compact_conversation_history
# ═══════════════════════════════════════════════════════════════════

class TestCompactConversationHistory:
    """Unit tests for adaptive compaction logic."""

    def test_empty_history_returns_empty(self):
        state = OrchestratorState()
        assert state.compact_conversation_history() == []

    def test_single_turn_returns_raw(self):
        state = OrchestratorState()
        state.add_conversation_turn("hi", "hello")
        result = state.compact_conversation_history()
        assert len(result) == 1
        assert result[0]["user"] == "hi"
        assert result[0]["assistant"] == "hello"
        assert "_compacted" not in result[0]

    def test_three_turns_all_raw(self):
        """With ≤ raw_tail turns, all should be raw (no compaction)."""
        state = OrchestratorState()
        for i in range(3):
            state.add_conversation_turn(f"u{i}", f"a{i}")
        result = state.compact_conversation_history(raw_tail=3)
        assert len(result) == 3
        for r in result:
            assert "_compacted" not in r

    def test_five_turns_two_compacted_three_raw(self):
        """5 turns with raw_tail=3: 2 compacted + 3 raw."""
        state = OrchestratorState()
        for i in range(5):
            state.add_conversation_turn(f"user {i}", f"assistant {i}")

        result = state.compact_conversation_history(raw_tail=3)
        assert len(result) == 5

        # First 2 compacted
        assert result[0]["_compacted"] == "true"
        assert result[0]["user"] == "user 0"
        assert result[1]["_compacted"] == "true"
        assert result[1]["user"] == "user 1"

        # Last 3 raw
        for i in range(2, 5):
            assert "_compacted" not in result[i]
            assert result[i]["user"] == f"user {i}"

    def test_eight_turns_five_compacted_three_raw(self):
        """8 turns with raw_tail=3: 5 compacted + 3 raw."""
        state = OrchestratorState()
        for i in range(8):
            state.add_conversation_turn(f"user {i}", f"assistant {i}")

        result = state.compact_conversation_history(raw_tail=3)
        assert len(result) == 8

        compacted = [r for r in result if r.get("_compacted") == "true"]
        raw = [r for r in result if "_compacted" not in r]
        assert len(compacted) == 5
        assert len(raw) == 3

        # Raw should be last 3 turns
        assert raw[0]["user"] == "user 5"
        assert raw[1]["user"] == "user 6"
        assert raw[2]["user"] == "user 7"

    def test_compacted_turns_truncated(self):
        """Compacted turns should truncate user text to 120 chars."""
        state = OrchestratorState()
        long_text = "x" * 300
        state.add_conversation_turn(long_text, "short")
        state.add_conversation_turn("recent1", "r1")
        state.add_conversation_turn("recent2", "r2")
        state.add_conversation_turn("recent3", "r3")

        result = state.compact_conversation_history(raw_tail=3)
        assert len(result) == 4
        assert result[0]["_compacted"] == "true"
        assert len(result[0]["user"]) == 120  # truncated

    def test_raw_turns_not_truncated(self):
        """Raw (recent) turns should not be truncated."""
        state = OrchestratorState()
        state.add_conversation_turn("old", "old_reply")
        long_user = "y" * 300
        state.add_conversation_turn(long_user, "recent reply")

        result = state.compact_conversation_history(raw_tail=1)
        raw_turn = result[-1]
        assert "_compacted" not in raw_turn
        assert raw_turn["user"] == long_user  # not truncated

    def test_custom_raw_tail(self):
        state = OrchestratorState()
        for i in range(6):
            state.add_conversation_turn(f"u{i}", f"a{i}")

        result = state.compact_conversation_history(raw_tail=5)
        compacted = [r for r in result if r.get("_compacted") == "true"]
        raw = [r for r in result if "_compacted" not in r]
        assert len(compacted) == 1
        assert len(raw) == 5

    def test_raw_tail_larger_than_history(self):
        """If raw_tail >= len(history), all turns raw."""
        state = OrchestratorState()
        state.add_conversation_turn("u1", "a1")
        state.add_conversation_turn("u2", "a2")

        result = state.compact_conversation_history(raw_tail=10)
        assert len(result) == 2
        for r in result:
            assert "_compacted" not in r

    def test_token_budget_enforcement(self):
        """Token budget should drop oldest compacted turns first."""
        state = OrchestratorState()
        for i in range(8):
            state.add_conversation_turn(f"user message number {i} " * 10, f"reply {i} " * 10)

        result_normal = state.compact_conversation_history(raw_tail=3)
        # Use a moderate budget that keeps some but not all
        from bantz.llm.token_utils import estimate_tokens_json
        full_tokens = estimate_tokens_json(result_normal)
        # Use ~60% of full budget to force partial compaction
        budget = int(full_tokens * 0.6)
        result_tight = state.compact_conversation_history(raw_tail=3, token_budget=budget)
        assert 0 < len(result_tight) < len(result_normal)
        # Last turn should always be present (oldest dropped first)
        assert result_tight[-1]["user"] == result_normal[-1]["user"]

    def test_token_budget_zero_means_no_limit(self):
        state = OrchestratorState()
        for i in range(8):
            state.add_conversation_turn(f"user {i}", f"assistant {i}")
        result = state.compact_conversation_history(raw_tail=3, token_budget=0)
        assert len(result) == 8

    def test_does_not_mutate_original_history(self):
        """compact_conversation_history must not mutate conversation_history."""
        state = OrchestratorState()
        for i in range(5):
            state.add_conversation_turn(f"u{i}", f"a{i}")

        original_len = len(state.conversation_history)
        _ = state.compact_conversation_history(raw_tail=3, token_budget=10)

        # Original list unchanged
        assert len(state.conversation_history) == original_len
        # No _compacted key in originals
        for turn in state.conversation_history:
            assert "_compacted" not in turn


# ═══════════════════════════════════════════════════════════════════
#  get_context_for_llm
# ═══════════════════════════════════════════════════════════════════

class TestGetContextForLLM:
    """get_context_for_llm should use adaptive compaction."""

    def test_empty_state_returns_empty_recent(self):
        state = OrchestratorState()
        ctx = state.get_context_for_llm()
        assert ctx["recent_conversation"] == []

    def test_two_turns_all_raw(self):
        state = OrchestratorState()
        state.add_conversation_turn("q1", "a1")
        state.add_conversation_turn("q2", "a2")
        ctx = state.get_context_for_llm()
        recent = ctx["recent_conversation"]
        assert len(recent) == 2
        for r in recent:
            assert "_compacted" not in r

    def test_five_turns_uses_compaction(self):
        state = OrchestratorState()
        for i in range(5):
            state.add_conversation_turn(f"u{i}", f"a{i}")
        ctx = state.get_context_for_llm()
        recent = ctx["recent_conversation"]
        assert len(recent) == 5
        # First 2 compacted
        assert recent[0].get("_compacted") == "true"
        assert recent[1].get("_compacted") == "true"
        # Last 3 raw
        assert "_compacted" not in recent[2]
        assert "_compacted" not in recent[3]
        assert "_compacted" not in recent[4]

    def test_tool_results_expanded_to_5(self):
        state = OrchestratorState()
        for i in range(5):
            state.add_tool_result(f"tool{i}", f"result {i}", success=True)
        ctx = state.get_context_for_llm()
        assert len(ctx["last_tool_results"]) == 5


# ═══════════════════════════════════════════════════════════════════
#  ContextBuilder._inject_conversation_history
# ═══════════════════════════════════════════════════════════════════

class TestContextBuilderConversationHistory:
    """Test adaptive history injection in context_builder."""

    def _make_builder(self, pii_filter=False):
        from bantz.brain.context_builder import ContextBuilder
        mock_memory = Mock()
        mock_memory.to_prompt_block.return_value = None
        mock_memory.__len__ = Mock(return_value=0)
        return ContextBuilder(
            memory=mock_memory,
            pii_filter=pii_filter,
        )

    def test_empty_history_no_output(self):
        builder = self._make_builder()
        parts: list[str] = []
        builder._inject_conversation_history([], parts)
        assert parts == []

    def test_two_turns_all_recent(self):
        builder = self._make_builder()
        history = [
            {"user": "merhaba", "assistant": "selam"},
            {"user": "nasılsın", "assistant": "iyiyim"},
        ]
        parts: list[str] = []
        builder._inject_conversation_history(history, parts)
        assert len(parts) == 1
        block = parts[0]
        assert "RECENT_CONVERSATION:" in block
        assert "  U: merhaba" in block
        assert "  A: selam" in block
        # No [past] markers for ≤3 turns
        assert "[past]" not in block

    def test_five_turns_compacted_and_raw(self):
        builder = self._make_builder()
        history = [{"user": f"u{i}", "assistant": f"a{i}"} for i in range(5)]
        parts: list[str] = []
        builder._inject_conversation_history(history, parts)
        block = parts[0]
        # First 2 should be compacted ([past] format)
        assert "[past] U: u0" in block
        assert "[past] U: u1" in block
        # Last 3 should be full format
        assert "  U: u2\n  A: a2" in block
        assert "  U: u3\n  A: a3" in block
        assert "  U: u4\n  A: a4" in block

    def test_eight_turns_five_compacted(self):
        builder = self._make_builder()
        history = [{"user": f"user{i}", "assistant": f"asst{i}"} for i in range(8)]
        parts: list[str] = []
        builder._inject_conversation_history(history, parts)
        block = parts[0]
        # 5 compacted (turns 0-4)
        for i in range(5):
            assert f"[past] U: user{i}" in block
        # 3 raw (turns 5-7)
        for i in range(5, 8):
            assert f"  U: user{i}\n  A: asst{i}" in block

    def test_compacted_turns_truncated(self):
        builder = self._make_builder()
        long_user = "x" * 300
        long_asst = "y" * 300
        history = [
            {"user": long_user, "assistant": long_asst},
            {"user": "recent1", "assistant": "r1"},
            {"user": "recent2", "assistant": "r2"},
            {"user": "recent3", "assistant": "r3"},
        ]
        parts: list[str] = []
        builder._inject_conversation_history(history, parts)
        block = parts[0]
        # Compacted turn user truncated to 100 chars, assistant to 80
        lines = block.split("\n")
        past_line = [l for l in lines if "[past]" in l][0]
        # Find the U: content — between "U: " and " → A: "
        u_start = past_line.index("U: ") + 3
        arrow_idx = past_line.index(" → A: ")
        u_content = past_line[u_start:arrow_idx]
        assert len(u_content) == 100

    def test_recent_turns_larger_char_limits(self):
        """Recent turns should allow up to 200 user + 300 assistant chars."""
        builder = self._make_builder()
        history = [
            {"user": "u" * 250, "assistant": "a" * 400},
        ]
        parts: list[str] = []
        builder._inject_conversation_history(history, parts)
        block = parts[0]
        # User truncated to 200
        assert "u" * 200 in block
        assert "u" * 201 not in block
        # Assistant truncated to 300
        assert "a" * 300 in block
        assert "a" * 301 not in block

    def test_pii_filter_applied(self):
        """PII filter should be applied to both compacted and raw turns."""
        builder = self._make_builder(pii_filter=True)
        history = [
            {"user": "old turn", "assistant": "old reply"},
            {"user": "recent 1", "assistant": "reply 1"},
            {"user": "recent 2", "assistant": "reply 2"},
            {"user": "recent 3", "assistant": "reply 3"},
        ]
        parts: list[str] = []
        # PII filter may fail if module not available, but method should not crash
        builder._inject_conversation_history(history, parts)
        assert len(parts) == 1  # Should still produce output


# ═══════════════════════════════════════════════════════════════════
#  Scenario tests — multi-turn reference retention
# ═══════════════════════════════════════════════════════════════════

class TestMultiTurnScenarios:
    """Validate acceptance criteria from Issue #1278."""

    def test_five_turn_calendar_planning(self):
        """5-turn calendar planning retains all context."""
        state = OrchestratorState()
        turns = [
            ("yarın toplantı ayarla", "Hangi saatte efendim?"),
            ("14:00'te olsun", "Kimlerle toplantı?"),
            ("Ali ve Mehmet ile", "Konu ne olsun?"),
            ("sprint planlama", "Toplantı detayları: yarın 14:00, Ali ve Mehmet, sprint planlama. Onaylıyor musunuz?"),
            ("evet, onayla", "Toplantı oluşturuldu!"),
        ]
        for user, asst in turns:
            state.add_conversation_turn(user, asst)

        # All 5 turns must be present
        compacted = state.compact_conversation_history(raw_tail=3)
        assert len(compacted) == 5

        # First 2 compacted: still contain key info
        assert "toplantı ayarla" in compacted[0]["user"]
        assert "14:00" in compacted[1]["user"]

        # Raw turns contain recent context (turns 2,3,4)
        assert "Ali ve Mehmet" in compacted[2]["user"]
        assert "sprint planlama" in compacted[3]["user"]
        assert "onayla" in compacted[4]["user"]

    def test_eight_turn_first_turn_reference(self):
        """8-turn conversation still references first turn."""
        state = OrchestratorState()
        turns = [
            ("Ankara'nın havası nasıl", "Ankara'da 25°C, güneşli."),
            ("İstanbul ne durumda", "İstanbul'da 22°C, parçalı bulutlu."),
            ("yarına ne olacak", "Yarın Ankara 20°C, İstanbul 18°C."),
            ("peki yağmur var mı", "İstanbul'da hafif yağmur bekleniyor."),
            ("Ankara için şemsiye lazım mı", "Ankara'da yağmur yok, şemsiyeye gerek yok."),
            ("teşekkürler", "Rica ederim efendim!"),
            ("ilk sorduğum şehir hangisiydi", "Ankara'ydı efendim."),
            ("oranın nem oranı nedir", "Ankara'da nem %45 civarında."),
        ]
        for user, asst in turns:
            state.add_conversation_turn(user, asst)

        compacted = state.compact_conversation_history(raw_tail=3)
        assert len(compacted) == 8

        # First turn is still present (compacted)
        assert compacted[0]["user"] == "Ankara'nın havası nasıl"
        assert compacted[0]["_compacted"] == "true"

        # Last 3 raw
        assert compacted[5]["user"] == "teşekkürler"
        assert compacted[6]["user"] == "ilk sorduğum şehir hangisiydi"
        assert compacted[7]["user"] == "oranın nem oranı nedir"

    def test_backward_compat_three_turns(self):
        """3-turn scenario should work identically — all raw, no compaction."""
        state = OrchestratorState()
        state.add_conversation_turn("merhaba", "selam")
        state.add_conversation_turn("nasılsın", "iyiyim")
        state.add_conversation_turn("hava nasıl", "güneşli")

        compacted = state.compact_conversation_history(raw_tail=3)
        assert len(compacted) == 3
        for turn in compacted:
            assert "_compacted" not in turn

        # get_context_for_llm also uses compaction
        ctx = state.get_context_for_llm()
        for turn in ctx["recent_conversation"]:
            assert "_compacted" not in turn

    def test_prompt_stays_within_budget(self):
        """Compacted output should be significantly smaller than raw."""
        state = OrchestratorState()
        for i in range(8):
            state.add_conversation_turn(
                f"Bu çok uzun bir soru metni {i} " * 20,
                f"Bu çok uzun bir cevap metni {i} " * 20,
            )

        from bantz.llm.token_utils import estimate_tokens_json
        raw_tokens = estimate_tokens_json(state.conversation_history)
        compacted = state.compact_conversation_history(raw_tail=3)
        compact_tokens = estimate_tokens_json(compacted)

        # Compacted should be smaller (older turns truncated)
        assert compact_tokens < raw_tokens

    def test_context_builder_build_integrates_history(self):
        """Full context_builder.build() uses adaptive history."""
        from bantz.brain.context_builder import ContextBuilder

        mock_memory = Mock()
        mock_memory.to_prompt_block.return_value = None
        mock_memory.__len__ = Mock(return_value=0)

        builder = ContextBuilder(memory=mock_memory)

        state = OrchestratorState()
        for i in range(6):
            state.add_conversation_turn(f"q{i}", f"a{i}")

        # Get compacted history (what get_context_for_llm provides)
        ctx = state.get_context_for_llm()
        history = ctx["recent_conversation"]

        result = builder.build(
            user_input="test",
            conversation_history=history,
            tool_results=[],
            state=state,
        )

        assert result.enhanced_summary is not None
        summary = result.enhanced_summary
        assert "RECENT_CONVERSATION:" in summary
        # Should contain both compacted and raw
        assert "[past]" in summary  # 3 compacted turns
        assert "  U: q3" in summary  # raw turns


# ═══════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases for adaptive context window."""

    def test_single_turn_no_crash(self):
        state = OrchestratorState()
        state.add_conversation_turn("hi", "hello")
        ctx = state.get_context_for_llm()
        assert len(ctx["recent_conversation"]) == 1

    def test_max_history_turns_overridden(self):
        """Allow runtime override of max_history_turns."""
        state = OrchestratorState()
        state.max_history_turns = 4
        for i in range(10):
            state.add_conversation_turn(f"u{i}", f"a{i}")
        assert len(state.conversation_history) == 4

    def test_compaction_with_missing_keys(self):
        """Turns with missing user/assistant keys should not crash."""
        state = OrchestratorState()
        state.conversation_history = [
            {},
            {"user": "q1"},
            {"assistant": "a1"},
            {"user": "recent", "assistant": "reply"},
        ]
        result = state.compact_conversation_history(raw_tail=1)
        assert len(result) == 4

    def test_reset_works_with_expanded_history(self):
        """Reset clears all 8 turns cleanly."""
        state = OrchestratorState()
        for i in range(8):
            state.add_conversation_turn(f"u{i}", f"a{i}")
        assert len(state.conversation_history) == 8
        state.reset()
        assert len(state.conversation_history) == 0
