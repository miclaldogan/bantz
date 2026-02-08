"""Rule-based Pre-route for Obvious Cases.

Issue #245: Rule-based pre-route to bypass router for obvious cases.

This module provides:
- Pattern matching for obvious intents (smalltalk, greetings, time, etc.)
- Bypass router for simple cases (30% reduction target)
- Extensible rule system with confidence scoring

Goal: Reduce LLM router calls by 30% for obvious patterns.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


# =============================================================================
# Intent Categories
# =============================================================================

class IntentCategory(Enum):
    """High-level intent categories for routing."""
    
    # Simple - bypass router, use local
    GREETING = "greeting"
    FAREWELL = "farewell"
    THANKS = "thanks"
    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"
    SMALLTALK = "smalltalk"
    TIME_QUERY = "time_query"
    DATE_QUERY = "date_query"
    
    # Calendar - bypass router, use calendar handler
    CALENDAR_LIST = "calendar_list"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_DELETE = "calendar_delete"
    CALENDAR_UPDATE = "calendar_update"

    # Email - hint only (do not bypass router)
    EMAIL_SEND = "email_send"
    
    # System - bypass router, use system handler
    VOLUME_CONTROL = "volume_control"
    BRIGHTNESS = "brightness"
    APP_LAUNCH = "app_launch"
    SCREENSHOT = "screenshot"
    
    # Complex - needs router
    UNKNOWN = "unknown"
    COMPLEX = "complex"
    AMBIGUOUS = "ambiguous"
    
    @property
    def can_bypass_router(self) -> bool:
        """Check if this intent can bypass the router."""
        return self in {
            IntentCategory.GREETING,
            IntentCategory.FAREWELL,
            IntentCategory.THANKS,
            IntentCategory.AFFIRMATIVE,
            IntentCategory.NEGATIVE,
            IntentCategory.SMALLTALK,
            IntentCategory.TIME_QUERY,
            IntentCategory.DATE_QUERY,
            IntentCategory.CALENDAR_LIST,
            IntentCategory.CALENDAR_CREATE,
            IntentCategory.CALENDAR_DELETE,
            IntentCategory.CALENDAR_UPDATE,
            IntentCategory.VOLUME_CONTROL,
            IntentCategory.BRIGHTNESS,
            IntentCategory.APP_LAUNCH,
            IntentCategory.SCREENSHOT,
        }
    
    @property
    def handler_type(self) -> str:
        """Get the handler type for this intent."""
        handlers = {
            IntentCategory.GREETING: "local",
            IntentCategory.FAREWELL: "local",
            IntentCategory.THANKS: "local",
            IntentCategory.AFFIRMATIVE: "local",
            IntentCategory.NEGATIVE: "local",
            IntentCategory.SMALLTALK: "local",
            IntentCategory.TIME_QUERY: "system",
            IntentCategory.DATE_QUERY: "system",
            IntentCategory.CALENDAR_LIST: "calendar",
            IntentCategory.CALENDAR_CREATE: "calendar",
            IntentCategory.CALENDAR_DELETE: "calendar",
            IntentCategory.CALENDAR_UPDATE: "calendar",
            IntentCategory.EMAIL_SEND: "router",
            IntentCategory.VOLUME_CONTROL: "system",
            IntentCategory.BRIGHTNESS: "system",
            IntentCategory.APP_LAUNCH: "system",
            IntentCategory.SCREENSHOT: "system",
            IntentCategory.UNKNOWN: "router",
            IntentCategory.COMPLEX: "router",
            IntentCategory.AMBIGUOUS: "router",
        }
        return handlers.get(self, "router")


# =============================================================================
# Match Result
# =============================================================================

@dataclass(frozen=True)
class PreRouteMatch:
    """Result of a pre-route rule match.
    
    Attributes:
        matched: Whether the rule matched.
        intent: Detected intent category.
        confidence: Confidence score (0.0-1.0).
        rule_name: Name of the matching rule.
        extracted: Extracted entities/data.
    """
    matched: bool
    intent: IntentCategory = IntentCategory.UNKNOWN
    confidence: float = 0.0
    rule_name: str = ""
    extracted: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def no_match(cls) -> PreRouteMatch:
        """Create a no-match result."""
        return cls(matched=False)
    
    @classmethod
    def create(
        cls,
        intent: IntentCategory,
        confidence: float,
        rule_name: str,
        extracted: Optional[dict[str, Any]] = None,
    ) -> PreRouteMatch:
        """Create a match result."""
        return cls(
            matched=True,
            intent=intent,
            confidence=confidence,
            rule_name=rule_name,
            extracted=extracted or {},
        )
    
    def should_bypass(self, min_confidence: float = 0.8) -> bool:
        """Check if router should be bypassed."""
        return (
            self.matched
            and self.intent.can_bypass_router
            and self.confidence >= min_confidence
        )


# =============================================================================
# Rule Base Class
# =============================================================================

class PreRouteRule(ABC):
    """Base class for pre-route rules."""
    
    def __init__(self, name: str, intent: IntentCategory) -> None:
        """Initialize rule.
        
        Args:
            name: Rule name for debugging.
            intent: Intent category this rule detects.
        """
        self.name = name
        self.intent = intent
    
    @abstractmethod
    def match(self, text: str) -> PreRouteMatch:
        """Try to match the rule against text.
        
        Args:
            text: User input text.
        
        Returns:
            Match result.
        """
        pass


class PatternRule(PreRouteRule):
    """Rule based on regex patterns."""
    
    def __init__(
        self,
        name: str,
        intent: IntentCategory,
        patterns: list[str],
        confidence: float = 0.95,
        case_sensitive: bool = False,
    ) -> None:
        """Initialize pattern rule.
        
        Args:
            name: Rule name.
            intent: Intent category.
            patterns: List of regex patterns.
            confidence: Confidence when matched.
            case_sensitive: Whether patterns are case-sensitive.
        """
        super().__init__(name, intent)
        self.confidence = confidence
        
        flags = 0 if case_sensitive else re.IGNORECASE
        self.compiled = [re.compile(p, flags) for p in patterns]
    
    def match(self, text: str) -> PreRouteMatch:
        """Match against patterns."""
        text = text.strip()
        
        for pattern in self.compiled:
            m = pattern.search(text)
            if m:
                return PreRouteMatch.create(
                    intent=self.intent,
                    confidence=self.confidence,
                    rule_name=self.name,
                    extracted=m.groupdict() if m.groupdict() else {},
                )
        
        return PreRouteMatch.no_match()


class KeywordRule(PreRouteRule):
    """Rule based on keyword matching."""
    
    def __init__(
        self,
        name: str,
        intent: IntentCategory,
        keywords: list[str],
        confidence: float = 0.9,
        exact_match: bool = False,
    ) -> None:
        """Initialize keyword rule.
        
        Args:
            name: Rule name.
            intent: Intent category.
            keywords: List of keywords/phrases.
            confidence: Confidence when matched.
            exact_match: Whether to require exact match.
        """
        super().__init__(name, intent)
        self.keywords = [k.lower() for k in keywords]
        self.confidence = confidence
        self.exact_match = exact_match
    
    def match(self, text: str) -> PreRouteMatch:
        """Match against keywords."""
        text_lower = text.strip().lower()
        
        for keyword in self.keywords:
            if self.exact_match:
                if text_lower == keyword:
                    return PreRouteMatch.create(
                        intent=self.intent,
                        confidence=self.confidence,
                        rule_name=self.name,
                        extracted={"keyword": keyword},
                    )
            else:
                if keyword in text_lower:
                    return PreRouteMatch.create(
                        intent=self.intent,
                        confidence=self.confidence,
                        rule_name=self.name,
                        extracted={"keyword": keyword},
                    )
        
        return PreRouteMatch.no_match()


class CompositeRule(PreRouteRule):
    """Rule combining multiple sub-rules."""
    
    def __init__(
        self,
        name: str,
        intent: IntentCategory,
        rules: list[PreRouteRule],
        require_all: bool = False,
    ) -> None:
        """Initialize composite rule.
        
        Args:
            name: Rule name.
            intent: Intent category.
            rules: Sub-rules to combine.
            require_all: Whether all rules must match.
        """
        super().__init__(name, intent)
        self.rules = rules
        self.require_all = require_all
    
    def match(self, text: str) -> PreRouteMatch:
        """Match against sub-rules."""
        matches = [r.match(text) for r in self.rules]
        matched = [m for m in matches if m.matched]
        
        if self.require_all:
            if len(matched) == len(self.rules):
                avg_confidence = sum(m.confidence for m in matched) / len(matched)
                return PreRouteMatch.create(
                    intent=self.intent,
                    confidence=avg_confidence,
                    rule_name=self.name,
                )
        else:
            if matched:
                best = max(matched, key=lambda m: m.confidence)
                return PreRouteMatch.create(
                    intent=self.intent,
                    confidence=best.confidence,
                    rule_name=self.name,
                    extracted=best.extracted,
                )
        
        return PreRouteMatch.no_match()


# =============================================================================
# Default Rules - Turkish
# =============================================================================

def create_greeting_rule() -> PreRouteRule:
    """Create greeting detection rule."""
    return KeywordRule(
        name="greeting",
        intent=IntentCategory.GREETING,
        keywords=[
            "merhaba", "selam", "selamlar", "hey", "hi", "hello",
            "günaydın", "iyi günler", "iyi akşamlar", "iyi geceler",
            "hayırlı günler", "hayırlı sabahlar",
        ],
        confidence=0.95,
        exact_match=False,
    )


def create_farewell_rule() -> PreRouteRule:
    """Create farewell detection rule."""
    return KeywordRule(
        name="farewell",
        intent=IntentCategory.FAREWELL,
        keywords=[
            "güle güle", "hoşçakal", "görüşürüz", "bye", "goodbye",
            "kendine iyi bak", "iyi geceler", "hoşça kal",
        ],
        confidence=0.95,
        exact_match=False,
    )


def create_thanks_rule() -> PreRouteRule:
    """Create thanks detection rule."""
    return KeywordRule(
        name="thanks",
        intent=IntentCategory.THANKS,
        keywords=[
            "teşekkür", "teşekkürler", "sağol", "sağ ol", "eyvallah",
            "thanks", "thank you", "mersi",
        ],
        confidence=0.95,
        exact_match=False,
    )


def create_affirmative_rule() -> PreRouteRule:
    """Create affirmative detection rule."""
    return KeywordRule(
        name="affirmative",
        intent=IntentCategory.AFFIRMATIVE,
        keywords=[
            "evet", "tamam", "olur", "peki", "ok", "okay", "yes",
            "tabii", "tabi", "elbette", "olabilir", "onaylıyorum",
        ],
        confidence=0.9,
        exact_match=True,  # Exact match to avoid false positives
    )


def create_negative_rule() -> PreRouteRule:
    """Create negative detection rule."""
    return KeywordRule(
        name="negative",
        intent=IntentCategory.NEGATIVE,
        keywords=[
            "hayır", "yok", "istemiyorum", "no", "olmaz", "vazgeç",
            "iptal", "cancel", "geri", "dur",
        ],
        confidence=0.9,
        exact_match=True,
    )


def create_time_rule() -> PreRouteRule:
    """Create time query detection rule."""
    return PatternRule(
        name="time_query",
        intent=IntentCategory.TIME_QUERY,
        patterns=[
            r"saat\s+kaç\b",
            r"kaç\s+saat",
            r"şu\s*an(?:ki)?\s+saat",
            r"what\s+time",
            r"current\s+time",
        ],
        confidence=0.95,
    )


def create_date_rule() -> PreRouteRule:
    """Create date query detection rule."""
    return PatternRule(
        name="date_query",
        intent=IntentCategory.DATE_QUERY,
        patterns=[
            r"bugün\s+(?:hangi\s+)?gün",
            r"bugün\s+ne(?:ydi)?\b",
            r"hangi\s+gün",
            r"tarih\s+ne",
            r"what\s+(?:day|date)",
            r"today(?:'s)?\s+date",
        ],
        confidence=0.95,
    )


def create_calendar_list_rule() -> PreRouteRule:
    """Create calendar list detection rule."""
    return PatternRule(
        name="calendar_list",
        intent=IntentCategory.CALENDAR_LIST,
        patterns=[
            r"takvim(?:im)?(?:de)?\s*(?:ne\s+var|görüntüle|göster|listele)",
            r"(?:bugün|yarın|bu\s+hafta|bu\s+ay)(?:ki)?\s+(?:etkinlik|toplantı|program)",
            r"etkinlik(?:ler)?(?:im)?\s*(?:ne|neler|göster|listele)",
            r"toplantı(?:lar)?(?:ım)?\s*(?:ne|neler|göster|listele)",
            r"program(?:ım)?\s*(?:ne|nasıl|göster)",
            r"(?:show|list)\s+(?:my\s+)?(?:calendar|events|meetings)",
        ],
        confidence=0.9,
    )


def create_calendar_create_rule() -> PreRouteRule:
    """Create calendar create detection rule."""
    return PatternRule(
        name="calendar_create",
        intent=IntentCategory.CALENDAR_CREATE,
        patterns=[
            r"(?:yeni\s+)?(?:etkinlik|toplantı|randevu)\s*(?:ekle|oluştur|kur|ayarla)",
            r"(?:takvim(?:e|ime)?)\s*(?:ekle|kaydet)",
            r"(?:create|add|schedule)\s+(?:an?\s+)?(?:event|meeting|appointment)",
            r"(?:saat)\s+(?:\d{1,2}(?::\d{2})?)\s*(?:ya|de|'da|'de)\s+(?:toplantı|etkinlik)",
        ],
        confidence=0.85,  # Lower confidence - may need more context
    )


def create_calendar_delete_rule() -> PreRouteRule:
    """Create calendar delete detection rule."""
    return PatternRule(
        name="calendar_delete",
        intent=IntentCategory.CALENDAR_DELETE,
        patterns=[
            r"(?:etkinlik|toplantı|randevu)\s*(?:sil|iptal\s+et|kaldır)",
            r"(?:delete|remove|cancel)\s+(?:the\s+)?(?:event|meeting|appointment)",
            r"(?:iptal)\s+(?:et)",
        ],
        confidence=0.9,
    )


def create_email_send_rule() -> PreRouteRule:
    """Create email send detection rule.

    This rule is intentionally "hint-only" (IntentCategory.EMAIL_SEND is not
    bypassable) because email sending requires slot extraction, safety checks,
    and confirmation via the orchestrator.
    """
    return PatternRule(
        name="email_send",
        intent=IntentCategory.EMAIL_SEND,
        patterns=[
            r"\b(mail|e-?posta)\b\s*(gönder|at|yaz|yolla|ilet)\b",
            r"\b(mail|e-?posta)\b.*\b(gönder|at|yaz|yolla|ilet)\b",
            r"\b\S+@\S+\.\S+\b.*\b(mail|e-?posta)\b",
            r"\b(mail|e-?posta)\b.*\b\S+@\S+\.\S+\b",
        ],
        confidence=0.97,
    )


def create_volume_rule() -> PreRouteRule:
    """Create volume control detection rule."""
    return PatternRule(
        name="volume_control",
        intent=IntentCategory.VOLUME_CONTROL,
        patterns=[
            r"ses(?:i)?\s*(?:aç|kapat|kıs|artır|azalt|yükselt|alçalt)",
            r"(?:volume)\s*(?:up|down|mute|unmute)",
            r"(?:artır|azalt|kıs|yükselt)\s*ses(?:i)?",
        ],
        confidence=0.95,
    )


def create_screenshot_rule() -> PreRouteRule:
    """Create screenshot detection rule."""
    return PatternRule(
        name="screenshot",
        intent=IntentCategory.SCREENSHOT,
        patterns=[
            r"ekran\s*görüntüsü\s*(?:al|çek)",
            r"screenshot\s*(?:al|çek)?",
            r"(?:take\s+a?\s*)?screenshot",
        ],
        confidence=0.95,
    )


def create_smalltalk_rule() -> PreRouteRule:
    """Create smalltalk detection rule."""
    return PatternRule(
        name="smalltalk",
        intent=IntentCategory.SMALLTALK,
        patterns=[
            r"nasılsın",
            r"ne\s+(?:yapıyorsun|haber)",
            r"(?:iyisin|iyi\s+misin)",
            r"how\s+are\s+you",
            r"what(?:'s)?\s+up",
            r"naber",
        ],
        confidence=0.9,
    )


# =============================================================================
# Pre-Router
# =============================================================================

class PreRouter:
    """Rule-based pre-router for obvious intent detection.
    
    Bypasses the LLM router for patterns that can be reliably
    detected with rules. Target: 30% reduction in router calls.
    
    Usage:
        router = PreRouter()
        result = router.route("Merhaba!")
        
        if result.should_bypass():
            # Handle locally
            handler = get_handler(result.intent.handler_type)
            response = handler.handle(text, result)
        else:
            # Use LLM router
            response = llm_router.route(text)
    """
    
    def __init__(
        self,
        rules: Optional[list[PreRouteRule]] = None,
        min_confidence: float = 0.8,
    ) -> None:
        """Initialize pre-router.
        
        Args:
            rules: Custom rules (uses defaults if None).
            min_confidence: Minimum confidence for bypass.
        """
        self.rules = rules or self._default_rules()
        self.min_confidence = min_confidence
        
        # Stats tracking
        self._total_queries = 0
        self._bypassed_queries = 0
        self._rule_hits: dict[str, int] = {}
    
    def _default_rules(self) -> list[PreRouteRule]:
        """Get default rules."""
        return [
            create_greeting_rule(),
            create_farewell_rule(),
            create_thanks_rule(),
            create_affirmative_rule(),
            create_negative_rule(),
            create_time_rule(),
            create_date_rule(),
            create_calendar_list_rule(),
            create_calendar_create_rule(),
            create_calendar_delete_rule(),
            create_email_send_rule(),
            create_volume_rule(),
            create_screenshot_rule(),
            create_smalltalk_rule(),
        ]
    
    def add_rule(self, rule: PreRouteRule) -> None:
        """Add a custom rule."""
        self.rules.append(rule)
    
    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name."""
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                del self.rules[i]
                return True
        return False
    
    def route(self, text: str) -> PreRouteMatch:
        """Try to pre-route the text.
        
        Args:
            text: User input text.
        
        Returns:
            Match result with intent if detected.
        """
        self._total_queries += 1
        
        text = text.strip()
        if not text:
            return PreRouteMatch.no_match()
        
        # Try each rule
        best_match: Optional[PreRouteMatch] = None
        
        for rule in self.rules:
            result = rule.match(text)
            
            if result.matched:
                if best_match is None or result.confidence > best_match.confidence:
                    best_match = result
        
        if best_match and best_match.should_bypass(self.min_confidence):
            self._bypassed_queries += 1
            self._rule_hits[best_match.rule_name] = (
                self._rule_hits.get(best_match.rule_name, 0) + 1
            )
        
        return best_match or PreRouteMatch.no_match()
    
    def should_bypass(self, text: str) -> bool:
        """Quick check if text should bypass router.
        
        Args:
            text: User input text.
        
        Returns:
            True if router should be bypassed.
        """
        result = self.route(text)
        return result.should_bypass(self.min_confidence)
    
    def get_bypass_rate(self) -> float:
        """Get the bypass rate (0.0-1.0)."""
        if self._total_queries == 0:
            return 0.0
        return self._bypassed_queries / self._total_queries
    
    def get_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        return {
            "total_queries": self._total_queries,
            "bypassed_queries": self._bypassed_queries,
            "bypass_rate": self.get_bypass_rate(),
            "bypass_rate_percent": f"{self.get_bypass_rate():.1%}",
            "rule_hits": dict(self._rule_hits),
            "target_rate": 0.30,  # 30% target
            "on_target": self.get_bypass_rate() >= 0.30,
        }
    
    def reset_stats(self) -> None:
        """Reset statistics."""
        self._total_queries = 0
        self._bypassed_queries = 0
        self._rule_hits.clear()


