# SPDX-License-Identifier: MIT
"""
NLU type definitions.

This module contains all the data structures used throughout the NLU system:
- IntentResult: The primary output of intent classification
- Slot: Named entity slots extracted from user input
- ClarificationRequest: When input is ambiguous
- NLUContext: Conversation and environment context
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================================
# Enums
# ============================================================================


class SlotType(Enum):
    """Types of slots that can be extracted from user input."""
    
    # Time-related
    TIME = "time"              # datetime
    DURATION = "duration"      # timedelta
    RELATIVE_TIME = "relative_time"  # "5 dakika sonra"
    
    # Entities
    URL = "url"                # URL or site name
    APP = "app"                # Application name
    FILE_PATH = "file_path"    # File or directory path
    QUERY = "query"            # Search query
    
    # Text
    TEXT = "text"              # Free text
    NUMBER = "number"          # Numeric value
    
    # Boolean
    BOOLEAN = "boolean"        # Yes/no
    
    # Commands
    COMMAND = "command"        # Terminal command
    
    def __str__(self) -> str:
        return self.value


class ConfidenceLevel(Enum):
    """Confidence levels for intent classification."""
    
    VERY_HIGH = "very_high"    # 0.95-1.0 - Regex exact match
    HIGH = "high"              # 0.85-0.95 - Strong LLM confidence
    MEDIUM = "medium"          # 0.70-0.85 - Reasonable confidence
    LOW = "low"                # 0.50-0.70 - May need clarification
    VERY_LOW = "very_low"      # 0.0-0.50 - Definitely needs clarification
    
    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        """Convert numeric score to confidence level."""
        if score >= 0.95:
            return cls.VERY_HIGH
        elif score >= 0.85:
            return cls.HIGH
        elif score >= 0.70:
            return cls.MEDIUM
        elif score >= 0.50:
            return cls.LOW
        else:
            return cls.VERY_LOW
    
    @property
    def needs_clarification(self) -> bool:
        """Whether this confidence level typically needs clarification."""
        return self in (ConfidenceLevel.LOW, ConfidenceLevel.VERY_LOW)
    
    @property
    def min_score(self) -> float:
        """Minimum score for this level."""
        thresholds = {
            ConfidenceLevel.VERY_HIGH: 0.95,
            ConfidenceLevel.HIGH: 0.85,
            ConfidenceLevel.MEDIUM: 0.70,
            ConfidenceLevel.LOW: 0.50,
            ConfidenceLevel.VERY_LOW: 0.0,
        }
        return thresholds[self]


class IntentCategory(Enum):
    """High-level intent categories for grouping."""
    
    BROWSER = "browser"        # Web browsing
    APP = "app"                # Application control
    FILE = "file"              # File operations
    TERMINAL = "terminal"      # Terminal commands
    REMINDER = "reminder"      # Reminders and scheduling
    CONVERSATION = "conversation"  # Chat/question
    SYSTEM = "system"          # System control
    AGENT = "agent"            # Agent mode
    QUEUE = "queue"            # Queue control
    UI = "ui"                  # Overlay/UI control
    UNKNOWN = "unknown"        # Unrecognized
    
    @classmethod
    def from_intent(cls, intent: str) -> "IntentCategory":
        """Determine category from intent name."""
        intent_lower = intent.lower()
        
        if intent_lower.startswith("browser_"):
            return cls.BROWSER
        elif intent_lower.startswith("app_"):
            return cls.APP
        elif intent_lower.startswith("file_"):
            return cls.FILE
        elif intent_lower.startswith("terminal_"):
            return cls.TERMINAL
        elif "reminder" in intent_lower or "checkin" in intent_lower:
            return cls.REMINDER
        elif intent_lower in ("conversation", "chat", "question"):
            return cls.CONVERSATION
        elif intent_lower.startswith("agent_"):
            return cls.AGENT
        elif intent_lower.startswith("queue_"):
            return cls.QUEUE
        elif intent_lower.startswith("overlay_") or intent_lower.startswith("ui_"):
            return cls.UI
        elif intent_lower in ("pc_hotkey", "pc_mouse_click", "pc_mouse_move"):
            return cls.SYSTEM
        elif intent_lower == "unknown":
            return cls.UNKNOWN
        else:
            return cls.SYSTEM


# ============================================================================
# Slot
# ============================================================================


@dataclass
class Slot:
    """A named entity slot extracted from user input.
    
    Slots represent structured information extracted from natural language,
    such as "5 dakika sonra" -> Slot(name="time", value="5 minutes", ...)
    
    Attributes:
        name: Slot name (e.g., "time", "url", "app")
        value: Extracted value (parsed)
        raw_text: Original text that was matched
        slot_type: Type of slot for validation
        confidence: Confidence in extraction (0-1)
        start_pos: Start position in original text
        end_pos: End position in original text
    """
    
    name: str
    value: Any
    raw_text: str
    slot_type: SlotType = SlotType.TEXT
    confidence: float = 1.0
    start_pos: Optional[int] = None
    end_pos: Optional[int] = None
    
    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "raw_text": self.raw_text,
            "slot_type": self.slot_type.value,
            "confidence": self.confidence,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Slot":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            value=data["value"],
            raw_text=data["raw_text"],
            slot_type=SlotType(data.get("slot_type", "text")),
            confidence=data.get("confidence", 1.0),
            start_pos=data.get("start_pos"),
            end_pos=data.get("end_pos"),
        )
    
    def __str__(self) -> str:
        return f"{self.name}={self.value!r}"


# ============================================================================
# Clarification
# ============================================================================


@dataclass
class ClarificationOption:
    """A possible clarification option for ambiguous input.
    
    When the user's input is ambiguous, we present options like:
    - "YouTube sitesini mi açayım?"
    - "YouTube uygulamasını mı açayım?"
    """
    
    intent: str
    description: str
    slots: Dict[str, Any] = field(default_factory=dict)
    probability: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "description": self.description,
            "slots": self.slots,
            "probability": self.probability,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClarificationOption":
        """Create from dictionary."""
        return cls(
            intent=data["intent"],
            description=data["description"],
            slots=data.get("slots", {}),
            probability=data.get("probability", 0.5),
        )


@dataclass
class ClarificationRequest:
    """Request for clarification when input is ambiguous.
    
    Generated when:
    - Confidence is too low
    - Multiple intents are equally likely
    - Required slots are missing
    """
    
    question: str
    options: List[ClarificationOption] = field(default_factory=list)
    original_text: str = ""
    reason: str = ""
    slot_needed: Optional[str] = None
    
    @property
    def has_options(self) -> bool:
        """Whether there are specific options to choose from."""
        return len(self.options) > 0
    
    @property
    def is_slot_request(self) -> bool:
        """Whether this is asking for a specific slot value."""
        return self.slot_needed is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "question": self.question,
            "options": [opt.to_dict() for opt in self.options],
            "original_text": self.original_text,
            "reason": self.reason,
            "slot_needed": self.slot_needed,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClarificationRequest":
        """Create from dictionary."""
        return cls(
            question=data["question"],
            options=[ClarificationOption.from_dict(o) for o in data.get("options", [])],
            original_text=data.get("original_text", ""),
            reason=data.get("reason", ""),
            slot_needed=data.get("slot_needed"),
        )


# ============================================================================
# Context
# ============================================================================


@dataclass
class NLUContext:
    """Context for intent classification.
    
    Provides additional information to help with classification:
    - Current application state (which app is focused)
    - Recent conversation history
    - Pending clarification requests
    - User preferences
    """
    
    # Current state
    focused_app: Optional[str] = None
    current_url: Optional[str] = None
    current_page_title: Optional[str] = None
    
    # Conversation history
    recent_intents: List[str] = field(default_factory=list)
    recent_texts: List[str] = field(default_factory=list)
    
    # Pending clarification
    pending_clarification: Optional[ClarificationRequest] = None
    last_intent_result: Optional["IntentResult"] = None
    
    # User preferences
    preferred_apps: Dict[str, str] = field(default_factory=dict)
    preferred_sites: Dict[str, str] = field(default_factory=dict)
    
    # Session info
    session_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def add_intent(self, intent: str, text: str, max_history: int = 10):
        """Add an intent to the history."""
        self.recent_intents.append(intent)
        self.recent_texts.append(text)
        
        # Trim history
        if len(self.recent_intents) > max_history:
            self.recent_intents = self.recent_intents[-max_history:]
            self.recent_texts = self.recent_texts[-max_history:]
    
    def get_last_intent(self) -> Optional[str]:
        """Get the last recognized intent."""
        return self.recent_intents[-1] if self.recent_intents else None
    
    def get_last_text(self) -> Optional[str]:
        """Get the last user text."""
        return self.recent_texts[-1] if self.recent_texts else None
    
    def is_followup(self) -> bool:
        """Check if current context suggests a follow-up."""
        return self.pending_clarification is not None or len(self.recent_intents) > 0
    
    def resolve_clarification(self, chosen_option: ClarificationOption) -> "IntentResult":
        """Resolve pending clarification with chosen option."""
        result = IntentResult(
            intent=chosen_option.intent,
            slots=chosen_option.slots,
            confidence=1.0,  # User explicitly chose
            original_text=self.pending_clarification.original_text if self.pending_clarification else "",
            source="clarification",
        )
        self.pending_clarification = None
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "focused_app": self.focused_app,
            "current_url": self.current_url,
            "current_page_title": self.current_page_title,
            "recent_intents": self.recent_intents,
            "recent_texts": self.recent_texts,
            "pending_clarification": (
                self.pending_clarification.to_dict()
                if self.pending_clarification else None
            ),
            "preferred_apps": self.preferred_apps,
            "preferred_sites": self.preferred_sites,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NLUContext":
        """Create from dictionary."""
        ctx = cls(
            focused_app=data.get("focused_app"),
            current_url=data.get("current_url"),
            current_page_title=data.get("current_page_title"),
            recent_intents=data.get("recent_intents", []),
            recent_texts=data.get("recent_texts", []),
            preferred_apps=data.get("preferred_apps", {}),
            preferred_sites=data.get("preferred_sites", {}),
            session_id=data.get("session_id"),
            timestamp=data.get("timestamp", time.time()),
        )
        
        if data.get("pending_clarification"):
            ctx.pending_clarification = ClarificationRequest.from_dict(
                data["pending_clarification"]
            )
        
        return ctx


# ============================================================================
# Intent Result
# ============================================================================


@dataclass
class IntentResult:
    """Result of intent classification.
    
    This is the primary output of the NLU system, containing:
    - The classified intent
    - Extracted slots (entities)
    - Confidence score
    - Any clarification needed
    
    Attributes:
        intent: The classified intent name
        slots: Extracted slot values
        confidence: Classification confidence (0-1)
        original_text: The original user input
        source: Where the classification came from
        ambiguous: Whether the intent is ambiguous
        clarification: Clarification request if needed
        alternatives: Alternative intents considered
        category: High-level intent category
        processing_time_ms: Time taken for classification
        metadata: Additional classification metadata
    """
    
    intent: str
    slots: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    original_text: str = ""
    source: str = "regex"  # regex, llm, hybrid, clarification
    ambiguous: bool = False
    clarification: Optional[ClarificationRequest] = None
    alternatives: List[Tuple[str, float]] = field(default_factory=list)
    category: Optional[IntentCategory] = None
    processing_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Auto-set category if not provided
        if self.category is None:
            self.category = IntentCategory.from_intent(self.intent)
        
        # Validate confidence
        if not 0.0 <= self.confidence <= 1.0:
            self.confidence = max(0.0, min(1.0, self.confidence))
    
    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Get the confidence level enum."""
        return ConfidenceLevel.from_score(self.confidence)
    
    @property
    def needs_clarification(self) -> bool:
        """Whether clarification is needed."""
        return self.clarification is not None or self.confidence_level.needs_clarification
    
    @property
    def is_successful(self) -> bool:
        """Whether classification was successful (high enough confidence)."""
        return self.confidence >= 0.5 and self.intent != "unknown"
    
    @property
    def slot_names(self) -> Set[str]:
        """Get names of all extracted slots."""
        return set(self.slots.keys())
    
    def get_slot(self, name: str, default: Any = None) -> Any:
        """Get a slot value by name."""
        return self.slots.get(name, default)
    
    def has_slot(self, name: str) -> bool:
        """Check if a slot exists."""
        return name in self.slots
    
    def with_slot(self, name: str, value: Any) -> "IntentResult":
        """Return a new result with an additional slot."""
        new_slots = dict(self.slots)
        new_slots[name] = value
        return IntentResult(
            intent=self.intent,
            slots=new_slots,
            confidence=self.confidence,
            original_text=self.original_text,
            source=self.source,
            ambiguous=self.ambiguous,
            clarification=self.clarification,
            alternatives=self.alternatives,
            category=self.category,
            processing_time_ms=self.processing_time_ms,
            metadata=self.metadata,
        )
    
    def with_confidence(self, confidence: float) -> "IntentResult":
        """Return a new result with updated confidence."""
        return IntentResult(
            intent=self.intent,
            slots=self.slots,
            confidence=confidence,
            original_text=self.original_text,
            source=self.source,
            ambiguous=self.ambiguous,
            clarification=self.clarification,
            alternatives=self.alternatives,
            category=self.category,
            processing_time_ms=self.processing_time_ms,
            metadata=self.metadata,
        )
    
    def to_parsed(self) -> "Parsed":
        """Convert to legacy Parsed format for compatibility."""
        from bantz.router.nlu import Parsed
        return Parsed(intent=self.intent, slots=self.slots)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "slots": self.slots,
            "confidence": self.confidence,
            "original_text": self.original_text,
            "source": self.source,
            "ambiguous": self.ambiguous,
            "clarification": (
                self.clarification.to_dict()
                if self.clarification else None
            ),
            "alternatives": self.alternatives,
            "category": self.category.value if self.category else None,
            "processing_time_ms": self.processing_time_ms,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentResult":
        """Create from dictionary."""
        result = cls(
            intent=data["intent"],
            slots=data.get("slots", {}),
            confidence=data.get("confidence", 1.0),
            original_text=data.get("original_text", ""),
            source=data.get("source", "unknown"),
            ambiguous=data.get("ambiguous", False),
            alternatives=data.get("alternatives", []),
            processing_time_ms=data.get("processing_time_ms", 0.0),
            metadata=data.get("metadata", {}),
        )
        
        if data.get("category"):
            result.category = IntentCategory(data["category"])
        
        if data.get("clarification"):
            result.clarification = ClarificationRequest.from_dict(data["clarification"])
        
        return result
    
    @classmethod
    def unknown(cls, text: str, source: str = "unknown") -> "IntentResult":
        """Create an unknown intent result."""
        return cls(
            intent="unknown",
            slots={},
            confidence=0.0,
            original_text=text,
            source=source,
            category=IntentCategory.UNKNOWN,
        )
    
    @classmethod
    def from_regex(
        cls,
        intent: str,
        slots: Dict[str, Any],
        text: str,
        confidence: float = 0.99,
    ) -> "IntentResult":
        """Create a result from regex matching."""
        return cls(
            intent=intent,
            slots=slots,
            confidence=confidence,
            original_text=text,
            source="regex",
        )
    
    @classmethod
    def from_llm(
        cls,
        intent: str,
        slots: Dict[str, Any],
        text: str,
        confidence: float,
        alternatives: Optional[List[Tuple[str, float]]] = None,
        processing_time_ms: float = 0.0,
    ) -> "IntentResult":
        """Create a result from LLM classification."""
        return cls(
            intent=intent,
            slots=slots,
            confidence=confidence,
            original_text=text,
            source="llm",
            alternatives=alternatives or [],
            processing_time_ms=processing_time_ms,
        )
    
    def __str__(self) -> str:
        slots_str = ", ".join(f"{k}={v!r}" for k, v in self.slots.items())
        return f"IntentResult({self.intent}, [{slots_str}], conf={self.confidence:.2f})"
    
    def __repr__(self) -> str:
        return self.__str__()


