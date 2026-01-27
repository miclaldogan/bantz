"""
Temporal Pattern Learner module.

Learns time-based patterns and routines from user behavior.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class DayOfWeek(Enum):
    """Days of the week."""
    
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass
class TimePattern:
    """A detected time-based pattern."""
    
    intent: str
    """The intent this pattern is for."""
    
    hour_distribution: Dict[int, float] = field(default_factory=dict)
    """Probability distribution over hours (0-23)."""
    
    day_distribution: Dict[int, float] = field(default_factory=dict)
    """Probability distribution over days (0-6, Monday=0)."""
    
    total_occurrences: int = 0
    """Total times this intent occurred."""
    
    def get_probability(self, hour: int, day: int) -> float:
        """Get probability for a specific hour and day."""
        hour_prob = self.hour_distribution.get(hour, 0.0)
        day_prob = self.day_distribution.get(day, 0.0)
        
        # Combined probability
        if hour_prob == 0 or day_prob == 0:
            return max(hour_prob, day_prob) * 0.5
        return (hour_prob + day_prob) / 2
    
    def get_peak_hours(self, n: int = 3) -> List[int]:
        """Get the n most likely hours."""
        sorted_hours = sorted(
            self.hour_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [h for h, _ in sorted_hours[:n]]
    
    def get_peak_days(self, n: int = 3) -> List[int]:
        """Get the n most likely days."""
        sorted_days = sorted(
            self.day_distribution.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return [d for d, _ in sorted_days[:n]]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "hour_distribution": self.hour_distribution,
            "day_distribution": self.day_distribution,
            "total_occurrences": self.total_occurrences,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimePattern":
        """Create from dictionary."""
        # Convert string keys back to int
        hour_dist = {int(k): v for k, v in data.get("hour_distribution", {}).items()}
        day_dist = {int(k): v for k, v in data.get("day_distribution", {}).items()}
        
        return cls(
            intent=data["intent"],
            hour_distribution=hour_dist,
            day_distribution=day_dist,
            total_occurrences=data.get("total_occurrences", 0),
        )


@dataclass
class Routine:
    """A detected routine (sequence of intents at regular times)."""
    
    name: str
    """Routine name/identifier."""
    
    intents: List[str]
    """Sequence of intents in this routine."""
    
    typical_hour: int
    """Typical hour this routine occurs."""
    
    typical_days: Set[int] = field(default_factory=set)
    """Days this routine typically occurs (0-6)."""
    
    confidence: float = 0.0
    """Confidence in this routine detection."""
    
    occurrences: int = 0
    """How many times this routine was detected."""
    
    last_triggered: Optional[datetime] = None
    """When this routine was last triggered."""
    
    def matches_time(self, hour: int, day: int, tolerance: int = 1) -> bool:
        """Check if current time matches this routine."""
        hour_match = abs(hour - self.typical_hour) <= tolerance
        day_match = day in self.typical_days if self.typical_days else True
        return hour_match and day_match
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "intents": self.intents,
            "typical_hour": self.typical_hour,
            "typical_days": list(self.typical_days),
            "confidence": self.confidence,
            "occurrences": self.occurrences,
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Routine":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            intents=data["intents"],
            typical_hour=data["typical_hour"],
            typical_days=set(data.get("typical_days", [])),
            confidence=data.get("confidence", 0.0),
            occurrences=data.get("occurrences", 0),
            last_triggered=datetime.fromisoformat(data["last_triggered"]) if data.get("last_triggered") else None,
        )


class TemporalPatternLearner:
    """
    Learns temporal patterns from user behavior.
    
    Detects:
    - Time preferences for intents
    - Daily/weekly routines
    - Seasonal patterns
    """
    
    # Minimum occurrences for pattern detection
    MIN_OCCURRENCES = 3
    
    # Probability threshold for pattern
    PATTERN_THRESHOLD = 0.15
    
    # Routine detection window (hours)
    ROUTINE_WINDOW_HOURS = 2
    
    # Minimum routine confidence
    MIN_ROUTINE_CONFIDENCE = 0.3
    
    def __init__(self):
        """Initialize the temporal pattern learner."""
        self._patterns: Dict[str, TimePattern] = {}
        self._routines: List[Routine] = []
        self._recent_events: List[Tuple[str, datetime]] = []
        self._event_buffer: List[Tuple[str, datetime]] = []
    
    @property
    def patterns(self) -> Dict[str, TimePattern]:
        """Get all patterns."""
        return self._patterns
    
    @property
    def routines(self) -> List[Routine]:
        """Get all routines."""
        return self._routines
    
    def observe(self, intent: str, timestamp: Optional[datetime] = None) -> None:
        """
        Observe an event and update patterns.
        
        Args:
            intent: The intent that occurred.
            timestamp: When it occurred (default: now).
        """
        timestamp = timestamp or datetime.now()
        hour = timestamp.hour
        day = timestamp.weekday()
        
        # Update pattern
        self._update_pattern(intent, hour, day)
        
        # Track for routine detection
        self._event_buffer.append((intent, timestamp))
        self._recent_events.append((intent, timestamp))
        
        # Limit buffers
        if len(self._event_buffer) > 100:
            self._event_buffer.pop(0)
        if len(self._recent_events) > 1000:
            self._recent_events.pop(0)
        
        # Check for routine patterns
        self._detect_routines()
    
    def get_pattern(self, intent: str) -> Optional[TimePattern]:
        """Get pattern for an intent."""
        return self._patterns.get(intent)
    
    def get_likely_intents(
        self,
        hour: Optional[int] = None,
        day: Optional[int] = None,
        n: int = 5,
    ) -> List[Tuple[str, float]]:
        """
        Get likely intents for a given time.
        
        Args:
            hour: Hour (0-23), default: now.
            day: Day (0-6), default: now.
            n: Number of intents to return.
            
        Returns:
            List of (intent, probability) tuples.
        """
        now = datetime.now()
        hour = hour if hour is not None else now.hour
        day = day if day is not None else now.weekday()
        
        probabilities = []
        
        for intent, pattern in self._patterns.items():
            prob = pattern.get_probability(hour, day)
            if prob > 0:
                probabilities.append((intent, prob))
        
        # Sort by probability
        probabilities.sort(key=lambda x: x[1], reverse=True)
        
        return probabilities[:n]
    
    def get_active_routines(
        self,
        hour: Optional[int] = None,
        day: Optional[int] = None,
    ) -> List[Routine]:
        """
        Get routines that should be active at given time.
        
        Args:
            hour: Hour to check.
            day: Day to check.
            
        Returns:
            Matching routines.
        """
        now = datetime.now()
        hour = hour if hour is not None else now.hour
        day = day if day is not None else now.weekday()
        
        active = []
        for routine in self._routines:
            if routine.matches_time(hour, day) and routine.confidence >= self.MIN_ROUTINE_CONFIDENCE:
                active.append(routine)
        
        return sorted(active, key=lambda r: r.confidence, reverse=True)
    
    def suggest_routine(self) -> Optional[Routine]:
        """
        Suggest a routine to execute now.
        
        Returns:
            Best matching routine or None.
        """
        active = self.get_active_routines()
        
        if not active:
            return None
        
        # Return highest confidence routine that hasn't been triggered recently
        now = datetime.now()
        for routine in active:
            if routine.last_triggered is None:
                return routine
            
            time_since = (now - routine.last_triggered).total_seconds() / 3600
            if time_since > 20:  # At least 20 hours since last trigger
                return routine
        
        return None
    
    def mark_routine_triggered(self, routine_name: str) -> None:
        """Mark a routine as triggered."""
        for routine in self._routines:
            if routine.name == routine_name:
                routine.last_triggered = datetime.now()
                routine.occurrences += 1
                break
    
    def add_routine(self, routine: Routine) -> None:
        """
        Manually add a routine.
        
        Args:
            routine: The routine to add.
        """
        # Check for duplicate
        for existing in self._routines:
            if existing.name == routine.name:
                return
        
        self._routines.append(routine)
    
    def remove_routine(self, name: str) -> bool:
        """
        Remove a routine.
        
        Args:
            name: Routine name.
            
        Returns:
            Whether routine was removed.
        """
        for i, routine in enumerate(self._routines):
            if routine.name == name:
                self._routines.pop(i)
                return True
        return False
    
    def reset(self) -> None:
        """Reset all learned patterns and routines."""
        self._patterns.clear()
        self._routines.clear()
        self._recent_events.clear()
        self._event_buffer.clear()
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            "patterns": {k: v.to_dict() for k, v in self._patterns.items()},
            "routines": [r.to_dict() for r in self._routines],
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load from dictionary."""
        patterns_data = data.get("patterns", {})
        self._patterns = {k: TimePattern.from_dict(v) for k, v in patterns_data.items()}
        
        routines_data = data.get("routines", [])
        self._routines = [Routine.from_dict(r) for r in routines_data]
    
    def _update_pattern(self, intent: str, hour: int, day: int) -> None:
        """Update pattern for an intent."""
        if intent not in self._patterns:
            self._patterns[intent] = TimePattern(intent=intent)
        
        pattern = self._patterns[intent]
        pattern.total_occurrences += 1
        
        # Update distributions with exponential moving average
        alpha = 0.1
        
        # Hour distribution
        for h in range(24):
            current = pattern.hour_distribution.get(h, 0.0)
            target = 1.0 if h == hour else 0.0
            pattern.hour_distribution[h] = current + alpha * (target - current)
        
        # Day distribution
        for d in range(7):
            current = pattern.day_distribution.get(d, 0.0)
            target = 1.0 if d == day else 0.0
            pattern.day_distribution[d] = current + alpha * (target - current)
    
    def _detect_routines(self) -> None:
        """Detect routines from event buffer."""
        if len(self._event_buffer) < 3:
            return
        
        # Look for sequences that occur at similar times
        window = timedelta(hours=self.ROUTINE_WINDOW_HOURS)
        
        # Group events by approximate time
        time_groups: Dict[str, List[Tuple[str, datetime]]] = {}
        
        for intent, ts in self._event_buffer:
            # Create time key (hour, day)
            key = f"{ts.hour}_{ts.weekday()}"
            
            if key not in time_groups:
                time_groups[key] = []
            time_groups[key].append((intent, ts))
        
        # Find repeating sequences
        for key, events in time_groups.items():
            if len(events) < self.MIN_OCCURRENCES:
                continue
            
            hour, day = map(int, key.split("_"))
            intents = [e[0] for e in events]
            
            # Find common subsequences (simplified: just check for pairs)
            intent_counts: Dict[str, int] = {}
            for intent in intents:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            
            # Get most common intent at this time
            if intent_counts:
                top_intent = max(intent_counts.items(), key=lambda x: x[1])
                
                if top_intent[1] >= self.MIN_OCCURRENCES:
                    # Check if we already have this routine
                    routine_name = f"auto_{top_intent[0]}_{hour}"
                    
                    existing = None
                    for r in self._routines:
                        if r.name == routine_name:
                            existing = r
                            break
                    
                    if existing:
                        existing.occurrences = top_intent[1]
                        existing.confidence = min(1.0, top_intent[1] / 10)
                        existing.typical_days.add(day)
                    else:
                        routine = Routine(
                            name=routine_name,
                            intents=[top_intent[0]],
                            typical_hour=hour,
                            typical_days={day},
                            confidence=min(1.0, top_intent[1] / 10),
                            occurrences=top_intent[1],
                        )
                        self._routines.append(routine)


def create_temporal_pattern_learner() -> TemporalPatternLearner:
    """
    Factory function to create a temporal pattern learner.
    
    Returns:
        Configured TemporalPatternLearner instance.
    """
    return TemporalPatternLearner()
