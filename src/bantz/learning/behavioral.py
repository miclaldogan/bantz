"""
Behavioral Learner module.

RL-style learning system that observes user behavior and learns preferences.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from bantz.learning.profile import UserProfile


class EventBus(Protocol):
    """Protocol for event bus."""
    
    async def emit(self, event: str, data: dict) -> None:
        """Emit an event."""
        ...


class RewardSignal(Enum):
    """Reward signal types."""
    
    # Positive signals
    SUCCESS = "success"           # Komut başarılı (+1.0)
    FAST_RESPONSE = "fast"        # Hızlı yanıt (+0.2)
    REPEAT_USE = "repeat"         # Tekrar kullanım (+0.5)
    NO_CORRECTION = "no_correct"  # Düzeltme yok (+0.3)
    SEQUENCE_COMPLETE = "sequence" # Dizi tamamlama (+0.4)
    
    # Negative signals
    FAILURE = "failure"           # Komut başarısız (-1.0)
    CANCELLED = "cancelled"       # Kullanıcı iptal (-0.8)
    CORRECTED = "corrected"       # Manuel düzeltme (-0.5)
    SLOW_RESPONSE = "slow"        # Uzun bekleme (-0.3)
    REPEAT_REQUEST = "repeat_req" # Tekrar etme (-0.4)


# Reward values for each signal
REWARD_VALUES = {
    RewardSignal.SUCCESS: 1.0,
    RewardSignal.FAST_RESPONSE: 0.2,
    RewardSignal.REPEAT_USE: 0.5,
    RewardSignal.NO_CORRECTION: 0.3,
    RewardSignal.SEQUENCE_COMPLETE: 0.4,
    RewardSignal.FAILURE: -1.0,
    RewardSignal.CANCELLED: -0.8,
    RewardSignal.CORRECTED: -0.5,
    RewardSignal.SLOW_RESPONSE: -0.3,
    RewardSignal.REPEAT_REQUEST: -0.4,
}


@dataclass
class CommandEvent:
    """Represents a command/interaction event."""
    
    intent: str
    """The intent/action type."""
    
    parameters: Dict[str, Any] = field(default_factory=dict)
    """Action parameters."""
    
    timestamp: datetime = field(default_factory=datetime.now)
    """When the event occurred."""
    
    success: bool = True
    """Whether the action succeeded."""
    
    duration_ms: float = 0.0
    """Execution duration in milliseconds."""
    
    cancelled: bool = False
    """Whether user cancelled."""
    
    corrected: bool = False
    """Whether user corrected ASR."""
    
    context: Dict[str, Any] = field(default_factory=dict)
    """Additional context."""
    
    app: Optional[str] = None
    """Associated app (if any)."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "parameters": self.parameters,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "duration_ms": self.duration_ms,
            "cancelled": self.cancelled,
            "corrected": self.corrected,
            "context": self.context,
            "app": self.app,
        }


