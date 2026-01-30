"""
Jarvis Persona Module.

Provides Jarvis-style conversation responses with Turkish flavor:
- "Efendim" style formal address
- Natural Turkish expressions
- Context-aware responses

Example:
    persona = JarvisPersona()
    
    # Get searching response
    print(persona.get_response("searching"))
    # -> "Şimdi sizin için arıyorum efendim..."
    
    # Get contextual response
    print(persona.get_contextual("found_results", count=5))
    # -> "5 sonuç buldum efendim."
"""

import random
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


# =============================================================================
# Response Templates
# =============================================================================


JARVIS_RESPONSES: Dict[str, List[str]] = {
    # Searching / Processing
    "searching": [
        "Şimdi sizin için arıyorum efendim...",
        "Bakıyorum efendim, bir saniye...",
        "Arıyorum efendim...",
        "Hemen kontrol ediyorum efendim...",
        "Şimdi bulacağım efendim...",
    ],
    
    # News specific searching
    "searching_news": [
        "Haberlere bakıyorum efendim...",
        "Son haberleri getiriyorum efendim...",
        "Gündem haberlerini kontrol ediyorum efendim...",
        "Haber akışını tarıyorum efendim...",
    ],
    
    # Results found
    "results_found": [
        "Sonuçlar burada efendim.",
        "Buldum efendim.",
        "Sonuçlarınız hazır efendim.",
        "İşte sonuçlar efendim.",
    ],
    
    # News results
    "news_found": [
        "Haberler burada efendim.",
        "Gündem haberlerini getirdim efendim.",
        "Son haberler hazır efendim.",
        "İşte bugünün haberleri efendim.",
    ],
    
    # Page reading / extraction
    "reading_page": [
        "Sayfayı okuyorum efendim...",
        "İçeriği analiz ediyorum efendim...",
        "Sayfayı inceliyorum efendim...",
        "Okuyorum efendim, bir saniye...",
    ],
    
    # Summary ready
    "summary_ready": [
        "Buyurun efendim.",
        "İşte özet efendim.",
        "Özetledim efendim.",
        "Analiz hazır efendim.",
    ],
    
    # Answering question
    "answering": [
        "Bakayım efendim...",
        "Kontrol ediyorum efendim...",
        "Cevaplıyorum efendim...",
    ],
    
    # Answer ready
    "answer_ready": [
        "Buyurun efendim.",
        "Şöyle söyleyeyim efendim.",
        "Evet efendim.",
    ],
    
    # Content not found
    "no_content": [
        "Sayfadan içerik çıkaramadım efendim.",
        "Bu sayfada özetlenecek içerik bulamadım efendim.",
        "Sayfa içeriği okunamadı efendim.",
    ],
    
    # Panel moved
    "panel_moved": [
        "Panel taşındı efendim.",
        "Paneli taşıdım efendim.",
        "Tamam efendim.",
    ],
    
    # Panel shown
    "panel_shown": [
        "Sonuçlar panelde efendim.",
        "Panel açıldı efendim.",
        "Buyurun efendim.",
    ],
    
    # Panel hidden
    "panel_hidden": [
        "Panel kapatıldı efendim.",
        "Tamam efendim.",
    ],
    
    # Panel paginated
    "panel_page": [
        "Sayfa değişti efendim.",
        "Buyurun efendim.",
    ],
    
    # Panel item selected
    "panel_select": [
        "Açıyorum efendim.",
        "Hemen açıyorum efendim.",
    ],
    
    # Opening something
    "opening": [
        "Açıyorum efendim.",
        "Hemen açıyorum efendim.",
        "Şimdi açıyorum efendim.",
        "Buyurun efendim, açıyorum.",
    ],
    
    # Opening specific item
    "opening_item": [
        "Açıyorum efendim.",
        "Hemen o sayfayı açıyorum efendim.",
        "Şimdi yönlendiriyorum efendim.",
    ],
    
    # Error states
    "error": [
        "Maalesef bulamadım efendim.",
        "Üzgünüm efendim, bir sorun oluştu.",
        "Bu sefer olmadı efendim.",
        "Bulamadım efendim, tekrar dener misiniz?",
    ],
    
    # Not found
    "not_found": [
        "Maalesef sonuç bulunamadı efendim.",
        "Bu konuda bir şey bulamadım efendim.",
        "Sonuç yok efendim.",
        "Hiçbir şey çıkmadı efendim.",
    ],
    
    # Ready / Listening
    "ready": [
        "Dinliyorum efendim.",
        "Buyurun efendim.",
        "Efendim.",
        "Sizi dinliyorum.",
        "Evet efendim?",
    ],
    
    # Acknowledgment
    "acknowledged": [
        "Anladım efendim.",
        "Tamam efendim.",
        "Tabii efendim.",
        "Baş üstüne efendim.",
        "Hemen efendim.",
    ],
    
    # Greeting - Morning
    "greeting_morning": [
        "Günaydın efendim.",
        "Günaydın, bugün size nasıl yardımcı olabilirim?",
        "İyi sabahlar efendim, buyurun.",
    ],
    
    # Greeting - Afternoon
    "greeting_afternoon": [
        "İyi günler efendim.",
        "Merhaba efendim, buyurun.",
        "İyi günler, size nasıl yardımcı olabilirim?",
    ],
    
    # Greeting - Evening
    "greeting_evening": [
        "İyi akşamlar efendim.",
        "İyi akşamlar, buyurun efendim.",
        "Merhaba efendim.",
    ],
    
    # Farewell
    "farewell": [
        "İyi günler efendim.",
        "Görüşmek üzere efendim.",
        "Yine beklerim efendim.",
        "Hoşça kalın efendim.",
    ],
    
    # Thinking
    "thinking": [
        "Düşünüyorum efendim...",
        "Bir bakayım efendim...",
        "Hmm, şimdi düşünelim...",
        "Kontrol ediyorum efendim...",
    ],
    
    # Confirmation request
    "confirm": [
        "Emin misiniz efendim?",
        "Onaylıyor musunuz efendim?",
        "Devam edeyim mi efendim?",
        "Doğru mu efendim?",
    ],
    
    # Completion
    "done": [
        "Tamamlandı efendim.",
        "Oldu efendim.",
        "Bitti efendim.",
        "Hazır efendim.",
    ],
    
    # Waiting
    "waiting": [
        "Bekliyorum efendim.",
        "Dinlemeye devam ediyorum efendim.",
        "Hazırım efendim.",
    ],
    
    # Navigation
    "navigating": [
        "Sayfaya gidiyorum efendim.",
        "Yönlendiriyorum efendim.",
        "Hemen gidiyoruz efendim.",
    ],
    
    # Help
    "help": [
        "Size nasıl yardımcı olabilirim efendim?",
        "Buyurun efendim, ne yapabilirim?",
        "Emrinizdeyim efendim.",
    ],
    
    # Follow-up questions (after completing a task)
    "follow_up": [
        "Başka bir şey var mı efendim?",
        "Yardımcı olabileceğim başka bir konu var mı?",
        "Devam edelim mi efendim?",
        "Başka bir isteğiniz var mı efendim?",
    ],
    
    # Goodbye responses (when user says thanks/bye)
    "goodbye": [
        "Rica ederim efendim. Emrinize amadeyim.",
        "Ne demek efendim. İhtiyacınız olursa buradayım.",
        "Başka bir şey olursa söyleyin efendim.",
        "Rica ederim efendim.",
        "Her zaman efendim.",
    ],
    
    # Thanks acknowledgment
    "thanks_response": [
        "Rica ederim efendim.",
        "Ne demek efendim.",
        "Her zaman efendim.",
        "Önemli değil efendim.",
    ],
    
    # Engagement continue (staying in conversation)
    "staying_engaged": [
        "Dinliyorum efendim.",
        "Buyurun efendim.",
        "Evet efendim?",
        "Sizi dinliyorum.",
    ],
    
    # Timeout warning (before going idle)
    "timeout_warning": [
        "Hala buradayım efendim.",
        "Dinliyorum efendim.",
    ],
    
    # Going idle
    "going_idle": [
        "İhtiyacınız olursa 'Hey Bantz' deyin efendim.",
        "Beklemedeyim efendim.",
    ],
}


