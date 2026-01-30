# SPDX-License-Identifier: MIT
"""
Clarification Manager.

Handles ambiguous user inputs by:
1. Detecting when clarification is needed
2. Generating appropriate clarifying questions
3. Managing pending clarification state
4. Processing user responses to clarifications

Turkish-aware question generation for natural interaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bantz.nlu.types import (
    IntentResult,
    ClarificationRequest,
    ClarificationOption,
    NLUContext,
    ConfidenceLevel,
    IntentCategory,
)


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class ClarificationConfig:
    """Configuration for clarification behavior.
    
    Attributes:
        confidence_threshold: Below this, request clarification
        ambiguity_threshold: If top 2 intents are within this, ambiguous
        max_options: Maximum options to present
        auto_clarify_missing_slots: Ask for missing required slots
        remember_clarifications: Learn from resolved clarifications
    """
    
    confidence_threshold: float = 0.6
    ambiguity_threshold: float = 0.15
    max_options: int = 3
    auto_clarify_missing_slots: bool = True
    remember_clarifications: bool = True


# ============================================================================
# Question Templates
# ============================================================================


# Templates for different clarification scenarios
QUESTION_TEMPLATES = {
    # Missing slot
    "missing_slot": {
        "url": "Hangi siteyi açmamı istersin?",
        "site": "Hangi siteyi açmamı istersin?",
        "app": "Hangi uygulamayı açmamı istersin?",
        "query": "Ne aramak istiyorsun?",
        "path": "Hangi dosya veya klasör?",
        "command": "Hangi komutu çalıştırayım?",
        "time": "Ne zaman hatırlatayım?",
        "message": "Ne hatırlatayım?",
        "position": "Nereye taşıyayım? (sağ üst, sol alt, orta)",
        "element": "Hangi elemente tıklayayım?",
        "text": "Ne yazayım?",
        "default": "Neyi kastediyorsun?",
    },
    
    # Ambiguous intent
    "ambiguous_intent": {
        "browser_vs_app": "Tarayıcıda mı açayım yoksa uygulamayı mı?",
        "open_vs_search": "Siteyi mi açayım yoksa arama mı yapayım?",
        "file_vs_terminal": "Dosya olarak mı okuyayım yoksa komut olarak mı çalıştırayım?",
        "default": "Tam olarak ne yapmamı istersin?",
    },
    
    # Low confidence
    "low_confidence": {
        "very_short": "Biraz daha açıklar mısın?",
        "no_verb": "Ne yapmamı istiyorsun?",
        "default": "Tam olarak ne yapmamı istersin?",
    },
    
    # Confirmation
    "confirmation": {
        "dangerous": "{action} işlemini gerçekleştireyim mi?",
        "multiple_steps": "Bu işlem birkaç adım sürecek. Devam edeyim mi?",
        "default": "Bunu mu demek istedin: {description}?",
    },
}

# Intent descriptions for options
INTENT_DESCRIPTIONS = {
    # Browser
    "browser_open": "Web sitesi aç",
    "browser_search": "Sitede arama yap",
    "browser_click": "Elemente tıkla",
    "browser_type": "Metin yaz",
    "browser_scroll_down": "Aşağı kaydır",
    "browser_scroll_up": "Yukarı kaydır",
    "browser_back": "Geri git",
    
    # App
    "app_open": "Uygulama aç",
    "app_close": "Uygulama kapat",
    "app_list": "Uygulamaları listele",
    
    # File
    "file_read": "Dosya oku",
    "file_edit": "Dosya düzenle",
    "file_create": "Dosya oluştur",
    "file_delete": "Dosya sil",
    "file_list": "Dosyaları listele",
    
    # Terminal
    "terminal_run": "Komut çalıştır",
    
    # Reminder
    "reminder_add": "Hatırlatma ekle",
    "checkin_add": "Check-in ekle",
    
    # Conversation
    "conversation": "Sohbet",
    "greeting": "Selamlama",
    "help": "Yardım",
    
    # Queue
    "queue_pause": "Kuyruğu duraklat",
    "queue_resume": "Kuyruğa devam et",
    "queue_abort": "Kuyruğu iptal et",
    
    # UI
    "overlay_move": "Overlay'i taşı",
    "overlay_hide": "Overlay'i gizle",
    
    # Unknown
    "unknown": "Anlaşılamadı",
}


# ============================================================================
# Clarification Manager
# ============================================================================


class ClarificationManager:
    """Manages clarification dialogs for ambiguous inputs.
    
    Handles the full lifecycle:
    1. Detecting when clarification is needed
    2. Generating appropriate questions
    3. Storing pending clarification state
    4. Processing user responses
    
    Example:
        manager = ClarificationManager()
        
        result = IntentResult(intent="browser_open", confidence=0.4)
        if manager.needs_clarification(result):
            clarification = manager.generate_clarification(result, "aç")
            # Ask user the clarification.question
        
        # User responds: "youtube"
        resolved = manager.resolve_from_response("youtube", context)
    """
    
    def __init__(self, config: Optional[ClarificationConfig] = None):
        """Initialize the manager.
        
        Args:
            config: Clarification configuration
        """
        self.config = config or ClarificationConfig()
        self._pending: Dict[str, ClarificationRequest] = {}  # session_id -> request
        self._history: List[Tuple[ClarificationRequest, str]] = []  # (request, resolution)
    
    # ========================================================================
    # Detection
    # ========================================================================
    
    def needs_clarification(self, result: IntentResult) -> bool:
        """Check if a result needs clarification.
        
        Args:
            result: Intent classification result
        
        Returns:
            True if clarification is needed
        """
        # Already has clarification request
        if result.clarification is not None:
            return True
        
        # Low confidence
        if result.confidence < self.config.confidence_threshold:
            return True
        
        # Unknown intent
        if result.intent == "unknown":
            return True
        
        # Check ambiguity with alternatives
        if result.alternatives:
            top_alt = result.alternatives[0][1] if result.alternatives else 0
            if abs(result.confidence - top_alt) < self.config.ambiguity_threshold:
                return True
        
        return False
    
    def get_clarification_reason(self, result: IntentResult) -> str:
        """Get the reason why clarification is needed.
        
        Args:
            result: Intent classification result
        
        Returns:
            Reason string
        """
        if result.intent == "unknown":
            return "unknown_intent"
        
        if result.confidence < 0.3:
            return "very_low_confidence"
        
        if result.confidence < self.config.confidence_threshold:
            return "low_confidence"
        
        if result.alternatives:
            top_alt = result.alternatives[0][1] if result.alternatives else 0
            if abs(result.confidence - top_alt) < self.config.ambiguity_threshold:
                return "ambiguous_alternatives"
        
        if result.clarification and result.clarification.slot_needed:
            return "missing_slot"
        
        return "general"
    
    # ========================================================================
    # Question Generation
    # ========================================================================
    
    def generate_clarification(
        self,
        result: IntentResult,
        original_text: str,
        context: Optional[NLUContext] = None,
    ) -> ClarificationRequest:
        """Generate a clarification request.
        
        Args:
            result: Intent classification result
            original_text: Original user input
            context: NLU context for smarter questions
        
        Returns:
            ClarificationRequest with question and options
        """
        reason = self.get_clarification_reason(result)
        
        # If result already has a clarification, enhance it
        if result.clarification:
            clarification = result.clarification
            clarification.reason = reason
            return self._enhance_clarification(clarification, result, context)
        
        # Generate based on reason
        if reason == "missing_slot":
            return self._generate_slot_clarification(result, original_text)
        elif reason == "ambiguous_alternatives":
            return self._generate_alternatives_clarification(result, original_text)
        elif reason in ("low_confidence", "very_low_confidence"):
            return self._generate_confidence_clarification(result, original_text)
        elif reason == "unknown_intent":
            return self._generate_unknown_clarification(result, original_text)
        else:
            return self._generate_general_clarification(result, original_text)
    
    def _generate_slot_clarification(
        self,
        result: IntentResult,
        original_text: str,
    ) -> ClarificationRequest:
        """Generate clarification for missing slot."""
        # Determine which slot is needed
        slot_needed = self._find_missing_slot(result)
        
        # Get question template
        templates = QUESTION_TEMPLATES["missing_slot"]
        question = templates.get(slot_needed, templates["default"])
        
        return ClarificationRequest(
            question=question,
            original_text=original_text,
            reason="missing_slot",
            slot_needed=slot_needed,
        )
    
    def _generate_alternatives_clarification(
        self,
        result: IntentResult,
        original_text: str,
    ) -> ClarificationRequest:
        """Generate clarification for ambiguous alternatives."""
        options = []
        
        # Add main intent
        options.append(ClarificationOption(
            intent=result.intent,
            description=self._intent_description(result.intent, result.slots),
            slots=result.slots,
            probability=result.confidence,
        ))
        
        # Add alternatives
        for alt_intent, alt_conf in result.alternatives[:self.config.max_options - 1]:
            options.append(ClarificationOption(
                intent=alt_intent,
                description=self._intent_description(alt_intent, {}),
                slots={},
                probability=alt_conf,
            ))
        
        # Determine question
        question = self._get_ambiguity_question(result.intent, result.alternatives)
        
        return ClarificationRequest(
            question=question,
            options=options,
            original_text=original_text,
            reason="ambiguous_alternatives",
        )
    
    def _generate_confidence_clarification(
        self,
        result: IntentResult,
        original_text: str,
    ) -> ClarificationRequest:
        """Generate clarification for low confidence."""
        # Check if text is very short
        if len(original_text.split()) <= 2:
            question = QUESTION_TEMPLATES["low_confidence"]["very_short"]
        # Check if text has no verb
        elif not self._has_verb(original_text):
            question = QUESTION_TEMPLATES["low_confidence"]["no_verb"]
        else:
            question = QUESTION_TEMPLATES["low_confidence"]["default"]
        
        # If we have a guess, offer it as option
        options = []
        if result.intent != "unknown" and result.confidence > 0.3:
            options.append(ClarificationOption(
                intent=result.intent,
                description=self._intent_description(result.intent, result.slots),
                slots=result.slots,
                probability=result.confidence,
            ))
        
        return ClarificationRequest(
            question=question,
            options=options,
            original_text=original_text,
            reason="low_confidence",
        )
    
    def _generate_unknown_clarification(
        self,
        result: IntentResult,
        original_text: str,
    ) -> ClarificationRequest:
        """Generate clarification for unknown intent."""
        return ClarificationRequest(
            question="Ne yapmamı istediğini anlayamadım. Biraz daha açıklar mısın?",
            options=[],
            original_text=original_text,
            reason="unknown_intent",
        )
    
    def _generate_general_clarification(
        self,
        result: IntentResult,
        original_text: str,
    ) -> ClarificationRequest:
        """Generate general clarification."""
        question = QUESTION_TEMPLATES["ambiguous_intent"]["default"]
        
        return ClarificationRequest(
            question=question,
            options=[],
            original_text=original_text,
            reason="general",
        )
    
    def _enhance_clarification(
        self,
        clarification: ClarificationRequest,
        result: IntentResult,
        context: Optional[NLUContext],
    ) -> ClarificationRequest:
        """Enhance an existing clarification with context."""
        # Add context-aware suggestions
        if context:
            if context.focused_app and not clarification.options:
                # Suggest action on current app
                clarification.options.append(ClarificationOption(
                    intent="app_focus",
                    description=f"Mevcut uygulama: {context.focused_app}",
                    slots={"app": context.focused_app},
                    probability=0.3,
                ))
        
        return clarification
    
    # ========================================================================
    # Resolution
    # ========================================================================
    
    def set_pending(
        self,
        session_id: str,
        clarification: ClarificationRequest,
    ):
        """Set a pending clarification for a session.
        
        Args:
            session_id: Session identifier
            clarification: The clarification request
        """
        self._pending[session_id] = clarification
    
    def get_pending(self, session_id: str) -> Optional[ClarificationRequest]:
        """Get pending clarification for a session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Pending clarification or None
        """
        return self._pending.get(session_id)
    
    def clear_pending(self, session_id: str):
        """Clear pending clarification for a session.
        
        Args:
            session_id: Session identifier
        """
        self._pending.pop(session_id, None)
    
    def resolve_from_response(
        self,
        response: str,
        session_id: str,
    ) -> Optional[IntentResult]:
        """Resolve a clarification from user response.
        
        Args:
            response: User's response to clarification
            session_id: Session identifier
        
        Returns:
            Resolved IntentResult or None if can't resolve
        """
        clarification = self.get_pending(session_id)
        if not clarification:
            return None
        
        response_lower = response.lower().strip()
        
        # Check for option selection by number
        if response_lower.isdigit():
            idx = int(response_lower) - 1
            if 0 <= idx < len(clarification.options):
                option = clarification.options[idx]
                self.clear_pending(session_id)
                return self._resolve_option(option, clarification)
        
        # Check for option selection by name
        for option in clarification.options:
            if response_lower in option.description.lower():
                self.clear_pending(session_id)
                return self._resolve_option(option, clarification)
        
        # Check if this fills a missing slot
        if clarification.slot_needed:
            self.clear_pending(session_id)
            return self._resolve_slot(
                clarification.slot_needed,
                response,
                clarification,
            )
        
        # Check for cancellation
        if response_lower in ("iptal", "vazgeç", "boşver", "hayır"):
            self.clear_pending(session_id)
            return IntentResult(
                intent="cancel",
                slots={},
                confidence=1.0,
                original_text=response,
                source="clarification",
            )
        
        # Can't resolve - might need to re-parse with more context
        return None
    
    def _resolve_option(
        self,
        option: ClarificationOption,
        clarification: ClarificationRequest,
    ) -> IntentResult:
        """Resolve by selected option."""
        # Track for learning
        if self.config.remember_clarifications:
            self._history.append((clarification, option.intent))
        
        return IntentResult(
            intent=option.intent,
            slots=option.slots,
            confidence=1.0,  # User explicitly chose
            original_text=clarification.original_text,
            source="clarification",
        )
    
    def _resolve_slot(
        self,
        slot_name: str,
        value: str,
        clarification: ClarificationRequest,
    ) -> IntentResult:
        """Resolve by filling missing slot."""
        # Get original intent (if available from options)
        intent = "unknown"
        base_slots = {}
        
        if clarification.options:
            option = clarification.options[0]
            intent = option.intent
            base_slots = dict(option.slots)
        
        # Add the new slot value
        base_slots[slot_name] = value
        
        # Track for learning
        if self.config.remember_clarifications:
            self._history.append((clarification, f"{slot_name}={value}"))
        
        return IntentResult(
            intent=intent,
            slots=base_slots,
            confidence=0.9,  # User provided value
            original_text=clarification.original_text,
            source="clarification",
        )
    
    # ========================================================================
    # Helpers
    # ========================================================================
    
    def _find_missing_slot(self, result: IntentResult) -> str:
        """Find which slot is missing for an intent."""
        from bantz.nlu.classifier import REQUIRED_SLOTS
        
        required = REQUIRED_SLOTS.get(result.intent, [])
        
        for slot in required:
            if slot not in result.slots:
                return slot
        
        # Default to most common
        return "url" if "browser" in result.intent else "app"
    
    def _intent_description(
        self,
        intent: str,
        slots: Dict[str, Any],
    ) -> str:
        """Get human-readable description of intent with slots."""
        base = INTENT_DESCRIPTIONS.get(intent, intent)
        
        # Add slot info
        if slots:
            slot_parts = []
            for key, value in slots.items():
                if isinstance(value, str) and len(value) < 30:
                    slot_parts.append(f"{value}")
            
            if slot_parts:
                return f"{base}: {', '.join(slot_parts)}"
        
        return base
    
    def _get_ambiguity_question(
        self,
        main_intent: str,
        alternatives: List[Tuple[str, float]],
    ) -> str:
        """Get appropriate question for ambiguous intents."""
        templates = QUESTION_TEMPLATES["ambiguous_intent"]
        
        # Check specific ambiguity patterns
        alt_intents = [a[0] for a in alternatives[:2]]
        
        if "browser_open" in [main_intent] + alt_intents:
            if "app_open" in [main_intent] + alt_intents:
                return templates["browser_vs_app"]
        
        if "browser_search" in [main_intent] + alt_intents:
            if "browser_open" in [main_intent] + alt_intents:
                return templates["open_vs_search"]
        
        return templates["default"]
    
    def _has_verb(self, text: str) -> bool:
        """Check if text contains a Turkish verb."""
        turkish_verbs = [
            r"\b(aç|kapat|başlat|git|gel|yap|bul|ara|oku|yaz|sil|taşı|kopyala)\b",
            r"\b(göster|gizle|duraklat|devam|iptal|atla|kaydet|indir|yükle)\b",
            r"\b(hatırlat|çalıştır|çal|durdur|bekle|geç|dön|tak|çıkar)\b",
        ]
        
        for pattern in turkish_verbs:
            if re.search(pattern, text.lower()):
                return True
        
        return False
    
    def get_history(self, limit: int = 100) -> List[Tuple[ClarificationRequest, str]]:
        """Get clarification history.
        
        Args:
            limit: Maximum entries to return
        
        Returns:
            List of (request, resolution) tuples
        """
        return self._history[-limit:]
    
    def clear_history(self):
        """Clear clarification history."""
        self._history.clear()


# ============================================================================
# Helper Functions
# ============================================================================


def quick_clarify(result: IntentResult, text: str) -> Optional[ClarificationRequest]:
    """Quick check and generate clarification if needed.
    
    Args:
        result: Intent classification result
        text: Original text
    
    Returns:
        ClarificationRequest if needed, None otherwise
    """
    manager = ClarificationManager()
    
    if manager.needs_clarification(result):
        return manager.generate_clarification(result, text)
    
    return None


# Import re at module level
import re