@dataclass
class Prediction:
    """A prediction for next action."""
    
    intent: str
    """Predicted intent."""
    
    confidence: float
    """Confidence score (0.0 - 1.0)."""
    
    parameters: Dict[str, Any] = field(default_factory=dict)
    """Predicted parameters."""
    
    reason: str = ""
    """Why this was predicted."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "parameters": self.parameters,
            "reason": self.reason,
        }


class BehavioralLearner:
    """
    RL-style behavioral learning system.
    
    Observes user events, calculates rewards, and updates preferences
    using Q-learning style updates.
    """
    
    # Learning rate for Q-updates
    LEARNING_RATE = 0.1
    
    # Discount factor for future rewards
    DISCOUNT_FACTOR = 0.9
    
    # Threshold for "fast" response (ms)
    FAST_THRESHOLD_MS = 200.0
    
    # Threshold for "slow" response (ms)
    SLOW_THRESHOLD_MS = 2000.0
    
    # Time window for repeat detection (seconds)
    REPEAT_WINDOW_SECONDS = 86400  # 24 hours
    
    def __init__(
        self,
        profile: Optional[UserProfile] = None,
        event_bus: Optional[EventBus] = None,
    ):
        """
        Initialize the behavioral learner.
        
        Args:
            profile: User profile to learn into.
            event_bus: Optional event bus for notifications.
        """
        self._profile = profile
        self._event_bus = event_bus
        self._recent_events: List[CommandEvent] = []
        self._q_values: Dict[str, float] = {}  # intent -> Q-value
        self._action_counts: Dict[str, int] = {}  # intent -> count
        self._last_action: Optional[str] = None
    
    @property
    def profile(self) -> Optional[UserProfile]:
        """Get current profile."""
        return self._profile
    
    def set_profile(self, profile: UserProfile) -> None:
        """Set the user profile."""
        self._profile = profile
    
    def observe(self, event: CommandEvent, context: Dict = None) -> float:
        """
        Observe an event and learn from it.
        
        Args:
            event: The command event.
            context: Additional context.
            
        Returns:
            Calculated reward value.
        """
        context = context or {}
        
        # Calculate reward
        reward = self.get_reward(event)
        
        # Update preferences
        self.update_preferences(event.intent, reward)
        
        # Update sequences
        if self._last_action:
            self._update_sequence(self._last_action, event.intent)
        
        # Update app preference if present
        if event.app:
            self._update_app_preference(event.app, reward)
        
        # Update time patterns
        self._update_time_pattern(event)
        
        # Record interaction
        if self._profile:
            self._profile.record_interaction(event.success)
            hour = event.timestamp.hour
            self._profile.update_active_hour(hour)
        
        # Track recent events
        self._recent_events.append(event)
        if len(self._recent_events) > 100:
            self._recent_events.pop(0)
        
        # Update last action
        self._last_action = event.intent
        
        # Emit event
        if self._event_bus:
            import asyncio
            asyncio.create_task(self._event_bus.emit("behavior_observed", {
                "intent": event.intent,
                "reward": reward,
            }))
        
        return reward
    
    def get_reward(self, event: CommandEvent) -> float:
        """
        Calculate reward for an event.
        
        Args:
            event: The command event.
            
        Returns:
            Total reward value.
        """
        total_reward = 0.0
        
        # Base reward from success/failure
        if event.success:
            total_reward += REWARD_VALUES[RewardSignal.SUCCESS]
        else:
            total_reward += REWARD_VALUES[RewardSignal.FAILURE]
        
        # Speed bonus/penalty
        if event.duration_ms > 0:
            if event.duration_ms < self.FAST_THRESHOLD_MS:
                total_reward += REWARD_VALUES[RewardSignal.FAST_RESPONSE]
            elif event.duration_ms > self.SLOW_THRESHOLD_MS:
                total_reward += REWARD_VALUES[RewardSignal.SLOW_RESPONSE]
        
        # Cancellation penalty
        if event.cancelled:
            total_reward += REWARD_VALUES[RewardSignal.CANCELLED]
        
        # Correction penalty
        if event.corrected:
            total_reward += REWARD_VALUES[RewardSignal.CORRECTED]
        else:
            total_reward += REWARD_VALUES[RewardSignal.NO_CORRECTION]
        
        # Check for repeat usage
        if self._is_repeat_usage(event):
            total_reward += REWARD_VALUES[RewardSignal.REPEAT_USE]
        
        # Check for sequence completion
        if self._is_sequence_completion(event):
            total_reward += REWARD_VALUES[RewardSignal.SEQUENCE_COMPLETE]
        
        return total_reward
    
    def update_preferences(self, intent: str, reward: float) -> None:
        """
        Update preferences based on reward (Q-learning style).
        
        Args:
            intent: The intent to update.
            reward: The reward value.
        """
        # Get current Q-value
        current_q = self._q_values.get(intent, 0.0)
        
        # Update count
        count = self._action_counts.get(intent, 0) + 1
        self._action_counts[intent] = count
        
        # Q-learning update: Q(s,a) = Q(s,a) + α * (r + γ * max(Q(s',a')) - Q(s,a))
        # Simplified: Q(a) = Q(a) + α * (r - Q(a))
        new_q = current_q + self.LEARNING_RATE * (reward - current_q)
        self._q_values[intent] = new_q
        
        # Update profile
        if self._profile:
            # Normalize to 0-1 range for preference
            normalized = (new_q + 2) / 4  # Assuming rewards in [-2, 2]
            normalized = max(0.0, min(1.0, normalized))
            
            delta = (normalized - self._profile.preferred_intents.get(intent, 0.5)) * self.LEARNING_RATE
            self._profile.update_intent_preference(intent, delta)
            
            # Update command frequency
            self._profile.frequent_commands[intent] = count
    
    def predict_next(self, context: Dict = None) -> List[Prediction]:
        """
        Predict next likely actions.
        
        Args:
            context: Current context.
            
        Returns:
            List of predictions sorted by confidence.
        """
        context = context or {}
        predictions = []
        
        # Sequence-based predictions
        if self._last_action and self._profile:
            for action_a, action_b, prob in self._profile.command_sequences:
                if action_a == self._last_action and prob > 0.3:
                    predictions.append(Prediction(
                        intent=action_b,
                        confidence=prob,
                        reason=f"Sık kullanılan dizi: {action_a} -> {action_b}",
                    ))
        
        # Time-based predictions
        current_hour = datetime.now().hour
        if self._profile and self._profile.time_patterns:
            for intent, hour_probs in self._profile.time_patterns.items():
                if current_hour in hour_probs and hour_probs[current_hour] > 0.3:
                    predictions.append(Prediction(
                        intent=intent,
                        confidence=hour_probs[current_hour],
                        reason=f"Bu saatte sık kullanılıyor: {intent}",
                    ))
        
        # Q-value based predictions
        if self._q_values:
            top_intents = sorted(
                self._q_values.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:3]
            
            for intent, q_value in top_intents:
                confidence = (q_value + 2) / 4  # Normalize
                confidence = max(0.0, min(1.0, confidence))
                
                if confidence > 0.5 and not any(p.intent == intent for p in predictions):
                    predictions.append(Prediction(
                        intent=intent,
                        confidence=confidence * 0.8,  # Lower weight than sequences
                        reason=f"Yüksek tercih skoru: {intent}",
                    ))
        
        # Sort by confidence
        predictions.sort(key=lambda p: p.confidence, reverse=True)
        
        return predictions[:5]
    
    def _update_sequence(self, action_a: str, action_b: str) -> None:
        """Update command sequence probability."""
        if self._profile:
            self._profile.record_command_sequence(action_a, action_b)
    
    def _update_app_preference(self, app: str, reward: float) -> None:
        """Update app preference based on reward."""
        if self._profile:
            delta = reward * self.LEARNING_RATE * 0.5
            self._profile.update_app_preference(app, delta)
    
    def _update_time_pattern(self, event: CommandEvent) -> None:
        """Update time-based patterns."""
        if not self._profile:
            return
        
        hour = event.timestamp.hour
        intent = event.intent
        
        if intent not in self._profile.time_patterns:
            self._profile.time_patterns[intent] = {}
        
        current = self._profile.time_patterns[intent].get(hour, 0.0)
        # Exponential moving average
        alpha = 0.1
        self._profile.time_patterns[intent][hour] = current + alpha * (1.0 - current)
    
    def _is_repeat_usage(self, event: CommandEvent) -> bool:
        """Check if this is a repeat usage within time window."""
        for past_event in reversed(self._recent_events):
            time_diff = (event.timestamp - past_event.timestamp).total_seconds()
            
            if time_diff > self.REPEAT_WINDOW_SECONDS:
                break
            
            if past_event.intent == event.intent:
                return True
        
        return False
    
    def _is_sequence_completion(self, event: CommandEvent) -> bool:
        """Check if this completes an expected sequence."""
        if not self._last_action or not self._profile:
            return False
        
        expected_prob = self._profile.get_sequence_probability(
            self._last_action, event.intent
        )
        
        return expected_prob > 0.5
    
    def get_q_values(self) -> Dict[str, float]:
        """Get current Q-values."""
        return dict(self._q_values)
    
    def get_action_counts(self) -> Dict[str, int]:
        """Get action counts."""
        return dict(self._action_counts)
    
    def reset(self) -> None:
        """Reset learner state."""
        self._recent_events.clear()
        self._q_values.clear()
        self._action_counts.clear()
        self._last_action = None


def create_behavioral_learner(
    profile: Optional[UserProfile] = None,
    event_bus: Optional[EventBus] = None,
) -> BehavioralLearner:
    """
    Factory function to create a behavioral learner.
    
    Args:
        profile: User profile to learn into.
        event_bus: Optional event bus.
        
    Returns:
        Configured BehavioralLearner instance.
    """
    return BehavioralLearner(
        profile=profile,
        event_bus=event_bus,
    )
