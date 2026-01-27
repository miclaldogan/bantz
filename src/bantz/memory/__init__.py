"""
Bantz Memory System - Conversational Memory & Personality

Long-term memory, user preferences, and personality for a true assistant experience.
"""

from bantz.memory.types import (
    Memory,
    MemoryType,
    ConversationMemory,
    TaskMemory,
    PreferenceMemory,
    FactMemory,
    MemoryQuery,
    MemoryStats,
)
from bantz.memory.store import (
    MemoryStore,
    MemoryIndex,
    MemoryDecay,
)
from bantz.memory.profile import (
    UserProfile,
    ProfileManager,
    PreferenceConfidence,
    CommunicationStyle,
    WorkPattern,
)
from bantz.memory.personality import (
    Personality,
    SpeakingStyle,
    ResponseType,
    PersonalityPreset,
    PERSONALITIES,
    get_personality,
)
from bantz.memory.context import (
    ContextBuilder,
    ContextConfig,
    PromptSection,
)
from bantz.memory.learning import (
    LearningEngine,
    ExtractedFact,
    InteractionResult,
    LearningConfig,
)

__all__ = [
    # Types
    "Memory",
    "MemoryType",
    "ConversationMemory",
    "TaskMemory",
    "PreferenceMemory",
    "FactMemory",
    "MemoryQuery",
    "MemoryStats",
    # Store
    "MemoryStore",
    "MemoryIndex",
    "MemoryDecay",
    # Profile
    "UserProfile",
    "ProfileManager",
    "PreferenceConfidence",
    "CommunicationStyle",
    "WorkPattern",
    # Personality
    "Personality",
    "SpeakingStyle",
    "ResponseType",
    "PersonalityPreset",
    "PERSONALITIES",
    "get_personality",
    # Context
    "ContextBuilder",
    "ContextConfig",
    "PromptSection",
    # Learning
    "LearningEngine",
    "ExtractedFact",
    "InteractionResult",
    "LearningConfig",
]
