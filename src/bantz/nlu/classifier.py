# SPDX-License-Identifier: MIT
"""
LLM-based Intent Classifier.

Uses a large language model to classify user intent when regex patterns
are insufficient. The classifier:

1. Sends user input to LLM with a structured prompt
2. Parses JSON response for intent and slots
3. Returns IntentResult with confidence score

This is the "slow but accurate" path in the hybrid NLU system.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bantz.nlu.types import (
    IntentResult,
    ClarificationRequest,
    ClarificationOption,
    IntentCategory,
)

from bantz.llm.base import LLMClientProtocol, LLMMessage, create_client


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class ClassifierConfig:
    """Configuration for LLM intent classifier.
    
    Attributes:
        model: LLM model to use
        temperature: Sampling temperature (lower = more deterministic)
        max_tokens: Maximum tokens in response
        timeout_seconds: Request timeout
        min_confidence_threshold: Below this, mark as ambiguous
        cache_enabled: Whether to cache results
        cache_ttl_seconds: Cache entry lifetime
        max_cache_size: Maximum cache entries (prevents memory leak)
        cache_sweep_interval: Sweep expired entries every N classifies
    """
    
    model: str = "Qwen/Qwen2.5-3B-Instruct-AWQ"
    temperature: float = 0.1  # Low for consistent classification
    max_tokens: int = 256
    timeout_seconds: float = 30.0
    min_confidence_threshold: float = 0.5
    cache_enabled: bool = True
    cache_ttl_seconds: float = 300.0  # 5 minutes
    max_cache_size: int = 1000
    cache_sweep_interval: int = 50  # sweep every N classifies


# ============================================================================
# Intent Definitions
# ============================================================================


# All valid intents the classifier can return
VALID_INTENTS = {
    # Browser
    "browser_open",
    "browser_search",
    "browser_click",
    "browser_type",
    "browser_scroll_down",
    "browser_scroll_up",
    "browser_back",
    "browser_scan",
    "browser_wait",
    
    # App control
    "app_open",
    "app_close",
    "app_focus",
    "app_list",
    
    # File operations
    "file_read",
    "file_write",
    "file_edit",
    "file_create",
    "file_delete",
    "file_list",
    "file_search",
    
    # Terminal
    "terminal_run",
    "terminal_background",
    
    # Reminders
    "reminder_add",
    "reminder_list",
    "reminder_cancel",
    "checkin_add",
    
    # Queue control
    "queue_pause",
    "queue_resume",
    "queue_abort",
    "queue_skip",
    "queue_status",
    
    # UI/Overlay
    "overlay_move",
    "overlay_hide",
    "overlay_show",
    
    # Agent
    "agent_run",
    "agent_status",
    "agent_history",
    
    # System
    "pc_hotkey",
    "clipboard_set",
    "clipboard_get",
    
    # Conversation
    "conversation",
    "greeting",
    "thanks",
    "help",
    
    # Unknown
    "unknown",
}

# Required slots for each intent
REQUIRED_SLOTS = {
    "browser_open": ["url", "site"],  # At least one
    "browser_search": ["query"],
    "browser_click": ["element"],
    "browser_type": ["text"],
    "app_open": ["app"],
    "app_close": ["app"],
    "file_read": ["path"],
    "file_write": ["path", "content"],
    "file_edit": ["path"],
    "terminal_run": ["command"],
    "reminder_add": ["message", "time"],
    "checkin_add": ["message", "time"],
    "overlay_move": ["position"],
}

# Slot descriptions for LLM
SLOT_DESCRIPTIONS = {
    "url": "Tam URL veya site adı (youtube, google, github, vb.)",
    "site": "Site kısaltması (youtube, twitter, instagram)",
    "query": "Arama sorgusu",
    "element": "Tıklanacak element (buton, link, metin)",
    "text": "Yazılacak metin",
    "app": "Uygulama adı (spotify, discord, vscode, firefox)",
    "path": "Dosya veya klasör yolu",
    "content": "Dosya içeriği",
    "command": "Terminal komutu",
    "message": "Hatırlatma mesajı",
    "time": "Zaman ifadesi (5 dakika sonra, yarın saat 3)",
    "position": "Ekran pozisyonu (sağ üst, sol alt, orta)",
    "n": "Sayı değeri",
}


# ============================================================================
# System Prompt
# ============================================================================


SYSTEM_PROMPT = """Sen bir intent sınıflandırıcısın. Kullanıcının Türkçe mesajını analiz et ve JSON formatında yanıt ver.

