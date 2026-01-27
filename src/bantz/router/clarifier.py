"""Query Clarification System (Issue #21).

Belirsiz sorguları netleştirme sistemi.

Örnek:
    👤 "Şurada bir kaza olmuş neler var?"
    🤖 "Hangi bölgeden bahsediyorsunuz efendim? Örneğin İstanbul, Ankara?"
    👤 "Kadıköy"
    🤖 "Kadıköy kaza haberleri arıyorum efendim..."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum, auto


# ─────────────────────────────────────────────────────────────────
# Clarification Types
# ─────────────────────────────────────────────────────────────────

class ClarificationType(Enum):
    """Netleştirme soru tipleri."""
    LOCATION = auto()      # Nerede?
    TIME = auto()          # Ne zaman?
    SUBJECT = auto()       # Kim/Ne hakkında?
    SPECIFICITY = auto()   # Hangisi?
    CONFIRMATION = auto()  # Emin misiniz?


# ─────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────

@dataclass
class ClarificationQuestion:
    """Netleştirme sorusu."""
    type: ClarificationType
    question: str
    examples: List[str]
    slot_name: str
    context: str = ""


@dataclass
class QueryAnalysis:
    """Sorgu analiz sonucu."""
    original_query: str
    intent: str
    needs_clarification: bool
    missing_slots: List[str]
    clarification_question: Optional[ClarificationQuestion]
    confidence: float
    vague_indicators: List[str] = field(default_factory=list)


@dataclass
class ClarificationState:
    """Netleştirme durumu (conversation state)."""
    pending_question: Optional[ClarificationQuestion] = None
    original_query: str = ""
    original_intent: str = ""
    collected_slots: Dict[str, str] = field(default_factory=dict)
    clarification_count: int = 0
    max_clarifications: int = 2


# ─────────────────────────────────────────────────────────────────
# Clarification Templates
# ─────────────────────────────────────────────────────────────────

CLARIFICATION_TEMPLATES = {
    ClarificationType.LOCATION: {
        "question": "Hangi {context} bahsediyorsunuz efendim?",
        "question_alt": "Hangi bölge veya şehir efendim?",
        "examples": ["İstanbul", "Ankara", "İzmir"],
    },
    ClarificationType.TIME: {
        "question": "Ne zaman {context} efendim?",
        "question_alt": "Hangi tarih veya zaman diliminden bahsediyorsunuz efendim?",
        "examples": ["bugün", "dün", "bu hafta"],
    },
    ClarificationType.SUBJECT: {
        "question": "{context} hakkında daha fazla bilgi verir misiniz efendim?",
        "question_alt": "Konu hakkında biraz daha detay verebilir misiniz efendim?",
        "examples": [],
    },
    ClarificationType.SPECIFICITY: {
        "question": "Hangi {context} efendim?",
        "question_alt": "Tam olarak hangisinden bahsediyorsunuz efendim?",
        "examples": [],
    },
    ClarificationType.CONFIRMATION: {
        "question": "{context} emin misiniz efendim?",
        "question_alt": "Doğru anladım mı efendim?",
        "examples": ["evet", "hayır"],
    },
}


# ─────────────────────────────────────────────────────────────────
# Vague Indicator Patterns
# ─────────────────────────────────────────────────────────────────

VAGUE_INDICATORS = {
    "location": [
        r"\b[sş]urada\b",
        r"\borada\b", 
        r"\bburada\b",
        r"\bbir yerde\b",
        r"\byak[ıi]nlarda\b",
        r"\bcivarda\b",
        r"\betrafta\b",
        r"\bbir bölgede\b",
        r"\b[sş]ehirde\b",  # without specifying which city
    ],
    "time": [
        r"\bge[cç]enlerde\b",
        r"\bbir ara\b",
        r"\bbi zaman\b",
        r"\byak[ıi]nda\b",
        r"\bson zamanlarda\b",
        r"\bbu aralar\b",
        r"\bge[cç]en g[üu]n\b",
        r"\bdaha [öo]nce\b",
    ],
    "subject": [
        r"\bo [sş]ey\b",
        r"\b[sş]u [sş]ey\b",
        r"\bo konu\b",
        r"\b[sş]u konu\b",
        r"\bo olay\b",
        r"\bbiri\b",
        r"\bbir [sş]ey\b",
        r"\bbahsetti[gğ]im\b",
        r"\bbiliyorsun ya\b",
    ],
}


# Slot to clarification type mapping
SLOT_TO_TYPE = {
    "location": ClarificationType.LOCATION,
    "time": ClarificationType.TIME,
    "topic": ClarificationType.SUBJECT,
    "subject": ClarificationType.SUBJECT,
    "destination": ClarificationType.LOCATION,
    "source": ClarificationType.LOCATION,
    "person": ClarificationType.SUBJECT,
    "company": ClarificationType.SUBJECT,
}


# Context words for question generation
CONTEXT_WORDS = {
    "location": "bölgeden",
    "time": "olduğunu düşünüyorsunuz",
    "topic": "konudan",
    "subject": "kişi veya kurumdan",
    "destination": "yere gitmek istiyorsunuz",
    "source": "kaynaktan",
    "person": "kişiden",
    "company": "şirketten",
}


# Required slots for certain intents
INTENT_REQUIRED_SLOTS = {
    "news_search": ["topic"],
    "weather": ["location"],
    "directions": ["destination"],
    "event_search": ["location"],
    "stock_price": ["company"],
    "person_info": ["person"],
}


# ─────────────────────────────────────────────────────────────────
# Query Clarifier
# ─────────────────────────────────────────────────────────────────

class QueryClarifier:
    """Belirsiz sorguları netleştirme sistemi.
    
    Features:
    - Belirsiz ifadeleri tespit et (şurada, orada, geçenlerde)
    - Eksik slotları belirle
    - Jarvis tarzı netleştirme sorusu oluştur
    - Conversation state yönetimi
    - En fazla 2 netleştirme sorusu (UX için)
    
    Usage:
        clarifier = QueryClarifier()
        
        # Analyze query
        analysis = clarifier.analyze_query("şurada kaza olmuş", "news_search")
        
        if analysis.needs_clarification:
            # Ask question
            print(analysis.clarification_question.question)
            
            # User responds
            response = "Kadıköy"
            
            # Process response
            clarifier.process_response(response)
            
            # Get enhanced query
            enhanced = clarifier.get_enhanced_query()
            # "kaza olmuş Kadıköy"
    """
    
    def __init__(self, max_clarifications: int = 2):
        """Initialize clarifier.
        
        Args:
            max_clarifications: Max number of clarification questions (default 2)
        """
        self.max_clarifications = max_clarifications
        self._state = ClarificationState(max_clarifications=max_clarifications)
    
    @property
    def state(self) -> ClarificationState:
        """Get current state."""
        return self._state
    
    @property
    def is_pending(self) -> bool:
        """Check if there's a pending clarification."""
        return self._state.pending_question is not None
    
    @property
    def collected_slots(self) -> Dict[str, str]:
        """Get collected slot values."""
        return self._state.collected_slots.copy()
    
    def has_pending_question(self) -> bool:
        """Check if there's a pending clarification question."""
        return self._state.pending_question is not None
    
    def start_clarification(self, query: str, question: "ClarificationQuestion") -> None:
        """Start clarification flow.
        
        Args:
            query: Original user query
            question: First clarification question to ask
        """
        self._state.original_query = query
        self._state.pending_question = question
        self._state.clarification_count = 1
    
    # ─────────────────────────────────────────────────────────────
    # Main API
    # ─────────────────────────────────────────────────────────────
    
    def analyze_query(self, query: str, intent: str = "") -> QueryAnalysis:
        """Sorguyu analiz et, netleştirme gerekiyor mu?
        
        Args:
            query: User query
            intent: Detected intent (optional)
            
        Returns:
            QueryAnalysis with needs_clarification flag
        """
        query_lower = query.lower()
        
        # Find vague indicators
        vague_found = self._find_vague_indicators(query_lower)
        
        # Find missing required slots
        missing_slots = self._find_missing_slots(query_lower, intent, vague_found)
        
        # Check if we've exceeded max clarifications
        if self._state.clarification_count >= self.max_clarifications:
            return QueryAnalysis(
                original_query=query,
                intent=intent,
                needs_clarification=False,
                missing_slots=[],
                clarification_question=None,
                confidence=0.7,  # Lower confidence but proceed anyway
                vague_indicators=vague_found,
            )
        
        # No missing slots = no clarification needed
        if not missing_slots:
            return QueryAnalysis(
                original_query=query,
                intent=intent,
                needs_clarification=False,
                missing_slots=[],
                clarification_question=None,
                confidence=1.0,
                vague_indicators=vague_found,
            )
        
        # Generate clarification question for first missing slot
        slot = missing_slots[0]
        question = self._generate_question(slot, query)
        
        # Store state
        self._state.pending_question = question
        self._state.original_query = query
        self._state.original_intent = intent
        
        return QueryAnalysis(
            original_query=query,
            intent=intent,
            needs_clarification=True,
            missing_slots=missing_slots,
            clarification_question=question,
            confidence=0.5,
            vague_indicators=vague_found,
        )
    
    def process_response(self, response: str) -> Dict[str, str]:
        """Netleştirme yanıtını işle.
        
        Args:
            response: User's response to clarification question
            
        Returns:
            Updated collected slots
        """
        if not self._state.pending_question:
            return self._state.collected_slots.copy()
        
        slot_name = self._state.pending_question.slot_name
        self._state.collected_slots[slot_name] = response.strip()
        self._state.clarification_count += 1
        self._state.pending_question = None
        
        return self._state.collected_slots.copy()
    
    def get_enhanced_query(self) -> str:
        """Netleştirilmiş sorguyu döndür.
        
        Returns:
            Original query enhanced with collected slot values
        """
        query = self._state.original_query
        
        # Remove vague indicators and add specific values
        query = self._replace_vague_with_specific(query)
        
        return query.strip()
    
    def get_search_query(self) -> str:
        """Get optimized search query.
        
        Returns:
            Query optimized for search (combines topic + location etc.)
        """
        parts = []
        
        # Start with original query (cleaned)
        base = self._clean_vague_indicators(self._state.original_query)
        if base:
            parts.append(base)
        
        # Add collected slots
        for slot, value in self._state.collected_slots.items():
            if value and value not in base.lower():
                parts.append(value)
        
        return " ".join(parts).strip()
    
    def reset(self) -> None:
        """Durumu sıfırla."""
        self._state = ClarificationState(max_clarifications=self.max_clarifications)
    
    def needs_more_clarification(self) -> bool:
        """Check if more clarification is needed.
        
        Returns:
            True if we should ask another question
        """
        if self._state.clarification_count >= self.max_clarifications:
            return False
        
        # Re-analyze with current state
        enhanced = self.get_enhanced_query()
        analysis = self.analyze_query(enhanced, self._state.original_intent)
        
        return analysis.needs_clarification
    
    # ─────────────────────────────────────────────────────────────
    # Internal Methods
    # ─────────────────────────────────────────────────────────────
    
    def _find_vague_indicators(self, query: str) -> List[str]:
        """Find vague indicator words in query."""
        found = []
        
        for category, patterns in VAGUE_INDICATORS.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    found.append(category)
                    break  # One per category is enough
        
        return found
    
    def _find_missing_slots(
        self, 
        query: str, 
        intent: str,
        vague_found: List[str],
    ) -> List[str]:
        """Find missing required slots."""
        missing = []
        
        # Add slots for vague indicators
        for vague_type in vague_found:
            if vague_type not in self._state.collected_slots:
                missing.append(vague_type)
        
        # Check intent-specific required slots
        required = INTENT_REQUIRED_SLOTS.get(intent, [])
        for slot in required:
            if slot not in self._state.collected_slots:
                if not self._has_slot_value(query, slot):
                    if slot not in missing:
                        missing.append(slot)
        
        return missing
    
    def _has_slot_value(self, query: str, slot: str) -> bool:
        """Check if query already has a value for the slot."""
        query_lower = query.lower()
        
        if slot == "location":
            # Check for city/region names
            cities = [
                "istanbul", "ankara", "izmir", "bursa", "antalya",
                "adana", "konya", "gaziantep", "mersin", "diyarbakır",
                "kadıköy", "beşiktaş", "üsküdar", "fatih", "beyoğlu",
                "türkiye", "avrupa", "amerika", "asya",
            ]
            return any(city in query_lower for city in cities)
        
        if slot == "time":
            # Check for time expressions
            times = [
                "bugün", "dün", "yarın", "bu hafta", "geçen hafta",
                "bu ay", "geçen ay", "bu yıl", "geçen yıl",
                "sabah", "öğlen", "akşam", "gece",
                r"\d{1,2}[:/]\d{2}",  # Time pattern
                r"\d{1,2}\s+(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)",
            ]
            for t in times:
                if re.search(t, query_lower):
                    return True
            return False
        
        if slot == "company":
            # Check for company names
            companies = [
                "tesla", "apple", "google", "microsoft", "amazon",
                "facebook", "meta", "netflix", "twitter", "x",
                "turkcell", "garanti", "akbank", "işbank",
            ]
            return any(c in query_lower for c in companies)
        
        # Default: assume slot is missing
        return False
    
    def _generate_question(self, slot: str, context: str) -> ClarificationQuestion:
        """Generate clarification question for slot."""
        ctype = SLOT_TO_TYPE.get(slot, ClarificationType.SPECIFICITY)
        template = CLARIFICATION_TEMPLATES.get(ctype, CLARIFICATION_TEMPLATES[ClarificationType.SPECIFICITY])
        
        context_word = CONTEXT_WORDS.get(slot, "")
        
        # Format question
        if context_word:
            question = template["question"].format(context=context_word)
        else:
            question = template.get("question_alt", template["question"])
        
        # Add examples if available
        examples = template.get("examples", [])
        
        return ClarificationQuestion(
            type=ctype,
            question=question,
            examples=examples,
            slot_name=slot,
            context=context,
        )
    
    def _replace_vague_with_specific(self, query: str) -> str:
        """Replace vague indicators with specific values."""
        result = query
        
        for slot, value in self._state.collected_slots.items():
            if slot == "location":
                # Replace location-related vague words
                for pattern in VAGUE_INDICATORS.get("location", []):
                    result = re.sub(pattern, value, result, flags=re.IGNORECASE)
            elif slot == "time":
                for pattern in VAGUE_INDICATORS.get("time", []):
                    result = re.sub(pattern, value, result, flags=re.IGNORECASE)
            elif slot in ("topic", "subject"):
                for pattern in VAGUE_INDICATORS.get("subject", []):
                    result = re.sub(pattern, value, result, flags=re.IGNORECASE)
        
        return result
    
    def _clean_vague_indicators(self, query: str) -> str:
        """Remove vague indicators from query."""
        result = query
        
        for patterns in VAGUE_INDICATORS.values():
            for pattern in patterns:
                result = re.sub(pattern, "", result, flags=re.IGNORECASE)
        
        # Clean up extra spaces
        result = re.sub(r"\s+", " ", result).strip()
        
        return result


