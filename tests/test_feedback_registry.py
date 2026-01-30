"""
Tests for V2-6 Feedback Registry (Issue #38).
"""

import pytest

from bantz.conversation.feedback import (
    FeedbackType,
    FeedbackPhrase,
    FeedbackRegistry,
    create_feedback_registry,
    DEFAULT_PHRASES_TR,
    DEFAULT_PHRASES_EN,
)


class TestFeedbackType:
    """Tests for FeedbackType enum."""
    
    def test_types_exist(self):
        """Test all feedback types exist."""
        assert FeedbackType.ACKNOWLEDGMENT is not None
        assert FeedbackType.CONFIRMATION is not None
        assert FeedbackType.ERROR is not None
        assert FeedbackType.THINKING is not None
        assert FeedbackType.SUCCESS is not None
        assert FeedbackType.CLARIFICATION is not None
    
    def test_type_values(self):
        """Test type string values."""
        assert FeedbackType.ACKNOWLEDGMENT.value == "ack"
        assert FeedbackType.ERROR.value == "error"


class TestFeedbackPhrase:
    """Tests for FeedbackPhrase."""
    
    def test_create_phrase(self):
        """Test creating a phrase."""
        phrase = FeedbackPhrase(
            phrase="Anladım",
            feedback_type=FeedbackType.ACKNOWLEDGMENT,
            language="tr"
        )
        
        assert phrase.phrase == "Anladım"
        assert phrase.feedback_type == FeedbackType.ACKNOWLEDGMENT
        assert phrase.language == "tr"
    
    def test_phrase_weight(self):
        """Test phrase weight."""
        phrase = FeedbackPhrase(
            phrase="Test",
            feedback_type=FeedbackType.ACKNOWLEDGMENT,
            weight=2.0
        )
        
        assert phrase.weight == 2.0
    
    def test_phrase_weight_validation(self):
        """Test invalid weight is corrected."""
        phrase = FeedbackPhrase(
            phrase="Test",
            feedback_type=FeedbackType.ACKNOWLEDGMENT,
            weight=-1.0
        )
        
        assert phrase.weight == 1.0


class TestFeedbackRegistry:
    """Tests for FeedbackRegistry."""
    
    def test_default_phrases_loaded(self):
        """Test default phrases are loaded."""
        registry = FeedbackRegistry()
        
        count = registry.count()
        assert count > 0
    
    def test_get_random_turkish(self):
        """Test getting random Turkish phrase."""
        registry = FeedbackRegistry(language="tr")
        
        phrase = registry.get_random(FeedbackType.ACKNOWLEDGMENT)
        
        assert phrase != ""
        assert phrase in DEFAULT_PHRASES_TR[FeedbackType.ACKNOWLEDGMENT]
    
    def test_get_random_english(self):
        """Test getting random English phrase."""
        registry = FeedbackRegistry(language="en")
        
        phrase = registry.get_random(FeedbackType.ACKNOWLEDGMENT)
        
        assert phrase != ""
        assert phrase in DEFAULT_PHRASES_EN[FeedbackType.ACKNOWLEDGMENT]
    
    def test_get_all_phrases(self):
        """Test getting all phrases of a type."""
        registry = FeedbackRegistry()
        
        phrases = registry.get_all(FeedbackType.THINKING, language="tr")
        
        assert len(phrases) > 0
        assert "Bakayım" in phrases
    
    def test_register_custom_phrase(self):
        """Test registering custom phrase."""
        registry = FeedbackRegistry()
        
        custom = FeedbackPhrase(
            phrase="Özel cümle",
            feedback_type=FeedbackType.ACKNOWLEDGMENT,
            language="tr"
        )
        
        registry.register(custom)
        
        all_phrases = registry.get_all(FeedbackType.ACKNOWLEDGMENT, language="tr")
        assert "Özel cümle" in all_phrases
    
    def test_weighted_random(self):
        """Test weighted random selection."""
        registry = FeedbackRegistry(load_defaults=False)
        
        # Add phrases with different weights
        registry.register(FeedbackPhrase(
            phrase="Low weight",
            feedback_type=FeedbackType.ACKNOWLEDGMENT,
            language="tr",
            weight=0.1
        ))
        registry.register(FeedbackPhrase(
            phrase="High weight",
            feedback_type=FeedbackType.ACKNOWLEDGMENT,
            language="tr",
            weight=10.0
        ))
        
        # High weight should appear more often
        counts = {"Low weight": 0, "High weight": 0}
        for _ in range(100):
            phrase = registry.get_random(FeedbackType.ACKNOWLEDGMENT, language="tr")
            counts[phrase] += 1
        
        assert counts["High weight"] > counts["Low weight"]
    
    def test_feedback_type_isolation(self):
        """Test different types don't mix."""
        registry = FeedbackRegistry()
        
        ack_phrases = registry.get_all(FeedbackType.ACKNOWLEDGMENT, language="tr")
        error_phrases = registry.get_all(FeedbackType.ERROR, language="tr")
        
        # "Anladım" is ACK, "Bir hata oluştu" is ERROR
        assert "Anladım" in ack_phrases
        assert "Anladım" not in error_phrases
        assert "Bir hata oluştu" in error_phrases
        assert "Bir hata oluştu" not in ack_phrases
    
    def test_set_language(self):
        """Test setting default language."""
        registry = FeedbackRegistry(language="tr")
        
        registry.set_language("en")
        
        assert registry.language == "en"
    
    def test_count_by_type(self):
        """Test counting phrases by type."""
        registry = FeedbackRegistry()
        
        ack_count = registry.count(FeedbackType.ACKNOWLEDGMENT)
        
        assert ack_count > 0
    
    def test_clear_by_type(self):
        """Test clearing phrases by type."""
        registry = FeedbackRegistry()
        
        initial_count = registry.count(FeedbackType.ACKNOWLEDGMENT)
        registry.clear(FeedbackType.ACKNOWLEDGMENT)
        
        assert registry.count(FeedbackType.ACKNOWLEDGMENT) == 0
        # Other types should still have phrases
        assert registry.count(FeedbackType.ERROR) > 0
    
    def test_clear_all(self):
        """Test clearing all phrases."""
        registry = FeedbackRegistry()
        
        registry.clear()
        
        assert registry.count() == 0
    
    def test_factory_function(self):
        """Test create_feedback_registry factory."""
        registry = create_feedback_registry(language="en")
        
        assert isinstance(registry, FeedbackRegistry)
        assert registry.language == "en"
