"""
Smart Suggestions.

Suggest commands based on usage patterns:
- Next likely command
- Time-based suggestions
- Context-aware recommendations
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta
from collections import Counter
import logging

if TYPE_CHECKING:
    from bantz.analytics.tracker import UsageAnalytics

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Suggestion:
    """A command suggestion."""
    
    intent: str
    reason: str
    confidence: float  # 0.0 to 1.0
    display_text: str
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "reason": self.reason,
            "confidence": self.confidence,
            "display_text": self.display_text,
            "metadata": self.metadata,
        }


# =============================================================================
# Time-Based Patterns
# =============================================================================


# Default time-based suggestions
DEFAULT_TIME_PATTERNS: Dict[str, List[str]] = {
    # Morning (6-9)
    "morning_early": ["hava_durumu", "haberler", "takvim"],
    # Late morning (9-12)
    "morning_late": ["email_oku", "takvim", "toplantı"],
    # Afternoon (12-17)
    "afternoon": ["spotify", "youtube", "browser"],
    # Evening (17-21)
    "evening": ["müzik", "film", "yemek_tarifi"],
    # Night (21-24, 0-6)
    "night": ["alarm_kur", "hatırlatıcı", "not_al"],
}


def get_time_slot(hour: int) -> str:
    """Get time slot name for hour."""
    if 6 <= hour < 9:
        return "morning_early"
    elif 9 <= hour < 12:
        return "morning_late"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


# =============================================================================
# Smart Suggestions
# =============================================================================


class SmartSuggestions:
    """
    Suggest commands based on usage patterns.
    
    Analyzes:
    - Command sequences (what usually follows what)
    - Time-of-day patterns
    - Frequency of use
    
    Example:
        suggestions = SmartSuggestions(analytics)
        
        # After opening browser
        next_commands = suggestions.suggest_next("browser_aç")
        
        # Morning suggestions
        morning = suggestions.suggest_at_time(8)
    """
    
    def __init__(
        self,
        analytics: Optional["UsageAnalytics"] = None,
        time_patterns: Optional[Dict[str, List[str]]] = None,
    ):
        """
        Initialize smart suggestions.
        
        Args:
            analytics: UsageAnalytics instance for data
            time_patterns: Custom time-based patterns
        """
        self.analytics = analytics
        self.time_patterns = time_patterns or DEFAULT_TIME_PATTERNS
        self._sequence_cache: Dict[str, List[Tuple[str, int]]] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=30)
    
    def suggest_next(
        self,
        current_intent: str,
        limit: int = 5,
    ) -> List[Suggestion]:
        """
        Suggest likely next commands based on sequences.
        
        Args:
            current_intent: Current/last intent
            limit: Maximum suggestions
            
        Returns:
            List of suggestions
        """
        if not self.analytics:
            return []
        
        # Get sequence patterns
        self._refresh_cache_if_needed()
        
        followers = self._sequence_cache.get(current_intent, [])
        
        if not followers:
            return []
        
        # Calculate confidence based on count
        total = sum(count for _, count in followers)
        
        suggestions = []
        for intent, count in followers[:limit]:
            confidence = count / total if total > 0 else 0
            suggestions.append(Suggestion(
                intent=intent,
                reason=f"Genellikle '{current_intent}' sonrası kullanılıyor",
                confidence=confidence,
                display_text=self._intent_to_display(intent),
                metadata={"sequence_count": count},
            ))
        
        return suggestions
    
    def suggest_at_time(
        self,
        hour: Optional[int] = None,
        limit: int = 5,
    ) -> List[Suggestion]:
        """
        Suggest commands typical for time of day.
        
        Args:
            hour: Hour (0-23), uses current hour if None
            limit: Maximum suggestions
            
        Returns:
            List of suggestions
        """
        if hour is None:
            hour = datetime.now().hour
        
        time_slot = get_time_slot(hour)
        
        # Get default patterns for time slot
        default_intents = self.time_patterns.get(time_slot, [])
        
        # Combine with actual usage patterns if analytics available
        if self.analytics:
            hourly = self.analytics.get_hourly_distribution()
            stats = self.analytics.get_stats(days=30)
            
            # Get top intents weighted by time pattern
            weighted_intents = []
            for intent, count in stats.top_intents.items():
                # Higher weight if in default patterns
                weight = count * 2 if intent in default_intents else count
                weighted_intents.append((intent, weight))
            
            weighted_intents.sort(key=lambda x: x[1], reverse=True)
            
            suggestions = []
            seen = set()
            
            # Add from weighted list
            for intent, weight in weighted_intents:
                if intent not in seen and len(suggestions) < limit:
                    suggestions.append(Suggestion(
                        intent=intent,
                        reason=f"{time_slot} zamanı için öneriliyor",
                        confidence=0.7,
                        display_text=self._intent_to_display(intent),
                    ))
                    seen.add(intent)
            
            return suggestions
        
        # Fallback to defaults
        return [
            Suggestion(
                intent=intent,
                reason=f"{time_slot} zamanı için öneriliyor",
                confidence=0.5,
                display_text=self._intent_to_display(intent),
            )
            for intent in default_intents[:limit]
        ]
    
    def suggest_popular(self, limit: int = 5) -> List[Suggestion]:
        """
        Suggest most popular commands.
        
        Args:
            limit: Maximum suggestions
            
        Returns:
            List of suggestions
        """
        if not self.analytics:
            return []
        
        stats = self.analytics.get_stats(days=30)
        
        if not stats.top_intents:
            return []
        
        total = sum(stats.top_intents.values())
        
        return [
            Suggestion(
                intent=intent,
                reason=f"En çok kullanılan ({count} kez)",
                confidence=count / total if total > 0 else 0,
                display_text=self._intent_to_display(intent),
                metadata={"usage_count": count},
            )
            for intent, count in list(stats.top_intents.items())[:limit]
        ]
    
    def suggest_underused(
        self,
        all_intents: List[str],
        limit: int = 5,
    ) -> List[Suggestion]:
        """
        Suggest commands that exist but are rarely used.
        
        Args:
            all_intents: List of all available intents
            limit: Maximum suggestions
            
        Returns:
            List of suggestions
        """
        if not self.analytics:
            return []
        
        stats = self.analytics.get_stats(days=30)
        used_intents = set(stats.top_intents.keys())
        
        # Find unused or rarely used
        underused = []
        for intent in all_intents:
            if intent not in used_intents:
                underused.append((intent, 0))
            elif stats.top_intents.get(intent, 0) < 3:
                underused.append((intent, stats.top_intents[intent]))
        
        return [
            Suggestion(
                intent=intent,
                reason="Az kullanılmış, denemek ister misin?",
                confidence=0.3,
                display_text=self._intent_to_display(intent),
                metadata={"usage_count": count},
            )
            for intent, count in underused[:limit]
        ]
    
    def suggest_contextual(
        self,
        context: Dict[str, Any],
        limit: int = 5,
    ) -> List[Suggestion]:
        """
        Suggest based on current context.
        
        Args:
            context: Context dictionary (e.g., active app, clipboard)
            limit: Maximum suggestions
            
        Returns:
            List of suggestions
        """
        suggestions = []
        
        # Based on active application
        active_app = context.get("active_app", "").lower()
        
        if "chrome" in active_app or "firefox" in active_app:
            suggestions.append(Suggestion(
                intent="bookmark_ekle",
                reason="Tarayıcı açık - sayfa kaydedebilirsin",
                confidence=0.6,
                display_text="Bu sayfayı kaydet",
            ))
        
        if "spotify" in active_app:
            suggestions.extend([
                Suggestion(
                    intent="şarkı_beğen",
                    reason="Spotify açık - şarkı beğenebilirsin",
                    confidence=0.6,
                    display_text="Bu şarkıyı beğen",
                ),
                Suggestion(
                    intent="playlist_ekle",
                    reason="Spotify açık",
                    confidence=0.5,
                    display_text="Playlist'e ekle",
                ),
            ])
        
        # Based on clipboard content
        clipboard = context.get("clipboard", "")
        if "@" in clipboard and "." in clipboard:
            suggestions.append(Suggestion(
                intent="email_gönder",
                reason="Panoda email adresi var",
                confidence=0.7,
                display_text="Email gönder",
            ))
        
        if clipboard.startswith("http"):
            suggestions.append(Suggestion(
                intent="link_aç",
                reason="Panoda link var",
                confidence=0.8,
                display_text="Bu linki aç",
            ))
        
        return suggestions[:limit]
    
    def _refresh_cache_if_needed(self) -> None:
        """Refresh sequence cache if needed."""
        if self._cache_time and datetime.now() - self._cache_time < self._cache_ttl:
            return
        
        if not self.analytics:
            return
        
        # Get sequence patterns
        sequences = self.analytics.get_sequence_patterns(min_support=2)
        
        # Group by source intent
        self._sequence_cache.clear()
        for src, dst, count in sequences:
            if src not in self._sequence_cache:
                self._sequence_cache[src] = []
            self._sequence_cache[src].append((dst, count))
        
        # Sort each list by count
        for src in self._sequence_cache:
            self._sequence_cache[src].sort(key=lambda x: x[1], reverse=True)
        
        self._cache_time = datetime.now()
    
    def _intent_to_display(self, intent: str) -> str:
        """Convert intent to display text."""
        # Simple conversion: replace underscores with spaces, capitalize
        return intent.replace("_", " ").title()
    
    def get_all_suggestions(self, limit_per_category: int = 3) -> Dict[str, List[Suggestion]]:
        """
        Get all types of suggestions.
        
        Args:
            limit_per_category: Max suggestions per category
            
        Returns:
            Dictionary of suggestion lists by category
        """
        return {
            "time_based": self.suggest_at_time(limit=limit_per_category),
            "popular": self.suggest_popular(limit=limit_per_category),
        }


# =============================================================================
# Mock Implementation
# =============================================================================


class MockSmartSuggestions(SmartSuggestions):
    """Mock smart suggestions for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_suggestions: Dict[str, List[Suggestion]] = {}
    
    def set_mock_suggestions(
        self,
        category: str,
        suggestions: List[Suggestion],
    ) -> None:
        """Set mock suggestions for a category."""
        self._mock_suggestions[category] = suggestions
    
    def suggest_next(
        self,
        current_intent: str,
        limit: int = 5,
    ) -> List[Suggestion]:
        """Return mock if available."""
        key = f"next:{current_intent}"
        if key in self._mock_suggestions:
            return self._mock_suggestions[key][:limit]
        return super().suggest_next(current_intent, limit)
    
    def suggest_at_time(
        self,
        hour: Optional[int] = None,
        limit: int = 5,
    ) -> List[Suggestion]:
        """Return mock if available."""
        if "time" in self._mock_suggestions:
            return self._mock_suggestions["time"][:limit]
        return super().suggest_at_time(hour, limit)
    
    def suggest_popular(self, limit: int = 5) -> List[Suggestion]:
        """Return mock if available."""
        if "popular" in self._mock_suggestions:
            return self._mock_suggestions["popular"][:limit]
        return super().suggest_popular(limit)
