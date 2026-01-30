"""
Tests for BehavioralLearner.
"""

import pytest
from datetime import datetime, timedelta

from bantz.learning.profile import UserProfile
from bantz.learning.behavioral import (
    BehavioralLearner,
    CommandEvent,
    RewardSignal,
    Prediction,
    REWARD_VALUES,
    create_behavioral_learner,
)


class TestRewardSignal:
    """Tests for RewardSignal enum."""
    
    def test_reward_values_exist(self):
        """Test that all signals have reward values."""
        for signal in RewardSignal:
            assert signal in REWARD_VALUES
    
    def test_success_is_positive(self):
        """Test success has positive reward."""
        assert REWARD_VALUES[RewardSignal.SUCCESS] > 0
    
    def test_failure_is_negative(self):
        """Test failure has negative reward."""
        assert REWARD_VALUES[RewardSignal.FAILURE] < 0


class TestCommandEvent:
    """Tests for CommandEvent dataclass."""
    
    def test_create_basic_event(self):
        """Test creating a basic event."""
        event = CommandEvent(intent="open_app")
        
        assert event.intent == "open_app"
        assert event.success is True
        assert event.cancelled is False
        assert event.corrected is False
    
    def test_event_with_parameters(self):
        """Test event with parameters."""
        event = CommandEvent(
            intent="open_app",
            parameters={"app": "browser"},
            success=True,
            duration_ms=150.0,
        )
        
        assert event.parameters["app"] == "browser"
        assert event.duration_ms == 150.0
    
    def test_event_to_dict(self):
        """Test event serialization."""
        event = CommandEvent(
            intent="search",
            app="browser",
        )
        
        data = event.to_dict()
        
        assert data["intent"] == "search"
        assert data["app"] == "browser"
        assert "timestamp" in data


class TestPrediction:
    """Tests for Prediction dataclass."""
    
    def test_create_prediction(self):
        """Test creating a prediction."""
        pred = Prediction(
            intent="open_browser",
            confidence=0.85,
            reason="Sık kullanılan",
        )
        
        assert pred.intent == "open_browser"
        assert pred.confidence == 0.85
    
    def test_prediction_to_dict(self):
        """Test prediction serialization."""
        pred = Prediction(
            intent="search",
            confidence=0.7,
        )
        
        data = pred.to_dict()
        
        assert data["intent"] == "search"
        assert data["confidence"] == 0.7


