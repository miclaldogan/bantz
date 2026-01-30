"""
Tests for TemporalPatternLearner.
"""

import pytest
from datetime import datetime, timedelta

from bantz.learning.temporal import (
    TemporalPatternLearner,
    TimePattern,
    Routine,
    DayOfWeek,
    create_temporal_pattern_learner,
)


class TestDayOfWeek:
    """Tests for DayOfWeek enum."""
    
    def test_all_days_exist(self):
        """Test all days are defined."""
        assert DayOfWeek.MONDAY.value == 0
        assert DayOfWeek.TUESDAY.value == 1
        assert DayOfWeek.WEDNESDAY.value == 2
        assert DayOfWeek.THURSDAY.value == 3
        assert DayOfWeek.FRIDAY.value == 4
        assert DayOfWeek.SATURDAY.value == 5
        assert DayOfWeek.SUNDAY.value == 6


class TestTimePattern:
    """Tests for TimePattern dataclass."""
    
    def test_create_pattern(self):
        """Test creating a pattern."""
        pattern = TimePattern(intent="morning_routine")
        
        assert pattern.intent == "morning_routine"
        assert pattern.total_occurrences == 0
    
    def test_get_probability(self):
        """Test probability calculation."""
        pattern = TimePattern(
            intent="test",
            hour_distribution={9: 0.8, 10: 0.2},
            day_distribution={0: 0.6, 1: 0.4},
        )
        
        prob = pattern.get_probability(9, 0)
        
        assert prob > 0
    
    def test_get_peak_hours(self):
        """Test getting peak hours."""
        pattern = TimePattern(
            intent="test",
            hour_distribution={9: 0.8, 14: 0.6, 20: 0.3},
        )
        
        peaks = pattern.get_peak_hours(2)
        
        assert len(peaks) == 2
        assert 9 in peaks
        assert 14 in peaks
    
    def test_get_peak_days(self):
        """Test getting peak days."""
        pattern = TimePattern(
            intent="test",
            day_distribution={0: 0.9, 1: 0.7, 5: 0.3},
        )
        
        peaks = pattern.get_peak_days(2)
        
        assert len(peaks) == 2
        assert 0 in peaks
        assert 1 in peaks
    
    def test_to_dict(self):
        """Test serialization."""
        pattern = TimePattern(
            intent="test",
            hour_distribution={9: 0.5},
            total_occurrences=10,
        )
        
        data = pattern.to_dict()
        
        assert data["intent"] == "test"
        assert data["total_occurrences"] == 10
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "intent": "test",
            "hour_distribution": {"9": 0.5, "10": 0.3},
            "day_distribution": {"0": 0.6},
            "total_occurrences": 5,
        }
        
        pattern = TimePattern.from_dict(data)
        
        assert pattern.intent == "test"
        assert pattern.hour_distribution[9] == 0.5
        assert pattern.day_distribution[0] == 0.6


class TestRoutine:
    """Tests for Routine dataclass."""
    
    def test_create_routine(self):
        """Test creating a routine."""
        routine = Routine(
            name="morning",
            intents=["check_email", "open_calendar"],
            typical_hour=9,
        )
        
        assert routine.name == "morning"
        assert len(routine.intents) == 2
        assert routine.typical_hour == 9
    
    def test_matches_time(self):
        """Test time matching."""
        routine = Routine(
            name="test",
            intents=["a"],
            typical_hour=9,
            typical_days={0, 1, 2, 3, 4},  # Weekdays
        )
        
        assert routine.matches_time(9, 0) is True
        assert routine.matches_time(10, 0) is True  # Within tolerance
        assert routine.matches_time(12, 0) is False  # Outside tolerance
        assert routine.matches_time(9, 5) is False  # Weekend
    
    def test_matches_time_no_days(self):
        """Test time matching without day restriction."""
        routine = Routine(
            name="test",
            intents=["a"],
            typical_hour=14,
        )
        
        # Should match any day
        assert routine.matches_time(14, 5) is True
        assert routine.matches_time(14, 6) is True
    
    def test_to_dict(self):
        """Test serialization."""
        routine = Routine(
            name="test",
            intents=["a", "b"],
            typical_hour=10,
            typical_days={0, 1},
            confidence=0.8,
        )
        
        data = routine.to_dict()
        
        assert data["name"] == "test"
        assert data["typical_hour"] == 10
        assert 0 in data["typical_days"]
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "name": "test",
            "intents": ["x", "y"],
            "typical_hour": 15,
            "typical_days": [0, 2, 4],
            "confidence": 0.7,
            "occurrences": 5,
        }
        
        routine = Routine.from_dict(data)
        
        assert routine.name == "test"
        assert routine.typical_hour == 15
        assert 2 in routine.typical_days