# Contextual templates (with placeholders)
JARVIS_CONTEXTUAL: Dict[str, List[str]] = {
    "found_count": [
        "{count} sonuç buldum efendim.",
        "{count} tane buldum efendim.",
        "Toplam {count} sonuç var efendim.",
    ],
    
    "news_count": [
        "{count} haber buldum efendim.",
        "{count} haber var efendim.",
        "Toplamda {count} haber buldum efendim.",
    ],
    
    "opening_number": [
        "{number}. sonucu açıyorum efendim.",
        "{number}. haberi açıyorum efendim.",
        "Şimdi {number}. öğeyi açıyorum efendim.",
    ],
    
    "time_greeting": [
        "Saat {time}, {greeting} efendim.",
    ],
    
    "topic_search": [
        "{topic} hakkında arıyorum efendim...",
        "{topic} ile ilgili bakıyorum efendim...",
    ],
    
    "reading_title": [
        "{title} başlıklı içeriği okuyorum efendim.",
    ],
    
    "page_info": [
        "Şu an {page} sayfasındayız efendim.",
    ],
}


# =============================================================================
# Persona Class
# =============================================================================


@dataclass
class ResponseContext:
    """Context for generating responses."""
    
    intent: str = ""
    count: int = 0
    item_number: int = 0
    topic: str = ""
    title: str = ""
    page: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class JarvisPersona:
    """
    Jarvis-style response generator.
    
    Provides natural, context-aware responses in Turkish
    with formal "efendim" style address.
    
    Example:
        persona = JarvisPersona()
        
        # Simple response
        response = persona.get_response("searching")
        
        # Contextual response
        response = persona.get_contextual("found_count", count=5)
        
        # Time-aware greeting
        greeting = persona.get_greeting()
    """
    
    def __init__(
        self,
        responses: Optional[Dict[str, List[str]]] = None,
        contextual: Optional[Dict[str, List[str]]] = None,
        randomize: bool = True,
    ):
        """
        Initialize persona.
        
        Args:
            responses: Custom response templates
            contextual: Custom contextual templates
            randomize: Whether to randomize responses
        """
        self.responses = responses or JARVIS_RESPONSES.copy()
        self.contextual = contextual or JARVIS_CONTEXTUAL.copy()
        self.randomize = randomize
        
        # Track last used responses to avoid repetition
        self._last_used: Dict[str, int] = {}
    
    def get_response(self, category: str, fallback: str = "") -> str:
        """
        Get a response from category.
        
        Args:
            category: Response category (e.g., "searching", "ready")
            fallback: Fallback if category not found
            
        Returns:
            Response string
        """
        options = self.responses.get(category, [])
        
        if not options:
            return fallback or f"[{category}]"
        
        if self.randomize:
            return self._pick_avoiding_last(category, options)
        return options[0]
    
    def get_contextual(
        self,
        template_name: str,
        fallback: str = "",
        **kwargs: Any,
    ) -> str:
        """
        Get a contextual response with placeholders filled.
        
        Args:
            template_name: Template name (e.g., "found_count")
            fallback: Fallback if template not found
            **kwargs: Values to fill placeholders
            
        Returns:
            Formatted response string
        """
        templates = self.contextual.get(template_name, [])
        
        if not templates:
            return fallback or f"[{template_name}]"
        
        # Pick template
        if self.randomize:
            template = self._pick_avoiding_last(template_name, templates)
        else:
            template = templates[0]
        
        # Format with kwargs
        try:
            return template.format(**kwargs)
        except KeyError:
            return template
    
    def _pick_avoiding_last(self, category: str, options: List[str]) -> str:
        """Pick a response avoiding the last used one."""
        if len(options) == 1:
            return options[0]
        
        last_idx = self._last_used.get(category, -1)
        
        # Get available indices
        available = [i for i in range(len(options)) if i != last_idx]
        
        if not available:
            available = list(range(len(options)))
        
        idx = random.choice(available)
        self._last_used[category] = idx
        
        return options[idx]
    
    def get_greeting(self) -> str:
        """Get time-appropriate greeting."""
        hour = datetime.now().hour
        
        if 5 <= hour < 12:
            return self.get_response("greeting_morning")
        elif 12 <= hour < 18:
            return self.get_response("greeting_afternoon")
        else:
            return self.get_response("greeting_evening")
    
    def get_farewell(self) -> str:
        """Get farewell message."""
        return self.get_response("farewell")
    
    def combine(self, *categories: str, separator: str = " ") -> str:
        """
        Combine multiple response categories.
        
        Args:
            *categories: Category names to combine
            separator: String between responses
            
        Returns:
            Combined response string
        """
        parts = []
        for cat in categories:
            response = self.get_response(cat)
            if response and not response.startswith("["):
                parts.append(response)
        
        return separator.join(parts)
    
    def for_news_search(self, topic: str = "") -> str:
        """Get response for starting news search."""
        if topic and topic != "gündem":
            return self.get_contextual("topic_search", topic=topic)
        return self.get_response("searching_news")
    
    def for_news_results(self, count: int) -> str:
        """Get response for news results."""
        if count == 0:
            return self.get_response("not_found")
        
        response = self.get_response("news_found")
        count_text = self.get_contextual("news_count", count=count)
        
        return f"{response} {count_text}"
    
    def for_opening_item(self, number: int) -> str:
        """Get response for opening numbered item."""
        return self.get_contextual(
            "opening_number",
            number=number,
            fallback=self.get_response("opening"),
        )
    
    def add_response(self, category: str, response: str) -> None:
        """Add a new response to category."""
        if category not in self.responses:
            self.responses[category] = []
        self.responses[category].append(response)
    
    def add_contextual(self, template_name: str, template: str) -> None:
        """Add a new contextual template."""
        if template_name not in self.contextual:
            self.contextual[template_name] = []
        self.contextual[template_name].append(template)
    
    # ─────────────────────────────────────────────────────────────
    # Conversation Flow Methods (Issue #20)
    # ─────────────────────────────────────────────────────────────
    
    def get_follow_up(self) -> str:
        """Get follow-up question after completing a task."""
        return self.get_response("follow_up")
    
    def get_goodbye(self) -> str:
        """Get goodbye response when user ends conversation."""
        return self.get_response("goodbye")
    
    def get_thanks_response(self) -> str:
        """Get response to user's thanks."""
        return self.get_response("thanks_response")
    
    def get_staying_engaged(self) -> str:
        """Get response when staying in conversation."""
        return self.get_response("staying_engaged")
    
    def get_going_idle(self) -> str:
        """Get response when going to idle mode."""
        return self.get_response("going_idle")
    
    def wrap_response(
        self,
        content: str,
        add_follow_up: bool = True,
        separator: str = " ",
    ) -> str:
        """Wrap response with Jarvis style follow-up.
        
        Args:
            content: Main response content
            add_follow_up: Whether to add follow-up question
            separator: Separator between content and follow-up
            
        Returns:
            Wrapped response
        """
        if add_follow_up:
            follow_up = self.get_follow_up()
            return f"{content}{separator}{follow_up}"
        return content
    
    def get_acknowledgment(self, action_type: str) -> str:
        """Get acknowledgment for action type.
        
        Args:
            action_type: Type of action (searching, opening, etc.)
            
        Returns:
            Acknowledgment response
        """
        # Map action types to response categories
        mapping = {
            "search": "searching",
            "searching": "searching",
            "open": "opening",
            "opening": "opening",
            "read": "reading_page",
            "reading": "reading_page",
            "navigate": "navigating",
            "navigating": "navigating",
            "think": "thinking",
            "thinking": "thinking",
            "process": "thinking",
            "processing": "thinking",
        }
        
        category = mapping.get(action_type.lower(), "acknowledged")
        return self.get_response(category)
    
    def get_result_response(self, result_type: str) -> str:
        """Get result presentation response.
        
        Args:
            result_type: Type of result (found, not_found, error)
            
        Returns:
            Result response
        """
        mapping = {
            "found": "results_found",
            "success": "done",
            "not_found": "not_found",
            "error": "error",
            "ready": "summary_ready",
        }
        
        category = mapping.get(result_type.lower(), "results_found")
        return self.get_response(category)


