"""
Preference Model module.

Learns user preferences from choices, corrections, and cancellations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from bantz.learning.profile import UserProfile


class PreferenceType(Enum):
    """Types of preference learning events."""
    
    CHOICE = "choice"           # User made a choice
    CORRECTION = "correction"   # User corrected ASR
    CANCELLATION = "cancellation"  # User cancelled
    CONFIRMATION = "confirmation"  # User confirmed
    REJECTION = "rejection"     # User rejected suggestion


@dataclass
class PreferenceEntry:
    """A single preference learning entry."""
    
    type: PreferenceType
    """Type of preference event."""
    
    original: str
    """Original value/suggestion."""
    
    chosen: Optional[str] = None
    """Chosen/corrected value."""
    
    intent: Optional[str] = None
    """Related intent."""
    
    context: Dict[str, Any] = field(default_factory=dict)
    """Event context."""
    
    timestamp: datetime = field(default_factory=datetime.now)
    """When this occurred."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "original": self.original,
            "chosen": self.chosen,
            "intent": self.intent,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreferenceEntry":
        """Create from dictionary."""
        return cls(
            type=PreferenceType(data["type"]),
            original=data["original"],
            chosen=data.get("chosen"),
            intent=data.get("intent"),
            context=data.get("context", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
        )


class PreferenceModel:
    """
    Model for learning user preferences from interactions.
    
    Learns from:
    - Choices: What user selects among options
    - Corrections: How user corrects ASR transcriptions
    - Cancellations: What user cancels (negative signal)
    """
    
    # Learning weights
    CHOICE_WEIGHT = 1.0
    CORRECTION_WEIGHT = 0.8
    CANCELLATION_WEIGHT = -0.6
    CONFIRMATION_WEIGHT = 0.5
    REJECTION_WEIGHT = -0.4
    
    # Decay factor for old preferences
    DECAY_FACTOR = 0.95
    
    def __init__(
        self,
        profile: Optional[UserProfile] = None,
        max_history: int = 1000,
    ):
        """
        Initialize preference model.
        
        Args:
            profile: User profile to update.
            max_history: Max entries to keep.
        """
        self._profile = profile
        self._max_history = max_history
        self._history: List[PreferenceEntry] = []
        
        # Learned preferences
        self._word_preferences: Dict[str, Dict[str, float]] = {}  # wrong -> correct -> weight
        self._intent_preferences: Dict[str, float] = {}  # intent -> preference score
        self._app_preferences: Dict[str, float] = {}  # app -> preference score
        self._parameter_preferences: Dict[str, Dict[str, float]] = {}  # param_name -> value -> weight
    
    @property
    def profile(self) -> Optional[UserProfile]:
        """Get current profile."""
        return self._profile
    
    def set_profile(self, profile: UserProfile) -> None:
        """Set user profile."""
        self._profile = profile
    
    def learn_from_choice(
        self,
        options: List[str],
        chosen: str,
        intent: Optional[str] = None,
        context: Dict = None,
    ) -> None:
        """
        Learn from a user choice among options.
        
        Args:
            options: Available options.
            chosen: The option user chose.
            intent: Related intent.
            context: Additional context.
        """
        context = context or {}
        
        # Record entry
        entry = PreferenceEntry(
            type=PreferenceType.CHOICE,
            original=",".join(options),
            chosen=chosen,
            intent=intent,
            context=context,
        )
        self._add_entry(entry)
        
        # Boost chosen
        if intent:
            self._update_intent_preference(intent, self.CHOICE_WEIGHT)
        
        # Update parameter preferences if in context
        for key, value in context.items():
            if key.startswith("param_"):
                param_name = key[6:]
                self._update_parameter_preference(param_name, str(value), self.CHOICE_WEIGHT)
        
        # Record in profile
        if self._profile and intent:
            self._profile.update_intent_preference(intent, self.CHOICE_WEIGHT * 0.1)
    
    def learn_from_correction(
        self,
        original: str,
        corrected: str,
        intent: Optional[str] = None,
        context: Dict = None,
    ) -> None:
        """
        Learn from ASR correction.
        
        Args:
            original: Original transcription.
            corrected: User's correction.
            intent: Related intent.
            context: Additional context.
        """
        context = context or {}
        
        # Record entry
        entry = PreferenceEntry(
            type=PreferenceType.CORRECTION,
            original=original,
            chosen=corrected,
            intent=intent,
            context=context,
        )
        self._add_entry(entry)
        
        # Learn word correction
        self._learn_word_correction(original, corrected)
        
        # Slight negative signal for intent (had to correct)
        if intent:
            self._update_intent_preference(intent, -self.CORRECTION_WEIGHT * 0.5)
    
    def learn_from_cancellation(
        self,
        intent: str,
        reason: Optional[str] = None,
        context: Dict = None,
    ) -> None:
        """
        Learn from user cancellation.
        
        Args:
            intent: The intent that was cancelled.
            reason: Optional cancellation reason.
            context: Additional context.
        """
        context = context or {}
        if reason:
            context["reason"] = reason
        
        # Record entry
        entry = PreferenceEntry(
            type=PreferenceType.CANCELLATION,
            original=intent,
            intent=intent,
            context=context,
        )
        self._add_entry(entry)
        
        # Negative signal for intent
        self._update_intent_preference(intent, self.CANCELLATION_WEIGHT)
        
        # Update profile
        if self._profile:
            self._profile.update_intent_preference(intent, self.CANCELLATION_WEIGHT * 0.1)
    
    def learn_from_confirmation(
        self,
        intent: str,
        context: Dict = None,
    ) -> None:
        """
        Learn from user confirmation.
        
        Args:
            intent: The intent that was confirmed.
            context: Additional context.
        """
        context = context or {}
        
        # Record entry
        entry = PreferenceEntry(
            type=PreferenceType.CONFIRMATION,
            original=intent,
            intent=intent,
            context=context,
        )
        self._add_entry(entry)
        
        # Positive signal
        self._update_intent_preference(intent, self.CONFIRMATION_WEIGHT)
        
        # Update profile
        if self._profile:
            self._profile.update_intent_preference(intent, self.CONFIRMATION_WEIGHT * 0.1)
    
    def learn_from_rejection(
        self,
        suggestion: str,
        intent: Optional[str] = None,
        context: Dict = None,
    ) -> None:
        """
        Learn from user rejecting a suggestion.
        
        Args:
            suggestion: The rejected suggestion.
            intent: Related intent.
            context: Additional context.
        """
        context = context or {}
        
        # Record entry
        entry = PreferenceEntry(
            type=PreferenceType.REJECTION,
            original=suggestion,
            intent=intent,
            context=context,
        )
        self._add_entry(entry)
        
        # Negative signal
        if intent:
            self._update_intent_preference(intent, self.REJECTION_WEIGHT)
            
            if self._profile:
                self._profile.update_intent_preference(intent, self.REJECTION_WEIGHT * 0.1)
    
    def get_correction_suggestion(self, word: str) -> Optional[str]:
        """
        Get correction suggestion for a word.
        
        Args:
            word: Word to get suggestion for.
            
        Returns:
            Suggested correction or None.
        """
        if word not in self._word_preferences:
            return None
        
        corrections = self._word_preferences[word]
        if not corrections:
            return None
        
        # Return highest weighted correction
        best = max(corrections.items(), key=lambda x: x[1])
        if best[1] > 0.5:  # Threshold
            return best[0]
        
        return None
    
    def get_intent_preference(self, intent: str) -> float:
        """
        Get preference score for an intent.
        
        Args:
            intent: The intent.
            
        Returns:
            Preference score (-1.0 to 1.0).
        """
        return self._intent_preferences.get(intent, 0.0)
    
    def get_top_intents(self, n: int = 5) -> List[tuple]:
        """
        Get top preferred intents.
        
        Args:
            n: Number to return.
            
        Returns:
            List of (intent, score) tuples.
        """
        sorted_intents = sorted(
            self._intent_preferences.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_intents[:n]
    
    def get_parameter_preference(self, param_name: str, value: str) -> float:
        """
        Get preference for a parameter value.
        
        Args:
            param_name: Parameter name.
            value: Value to check.
            
        Returns:
            Preference weight.
        """
        if param_name not in self._parameter_preferences:
            return 0.0
        return self._parameter_preferences[param_name].get(value, 0.0)
    
    def get_history(
        self,
        type_filter: Optional[PreferenceType] = None,
        limit: int = 100,
    ) -> List[PreferenceEntry]:
        """
        Get preference history.
        
        Args:
            type_filter: Filter by type.
            limit: Max entries.
            
        Returns:
            List of entries.
        """
        entries = self._history
        
        if type_filter:
            entries = [e for e in entries if e.type == type_filter]
        
        return entries[-limit:]
    
    def decay_preferences(self) -> None:
        """Apply decay to old preferences."""
        for intent in self._intent_preferences:
            self._intent_preferences[intent] *= self.DECAY_FACTOR
        
        for param in self._parameter_preferences:
            for value in self._parameter_preferences[param]:
                self._parameter_preferences[param][value] *= self.DECAY_FACTOR
    
    def reset(self) -> None:
        """Reset all learned preferences."""
        self._history.clear()
        self._word_preferences.clear()
        self._intent_preferences.clear()
        self._app_preferences.clear()
        self._parameter_preferences.clear()
    
    def to_dict(self) -> Dict[str, Any]:
        """Export preferences to dictionary."""
        return {
            "word_preferences": self._word_preferences,
            "intent_preferences": self._intent_preferences,
            "app_preferences": self._app_preferences,
            "parameter_preferences": self._parameter_preferences,
            "history": [e.to_dict() for e in self._history[-100:]],  # Last 100
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load preferences from dictionary."""
        self._word_preferences = data.get("word_preferences", {})
        self._intent_preferences = data.get("intent_preferences", {})
        self._app_preferences = data.get("app_preferences", {})
        self._parameter_preferences = data.get("parameter_preferences", {})
        
        history_data = data.get("history", [])
        self._history = [PreferenceEntry.from_dict(e) for e in history_data]
    
    def _add_entry(self, entry: PreferenceEntry) -> None:
        """Add entry to history."""
        self._history.append(entry)
        
        # Trim if too large
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
    
    def _update_intent_preference(self, intent: str, delta: float) -> None:
        """Update intent preference score."""
        current = self._intent_preferences.get(intent, 0.0)
        new_value = current + delta
        # Clamp to [-1, 1]
        self._intent_preferences[intent] = max(-1.0, min(1.0, new_value))
    
    def _update_parameter_preference(self, param: str, value: str, delta: float) -> None:
        """Update parameter preference."""
        if param not in self._parameter_preferences:
            self._parameter_preferences[param] = {}
        
        current = self._parameter_preferences[param].get(value, 0.0)
        self._parameter_preferences[param][value] = current + delta
    
    def _learn_word_correction(self, original: str, corrected: str) -> None:
        """Learn word-level corrections."""
        orig_words = original.lower().split()
        corr_words = corrected.lower().split()
        
        # Simple word alignment (for same length)
        if len(orig_words) == len(corr_words):
            for ow, cw in zip(orig_words, corr_words):
                if ow != cw:
                    if ow not in self._word_preferences:
                        self._word_preferences[ow] = {}
                    
                    current = self._word_preferences[ow].get(cw, 0.0)
                    self._word_preferences[ow][cw] = current + self.CORRECTION_WEIGHT


def create_preference_model(
    profile: Optional[UserProfile] = None,
    max_history: int = 1000,
) -> PreferenceModel:
    """
    Factory function to create a preference model.
    
    Args:
        profile: User profile to update.
        max_history: Max history entries.
        
    Returns:
        Configured PreferenceModel instance.
    """
    return PreferenceModel(
        profile=profile,
        max_history=max_history,
    )
