"""Jarvis Conversation Flow Manager (Issue #20).

Sürekli konuşma akışı - wake word atla, efendim hitabı, timeout yönetimi.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, List, Any, Dict

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Conversation State Machine
# ─────────────────────────────────────────────────────────────────

class ConversationState(Enum):
    """Konuşma durumları."""
    IDLE = auto()         # Beklemede, wake word dinliyor
    ENGAGED = auto()      # Aktif konuşma, wake word gerekmez
    PROCESSING = auto()   # İşlem yapılıyor
    SPEAKING = auto()     # Bantz konuşuyor
    WAITING = auto()      # Kullanıcı cevabı bekleniyor


@dataclass
class ConversationContext:
    """Konuşma bağlamı.
    
    Attributes:
        state: Mevcut konuşma durumu
        last_interaction: Son etkileşim zamanı
        turn_count: Konuşma tur sayısı
        topic: Aktif konu (opsiyonel)
        pending_question: Bekleyen soru (opsiyonel)
        last_command: Son verilen komut
        last_response: Son verilen yanıt
    """
    state: ConversationState = ConversationState.IDLE
    last_interaction: float = 0.0
    turn_count: int = 0
    topic: Optional[str] = None
    pending_question: Optional[str] = None
    last_command: Optional[str] = None
    last_response: Optional[str] = None


@dataclass
class ConversationConfig:
    """Konuşma yönetimi konfigürasyonu.
    
    Attributes:
        engagement_timeout: Konuşma devam etme süresi (saniye)
        quick_response_window: Hızlı yanıt penceresi (saniye)
        max_turns: Maksimum konuşma turu
    """
    engagement_timeout: float = 8.0
    quick_response_window: float = 3.0
    max_turns: int = 20


# ─────────────────────────────────────────────────────────────────
# Conversation Manager
# ─────────────────────────────────────────────────────────────────

class ConversationManager:
    """Jarvis tarzı sürekli konuşma yönetimi.
    
    Wake word atla, engagement timeout, follow-up soru yönetimi.
    
    Usage:
        async def on_state_change(ctx: ConversationContext):
            print(f"State: {ctx.state.name}")
        
        conversation = ConversationManager(on_state_change=on_state_change)
        
        # Wake word tetiklendi
        conversation.start_interaction()
        
        # Konuşma devam mı?
        if conversation.should_skip_wake_word():
            # Wake word gerekmez
            pass
        
        # Vedalaşma kontrolü
        if conversation.is_goodbye("teşekkürler"):
            conversation.end_interaction(keep_engaged=False)
    """
    
    # Vedalaşma kalıpları
    GOODBYE_PATTERNS = [
        "teşekkürler", "teşekkür ederim", "sağol", "sağ ol",
        "tamam", "bu kadar", "yeter", "bitirdik",
        "görüşürüz", "iyi günler", "iyi akşamlar", "iyi geceler",
        "hoşça kal", "güle güle", "bye",
    ]
    
    # Follow-up tetikleyicileri (Bantz bunları söylediğinde)
    FOLLOW_UP_TRIGGERS = [
        "başka bir şey var mı",
        "devam edelim mi",
        "bir şey daha",
        "sormak istediğiniz",
        "yardımcı olabileceğim",
    ]
    
    # Follow-up başlangıçları (kullanıcı böyle başlarsa)
    FOLLOW_UP_STARTERS = [
        "peki", "ya", "e", "hm", "hmm",
        "bir de", "ayrıca", "sonra",
        "evet", "hayır", "olur", "olmaz",
    ]
    
    def __init__(
        self,
        config: Optional[ConversationConfig] = None,
        on_state_change: Optional[Callable[[ConversationContext], Any]] = None,
    ):
        """Initialize conversation manager.
        
        Args:
            config: Konuşma konfigürasyonu
            on_state_change: State değişikliğinde çağrılacak callback
        """
        self.config = config or ConversationConfig()
        self.on_state_change = on_state_change
        
        self._context = ConversationContext()
        self._timeout_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._on_timeout_callbacks: List[Callable[[], Any]] = []
        self._on_engaged_callbacks: List[Callable[[], Any]] = []
        self._on_idle_callbacks: List[Callable[[], Any]] = []
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def context(self) -> ConversationContext:
        """Get current context."""
        return self._context
    
    @property
    def state(self) -> ConversationState:
        """Get current state."""
        return self._context.state
    
    @property
    def is_engaged(self) -> bool:
        """Aktif konuşma var mı?"""
        return self._context.state != ConversationState.IDLE
    
    @property
    def is_idle(self) -> bool:
        """Beklemede mi?"""
        return self._context.state == ConversationState.IDLE
    
    @property
    def turn_count(self) -> int:
        """Konuşma tur sayısı."""
        return self._context.turn_count
    
    @property
    def time_since_last_interaction(self) -> float:
        """Son etkileşimden bu yana geçen süre."""
        if self._context.last_interaction == 0:
            return float('inf')
        return time.time() - self._context.last_interaction
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_timeout(self, callback: Callable[[], Any]) -> None:
        """Timeout olduğunda çağrılacak callback."""
        self._on_timeout_callbacks.append(callback)
    
    def on_engaged(self, callback: Callable[[], Any]) -> None:
        """Engaged state'e geçildiğinde çağrılacak callback."""
        self._on_engaged_callbacks.append(callback)
    
    def on_idle(self, callback: Callable[[], Any]) -> None:
        """Idle state'e geçildiğinde çağrılacak callback."""
        self._on_idle_callbacks.append(callback)
    
    # ─────────────────────────────────────────────────────────────
    # State Management
    # ─────────────────────────────────────────────────────────────
    
    def _set_state(self, state: ConversationState) -> None:
        """Set state and notify."""
        old_state = self._context.state
        if state == old_state:
            return
        
        self._context.state = state
        
        logger.debug(f"[Conversation] State: {old_state.name} -> {state.name}")
        
        # Fire specific callbacks
        if state == ConversationState.ENGAGED and old_state == ConversationState.IDLE:
            self._fire_callbacks(self._on_engaged_callbacks)
        elif state == ConversationState.IDLE and old_state != ConversationState.IDLE:
            self._fire_callbacks(self._on_idle_callbacks)
        
        # Fire general callback
        self._notify_state_change()
    
    def _notify_state_change(self) -> None:
        """Notify state change."""
        if self.on_state_change:
            try:
                self.on_state_change(self._context)
            except Exception as e:
                logger.error(f"[Conversation] State change callback error: {e}")
    
    def _fire_callbacks(self, callbacks: List[Callable]) -> None:
        """Fire all callbacks in list."""
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"[Conversation] Callback error: {e}")
    
    # ─────────────────────────────────────────────────────────────
    # Interaction Control
    # ─────────────────────────────────────────────────────────────
    
    def start_interaction(self, topic: Optional[str] = None) -> None:
        """Etkileşim başlat - wake word tetiklendi veya konuşma devam.
        
        Args:
            topic: Konuşma konusu (opsiyonel)
        """
        self._context.last_interaction = time.time()
        self._context.turn_count += 1
        
        if topic:
            self._context.topic = topic
        
        self._set_state(ConversationState.ENGAGED)
        self._reset_timeout()
        
        logger.info(f"[Conversation] Interaction started (turn {self._context.turn_count})")
    
    def end_interaction(self, keep_engaged: bool = True) -> None:
        """Etkileşim bitir.
        
        Args:
            keep_engaged: True ise konuşma devam edecek (timeout başlar)
        """
        self._context.last_interaction = time.time()
        
        if keep_engaged:
            # Konuşma devam edecek, timeout başlat
            self._reset_timeout()
            self._set_state(ConversationState.ENGAGED)
            logger.debug("[Conversation] Interaction ended, staying engaged")
        else:
            # Tamamen bitir
            self._cancel_timeout()
            self._reset_context()
            self._set_state(ConversationState.IDLE)
            logger.info("[Conversation] Interaction ended, going idle")
    
    def set_processing(self) -> None:
        """İşlem yapılıyor state'ine geç."""
        self._context.last_interaction = time.time()
        self._cancel_timeout()  # İşlem sırasında timeout yok
        self._set_state(ConversationState.PROCESSING)
    
    def set_speaking(self) -> None:
        """Konuşuyor state'ine geç."""
        self._set_state(ConversationState.SPEAKING)
    
    def set_waiting(self, question: Optional[str] = None) -> None:
        """Kullanıcı cevabı bekleniyor state'ine geç.
        
        Args:
            question: Beklenen cevabın sorusu
        """
        self._context.pending_question = question
        self._reset_timeout()
        self._set_state(ConversationState.WAITING)
    
    def record_command(self, command: str) -> None:
        """Son komutu kaydet."""
        self._context.last_command = command
    
    def record_response(self, response: str) -> None:
        """Son yanıtı kaydet."""
        self._context.last_response = response
    
    # ─────────────────────────────────────────────────────────────
    # Wake Word Logic
    # ─────────────────────────────────────────────────────────────
    
    def should_skip_wake_word(self) -> bool:
        """Wake word atlanmalı mı?
        
        Returns:
            True ise wake word gerekmez
        """
        if self._context.state == ConversationState.IDLE:
            return False
        
        # Engagement timeout kontrolü
        elapsed = self.time_since_last_interaction
        if elapsed > self.config.engagement_timeout:
            logger.debug(f"[Conversation] Engagement timeout ({elapsed:.1f}s > {self.config.engagement_timeout}s)")
            self._timeout_expired()
            return False
        
        # Max turns kontrolü
        if self._context.turn_count >= self.config.max_turns:
            logger.debug(f"[Conversation] Max turns reached ({self._context.turn_count})")
            self._timeout_expired()
            return False
        
        return True
    
    def is_quick_response_window(self) -> bool:
        """Hızlı yanıt penceresi içinde mi?
        
        Returns:
            True ise kullanıcı hızlı yanıt verebilir
        """
        elapsed = self.time_since_last_interaction
        return elapsed <= self.config.quick_response_window
    
    # ─────────────────────────────────────────────────────────────
    # Text Analysis
    # ─────────────────────────────────────────────────────────────
    
    def is_goodbye(self, text: str) -> bool:
        """Vedalaşma mı?
        
        Args:
            text: Kullanıcı metni
            
        Returns:
            True ise vedalaşma
        """
        text_lower = text.lower().strip()
        
        # Direkt eşleşme
        for pattern in self.GOODBYE_PATTERNS:
            if pattern in text_lower:
                return True
        
        return False
    
    def is_follow_up(self, text: str) -> bool:
        """Follow-up (takip) ifadesi mi?
        
        Args:
            text: Kullanıcı metni
            
        Returns:
            True ise follow-up
        """
        text_lower = text.lower().strip()
        words = text_lower.split()
        
        # Çok kısa yanıtlar (5 kelime veya az) follow-up
        if len(words) <= 5 and self.is_engaged:
            return True
        
        # Follow-up başlangıçları
        for starter in self.FOLLOW_UP_STARTERS:
            if text_lower.startswith(starter):
                return True
        
        return False
    
    def is_confirmation(self, text: str) -> bool:
        """Onay ifadesi mi?
        
        Args:
            text: Kullanıcı metni
            
        Returns:
            True ise onay
        """
        confirmations = ["evet", "olur", "tamam", "ok", "peki", "tabii", "tabi", "elbette"]
        text_lower = text.lower().strip()
        
        return text_lower in confirmations
    
    def is_rejection(self, text: str) -> bool:
        """Red ifadesi mi?
        
        Args:
            text: Kullanıcı metni
            
        Returns:
            True ise red
        """
        rejections = ["hayır", "olmaz", "yok", "istemiyorum", "iptal", "vazgeç"]
        text_lower = text.lower().strip()
        
        return any(r in text_lower for r in rejections)
    
    def is_number_selection(self, text: str) -> Optional[int]:
        """Sayı seçimi mi? (örn: "3" -> 3. sonucu seç)
        
        Args:
            text: Kullanıcı metni
            
        Returns:
            Seçilen sayı veya None
        """
        text_stripped = text.strip()
        
        # Sadece sayı
        if text_stripped.isdigit():
            return int(text_stripped)
        
        # "birinci", "ikinci" vb.
        ordinals = {
            "birinci": 1, "ilk": 1, "bir": 1,
            "ikinci": 2, "iki": 2,
            "üçüncü": 3, "üç": 3,
            "dördüncü": 4, "dört": 4,
            "beşinci": 5, "beş": 5,
            "sonuncu": -1, "son": -1,
        }
        
        text_lower = text.lower().strip()
        for word, num in ordinals.items():
            if word in text_lower:
                return num
        
        return None
    
    def is_navigation(self, text: str) -> Optional[str]:
        """Navigasyon komutu mu?
        
        Args:
            text: Kullanıcı metni
            
        Returns:
            Navigasyon tipi ("next", "prev", "first", "last") veya None
        """
        text_lower = text.lower().strip()
        
        if any(w in text_lower for w in ["sonraki", "devam", "ilerle"]):
            return "next"
        if any(w in text_lower for w in ["önceki", "geri", "geriye"]):
            return "prev"
        if any(w in text_lower for w in ["ilk", "başa", "baştan"]):
            return "first"
        if any(w in text_lower for w in ["son", "sona"]):
            return "last"
        
        return None
    
    # ─────────────────────────────────────────────────────────────
    # Timeout Management
    # ─────────────────────────────────────────────────────────────
    
    def _reset_timeout(self) -> None:
        """Timeout'u sıfırla."""
        self._cancel_timeout()
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._timeout_task = asyncio.create_task(self._engagement_timeout())
        except RuntimeError:
            # No event loop
            pass
    
    def _cancel_timeout(self) -> None:
        """Timeout'u iptal et."""
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None
    
    async def _engagement_timeout(self) -> None:
        """Engagement timeout - süre dolunca IDLE'a dön."""
        await asyncio.sleep(self.config.engagement_timeout)
        self._timeout_expired()
    
    def _timeout_expired(self) -> None:
        """Timeout süresi doldu."""
        logger.info("[Conversation] Engagement timeout expired")
        
        self._reset_context()
        self._set_state(ConversationState.IDLE)
        
        # Fire timeout callbacks
        self._fire_callbacks(self._on_timeout_callbacks)
    
    def _reset_context(self) -> None:
        """Context'i sıfırla."""
        self._context.turn_count = 0
        self._context.topic = None
        self._context.pending_question = None
    
    # ─────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────
    
    def reset(self) -> None:
        """Tüm state'i sıfırla."""
        self._cancel_timeout()
        self._context = ConversationContext()
        logger.info("[Conversation] Reset")
    
    def get_stats(self) -> dict:
        """İstatistikleri al."""
        return {
            "state": self._context.state.name,
            "turn_count": self._context.turn_count,
            "topic": self._context.topic,
            "last_interaction": self._context.last_interaction,
            "time_since_last": self.time_since_last_interaction,
            "is_engaged": self.is_engaged,
        }


