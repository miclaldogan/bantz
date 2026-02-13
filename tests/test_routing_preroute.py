"""Tests for rule-based pre-route module.

Issue #245: Rule-based pre-route for obvious cases.

Tests cover:
- IntentCategory enum and properties
- PreRouteMatch dataclass
- Rule types (Pattern, Keyword, Composite)
- Default rules for Turkish
- PreRouter class and statistics
- LocalResponseGenerator
- Integration helpers
"""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from bantz.routing.preroute import (
    IntentCategory,
    PreRouteMatch,
    PreRouteRule,
    PatternRule,
    KeywordRule,
    CompositeRule,
    PreRouter,
    LocalResponseGenerator,
    create_greeting_rule,
    create_farewell_rule,
    create_thanks_rule,
    create_affirmative_rule,
    create_negative_rule,
    create_time_rule,
    create_date_rule,
    create_calendar_list_rule,
    create_calendar_create_rule,
    create_calendar_delete_rule,
    create_email_send_rule,
    create_volume_rule,
    create_screenshot_rule,
    create_smalltalk_rule,
    integrate_prerouter,
)


# =============================================================================
# IntentCategory Tests
# =============================================================================

class TestIntentCategory:
    """Tests for IntentCategory enum."""
    
    def test_greeting_value(self) -> None:
        """Test GREETING value."""
        assert IntentCategory.GREETING.value == "greeting"
    
    def test_calendar_list_value(self) -> None:
        """Test CALENDAR_LIST value."""
        assert IntentCategory.CALENDAR_LIST.value == "calendar_list"
    
    def test_unknown_value(self) -> None:
        """Test UNKNOWN value."""
        assert IntentCategory.UNKNOWN.value == "unknown"
    
    def test_greeting_can_bypass(self) -> None:
        """Test GREETING can bypass router."""
        assert IntentCategory.GREETING.can_bypass_router is True
    
    def test_farewell_can_bypass(self) -> None:
        """Test FAREWELL can bypass router."""
        assert IntentCategory.FAREWELL.can_bypass_router is True
    
    def test_thanks_can_bypass(self) -> None:
        """Test THANKS can bypass router."""
        assert IntentCategory.THANKS.can_bypass_router is True
    
    def test_time_query_can_bypass(self) -> None:
        """Test TIME_QUERY can bypass router."""
        assert IntentCategory.TIME_QUERY.can_bypass_router is True
    
    def test_calendar_list_can_bypass(self) -> None:
        """Test CALENDAR_LIST can bypass router."""
        assert IntentCategory.CALENDAR_LIST.can_bypass_router is True
    
    def test_unknown_cannot_bypass(self) -> None:
        """Test UNKNOWN cannot bypass router."""
        assert IntentCategory.UNKNOWN.can_bypass_router is False
    
    def test_complex_cannot_bypass(self) -> None:
        """Test COMPLEX cannot bypass router."""
        assert IntentCategory.COMPLEX.can_bypass_router is False
    
    def test_ambiguous_cannot_bypass(self) -> None:
        """Test AMBIGUOUS cannot bypass router."""
        assert IntentCategory.AMBIGUOUS.can_bypass_router is False
    
    def test_greeting_handler_type(self) -> None:
        """Test GREETING handler type."""
        assert IntentCategory.GREETING.handler_type == "local"
    
    def test_time_query_handler_type(self) -> None:
        """Test TIME_QUERY handler type."""
        assert IntentCategory.TIME_QUERY.handler_type == "system"
    
    def test_calendar_list_handler_type(self) -> None:
        """Test CALENDAR_LIST handler type."""
        assert IntentCategory.CALENDAR_LIST.handler_type == "calendar"
    
    def test_unknown_handler_type(self) -> None:
        """Test UNKNOWN handler type."""
        assert IntentCategory.UNKNOWN.handler_type == "router"

    def test_email_send_not_bypassable(self) -> None:
        assert IntentCategory.EMAIL_SEND.can_bypass_router is False

    def test_email_send_handler_type(self) -> None:
        assert IntentCategory.EMAIL_SEND.handler_type == "router"