class TestBehavioralLearner:
    """Tests for BehavioralLearner class."""
    
    def test_create_learner(self):
        """Test creating a learner."""
        learner = BehavioralLearner()
        
        assert learner.profile is None
    
    def test_create_learner_with_profile(self):
        """Test creating learner with profile."""
        profile = UserProfile()
        learner = BehavioralLearner(profile=profile)
        
        assert learner.profile == profile
    
    def test_set_profile(self):
        """Test setting profile."""
        learner = BehavioralLearner()
        profile = UserProfile()
        
        learner.set_profile(profile)
        
        assert learner.profile == profile
    
    def test_get_reward_success(self):
        """Test reward for successful event."""
        learner = BehavioralLearner()
        
        event = CommandEvent(intent="test", success=True)
        reward = learner.get_reward(event)
        
        assert reward > 0
    
    def test_get_reward_failure(self):
        """Test reward for failed event."""
        learner = BehavioralLearner()
        
        event = CommandEvent(intent="test", success=False)
        reward = learner.get_reward(event)
        
        assert reward < 0
    
    def test_get_reward_fast_response(self):
        """Test bonus for fast response."""
        learner = BehavioralLearner()
        
        fast_event = CommandEvent(intent="test", success=True, duration_ms=100)
        slow_event = CommandEvent(intent="test", success=True, duration_ms=3000)
        
        fast_reward = learner.get_reward(fast_event)
        slow_reward = learner.get_reward(slow_event)
        
        assert fast_reward > slow_reward
    
    def test_get_reward_cancelled(self):
        """Test penalty for cancellation."""
        learner = BehavioralLearner()
        
        normal = CommandEvent(intent="test", success=True)
        cancelled = CommandEvent(intent="test", success=True, cancelled=True)
        
        assert learner.get_reward(normal) > learner.get_reward(cancelled)
    
    def test_get_reward_corrected(self):
        """Test penalty for correction."""
        learner = BehavioralLearner()
        
        normal = CommandEvent(intent="test", success=True)
        corrected = CommandEvent(intent="test", success=True, corrected=True)
        
        assert learner.get_reward(normal) > learner.get_reward(corrected)
    
    def test_observe_updates_q_values(self):
        """Test that observe updates Q-values."""
        learner = BehavioralLearner()
        
        event = CommandEvent(intent="open_app", success=True)
        learner.observe(event)
        
        q_values = learner.get_q_values()
        assert "open_app" in q_values
    
    def test_observe_updates_action_counts(self):
        """Test that observe updates action counts."""
        learner = BehavioralLearner()
        
        event = CommandEvent(intent="open_app", success=True)
        learner.observe(event)
        learner.observe(event)
        
        counts = learner.get_action_counts()
        assert counts["open_app"] == 2
    
    def test_observe_with_profile(self):
        """Test observe updates profile."""
        profile = UserProfile()
        learner = BehavioralLearner(profile=profile)
        
        event = CommandEvent(intent="test", success=True)
        learner.observe(event)
        
        assert profile.total_interactions == 1
        assert profile.successful_interactions == 1
    
    def test_observe_updates_sequences(self):
        """Test observe tracks sequences."""
        profile = UserProfile()
        learner = BehavioralLearner(profile=profile)
        
        event1 = CommandEvent(intent="action_a", success=True)
        event2 = CommandEvent(intent="action_b", success=True)
        
        learner.observe(event1)
        learner.observe(event2)
        
        prob = profile.get_sequence_probability("action_a", "action_b")
        assert prob > 0
    
    def test_update_preferences_positive(self):
        """Test positive reward increases preference."""
        learner = BehavioralLearner()
        
        learner.update_preferences("test_intent", 1.0)
        learner.update_preferences("test_intent", 1.0)
        
        q_values = learner.get_q_values()
        assert q_values["test_intent"] > 0
    
    def test_update_preferences_negative(self):
        """Test negative reward decreases preference."""
        learner = BehavioralLearner()
        
        # Start with positive
        learner.update_preferences("test_intent", 1.0)
        # Then negative
        learner.update_preferences("test_intent", -1.0)
        learner.update_preferences("test_intent", -1.0)
        
        q_values = learner.get_q_values()
        # Should have decreased
        assert q_values["test_intent"] < 0.5
    
    def test_predict_next_empty(self):
        """Test predict with no history."""
        learner = BehavioralLearner()
        
        predictions = learner.predict_next()
        
        assert predictions == []
    
    def test_predict_next_with_q_values(self):
        """Test predict uses Q-values."""
        learner = BehavioralLearner()
        
        # Build up some Q-values
        for _ in range(5):
            event = CommandEvent(intent="popular", success=True)
            learner.observe(event)
        
        predictions = learner.predict_next()
        
        assert len(predictions) > 0
        assert any(p.intent == "popular" for p in predictions)
    
    def test_predict_next_with_sequences(self):
        """Test predict uses sequences."""
        profile = UserProfile()
        learner = BehavioralLearner(profile=profile)
        
        # Build sequence pattern
        for _ in range(10):
            learner.observe(CommandEvent(intent="first", success=True))
            learner.observe(CommandEvent(intent="second", success=True))
        
        predictions = learner.predict_next()
        
        # Should predict "second" after observing "first" last
        assert any(p.intent == "second" for p in predictions)
    
    def test_reset(self):
        """Test reset clears state."""
        learner = BehavioralLearner()
        
        learner.observe(CommandEvent(intent="test", success=True))
        learner.reset()
        
        assert learner.get_q_values() == {}
        assert learner.get_action_counts() == {}


class TestFactory:
    """Tests for factory function."""
    
    def test_create_behavioral_learner(self):
        """Test factory function."""
        learner = create_behavioral_learner()
        
        assert learner is not None
        assert isinstance(learner, BehavioralLearner)
    
    def test_create_with_profile(self):
        """Test factory with profile."""
        profile = UserProfile()
        learner = create_behavioral_learner(profile=profile)
        
        assert learner.profile == profile
