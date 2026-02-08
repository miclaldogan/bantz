"""ConversationFSM ↔ OrchestratorLoop integration (Issue #522).

Bridges the async ConversationFSM with the sync OrchestratorLoop.process_turn(),
providing automatic state transitions and barge-in detection.

Flow per turn::

    process_turn() called
      → THINKING  (planning + tool execution)
      → SPEAKING  (finalization done, response ready)
      → IDLE      (turn complete)

Barge-in::

    If FSM is in SPEAKING and a new process_turn() arrives,
    the bridge fires barge_in → LISTENING → THINKING automatically.

EventBus integration::

    Every transition publishes ``fsm.state_changed`` with
    old_state, new_state, trigger, turn_number.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "FSMBridge",
    "FSMTransitionRecord",
]


# ── Transition record ────────────────────────────────────────

@dataclass
class FSMTransitionRecord:
    """Record of a single FSM state transition."""

    turn_number: int = 0
    old_state: str = ""
    new_state: str = ""
    trigger: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_trace_line(self) -> str:
        return (
            f"[fsm] {self.old_state} → {self.new_state} "
            f"trigger={self.trigger} turn={self.turn_number}"
        )


# ── FSM Bridge ───────────────────────────────────────────────

class FSMBridge:
    """Sync bridge between async ConversationFSM and OrchestratorLoop.

    Parameters
    ----------
    fsm :
        The ConversationFSM instance. If ``None``, all operations are no-ops
        (graceful degradation for envs without voice/FSM).
    event_bus :
        EventBus to publish ``fsm.state_changed`` events.
    debug :
        Whether to emit debug log lines for each transition.
    """

    def __init__(
        self,
        fsm: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        *,
        debug: bool = False,
    ) -> None:
        self._fsm = fsm
        self._event_bus = event_bus
        self._debug = debug
        self._records: List[FSMTransitionRecord] = []
        self._current_turn: int = 0

        # Resolve or create an event loop for running async FSM transitions
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Helpers ───────────────────────────────────────────────

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create an event loop for sync→async bridging."""
        if self._loop is not None and not self._loop.is_closed():
            return self._loop
        try:
            self._loop = asyncio.get_event_loop()
            if self._loop.is_closed():
                raise RuntimeError("closed")
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def _run_transition(self, trigger: str) -> bool:
        """Run an async FSM transition synchronously.

        Returns True if transition succeeded, False otherwise.
        """
        if self._fsm is None:
            return False
        try:
            loop = self._get_loop()
            if loop.is_running():
                # Already inside an async context — schedule as task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(self._run_in_new_loop, trigger)
                    return future.result(timeout=2.0)
            else:
                return loop.run_until_complete(self._fsm.transition(trigger))
        except Exception as e:
            logger.warning("[fsm-bridge] Transition failed: trigger=%s err=%s", trigger, e)
            return False

    @staticmethod
    def _run_in_new_loop_static(fsm: Any, trigger: str) -> bool:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fsm.transition(trigger))
        finally:
            loop.close()

    def _run_in_new_loop(self, trigger: str) -> bool:
        return self._run_in_new_loop_static(self._fsm, trigger)

    def _record(self, old: str, new: str, trigger: str) -> FSMTransitionRecord:
        rec = FSMTransitionRecord(
            turn_number=self._current_turn,
            old_state=old,
            new_state=new,
            trigger=trigger,
        )
        self._records.append(rec)
        if self._debug:
            logger.debug(rec.to_trace_line())
        if self._event_bus is not None:
            self._event_bus.publish("fsm.state_changed", {
                "old_state": old,
                "new_state": new,
                "trigger": trigger,
                "turn_number": self._current_turn,
            })
        return rec

    @property
    def current_state(self) -> str:
        """Current FSM state as a string (or 'unknown')."""
        if self._fsm is None:
            return "unknown"
        return str(self._fsm.current_state)

    @property
    def records(self) -> List[FSMTransitionRecord]:
        return list(self._records)

    @property
    def last(self) -> Optional[FSMTransitionRecord]:
        return self._records[-1] if self._records else None

    # ── Turn lifecycle ────────────────────────────────────────

    def on_turn_start(self, turn_number: int) -> Optional[FSMTransitionRecord]:
        """Call at the start of process_turn().

        Transitions:
        - IDLE → THINKING (normal)
        - SPEAKING → LISTENING → THINKING (barge-in)
        """
        self._current_turn = turn_number

        if self._fsm is None:
            return None

        old = str(self._fsm.current_state)

        # Barge-in: if still speaking when new turn starts
        if old == "speaking":
            self._run_transition("barge_in")       # SPEAKING → LISTENING
            mid = str(self._fsm.current_state)
            self._record(old, mid, "barge_in")

            self._run_transition("speech_end")     # LISTENING → THINKING
            new = str(self._fsm.current_state)
            return self._record(mid, new, "speech_end")

        # Normal: IDLE → LISTENING → THINKING
        if old == "idle":
            self._run_transition("speech_start")   # IDLE → LISTENING
            mid = str(self._fsm.current_state)
            self._record(old, mid, "speech_start")

            self._run_transition("speech_end")     # LISTENING → THINKING
            new = str(self._fsm.current_state)
            return self._record(mid, new, "speech_end")

        return None

    def on_finalization_done(self) -> Optional[FSMTransitionRecord]:
        """Call after finalization phase completes (response ready).

        Transitions: THINKING → SPEAKING
        """
        if self._fsm is None:
            return None

        old = str(self._fsm.current_state)
        if old != "thinking":
            return None

        self._run_transition("thinking_done")  # THINKING → SPEAKING
        new = str(self._fsm.current_state)
        return self._record(old, new, "thinking_done")

    def on_turn_end(self) -> Optional[FSMTransitionRecord]:
        """Call at the end of process_turn().

        Transitions: SPEAKING → IDLE
        """
        if self._fsm is None:
            return None

        old = str(self._fsm.current_state)
        if old != "speaking":
            return None

        self._run_transition("speaking_done")  # SPEAKING → IDLE
        new = str(self._fsm.current_state)
        return self._record(old, new, "speaking_done")

    def on_confirmation_needed(self) -> Optional[FSMTransitionRecord]:
        """Call when a confirmation is required.

        Transitions: THINKING → CONFIRMING
        """
        if self._fsm is None:
            return None

        old = str(self._fsm.current_state)
        if old != "thinking":
            return None

        self._run_transition("confirm")  # THINKING → CONFIRMING
        new = str(self._fsm.current_state)
        return self._record(old, new, "confirm")

    # ── Utility ───────────────────────────────────────────────

    def clear(self) -> None:
        """Reset records (not the FSM itself)."""
        self._records.clear()
        self._current_turn = 0

    def is_barge_in(self) -> bool:
        """Whether the current turn started via barge-in."""
        for rec in self._records:
            if rec.turn_number == self._current_turn and rec.trigger == "barge_in":
                return True
        return False
