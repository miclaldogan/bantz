"""
Conversation Context for V2-6 (Issue #38).

Maintains conversation history and turn information:
- TurnInfo for each utterance
- Max turn limit with FIFO eviction
- Recent turn retrieval
- Conversation ID tracking
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# =============================================================================
# Turn Info
# =============================================================================


@dataclass
class TurnInfo:
    """Information about a single conversation turn."""
    
    turn_id: str
    role: str  # "user" | "assistant"
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    intent: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    tts_duration_ms: Optional[float] = None
    asr_confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def user(
        cls,
        text: str,
        intent: Optional[str] = None,
        entities: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> "TurnInfo":
        """Create a user turn."""
        return cls(
            turn_id=str(uuid.uuid4()),
            role="user",
            text=text,
            intent=intent,
            entities=entities,
            **kwargs
        )
    
    @classmethod
    def assistant(
        cls,
        text: str,
        tts_duration_ms: Optional[float] = None,
        **kwargs
    ) -> "TurnInfo":
        """Create an assistant turn."""
        return cls(
            turn_id=str(uuid.uuid4()),
            role="assistant",
            text=text,
            tts_duration_ms=tts_duration_ms,
            **kwargs
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "intent": self.intent,
            "entities": self.entities,
            "tts_duration_ms": self.tts_duration_ms,
            "asr_confidence": self.asr_confidence,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TurnInfo":
        """Create from dictionary."""
        return cls(
            turn_id=data["turn_id"],
            role=data["role"],
            text=data["text"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            intent=data.get("intent"),
            entities=data.get("entities"),
            tts_duration_ms=data.get("tts_duration_ms"),
            asr_confidence=data.get("asr_confidence"),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# Conversation Context
# =============================================================================


class ConversationContext:
    """
    Maintains conversation history and context.
    
    Features:
    - Turn history with max limit
    - Recent turn retrieval
    - Last user/assistant turn access
    - Conversation ID tracking
    """
    
    def __init__(
        self,
        max_turns: int = 10,
        conversation_id: Optional[str] = None
    ):
        """
        Initialize conversation context.
        
        Args:
            max_turns: Maximum number of turns to keep
            conversation_id: Optional conversation ID (generated if not provided)
        """
        self._max_turns = max_turns
        self._conversation_id = conversation_id or str(uuid.uuid4())
        self._turns: List[TurnInfo] = []
        self._lock = threading.Lock()
        self._created_at = datetime.now()
        self._metadata: Dict[str, Any] = {}
    
    @property
    def conversation_id(self) -> str:
        """Get conversation ID."""
        return self._conversation_id
    
    @property
    def turn_count(self) -> int:
        """Get number of turns."""
        with self._lock:
            return len(self._turns)
    
    @property
    def max_turns(self) -> int:
        """Get max turns limit."""
        return self._max_turns
    
    @property
    def created_at(self) -> datetime:
        """Get creation timestamp."""
        return self._created_at
    
    @property
    def is_empty(self) -> bool:
        """Check if context is empty."""
        with self._lock:
            return len(self._turns) == 0
    
    def add_turn(self, turn: TurnInfo) -> None:
        """
        Add a turn to the context (thread-safe).
        
        Evicts oldest turn if max limit is reached.
        """
        with self._lock:
            self._turns.append(turn)
            
            # Evict oldest if needed
            while len(self._turns) > self._max_turns:
                self._turns.pop(0)
    
    def add_user_turn(
        self,
        text: str,
        intent: Optional[str] = None,
        entities: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> TurnInfo:
        """Add a user turn."""
        turn = TurnInfo.user(text=text, intent=intent, entities=entities, **kwargs)
        self.add_turn(turn)
        return turn
    
    def add_assistant_turn(
        self,
        text: str,
        tts_duration_ms: Optional[float] = None,
        **kwargs
    ) -> TurnInfo:
        """Add an assistant turn."""
        turn = TurnInfo.assistant(text=text, tts_duration_ms=tts_duration_ms, **kwargs)
        self.add_turn(turn)
        return turn
    
    def get_recent_turns(self, n: int = 5) -> List[TurnInfo]:
        """Get the N most recent turns (thread-safe)."""
        with self._lock:
            return list(self._turns[-n:])
    
    def get_all_turns(self) -> List[TurnInfo]:
        """Get all turns (thread-safe)."""
        with self._lock:
            return list(self._turns)
    
    def get_last_turn(self) -> Optional[TurnInfo]:
        """Get the last turn (thread-safe)."""
        with self._lock:
            if not self._turns:
                return None
            return self._turns[-1]
    
    def get_last_user_turn(self) -> Optional[TurnInfo]:
        """Get the last user turn (thread-safe)."""
        with self._lock:
            for turn in reversed(self._turns):
                if turn.role == "user":
                    return turn
            return None
    
    def get_last_assistant_turn(self) -> Optional[TurnInfo]:
        """Get the last assistant turn (thread-safe)."""
        with self._lock:
            for turn in reversed(self._turns):
                if turn.role == "assistant":
                    return turn
            return None
    
    def get_turns_by_role(self, role: str) -> List[TurnInfo]:
        """Get all turns by role (thread-safe)."""
        with self._lock:
            return [t for t in self._turns if t.role == role]
    
    def clear(self) -> int:
        """Clear all turns (thread-safe)."""
        with self._lock:
            count = len(self._turns)
            self._turns.clear()
            return count
    
    def set_metadata(self, key: str, value: Any) -> None:
        """Set context metadata."""
        self._metadata[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get context metadata."""
        return self._metadata.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (thread-safe)."""
        with self._lock:
            return {
                "conversation_id": self._conversation_id,
                "created_at": self._created_at.isoformat(),
                "max_turns": self._max_turns,
                "turn_count": len(self._turns),
                "turns": [t.to_dict() for t in self._turns],
                "metadata": self._metadata,
            }
    
    def to_messages(self) -> List[Dict[str, str]]:
        """Convert to chat message format for LLM (thread-safe)."""
        with self._lock:
            return [
                {"role": t.role, "content": t.text}
                for t in self._turns
            ]
    
    def get_summary(self) -> str:
        """Get a text summary of the conversation (thread-safe)."""
        with self._lock:
            if not self._turns:
                return "No conversation yet."
            
            lines = []
            for turn in self._turns[-5:]:  # Last 5 turns
                role = "User" if turn.role == "user" else "Assistant"
                lines.append(f"{role}: {turn.text[:100]}...")
            
            return "\n".join(lines)


def create_conversation_context(
    max_turns: int = 10,
    conversation_id: Optional[str] = None
) -> ConversationContext:
    """Factory for creating conversation context."""
    return ConversationContext(max_turns=max_turns, conversation_id=conversation_id)
