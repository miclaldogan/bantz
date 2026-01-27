"""Tests for Query Clarification System (Issue #21)."""
from __future__ import annotations

import pytest

from bantz.router.clarifier import (
    QueryClarifier,
    QueryAnalysis,
    ClarificationType,
    ClarificationQuestion,
    ClarificationState,
    MockQueryClarifier,
)
from bantz.router.query_expander import (
    QueryExpander,
    ExpandedQuery,
    QuerySuggestion,
    MockQueryExpander,
)
from bantz.router.nlu import parse_intent


# ─────────────────────────────────────────────────────────────────
# QueryClarifier Tests
# ─────────────────────────────────────────────────────────────────

class TestQueryClarifierBasics:
    """Basic QueryClarifier tests."""
    
    def test_init(self):
        """Test clarifier initialization."""
        clarifier = QueryClarifier()
        assert clarifier.max_clarifications == 2
        assert not clarifier.is_pending
        assert clarifier.collected_slots == {}
    
    def test_init_custom_max(self):
        """Test clarifier with custom max clarifications."""
        clarifier = QueryClarifier(max_clarifications=3)
        assert clarifier.max_clarifications == 3
    
    def test_has_pending_question_initial(self):
        """Test has_pending_question returns False initially."""
        clarifier = QueryClarifier()
        assert not clarifier.has_pending_question()
    
    def test_reset(self):
        """Test reset clears state."""
        clarifier = QueryClarifier()
        clarifier._state.original_query = "test"
        clarifier._state.clarification_count = 1
        
        clarifier.reset()
        
        assert clarifier._state.original_query == ""
        assert clarifier._state.clarification_count == 0


class TestVagueIndicatorDetection:
    """Tests for detecting vague indicators in queries."""
    
    def test_detect_vague_location_surada(self):
        """Test 'şurada' triggers clarification."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("şurada kaza olmuş", "news_briefing")
        
        assert analysis.needs_clarification
        assert "location" in analysis.vague_indicators or len(analysis.missing_slots) > 0
    
    def test_detect_vague_location_orada(self):
        """Test 'orada' triggers clarification."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("orada yangın çıkmış", "news_briefing")
        
        assert analysis.needs_clarification
    
    def test_detect_vague_time_gecenlerde(self):
        """Test 'geçenlerde' triggers clarification."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("geçenlerde bir olay olmuştu", "news_briefing")
        
        assert analysis.needs_clarification
    
    def test_specific_location_no_clarification(self):
        """Test specific location doesn't need clarification."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("Kadıköy'de kaza olmuş", "news_briefing")
        
        # Should not need clarification if location is specific
        assert not analysis.needs_clarification or "location" not in analysis.missing_slots
    
    def test_specific_query_no_clarification(self):
        """Test fully specific query doesn't need clarification."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("bugün İstanbul'da deprem mi oldu", "news_briefing")
        
        # Fully specific - no clarification needed
        assert not analysis.needs_clarification


class TestClarificationFlow:
    """Tests for the clarification flow."""
    
    def test_start_clarification(self):
        """Test starting clarification flow."""
        clarifier = QueryClarifier()
        question = ClarificationQuestion(
            type=ClarificationType.LOCATION,
            question="Hangi bölgeden bahsediyorsunuz efendim?",
            examples=["Kadıköy", "Beşiktaş"],
            slot_name="location",
        )
        
        clarifier.start_clarification("şurada kaza olmuş", question)
        
        assert clarifier.has_pending_question()
        assert clarifier._state.original_query == "şurada kaza olmuş"
        assert clarifier._state.clarification_count == 1
    
    def test_process_response(self):
        """Test processing user response to clarification."""
        clarifier = QueryClarifier()
        question = ClarificationQuestion(
            type=ClarificationType.LOCATION,
            question="Hangi bölgeden bahsediyorsunuz efendim?",
            examples=["Kadıköy", "Beşiktaş"],
            slot_name="location",
        )
        
        clarifier.start_clarification("şurada kaza olmuş", question)
        collected = clarifier.process_response("Kadıköy")
        
        assert collected["location"] == "Kadıköy"
        assert not clarifier.has_pending_question()
    
    def test_get_search_query(self):
        """Test getting search query after clarification."""
        clarifier = QueryClarifier()
        question = ClarificationQuestion(
            type=ClarificationType.LOCATION,
            question="Hangi bölgeden bahsediyorsunuz efendim?",
            examples=["Kadıköy", "Beşiktaş"],
            slot_name="location",
        )
        
        clarifier.start_clarification("şurada kaza olmuş", question)
        clarifier.process_response("Kadıköy")
        
        search_query = clarifier.get_search_query()
        
        # Should contain both the event and location
        assert "kaza" in search_query.lower()
        assert "kadıköy" in search_query.lower()
    
    def test_max_clarifications_limit(self):
        """Test max clarifications limit is respected."""
        clarifier = QueryClarifier(max_clarifications=2)
        
        # First clarification
        question1 = ClarificationQuestion(
            type=ClarificationType.LOCATION,
            question="Hangi bölge?",
            examples=[],
            slot_name="location",
        )
        clarifier.start_clarification("orada birşey olmuş geçenlerde", question1)
        clarifier.process_response("Ankara")
        
        # Second clarification
        question2 = ClarificationQuestion(
            type=ClarificationType.TIME,
            question="Ne zaman?",
            examples=[],
            slot_name="time",
        )
        clarifier._state.pending_question = question2
        clarifier._state.clarification_count = 2
        clarifier.process_response("dün")
        
        # Third analysis - should not need more clarification
        analysis = clarifier.analyze_query("birşey olmuş", "news_briefing")
        assert not analysis.needs_clarification


class TestClarificationQuestionGeneration:
    """Tests for clarification question generation."""
    
    def test_location_question_jarvis_style(self):
        """Test location question is in Jarvis style with 'efendim'."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("şurada kaza var", "news_briefing")
        
        if analysis.needs_clarification and analysis.clarification_question:
            question = analysis.clarification_question.question
            assert "efendim" in question.lower()
    
    def test_question_has_examples(self):
        """Test clarification question includes examples."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("orada yangın çıkmış", "news_briefing")
        
        if analysis.needs_clarification and analysis.clarification_question:
            # Location questions should have example cities
            assert len(analysis.clarification_question.examples) > 0


# ─────────────────────────────────────────────────────────────────
# QueryExpander Tests
# ─────────────────────────────────────────────────────────────────

class TestQueryExpanderBasics:
    """Basic QueryExpander tests."""
    
    def test_init_without_llm(self):
        """Test expander without LLM."""
        expander = QueryExpander()
        assert not expander.has_llm
    
    def test_expand_simple(self):
        """Test simple expansion without LLM."""
        expander = QueryExpander()
        
        result = expander.expand_simple(
            "kaza haberleri",
            {"location": "Kadıköy", "time": "bugün"}
        )
        
        assert "kaza" in result
        assert "Kadıköy" in result
        assert "bugün" in result
    
    def test_expand_simple_no_duplicates(self):
        """Test simple expansion doesn't duplicate existing terms."""
        expander = QueryExpander()
        
        result = expander.expand_simple(
            "Kadıköy kaza haberleri",
            {"location": "Kadıköy"}
        )
        
        # Should not have "Kadıköy" twice
        assert result.count("Kadıköy") == 1
    
    def test_suggest_simple(self):
        """Test simple suggestions."""
        expander = QueryExpander()
        
        suggestions = expander.suggest_simple("deprem haberleri")
        
        assert len(suggestions) <= 3
        assert any("son dakika" in s for s in suggestions)
    
    def test_optimize_simple_removes_fillers(self):
        """Test optimization removes filler words."""
        expander = QueryExpander()
        
        result = expander.optimize_simple("bana bir kaza haberlere bak lütfen")
        
        # Filler words should be removed
        assert "bana" not in result
        assert "lütfen" not in result
        assert "kaza" in result


