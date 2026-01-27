"""Emotion Detection for TTS (Issue #10).

Selects appropriate emotion based on context, intent, and success state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, TYPE_CHECKING

from bantz.voice.advanced_tts import Emotion

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────
# Emotion Patterns
# ─────────────────────────────────────────────────────────────────

# Words/patterns that indicate specific emotions
EMOTION_PATTERNS: Dict[Emotion, List[str]] = {
    Emotion.HAPPY: [
        "başardım", "başardık", "tamamlandı", "harika", "mükemmel",
        "süper", "muhteşem", "bravo", "aferin", "güzel",
        "başarılı", "tebrikler", "kutlarım", "sevindim",
        "iyi haber", "güzel haber", "mutluyum",
    ],
    Emotion.EXCITED: [
        "heyecanlı", "şaşırtıcı", "inanılmaz", "vay",
        "acil", "hızlıca", "çabuk", "hemen",
        "son dakika", "breaking", "önemli gelişme",
    ],
    Emotion.SERIOUS: [
        "dikkat", "uyarı", "önemli", "kritik",
        "tehlike", "risk", "sorun", "problem",
        "hata", "başarısız", "iptal", "durdur",
    ],
    Emotion.CONCERNED: [
        "maalesef", "üzgünüm", "ne yazık", "kötü haber",
        "endişe", "merak", "şüphe", "belirsiz",
        "bulunamadı", "erişilemiyor", "başarısız oldu",
    ],
    Emotion.CALM: [
        "tamam", "anladım", "olur", "evet efendim",
        "peki", "tabii", "elbette", "şimdi",
        "işte", "buyurun", "efendim",
    ],
}

# Intent to emotion mapping
INTENT_EMOTIONS: Dict[str, Emotion] = {
    # Success intents
    "browser_open": Emotion.NEUTRAL,
    "google_search": Emotion.NEUTRAL,
    "news_briefing": Emotion.NEUTRAL,
    
    # Warning/error intents
    "unknown": Emotion.CONCERNED,
    
    # Confirmation intents
    "confirm_yes": Emotion.HAPPY,
    "confirm_no": Emotion.NEUTRAL,
    
    # Agent intents
    "agent_run": Emotion.NEUTRAL,
    "agent_status": Emotion.NEUTRAL,
}


# ─────────────────────────────────────────────────────────────────
# Emotion Context
# ─────────────────────────────────────────────────────────────────

@dataclass
class EmotionContext:
    """Context for emotion selection.
    
    Attributes:
        text: Response text to analyze
        intent: Detected intent
        success: Whether operation was successful
        user_mood: Inferred user mood
        urgency: Urgency level (0.0 - 1.0)
    """
    text: str = ""
    intent: str = ""
    success: bool = True
    user_mood: Optional[str] = None
    urgency: float = 0.0
    previous_emotion: Optional[Emotion] = None


@dataclass
class EmotionResult:
    """Result of emotion selection.
    
    Attributes:
        emotion: Selected emotion
        confidence: Confidence score (0.0 - 1.0)
        reason: Explanation for selection
        matched_patterns: Patterns that triggered this emotion
    """
    emotion: Emotion
    confidence: float
    reason: str = ""
    matched_patterns: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Emotion Selector
# ─────────────────────────────────────────────────────────────────

class EmotionSelector:
    """Select appropriate TTS emotion based on context.
    
    Uses text analysis, intent, and success state to determine
    the most appropriate emotional tone for speech synthesis.
    
    Usage:
        selector = EmotionSelector()
        
        # From text
        result = selector.select_from_text("Harika bir haber var!")
        # result.emotion == Emotion.HAPPY
        
        # From context
        context = EmotionContext(
            text="İşlem başarısız oldu",
            intent="unknown",
            success=False,
        )
        result = selector.select(context)
        # result.emotion == Emotion.CONCERNED
    """
    
    def __init__(self):
        """Initialize emotion selector."""
        self._pattern_cache: Dict[Emotion, re.Pattern] = {}
        self._build_pattern_cache()
    
    def _build_pattern_cache(self) -> None:
        """Build regex patterns from emotion words."""
        for emotion, words in EMOTION_PATTERNS.items():
            pattern = r"\b(" + "|".join(re.escape(w) for w in words) + r")\b"
            self._pattern_cache[emotion] = re.compile(pattern, re.IGNORECASE)
    
    # ─────────────────────────────────────────────────────────────
    # Main API
    # ─────────────────────────────────────────────────────────────
    
    def select(self, context: EmotionContext) -> EmotionResult:
        """Select emotion based on full context.
        
        Priority:
        1. Success state (failure -> concerned)
        2. Text patterns
        3. Intent mapping
        4. Default to neutral
        
        Args:
            context: Emotion context
            
        Returns:
            EmotionResult with selected emotion
        """
        # Check success state first
        if not context.success:
            return EmotionResult(
                emotion=Emotion.CONCERNED,
                confidence=0.9,
                reason="Operation failed",
            )
        
        # Check text patterns
        text_result = self._analyze_text(context.text)
        if text_result.confidence > 0.6:
            return text_result
        
        # Check intent mapping
        if context.intent in INTENT_EMOTIONS:
            return EmotionResult(
                emotion=INTENT_EMOTIONS[context.intent],
                confidence=0.7,
                reason=f"Intent: {context.intent}",
            )
        
        # Check urgency
        if context.urgency > 0.7:
            return EmotionResult(
                emotion=Emotion.EXCITED,
                confidence=0.6,
                reason="High urgency",
            )
        
        # Default to neutral
        return EmotionResult(
            emotion=Emotion.NEUTRAL,
            confidence=0.5,
            reason="Default",
        )
    
    def select_from_text(self, text: str) -> EmotionResult:
        """Select emotion based on text only.
        
        Args:
            text: Text to analyze
            
        Returns:
            EmotionResult
        """
        return self._analyze_text(text)
    
    def select_for_response(
        self,
        text: str,
        intent: str,
        success: bool,
    ) -> Emotion:
        """Simple emotion selection for responses.
        
        Args:
            text: Response text
            intent: Intent name
            success: Whether operation succeeded
            
        Returns:
            Selected Emotion
        """
        context = EmotionContext(
            text=text,
            intent=intent,
            success=success,
        )
        return self.select(context).emotion
    
    # ─────────────────────────────────────────────────────────────
    # Text Analysis
    # ─────────────────────────────────────────────────────────────
    
    def _analyze_text(self, text: str) -> EmotionResult:
        """Analyze text for emotion patterns.
        
        Args:
            text: Text to analyze
            
        Returns:
            EmotionResult
        """
        if not text:
            return EmotionResult(
                emotion=Emotion.NEUTRAL,
                confidence=0.3,
                reason="Empty text",
            )
        
        text_lower = text.lower()
        
        # Check each emotion pattern
        best_emotion = Emotion.NEUTRAL
        best_confidence = 0.0
        matched_patterns: List[str] = []
        
        for emotion, pattern in self._pattern_cache.items():
            matches = pattern.findall(text_lower)
            if matches:
                # More matches = higher confidence
                confidence = min(0.5 + len(matches) * 0.15, 0.95)
                if confidence > best_confidence:
                    best_emotion = emotion
                    best_confidence = confidence
                    matched_patterns = matches
        
        return EmotionResult(
            emotion=best_emotion,
            confidence=best_confidence,
            reason="Pattern matching",
            matched_patterns=matched_patterns,
        )
    
    def _detect_question(self, text: str) -> bool:
        """Check if text is a question.
        
        Args:
            text: Text to check
            
        Returns:
            True if text appears to be a question
        """
        question_indicators = ["?", "mi", "mı", "mu", "mü", "nedir", "ne zaman", "nasıl", "neden"]
        text_lower = text.lower()
        return any(q in text_lower for q in question_indicators)


# ─────────────────────────────────────────────────────────────────
# Jarvis Response Formatter
# ─────────────────────────────────────────────────────────────────

class JarvisResponseFormatter:
    """Format responses in Jarvis style with appropriate emotion.
    
    Adds emotional context and polite addressing to responses.
    
    Usage:
        formatter = JarvisResponseFormatter()
        
        response = formatter.format(
            "İşlem tamamlandı",
            Emotion.HAPPY,
        )
        # "İşlem tamamlandı efendim! 😊"
    """
    
    # Emotion to suffix mapping
    EMOTION_SUFFIXES = {
        Emotion.NEUTRAL: ["efendim.", "efendim."],
        Emotion.HAPPY: ["efendim! 😊", "efendim!", "efendim, başarıyla!"],
        Emotion.EXCITED: ["efendim! 🎉", "efendim!", "efendim, hemen!"],
        Emotion.SERIOUS: ["efendim.", "efendim, dikkat.", "efendim."],
        Emotion.CONCERNED: ["efendim.", "efendim, maalesef.", "üzgünüm efendim."],
        Emotion.CALM: ["efendim.", "efendim.", "efendim."],
        Emotion.ANGRY: ["efendim.", "efendim.", "efendim."],
    }
    
    # Emotion to prefix mapping (for emphasis)
    EMOTION_PREFIXES = {
        Emotion.EXCITED: ["Efendim!", "Hemen", ""],
        Emotion.CONCERNED: ["Maalesef", "Ne yazık ki", ""],
        Emotion.HAPPY: ["Harika!", "Güzel haber:", ""],
    }
    
    def __init__(self, use_emoji: bool = True):
        """Initialize formatter.
        
        Args:
            use_emoji: Whether to include emoji in responses
        """
        self.use_emoji = use_emoji
    
    def format(
        self,
        text: str,
        emotion: Emotion = Emotion.NEUTRAL,
        add_prefix: bool = False,
    ) -> str:
        """Format text with emotion.
        
        Args:
            text: Response text
            emotion: Emotion to apply
            add_prefix: Whether to add emotional prefix
            
        Returns:
            Formatted response
        """
        text = text.strip()
        
        # Add prefix if requested
        if add_prefix and emotion in self.EMOTION_PREFIXES:
            prefixes = self.EMOTION_PREFIXES[emotion]
            import random
            prefix = random.choice(prefixes)
            if prefix:
                text = f"{prefix} {text}"
        
        # Check if already has "efendim"
        if "efendim" in text.lower():
            return text
        
        # Add suffix
        suffixes = self.EMOTION_SUFFIXES.get(emotion, ["efendim."])
        
        # Remove emoji if disabled
        if not self.use_emoji:
            suffixes = [s.split()[0] if " " in s else s.replace("😊", "").replace("🎉", "").strip() for s in suffixes]
        
        import random
        suffix = random.choice(suffixes)
        
        # Add suffix appropriately
        if text.endswith((".", "!", "?")):
            # Replace ending punctuation
            text = text[:-1] + " " + suffix
        else:
            text = text + " " + suffix
        
        return text


# ─────────────────────────────────────────────────────────────────
# Mock Selector for Testing
# ─────────────────────────────────────────────────────────────────

class MockEmotionSelector:
    """Mock emotion selector for testing."""
    
    def __init__(self):
        self._default_emotion = Emotion.NEUTRAL
        self._emotion_map: Dict[str, Emotion] = {}
    
    def set_default(self, emotion: Emotion) -> None:
        """Set default emotion."""
        self._default_emotion = emotion
    
    def set_emotion_for_text(self, text: str, emotion: Emotion) -> None:
        """Map specific text to emotion."""
        self._emotion_map[text.lower()] = emotion
    
    def select(self, context: EmotionContext) -> EmotionResult:
        text_lower = context.text.lower()
        if text_lower in self._emotion_map:
            return EmotionResult(
                emotion=self._emotion_map[text_lower],
                confidence=1.0,
                reason="Mock mapping",
            )
        return EmotionResult(
            emotion=self._default_emotion,
            confidence=0.5,
            reason="Mock default",
        )
    
    def select_from_text(self, text: str) -> EmotionResult:
        return self.select(EmotionContext(text=text))
    
    def select_for_response(
        self,
        text: str,
        intent: str,
        success: bool,
    ) -> Emotion:
        if not success:
            return Emotion.CONCERNED
        return self._default_emotion