# =============================================================================
# PreRouteMatch Tests
# =============================================================================

class TestPreRouteMatch:
    """Tests for PreRouteMatch dataclass."""
    
    def test_no_match(self) -> None:
        """Test no_match factory."""
        result = PreRouteMatch.no_match()
        assert result.matched is False
        assert result.intent == IntentCategory.UNKNOWN
        assert result.confidence == 0.0
    
    def test_create_match(self) -> None:
        """Test create factory."""
        result = PreRouteMatch.create(
            intent=IntentCategory.GREETING,
            confidence=0.95,
            rule_name="greeting",
        )
        assert result.matched is True
        assert result.intent == IntentCategory.GREETING
        assert result.confidence == 0.95
        assert result.rule_name == "greeting"
    
    def test_create_with_extracted(self) -> None:
        """Test create with extracted data."""
        result = PreRouteMatch.create(
            intent=IntentCategory.TIME_QUERY,
            confidence=0.9,
            rule_name="time_query",
            extracted={"hour": "14"},
        )
        assert result.extracted["hour"] == "14"
    
    def test_should_bypass_high_confidence(self) -> None:
        """Test should_bypass with high confidence."""
        result = PreRouteMatch.create(
            intent=IntentCategory.GREETING,
            confidence=0.95,
            rule_name="greeting",
        )
        assert result.should_bypass(min_confidence=0.8) is True
    
    def test_should_bypass_low_confidence(self) -> None:
        """Test should_bypass with low confidence."""
        result = PreRouteMatch.create(
            intent=IntentCategory.GREETING,
            confidence=0.5,
            rule_name="greeting",
        )
        assert result.should_bypass(min_confidence=0.8) is False
    
    def test_should_bypass_non_bypassable_intent(self) -> None:
        """Test should_bypass with non-bypassable intent."""
        result = PreRouteMatch.create(
            intent=IntentCategory.COMPLEX,
            confidence=0.95,
            rule_name="complex",
        )
        assert result.should_bypass(min_confidence=0.8) is False
    
    def test_should_bypass_no_match(self) -> None:
        """Test should_bypass with no match."""
        result = PreRouteMatch.no_match()
        assert result.should_bypass() is False


# =============================================================================
# PatternRule Tests
# =============================================================================

class TestPatternRule:
    """Tests for PatternRule class."""
    
    def test_simple_pattern_match(self) -> None:
        """Test simple pattern matching."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.TIME_QUERY,
            patterns=[r"saat\s+kaç"],
        )
        result = rule.match("Saat kaç?")
        assert result.matched is True
        assert result.intent == IntentCategory.TIME_QUERY
    
    def test_pattern_no_match(self) -> None:
        """Test pattern not matching."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.TIME_QUERY,
            patterns=[r"saat\s+kaç"],
        )
        result = rule.match("Bugün hava nasıl?")
        assert result.matched is False
    
    def test_case_insensitive(self) -> None:
        """Test case insensitive matching."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.GREETING,
            patterns=[r"merhaba"],
            case_sensitive=False,
        )
        assert rule.match("MERHABA").matched is True
        assert rule.match("Merhaba").matched is True
    
    def test_case_sensitive(self) -> None:
        """Test case sensitive matching."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.GREETING,
            patterns=[r"merhaba"],
            case_sensitive=True,
        )
        assert rule.match("merhaba").matched is True
        assert rule.match("MERHABA").matched is False
    
    def test_multiple_patterns(self) -> None:
        """Test multiple patterns."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.GREETING,
            patterns=[r"merhaba", r"selam", r"hey"],
        )
        assert rule.match("merhaba").matched is True
        assert rule.match("selam").matched is True
        assert rule.match("hey").matched is True
    
    def test_named_groups_extracted(self) -> None:
        """Test named groups are extracted."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.TIME_QUERY,
            patterns=[r"saat\s+(?P<hour>\d+)"],
        )
        result = rule.match("saat 14 oldu")
        assert result.matched is True
        assert result.extracted.get("hour") == "14"
    
    def test_custom_confidence(self) -> None:
        """Test custom confidence."""
        rule = PatternRule(
            name="test",
            intent=IntentCategory.GREETING,
            patterns=[r"merhaba"],
            confidence=0.85,
        )
        result = rule.match("merhaba")
        assert result.confidence == 0.85


