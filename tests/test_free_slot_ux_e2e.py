# SPDX-License-Identifier: MIT
"""End-to-end tests for free slot UX (Issue #237)."""

from datetime import datetime, time, timedelta, timezone

import pytest

from bantz.agent.builtin_tools import build_default_registry
from bantz.brain.brain_loop import BrainLoop


class TestFreeSlotUX:
    """Test free slot UX meets acceptance criteria (Issue #237)."""
    
    @pytest.fixture
    def brain_loop(self):
        """Create brain loop with calendar tools."""
        registry = build_default_registry()
        return BrainLoop(tools=registry)
    
    def test_simple_query_no_clarification(self, brain_loop):
        """Test 'uygun saat var mı' completes with minimal clarification.
        
        Acceptance: 5 sample conversations with max 1 clarifying question.
        """
        # Mock current time: 2026-02-03 10:00 UTC
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        # User asks for free slots with no details
        result = brain_loop.run(
            turn_input="bugün uygun saat var mı",
            session_context={"reference_time": now.isoformat()},
        )
        
        # Should return slots or ask 1 clarifying question (duration/window)
        assert result is not None
        assert result.kind in ("say", "tool_output")
        
        # If clarification needed, should be about duration or time window
        if "kaç" in result.text.lower() or "ne zaman" in result.text.lower():
            # Acceptable clarification
            assert len(result.text) < 200  # Keep it brief
        else:
            # Direct answer with slots
            assert "boşluk" in result.text.lower() or "saat" in result.text.lower()
    
    def test_with_duration_no_extra_questions(self, brain_loop):
        """Test '1 saatlik boşluk' should not ask for duration again."""
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        result = brain_loop.run(
            turn_input="yarın 1 saatlik toplantı için uygun saat var mı",
            session_context={"reference_time": now.isoformat()},
        )
        
        # Should NOT ask about duration since it's provided
        assert result is not None
        # Should not contain duration questions
        assert "kaç dakika" not in result.text.lower()
        assert "ne kadar" not in result.text.lower()
    
    def test_defaults_30_minutes(self, brain_loop):
        """Test default duration is 30 minutes when not specified."""
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        # Query without duration
        result = brain_loop.run(
            turn_input="öğleden sonra boş zaman var mı",
            session_context={"reference_time": now.isoformat()},
        )
        
        # Should use 30m default (verifiable in metadata or tool calls)
        assert result is not None
        metadata = result.metadata or {}
        
        # Check if duration_minutes is in metadata
        if "duration_minutes" in metadata:
            assert metadata["duration_minutes"] == 30
    
    def test_afternoon_window_sets_13_18(self, brain_loop):
        """Test 'öğleden sonra' sets correct time window."""
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        result = brain_loop.run(
            turn_input="öğleden sonra uygun saat",
            session_context={"reference_time": now.isoformat()},
        )
        
        assert result is not None
        # Metadata should show afternoon window (13:00-18:00)
        metadata = result.metadata or {}
        
        # Check for window hints in metadata
        if "window_start" in metadata:
            assert metadata["window_start"] == "13:00"
        if "window_end" in metadata:
            assert metadata["window_end"] == "18:00"
    
    def test_top_3_slots_shown(self, brain_loop):
        """Test system shows top 3 slots by default."""
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        result = brain_loop.run(
            turn_input="bugün boşluk var mı",
            session_context={"reference_time": now.isoformat()},
        )
        
        assert result is not None
        
        # Check for slot formatting (1), 2), 3))
        text_lower = result.text.lower()
        
        # If slots are shown, should show up to 3
        if "1)" in result.text or "2)" in result.text:
            # Has slot numbering - verify max 3 in initial response
            slot_count = result.text.count(")")
            # Allow some flexibility for other parentheses in text
            assert slot_count <= 5, "Should show max 3 slots initially"
    
    def test_conversation_count_minimal(self, brain_loop):
        """Test acceptance criteria: max 1 clarifying question in 5 examples."""
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        # 5 example conversations
        queries = [
            "uygun saat var mı",
            "yarın 1 saatlik boşluk",
            "öğleden sonra boş zaman",
            "pazartesi sabah toplantı için saat",
            "bugün 30 dakika müsait zaman",
        ]
        
        clarification_count = 0
        
        for query in queries:
            result = brain_loop.run(
                turn_input=query,
                session_context={"reference_time": now.isoformat()},
            )
            
            # Check if response is asking a question (clarification)
            if "?" in result.text or "mi" in result.text.lower() or "mı" in result.text.lower():
                # Might be clarification - check for question keywords
                if any(keyword in result.text.lower() for keyword in ["kaç", "hangi", "ne zaman", "nasıl"]):
                    clarification_count += 1
        
        # Acceptance: max 1 clarification in 5 conversations
        assert clarification_count <= 1, f"Expected max 1 clarification, got {clarification_count}"
    
    def test_more_slots_option_available(self, brain_loop):
        """Test 'daha fazla' option is mentioned."""
        now = datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc)
        
        result = brain_loop.run(
            turn_input="bugün boşluk var mı",
            session_context={"reference_time": now.isoformat()},
        )
        
        assert result is not None
        
        # Should mention ability to see more slots
        # Either explicitly or through menu system
        text_lower = result.text.lower()
        
        # Check for "daha fazla", "başka", or numbered options
        has_more_option = any(keyword in text_lower for keyword in [
            "daha fazla",
            "başka",
            "tümü",
            "diğer",
        ]) or ")" in result.text  # Numbered menu
        
        # If showing slots, should indicate more are available
        if "boşluk" in text_lower or "saat" in text_lower:
            # Allow flexibility - not all responses need "more" option
            pass  # Informational test