# Görevin
1. Kullanıcının ne yapmak istediğini anla
2. Doğru intent'i seç
3. Gerekli slot'ları çıkar
4. Emin değilsen düşük confidence ver

# Çıktı Formatı
SADECE geçerli JSON döndür, başka bir şey yazma:
{
    "intent": "intent_adı",
    "confidence": 0.0-1.0,
    "slots": {"slot_adı": "değer"},
    "ambiguous": false,
    "clarification_needed": null,
    "alternatives": []
}

# Mevcut Intent'ler

## Tarayıcı
- browser_open: Web sitesi açma. Slots: url veya site
- browser_search: Sitede arama. Slots: query, site (optional)
- browser_click: Elemente tıklama. Slots: element
- browser_type: Metin yazma. Slots: text
- browser_scroll_down/up: Sayfa kaydırma
- browser_back: Geri gitme

## Uygulama
- app_open: Uygulama açma. Slots: app
- app_close: Uygulama kapatma. Slots: app
- app_list: Açık uygulamaları listele

## Dosya
- file_read: Dosya okuma. Slots: path
- file_edit: Dosya düzenleme. Slots: path
- file_list: Klasör listeleme. Slots: path (optional)

## Terminal
- terminal_run: Komut çalıştırma. Slots: command

## Hatırlatma
- reminder_add: Hatırlatma ekleme. Slots: message, time
- checkin_add: Check-in ekleme. Slots: message, time

## Kuyruk
- queue_pause: Kuyruğu duraklat
- queue_resume: Kuyruğa devam et
- queue_abort: Kuyruğu iptal et

## Arayüz
- overlay_move: Overlay'i taşı. Slots: position (sağ üst, sol alt, orta, vb.)
- overlay_hide: Overlay'i gizle

## Agent
- agent_run: Çok adımlı görev. Slots: request

## Sohbet
- conversation: Genel sohbet veya soru
- greeting: Selamlama
- thanks: Teşekkür
- help: Yardım isteme

## Bilinmeyen
- unknown: Anlaşılamadı (confidence düşük olmalı)

# Slot Çıkarma Kuralları
- URL: "youtube.com", "github.com/user/repo" -> url slot
- Site kısaltma: "youtube", "twitter" -> site slot
- Uygulama: "spotify", "discord", "vscode" -> app slot
- Zaman: "5 dakika sonra", "yarın 15:00" -> time slot
- Pozisyon: "sağ üst", "sol alt", "orta" -> position slot

# Belirsizlik
Eğer emin değilsen:
- confidence düşür (0.3-0.6)
- ambiguous: true yap
- clarification_needed: "Soru cümlesi" ekle
- alternatives: [["diğer_intent", 0.4]] ekle

# Örnekler

Girdi: "youtube aç"
{"intent": "browser_open", "confidence": 0.95, "slots": {"site": "youtube"}, "ambiguous": false}

Girdi: "youtube'a gidebilir misin"
{"intent": "browser_open", "confidence": 0.90, "slots": {"site": "youtube"}, "ambiguous": false}

Girdi: "spotify'da coldplay çal"
{"intent": "browser_search", "confidence": 0.85, "slots": {"site": "spotify", "query": "coldplay"}, "ambiguous": false}