# =============================================================================
# KeywordRule Tests
# =============================================================================

class TestKeywordRule:
    """Tests for KeywordRule class."""
    
    def test_keyword_match(self) -> None:
        """Test keyword matching."""
        rule = KeywordRule(
            name="test",
            intent=IntentCategory.GREETING,
            keywords=["merhaba", "selam"],
        )
        result = rule.match("Merhaba!")
        assert result.matched is True
        assert result.extracted["keyword"] == "merhaba"
    
    def test_keyword_no_match(self) -> None:
        """Test keyword not matching."""
        rule = KeywordRule(
            name="test",
            intent=IntentCategory.GREETING,
            keywords=["merhaba", "selam"],
        )
        result = rule.match("Günaydın")
        assert result.matched is False
    
    def test_exact_match_true(self) -> None:
        """Test exact match mode."""
        rule = KeywordRule(
            name="test",
            intent=IntentCategory.AFFIRMATIVE,
            keywords=["evet", "tamam"],
            exact_match=True,
        )
        assert rule.match("evet").matched is True
        assert rule.match("evet diyorum").matched is False
    
    def test_exact_match_false(self) -> None:
        """Test non-exact match mode."""
        rule = KeywordRule(
            name="test",
            intent=IntentCategory.AFFIRMATIVE,
            keywords=["evet", "tamam"],
            exact_match=False,
        )
        assert rule.match("evet").matched is True
        assert rule.match("evet diyorum").matched is True
    
    def test_case_insensitive(self) -> None:
        """Test case insensitive matching."""
        rule = KeywordRule(
            name="test",
            intent=IntentCategory.GREETING,
            keywords=["merhaba"],
        )
        assert rule.match("MERHABA").matched is True
        assert rule.match("Merhaba").matched is True


# =============================================================================
# CompositeRule Tests
# =============================================================================

class TestCompositeRule:
    """Tests for CompositeRule class."""
    
    def test_any_match(self) -> None:
        """Test any rule matching (OR)."""
        rule = CompositeRule(
            name="test",
            intent=IntentCategory.GREETING,
            rules=[
                KeywordRule("r1", IntentCategory.GREETING, ["merhaba"]),
                KeywordRule("r2", IntentCategory.GREETING, ["selam"]),
            ],
            require_all=False,
        )
        assert rule.match("merhaba").matched is True
        assert rule.match("selam").matched is True
        assert rule.match("günaydın").matched is False
    
    def test_all_match(self) -> None:
        """Test all rules matching (AND)."""
        rule = CompositeRule(
            name="test",
            intent=IntentCategory.GREETING,
            rules=[
                KeywordRule("r1", IntentCategory.GREETING, ["merhaba"]),
                KeywordRule("r2", IntentCategory.GREETING, ["nasılsın"]),
            ],
            require_all=True,
        )
        assert rule.match("merhaba nasılsın").matched is True
        assert rule.match("merhaba").matched is False
    
    def test_best_confidence_returned(self) -> None:
        """Test best confidence is returned."""
        rule = CompositeRule(
            name="test",
            intent=IntentCategory.GREETING,
            rules=[
                KeywordRule("r1", IntentCategory.GREETING, ["merhaba"], confidence=0.8),
                PatternRule("r2", IntentCategory.GREETING, [r"merhaba"], confidence=0.95),
            ],
            require_all=False,
        )
        result = rule.match("merhaba")
        assert result.confidence == 0.95


# =============================================================================
# Default Rule Factory Tests
# =============================================================================

