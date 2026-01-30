"""
Tests for PreferenceModel.
"""

import pytest
from datetime import datetime

from bantz.learning.profile import UserProfile
from bantz.learning.preferences import (
    PreferenceModel,
    PreferenceEntry,
    PreferenceType,
    create_preference_model,
)


class TestPreferenceType:
    """Tests for PreferenceType enum."""
    
    def test_all_types_exist(self):
        """Test all preference types exist."""
        assert PreferenceType.CHOICE
        assert PreferenceType.CORRECTION
        assert PreferenceType.CANCELLATION
        assert PreferenceType.CONFIRMATION
        assert PreferenceType.REJECTION


class TestPreferenceEntry:
    """Tests for PreferenceEntry dataclass."""
    
    def test_create_entry(self):
        """Test creating an entry."""
        entry = PreferenceEntry(
            type=PreferenceType.CHOICE,
            original="option1,option2",
            chosen="option1",
        )
        
        assert entry.type == PreferenceType.CHOICE
        assert entry.original == "option1,option2"
        assert entry.chosen == "option1"
    
    def test_entry_to_dict(self):
        """Test entry serialization."""
        entry = PreferenceEntry(
            type=PreferenceType.CORRECTION,
            original="hello",
            chosen="hallo",
            intent="greeting",
        )
        
        data = entry.to_dict()
        
        assert data["type"] == "correction"
        assert data["original"] == "hello"
        assert data["chosen"] == "hallo"
    
    def test_entry_from_dict(self):
        """Test entry deserialization."""
        data = {
            "type": "choice",
            "original": "a,b",
            "chosen": "a",
            "timestamp": "2024-01-15T10:30:00",
        }
        
        entry = PreferenceEntry.from_dict(data)
        
        assert entry.type == PreferenceType.CHOICE
        assert entry.chosen == "a"