Girdi: "5 dakika sonra toplantı var hatırlat"
{"intent": "reminder_add", "confidence": 0.95, "slots": {"time": "5 dakika sonra", "message": "toplantı var"}, "ambiguous": false}

Girdi: "aç"
{"intent": "unknown", "confidence": 0.3, "slots": {}, "ambiguous": true, "clarification_needed": "Neyi açmamı istersin?"}

Girdi: "sağ üste geç"
{"intent": "overlay_move", "confidence": 0.95, "slots": {"position": "sağ üst"}, "ambiguous": false}

Girdi: "selam nasılsın"
{"intent": "greeting", "confidence": 0.95, "slots": {}, "ambiguous": false}
"""


# ============================================================================
# LLM Intent Classifier
# ============================================================================


class LLMIntentClassifier:
    """LLM-based intent classification.
    
    Uses an LLM to understand natural language variations that regex
    can't handle. Returns structured IntentResult with confidence.
    
    Example:
        classifier = LLMIntentClassifier()
        result = classifier.classify("youtube'a gidebilir misin lütfen")
        # IntentResult(intent='browser_open', slots={'site': 'youtube'}, confidence=0.90)
    """
    
    def __init__(
        self,
        config: Optional[ClassifierConfig] = None,
        llm_client: Optional[LLMClientProtocol] = None,
    ):
        """Initialize the classifier.
        
        Args:
            config: Classifier configuration
            llm_client: Pre-configured LLM client (optional)
        """
        self.config = config or ClassifierConfig()
        self._client = llm_client
        self._cache: Dict[str, Tuple[IntentResult, float]] = {}  # text -> (result, timestamp)
        self._classify_count: int = 0  # classify call counter for periodic sweep
    
    @property
    def client(self):
        """Lazy-load LLM client."""
        if self._client is None:
            self._client = create_client(
                "vllm",
                base_url=os.getenv("BANTZ_VLLM_URL", "http://127.0.0.1:8001"),
                model=self.config.model,
                timeout=self.config.timeout_seconds,
            )
        return self._client
    
    def classify(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """Classify user input into intent.
        
        Args:
            text: User input text
            context: Optional context (current app, URL, etc.)
        
        Returns:
            IntentResult with intent, slots, and confidence
        """
        start_time = time.time()
        
        # Normalize text
        text = text.strip()
        if not text:
            return IntentResult.unknown("", source="llm")
        
        # Check cache
        cache_key = self._cache_key(text, context)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        
        try:
            # Build messages
            messages = self._build_messages(text, context)
            
            # Call LLM
            response = self.client.chat(
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            
            # Parse response
            result = self._parse_response(response, text, start_time)
            
            # Cache result (bounded — Issue #652)
            self._put_cache(cache_key, result)
            
            return result
            
        except Exception as e:
            # Log error and return unknown
            processing_time = (time.time() - start_time) * 1000
            return IntentResult(
                intent="unknown",
                slots={},
                confidence=0.0,
                original_text=text,
                source="llm",
                processing_time_ms=processing_time,
                metadata={"error": str(e)},
            )
    
    def _build_messages(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List:
        """Build messages for LLM chat."""
        messages = [LLMMessage(role="system", content=SYSTEM_PROMPT)]
        
        # Add context if provided
        if context:
            context_str = self._format_context(context)
            if context_str:
                messages.append(LLMMessage(
                    role="system",
                    content=f"Mevcut bağlam:\n{context_str}",
                ))
        
        # Add user message
        messages.append(LLMMessage(role="user", content=text))
        
        return messages
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context for LLM."""
        parts = []
        
        if context.get("focused_app"):
            parts.append(f"- Aktif uygulama: {context['focused_app']}")
        if context.get("current_url"):
            parts.append(f"- Mevcut URL: {context['current_url']}")
        if context.get("current_page_title"):
            parts.append(f"- Sayfa başlığı: {context['current_page_title']}")
        if context.get("recent_intents"):
            recent = ", ".join(context["recent_intents"][-3:])
            parts.append(f"- Son intent'ler: {recent}")
        
        return "\n".join(parts)
    
    def _parse_response(
        self,
        response: str,
        original_text: str,
        start_time: float,
    ) -> IntentResult:
        """Parse LLM response into IntentResult."""
        processing_time = (time.time() - start_time) * 1000
        
        # Try to extract JSON from response
        json_data = self._extract_json(response)
        
        if json_data is None:
            return IntentResult(
                intent="unknown",
                slots={},
                confidence=0.0,
                original_text=original_text,
                source="llm",
                processing_time_ms=processing_time,
                metadata={"raw_response": response, "parse_error": "No valid JSON"},
            )
        
        # Extract fields
        intent = json_data.get("intent", "unknown")
        confidence = float(json_data.get("confidence", 0.5))
        slots = json_data.get("slots", {})
        ambiguous = json_data.get("ambiguous", False)
        clarification_needed = json_data.get("clarification_needed")
        alternatives = json_data.get("alternatives", [])
        
        # Validate intent
        if intent not in VALID_INTENTS:
            # Try to find closest match
            intent = self._find_closest_intent(intent)
            confidence *= 0.8  # Reduce confidence for mapping
        
        # Build clarification if needed
        clarification = None
        if ambiguous and clarification_needed:
            clarification = ClarificationRequest(
                question=clarification_needed,
                original_text=original_text,
                reason="low_confidence",
            )
            
            # Add alternatives as options
            for alt_intent, alt_conf in alternatives:
                clarification.options.append(ClarificationOption(
                    intent=alt_intent,
                    description=self._intent_description(alt_intent),
                    probability=alt_conf,
                ))
        
        # Check for missing required slots
        if intent in REQUIRED_SLOTS:
            missing = self._check_required_slots(intent, slots)
            if missing and clarification is None:
                clarification = ClarificationRequest(
                    question=f"{missing[0]} gerekli. {SLOT_DESCRIPTIONS.get(missing[0], '')}",
                    original_text=original_text,
                    reason="missing_slot",
                    slot_needed=missing[0],
                )
                ambiguous = True
        
        return IntentResult(
            intent=intent,
            slots=slots,
            confidence=confidence,
            original_text=original_text,
            source="llm",
            ambiguous=ambiguous,
            clarification=clarification,
            alternatives=[(a[0], a[1]) for a in alternatives if len(a) >= 2],
            processing_time_ms=processing_time,
            metadata={"raw_response": response},
        )
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON in text
        patterns = [
            r'\{[^{}]*\}',  # Simple object
            r'\{[^{}]*\{[^{}]*\}[^{}]*\}',  # Nested object (one level)
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def _find_closest_intent(self, intent: str) -> str:
        """Find closest valid intent for an invalid one."""
        intent_lower = intent.lower().replace("-", "_").replace(" ", "_")
        
        # Direct match
        if intent_lower in VALID_INTENTS:
            return intent_lower
        
        # Common mappings
        mappings = {
            "open_browser": "browser_open",
            "open_app": "app_open",
            "close_app": "app_close",
            "search": "browser_search",
            "google_search": "browser_search",
            "add_reminder": "reminder_add",
            "set_reminder": "reminder_add",
            "run_command": "terminal_run",
            "exec": "terminal_run",
            "chat": "conversation",
            "talk": "conversation",
            "hello": "greeting",
            "hi": "greeting",
            "bye": "thanks",
            "open_file": "file_read",
            "read": "file_read",
            "write": "file_write",
            "edit": "file_edit",
        }
        
        if intent_lower in mappings:
            return mappings[intent_lower]
        
        # Prefix matching
        for valid in VALID_INTENTS:
            if intent_lower.startswith(valid.split("_")[0]):
                return valid
        
        return "unknown"
    
    def _check_required_slots(
        self,
        intent: str,
        slots: Dict[str, Any],
    ) -> List[str]:
        """Check for missing required slots."""
        required = REQUIRED_SLOTS.get(intent, [])
        if not required:
            return []
        
        # For browser_open, either url or site is needed
        if intent == "browser_open":
            if slots.get("url") or slots.get("site"):
                return []
            return ["url"]  # Default to asking for url
        
        # For other intents, all required slots must be present
        missing = [slot for slot in required if slot not in slots]
        return missing
    
    def _intent_description(self, intent: str) -> str:
        """Get human-readable description for intent."""
        descriptions = {
            "browser_open": "Web sitesi aç",
            "browser_search": "Arama yap",
            "app_open": "Uygulama aç",
            "app_close": "Uygulama kapat",
            "file_read": "Dosya oku",
            "file_edit": "Dosya düzenle",
            "terminal_run": "Terminal komutu çalıştır",
            "reminder_add": "Hatırlatma ekle",
            "conversation": "Sohbet",
            "unknown": "Anlaşılamadı",
        }
        return descriptions.get(intent, intent)
    
    def _cache_key(self, text: str, context: Optional[Dict[str, Any]]) -> str:
        """Generate cache key for text and context."""
        # Simple key: just the text (lowercase, trimmed)
        # Could include context hash for more precise caching
        return text.lower().strip()
    
    def _get_cached(self, key: str) -> Optional[IntentResult]:
        """Get cached result if still valid."""
        if not self.config.cache_enabled:
            return None
        
        if key not in self._cache:
            return None
        
        result, timestamp = self._cache[key]
        
        # Check TTL
        if time.time() - timestamp > self.config.cache_ttl_seconds:
            del self._cache[key]
            return None
        
        return result

    def _put_cache(self, key: str, result: IntentResult) -> None:
        """Store a result in the cache, enforcing max size.

        When the cache exceeds ``max_cache_size`` the oldest entry
        (by insertion timestamp) is evicted.  A periodic sweep of
        expired entries runs every ``cache_sweep_interval`` classifies.
        """
        if not self.config.cache_enabled:
            return

        # Periodic sweep — remove all TTL-expired entries
        self._classify_count += 1
        if self._classify_count % self.config.cache_sweep_interval == 0:
            self._sweep_expired()

        # Evict oldest if at capacity
        while len(self._cache) >= self.config.max_cache_size:
            self._evict_oldest()

        self._cache[key] = (result, time.time())

    def _sweep_expired(self) -> int:
        """Remove all TTL-expired cache entries.

        Returns:
            Number of entries removed.
        """
        now = time.time()
        ttl = self.config.cache_ttl_seconds
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > ttl]
        for k in expired:
            del self._cache[k]
        return len(expired)

    def _evict_oldest(self) -> None:
        """Evict the single oldest cache entry by timestamp."""
        if not self._cache:
            return
        oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
        del self._cache[oldest_key]

    def clear_cache(self):
        """Clear the result cache."""
        self._cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self.config.max_cache_size,
            "enabled": self.config.cache_enabled,
            "ttl_seconds": self.config.cache_ttl_seconds,
        }


# ============================================================================
# Batch Classification
# ============================================================================


def classify_batch(
    texts: List[str],
    classifier: Optional[LLMIntentClassifier] = None,
) -> List[IntentResult]:
    """Classify multiple texts.
    
    Args:
        texts: List of texts to classify
        classifier: Classifier instance (created if not provided)
    
    Returns:
        List of IntentResults
    """
    if classifier is None:
        classifier = LLMIntentClassifier()
    
    return [classifier.classify(text) for text in texts]


# ============================================================================
# Quick Classification
# ============================================================================


def quick_classify(text: str) -> IntentResult:
    """Quick classification with default settings.
    
    Args:
        text: Text to classify
    
    Returns:
        IntentResult
    """
    classifier = LLMIntentClassifier()
    return classifier.classify(text)
