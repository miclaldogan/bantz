"""
Feedback Phrase Registry for V2-6 (Issue #38).

Standard phrases for conversation feedback:
- Acknowledgment: "Anladım", "Tamam", "Peki"
- Confirmation: "Emin misin?", "Onaylıyor musun?"
- Error: "Bir hata oluştu", "Yapamadım"
- Thinking: "Bakayım", "Bir saniye"
- Success: "Tamamlandı", "Yaptım"
- Clarification: "Ne demek istedin?", "Tekrar eder misin?"
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# =============================================================================
# Feedback Type
# =============================================================================


class FeedbackType(Enum):
    """Types of feedback phrases."""
    
    ACKNOWLEDGMENT = "ack"       # "Anladım", "Tamam", "Peki"
    CONFIRMATION = "confirm"     # "Emin misin?", "Onaylıyor musun?"
    ERROR = "error"              # "Bir hata oluştu", "Yapamadım"
    THINKING = "thinking"        # "Bakayım", "Bir saniye"
    SUCCESS = "success"          # "Tamamlandı", "Yaptım"
    CLARIFICATION = "clarify"    # "Ne demek istedin?", "Tekrar eder misin?"
    GREETING = "greeting"        # "Merhaba", "Buyur"
    FAREWELL = "farewell"        # "Görüşürüz", "İyi günler"
    WAITING = "waiting"          # "Bekle bir dakika", "Hemen hallederim"


# =============================================================================
# Feedback Phrase
# =============================================================================


@dataclass
class FeedbackPhrase:
    """A feedback phrase with metadata."""
    
    phrase: str
    feedback_type: FeedbackType
    language: str = "tr"
    weight: float = 1.0  # Weight for random selection
    context: Optional[str] = None  # Optional context hint
    
    def __post_init__(self):
        """Validate weight."""
        if self.weight <= 0:
            self.weight = 1.0


# =============================================================================
# Default Phrases
# =============================================================================


DEFAULT_PHRASES_TR: Dict[FeedbackType, List[str]] = {
    FeedbackType.ACKNOWLEDGMENT: [
        "Anladım",
        "Tamam",
        "Peki",
        "Peki efendim",
        "Baş üstüne",
        "Olur",
        "Tabii",
    ],
    FeedbackType.CONFIRMATION: [
        "Emin misin?",
        "Onaylıyor musun?",
        "Bu işlemi yapmamı istiyor musun?",
        "Doğru mu anladım?",
        "Devam edeyim mi?",
    ],
    FeedbackType.ERROR: [
        "Bir hata oluştu",
        "Yapamadım",
        "Maalesef olmadı",
        "Bir sorun var",
        "Başaramadım",
        "Üzgünüm, bir hata oluştu",
    ],
    FeedbackType.THINKING: [
        "Bakayım",
        "Bir saniye",
        "Kontrol ediyorum",
        "Bir dakika",
        "Şimdi bakıyorum",
        "Hmm, düşüneyim",
    ],
    FeedbackType.SUCCESS: [
        "Tamamlandı",
        "Yaptım",
        "Hazır",
        "Bitti",
        "Oldu",
        "Hallettim",
        "Tamam, yaptım",
    ],
    FeedbackType.CLARIFICATION: [
        "Ne demek istedin?",
        "Tekrar eder misin?",
        "Anlamadım",
        "Biraz daha açıklar mısın?",
        "Ne yapmamı istiyorsun?",
    ],
    FeedbackType.GREETING: [
        "Merhaba",
        "Buyur",
        "Evet?",
        "Dinliyorum",
        "Seni duyuyorum",
    ],
    FeedbackType.FAREWELL: [
        "Görüşürüz",
        "İyi günler",
        "Kendine iyi bak",
        "Sonra görüşürüz",
        "Hoşça kal",
    ],
    FeedbackType.WAITING: [
        "Bekle bir dakika",
        "Hemen hallederim",
        "Şimdi yapıyorum",
        "Bir saniye bekle",
    ],
}

DEFAULT_PHRASES_EN: Dict[FeedbackType, List[str]] = {
    FeedbackType.ACKNOWLEDGMENT: [
        "Got it",
        "Okay",
        "Sure",
        "Alright",
        "Understood",
    ],
    FeedbackType.CONFIRMATION: [
        "Are you sure?",
        "Do you confirm?",
        "Should I proceed?",
        "Is that correct?",
    ],
    FeedbackType.ERROR: [
        "An error occurred",
        "I couldn't do that",
        "Sorry, that didn't work",
        "Something went wrong",
    ],
    FeedbackType.THINKING: [
        "Let me check",
        "One moment",
        "Looking into it",
        "Just a second",
        "Hmm, let me think",
    ],
    FeedbackType.SUCCESS: [
        "Done",
        "Completed",
        "All set",
        "Finished",
        "Got it done",
    ],
    FeedbackType.CLARIFICATION: [
        "What do you mean?",
        "Can you repeat that?",
        "I didn't understand",
        "Could you clarify?",
    ],
    FeedbackType.GREETING: [
        "Hello",
        "Hi there",
        "Yes?",
        "I'm listening",
    ],
    FeedbackType.FAREWELL: [
        "Goodbye",
        "See you later",
        "Take care",
        "Bye",
    ],
    FeedbackType.WAITING: [
        "Just a moment",
        "Working on it",
        "Give me a second",
    ],
}


# =============================================================================
# Feedback Registry
# =============================================================================


class FeedbackRegistry:
    """
    Registry for feedback phrases.
    
    Provides random selection with weights,
    language support, and custom phrase registration.
    """
    
    def __init__(self, language: str = "tr", load_defaults: bool = True):
        """
        Initialize registry.
        
        Args:
            language: Default language ("tr" or "en")
            load_defaults: Whether to load default phrases
        """
        self._language = language
        self._phrases: Dict[FeedbackType, List[FeedbackPhrase]] = {
            ft: [] for ft in FeedbackType
        }
        
        if load_defaults:
            self._load_defaults()
    
    def _load_defaults(self) -> None:
        """Load default phrases."""
        # Load Turkish phrases
        for feedback_type, phrases in DEFAULT_PHRASES_TR.items():
            for phrase in phrases:
                self._phrases[feedback_type].append(
                    FeedbackPhrase(
                        phrase=phrase,
                        feedback_type=feedback_type,
                        language="tr"
                    )
                )
        
        # Load English phrases
        for feedback_type, phrases in DEFAULT_PHRASES_EN.items():
            for phrase in phrases:
                self._phrases[feedback_type].append(
                    FeedbackPhrase(
                        phrase=phrase,
                        feedback_type=feedback_type,
                        language="en"
                    )
                )
    
    def register(self, phrase: FeedbackPhrase) -> None:
        """Register a new phrase."""
        self._phrases[phrase.feedback_type].append(phrase)
    
    def register_many(self, phrases: List[FeedbackPhrase]) -> int:
        """Register multiple phrases."""
        for phrase in phrases:
            self.register(phrase)
        return len(phrases)
    
    def get_random(
        self,
        feedback_type: FeedbackType,
        language: Optional[str] = None
    ) -> str:
        """
        Get a random phrase of the given type.
        
        Args:
            feedback_type: Type of feedback
            language: Language filter (None = use default)
            
        Returns:
            Random phrase string
        """
        lang = language or self._language
        
        # Filter by language
        candidates = [
            p for p in self._phrases[feedback_type]
            if p.language == lang
        ]
        
        if not candidates:
            # Fallback to any language
            candidates = self._phrases[feedback_type]
        
        if not candidates:
            return ""
        
        # Weighted random selection
        weights = [p.weight for p in candidates]
        total = sum(weights)
        
        if total == 0:
            return random.choice(candidates).phrase
        
        r = random.uniform(0, total)
        cumulative = 0
        for phrase, weight in zip(candidates, weights):
            cumulative += weight
            if r <= cumulative:
                return phrase.phrase
        
        return candidates[-1].phrase
    
    def get_all(
        self,
        feedback_type: FeedbackType,
        language: Optional[str] = None
    ) -> List[str]:
        """
        Get all phrases of the given type.
        
        Args:
            feedback_type: Type of feedback
            language: Language filter (None = all languages)
            
        Returns:
            List of phrase strings
        """
        if language:
            return [
                p.phrase for p in self._phrases[feedback_type]
                if p.language == language
            ]
        return [p.phrase for p in self._phrases[feedback_type]]
    
    def get_phrase_objects(
        self,
        feedback_type: FeedbackType,
        language: Optional[str] = None
    ) -> List[FeedbackPhrase]:
        """Get phrase objects (not just strings)."""
        if language:
            return [
                p for p in self._phrases[feedback_type]
                if p.language == language
            ]
        return list(self._phrases[feedback_type])
    
    def set_language(self, language: str) -> None:
        """Set default language."""
        self._language = language
    
    @property
    def language(self) -> str:
        """Get default language."""
        return self._language
    
    def count(self, feedback_type: Optional[FeedbackType] = None) -> int:
        """Count phrases."""
        if feedback_type:
            return len(self._phrases[feedback_type])
        return sum(len(phrases) for phrases in self._phrases.values())
    
    def clear(self, feedback_type: Optional[FeedbackType] = None) -> int:
        """Clear phrases."""
        if feedback_type:
            count = len(self._phrases[feedback_type])
            self._phrases[feedback_type].clear()
            return count
        
        count = self.count()
        for ft in FeedbackType:
            self._phrases[ft].clear()
        return count


def create_feedback_registry(
    language: str = "tr",
    load_defaults: bool = True
) -> FeedbackRegistry:
    """Factory for creating feedback registry."""
    return FeedbackRegistry(language=language, load_defaults=load_defaults)