class TestPreferenceModel:
    """Tests for PreferenceModel class."""
    
    def test_create_model(self):
        """Test creating a model."""
        model = PreferenceModel()
        
        assert model.profile is None
    
    def test_create_with_profile(self):
        """Test creating model with profile."""
        profile = UserProfile()
        model = PreferenceModel(profile=profile)
        
        assert model.profile == profile
    
    def test_set_profile(self):
        """Test setting profile."""
        model = PreferenceModel()
        profile = UserProfile()
        
        model.set_profile(profile)
        
        assert model.profile == profile
    
    def test_learn_from_choice(self):
        """Test learning from choice."""
        model = PreferenceModel()
        
        model.learn_from_choice(
            options=["browser", "editor", "terminal"],
            chosen="browser",
            intent="open_app",
        )
        
        pref = model.get_intent_preference("open_app")
        assert pref > 0
    
    def test_learn_from_choice_updates_profile(self):
        """Test choice updates profile."""
        profile = UserProfile()
        model = PreferenceModel(profile=profile)
        
        model.learn_from_choice(
            options=["a", "b"],
            chosen="a",
            intent="test_intent",
        )
        
        assert "test_intent" in profile.preferred_intents
    
    def test_learn_from_correction(self):
        """Test learning from correction."""
        model = PreferenceModel()
        
        model.learn_from_correction(
            original="helo",
            corrected="hello",
            intent="greeting",
        )
        
        # Check word correction was learned
        suggestion = model.get_correction_suggestion("helo")
        # May not reach threshold with single correction
        assert suggestion is None or suggestion == "hello"
    
    def test_learn_from_correction_multiple(self):
        """Test learning from multiple corrections."""
        model = PreferenceModel()
        
        # Same correction multiple times
        for _ in range(5):
            model.learn_from_correction(
                original="helo",
                corrected="hello",
            )
        
        suggestion = model.get_correction_suggestion("helo")
        assert suggestion == "hello"
    
    def test_learn_from_cancellation(self):
        """Test learning from cancellation."""
        model = PreferenceModel()
        
        model.learn_from_cancellation(intent="risky_action")
        
        pref = model.get_intent_preference("risky_action")
        assert pref < 0
    
    def test_learn_from_cancellation_updates_profile(self):
        """Test cancellation updates profile."""
        profile = UserProfile()
        model = PreferenceModel(profile=profile)
        
        # Set a known starting value
        profile.preferred_intents["test"] = 0.5
        
        # Multiple cancellations to see effect
        for _ in range(10):
            model.learn_from_cancellation(intent="test")
        
        # Should have decreased from 0.5
        assert profile.preferred_intents["test"] < 0.5
    
    def test_learn_from_confirmation(self):
        """Test learning from confirmation."""
        model = PreferenceModel()
        
        model.learn_from_confirmation(intent="safe_action")
        
        pref = model.get_intent_preference("safe_action")
        assert pref > 0
    
    def test_learn_from_rejection(self):
        """Test learning from rejection."""
        model = PreferenceModel()
        
        model.learn_from_rejection(
            suggestion="do something",
            intent="unwanted",
        )
        
        pref = model.get_intent_preference("unwanted")
        assert pref < 0
    
    def test_get_intent_preference_unknown(self):
        """Test getting preference for unknown intent."""
        model = PreferenceModel()
        
        pref = model.get_intent_preference("unknown")
        
        assert pref == 0.0
    
    def test_get_top_intents(self):
        """Test getting top intents."""
        model = PreferenceModel()
        
        model.learn_from_confirmation(intent="popular")
        model.learn_from_confirmation(intent="popular")
        model.learn_from_confirmation(intent="less_popular")
        model.learn_from_cancellation(intent="unpopular")
        
        top = model.get_top_intents(2)
        
        assert len(top) <= 2
        assert top[0][0] == "popular"
    
    def test_get_parameter_preference(self):
        """Test parameter preference."""
        model = PreferenceModel()
        
        model.learn_from_choice(
            options=["a", "b"],
            chosen="a",
            context={"param_size": "large"},
        )
        
        pref = model.get_parameter_preference("size", "large")
        assert pref > 0
    
    def test_get_history(self):
        """Test getting history."""
        model = PreferenceModel()
        
        model.learn_from_choice(["a"], "a")
        model.learn_from_confirmation(intent="test")
        
        history = model.get_history()
        
        assert len(history) == 2
    
    def test_get_history_filtered(self):
        """Test getting filtered history."""
        model = PreferenceModel()
        
        model.learn_from_choice(["a"], "a")
        model.learn_from_confirmation(intent="test")
        model.learn_from_confirmation(intent="test2")
        
        history = model.get_history(type_filter=PreferenceType.CONFIRMATION)
        
        assert len(history) == 2
        assert all(e.type == PreferenceType.CONFIRMATION for e in history)
    
    def test_decay_preferences(self):
        """Test preference decay."""
        model = PreferenceModel()
        
        model.learn_from_confirmation(intent="test")
        original = model.get_intent_preference("test")
        
        model.decay_preferences()
        
        decayed = model.get_intent_preference("test")
        assert decayed < original
    
    def test_reset(self):
        """Test reset."""
        model = PreferenceModel()
        
        model.learn_from_choice(["a"], "a")
        model.learn_from_correction("x", "y")
        
        model.reset()
        
        assert model.get_history() == []
        assert model.get_top_intents() == []
    
    def test_to_dict(self):
        """Test serialization."""
        model = PreferenceModel()
        
        model.learn_from_confirmation(intent="test")
        
        data = model.to_dict()
        
        assert "intent_preferences" in data
        assert "history" in data
    
    def test_from_dict(self):
        """Test deserialization."""
        model = PreferenceModel()
        
        data = {
            "intent_preferences": {"test": 0.5},
            "word_preferences": {},
            "app_preferences": {},
            "parameter_preferences": {},
            "history": [],
        }
        
        model.from_dict(data)
        
        assert model.get_intent_preference("test") == 0.5
    
    def test_history_limit(self):
        """Test history is limited."""
        model = PreferenceModel(max_history=10)
        
        for i in range(20):
            model.learn_from_choice([f"opt{i}"], f"opt{i}")
        
        history = model.get_history(limit=100)
        assert len(history) == 10


class TestFactory:
    """Tests for factory function."""
    
    def test_create_preference_model(self):
        """Test factory function."""
        model = create_preference_model()
        
        assert model is not None
        assert isinstance(model, PreferenceModel)
    
    def test_create_with_profile(self):
        """Test factory with profile."""
        profile = UserProfile()
        model = create_preference_model(profile=profile)
        
        assert model.profile == profile
