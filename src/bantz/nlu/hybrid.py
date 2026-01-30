# SPDX-License-Identifier: MIT
"""
Hybrid NLU System.

Combines multiple approaches for optimal speed and accuracy:

1. **Regex Fast Path**: Pattern matching for common, unambiguous commands
   - Latency: <1ms
   - Accuracy: 100% for matched patterns
   
2. **LLM Fallback**: Natural language understanding for everything else
   - Latency: 100-500ms
   - Accuracy: 85-95% for natural variations

3. **Slot Extraction**: Turkish-aware entity extraction
   - Time, URL, app names, queries

4. **Clarification**: Ask user when uncertain

The system prioritizes speed while maintaining accuracy.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from bantz.nlu.types import (
    IntentResult,
    NLUContext,
    NLUStats,
    ConfidenceLevel,
)
from bantz.nlu.classifier import LLMIntentClassifier, ClassifierConfig
from bantz.nlu.slots import SlotExtractor
from bantz.nlu.clarification import ClarificationManager, ClarificationConfig


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class HybridConfig:
    """Configuration for hybrid NLU system.
    
    Attributes:
        regex_confidence: Confidence for regex matches
        regex_min_confidence: Minimum confidence for regex path
        llm_enabled: Whether to use LLM fallback
        llm_timeout_ms: Maximum time for LLM call
        slot_extraction_enabled: Whether to extract slots
        clarification_enabled: Whether to ask for clarification
        caching_enabled: Whether to cache LLM results
        cache_size: Maximum cache entries
        stats_enabled: Whether to track statistics
    """
    
    regex_confidence: float = 0.99
    regex_min_confidence: float = 0.85
    llm_enabled: bool = True
    llm_timeout_ms: float = 500.0
    slot_extraction_enabled: bool = True
    clarification_enabled: bool = True
    caching_enabled: bool = True
    cache_size: int = 1000
    stats_enabled: bool = True
    
    # LLM config
    llm_model: str = "qwen2.5:3b-instruct"
    llm_temperature: float = 0.1


# ============================================================================
# Regex Patterns
# ============================================================================

# Type alias for pattern handlers
PatternHandler = Callable[[re.Match, str], IntentResult]


class RegexPatterns:
    """Collection of regex patterns for fast path matching.
    
    Patterns are ordered by specificity and frequency.
    Each pattern returns an IntentResult when matched.
    """
    
    def __init__(self):
        """Initialize patterns."""
        self.patterns: List[Tuple[re.Pattern, PatternHandler]] = []
        self._build_patterns()
    
    def _build_patterns(self):
        """Build all regex patterns."""
        
        # ============================================================
        # Browser patterns
        # ============================================================
        
        # Site with Turkish suffixes: "youtube aç", "youtube'a git"
        self.patterns.append((
            re.compile(
                r"^(youtube|twitter|instagram|github|google|reddit|spotify|twitch|linkedin|facebook|wikipedia|vikipedi|netflix|amazon|trendyol)"
                r"[''`]?(?:a|e|ya|ye|ı|i|u|ü)?(?:\s+|\s*$)"
                r"(?:aç|git|gir|başlat|göster)?$",
                re.IGNORECASE,
            ),
            self._handle_site_open,
        ))
        
        # Natural variations: "youtube'a gidebilir misin"
        self.patterns.append((
            re.compile(
                r"(youtube|twitter|instagram|github|google|reddit|spotify|twitch)"
                r"[''`]?(?:a|e|ya|ye)\s+"
                r"(?:gidebilir\s+misin|açabilir\s+misin|git(?:sene)?|aç(?:sana)?)",
                re.IGNORECASE,
            ),
            self._handle_site_open_natural,
        ))
        
        # URL pattern: "https://..." or "xxx.com"
        self.patterns.append((
            re.compile(
                r"(https?://[^\s]+|[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)\s*(?:aç|git|gir)?",
                re.IGNORECASE,
            ),
            self._handle_url_open,
        ))
        
        # Search patterns: "youtube'da X ara", "google X"
        self.patterns.append((
            re.compile(
                r"(youtube|google|wikipedia|vikipedi|amazon|twitter)[''`]?(?:da|de|ta|te)\s+(.+?)\s*(?:ara|bul|arat)",
                re.IGNORECASE,
            ),
            self._handle_site_search,
        ))
        
        # Simple search: "X ara", "X'i ara"
        self.patterns.append((
            re.compile(
                r"(.+?)[''`]?(?:y[ıi]|[ıiuü])?\s*ara\s*$",
                re.IGNORECASE,
            ),
            self._handle_simple_search,
        ))
        
        # ============================================================
        # App patterns
        # ============================================================
        
        # App open: "spotify aç", "vscode'u aç"
        self.patterns.append((
            re.compile(
                r"^(spotify|discord|vscode|code|terminal|firefox|chrome|slack|telegram|steam|gimp|blender)"
                r"[''`]?(?:u|ü|ı|i|yu|yü)?\s*"
                r"(?:aç|başlat|çalıştır|getir)$",
                re.IGNORECASE,
            ),
            self._handle_app_open,
        ))
        
        # App close: "spotify kapat"
        self.patterns.append((
            re.compile(
                r"^(spotify|discord|vscode|code|terminal|firefox|chrome|slack|telegram)"
                r"[''`]?(?:y[ıi]|[ıi])?\s*"
                r"(?:kapat|durdur|öldür|kill)$",
                re.IGNORECASE,
            ),
            self._handle_app_close,
        ))
        
        # Generic app: "X uygulamasını aç"
        self.patterns.append((
            re.compile(
                r"(.+?)\s+(?:uygulamas[ıi]n[ıi]|app[''`]?[ıi])\s*(aç|kapat)",
                re.IGNORECASE,
            ),
            self._handle_generic_app,
        ))
        
        # ============================================================
        # Reminder patterns
        # ============================================================
        
        # Time-based: "5 dakika sonra X hatırlat"
        self.patterns.append((
            re.compile(
                r"(\d+|bir|iki|üç|beş|on)\s*(dakika|dk|saat|sa)\s*sonra\s+(.+?)\s*(?:hatırlat|yokla|uyar)",
                re.IGNORECASE,
            ),
            self._handle_reminder_time_first,
        ))
        
        # Message-based: "X hatırlat 5 dakika sonra"
        self.patterns.append((
            re.compile(
                r"(.+?)\s*hatırlat\s+(\d+|bir|iki|üç|beş|on)\s*(dakika|dk|saat|sa)\s*sonra",
                re.IGNORECASE,
            ),
            self._handle_reminder_message_first,
        ))
        
        # ============================================================
        # Queue control
        # ============================================================
        
        self.patterns.append((
            re.compile(r"^(duraklat|bekle|dur\s+bir)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("queue_pause", {}, t),
        ))
        
        self.patterns.append((
            re.compile(r"^(devam|devam\s+et|sürdür)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("queue_resume", {}, t),
        ))
        
        self.patterns.append((
            re.compile(r"^(iptal|iptal\s+et|kuyruğu\s+iptal)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("queue_abort", {}, t),
        ))
        
        self.patterns.append((
            re.compile(r"^(atla|sıradaki|sonrakine\s+geç)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("queue_skip", {}, t),
        ))
        
        # ============================================================
        # UI/Overlay
        # ============================================================
        
        # Position: "sağ üste geç", "ortaya git"
        self.patterns.append((
            re.compile(
                r"(sağ\s*üst|sol\s*üst|sağ\s*alt|sol\s*alt|orta(?:ya)?|merkez)\s*(?:e|a)?\s*(?:geç|git|taşın|dön)",
                re.IGNORECASE,
            ),
            self._handle_overlay_move,
        ))
        
        # Hide: "gizlen", "kapat kendini"
        self.patterns.append((
            re.compile(r"^(gizlen|kendini\s+kapat|görünmez\s+ol)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("overlay_hide", {}, t),
        ))
        
        # ============================================================
        # Confirmation
        # ============================================================
        
        self.patterns.append((
            re.compile(r"^(evet|e|onayla|tamam|olur)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("confirm_yes", {}, t),
        ))
        
        self.patterns.append((
            re.compile(r"^(hayır|h|yok|vazgeç|iptal)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("confirm_no", {}, t),
        ))
        
        # ============================================================
        # Greetings
        # ============================================================
        
        self.patterns.append((
            re.compile(r"^(selam|merhaba|hey|hi|hello|günaydın|iyi\s+akşamlar)(?:\s+.*)?$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("greeting", {}, t),
        ))
        
        self.patterns.append((
            re.compile(r"^(teşekkürler|teşekkür\s+ederim|sağol|eyvallah|thanks)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("thanks", {}, t),
        ))
        
        # ============================================================
        # Help
        # ============================================================
        
        self.patterns.append((
            re.compile(r"^(yardım|help|ne\s+yapabilirsin|komutlar)$", re.IGNORECASE),
            lambda m, t: IntentResult.from_regex("help", {}, t),
        ))
    
    # ================================================================
    # Pattern Handlers
    # ================================================================
    
    def _handle_site_open(self, match: re.Match, text: str) -> IntentResult:
        """Handle site open pattern."""
        site = match.group(1).lower()
        return IntentResult.from_regex(
            "browser_open",
            {"site": site},
            text,
        )
    
    def _handle_site_open_natural(self, match: re.Match, text: str) -> IntentResult:
        """Handle natural site open pattern."""
        site = match.group(1).lower()
        return IntentResult.from_regex(
            "browser_open",
            {"site": site},
            text,
            confidence=0.95,  # Slightly lower for natural
        )
    
    def _handle_url_open(self, match: re.Match, text: str) -> IntentResult:
        """Handle URL open pattern."""
        url = match.group(1)
        if not url.startswith("http"):
            url = f"https://{url}"
        return IntentResult.from_regex(
            "browser_open",
            {"url": url},
            text,
        )
    
    def _handle_site_search(self, match: re.Match, text: str) -> IntentResult:
        """Handle site search pattern."""
        site = match.group(1).lower()
        query = match.group(2).strip()
        return IntentResult.from_regex(
            "browser_search",
            {"site": site, "query": query},
            text,
        )
    
    def _handle_simple_search(self, match: re.Match, text: str) -> IntentResult:
        """Handle simple search pattern."""
        query = match.group(1).strip()
        # Remove common prefixes
        query = re.sub(r"^(?:bana\s+|google\s+)", "", query)
        return IntentResult.from_regex(
            "browser_search",
            {"query": query},
            text,
            confidence=0.85,
        )
    
    def _handle_app_open(self, match: re.Match, text: str) -> IntentResult:
        """Handle app open pattern."""
        app = match.group(1).lower()
        # Normalize app names
        app_map = {
            "code": "vscode",
            "terminal": "gnome-terminal",
        }
        return IntentResult.from_regex(
            "app_open",
            {"app": app_map.get(app, app)},
            text,
        )
    
    def _handle_app_close(self, match: re.Match, text: str) -> IntentResult:
        """Handle app close pattern."""
        app = match.group(1).lower()
        return IntentResult.from_regex(
            "app_close",
            {"app": app},
            text,
        )
    
    def _handle_generic_app(self, match: re.Match, text: str) -> IntentResult:
        """Handle generic app pattern."""
        app = match.group(1).strip().lower()
        action = match.group(2).lower()
        intent = "app_open" if "aç" in action else "app_close"
        return IntentResult.from_regex(
            intent,
            {"app": app},
            text,
            confidence=0.85,
        )
    
    def _handle_reminder_time_first(self, match: re.Match, text: str) -> IntentResult:
        """Handle reminder with time first."""
        num_str = match.group(1)
        unit = match.group(2).lower()
        message = match.group(3).strip()
        
        time_str = f"{num_str} {unit} sonra"
        
        return IntentResult.from_regex(
            "reminder_add",
            {"time": time_str, "message": message},
            text,
        )
    
    def _handle_reminder_message_first(self, match: re.Match, text: str) -> IntentResult:
        """Handle reminder with message first."""
        message = match.group(1).strip()
        num_str = match.group(2)
        unit = match.group(3).lower()
        
        time_str = f"{num_str} {unit} sonra"
        
        return IntentResult.from_regex(
            "reminder_add",
            {"time": time_str, "message": message},
            text,
        )
    
    def _handle_overlay_move(self, match: re.Match, text: str) -> IntentResult:
        """Handle overlay move pattern."""
        position = match.group(1).lower().strip()
        
        # Normalize position
        position_map = {
            "sağ üst": "top-right",
            "sağüst": "top-right",
            "sol üst": "top-left",
            "solüst": "top-left",
            "sağ alt": "bottom-right",
            "sağalt": "bottom-right",
            "sol alt": "bottom-left",
            "solalt": "bottom-left",
            "orta": "center",
            "ortaya": "center",
            "merkez": "center",
        }
        
        normalized = position_map.get(position, position)
        
        return IntentResult.from_regex(
            "overlay_move",
            {"position": normalized},
            text,
        )
    
    # ================================================================
    # Match Method
    # ================================================================
    
    def match(self, text: str) -> Optional[IntentResult]:
        """Try to match text against all patterns.
        
        Args:
            text: Input text
        
        Returns:
            IntentResult if matched, None otherwise
        """
        text_stripped = text.strip()
        
        for pattern, handler in self.patterns:
            match = pattern.match(text_stripped)
            if match:
                return handler(match, text_stripped)
            
            # Also try search for some patterns
            if pattern.pattern.startswith("("):  # Non-anchored patterns
                match = pattern.search(text_stripped)
                if match:
                    return handler(match, text_stripped)
        
        return None


# ============================================================================
# Hybrid NLU
# ============================================================================


class HybridNLU:
    """Hybrid Natural Language Understanding system.
    
    Combines regex patterns with LLM for optimal accuracy and speed.
    
    Usage:
        nlu = HybridNLU()
        result = nlu.parse("youtube aç")
        # IntentResult(intent='browser_open', slots={'site': 'youtube'})
        
        result = nlu.parse("youtube'a gidebilir misin lütfen")
        # IntentResult(intent='browser_open', slots={'site': 'youtube'})
    """
    
    def __init__(
        self,
        config: Optional[HybridConfig] = None,
        llm_classifier: Optional[LLMIntentClassifier] = None,
    ):
        """Initialize hybrid NLU.
        
        Args:
            config: Hybrid configuration
            llm_classifier: Pre-configured LLM classifier (optional)
        """
        self.config = config or HybridConfig()
        
        # Components
        self._patterns = RegexPatterns()
        self._slot_extractor = SlotExtractor() if self.config.slot_extraction_enabled else None
        self._clarification = ClarificationManager() if self.config.clarification_enabled else None
        self._llm: Optional[LLMIntentClassifier] = llm_classifier
        
        # Stats
        self._stats = NLUStats() if self.config.stats_enabled else None
        
        # Context
        self._context: Dict[str, NLUContext] = {}  # session_id -> context
    
    @property
    def llm(self) -> LLMIntentClassifier:
        """Lazy-load LLM classifier."""
        if self._llm is None:
            llm_config = ClassifierConfig(
                model=self.config.llm_model,
                temperature=self.config.llm_temperature,
                cache_enabled=self.config.caching_enabled,
            )
            self._llm = LLMIntentClassifier(config=llm_config)
        return self._llm
    
    # ========================================================================
    # Main Parse Method
    # ========================================================================
    
    def parse(
        self,
        text: str,
        context: Optional[NLUContext] = None,
        session_id: Optional[str] = None,
    ) -> IntentResult:
        """Parse user input into intent.
        
        This is the main entry point. It:
        1. Tries regex patterns first (fast path)
        2. Falls back to LLM if no match (slow but accurate)
        3. Extracts slots from text
        4. Generates clarification if needed
        
        Args:
            text: User input text
            context: Optional NLU context
            session_id: Session ID for context tracking
        
        Returns:
            IntentResult with intent, slots, and confidence
        """
        start_time = time.time()
        
        # Normalize text
        text = text.strip()
        if not text:
            return IntentResult.unknown("", source="hybrid")
        
        # Get or create context
        if session_id and not context:
            context = self._get_context(session_id)
        
        # Check for pending clarification
        if session_id and self._clarification:
            pending = self._clarification.get_pending(session_id)
            if pending:
                resolved = self._clarification.resolve_from_response(text, session_id)
                if resolved:
                    if self._stats:
                        self._stats.record_clarification_resolved()
                    return resolved
        
        # Try regex first (fast path)
        result = self._try_regex(text)
        
        # Fall back to LLM if no regex match
        if result is None and self.config.llm_enabled:
            result = self._try_llm(text, context)
        
        # If still no result, return unknown
        if result is None:
            result = IntentResult.unknown(text, source="hybrid")
        
        # Enhance with slot extraction
        if self.config.slot_extraction_enabled and self._slot_extractor:
            result = self._enhance_with_slots(result, text)
        
        # Check for clarification
        if self.config.clarification_enabled and self._clarification:
            if self._clarification.needs_clarification(result):
                clarification = self._clarification.generate_clarification(result, text, context)
                result.clarification = clarification
                
                if session_id:
                    self._clarification.set_pending(session_id, clarification)
        
        # Update timing
        result.processing_time_ms = (time.time() - start_time) * 1000
        
        # Update context
        if session_id and context:
            context.add_intent(result.intent, text)
            context.last_intent_result = result
        
        # Record stats
        if self._stats:
            self._stats.record_result(result)
        
        return result
    
    # ========================================================================
    # Internal Methods
    # ========================================================================
    
    def _try_regex(self, text: str) -> Optional[IntentResult]:
        """Try regex patterns.
        
        Args:
            text: Input text
        
        Returns:
            IntentResult if matched, None otherwise
        """
        result = self._patterns.match(text)
        
        if result and result.confidence >= self.config.regex_min_confidence:
            return result
        
        return None
    
    def _try_llm(
        self,
        text: str,
        context: Optional[NLUContext] = None,
    ) -> Optional[IntentResult]:
        """Try LLM classification.
        
        Args:
            text: Input text
            context: NLU context
        
        Returns:
            IntentResult from LLM
        """
        try:
            # Build context dict for LLM
            ctx_dict = None
            if context:
                ctx_dict = {
                    "focused_app": context.focused_app,
                    "current_url": context.current_url,
                    "current_page_title": context.current_page_title,
                    "recent_intents": context.recent_intents,
                }
            
            return self.llm.classify(text, ctx_dict)
            
        except Exception as e:
            # Log error but don't crash
            if self._stats:
                self._stats.record_error()
            
            return IntentResult(
                intent="unknown",
                slots={},
                confidence=0.0,
                original_text=text,
                source="llm",
                metadata={"error": str(e)},
            )
    
    def _enhance_with_slots(
        self,
        result: IntentResult,
        text: str,
    ) -> IntentResult:
        """Enhance result with extracted slots.
        
        Args:
            result: Current intent result
            text: Original text
        
        Returns:
            Enhanced result with more slots
        """
        if not self._slot_extractor:
            return result
        
        # Extract slots for this intent
        extracted = self._slot_extractor.extract_for_intent(text, result.intent)
        
        # Merge with existing slots (existing take priority)
        merged_slots = dict(extracted)
        merged_slots.update(result.slots)
        
        if merged_slots != result.slots:
            return IntentResult(
                intent=result.intent,
                slots=merged_slots,
                confidence=result.confidence,
                original_text=result.original_text,
                source=result.source,
                ambiguous=result.ambiguous,
                clarification=result.clarification,
                alternatives=result.alternatives,
                category=result.category,
                processing_time_ms=result.processing_time_ms,
                metadata=result.metadata,
            )
        
        return result
    
    def _get_context(self, session_id: str) -> NLUContext:
        """Get or create context for session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            NLUContext for session
        """
        if session_id not in self._context:
            self._context[session_id] = NLUContext(session_id=session_id)
        return self._context[session_id]
    
    # ========================================================================
    # Public Methods
    # ========================================================================
    
    def get_stats(self) -> Optional[NLUStats]:
        """Get NLU statistics.
        
        Returns:
            NLUStats if tracking enabled, None otherwise
        """
        return self._stats
    
    def reset_stats(self):
        """Reset statistics."""
        if self._stats:
            self._stats.reset()
    
    def get_context(self, session_id: str) -> Optional[NLUContext]:
        """Get context for a session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            NLUContext or None
        """
        return self._context.get(session_id)
    
    def set_context(self, session_id: str, context: NLUContext):
        """Set context for a session.
        
        Args:
            session_id: Session identifier
            context: Context to set
        """
        self._context[session_id] = context
    
    def clear_context(self, session_id: str):
        """Clear context for a session.
        
        Args:
            session_id: Session identifier
        """
        self._context.pop(session_id, None)
        if self._clarification:
            self._clarification.clear_pending(session_id)
    
    def clear_all_contexts(self):
        """Clear all session contexts."""
        self._context.clear()
    
    def to_legacy_parsed(self, result: IntentResult):
        """Convert to legacy Parsed format.
        
        Args:
            result: IntentResult
        
        Returns:
            Parsed object from router.nlu
        """
        return result.to_parsed()


# ============================================================================
# Quick Parse Function
# ============================================================================


def quick_parse(text: str) -> IntentResult:
    """Quick parse with default settings.
    
    Args:
        text: Text to parse
    
    Returns:
        IntentResult
    """
    nlu = HybridNLU()
    return nlu.parse(text)


# ============================================================================
# Singleton Instance
# ============================================================================


_default_nlu: Optional[HybridNLU] = None


def get_nlu() -> HybridNLU:
    """Get the default HybridNLU instance.
    
    Returns:
        Shared HybridNLU instance
    """
    global _default_nlu
    if _default_nlu is None:
        _default_nlu = HybridNLU()
    return _default_nlu


def parse(text: str, session_id: Optional[str] = None) -> IntentResult:
    """Parse text using the default NLU instance.
    
    Args:
        text: Text to parse
        session_id: Optional session ID
    
    Returns:
        IntentResult
    """
    return get_nlu().parse(text, session_id=session_id)