class TestDefaultRuleFactories:
    """Tests for default rule factory functions."""
    
    def test_greeting_rule(self) -> None:
        """Test greeting rule."""
        rule = create_greeting_rule()
        assert rule.match("Merhaba!").matched is True
        assert rule.match("Selam").matched is True
        assert rule.match("Günaydın").matched is True
        assert rule.match("Hello").matched is True
        # Issue #1001: "hi" removed — matches Turkish "hiç", "hikaye" etc.
        assert rule.match("Hi").matched is False
        assert rule.match("hiç sorun yok").matched is False
    
    def test_farewell_rule(self) -> None:
        """Test farewell rule."""
        rule = create_farewell_rule()
        assert rule.match("Güle güle").matched is True
        assert rule.match("Görüşürüz").matched is True
        assert rule.match("Hoşçakal").matched is True
    
    def test_thanks_rule(self) -> None:
        """Test thanks rule."""
        rule = create_thanks_rule()
        assert rule.match("Teşekkürler!").matched is True
        assert rule.match("Sağol").matched is True
        assert rule.match("Mersi").matched is True
    
    def test_affirmative_rule(self) -> None:
        """Test affirmative rule."""
        rule = create_affirmative_rule()
        assert rule.match("evet").matched is True
        assert rule.match("tamam").matched is True
        assert rule.match("ok").matched is True
    
    def test_negative_rule(self) -> None:
        """Test negative rule."""
        rule = create_negative_rule()
        assert rule.match("hayır").matched is True
        assert rule.match("iptal").matched is True
        assert rule.match("no").matched is True
    
    def test_time_rule(self) -> None:
        """Test time rule."""
        rule = create_time_rule()
        assert rule.match("Saat kaç?").matched is True
        assert rule.match("Şu anki saat").matched is True
    
    def test_date_rule(self) -> None:
        """Test date rule."""
        rule = create_date_rule()
        assert rule.match("Bugün hangi gün?").matched is True
        assert rule.match("Tarih ne?").matched is True
    
    def test_calendar_list_rule(self) -> None:
        """Test calendar list rule."""
        rule = create_calendar_list_rule()
        assert rule.match("Takvimde ne var?").matched is True
        assert rule.match("Bugünkü toplantılarım ne?").matched is True
        assert rule.match("Etkinliklerim ne?").matched is True
    
    def test_calendar_create_rule(self) -> None:
        """Test calendar create rule."""
        rule = create_calendar_create_rule()
        assert rule.match("Yeni etkinlik ekle").matched is True
        assert rule.match("Toplantı oluştur").matched is True
    
    def test_calendar_delete_rule(self) -> None:
        """Test calendar delete rule."""
        rule = create_calendar_delete_rule()
        assert rule.match("Etkinlik sil").matched is True
        assert rule.match("Toplantıyı iptal et").matched is True
    
    def test_volume_rule(self) -> None:
        """Test volume rule."""
        rule = create_volume_rule()
        assert rule.match("Sesi aç").matched is True
        assert rule.match("Sesi kıs").matched is True
    
    def test_screenshot_rule(self) -> None:
        """Test screenshot rule."""
        rule = create_screenshot_rule()
        assert rule.match("Ekran görüntüsü al").matched is True
        assert rule.match("Screenshot çek").matched is True
    
    def test_smalltalk_rule(self) -> None:
        """Test smalltalk rule."""
        rule = create_smalltalk_rule()
        assert rule.match("Nasılsın?").matched is True
        assert rule.match("Ne haber?").matched is True


# =============================================================================
# PreRouter Tests
# =============================================================================

