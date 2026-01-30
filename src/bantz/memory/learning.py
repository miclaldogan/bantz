"""
Learning Engine - Learn from interactions automatically.

Extracts facts, preferences, and patterns from user interactions
to improve personalization over time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple

from bantz.memory.types import (
    Memory,
    MemoryType,
    ConversationMemory,
    TaskMemory,
    PreferenceMemory,
    FactMemory,
)
from bantz.memory.store import MemoryStore
from bantz.memory.profile import ProfileManager, UserProfile


@dataclass
class ExtractedFact:
    """A fact extracted from user input."""
    
    category: str       # name, job, location, etc.
    value: str          # The actual value
    confidence: float   # 0.0 - 1.0
    source: str         # Pattern that matched
    original_text: str  # Original user text
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "category": self.category,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "original_text": self.original_text,
        }


@dataclass
class ExtractedPreference:
    """A preference extracted from user input."""
    
    key: str            # Preference key (e.g., app.discord.monitor)
    value: Any          # Preference value
    confidence: float   # 0.0 - 1.0
    reason: str         # Why this was extracted
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class InteractionResult:
    """Result of a task or interaction."""
    
    description: str
    success: bool
    duration_seconds: float = 0.0
    steps: List[str] = field(default_factory=list)
    apps_used: List[str] = field(default_factory=list)
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def success_result(
        cls,
        description: str,
        duration: float = 0.0,
        steps: List[str] = None,
        apps: List[str] = None,
    ) -> InteractionResult:
        """Create a successful result."""
        return cls(
            description=description,
            success=True,
            duration_seconds=duration,
            steps=steps or [],
            apps_used=apps or [],
        )
    
    @classmethod
    def failure_result(
        cls,
        description: str,
        error: str,
        duration: float = 0.0,
    ) -> InteractionResult:
        """Create a failure result."""
        return cls(
            description=description,
            success=False,
            duration_seconds=duration,
            error_message=error,
        )


@dataclass
class LearningConfig:
    """Configuration for learning engine."""
    
    # Feature toggles
    learn_facts: bool = True
    learn_preferences: bool = True
    learn_patterns: bool = True
    store_conversations: bool = True
    store_tasks: bool = True
    
    # Confidence thresholds
    min_fact_confidence: float = 0.5
    min_preference_confidence: float = 0.4
    
    # Importance settings
    conversation_importance: float = 0.3
    task_success_importance: float = 0.6
    task_failure_importance: float = 0.3
    fact_importance: float = 0.8
    preference_importance: float = 0.7
    
    # Topic extraction
    extract_topics: bool = True
    max_topic_length: int = 50
    
    # Sentiment analysis (simple)
    analyze_sentiment: bool = True


class FactExtractor:
    """Extract facts from user text using patterns."""
    
    def __init__(self):
        """Initialize fact extractor with patterns."""
        # Turkish patterns for fact extraction
        self.patterns: List[Tuple[Pattern, str, str]] = [
            # Name patterns
            (re.compile(r"(?:benim\s+)?ad[ıi]m\s+(\w+)", re.IGNORECASE), "name", "name_statement"),
            (re.compile(r"ben\s+(\w+)(?:'(?:y[ıi]m|[yi]m))?", re.IGNORECASE), "name", "name_intro"),
            (re.compile(r"bana\s+(\w+)\s+de(?:rler|yin)", re.IGNORECASE), "name", "name_nickname"),
            
            # Job patterns
            (re.compile(r"(?:ben\s+)?(?:bir\s+)?(\w+(?:\s+\w+)?)\s*(?:olarak\s+)?çalışıyorum", re.IGNORECASE), "job", "job_statement"),
            (re.compile(r"mesleğim\s+(\w+(?:\s+\w+)?)", re.IGNORECASE), "job", "job_profession"),
            (re.compile(r"(\w+(?:\s+\w+)?)\s*(?:'y[ıi]m|y[ıi]m)", re.IGNORECASE), "job", "job_title"),
            
            # Location patterns
            (re.compile(r"(?:ben\s+)?(\w+)'?(?:da|de|ta|te)\s+(?:yaşıyorum|oturuyorum)", re.IGNORECASE), "location", "location_live"),
            (re.compile(r"(\w+)'?(?:dan|den|tan|ten)\s+(?:geliyorum|arıyorum)", re.IGNORECASE), "location", "location_from"),
            
            # Age patterns
            (re.compile(r"(\d{1,3})\s+yaşındayım", re.IGNORECASE), "age", "age_statement"),
            (re.compile(r"yaşım\s+(\d{1,3})", re.IGNORECASE), "age", "age_number"),
            
            # Birthday patterns
            (re.compile(r"doğum\s+günüm\s+(\d{1,2})\s+(\w+)", re.IGNORECASE), "birthday", "birthday_date"),
            
            # Email patterns
            (re.compile(r"(?:e-?mail(?:im)?|posta(?:m)?)\s*[:=]?\s*(\S+@\S+\.\S+)", re.IGNORECASE), "email", "email_statement"),
            
            # Phone patterns
            (re.compile(r"(?:telefon(?:um)?|numara(?:m)?)\s*[:=]?\s*(\+?\d[\d\s-]{8,})", re.IGNORECASE), "phone", "phone_statement"),
            
            # Company patterns
            (re.compile(r"(\w+(?:\s+\w+)?)'?(?:da|de|ta|te)\s+çalışıyorum", re.IGNORECASE), "company", "company_work"),
            (re.compile(r"şirket(?:im)?\s+(\w+(?:\s+\w+)?)", re.IGNORECASE), "company", "company_name"),
            
            # Hobby patterns
            (re.compile(r"(?:hobim|hobilerim)\s+(.+?)(?:\.|$)", re.IGNORECASE), "hobby", "hobby_statement"),
            (re.compile(r"(\w+)\s+(?:oynamayı|yapmayı|izlemeyi)\s+seviyorum", re.IGNORECASE), "hobby", "hobby_like"),
        ]
    
    def extract(self, text: str) -> List[ExtractedFact]:
        """
        Extract facts from text.
        
        Args:
            text: User input text
            
        Returns:
            List of extracted facts
        """
        facts = []
        text_lower = text.lower()
        
        for pattern, category, source in self.patterns:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                
                # Calculate confidence based on pattern specificity
                confidence = self._calculate_confidence(source, text_lower)
                
                facts.append(ExtractedFact(
                    category=category,
                    value=value,
                    confidence=confidence,
                    source=source,
                    original_text=text,
                ))
        
        return facts
    
    def _calculate_confidence(self, source: str, text: str) -> float:
        """Calculate confidence based on source and context."""
        # Higher confidence for explicit statements
        high_confidence_sources = ["name_statement", "job_profession", "age_statement", "email_statement"]
        if source in high_confidence_sources:
            return 0.9
        
        # Medium confidence for contextual mentions
        medium_confidence_sources = ["name_intro", "job_statement", "location_live"]
        if source in medium_confidence_sources:
            return 0.7
        
        # Lower confidence for inferences
        return 0.5


class PreferenceExtractor:
    """Extract preferences from user input."""
    
    def __init__(self):
        """Initialize preference extractor with patterns."""
        self.patterns: List[Tuple[Pattern, str, str]] = [
            # App positioning
            (re.compile(r"(\w+)'?[yi]?\s+(?:her\s+zaman\s+)?(?:sol|sağ)\s+(?:monitör|ekran)(?:'?[ea]|\s+tarafına?)\s*(?:aç|koy)", re.IGNORECASE), 
             "app.{}.monitor", "monitor_preference"),
            
            # Volume preferences
            (re.compile(r"ses(?:i)?\s+(\d+)(?:\s*%)?", re.IGNORECASE), 
             "audio.volume", "volume_preference"),
            
            # Brightness
            (re.compile(r"parlaklı[kğ](?:ı)?\s+(\d+)(?:\s*%)?", re.IGNORECASE), 
             "display.brightness", "brightness_preference"),
            
            # Default browser
            (re.compile(r"(?:varsayılan\s+)?tarayıcı(?:m)?\s+(\w+)", re.IGNORECASE), 
             "browser.default", "browser_preference"),
            
            # Default editor
            (re.compile(r"(?:varsayılan\s+)?editör(?:üm)?\s+(\w+)", re.IGNORECASE), 
             "editor.default", "editor_preference"),
            
            # Theme preference
            (re.compile(r"(karanlık|koyu|dark|aydınlık|açık|light)\s+(?:tema|mod)", re.IGNORECASE), 
             "theme.mode", "theme_preference"),
            
            # Notification preference
            (re.compile(r"bildirim(?:ler)?(?:i)?\s+(aç|kapat|kapa)", re.IGNORECASE), 
             "notifications.enabled", "notification_preference"),
            
            # Language preference
            (re.compile(r"(?:dil(?:im)?|language)\s+(\w+)", re.IGNORECASE), 
             "language.preferred", "language_preference"),
            
            # Time format
            (re.compile(r"(\d{2})\s*saat(?:lik)?\s+format", re.IGNORECASE), 
             "time.format", "time_format_preference"),
        ]
    
    def extract(self, text: str) -> List[ExtractedPreference]:
        """
        Extract preferences from text.
        
        Args:
            text: User input text
            
        Returns:
            List of extracted preferences
        """
        preferences = []
        
        for pattern, key_template, reason in self.patterns:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                
                # Format key if it has placeholders
                if "{}" in key_template:
                    key = key_template.format(value.lower())
                else:
                    key = key_template
                
                # Convert value to appropriate type
                processed_value = self._process_value(key, value)
                
                preferences.append(ExtractedPreference(
                    key=key,
                    value=processed_value,
                    confidence=0.7,
                    reason=reason,
                ))
        
        return preferences
    
    def _process_value(self, key: str, value: str) -> Any:
        """Process and convert value to appropriate type."""
        value_lower = value.lower()
        
        # Boolean conversions
        if key.endswith(".enabled"):
            return value_lower in ["aç", "açık", "on", "true", "evet"]
        
        # Number conversions
        if key in ["audio.volume", "display.brightness"]:
            try:
                return int(value)
            except ValueError:
                return value
        
        # Theme mode
        if key == "theme.mode":
            if value_lower in ["karanlık", "koyu", "dark"]:
                return "dark"
            else:
                return "light"
        
        # Monitor preference
        if "monitor" in key:
            if "sol" in value_lower:
                return "left"
            elif "sağ" in value_lower:
                return "right"
        
        return value


class TopicExtractor:
    """Extract conversation topics."""
    
    # Common Turkish question words and patterns
    TOPIC_PATTERNS = [
        (re.compile(r"(?:nasıl|ne\s+şekilde)\s+(.+?)(?:\?|$)", re.IGNORECASE), "how"),
        (re.compile(r"(?:neden|niçin)\s+(.+?)(?:\?|$)", re.IGNORECASE), "why"),
        (re.compile(r"(?:ne\s+zaman)\s+(.+?)(?:\?|$)", re.IGNORECASE), "when"),
        (re.compile(r"(?:nerede|nereye)\s+(.+?)(?:\?|$)", re.IGNORECASE), "where"),
        (re.compile(r"(?:kim)\s+(.+?)(?:\?|$)", re.IGNORECASE), "who"),
        (re.compile(r"(.+?)\s+(?:aç|kapat|başlat|durdur|yap|et)", re.IGNORECASE), "action"),
    ]
    
    # Keywords that indicate topics
    TOPIC_KEYWORDS = {
        "programming": ["kod", "program", "yazılım", "geliştir", "debug", "compile"],
        "browser": ["tarayıcı", "browser", "chrome", "firefox", "web", "site"],
        "file": ["dosya", "klasör", "file", "folder", "kopyala", "sil", "taşı"],
        "system": ["sistem", "windows", "linux", "bilgisayar", "pc"],
        "media": ["müzik", "video", "film", "spotify", "youtube"],
        "communication": ["mail", "mesaj", "discord", "slack", "teams"],
        "productivity": ["takvim", "not", "todo", "hatırlatıcı", "meeting"],
    }
    
    def extract(self, text: str, max_length: int = 50) -> str:
        """
        Extract main topic from text.
        
        Args:
            text: User input text
            max_length: Maximum topic length
            
        Returns:
            Extracted topic or empty string
        """
        text_lower = text.lower()
        
        # Try keyword matching first
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return topic
        
        # Try pattern matching
        for pattern, topic_type in self.TOPIC_PATTERNS:
            match = pattern.search(text)
            if match:
                topic = match.group(1).strip()
                if len(topic) <= max_length:
                    return topic[:max_length]
        
        # Default: first few words
        words = text.split()[:5]
        return " ".join(words)[:max_length]


class SentimentAnalyzer:
    """Simple sentiment analysis for Turkish text."""
    
    # Positive words
    POSITIVE_WORDS = [
        "teşekkür", "sağol", "harika", "mükemmel", "güzel", "süper",
        "iyi", "başarılı", "tamam", "evet", "sevdim", "beğendim",
        "aferin", "bravo", "helal", "muhteşem", "fantastik",
    ]
    
    # Negative words
    NEGATIVE_WORDS = [
        "kötü", "berbat", "hayır", "olmadı", "hata", "yanlış",
        "problem", "sorun", "başarısız", "olmaz", "istemiyorum",
        "sinir", "kızgın", "hayal kırıklığı", "rezalet",
    ]
    
    def analyze(self, text: str) -> float:
        """
        Analyze sentiment of text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Sentiment score (-1.0 to 1.0)
        """
        text_lower = text.lower()
        
        positive_count = sum(1 for word in self.POSITIVE_WORDS if word in text_lower)
        negative_count = sum(1 for word in self.NEGATIVE_WORDS if word in text_lower)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        return (positive_count - negative_count) / total


class LearningEngine:
    """
    Learn from interactions automatically.
    
    Processes user inputs and interaction results to:
    - Extract and store facts
    - Learn preferences
    - Store conversation memories
    - Track task history
    """
    
    def __init__(
        self,
        memory_store: MemoryStore,
        profile_manager: ProfileManager,
        config: Optional[LearningConfig] = None,
    ):
        """
        Initialize learning engine.
        
        Args:
            memory_store: Memory storage
            profile_manager: User profile manager
            config: Learning configuration
        """
        self.memory = memory_store
        self.profile = profile_manager
        self.config = config or LearningConfig()
        
        # Extractors
        self.fact_extractor = FactExtractor()
        self.preference_extractor = PreferenceExtractor()
        self.topic_extractor = TopicExtractor()
        self.sentiment_analyzer = SentimentAnalyzer()
        
        # Session tracking
        self.session_id: Optional[str] = None
        self.interaction_count = 0
    
    def start_session(self, session_id: str) -> None:
        """Start a new learning session."""
        self.session_id = session_id
        self.interaction_count = 0
        self.profile.start_session()
    
    def process_interaction(
        self,
        user_input: str,
        assistant_response: str,
        task_result: Optional[InteractionResult] = None,
    ) -> Dict[str, Any]:
        """
        Learn from a single interaction.
        
        Args:
            user_input: User's input message
            assistant_response: Assistant's response
            task_result: Optional task execution result
            
        Returns:
            Dictionary of learned items
        """
        learned = {
            "facts": [],
            "preferences": [],
            "memory_id": None,
            "task_id": None,
        }
        
        self.interaction_count += 1
        self.profile.record_interaction()
        
        # Extract and learn facts
        if self.config.learn_facts:
            facts = self._extract_and_store_facts(user_input)
            learned["facts"] = [f.to_dict() for f in facts]
        
        # Extract and learn preferences
        if self.config.learn_preferences:
            prefs = self._extract_and_store_preferences(user_input)
            learned["preferences"] = [p.to_dict() for p in prefs]
        
        # Store conversation memory
        if self.config.store_conversations:
            memory_id = self._store_conversation(user_input, assistant_response)
            learned["memory_id"] = memory_id
        
        # Store task memory if provided
        if task_result and self.config.store_tasks:
            task_id = self._store_task(task_result)
            learned["task_id"] = task_id
            
            # Record apps used
            for app in task_result.apps_used:
                self.profile.record_app_usage(app)
            
            # Record task type
            if task_result.success:
                self.profile.record_task(task_result.description)
        
        return learned
    
    def _extract_and_store_facts(self, text: str) -> List[ExtractedFact]:
        """Extract facts and store in profile."""
        facts = self.fact_extractor.extract(text)
        
        stored_facts = []
        for fact in facts:
            if fact.confidence >= self.config.min_fact_confidence:
                # Store in profile
                self.profile.learn_fact(
                    category=fact.category,
                    value=fact.value,
                    source=fact.source,
                )
                
                # Store as memory
                memory = FactMemory.from_statement(
                    category=fact.category,
                    value=fact.value,
                    source="user_stated",
                )
                memory.session_id = self.session_id
                memory.importance = self.config.fact_importance
                self.memory.store(memory)
                
                stored_facts.append(fact)
        
        return stored_facts
    
    def _extract_and_store_preferences(self, text: str) -> List[ExtractedPreference]:
        """Extract preferences and store in profile."""
        prefs = self.preference_extractor.extract(text)
        
        stored_prefs = []
        for pref in prefs:
            if pref.confidence >= self.config.min_preference_confidence:
                # Store in profile
                self.profile.learn_preference(
                    key=pref.key,
                    value=pref.value,
                    confidence=pref.confidence,
                    source=pref.reason,
                )
                
                # Store as memory
                memory = PreferenceMemory.from_observation(
                    key=pref.key,
                    value=pref.value,
                    confidence=pref.confidence,
                )
                memory.session_id = self.session_id
                memory.importance = self.config.preference_importance
                self.memory.store(memory)
                
                stored_prefs.append(pref)
        
        return stored_prefs
    
    def _store_conversation(self, user_input: str, assistant_response: str) -> str:
        """Store conversation as memory."""
        # Extract topic
        topic = ""
        if self.config.extract_topics:
            topic = self.topic_extractor.extract(user_input, self.config.max_topic_length)
        
        # Analyze sentiment
        sentiment = 0.0
        if self.config.analyze_sentiment:
            sentiment = self.sentiment_analyzer.analyze(user_input)
        
        # Calculate importance
        importance = self._calculate_conversation_importance(
            user_input,
            assistant_response,
            sentiment,
        )
        
        # Create and store memory
        memory = ConversationMemory.from_exchange(
            user_message=user_input,
            assistant_response=assistant_response,
            topic=topic,
            sentiment=sentiment,
            importance=importance,
        )
        memory.session_id = self.session_id
        
        return self.memory.store(memory)
    
    def _calculate_conversation_importance(
        self,
        user_input: str,
        response: str,
        sentiment: float,
    ) -> float:
        """Calculate importance of a conversation."""
        importance = self.config.conversation_importance
        
        # Longer conversations might be more important
        if len(user_input) > 100:
            importance += 0.1
        
        # Questions might be more important
        if "?" in user_input:
            importance += 0.1
        
        # Strong sentiment indicates importance
        if abs(sentiment) > 0.5:
            importance += 0.1
        
        return min(1.0, importance)
    
    def _store_task(self, result: InteractionResult) -> str:
        """Store task result as memory."""
        memory = TaskMemory.from_execution(
            description=result.description,
            steps=result.steps,
            success=result.success,
            duration=result.duration_seconds,
            error=result.error_message,
            apps=result.apps_used,
        )
        memory.session_id = self.session_id
        memory.importance = (
            self.config.task_success_importance 
            if result.success 
            else self.config.task_failure_importance
        )
        
        return self.memory.store(memory)
    
    def learn_from_correction(
        self,
        original_response: str,
        correction: str,
        preference_key: Optional[str] = None,
    ) -> None:
        """
        Learn from user correction.
        
        Args:
            original_response: What assistant said
            correction: User's correction
            preference_key: Optional preference to update
        """
        # Store as conversation with high importance
        memory = ConversationMemory.from_exchange(
            user_message=f"Düzeltme: {correction}",
            assistant_response=original_response,
            topic="correction",
            importance=0.8,
        )
        memory.session_id = self.session_id
        memory.tags.append("correction")
        self.memory.store(memory)
        
        # If preference key provided, update with correction
        if preference_key:
            self.profile.learn_preference(
                key=preference_key,
                value=correction,
                confidence=0.9,  # High confidence from explicit correction
                source="user_correction",
            )
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about learning."""
        return {
            "session_id": self.session_id,
            "interaction_count": self.interaction_count,
            "total_memories": self.memory.get_stats().total_memories,
            "known_facts": len(self.profile.profile.facts),
            "learned_preferences": len(self.profile.profile.preferences),
        }
    
    def forget_fact(self, category: str) -> bool:
        """
        Forget a specific fact.
        
        Args:
            category: Fact category to forget
            
        Returns:
            True if fact was found and forgotten
        """
        if category in self.profile.profile.facts:
            del self.profile.profile.facts[category]
            self.profile.save()
            return True
        return False
    
    def reset_preferences(self) -> int:
        """Reset all learned preferences."""
        count = len(self.profile.profile.preferences)
        self.profile.profile.preferences.clear()
        self.profile.save()
        return count