class TestQueryExpanderAsync:
    """Async QueryExpander tests."""
    
    @pytest.mark.asyncio
    async def test_expand_query_without_llm(self):
        """Test async expansion falls back to simple without LLM."""
        expander = QueryExpander()
        
        result = await expander.expand_query(
            "kaza",
            context={"location": "İstanbul"}
        )
        
        assert isinstance(result, ExpandedQuery)
        assert result.original == "kaza"
        assert "İstanbul" in result.expanded
    
    @pytest.mark.asyncio
    async def test_suggest_related_without_llm(self):
        """Test async suggestions falls back to simple without LLM."""
        expander = QueryExpander()
        
        suggestions = await expander.suggest_related("yangın haberleri")
        
        assert len(suggestions) <= 3
        assert all(isinstance(s, QuerySuggestion) for s in suggestions)
    
    @pytest.mark.asyncio
    async def test_optimize_without_llm(self):
        """Test async optimize falls back to simple without LLM."""
        expander = QueryExpander()
        
        result = await expander.optimize("bana kaza haberleri göster lütfen")
        
        assert "kaza" in result
        assert "lütfen" not in result


# ─────────────────────────────────────────────────────────────────
# Mock Tests
# ─────────────────────────────────────────────────────────────────

class TestMockQueryClarifier:
    """Tests for MockQueryClarifier."""
    
    def test_mock_set_pending(self):
        """Test mock can set pending state."""
        mock = MockQueryClarifier()
        
        mock.set_pending_response("location", "Ankara kaza haberleri")
        
        assert mock.get_pending_slot() == "location"
    
    def test_mock_analyze(self):
        """Test mock analyze returns configured result."""
        mock = MockQueryClarifier()
        mock.set_needs_clarification(True, ClarificationType.LOCATION)
        
        analysis = mock.analyze_query("test", "intent")
        
        assert analysis.needs_clarification


