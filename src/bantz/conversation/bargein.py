"""
Barge-in Handler for V2-6 (Issue #38, Issue #428).

Handles user interruption during TTS playback:
- Stops TTS when user speaks
- Transitions FSM to LISTENING
- Configurable thresholds for interrupt detection
- CancellationToken for in-flight tool execution (Issue #428)
- Turn-ID isolation to prevent cross-turn result leakage (Issue #428)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


# =============================================================================
# CancellationToken (Issue #428)
# =============================================================================


class CancellationToken:
    """
    Cooperative cancellation token for long-running tool executions.

    Usage::

        token = CancellationToken()
        # Start a tool
        if token.is_cancelled:
            return  # exit early
        # ... do work ...
        token.cancel()  # trigger from barge-in
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Signal cancellation."""
        self._cancelled = True
        self._event.set()

    def reset(self) -> None:
        """Reset to non-cancelled state."""
        self._cancelled = False
        self._event.clear()

    async def wait(self, timeout: float | None = None) -> bool:
        """Wait until cancelled. Returns True if cancelled, False on timeout."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# =============================================================================
# Turn Context (Issue #428)
# =============================================================================


@dataclass
class TurnContext:
    """
    Associates a unique turn_id with each user utterance.

    Tool results tagged with the originating turn_id so that barge-in
    can discard stale results from previous turns.
    """

    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    _tool_results: list[dict[str, Any]] = field(default_factory=list)

    def add_tool_result(self, result: dict[str, Any]) -> None:
        """Attach a tool result to this turn."""
        result["_turn_id"] = self.turn_id
        self._tool_results.append(result)

    @property
    def tool_results(self) -> list[dict[str, Any]]:
        return list(self._tool_results)

    @property
    def is_cancelled(self) -> bool:
        return self.cancellation_token.is_cancelled

    def cancel(self) -> None:
        """Cancel all in-flight work for this turn."""
        self.cancellation_token.cancel()


# =============================================================================
# Barge-in Action
# =============================================================================


class BargeInAction(Enum):
    """Actions that can be taken on barge-in."""
    
    STOP_TTS = "stop_tts"           # Just stop TTS
    STOP_AND_LISTEN = "stop_and_listen"  # Stop TTS and start listening
    QUEUE_RESPONSE = "queue_response"     # Queue user speech for later
    IGNORE = "ignore"               # Ignore the interruption


# =============================================================================
# Barge-in Event
# =============================================================================


@dataclass
class BargeInEvent:
    """Event representing a barge-in attempt."""
    
    timestamp: datetime = field(default_factory=datetime.now)
    speech_snippet: Optional[str] = None
    speech_volume: float = 0.0
    speech_duration_ms: float = 0.0
    tts_was_playing: bool = True
    action_taken: BargeInAction = BargeInAction.STOP_AND_LISTEN
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "speech_snippet": self.speech_snippet,
            "speech_volume": self.speech_volume,
            "speech_duration_ms": self.speech_duration_ms,
            "tts_was_playing": self.tts_was_playing,
            "action_taken": self.action_taken.value,
        }


# =============================================================================
# Protocol Interfaces
# =============================================================================


class TTSEngine(Protocol):
    """Protocol for TTS engine."""
    
    def is_playing(self) -> bool:
        """Check if TTS is playing."""
        ...
    
    async def stop(self) -> None:
        """Stop TTS playback."""
        ...


class ConversationFSMProtocol(Protocol):
    """Protocol for conversation FSM."""
    
    @property
    def is_speaking(self) -> bool:
        """Check if in SPEAKING state."""
        ...
    
    async def transition(self, trigger: str) -> bool:
        """Attempt a state transition."""
        ...


# =============================================================================
# Barge-in Handler
# =============================================================================


