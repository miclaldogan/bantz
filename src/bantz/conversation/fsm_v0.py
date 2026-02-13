"""Formal Conversation FSM v0 (Issue #455).

Extends the original FSM (Issue #38) with additional states required for
the full agent lifecycle:

States
------
IDLE → LISTENING → PLANNING → EXECUTING → CONFIRMING → RESPONDING → IDLE
                                   ↓              ↓
                                 ERROR ←──── CANCELLED

Events (triggers)
-----------------
user_input, input_complete, plan_ready, no_tools, confirmation_required,
tools_complete, user_confirmed, user_denied, response_delivered,
error, user_cancel, error_handled, reset

Features:

- Strict transition table — invalid transitions are logged and ignored
- ``can_transition`` / ``get_allowed_events`` for UI state exposure
- Transition history with timestamps
- Configurable timeout on EXECUTING state (default 60 s)
- Callback hooks for state entry/exit
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "FSMState",
    "FSMEvent",
    "TransitionRecord",
    "ConversationFSMv0",
]


# ── States ────────────────────────────────────────────────────────────

class FSMState(Enum):
    """Conversation lifecycle states."""

    IDLE = "idle"
    LISTENING = "listening"
    PLANNING = "planning"
    EXECUTING = "executing"
    CONFIRMING = "confirming"
    RESPONDING = "responding"
    ERROR = "error"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


# ── Events ────────────────────────────────────────────────────────────

class FSMEvent(Enum):
    """Events that trigger state transitions."""

    USER_INPUT = "user_input"
    INPUT_COMPLETE = "input_complete"
    PLAN_READY = "plan_ready"
    NO_TOOLS = "no_tools"
    CONFIRMATION_REQUIRED = "confirmation_required"
    TOOLS_COMPLETE = "tools_complete"
    USER_CONFIRMED = "user_confirmed"
    USER_DENIED = "user_denied"
    RESPONSE_DELIVERED = "response_delivered"
    ERROR = "error"
    USER_CANCEL = "user_cancel"
    ERROR_HANDLED = "error_handled"
    RESET = "reset"

    def __str__(self) -> str:
        return self.value


# ── Transition table ──────────────────────────────────────────────────

# (current_state, event) → next_state
_TRANSITIONS: Dict[tuple[FSMState, FSMEvent], FSMState] = {
    # Happy path
    (FSMState.IDLE, FSMEvent.USER_INPUT): FSMState.LISTENING,
    (FSMState.LISTENING, FSMEvent.INPUT_COMPLETE): FSMState.PLANNING,
    (FSMState.PLANNING, FSMEvent.PLAN_READY): FSMState.EXECUTING,
    (FSMState.PLANNING, FSMEvent.NO_TOOLS): FSMState.RESPONDING,
    (FSMState.EXECUTING, FSMEvent.CONFIRMATION_REQUIRED): FSMState.CONFIRMING,
    (FSMState.EXECUTING, FSMEvent.TOOLS_COMPLETE): FSMState.RESPONDING,
    (FSMState.CONFIRMING, FSMEvent.USER_CONFIRMED): FSMState.EXECUTING,
    (FSMState.CONFIRMING, FSMEvent.USER_DENIED): FSMState.CANCELLED,
    (FSMState.RESPONDING, FSMEvent.RESPONSE_DELIVERED): FSMState.IDLE,
    # Error / cancel from any state (added dynamically below)
    (FSMState.ERROR, FSMEvent.ERROR_HANDLED): FSMState.IDLE,
    (FSMState.CANCELLED, FSMEvent.RESET): FSMState.IDLE,
}

# ANY state → ERROR on error, ANY state → CANCELLED on user_cancel
for _state in FSMState:
    if _state not in (FSMState.ERROR, FSMState.CANCELLED):
        _TRANSITIONS[(
            _state, FSMEvent.ERROR
        )] = FSMState.ERROR
        _TRANSITIONS[(
            _state, FSMEvent.USER_CANCEL
        )] = FSMState.CANCELLED


# ── Transition record ─────────────────────────────────────────────────

@dataclass
class TransitionRecord:
    """Log entry for a state transition."""

    from_state: FSMState
    to_state: FSMState
    event: FSMEvent
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── FSM ───────────────────────────────────────────────────────────────

StateCallback = Callable[[FSMState, FSMState, FSMEvent], None]


class ConversationFSMv0:
    """Formal conversation FSM with strict transition validation.

    Parameters
    ----------
    initial_state:
        Starting state (default ``IDLE``).
    executing_timeout:
        Seconds before EXECUTING auto-transitions to ERROR (default 60).
    """

    def __init__(
        self,
        initial_state: FSMState = FSMState.IDLE,
        executing_timeout: float = 60.0,
    ) -> None:
        self._state = initial_state
        self._executing_timeout = executing_timeout
        self._executing_entered: Optional[float] = None
        self._history: List[TransitionRecord] = []
        self._on_enter: Dict[FSMState, List[StateCallback]] = {}
        self._on_exit: Dict[FSMState, List[StateCallback]] = {}

    # ── properties ────────────────────────────────────────────────────

    @property
    def state(self) -> FSMState:
        """Current FSM state."""
        self._check_executing_timeout()
        return self._state

    @property
    def history(self) -> List[TransitionRecord]:
        """Full transition history."""
        return list(self._history)

    # ── transition API ────────────────────────────────────────────────

    def transition(self, event: FSMEvent | str, **metadata: Any) -> FSMState:
        """Attempt a state transition.

        If the transition is not valid, it is logged and the current
        state is returned unchanged.

        Parameters
        ----------
        event:
            The event to fire.
        **metadata:
            Extra context stored in the :class:`TransitionRecord`.

        Returns
        -------
        FSMState
            The new state after the transition (or the same state if invalid).
        """
        if isinstance(event, str):
            event = FSMEvent(event)

        self._check_executing_timeout()

        key = (self._state, event)
        next_state = _TRANSITIONS.get(key)

        if next_state is None:
            logger.warning(
                "Invalid transition: %s + %s (ignored)",
                self._state, event,
            )
            return self._state

        prev = self._state

        # Fire exit callbacks
        for cb in self._on_exit.get(prev, []):
            try:
                cb(prev, next_state, event)
            except Exception:
                logger.exception("on_exit callback error")

        self._state = next_state

        # Track EXECUTING entry time for timeout
        if next_state == FSMState.EXECUTING:
            self._executing_entered = time.monotonic()
        else:
            self._executing_entered = None

        # Record history
        self._history.append(TransitionRecord(
            from_state=prev,
            to_state=next_state,
            event=event,
            metadata=metadata,
        ))

        logger.info("FSM: %s → %s (event=%s)", prev, next_state, event)

        # Fire enter callbacks
        for cb in self._on_enter.get(next_state, []):
            try:
                cb(prev, next_state, event)
            except Exception:
                logger.exception("on_enter callback error")

        return next_state

    def can_transition(self, event: FSMEvent | str) -> bool:
        """Check whether *event* is valid from the current state."""
        if isinstance(event, str):
            event = FSMEvent(event)
        self._check_executing_timeout()
        return (self._state, event) in _TRANSITIONS

    def get_allowed_events(self) -> List[FSMEvent]:
        """Return all events valid from the current state."""
        self._check_executing_timeout()
        return [
            ev for (st, ev) in _TRANSITIONS
            if st == self._state
        ]

    def reset(self) -> None:
        """Force-reset to IDLE (clears history)."""
        self._state = FSMState.IDLE
        self._executing_entered = None
        self._history.clear()

    # ── callbacks ─────────────────────────────────────────────────────

    def on_enter(self, state: FSMState, callback: StateCallback) -> None:
        """Register a callback for entering *state*."""
        self._on_enter.setdefault(state, []).append(callback)

    def on_exit(self, state: FSMState, callback: StateCallback) -> None:
        """Register a callback for exiting *state*."""
        self._on_exit.setdefault(state, []).append(callback)

    # ── timeout ───────────────────────────────────────────────────────

    def _check_executing_timeout(self) -> None:
        """Auto-transition EXECUTING → ERROR if timeout exceeded."""
        if (
            self._state == FSMState.EXECUTING
            and self._executing_entered is not None
            and (time.monotonic() - self._executing_entered) > self._executing_timeout
        ):
            logger.warning("EXECUTING timeout (%.0fs) — transitioning to ERROR", self._executing_timeout)
            prev = self._state
            self._state = FSMState.ERROR
            self._executing_entered = None
            self._history.append(TransitionRecord(
                from_state=prev,
                to_state=FSMState.ERROR,
                event=FSMEvent.ERROR,
                metadata={"reason": "executing_timeout"},
            ))