class TestPreRouter:
    """Tests for PreRouter class."""
    
    def test_creation_default_rules(self) -> None:
        """Test creation with default rules."""
        router = PreRouter()
        assert len(router.rules) > 0
    
    def test_creation_custom_rules(self) -> None:
        """Test creation with custom rules."""
        rules = [create_greeting_rule()]
        router = PreRouter(rules=rules)
        assert len(router.rules) == 1
    
    def test_route_greeting(self) -> None:
        """Test routing greeting."""
        router = PreRouter()
        result = router.route("Merhaba!")
        assert result.matched is True
        assert result.intent == IntentCategory.GREETING
    
    def test_route_time_query(self) -> None:
        """Test routing time query."""
        router = PreRouter()
        result = router.route("Saat kaç?")
        assert result.matched is True
        assert result.intent == IntentCategory.TIME_QUERY
    
    def test_route_unknown(self) -> None:
        """Test routing unknown text."""
        router = PreRouter()
        result = router.route("Bu sorguyu regex ile yakalayamazsın!")
        assert result.matched is False
    
    def test_route_empty_text(self) -> None:
        """Test routing empty text."""
        router = PreRouter()
        result = router.route("")
        assert result.matched is False
    
    def test_should_bypass_true(self) -> None:
        """Test should_bypass returns true."""
        router = PreRouter()
        assert router.should_bypass("Merhaba!") is True
    
    def test_should_bypass_false(self) -> None:
        """Test should_bypass returns false."""
        router = PreRouter()
        assert router.should_bypass("Bu karmaşık bir soru mu?") is False
    
    def test_add_rule(self) -> None:
        """Test adding a rule."""
        router = PreRouter()
        initial_count = len(router.rules)
        custom_rule = KeywordRule("custom", IntentCategory.GREETING, ["özel"])
        router.add_rule(custom_rule)
        assert len(router.rules) == initial_count + 1
        assert router.route("özel kelime").matched is True
    
    def test_remove_rule(self) -> None:
        """Test removing a rule."""
        router = PreRouter()
        initial_count = len(router.rules)
        result = router.remove_rule("greeting")
        assert result is True
        assert len(router.rules) == initial_count - 1
    
    def test_remove_rule_not_found(self) -> None:
        """Test removing non-existent rule."""
        router = PreRouter()
        result = router.remove_rule("nonexistent")
        assert result is False
    
    def test_stats_tracking(self) -> None:
        """Test statistics tracking."""
        router = PreRouter()
        
        router.route("Merhaba!")  # Bypassed
        router.route("Saat kaç?")  # Bypassed
        router.route("Karmaşık soru")  # Not bypassed
        
        stats = router.get_stats()
        assert stats["total_queries"] == 3
        assert stats["bypassed_queries"] == 2
        assert stats["bypass_rate"] == pytest.approx(2/3)
    
    def test_bypass_rate(self) -> None:
        """Test bypass rate calculation."""
        router = PreRouter()
        
        # No queries
        assert router.get_bypass_rate() == 0.0
        
        # All bypassed
        router.route("Merhaba!")
        assert router.get_bypass_rate() == 1.0
        
        # 50% bypassed
        router.route("Karmaşık soru")
        assert router.get_bypass_rate() == 0.5
    
    def test_reset_stats(self) -> None:
        """Test resetting statistics."""
        router = PreRouter()
        
        router.route("Merhaba!")
        router.route("Selam")
        
        assert router.get_stats()["total_queries"] == 2
        
        router.reset_stats()
        
        assert router.get_stats()["total_queries"] == 0
        assert router.get_stats()["bypassed_queries"] == 0
    
    def test_rule_hits_tracking(self) -> None:
        """Test rule hits tracking."""
        router = PreRouter()
        
        router.route("Merhaba!")
        router.route("Selam")
        router.route("Saat kaç?")
        
        stats = router.get_stats()
        assert stats["rule_hits"]["greeting"] == 2
        assert stats["rule_hits"]["time_query"] == 1
    
    def test_min_confidence_setting(self) -> None:
        """Test minimum confidence setting."""
        router = PreRouter(min_confidence=0.99)
        
        result = router.route("Merhaba!")  # 0.95 confidence
        # Should match but not bypass due to high threshold
        assert result.should_bypass(min_confidence=0.99) is False


# =============================================================================
# LocalResponseGenerator Tests
# =============================================================================