# =============================================================================
# Response Generators for Bypassed Intents
# =============================================================================

class LocalResponseGenerator:
    """Generate responses for locally handled intents."""
    
    @staticmethod
    def greeting() -> str:
        """Generate greeting response."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "Günaydın! Size nasıl yardımcı olabilirim?"
        elif 12 <= hour < 18:
            return "İyi günler! Size nasıl yardımcı olabilirim?"
        elif 18 <= hour < 22:
            return "İyi akşamlar! Size nasıl yardımcı olabilirim?"
        else:
            return "Merhaba! Size nasıl yardımcı olabilirim?"
    
    @staticmethod
    def farewell() -> str:
        """Generate farewell response."""
        return "Görüşmek üzere! İyi günler dilerim."
    
    @staticmethod
    def thanks() -> str:
        """Generate thanks response."""
        return "Rica ederim! Başka bir konuda yardımcı olabilir miyim?"
    
    @staticmethod
    def affirmative() -> str:
        """Generate affirmative acknowledgment."""
        return "Tamam, anlaşıldı."
    
    @staticmethod
    def negative() -> str:
        """Generate negative acknowledgment."""
        return "Anladım, iptal ettim."
    
    @staticmethod
    def smalltalk() -> str:
        """Generate smalltalk response."""
        return "İyiyim, teşekkürler! Size nasıl yardımcı olabilirim?"
    
    @staticmethod
    def time_query() -> str:
        """Generate time response."""
        now = datetime.now()
        return f"Saat şu anda {now.strftime('%H:%M')}."
    
    @staticmethod
    def date_query() -> str:
        """Generate date response."""
        now = datetime.now()
        days_tr = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
        months_tr = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                     "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        
        day_name = days_tr[now.weekday()]
        month_name = months_tr[now.month - 1]
        
        return f"Bugün {day_name}, {now.day} {month_name} {now.year}."
    
    def generate(self, intent: IntentCategory) -> str:
        """Generate response for intent.
        
        Args:
            intent: Intent category.
        
        Returns:
            Generated response.
        """
        generators = {
            IntentCategory.GREETING: self.greeting,
            IntentCategory.FAREWELL: self.farewell,
            IntentCategory.THANKS: self.thanks,
            IntentCategory.AFFIRMATIVE: self.affirmative,
            IntentCategory.NEGATIVE: self.negative,
            IntentCategory.SMALLTALK: self.smalltalk,
            IntentCategory.TIME_QUERY: self.time_query,
            IntentCategory.DATE_QUERY: self.date_query,
        }
        
        generator = generators.get(intent)
        if generator:
            return generator()
        
        return "Anladım."


# =============================================================================
# Integration Helper
# =============================================================================

def integrate_prerouter(
    prerouter: PreRouter,
    llm_router_func: Callable[[str], Any],
    text: str,
) -> tuple[Any, bool]:
    """Integrate pre-router with LLM router.
    
    Args:
        prerouter: Pre-router instance.
        llm_router_func: Function to call LLM router.
        text: User input text.
    
    Returns:
        Tuple of (result, was_bypassed).
    """
    match = prerouter.route(text)
    
    if match.should_bypass():
        # Return pre-route result
        return match, True
    else:
        # Fall through to LLM router
        return llm_router_func(text), False