# ─────────────────────────────────────────────────────────────────
# Mock Conversation Manager
# ─────────────────────────────────────────────────────────────────

class MockConversationManager:
    """Mock conversation manager for testing."""
    
    def __init__(self, config: Optional[ConversationConfig] = None):
        self.config = config or ConversationConfig()
        self._context = ConversationContext()
        self._should_skip = False
        self._is_goodbye_result = False
        self._is_follow_up_result = False
    
    @property
    def context(self) -> ConversationContext:
        return self._context
    
    @property
    def state(self) -> ConversationState:
        return self._context.state
    
    @property
    def is_engaged(self) -> bool:
        return self._context.state != ConversationState.IDLE
    
    @property
    def is_idle(self) -> bool:
        return self._context.state == ConversationState.IDLE
    
    @property
    def turn_count(self) -> int:
        return self._context.turn_count
    
    def set_should_skip_wake_word(self, value: bool) -> None:
        self._should_skip = value
    
    def set_is_goodbye_result(self, value: bool) -> None:
        self._is_goodbye_result = value
    
    def set_is_follow_up_result(self, value: bool) -> None:
        self._is_follow_up_result = value
    
    def start_interaction(self, topic: Optional[str] = None) -> None:
        self._context.state = ConversationState.ENGAGED
        self._context.turn_count += 1
        self._context.last_interaction = time.time()
        if topic:
            self._context.topic = topic
    
    def end_interaction(self, keep_engaged: bool = True) -> None:
        if keep_engaged:
            self._context.state = ConversationState.ENGAGED
        else:
            self._context.state = ConversationState.IDLE
            self._context.turn_count = 0
    
    def set_processing(self) -> None:
        self._context.state = ConversationState.PROCESSING
    
    def set_speaking(self) -> None:
        self._context.state = ConversationState.SPEAKING
    
    def set_waiting(self, question: Optional[str] = None) -> None:
        self._context.state = ConversationState.WAITING
        self._context.pending_question = question
    
    def should_skip_wake_word(self) -> bool:
        return self._should_skip
    
    def is_goodbye(self, text: str) -> bool:
        return self._is_goodbye_result
    
    def is_follow_up(self, text: str) -> bool:
        return self._is_follow_up_result
    
    def is_confirmation(self, text: str) -> bool:
        return text.lower() in ["evet", "olur", "tamam"]
    
    def is_rejection(self, text: str) -> bool:
        return text.lower() in ["hayır", "olmaz"]
    
    def is_number_selection(self, text: str) -> Optional[int]:
        if text.isdigit():
            return int(text)
        return None
    
    def is_navigation(self, text: str) -> Optional[str]:
        return None
    
    def record_command(self, command: str) -> None:
        self._context.last_command = command
    
    def record_response(self, response: str) -> None:
        self._context.last_response = response
    
    def reset(self) -> None:
        self._context = ConversationContext()
    
    def get_stats(self) -> dict:
        return {
            "state": self._context.state.name,
            "turn_count": self._context.turn_count,
        }
    
    def on_timeout(self, callback: Callable) -> None:
        pass
    
    def on_engaged(self, callback: Callable) -> None:
        pass
    
    def on_idle(self, callback: Callable) -> None:
        pass
