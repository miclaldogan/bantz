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

# V2-4 Memory System (Issue #36)
from bantz.memory.snippet import (
    SnippetType,
    MemorySnippet,
    create_snippet,
)
from bantz.memory.snippet_store import (
    SnippetStore,
    InMemoryStore,
    SQLiteStore,
    create_session_store,
    create_persistent_store,
)
from bantz.memory.write_policy import (
    WriteDecision,
    PolicyResult,
    WritePolicy,
    SensitivePattern,
    create_write_policy,
)
from bantz.memory.retrieval import (
    RetrievalContext,
    MemoryRetriever,
    create_retriever,
)
from bantz.memory.snippet_manager import (
    MemoryManager,
    create_memory_manager,
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
    # V2-4 Snippet System
    "SnippetType",
    "MemorySnippet",
    "create_snippet",
    "SnippetStore",
    "InMemoryStore",
    "SQLiteStore",
    "create_session_store",
    "create_persistent_store",
    "WriteDecision",
    "PolicyResult",
    "WritePolicy",
    "SensitivePattern",
    "create_write_policy",
    "RetrievalContext",
    "MemoryRetriever",
    "create_retriever",
    "MemoryManager",
    "create_memory_manager",
]