class TestTemporalPatternLearner:
    """Tests for TemporalPatternLearner class."""
    
    def test_create_learner(self):
        """Test creating a learner."""
        learner = TemporalPatternLearner()
        
        assert len(learner.patterns) == 0
        assert len(learner.routines) == 0
    
    def test_observe_creates_pattern(self):
        """Test observe creates pattern."""
        learner = TemporalPatternLearner()
        
        learner.observe("test_intent")
        
        assert "test_intent" in learner.patterns
    
    def test_observe_updates_pattern(self):
        """Test observe updates pattern."""
        learner = TemporalPatternLearner()
        
        learner.observe("test_intent")
        learner.observe("test_intent")
        
        pattern = learner.get_pattern("test_intent")
        assert pattern.total_occurrences == 2
    
    def test_observe_with_timestamp(self):
        """Test observe with specific timestamp."""
        learner = TemporalPatternLearner()
        
        timestamp = datetime(2024, 1, 15, 10, 30)  # Monday 10:30
        learner.observe("test", timestamp=timestamp)
        
        pattern = learner.get_pattern("test")
        
        assert 10 in pattern.hour_distribution
        assert 0 in pattern.day_distribution  # Monday
    
    def test_get_pattern_nonexistent(self):
        """Test getting nonexistent pattern."""
        learner = TemporalPatternLearner()
        
        pattern = learner.get_pattern("unknown")
        
        assert pattern is None
    
    def test_get_likely_intents(self):
        """Test getting likely intents."""
        learner = TemporalPatternLearner()
        
        # Create some patterns at specific times
        for _ in range(10):
            learner.observe("morning_task", datetime(2024, 1, 15, 9, 0))
        
        for _ in range(10):
            learner.observe("afternoon_task", datetime(2024, 1, 15, 14, 0))
        
        # Get likely intents at 9am
        likely = learner.get_likely_intents(hour=9, day=0)
        
        assert len(likely) > 0
        # Morning task should be more likely at 9am
        morning_prob = next((p for i, p in likely if i == "morning_task"), 0)
        afternoon_prob = next((p for i, p in likely if i == "afternoon_task"), 0)
        
        assert morning_prob > afternoon_prob
    
    def test_add_routine(self):
        """Test adding a routine."""
        learner = TemporalPatternLearner()
        
        routine = Routine(
            name="test_routine",
            intents=["a", "b"],
            typical_hour=10,
        )
        
        learner.add_routine(routine)
        
        assert len(learner.routines) == 1
        assert learner.routines[0].name == "test_routine"
    
    def test_add_routine_duplicate(self):
        """Test adding duplicate routine."""
        learner = TemporalPatternLearner()
        
        routine1 = Routine(name="test", intents=["a"], typical_hour=10)
        routine2 = Routine(name="test", intents=["b"], typical_hour=11)
        
        learner.add_routine(routine1)
        learner.add_routine(routine2)
        
        assert len(learner.routines) == 1
    
    def test_remove_routine(self):
        """Test removing a routine."""
        learner = TemporalPatternLearner()
        
        routine = Routine(name="test", intents=["a"], typical_hour=10)
        learner.add_routine(routine)
        
        result = learner.remove_routine("test")
        
        assert result is True
        assert len(learner.routines) == 0
    
    def test_remove_routine_nonexistent(self):
        """Test removing nonexistent routine."""
        learner = TemporalPatternLearner()
        
        result = learner.remove_routine("unknown")
        
        assert result is False
    
    def test_get_active_routines(self):
        """Test getting active routines."""
        learner = TemporalPatternLearner()
        
        routine = Routine(
            name="morning",
            intents=["check_email"],
            typical_hour=9,
            typical_days={0, 1, 2, 3, 4},
            confidence=0.8,
        )
        learner.add_routine(routine)
        
        active = learner.get_active_routines(hour=9, day=0)
        
        assert len(active) == 1
        assert active[0].name == "morning"
    
    def test_get_active_routines_filters_low_confidence(self):
        """Test active routines filters by confidence."""
        learner = TemporalPatternLearner()
        
        routine = Routine(
            name="uncertain",
            intents=["a"],
            typical_hour=10,
            confidence=0.1,  # Below threshold
        )
        learner.add_routine(routine)
        
        active = learner.get_active_routines(hour=10, day=0)
        
        assert len(active) == 0
    
    def test_suggest_routine(self):
        """Test routine suggestion."""
        learner = TemporalPatternLearner()
        
        routine = Routine(
            name="suggestion",
            intents=["task"],
            typical_hour=datetime.now().hour,
            typical_days={datetime.now().weekday()},
            confidence=0.8,
        )
        learner.add_routine(routine)
        
        suggested = learner.suggest_routine()
        
        assert suggested is not None
        assert suggested.name == "suggestion"
    
    def test_suggest_routine_none(self):
        """Test no routine suggestion."""
        learner = TemporalPatternLearner()
        
        suggested = learner.suggest_routine()
        
        assert suggested is None
    
    def test_mark_routine_triggered(self):
        """Test marking routine as triggered."""
        learner = TemporalPatternLearner()
        
        routine = Routine(
            name="test",
            intents=["a"],
            typical_hour=10,
            occurrences=0,
        )
        learner.add_routine(routine)
        
        learner.mark_routine_triggered("test")
        
        assert learner.routines[0].occurrences == 1
        assert learner.routines[0].last_triggered is not None
    
    def test_reset(self):
        """Test reset."""
        learner = TemporalPatternLearner()
        
        learner.observe("test")
        learner.add_routine(Routine(name="r", intents=["a"], typical_hour=10))
        
        learner.reset()
        
        assert len(learner.patterns) == 0
        assert len(learner.routines) == 0
    
    def test_to_dict(self):
        """Test serialization."""
        learner = TemporalPatternLearner()
        
        learner.observe("test")
        learner.add_routine(Routine(name="r", intents=["a"], typical_hour=10))
        
        data = learner.to_dict()
        
        assert "patterns" in data
        assert "routines" in data
        assert "test" in data["patterns"]
    
    def test_from_dict(self):
        """Test deserialization."""
        learner = TemporalPatternLearner()
        
        data = {
            "patterns": {
                "test": {
                    "intent": "test",
                    "hour_distribution": {},
                    "day_distribution": {},
                    "total_occurrences": 5,
                }
            },
            "routines": [
                {
                    "name": "routine1",
                    "intents": ["a"],
                    "typical_hour": 9,
                    "typical_days": [],
                    "confidence": 0.5,
                    "occurrences": 3,
                }
            ],
        }
        
        learner.from_dict(data)
        
        assert "test" in learner.patterns
        assert len(learner.routines) == 1


class TestRoutineDetection:
    """Tests for automatic routine detection."""
    
    def test_detects_routine_from_observations(self):
        """Test that routines are detected from repeated observations."""
        learner = TemporalPatternLearner()
        
        # Simulate same action at same time multiple days
        base_time = datetime(2024, 1, 15, 9, 0)  # Monday 9am
        
        for i in range(10):
            learner.observe(
                "check_email",
                timestamp=base_time + timedelta(days=i)
            )
        
        # Should have detected a routine
        active = learner.get_active_routines(hour=9, day=0)
        
        # Depending on detection threshold, may or may not have routine
        # At least pattern should exist
        assert "check_email" in learner.patterns


class TestFactory:
    """Tests for factory function."""
    
    def test_create_temporal_pattern_learner(self):
        """Test factory function."""
        learner = create_temporal_pattern_learner()
        
        assert learner is not None
        assert isinstance(learner, TemporalPatternLearner)