# ============================================================================
# Stats
# ============================================================================


@dataclass
class NLUStats:
    """Statistics for NLU performance tracking.
    
    Tracks:
    - Classification counts by source (regex/LLM)
    - Average latency
    - Clarification rates
    - Intent distribution
    """
    
    total_requests: int = 0
    regex_hits: int = 0
    llm_hits: int = 0
    clarifications_requested: int = 0
    clarifications_resolved: int = 0
    
    total_latency_ms: float = 0.0
    regex_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    
    intent_counts: Dict[str, int] = field(default_factory=dict)
    category_counts: Dict[str, int] = field(default_factory=dict)
    confidence_sum: float = 0.0
    
    errors: int = 0
    
    def record_result(self, result: IntentResult):
        """Record a classification result."""
        self.total_requests += 1
        self.confidence_sum += result.confidence
        
        # Track source
        if result.source == "regex":
            self.regex_hits += 1
            self.regex_latency_ms += result.processing_time_ms
        elif result.source == "llm":
            self.llm_hits += 1
            self.llm_latency_ms += result.processing_time_ms
        
        self.total_latency_ms += result.processing_time_ms
        
        # Track clarifications
        if result.clarification:
            self.clarifications_requested += 1
        
        # Track intents
        self.intent_counts[result.intent] = self.intent_counts.get(result.intent, 0) + 1
        
        # Track categories
        if result.category:
            cat_name = result.category.value
            self.category_counts[cat_name] = self.category_counts.get(cat_name, 0) + 1
    
    def record_clarification_resolved(self):
        """Record that a clarification was resolved."""
        self.clarifications_resolved += 1
    
    def record_error(self):
        """Record an error."""
        self.errors += 1
    
    @property
    def regex_rate(self) -> float:
        """Percentage of requests handled by regex."""
        if self.total_requests == 0:
            return 0.0
        return (self.regex_hits / self.total_requests) * 100
    
    @property
    def llm_rate(self) -> float:
        """Percentage of requests handled by LLM."""
        if self.total_requests == 0:
            return 0.0
        return (self.llm_hits / self.total_requests) * 100
    
    @property
    def average_confidence(self) -> float:
        """Average confidence score."""
        if self.total_requests == 0:
            return 0.0
        return self.confidence_sum / self.total_requests
    
    @property
    def average_latency_ms(self) -> float:
        """Average processing time in milliseconds."""
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests
    
    @property
    def average_regex_latency_ms(self) -> float:
        """Average regex processing time."""
        if self.regex_hits == 0:
            return 0.0
        return self.regex_latency_ms / self.regex_hits
    
    @property
    def average_llm_latency_ms(self) -> float:
        """Average LLM processing time."""
        if self.llm_hits == 0:
            return 0.0
        return self.llm_latency_ms / self.llm_hits
    
    @property
    def clarification_rate(self) -> float:
        """Percentage of requests needing clarification."""
        if self.total_requests == 0:
            return 0.0
        return (self.clarifications_requested / self.total_requests) * 100
    
    def top_intents(self, n: int = 10) -> List[Tuple[str, int]]:
        """Get top N intents by count."""
        sorted_intents = sorted(
            self.intent_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_intents[:n]
    
    def summary(self) -> str:
        """Get a summary of stats."""
        lines = [
            "=== NLU Stats ===",
            f"Total requests: {self.total_requests}",
            f"Regex hits: {self.regex_hits} ({self.regex_rate:.1f}%)",
            f"LLM hits: {self.llm_hits} ({self.llm_rate:.1f}%)",
            f"Average confidence: {self.average_confidence:.2f}",
            f"Average latency: {self.average_latency_ms:.1f}ms",
            f"  Regex: {self.average_regex_latency_ms:.1f}ms",
            f"  LLM: {self.average_llm_latency_ms:.1f}ms",
            f"Clarifications: {self.clarifications_requested} ({self.clarification_rate:.1f}%)",
            f"Errors: {self.errors}",
            "",
            "Top intents:",
        ]
        
        for intent, count in self.top_intents(5):
            pct = (count / self.total_requests * 100) if self.total_requests > 0 else 0
            lines.append(f"  {intent}: {count} ({pct:.1f}%)")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_requests": self.total_requests,
            "regex_hits": self.regex_hits,
            "llm_hits": self.llm_hits,
            "regex_rate": self.regex_rate,
            "llm_rate": self.llm_rate,
            "average_confidence": self.average_confidence,
            "average_latency_ms": self.average_latency_ms,
            "clarifications_requested": self.clarifications_requested,
            "clarifications_resolved": self.clarifications_resolved,
            "clarification_rate": self.clarification_rate,
            "errors": self.errors,
            "intent_counts": self.intent_counts,
            "category_counts": self.category_counts,
        }
    
    def reset(self):
        """Reset all statistics."""
        self.total_requests = 0
        self.regex_hits = 0
        self.llm_hits = 0
        self.clarifications_requested = 0
        self.clarifications_resolved = 0
        self.total_latency_ms = 0.0
        self.regex_latency_ms = 0.0
        self.llm_latency_ms = 0.0
        self.intent_counts.clear()
        self.category_counts.clear()
        self.confidence_sum = 0.0
        self.errors = 0
