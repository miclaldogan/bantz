"""
Issue #58: Behavioral Learning & User Modeling (RL-style).

Smart learning system that learns from user behavior
and provides a personalized experience.
"""

from bantz.learning.profile import (
    BehavioralProfile,
    UserProfile,  # backward-compat alias for BehavioralProfile
    ProfileManager,
    create_profile_manager,
)

from bantz.learning.behavioral import (
    BehavioralLearner,
    CommandEvent,
    RewardSignal,
    Prediction,
    create_behavioral_learner,
)

from bantz.learning.preferences import (
    PreferenceModel,
    PreferenceEntry,
    create_preference_model,
)

from bantz.learning.bandit import (
    ContextualBandit,
    ArmStats,
    create_contextual_bandit,
)

from bantz.learning.temporal import (
    TemporalPatternLearner,
    Routine,
    TimePattern,
    create_temporal_pattern_learner,
)

from bantz.learning.adaptive import (
    AdaptiveResponse,
    ResponseStyle,
    create_adaptive_response,
)

from bantz.learning.storage import (
    ProfileStorage,
    create_profile_storage,
)

__all__ = [
    # Profile
    "BehavioralProfile",
    "UserProfile",  # backward-compat alias
    "ProfileManager",
    "create_profile_manager",
    # Behavioral
    "BehavioralLearner",
    "CommandEvent",
    "RewardSignal",
    "Prediction",
    "create_behavioral_learner",
    # Preferences
    "PreferenceModel",
    "PreferenceEntry",
    "create_preference_model",
    # Bandit
    "ContextualBandit",
    "ArmStats",
    "create_contextual_bandit",
    # Temporal
    "TemporalPatternLearner",
    "Routine",
    "TimePattern",
    "create_temporal_pattern_learner",
    # Adaptive
    "AdaptiveResponse",
    "ResponseStyle",
    "create_adaptive_response",
    # Storage
    "ProfileStorage",
    "create_profile_storage",
]
