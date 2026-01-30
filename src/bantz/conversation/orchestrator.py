"""
Conversation Orchestrator for V2-6 (Issue #38).

Coordinates the conversation flow:
- FSM state management
- ASR → Router → LLM → TTS pipeline
- Feedback phrase injection
- Error handling
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol

from bantz.conversation.fsm import (
    ConversationFSM,
    ConversationState,
    TRIGGER_SPEECH_START,
    TRIGGER_SPEECH_END,
    TRIGGER_THINKING_DONE,
    TRIGGER_SPEAKING_START,
    TRIGGER_SPEAKING_DONE,
    TRIGGER_TIMEOUT,
)
from bantz.conversation.feedback import FeedbackRegistry, FeedbackType
from bantz.conversation.context import ConversationContext, TurnInfo
from bantz.conversation.bargein import BargeInHandler

logger = logging.getLogger(__name__)


# =============================================================================
# Protocol Interfaces
# =============================================================================


class ASREngine(Protocol):
    """Protocol for ASR engine."""
    
    async def listen(self) -> str:
        """Listen and transcribe speech."""
        ...


class TTSEngine(Protocol):
    """Protocol for TTS engine."""
    
    async def speak(self, text: str) -> None:
        """Speak text."""
        ...
    
    def is_playing(self) -> bool:
        """Check if playing."""
        ...
    
    async def stop(self) -> None:
        """Stop playback."""
        ...


class RouterEngine(Protocol):
    """Protocol for router engine."""
    
    async def route(self, text: str, context: Any = None) -> Any:
        """Route utterance to appropriate handler."""
        ...


# =============================================================================
# Orchestrator Config
# =============================================================================


@dataclass
class OrchestratorConfig:
    """Configuration for orchestrator."""
    
    thinking_timeout_s: float = 30.0
    speaking_timeout_s: float = 60.0
    listening_timeout_s: float = 10.0
    speak_acknowledgment: bool = True
    speak_thinking: bool = True
    speak_error: bool = True
    language: str = "tr"


# =============================================================================
# Conversation Orchestrator
# =============================================================================


class ConversationOrchestrator:
    """
    Orchestrates the full conversation flow.
    
    Pipeline:
    1. IDLE → LISTENING (wakeword/speech)
    2. LISTENING → THINKING (speech end)
    3. Router processes utterance
    4. THINKING → SPEAKING (response ready)
    5. TTS speaks response
    6. SPEAKING → IDLE (TTS done)
    
    Features:
    - Feedback phrases (ack, thinking, error)
    - Barge-in handling
    - Context management
    - Error recovery
    """
    
    def __init__(
        self,
        fsm: Optional[ConversationFSM] = None,
        asr: Optional[ASREngine] = None,
        tts: Optional[TTSEngine] = None,
        router: Optional[RouterEngine] = None,
        feedback: Optional[FeedbackRegistry] = None,
        context: Optional[ConversationContext] = None,
        bargein: Optional[BargeInHandler] = None,
        event_bus: Optional[Any] = None,
        config: Optional[OrchestratorConfig] = None,
    ):
        """
        Initialize orchestrator.
        
        Args:
            fsm: Conversation FSM
            asr: ASR engine for speech recognition
            tts: TTS engine for speech synthesis
            router: Router for utterance processing
            feedback: Feedback phrase registry
            context: Conversation context
            bargein: Barge-in handler
            event_bus: Event bus for notifications
            config: Orchestrator configuration
        """
        self._fsm = fsm or ConversationFSM(event_bus=event_bus)
        self._asr = asr
        self._tts = tts
        self._router = router
        self._feedback = feedback or FeedbackRegistry()
        self._context = context or ConversationContext()
        self._bargein = bargein
        self._event_bus = event_bus
        self._config = config or OrchestratorConfig()
        
        # State
        self._active = False
        self._processing = False
        self._current_task: Optional[asyncio.Task] = None
        
        # Statistics
        self._total_utterances = 0
        self._successful_responses = 0
        self._errors = 0
    
    @property
    def is_active(self) -> bool:
        """Check if orchestrator is active."""
        return self._active
    
    @property
    def is_processing(self) -> bool:
        """Check if currently processing."""
        return self._processing
    
    @property
    def current_state(self) -> ConversationState:
        """Get current FSM state."""
        return self._fsm.current_state
    
    @property
    def context(self) -> ConversationContext:
        """Get conversation context."""
        return self._context
    
    async def start(self) -> None:
        """Start the orchestrator."""
        if self._active:
            return
        
        self._active = True
        self._fsm.reset()
        
        logger.info("Conversation orchestrator started")
        
        if self._event_bus and hasattr(self._event_bus, 'emit'):
            await self._event_bus.emit("orchestrator.started", {
                "timestamp": datetime.now().isoformat()
            })
    
    async def stop(self) -> None:
        """Stop the orchestrator."""
        if not self._active:
            return
        
        self._active = False
        
        # Cancel current task if any
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
        
        # Stop TTS if playing
        if self._tts and self._tts.is_playing():
            await self._tts.stop()
        
        self._fsm.reset()
        
        logger.info("Conversation orchestrator stopped")
        
        if self._event_bus and hasattr(self._event_bus, 'emit'):
            await self._event_bus.emit("orchestrator.stopped", {
                "timestamp": datetime.now().isoformat()
            })
    
    async def process_utterance(self, text: str) -> str:
        """
        Process a user utterance through the full pipeline.
        
        Args:
            text: User's speech text
            
        Returns:
            Assistant's response text
        """
        if not self._active:
            logger.warning("Orchestrator not active")
            return ""
        
        self._processing = True
        self._total_utterances += 1
        
        try:
            # Add user turn to context
            user_turn = self._context.add_user_turn(text)
            
            # Transition to THINKING
            await self._fsm.transition(TRIGGER_SPEECH_END)
            
            # Speak acknowledgment
            if self._config.speak_acknowledgment:
                await self.speak_feedback(FeedbackType.ACKNOWLEDGMENT)
            
            # Speak thinking
            if self._config.speak_thinking:
                await self.speak_feedback(FeedbackType.THINKING)
            
            # Route utterance
            response = ""
            if self._router:
                try:
                    result = await asyncio.wait_for(
                        self._router.route(text, self._context),
                        timeout=self._config.thinking_timeout_s
                    )
                    response = str(result) if result else ""
                except asyncio.TimeoutError:
                    logger.error("Router timeout")
                    response = self._feedback.get_random(FeedbackType.ERROR)
                    self._errors += 1
                except Exception as e:
                    logger.error(f"Router error: {e}")
                    response = self._feedback.get_random(FeedbackType.ERROR)
                    self._errors += 1
            else:
                # No router, echo back
                response = f"Duydum: {text}"
            
            # Add assistant turn
            self._context.add_assistant_turn(response)
            
            # Transition to SPEAKING
            await self._fsm.transition(TRIGGER_THINKING_DONE)
            
            # Speak response
            if self._tts and response:
                await self._tts.speak(response)
            
            # Transition to IDLE
            await self._fsm.transition(TRIGGER_SPEAKING_DONE)
            
            self._successful_responses += 1
            return response
            
        except Exception as e:
            logger.error(f"Error processing utterance: {e}")
            self._errors += 1
            
            # Try to speak error
            if self._config.speak_error:
                try:
                    await self.speak_feedback(FeedbackType.ERROR)
                except Exception:
                    pass
            
            # Reset to IDLE
            self._fsm.reset()
            return ""
            
        finally:
            self._processing = False
    
    async def speak_feedback(
        self,
        feedback_type: FeedbackType,
        wait: bool = False
    ) -> None:
        """
        Speak a feedback phrase.
        
        Args:
            feedback_type: Type of feedback
            wait: Whether to wait for TTS to finish
        """
        phrase = self._feedback.get_random(
            feedback_type,
            language=self._config.language
        )
        
        if not phrase or not self._tts:
            return
        
        try:
            if wait:
                await self._tts.speak(phrase)
            else:
                # Fire and forget
                asyncio.create_task(self._tts.speak(phrase))
        except Exception as e:
            logger.error(f"Error speaking feedback: {e}")
    
    async def handle_wakeword(self) -> None:
        """Handle wakeword detection."""
        if not self._active:
            return
        
        from bantz.conversation.fsm import TRIGGER_WAKEWORD
        await self._fsm.transition(TRIGGER_WAKEWORD)
        
        # Speak greeting
        await self.speak_feedback(FeedbackType.GREETING)
    
    async def handle_barge_in(
        self,
        speech_volume: float = 0.7,
        speech_duration_ms: float = 300
    ) -> bool:
        """
        Handle barge-in attempt.
        
        Args:
            speech_volume: Volume of interrupting speech
            speech_duration_ms: Duration of interrupting speech
            
        Returns:
            True if barge-in was accepted
        """
        if not self._bargein:
            return False
        
        from bantz.conversation.bargein import BargeInEvent, BargeInAction
        
        event = BargeInEvent(
            speech_volume=speech_volume,
            speech_duration_ms=speech_duration_ms,
            tts_was_playing=self._tts.is_playing() if self._tts else False
        )
        
        action = await self._bargein.handle(event)
        return action != BargeInAction.IGNORE
    
    def get_stats(self) -> dict:
        """Get orchestrator statistics."""
        return {
            "active": self._active,
            "current_state": self._fsm.current_state.value,
            "total_utterances": self._total_utterances,
            "successful_responses": self._successful_responses,
            "errors": self._errors,
            "success_rate": (
                self._successful_responses / self._total_utterances
                if self._total_utterances > 0
                else 0.0
            ),
            "conversation_turns": self._context.turn_count,
        }
    
    def reset_context(self) -> None:
        """Reset conversation context."""
        self._context.clear()
    
    def new_conversation(self) -> str:
        """Start a new conversation."""
        self._context = ConversationContext()
        self._fsm.reset()
        return self._context.conversation_id


def create_orchestrator(
    event_bus: Optional[Any] = None,
    language: str = "tr",
    **kwargs
) -> ConversationOrchestrator:
    """Factory for creating conversation orchestrator."""
    config = OrchestratorConfig(language=language)
    feedback = FeedbackRegistry(language=language)
    fsm = ConversationFSM(event_bus=event_bus)
    context = ConversationContext()
    
    return ConversationOrchestrator(
        fsm=fsm,
        feedback=feedback,
        context=context,
        event_bus=event_bus,
        config=config,
        **kwargs
    )