class TestLocalResponseGenerator:
    """Tests for LocalResponseGenerator class."""
    
    def test_greeting_response(self) -> None:
        """Test greeting response."""
        gen = LocalResponseGenerator()
        response = gen.greeting()
        assert "yardımcı" in response
    
    def test_farewell_response(self) -> None:
        """Test farewell response."""
        gen = LocalResponseGenerator()
        response = gen.farewell()
        assert "Görüşmek" in response or "günler" in response
    
    def test_thanks_response(self) -> None:
        """Test thanks response."""
        gen = LocalResponseGenerator()
        response = gen.thanks()
        assert "Rica" in response
    
    def test_affirmative_response(self) -> None:
        """Test affirmative response."""
        gen = LocalResponseGenerator()
        response = gen.affirmative()
        assert "Tamam" in response
    
    def test_negative_response(self) -> None:
        """Test negative response."""
        gen = LocalResponseGenerator()
        response = gen.negative()
        assert "iptal" in response
    
    def test_smalltalk_response(self) -> None:
        """Test smalltalk response."""
        gen = LocalResponseGenerator()
        response = gen.smalltalk()
        assert "yardımcı" in response
    
    def test_time_query_response(self) -> None:
        """Test time query response."""
        gen = LocalResponseGenerator()
        response = gen.time_query()
        assert "Saat" in response
        # Check format HH:MM is present
        import re
        assert re.search(r"\d{2}:\d{2}", response) is not None
    
    def test_date_query_response(self) -> None:
        """Test date query response."""
        gen = LocalResponseGenerator()
        response = gen.date_query()
        assert "Bugün" in response
        # Check year is present
        assert str(datetime.now().year) in response
    
    def test_generate_method(self) -> None:
        """Test generate method dispatches correctly."""
        gen = LocalResponseGenerator()
        
        response = gen.generate(IntentCategory.GREETING)
        assert "yardımcı" in response
        
        response = gen.generate(IntentCategory.TIME_QUERY)
        assert "Saat" in response
    
    def test_generate_unknown_intent(self) -> None:
        """Test generate with unknown intent."""
        gen = LocalResponseGenerator()
        response = gen.generate(IntentCategory.COMPLEX)
        assert response == "Anladım."


# =============================================================================
# Integration Helper Tests
# =============================================================================

class TestIntegratePrerouter:
    """Tests for integrate_prerouter function."""
    
    def test_bypass_for_greeting(self) -> None:
        """Test bypass for greeting."""
        prerouter = PreRouter()
        mock_router = MagicMock(return_value="llm_result")
        
        result, was_bypassed = integrate_prerouter(
            prerouter, mock_router, "Merhaba!"
        )
        
        assert was_bypassed is True
        assert isinstance(result, PreRouteMatch)
        assert result.intent == IntentCategory.GREETING
        mock_router.assert_not_called()
    
    def test_no_bypass_for_complex(self) -> None:
        """Test no bypass for complex query."""
        prerouter = PreRouter()
        mock_router = MagicMock(return_value="llm_result")
        
        result, was_bypassed = integrate_prerouter(
            prerouter, mock_router, "Bu karmaşık bir soru"
        )
        
        assert was_bypassed is False
        assert result == "llm_result"
        mock_router.assert_called_once_with("Bu karmaşık bir soru")


# =============================================================================
# E2E Integration Tests
# =============================================================================

