"""Voice session state machine (Issue #290).

Deterministic FSM for voice service:
  - ACTIVE_LISTEN: full ASR active (no wake word needed)
  - WAKE_ONLY: only wake word detection (low CPU)
  - IDLE_SLEEP: no audio processing (optional, battery save)

State transitions::

    Boot + LLM ready → ACTIVE_LISTEN (TTL: 90s)
    User speech      → reset TTL
    Silence timeout  → WAKE_ONLY
    Dismiss intent   → WAKE_ONLY
    Wake word        → ACTIVE_LISTEN
    IDLE enabled     → IDLE_SLEEP (after wake_only timeout)

Config env vars::

    BANTZ_ACTIVE_LISTEN_TTL_S=90
    BANTZ_SILENCE_TO_WAKE_S=30
    BANTZ_IDLE_SLEEP_ENABLED=false
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "VoiceState",
    "VoiceFSM",
    "FSMConfig",
    "StateTransition",
]


class VoiceState(Enum):
    """Voice session states."""

    ACTIVE_LISTEN = "active_listen"
    WAKE_ONLY = "wake_only"
    IDLE_SLEEP = "idle_sleep"


@dataclass
class StateTransition:
    """Record of a state transition."""

    from_state: VoiceState
    to_state: VoiceState
    trigger: str
    timestamp: float = 0.0


@dataclass
class FSMConfig:
    """FSM configuration.

    Attributes
    ----------
    active_listen_ttl:
        Seconds before ACTIVE_LISTEN → WAKE_ONLY (no speech).
    silence_threshold:
        Seconds of silence before transition.
    idle_sleep_enabled:
        Whether IDLE_SLEEP state is available.
    idle_sleep_timeout:
        Seconds in WAKE_ONLY before → IDLE_SLEEP.
    """

    active_listen_ttl: float = 90.0
    silence_threshold: float = 30.0
    idle_sleep_enabled: bool = False
    idle_sleep_timeout: float = 300.0

    @classmethod
    def from_env(cls) -> "FSMConfig":
        """Load config from environment variables."""
        def _float(name: str, default: float) -> float:
            raw = os.getenv(name, "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def _bool(name: str, default: bool) -> bool:
            raw = os.getenv(name, "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "on"}

        return cls(
            active_listen_ttl=_float("BANTZ_ACTIVE_LISTEN_TTL_S", 90.0),
            silence_threshold=_float("BANTZ_SILENCE_TO_WAKE_S", 30.0),
            idle_sleep_enabled=_bool("BANTZ_IDLE_SLEEP_ENABLED", False),
            idle_sleep_timeout=_float("BANTZ_IDLE_SLEEP_TIMEOUT_S", 300.0),
        )


class VoiceFSM:
    """Deterministic voice session state machine.

    Parameters
    ----------
    config:
        FSM configuration.
    clock:
        Optional clock function for testing. Defaults to time.monotonic.
    on_transition:
        Optional callback for state transitions.
    """

    def __init__(
        self,
        config: Optional[FSMConfig] = None,
        clock: Optional[Callable[[], float]] = None,
        on_transition: Optional[Callable[[StateTransition], None]] = None,
    ):
        self.config = config or FSMConfig()
        self._clock = clock or time.monotonic
        self._on_transition = on_transition

        self._state = VoiceState.WAKE_ONLY
        self._last_activity = self._clock()
        self._state_entered_at = self._clock()
        self._history: List[StateTransition] = []
        self._lock = threading.Lock()

    @property
    def state(self) -> VoiceState:
        """Current state (thread-safe)."""
        with self._lock:
            return self._state

    @property
    def last_activity(self) -> float:
        """Timestamp of last user activity (thread-safe)."""
        with self._lock:
            return self._last_activity

    @property
    def history(self) -> List[StateTransition]:
        """State transition history (thread-safe)."""
        with self._lock:
            return list(self._history)

    def _transition(self, new_state: VoiceState, trigger: str) -> None:
        """Execute a state transition (caller must hold _lock)."""
        if new_state == self._state:
            return

        old = self._state
        now = self._clock()
        transition = StateTransition(
            from_state=old,
            to_state=new_state,
            trigger=trigger,
            timestamp=now,
        )

        logger.debug(
            "[fsm] %s → %s (trigger: %s)",
            old.value, new_state.value, trigger,
        )

        self._state = new_state
        self._state_entered_at = now
        self._history.append(transition)

        if self._on_transition:
            self._on_transition(transition)

    # ── Event handlers (thread-safe) ──────────────────────────────

    def on_boot_ready(self) -> None:
        """LLM warmup complete — enter active listening."""
        with self._lock:
            self._transition(VoiceState.ACTIVE_LISTEN, "boot_ready")
            self._last_activity = self._clock()

    def on_user_speech(self) -> None:
        """User started speaking — reset TTL."""
        with self._lock:
            self._last_activity = self._clock()

            if self._state == VoiceState.WAKE_ONLY:
                # Should not happen without wake word, but handle gracefully
                logger.debug("[fsm] speech in WAKE_ONLY — ignoring (need wake word)")
                return

            if self._state == VoiceState.IDLE_SLEEP:
                self._transition(VoiceState.ACTIVE_LISTEN, "speech_from_idle")
                return

            # Already in ACTIVE_LISTEN — just reset timer
            logger.debug("[fsm] speech in ACTIVE_LISTEN — TTL reset")

    def on_silence_timeout(self) -> None:
        """Silence detected — transition to wake-only."""
        with self._lock:
            if self._state == VoiceState.ACTIVE_LISTEN:
                self._transition(VoiceState.WAKE_ONLY, "silence_timeout")

    def on_dismiss_intent(self) -> None:
        """User said goodbye — transition to wake-only."""
        with self._lock:
            if self._state == VoiceState.ACTIVE_LISTEN:
                self._transition(VoiceState.WAKE_ONLY, "dismiss_intent")

    def on_wake_word(self) -> None:
        """Wake word detected — enter active listening."""
        with self._lock:
            self._transition(VoiceState.ACTIVE_LISTEN, "wake_word")
            self._last_activity = self._clock()

    def tick(self) -> None:
        """Timer check — call periodically to enforce timeouts (thread-safe).

        Checks if current state has exceeded its TTL and transitions
        accordingly.
        """
        with self._lock:
            now = self._clock()

            if self._state == VoiceState.ACTIVE_LISTEN:
                elapsed = now - self._last_activity
                if elapsed >= self.config.active_listen_ttl:
                    self._transition(VoiceState.WAKE_ONLY, "silence_timeout")

            elif self._state == VoiceState.WAKE_ONLY and self.config.idle_sleep_enabled:
                elapsed = now - self._state_entered_at
                # Guard: don't sleep if there was recent activity (e.g.
                # user speaking without a wake word match).
                since_activity = now - self._last_activity
                if elapsed >= self.config.idle_sleep_timeout and since_activity >= self.config.idle_sleep_timeout:
                    self._transition(VoiceState.IDLE_SLEEP, "idle_timeout")

    def time_until_timeout(self) -> Optional[float]:
        """Seconds until next timeout, or None if no timeout pending (thread-safe)."""
        with self._lock:
            now = self._clock()

            if self._state == VoiceState.ACTIVE_LISTEN:
                remaining = self.config.active_listen_ttl - (now - self._last_activity)
                return max(0.0, remaining)

            if self._state == VoiceState.WAKE_ONLY and self.config.idle_sleep_enabled:
                remaining = self.config.idle_sleep_timeout - (now - self._state_entered_at)
                return max(0.0, remaining)

            return None
