"""
Memory Types - Data structures for long-term memory.

Defines different types of memories: conversations, tasks, preferences, and facts.
Each memory type has specialized fields for its specific use case.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class MemoryType(Enum):
    """Types of memories that can be stored."""
    
    CONVERSATION = "conversation"  # What was discussed
    TASK = "task"                  # What was done
    PREFERENCE = "preference"      # User preferences learned
    FACT = "fact"                  # Facts about the user
    EVENT = "event"                # Calendar events, reminders
    RELATIONSHIP = "relationship"  # Connections between memories
    
    @property
    def importance_weight(self) -> float:
        """Default importance weight for this memory type."""
        weights = {
            MemoryType.CONVERSATION: 0.3,
            MemoryType.TASK: 0.5,
            MemoryType.PREFERENCE: 0.7,
            MemoryType.FACT: 0.8,
            MemoryType.EVENT: 0.6,
            MemoryType.RELATIONSHIP: 0.4,
        }
        return weights.get(self, 0.5)
    
    @property
    def decay_rate(self) -> float:
        """Daily decay rate for importance (0 = no decay, 1 = full decay)."""
        rates = {
            MemoryType.CONVERSATION: 0.05,  # Conversations fade faster
            MemoryType.TASK: 0.03,          # Tasks remembered longer
            MemoryType.PREFERENCE: 0.01,    # Preferences very stable
            MemoryType.FACT: 0.005,         # Facts almost permanent
            MemoryType.EVENT: 0.1,          # Events fade quickly after done
            MemoryType.RELATIONSHIP: 0.02,
        }
        return rates.get(self, 0.03)


@dataclass
class Memory:
    """
    A single memory entry.
    
    Memories are the atomic units of long-term storage. Each memory has:
    - Unique identifier
    - Timestamp of creation
    - Type classification
    - Content (the actual memory)
    - Metadata for additional context
    - Importance score for prioritization
    - Access tracking for reinforcement
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    type: MemoryType = MemoryType.CONVERSATION
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5  # 0.0 - 1.0
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    
    # Embeddings for semantic search (optional)
    embedding: Optional[List[float]] = None
    
    # Tags for quick filtering
    tags: List[str] = field(default_factory=list)
    
    # Source tracking
    source: str = "user_interaction"
    session_id: Optional[str] = None
    
    def __post_init__(self):
        """Validate memory after initialization."""
        self.importance = max(0.0, min(1.0, self.importance))
        if isinstance(self.type, str):
            self.type = MemoryType(self.type)
    
    def access(self) -> None:
        """Record an access to this memory (reinforcement)."""
        self.access_count += 1
        self.last_accessed = datetime.now()
        # Slight importance boost on access
        self.importance = min(1.0, self.importance + 0.02)
    
    def decay(self, days: float = 1.0) -> None:
        """Apply importance decay based on time passed."""
        decay_amount = self.type.decay_rate * days
        self.importance = max(0.0, self.importance - decay_amount)
    
    def matches_query(self, query: str) -> bool:
        """Simple keyword matching for search."""
        query_lower = query.lower()
        content_lower = self.content.lower()
        
        # Check content
        if query_lower in content_lower:
            return True
        
        # Check tags
        for tag in self.tags:
            if query_lower in tag.lower():
                return True
        
        # Check metadata values
        for value in self.metadata.values():
            if isinstance(value, str) and query_lower in value.lower():
                return True
        
        return False
    
    def relevance_score(self, query: str) -> float:
        """
        Calculate relevance score for a query.
        
        Higher score = more relevant to the query.
        """
        if not query:
            return self.importance
        
        query_words = set(query.lower().split())
        content_words = set(self.content.lower().split())
        
        # Word overlap score
        overlap = len(query_words & content_words)
        total = len(query_words | content_words)
        word_score = overlap / total if total > 0 else 0
        
        # Combine with importance
        return (word_score * 0.7 + self.importance * 0.3)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert memory to dictionary for serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type.value,
            "content": self.content,
            "metadata": self.metadata,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "tags": self.tags,
            "source": self.source,
            "session_id": self.session_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Memory:
        """Create memory from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            type=MemoryType(data.get("type", "conversation")),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None,
            tags=data.get("tags", []),
            source=data.get("source", "user_interaction"),
            session_id=data.get("session_id"),
        )


@dataclass
class ConversationMemory(Memory):
    """
    Memory of a conversation exchange.
    
    Stores user message, assistant response, topic, and sentiment.
    Used for context carryover and remembering what was discussed.
    """
    
    type: MemoryType = field(default=MemoryType.CONVERSATION)
    
    # Conversation specific fields
    user_message: str = ""
    assistant_response: str = ""
    topic: str = ""
    sentiment: float = 0.0  # -1.0 (negative) to 1.0 (positive)
    language: str = "tr"
    
    def __post_init__(self):
        super().__post_init__()
        # Build content from messages if not set
        if not self.content and (self.user_message or self.assistant_response):
            self.content = f"User: {self.user_message}\nAssistant: {self.assistant_response}"
        
        # Store in metadata
        self.metadata.update({
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "topic": self.topic,
            "sentiment": self.sentiment,
            "language": self.language,
        })
    
    @classmethod
    def from_exchange(
        cls,
        user_message: str,
        assistant_response: str,
        topic: str = "",
        sentiment: float = 0.0,
        importance: float = 0.3,
    ) -> ConversationMemory:
        """Create conversation memory from an exchange."""
        return cls(
            user_message=user_message,
            assistant_response=assistant_response,
            topic=topic,
            sentiment=sentiment,
            importance=importance,
            tags=["conversation", topic] if topic else ["conversation"],
        )


@dataclass
class TaskMemory(Memory):
    """
    Memory of a task that was performed.
    
    Stores task description, steps taken, success status, and duration.
    Used for recalling what was done and learning from successes/failures.
    """
    
    type: MemoryType = field(default=MemoryType.TASK)
    
    # Task specific fields
    task_description: str = ""
    steps: List[str] = field(default_factory=list)
    success: bool = True
    duration_seconds: float = 0.0
    error_message: str = ""
    related_apps: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        super().__post_init__()
        # Build content from description if not set
        if not self.content and self.task_description:
            status = "✓" if self.success else "✗"
            self.content = f"[{status}] {self.task_description}"
            if self.steps:
                self.content += f"\nSteps: {', '.join(self.steps)}"
        
        # Store in metadata
        self.metadata.update({
            "task_description": self.task_description,
            "steps": self.steps,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "related_apps": self.related_apps,
        })
        
        # Adjust importance based on success
        if not self.success:
            self.importance = min(self.importance * 0.7, 0.3)
    
    @classmethod
    def from_execution(
        cls,
        description: str,
        steps: List[str],
        success: bool,
        duration: float = 0.0,
        error: str = "",
        apps: List[str] = None,
    ) -> TaskMemory:
        """Create task memory from an execution."""
        return cls(
            task_description=description,
            steps=steps,
            success=success,
            duration_seconds=duration,
            error_message=error,
            related_apps=apps or [],
            importance=0.6 if success else 0.3,
            tags=["task", "success" if success else "failure"],
        )


@dataclass
class PreferenceMemory(Memory):
    """
    Memory of a learned user preference.
    
    Stores preference type, value, and confidence level.
    Used for personalizing assistant behavior.
    """
    
    type: MemoryType = field(default=MemoryType.PREFERENCE)
    
    # Preference specific fields
    preference_key: str = ""
    preference_value: Any = None
    confidence: float = 0.5  # 0.0 - 1.0
    source_count: int = 1  # How many interactions confirmed this
    last_confirmed: Optional[datetime] = None
    
    def __post_init__(self):
        super().__post_init__()
        # Build content from preference
        if not self.content and self.preference_key:
            self.content = f"Preference: {self.preference_key} = {self.preference_value}"
        
        # Store in metadata
        self.metadata.update({
            "preference_key": self.preference_key,
            "preference_value": self.preference_value,
            "confidence": self.confidence,
            "source_count": self.source_count,
        })
        
        # Higher confidence = higher importance
        self.importance = max(self.importance, self.confidence * 0.8)
    
    def confirm(self) -> None:
        """Confirm this preference (increases confidence)."""
        self.source_count += 1
        self.confidence = min(1.0, self.confidence + 0.1)
        self.last_confirmed = datetime.now()
        self.access()
    
    def contradict(self) -> None:
        """Register a contradiction (decreases confidence)."""
        self.confidence = max(0.0, self.confidence - 0.2)
        self.importance = max(0.0, self.importance - 0.1)
    
    @classmethod
    def from_observation(
        cls,
        key: str,
        value: Any,
        confidence: float = 0.5,
    ) -> PreferenceMemory:
        """Create preference memory from an observation."""
        return cls(
            preference_key=key,
            preference_value=value,
            confidence=confidence,
            importance=confidence * 0.7,
            tags=["preference", key.split(".")[0] if "." in key else key],
        )


@dataclass
class FactMemory(Memory):
    """
    Memory of a fact about the user.
    
    Stores fact category, value, and source.
    Used for personalizing responses and remembering user information.
    """
    
    type: MemoryType = field(default=MemoryType.FACT)
    
    # Fact specific fields
    fact_category: str = ""  # name, job, location, birthday, etc.
    fact_value: str = ""
    fact_source: str = "user_stated"  # user_stated, inferred, observed
    verified: bool = False
    
    def __post_init__(self):
        super().__post_init__()
        # Build content from fact
        if not self.content and self.fact_category:
            self.content = f"{self.fact_category}: {self.fact_value}"
        
        # Store in metadata
        self.metadata.update({
            "fact_category": self.fact_category,
            "fact_value": self.fact_value,
            "fact_source": self.fact_source,
            "verified": self.verified,
        })
        
        # Facts are generally important
        self.importance = max(self.importance, 0.7)
    
    def verify(self) -> None:
        """Mark this fact as verified."""
        self.verified = True
        self.importance = min(1.0, self.importance + 0.2)
        self.access()
    
    @classmethod
    def from_statement(
        cls,
        category: str,
        value: str,
        source: str = "user_stated",
    ) -> FactMemory:
        """Create fact memory from a statement."""
        return cls(
            fact_category=category,
            fact_value=value,
            fact_source=source,
            verified=source == "user_stated",
            importance=0.8 if source == "user_stated" else 0.5,
            tags=["fact", category],
        )


@dataclass
class MemoryQuery:
    """
    Query parameters for memory recall.
    
    Allows filtering and sorting memories based on various criteria.
    """
    
    # Text search
    query: str = ""
    
    # Type filter
    types: Optional[List[MemoryType]] = None
    
    # Time range
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    
    # Importance filter
    min_importance: float = 0.0
    max_importance: float = 1.0
    
    # Tag filter
    tags: Optional[List[str]] = None
    
    # Limit and offset
    limit: int = 10
    offset: int = 0
    
    # Sorting
    sort_by: str = "relevance"  # relevance, timestamp, importance, access_count
    sort_desc: bool = True
    
    # Session filter
    session_id: Optional[str] = None
    
    def matches(self, memory: Memory) -> bool:
        """Check if a memory matches this query."""
        # Type filter
        if self.types and memory.type not in self.types:
            return False
        
        # Time range
        if self.since and memory.timestamp < self.since:
            return False
        if self.until and memory.timestamp > self.until:
            return False
        
        # Importance filter
        if memory.importance < self.min_importance:
            return False
        if memory.importance > self.max_importance:
            return False
        
        # Tag filter
        if self.tags:
            if not any(tag in memory.tags for tag in self.tags):
                return False
        
        # Session filter
        if self.session_id and memory.session_id != self.session_id:
            return False
        
        # Text search
        if self.query and not memory.matches_query(self.query):
            return False
        
        return True


@dataclass
class MemoryStats:
    """Statistics about the memory store."""
    
    total_memories: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    avg_importance: float = 0.0
    oldest_memory: Optional[datetime] = None
    newest_memory: Optional[datetime] = None
    total_accesses: int = 0
    storage_bytes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "total_memories": self.total_memories,
            "by_type": self.by_type,
            "avg_importance": self.avg_importance,
            "oldest_memory": self.oldest_memory.isoformat() if self.oldest_memory else None,
            "newest_memory": self.newest_memory.isoformat() if self.newest_memory else None,
            "total_accesses": self.total_accesses,
            "storage_bytes": self.storage_bytes,
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        lines = [
            f"📊 Memory Statistics",
            f"Total: {self.total_memories} memories",
        ]
        
        for type_name, count in self.by_type.items():
            lines.append(f"  • {type_name}: {count}")
        
        lines.append(f"Avg importance: {self.avg_importance:.2f}")
        lines.append(f"Total accesses: {self.total_accesses}")
        
        return "\n".join(lines)