class TestPreRouterE2E:
    """End-to-end integration tests."""
    
    def test_30_percent_target_achievable(self) -> None:
        """Test that 30% bypass rate is achievable with typical traffic."""
        router = PreRouter()
        
        # Simulate typical traffic mix
        queries = [
            # Simple - should bypass (30%)
            "Merhaba!",
            "Saat kaç?",
            "Teşekkürler",
            # Complex - should not bypass (70%)
            "Yarınki toplantıda sunum yapacağım",
            "Bu e-postayı nasıl yazmalıyım?",
            "Projede hangi teknolojileri kullanmalıyız?",
            "Raporu hazırlayabilir misin?",
            "Toplantı notlarını özetle",
            "Kodda bir hata var",
            "Bana bir hikaye anlat",
        ]
        
        for q in queries:
            router.route(q)
        
        stats = router.get_stats()
        # At least 3 out of 10 should bypass (30%)
        assert stats["bypassed_queries"] >= 3
    
    def test_full_flow_with_response_generation(self) -> None:
        """Test full flow from query to response."""
        router = PreRouter()
        generator = LocalResponseGenerator()
        
        # Greeting flow
        result = router.route("Merhaba!")
        assert result.should_bypass()
        response = generator.generate(result.intent)
        assert "yardımcı" in response
        
        # Time query flow
        result = router.route("Saat kaç?")
        assert result.should_bypass()
        response = generator.generate(result.intent)
        assert "Saat" in response
    
    def test_calendar_intent_detection(self) -> None:
        """Test calendar intent detection."""
        router = PreRouter()
        
        # List events
        result = router.route("Takvimde ne var?")
        assert result.intent == IntentCategory.CALENDAR_LIST
        
        # Create event
        result = router.route("Yeni toplantı ekle")
        assert result.intent == IntentCategory.CALENDAR_CREATE
        
        # Delete event
        result = router.route("Toplantıyı iptal et")
        assert result.intent == IntentCategory.CALENDAR_DELETE
    
    def test_system_command_detection(self) -> None:
        """Test system command detection."""
        router = PreRouter()
        
        # Volume
        result = router.route("Sesi kıs")
        assert result.intent == IntentCategory.VOLUME_CONTROL
        
        # Screenshot
        result = router.route("Ekran görüntüsü al")
        assert result.intent == IntentCategory.SCREENSHOT
    
    def test_stats_report(self) -> None:
        """Test statistics report."""
        router = PreRouter()
        
        # Generate some traffic
        queries = [
            "Merhaba",
            "Selam",
            "Saat kaç",
            "Nasılsın",
            "Bu ne demek?",
            "Karmaşık soru",
        ]
        
        for q in queries:
            router.route(q)
        
        stats = router.get_stats()
        
        assert "total_queries" in stats
        assert "bypassed_queries" in stats
        assert "bypass_rate" in stats
        assert "bypass_rate_percent" in stats
        assert "rule_hits" in stats
        assert "target_rate" in stats
        assert "on_target" in stats


# =============================================================================
# Issue #998: has_pending_confirmation scoping
# =============================================================================


class TestPendingConfirmationScope:
    """Issue #998: has_pending_confirmation should only suppress
    AFFIRMATIVE/NEGATIVE rules, not all rules."""

    def test_confirmation_pending_blocks_affirmative(self):
        """'evet' should NOT match when confirmation is pending."""
        router = PreRouter()
        result = router.route("evet", has_pending_confirmation=True)
        # Should not match affirmative — let orchestrator handle it
        assert not result.matched or result.intent != IntentCategory.AFFIRMATIVE

    def test_confirmation_pending_blocks_negative(self):
        """'hayır' should NOT match when confirmation is pending."""
        router = PreRouter()
        result = router.route("hayır", has_pending_confirmation=True)
        assert not result.matched or result.intent != IntentCategory.NEGATIVE

    def test_confirmation_pending_allows_greeting(self):
        """'merhaba' should still match when confirmation is pending."""
        router = PreRouter()
        result = router.route("merhaba", has_pending_confirmation=True)
        assert result.matched
        assert result.intent == IntentCategory.GREETING

    def test_confirmation_pending_allows_time_query(self):
        """'saat kaç' should still match when confirmation is pending."""
        router = PreRouter()
        result = router.route("saat kaç", has_pending_confirmation=True)
        assert result.matched
        assert result.intent == IntentCategory.TIME_QUERY

    def test_confirmation_pending_allows_calendar_list(self):
        """Calendar list queries should still work during confirmation."""
        router = PreRouter()
        result = router.route("bugünkü etkinlik göster", has_pending_confirmation=True)
        assert result.matched
        assert result.intent == IntentCategory.CALENDAR_LIST

    def test_no_confirmation_still_matches_affirmative(self):
        """Without pending confirmation, 'evet' should match normally."""
        router = PreRouter()
        result = router.route("evet", has_pending_confirmation=False)
        assert result.matched
        assert result.intent == IntentCategory.AFFIRMATIVE
