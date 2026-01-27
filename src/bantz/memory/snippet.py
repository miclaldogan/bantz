"""
Memory Snippet Types for V2-4 Memory System (Issue #36).

Three-tier memory architecture:
- SESSION: In-memory, cleared on restart
- PROFILE: Persistent user preferences
- EPISODIC: Time-stamped event memories

Provides MemorySnippet dataclass with TTL support.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class SnippetType(Enum):
    """
    Memory snippet types for 3-tier architecture.
    
    Different from legacy MemoryType - this is for V2-4 system.
    """
    
    SESSION = "session"       # In-memory, cleared on restart
    PROFILE = "profile"       # Persistent user preferences
    EPISODIC = "episodic"     # Time-stamped event memories
    
    @property
    def is_persistent(self) -> bool:
        """Whether this memory type persists across restarts."""
        return self in (SnippetType.PROFILE, SnippetType.EPISODIC)
    
    @property
    def default_ttl(self) -> Optional[timedelta]:
        """Default TTL for this memory type."""
        defaults = {
            SnippetType.SESSION: timedelta(hours=24),
            SnippetType.PROFILE: None,  # No expiry
            SnippetType.EPISODIC: timedelta(days=90),
        }
        return defaults.get(self)
    
    @property
    def priority(self) -> int:
        """Priority for retrieval ordering (higher = more important)."""
        priorities = {
            SnippetType.SESSION: 3,    # Most recent, highest priority
            SnippetType.PROFILE: 2,    # User preferences
            SnippetType.EPISODIC: 1,   # Historical events
        }
        return priorities.get(self, 0)


@dataclass
class MemorySnippet:
    """
    A memory snippet - atomic unit of the V2-4 memory system.
    
    Features:
    - Unique ID for referencing
    - Content string (the actual memory)
    - Memory type (session/profile/episodic)
    - Optional source tracking (URL, file path, etc.)
    - Timestamp for chronological ordering
    - Confidence score for reliability
    - TTL for automatic expiry
    - Tags for quick filtering
    - Metadata for extensibility
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    snippet_type: SnippetType = SnippetType.SESSION
    source: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0
    ttl: Optional[timedelta] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Access tracking
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    
    def __post_init__(self):
        """Validate and normalize fields."""
        # Clamp confidence to [0, 1]
        self.confidence = max(0.0, min(1.0, self.confidence))
        
        # Convert string type to enum
        if isinstance(self.snippet_type, str):
            self.snippet_type = SnippetType(self.snippet_type)
        
        # Set default TTL if not specified
        if self.ttl is None and self.snippet_type.default_ttl:
            self.ttl = self.snippet_type.default_ttl
    
    def is_expired(self) -> bool:
        """
        Check if snippet has expired based on TTL.
        
        Returns:
            True if TTL is set and has elapsed, False otherwise
        """
        if self.ttl is None:
            return False
        
        expiry_time = self.timestamp + self.ttl
        return datetime.now() > expiry_time
    
    def time_until_expiry(self) -> Optional[timedelta]:
        """
        Get time remaining until expiry.
        
        Returns:
            Remaining time if TTL is set and not expired, None otherwise
        """
        if self.ttl is None:
            return None
        
        expiry_time = self.timestamp + self.ttl
        remaining = expiry_time - datetime.now()
        
        if remaining.total_seconds() < 0:
            return timedelta(0)
        
        return remaining
    
    def access(self) -> None:
        """Record an access to this snippet."""
        self.access_count += 1
        self.last_accessed = datetime.now()
    
    @property
    def age(self) -> timedelta:
        """Get age of snippet since creation."""
        return datetime.now() - self.timestamp
    
    @property
    def age_seconds(self) -> float:
        """Get age in seconds."""
        return self.age.total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snippet to dictionary for serialization."""
        return {
            "id": self.id,
            "content": self.content,
            "snippet_type": self.snippet_type.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
            "ttl_seconds": self.ttl.total_seconds() if self.ttl else None,
            "tags": self.tags,
            "metadata": self.metadata,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemorySnippet":
        """Create snippet from dictionary."""
        ttl = None
        if data.get("ttl_seconds"):
            ttl = timedelta(seconds=data["ttl_seconds"])
        
        last_accessed = None
        if data.get("last_accessed"):
            last_accessed = datetime.fromisoformat(data["last_accessed"])
        
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            content=data.get("content", ""),
            snippet_type=SnippetType(data.get("snippet_type", "session")),
            source=data.get("source"),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            confidence=data.get("confidence", 1.0),
            ttl=ttl,
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            access_count=data.get("access_count", 0),
            last_accessed=last_accessed,
        )
    
    def __repr__(self) -> str:
        """String representation."""
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"MemorySnippet(id={self.id[:8]}, type={self.snippet_type.value}, content='{content_preview}')"


def create_snippet(
    content: str,
    snippet_type: SnippetType = SnippetType.SESSION,
    source: Optional[str] = None,
    confidence: float = 1.0,
    ttl: Optional[timedelta] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MemorySnippet:
    """
    Factory function to create a memory snippet.
    
    Args:
        content: The memory content
        snippet_type: Type of memory (SESSION/PROFILE/EPISODIC)
        source: Source of the memory (URL, file, etc.)
        confidence: Confidence score (0.0 - 1.0)
        ttl: Time to live
        tags: Tags for filtering
        metadata: Additional metadata
    
    Returns:
        MemorySnippet instance
    """
    return MemorySnippet(
        content=content,
        snippet_type=snippet_type,
        source=source,
        confidence=confidence,
        ttl=ttl,
        tags=tags or [],
        metadata=metadata or {},
    )
