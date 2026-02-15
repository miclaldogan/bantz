"""
Conversation Finite State Machine for V2-6 (Issue #38).

States:
- IDLE: Waiting for wakeword
- LISTENING: VAD active, user speaking
- THINKING: LLM processing
- SPEAKING: TTS playing
- CONFIRMING: Awaiting confirmation ("emin misin?")

Provides state transitions with callbacks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# Trigger Constants
# =============================================================================

TRIGGER_WAKEWORD = "wakeword"
TRIGGER_SPEECH_START = "speech_start"
TRIGGER_SPEECH_END = "speech_end"
TRIGGER_THINKING_START = "thinking_start"
TRIGGER_THINKING_DONE = "thinking_done"
TRIGGER_SPEAKING_START = "speaking_start"
TRIGGER_SPEAKING_DONE = "speaking_done"
TRIGGER_BARGE_IN = "barge_in"
TRIGGER_TIMEOUT = "timeout"
TRIGGER_CONFIRM = "confirm"
TRIGGER_CANCEL = "cancel"


# =============================================================================
# Conversation State
# =============================================================================


class ConversationState(Enum):
    """Conversation states."""
    
    IDLE = "idle"               # Waiting
    LISTENING = "listening"     # VAD active, user speaking
    THINKING = "thinking"       # LLM processing
    SPEAKING = "speaking"       # TTS playing
    CONFIRMING = "confirming"   # Waiting for confirmation
    
    def __str__(self) -> str:
        return self.value


# =============================================================================
# State Transition
# =============================================================================


@dataclass
class StateTransition:
    """Definition of a state transition."""
    
    from_state: ConversationState
    to_state: ConversationState
    trigger: str
    condition: Optional[Callable[[], bool]] = None
    
    def is_valid(self) -> bool:
        """Check if transition condition is met."""
        if self.condition is None:
            return True
        return self.condition()


# =============================================================================
# Conversation FSM
# =============================================================================


class ConversationFSM:
    """
    Finite State Machine for conversation flow.
    
    Manages state transitions and callbacks for:
    - Wakeword detection → LISTENING
    - Speech end → THINKING
    - LLM done → SPEAKING
    - TTS done → IDLE
    - Barge-in → interrupt and LISTENING
    """
    
    def __init__(self, event_bus: Optional[Any] = None):
        """
        Initialize FSM.
        
        Args:
            event_bus: Optional event bus for state change notifications
        """
        self._current_state = ConversationState.IDLE
        self._event_bus = event_bus
        
        # Callbacks
        self._on_enter_callbacks: Dict[ConversationState, List[Callable]] = {
            state: [] for state in ConversationState
        }
        self._on_exit_callbacks: Dict[ConversationState, List[Callable]] = {
            state: [] for state in ConversationState
        }
        
        # Transition history
        self._history: List[Dict[str, Any]] = []
        self._max_history = 100
        
        # Define valid transitions
        self._transitions = self._build_transitions()
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    def _build_transitions(self) -> Dict[str, List[StateTransition]]:
        """Build transition table."""
        transitions = [
            # From IDLE
            StateTransition(ConversationState.IDLE, ConversationState.LISTENING, TRIGGER_WAKEWORD),
            StateTransition(ConversationState.IDLE, ConversationState.LISTENING, TRIGGER_SPEECH_START),
            
            # From LISTENING
            StateTransition(ConversationState.LISTENING, ConversationState.THINKING, TRIGGER_SPEECH_END),
            StateTransition(ConversationState.LISTENING, ConversationState.IDLE, TRIGGER_TIMEOUT),
            
            # From THINKING
            StateTransition(ConversationState.THINKING, ConversationState.SPEAKING, TRIGGER_THINKING_DONE),
            StateTransition(ConversationState.THINKING, ConversationState.CONFIRMING, TRIGGER_CONFIRM),
            StateTransition(ConversationState.THINKING, ConversationState.IDLE, TRIGGER_TIMEOUT),
            
            # From SPEAKING
            StateTransition(ConversationState.SPEAKING, ConversationState.IDLE, TRIGGER_SPEAKING_DONE),
            StateTransition(ConversationState.SPEAKING, ConversationState.LISTENING, TRIGGER_BARGE_IN),
            
            # From CONFIRMING
            StateTransition(ConversationState.CONFIRMING, ConversationState.THINKING, TRIGGER_CONFIRM),
            StateTransition(ConversationState.CONFIRMING, ConversationState.IDLE, TRIGGER_CANCEL),
            StateTransition(ConversationState.CONFIRMING, ConversationState.IDLE, TRIGGER_TIMEOUT),
            StateTransition(ConversationState.CONFIRMING, ConversationState.LISTENING, TRIGGER_SPEECH_START),
        ]
        
        # Group by trigger
        result: Dict[str, List[StateTransition]] = {}
        for t in transitions:
            if t.trigger not in result:
                result[t.trigger] = []
            result[t.trigger].append(t)
        
        return result
    
    @property
    def current_state(self) -> ConversationState:
        """Get current state."""
        return self._current_state
    
    @property
    def is_idle(self) -> bool:
        """Check if in IDLE state."""
        return self._current_state == ConversationState.IDLE
    
    @property
    def is_listening(self) -> bool:
        """Check if in LISTENING state."""
        return self._current_state == ConversationState.LISTENING
    
    @property
    def is_thinking(self) -> bool:
        """Check if in THINKING state."""
        return self._current_state == ConversationState.THINKING
    
    @property
    def is_speaking(self) -> bool:
        """Check if in SPEAKING state."""
        return self._current_state == ConversationState.SPEAKING
    
    @property
    def is_active(self) -> bool:
        """Check if conversation is active (not IDLE)."""
        return self._current_state != ConversationState.IDLE
    
    def can_transition(self, trigger: str) -> bool:
        """Check if a transition is possible."""
        if trigger not in self._transitions:
            return False
        
        for t in self._transitions[trigger]:
            if t.from_state == self._current_state and t.is_valid():
                return True
        
        return False
    
    async def transition(self, trigger: str) -> bool:
        """
        Attempt a state transition.
        
        Args:
            trigger: Trigger name
            
        Returns:
            True if transition occurred, False otherwise
        """
        async with self._lock:
            if trigger not in self._transitions:
                logger.debug(f"Unknown trigger: {trigger}")
                return False
            
            # Find valid transition
            valid_transition = None
            for t in self._transitions[trigger]:
                if t.from_state == self._current_state and t.is_valid():
                    valid_transition = t
                    break
            
            if valid_transition is None:
                logger.debug(
                    f"Invalid transition: {self._current_state} --{trigger}--> ?"
                )
                return False
            
            # Execute transition
            old_state = self._current_state
            new_state = valid_transition.to_state
            
            # Exit callbacks
            await self._call_exit_callbacks(old_state)
            
            # Update state
            self._current_state = new_state
            
            # Record in history
            self._record_transition(old_state, new_state, trigger)
            
            # Enter callbacks
            await self._call_enter_callbacks(new_state)
            
            # Emit event
            if self._event_bus:
                await self._emit_state_change(old_state, new_state, trigger)
            
            logger.debug(f"Transition: {old_state} --{trigger}--> {new_state}")
            return True
    
    async def _call_enter_callbacks(self, state: ConversationState) -> None:
        """Call on_enter callbacks."""
        for callback in self._on_enter_callbacks[state]:
            try:
                result = callback(state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in on_enter callback: {e}")
    
    async def _call_exit_callbacks(self, state: ConversationState) -> None:
        """Call on_exit callbacks."""
        for callback in self._on_exit_callbacks[state]:
            try:
                result = callback(state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in on_exit callback: {e}")
    
    async def _emit_state_change(
        self,
        old_state: ConversationState,
        new_state: ConversationState,
        trigger: str
    ) -> None:
        """Emit state change event."""
        if self._event_bus and hasattr(self._event_bus, 'emit'):
            try:
                await self._event_bus.emit("conversation.state_changed", {
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "trigger": trigger,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.error(f"Error emitting state change: {e}")
    
    def _record_transition(
        self,
        old_state: ConversationState,
        new_state: ConversationState,
        trigger: str
    ) -> None:
        """Record transition in history."""
        self._history.append({
            "from": old_state.value,
            "to": new_state.value,
            "trigger": trigger,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Trim history
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
    
    def on_enter(self, state: ConversationState, callback: Callable) -> None:
        """Register callback for state entry."""
        self._on_enter_callbacks[state].append(callback)
    
    def on_exit(self, state: ConversationState, callback: Callable) -> None:
        """Register callback for state exit."""
        self._on_exit_callbacks[state].append(callback)
    
    def remove_on_enter(self, state: ConversationState, callback: Callable) -> bool:
        """Remove on_enter callback."""
        try:
            self._on_enter_callbacks[state].remove(callback)
            return True
        except ValueError:
            return False
    
    def remove_on_exit(self, state: ConversationState, callback: Callable) -> bool:
        """Remove on_exit callback."""
        try:
            self._on_exit_callbacks[state].remove(callback)
            return True
        except ValueError:
            return False
    
    def reset(self) -> None:
        """Reset FSM to IDLE state."""
        self._current_state = ConversationState.IDLE
        self._history.clear()
    
    def get_history(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get recent transition history."""
        return self._history[-n:]
    
    def get_valid_triggers(self) -> List[str]:
        """Get list of valid triggers from current state."""
        valid = []
        for trigger, transitions in self._transitions.items():
            for t in transitions:
                if t.from_state == self._current_state and t.is_valid():
                    valid.append(trigger)
                    break
        return valid


def create_conversation_fsm(event_bus: Optional[Any] = None) -> ConversationFSM:
    """Factory for creating conversation FSM."""
    return ConversationFSM(event_bus=event_bus)