# =============================================================================
# Convenience Functions
# =============================================================================


# Global default persona
_default_persona: Optional[JarvisPersona] = None


def get_persona() -> JarvisPersona:
    """Get or create default persona."""
    global _default_persona
    if _default_persona is None:
        _default_persona = JarvisPersona()
    return _default_persona


def say(category: str, **kwargs: Any) -> str:
    """
    Quick access to persona responses.
    
    Example:
        say("searching")  # -> "Arıyorum efendim..."
        say("found_count", count=5)  # -> "5 sonuç buldum efendim."
    """
    persona = get_persona()
    
    # Try contextual first if kwargs provided
    if kwargs:
        response = persona.get_contextual(category, **kwargs)
        if not response.startswith("["):
            return response
    
    return persona.get_response(category)


def jarvis_greeting() -> str:
    """Get Jarvis greeting based on time."""
    return get_persona().get_greeting()


def jarvis_farewell() -> str:
    """Get Jarvis farewell."""
    return get_persona().get_farewell()


# =============================================================================
# Response Builder
# =============================================================================


class ResponseBuilder:
    """
    Builder for complex multi-part responses.
    
    Example:
        response = (ResponseBuilder()
            .add("Efendim,")
            .add_from("news_found")
            .add_contextual("news_count", count=5)
            .add("İlk 3 haberi okuyorum.")
            .build())
    """
    
    def __init__(self, persona: Optional[JarvisPersona] = None):
        """Initialize builder with persona."""
        self.persona = persona or get_persona()
        self._parts: List[str] = []
    
    def add(self, text: str) -> "ResponseBuilder":
        """Add literal text."""
        if text:
            self._parts.append(text)
        return self
    
    def add_from(self, category: str) -> "ResponseBuilder":
        """Add response from category."""
        response = self.persona.get_response(category)
        if response and not response.startswith("["):
            self._parts.append(response)
        return self
    
    def add_contextual(
        self,
        template_name: str,
        **kwargs: Any,
    ) -> "ResponseBuilder":
        """Add contextual response."""
        response = self.persona.get_contextual(template_name, **kwargs)
        if response and not response.startswith("["):
            self._parts.append(response)
        return self
    
    def add_if(
        self,
        condition: bool,
        text: str,
    ) -> "ResponseBuilder":
        """Add text if condition is true."""
        if condition:
            self._parts.append(text)
        return self
    
    def add_from_if(
        self,
        condition: bool,
        category: str,
    ) -> "ResponseBuilder":
        """Add category response if condition is true."""
        if condition:
            self.add_from(category)
        return self
    
    def build(self, separator: str = " ") -> str:
        """Build final response."""
        return separator.join(self._parts)
    
    def clear(self) -> "ResponseBuilder":
        """Clear all parts."""
        self._parts.clear()
        return self