class TestMockQueryExpander:
    """Tests for MockQueryExpander."""
    
    def test_mock_set_expand_result(self):
        """Test mock can set expand result."""
        mock = MockQueryExpander()
        mock.set_expand_result("kaza", "Kadıköy kaza son dakika")
        
        result = mock.expand_simple("kaza", {})
        
        assert result == "Kadıköy kaza son dakika"
    
    def test_mock_set_suggestions(self):
        """Test mock can set suggestions."""
        mock = MockQueryExpander()
        mock.set_suggestions(["test1", "test2"])
        
        result = mock.suggest_simple("query")
        
        assert result == ["test1", "test2"]


# ─────────────────────────────────────────────────────────────────
# NLU Vague Pattern Tests
# ─────────────────────────────────────────────────────────────────

class TestNLUVaguePatterns:
    """Tests for NLU vague pattern detection."""
    
    def test_vague_location_with_event(self):
        """Test vague location with event word triggers vague_search."""
        parsed = parse_intent("şurada kaza olmuş")
        assert parsed.intent == "vague_search"
        assert parsed.slots.get("has_vague_location") is True
    
    def test_vague_time_with_event(self):
        """Test vague time with event word triggers vague_search."""
        parsed = parse_intent("geçenlerde bir olay olmuş")
        assert parsed.intent == "vague_search"
        assert parsed.slots.get("has_vague_time") is True
    
    def test_orada_with_event(self):
        """Test 'orada' with event triggers vague_search."""
        parsed = parse_intent("orada yangın çıkmış")
        assert parsed.intent == "vague_search"
    
    def test_specific_location_no_vague(self):
        """Test specific location doesn't trigger vague_search."""
        parsed = parse_intent("İstanbul'da kaza olmuş")
        # Should be regular news_briefing or google_search, not vague_search
        assert parsed.intent != "vague_search" or not parsed.slots.get("has_vague_location")
    
    def test_no_event_no_vague(self):
        """Test vague indicator without event word doesn't trigger."""
        parsed = parse_intent("şurada güzel bir cafe var")
        # No event word, shouldn't be vague_search
        assert parsed.intent != "vague_search"


# ─────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────

class TestClarificationIntegration:
    """Integration tests for the full clarification flow."""
    
    def test_full_flow_location_clarification(self):
        """Test full flow: vague query -> clarification -> search."""
        clarifier = QueryClarifier()
        
        # Step 1: Analyze vague query
        analysis = clarifier.analyze_query("şurada kaza olmuş", "news_briefing")
        assert analysis.needs_clarification
        
        # Step 2: Start clarification
        if analysis.clarification_question:
            clarifier.start_clarification("şurada kaza olmuş", analysis.clarification_question)
        
        # Step 3: User responds
        clarifier.process_response("Kadıköy")
        
        # Step 4: Get search query
        search_query = clarifier.get_search_query()
        
        assert "kaza" in search_query.lower()
        assert "kadıköy" in search_query.lower()
    
    def test_flow_with_multiple_clarifications(self):
        """Test flow with multiple clarification questions."""
        clarifier = QueryClarifier(max_clarifications=2)
        
        # Step 1: First vague query (location + time vague)
        q1 = ClarificationQuestion(
            type=ClarificationType.LOCATION,
            question="Hangi bölge efendim?",
            examples=["Kadıköy"],
            slot_name="location",
        )
        clarifier.start_clarification("orada geçenlerde birşey olmuş", q1)
        clarifier.process_response("Beşiktaş")
        
        # Step 2: Second clarification (time)
        q2 = ClarificationQuestion(
            type=ClarificationType.TIME,
            question="Ne zaman efendim?",
            examples=["bugün"],
            slot_name="time",
        )
        clarifier._state.pending_question = q2
        clarifier.process_response("dün")
        
        # Step 3: Get combined search
        search_query = clarifier.get_search_query()
        
        assert "beşiktaş" in search_query.lower()
        assert "dün" in search_query.lower()


# ─────────────────────────────────────────────────────────────────
# Edge Cases
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_query(self):
        """Test empty query handling."""
        clarifier = QueryClarifier()
        analysis = clarifier.analyze_query("", "news_briefing")
        
        # Empty query shouldn't crash
        assert analysis is not None
    
    def test_reset_mid_flow(self):
        """Test reset during clarification flow."""
        clarifier = QueryClarifier()
        
        question = ClarificationQuestion(
            type=ClarificationType.LOCATION,
            question="Hangi bölge?",
            examples=[],
            slot_name="location",
        )
        clarifier.start_clarification("test query", question)
        
        # Reset mid-flow
        clarifier.reset()
        
        assert not clarifier.has_pending_question()
        assert clarifier._state.original_query == ""
    
    def test_process_response_no_pending(self):
        """Test process_response when no pending question."""
        clarifier = QueryClarifier()
        
        result = clarifier.process_response("random response")
        
        # Should return empty slots, not crash
        assert result == {}
    
    def test_unicode_in_query(self):
        """Test Turkish unicode characters handled correctly."""
        clarifier = QueryClarifier()
        
        analysis = clarifier.analyze_query(
            "Şımarık Öğüt Çiğköfte Üstü İçin",
            "news_briefing"
        )
        
        # Should not crash with Turkish characters
        assert analysis is not None