class BargeInHandler:
    """
    Handles barge-in (user interruption during TTS).
    
    When user speaks while TTS is playing:
    1. Detect speech above threshold
    2. Stop TTS playback
    3. Transition FSM to LISTENING
    4. Log the event
    """
    
    # Default thresholds
    INTERRUPT_THRESHOLD = 0.5  # Volume threshold (0-1)
    MIN_SPEECH_DURATION_MS = 200  # Minimum speech length to interrupt
    
    def __init__(
        self,
        tts: Optional[TTSEngine] = None,
        fsm: Optional[ConversationFSMProtocol] = None,
        interrupt_threshold: float = 0.5,
        min_speech_duration_ms: float = 200,
        event_bus: Optional[Any] = None
    ):
        """
        Initialize barge-in handler.
        
        Args:
            tts: TTS engine for stopping playback
            fsm: Conversation FSM for state transitions
            interrupt_threshold: Volume threshold for interruption
            min_speech_duration_ms: Minimum speech duration to trigger interrupt
            event_bus: Optional event bus for logging
        """
        self._tts = tts
        self._fsm = fsm
        self._interrupt_threshold = interrupt_threshold
        self._min_speech_duration_ms = min_speech_duration_ms
        self._event_bus = event_bus
        
        # Active turn tracking (Issue #428)
        self._active_turn: Optional[TurnContext] = None
        
        # Event history
        self._events: list[BargeInEvent] = []
        self._max_events = 50
        
        # Statistics
        self._total_interrupts = 0
        self._ignored_interrupts = 0
        self._cancelled_turns = 0
    
    def should_interrupt(
        self,
        speech_volume: float,
        speech_duration_ms: float = 0.0
    ) -> bool:
        """
        Check if speech should trigger an interrupt.
        
        Args:
            speech_volume: Current speech volume (0-1)
            speech_duration_ms: Duration of speech in milliseconds
            
        Returns:
            True if should interrupt, False otherwise
        """
        # Check volume threshold
        if speech_volume < self._interrupt_threshold:
            return False
        
        # Check minimum duration
        if speech_duration_ms < self._min_speech_duration_ms:
            return False
        
        return True
    
    async def handle(self, event: BargeInEvent) -> BargeInAction:
        """
        Handle a barge-in event.
        
        When accepted, cancels the active turn's tool executions (Issue #428)
        and logs the cancellation.
        
        Args:
            event: The barge-in event
            
        Returns:
            The action taken
        """
        # Check if we should interrupt
        if not self.should_interrupt(event.speech_volume, event.speech_duration_ms):
            event.action_taken = BargeInAction.IGNORE
            self._ignored_interrupts += 1
            self._record_event(event)
            logger.debug("Barge-in ignored: below threshold")
            return BargeInAction.IGNORE
        
        # Check if TTS is actually playing
        if self._tts and not self._tts.is_playing():
            event.tts_was_playing = False
            event.action_taken = BargeInAction.IGNORE
            self._record_event(event)
            logger.debug("Barge-in ignored: TTS not playing")
            return BargeInAction.IGNORE
        
        # ── Issue #428: Cancel active turn's tool executions ──
        if self._active_turn and not self._active_turn.is_cancelled:
            old_turn_id = self._active_turn.turn_id
            self._active_turn.cancel()
            self._cancelled_turns += 1
            logger.info(
                "Barge-in: cancelled active turn %s tool executions",
                old_turn_id,
            )
        
        # Stop TTS
        if self._tts:
            try:
                await self._tts.stop()
                logger.debug("TTS stopped due to barge-in")
            except Exception as e:
                logger.error(f"Error stopping TTS: {e}")
        
        # Transition FSM to LISTENING
        if self._fsm:
            try:
                from bantz.conversation.fsm import TRIGGER_BARGE_IN
                success = await self._fsm.transition(TRIGGER_BARGE_IN)
                if success:
                    event.action_taken = BargeInAction.STOP_AND_LISTEN
                    logger.debug("FSM transitioned to LISTENING")
                else:
                    event.action_taken = BargeInAction.STOP_TTS
                    logger.debug("FSM transition failed, just stopped TTS")
            except Exception as e:
                logger.error(f"Error transitioning FSM: {e}")
                event.action_taken = BargeInAction.STOP_TTS
        else:
            event.action_taken = BargeInAction.STOP_TTS
        
        # Record event
        self._total_interrupts += 1
        self._record_event(event)
        
        # Emit event
        await self._emit_barge_in(event)
        
        return event.action_taken
    
    def _record_event(self, event: BargeInEvent) -> None:
        """Record event in history."""
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
    
    async def _emit_barge_in(self, event: BargeInEvent) -> None:
        """Emit barge-in event."""
        if self._event_bus and hasattr(self._event_bus, 'emit'):
            try:
                await self._event_bus.emit("conversation.barge_in", event.to_dict())
            except Exception as e:
                logger.error(f"Error emitting barge-in event: {e}")
    
    # ── Turn management (Issue #428) ────────────────────────────

    def start_turn(self) -> TurnContext:
        """
        Create a new TurnContext for the current utterance.

        If a previous turn is still active, it is cancelled first.
        """
        if self._active_turn and not self._active_turn.is_cancelled:
            self._active_turn.cancel()
            self._cancelled_turns += 1
        self._active_turn = TurnContext()
        logger.debug("Started new turn %s", self._active_turn.turn_id)
        return self._active_turn

    @property
    def active_turn(self) -> Optional[TurnContext]:
        return self._active_turn

    def finish_turn(self) -> None:
        """Mark the current turn as complete (not cancelled)."""
        self._active_turn = None

    def is_turn_valid(self, turn_id: str) -> bool:
        """Check if *turn_id* matches the active (non-cancelled) turn."""
        if self._active_turn is None:
            return False
        return (
            self._active_turn.turn_id == turn_id
            and not self._active_turn.is_cancelled
        )

    def get_events(self, n: int = 10) -> list[BargeInEvent]:
        """Get recent barge-in events."""
        return self._events[-n:]
    
    def get_stats(self) -> dict:
        """Get barge-in statistics."""
        return {
            "total_interrupts": self._total_interrupts,
            "ignored_interrupts": self._ignored_interrupts,
            "cancelled_turns": self._cancelled_turns,
            "interrupt_rate": (
                self._total_interrupts / (self._total_interrupts + self._ignored_interrupts)
                if (self._total_interrupts + self._ignored_interrupts) > 0
                else 0.0
            ),
            "threshold": self._interrupt_threshold,
            "min_duration_ms": self._min_speech_duration_ms,
        }
    
    def set_threshold(self, threshold: float) -> None:
        """Set interrupt threshold."""
        self._interrupt_threshold = max(0.0, min(1.0, threshold))
    
    def set_min_duration(self, duration_ms: float) -> None:
        """Set minimum speech duration."""
        self._min_speech_duration_ms = max(0.0, duration_ms)
    
    def clear_history(self) -> int:
        """Clear event history."""
        count = len(self._events)
        self._events.clear()
        return count


def create_barge_in_handler(
    tts: Optional[TTSEngine] = None,
    fsm: Optional[ConversationFSMProtocol] = None,
    **kwargs
) -> BargeInHandler:
    """Factory for creating barge-in handler."""
    return BargeInHandler(tts=tts, fsm=fsm, **kwargs)