# ─────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────

def format_clarification_response(question: ClarificationQuestion) -> str:
    """Format clarification question for Jarvis response.
    
    Args:
        question: ClarificationQuestion to format
        
    Returns:
        Formatted string with examples
    """
    response = question.question
    
    if question.examples:
        examples_str = ", ".join(question.examples[:3])
        response += f" Örneğin {examples_str}?"
    
    return response


def is_clarification_response(text: str, pending_question: Optional[ClarificationQuestion]) -> bool:
    """Check if text is a response to a clarification question.
    
    Args:
        text: User input
        pending_question: Currently pending question
        
    Returns:
        True if this looks like a clarification response
    """
    if not pending_question:
        return False
    
    # Short responses are likely clarification answers
    if len(text.split()) <= 3:
        return True
    
    # Check if it matches expected examples
    text_lower = text.lower().strip()
    for example in pending_question.examples:
        if example.lower() in text_lower:
            return True
    
    return False


# ─────────────────────────────────────────────────────────────────
# Mock Clarifier for Testing
# ─────────────────────────────────────────────────────────────────

class MockQueryClarifier:
    """Mock clarifier for testing."""
    
    def __init__(self):
        self._analyses: List[QueryAnalysis] = []
        self._responses: List[str] = []
        self._is_pending = False
        self._collected_slots: Dict[str, str] = {}
        self._pending_slot: Optional[str] = None
        self._needs_clarification = False
        self._clarification_type = ClarificationType.LOCATION
    
    def add_mock_analysis(
        self,
        query: str,
        needs_clarification: bool,
        missing_slot: str = "",
        question: str = "",
    ) -> None:
        """Add a mock analysis result."""
        cq = None
        if needs_clarification and missing_slot:
            cq = ClarificationQuestion(
                type=ClarificationType.LOCATION,
                question=question or f"Hangi {missing_slot} efendim?",
                examples=["örnek1", "örnek2"],
                slot_name=missing_slot,
            )
        
        analysis = QueryAnalysis(
            original_query=query,
            intent="test",
            needs_clarification=needs_clarification,
            missing_slots=[missing_slot] if missing_slot else [],
            clarification_question=cq,
            confidence=0.5 if needs_clarification else 1.0,
        )
        self._analyses.append(analysis)
        self._is_pending = needs_clarification
    
    def set_pending_response(self, slot: str, search_query: str) -> None:
        """Set pending response for testing."""
        self._pending_slot = slot
        self._is_pending = True
    
    def get_pending_slot(self) -> Optional[str]:
        """Get pending slot name."""
        return self._pending_slot
    
    def set_needs_clarification(
        self,
        needs: bool,
        clarification_type: ClarificationType = ClarificationType.LOCATION,
    ) -> None:
        """Set whether clarification is needed."""
        self._needs_clarification = needs
        self._clarification_type = clarification_type
    
    def analyze_query(self, query: str, intent: str = "") -> QueryAnalysis:
        if self._analyses:
            return self._analyses.pop(0)
        
        cq = None
        if self._needs_clarification:
            cq = ClarificationQuestion(
                type=self._clarification_type,
                question="Hangi bölgeden bahsediyorsunuz efendim?",
                examples=["İstanbul", "Ankara"],
                slot_name="location",
            )
        
        return QueryAnalysis(
            original_query=query,
            intent=intent,
            needs_clarification=self._needs_clarification,
            missing_slots=["location"] if self._needs_clarification else [],
            clarification_question=cq,
            confidence=0.5 if self._needs_clarification else 1.0,
        )
    
    def process_response(self, response: str) -> Dict[str, str]:
        self._responses.append(response)
        self._is_pending = False
        self._collected_slots["location"] = response
        return self._collected_slots.copy()
    
    @property
    def is_pending(self) -> bool:
        return self._is_pending
    
    @property
    def collected_slots(self) -> Dict[str, str]:
        return self._collected_slots.copy()
    
    def reset(self) -> None:
        self._analyses.clear()
        self._responses.clear()
        self._is_pending = False
        self._collected_slots.clear()
        self._pending_slot = None
        self._needs_clarification = False
