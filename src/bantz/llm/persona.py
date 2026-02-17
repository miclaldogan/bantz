"""
Bantz Persona Module — The Broadcaster.

Provides theatrical, radio-host-style conversation responses:
- "Friend" / "old friend" address style
- Polished, mid-Atlantic charm
- Context-aware responses with dramatic flair

Example:
    persona = JarvisPersona()
    
    # Get searching response
    print(persona.get_response("searching"))
    # -> "Let us peel back the curtain, shall we..."
    
    # Get contextual response
    print(persona.get_contextual("found_results", count=5))
    # -> "Found 5 results for you, friend."
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
        "Let us peel back the curtain, shall we...",
        "Shuffling the deck for you, friend...",
        "One moment — the broadcast is tuning in...",
        "Searching the archives, old friend...",
        "Allow me to consult the records...",
    ],
    
    # News specific searching
    "searching_news": [
        "Scanning the headlines — stand by for the bulletin...",
        "The news desk is buzzing — one moment...",
        "Tuning into the latest broadcast...",
        "Let me pull today's wire reports...",
    ],
    
    # Results found
    "results_found": [
        "The ink is dry — here you are.",
        "Consider the strings pulled.",
        "The curtain rises — your results, friend.",
        "And there we have it.",
    ],
    
    # News results
    "news_found": [
        "Fresh off the press, friend.",
        "The bulletin is in — here are your headlines.",
        "Today's broadcast, served warm.",
        "The wire has spoken — here's what's new.",
    ],
    
    # Page reading / extraction
    "reading_page": [
        "Reading between the lines, one moment...",
        "Analyzing the manuscript...",
        "Turning the pages — bear with me...",
        "Examining the document, friend...",
    ],
    
    # Summary ready
    "summary_ready": [
        "The synopsis is ready.",
        "Here's the executive summary, friend.",
        "All distilled and ready for you.",
        "The abridged version, as requested.",
    ],
    
    # Answering question
    "answering": [
        "Let me consult the records...",
        "Checking the files...",
        "Processing your inquiry...",
    ],
    
    # Answer ready
    "answer_ready": [
        "Here you are, friend.",
        "Allow me to present the findings.",
        "Indeed.",
    ],
    
    # Content not found
    "no_content": [
        "The page appears to be... blank. A curious plot twist.",
        "No extractable content on this one, I'm afraid.",
        "The manuscript yields nothing — how mysterious.",
    ],
    
    # Panel moved
    "panel_moved": [
        "Panel relocated, friend.",
        "Consider it moved.",
        "Done and done.",
    ],
    
    # Panel shown
    "panel_shown": [
        "Results are on stage, friend.",
        "The panel is live.",
        "Here you are.",
    ],
    
    # Panel hidden
    "panel_hidden": [
        "Panel dismissed.",
        "Off the air.",
    ],
    
    # Panel paginated
    "panel_page": [
        "Turning the page...",
        "Next act, coming up.",
    ],
    
    # Panel item selected
    "panel_select": [
        "Opening now, friend.",
        "Right away.",
    ],
    
    # Opening something
    "opening": [
        "Opening that up for you, friend.",
        "Right away — the curtain rises.",
        "Consider it done.",
        "On it.",
    ],
    
    # Opening specific item
    "opening_item": [
        "Opening now.",
        "Pulling up that page for you...",
        "Redirecting the broadcast...",
    ],
    
    # Error states
    "error": [
        "A delightful little glitch in the script!",
        "The deck is missing a card, I'm afraid.",
        "A plot twist — something went awry.",
        "It appears we have a bit of static on the line.",
    ],
    
    # Not found
    "not_found": [
        "The search yields nothing — a dead signal.",
        "Nothing in the archives on that one, friend.",
        "No results. The airwaves are silent.",
        "Came up empty, I'm afraid.",
    ],
    
    # Ready / Listening
    "ready": [
        "The stage is set. What shall we perform?",
        "The broadcast is live.",
        "At your service, friend.",
        "I'm listening.",
        "Go ahead, I'm all ears.",
    ],
    
    # Acknowledgment
    "acknowledged": [
        "Understood, friend.",
        "Consider it noted.",
        "Absolutely.",
        "Right away.",
        "On it.",
    ],
    
    # Greeting - Morning
    "greeting_morning": [
        "Good morning, friend. The signal is strong and the coffee is bitter.",
        "Rise and shine — the broadcast is live!",
        "Morning! The stage is set for a productive day.",
    ],
    
    # Greeting - Afternoon
    "greeting_afternoon": [
        "Good afternoon, friend. How may I assist?",
        "The afternoon broadcast is on — what's on the agenda?",
        "Hello there! The show goes on.",
    ],
    
    # Greeting - Evening
    "greeting_evening": [
        "Good evening, friend. The night shift is on.",
        "Evening! The late broadcast begins.",
        "Hello, friend.",
    ],
    
    # Farewell
    "farewell": [
        "Until the next broadcast, friend.",
        "The show pauses — but never ends. Farewell.",
        "Signing off for now. You know where to find me.",
        "Until next time.",
    ],
    
    # Thinking
    "thinking": [
        "Let me think on that...",
        "Processing, one moment...",
        "Hmm, let me consider...",
        "Consulting the inner workings...",
    ],
    
    # Confirmation request
    "confirm": [
        "Are you certain, friend?",
        "Shall I proceed?",
        "Do you confirm this course of action?",
        "Is that correct?",
    ],
    
    # Completion
    "done": [
        "The ink is dry.",
        "Consider it done, friend.",
        "Mission accomplished.",
        "All wrapped up.",
    ],
    
    # Waiting
    "waiting": [
        "Standing by, friend.",
        "The broadcast awaits your command.",
        "Ready when you are.",
    ],
    
    # Navigation
    "navigating": [
        "Charting the course now...",
        "Redirecting the signal...",
        "En route.",
    ],
    
    # Help
    "help": [
        "How may I be of service, friend?",
        "What can I do for you?",
        "At your command.",
    ],
    
    # Follow-up questions (after completing a task)
    "follow_up": [
        "Anything else, friend?",
        "What's next on the program?",
        "Shall we continue?",
        "Another request, perhaps?",
    ],
    
    # Goodbye responses (when user says thanks/bye)
    "goodbye": [
        "My pleasure, friend. The broadcast never truly ends.",
        "Of course. I'll be here when you need me.",
        "Don't hesitate to call again.",
        "My pleasure.",
        "Always at your service.",
    ],
    
    # Thanks acknowledgment
    "thanks_response": [
        "My pleasure, friend.",
        "Think nothing of it.",
        "Always glad to help.",
        "No trouble at all.",
    ],
    
    # Engagement continue (staying in conversation)
    "staying_engaged": [
        "I'm listening, friend.",
        "Go ahead.",
        "Yes?",
        "The mic is still hot.",
    ],
    
    # Timeout warning (before going idle)
    "timeout_warning": [
        "Still here, friend.",
        "The broadcast continues...",
    ],
    
    # Going idle
    "going_idle": [
        "Say 'Hey Bantz' when you need me, friend.",
        "Standing by on the frequencies.",
    ],
}


# Contextual templates (with placeholders)
JARVIS_CONTEXTUAL: Dict[str, List[str]] = {
    "found_count": [
        "Found {count} results for you, friend.",
        "{count} items pulled from the archives.",
        "A total of {count} results, friend.",
    ],
    
    "news_count": [
        "{count} headlines in the bulletin, friend.",
        "{count} stories on the wire.",
        "Pulled {count} articles for you.",
    ],
    
    "opening_number": [
        "Opening item number {number}, friend.",
        "Pulling up number {number} for you.",
        "Now presenting item {number}.",
    ],
    
    "time_greeting": [
        "It's {time} — {greeting}, friend.",
    ],
    
    "topic_search": [
        "Searching the archives for {topic}...",
        "Looking into {topic} for you...",
    ],
    
    "reading_title": [
        "Reading the piece titled '{title}', one moment...",
    ],
    
    "page_info": [
        "Currently on page {page}, friend.",
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
    Broadcaster-style response generator.
    
    Provides natural, context-aware responses in English
    with theatrical "friend" style address.
    
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
        if topic and topic not in ("gündem", "trending", "latest"):
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
        say("searching")  # -> "Let us peel back the curtain..."
        say("found_count", count=5)  # -> "Found 5 results for you, friend."
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
            .add("Friend,")
            .add_from("news_found")
            .add_contextual("news_count", count=5)
            .add("Let me read the top 3 for you.")
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
