"""Memory data models for persistent SQLite storage (Issue #448).

Defines the core data structures used by :class:`PersistentMemoryStore`:

- :class:`MemoryItem` — episodic / semantic / fact memory entries
- :class:`Session` — conversation session envelope
- :class:`ToolTrace` — individual tool execution record
- :class:`UserProfile` — key-value user preference pair
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryItemType(Enum):
    """Kinds of persistent memory items."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    FACT = "fact"


@dataclass
class MemoryItem:
    """A single persistent memory entry.

    Attributes
    ----------
    id:
        Unique identifier (UUID).
    session_id:
        Owning session, if any.
    type:
        ``episodic``, ``semantic``, or ``fact``.
    content:
        Plain-text content of the memory.
    embedding_vector:
        Optional embedding for semantic retrieval (JSON-serialised list).
    importance:
        Importance score 0.0–1.0.
    created_at:
        When the memory was created.
    accessed_at:
        Last access timestamp.
    access_count:
        Number of times this memory was retrieved.
    tags:
        Free-form tags for quick filtering.
    metadata:
        Arbitrary JSON-serialisable metadata.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    type: MemoryItemType = MemoryItemType.EPISODIC
    content: str = ""
    embedding_vector: Optional[List[float]] = None
    importance: float = 0.5
    created_at: datetime = field(default_factory=datetime.utcnow)
    accessed_at: datetime = field(default_factory=datetime.utcnow)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.importance = max(0.0, min(1.0, self.importance))
        if isinstance(self.type, str):
            self.type = MemoryItemType(self.type)

    def touch(self) -> None:
        """Record an access (bump count + timestamp)."""
        self.access_count += 1
        self.accessed_at = datetime.utcnow()


@dataclass
class Session:
    """A conversation session envelope.

    Attributes
    ----------
    id:
        Unique session identifier (UUID).
    start_time:
        When the session started.
    end_time:
        When the session ended (*None* while active).
    summary:
        LLM-generated session summary (filled on close).
    turn_count:
        Number of user turns in this session.
    metadata:
        Arbitrary metadata (locale, timezone, …).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    summary: str = ""
    turn_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.end_time is None


@dataclass
class ToolTrace:
    """Record of a single tool execution.

    Attributes
    ----------
    id:
        Unique trace identifier (UUID).
    session_id:
        Session that triggered this tool call.
    tool_name:
        Canonical tool name (``calendar.create_event``).
    args_hash:
        SHA-256 of the serialised arguments.
    result_summary:
        Human-readable one-liner of the tool result.
    success:
        Whether the tool call succeeded.
    latency_ms:
        Execution time in milliseconds.
    created_at:
        When the tool was invoked.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    tool_name: str = ""
    args_hash: str = ""
    result_summary: str = ""
    success: bool = True
    latency_ms: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class UserProfile:
    """A key-value pair in the user profile store.

    Attributes
    ----------
    id:
        Auto-generated UUID.
    key:
        Profile key (``preferred_language``, ``timezone``, …).
    value:
        Arbitrary string value (caller may JSON-encode complex data).
    updated_at:
        Last update timestamp.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    key: str = ""
    value: str = ""
    updated_at: datetime = field(default_factory=datetime.utcnow)
