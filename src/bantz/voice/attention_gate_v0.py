"""FSM-driven Voice Attention Gate v0 (Issue #457).

Maps conversation FSM states to voice listening modes and filters
audio events accordingly.

Modes
-----
- **FULL_LISTEN** — process everything (idle / listening / confirming)
- **WAKE_ONLY** — only wakeword triggers (thinking / planning)
- **COMMAND_ONLY** — wakeword + interrupt keywords (executing)
- **MUTED** — ignore all audio (TTS speaking)

The gate auto-transitions when:
- FSM state changes → mode from ``STATE_ATTENTION_MAP``
- TTS starts → MUTED
- TTS ends → restore previous mode
- Wakeword in COMMAND_ONLY → temporarily open to FULL_LISTEN

See Also
--------
- ``src/bantz/voice/attention_gate.py`` — legacy gate (job-based)
- ``src/bantz/conversation/fsm_v0.py`` — formal FSM (Issue #455)
- ``src/bantz/core/interrupt_controller.py`` — interrupt keywords (Issue #456)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "AttentionMode",
    "AudioEvent",
    "AttentionGateV0",
    "STATE_ATTENTION_MAP",
]


# ── Modes ─────────────────────────────────────────────────────────────

class AttentionMode(Enum):
    """Voice listening modes."""

    FULL_LISTEN = "full_listen"    # Process everything
    WAKE_ONLY = "wake_only"        # Only wakeword
    COMMAND_ONLY = "command_only"   # Wakeword + interrupt keywords
    MUTED = "muted"                # Ignore all audio

    def __str__(self) -> str:
        return self.value


# ── Audio event ───────────────────────────────────────────────────────

@dataclass
class AudioEvent:
    """Represents an incoming audio event for gate filtering."""

    is_wakeword: bool = False
    is_interrupt_keyword: bool = False
    is_speech: bool = False
    text: str = ""
    timestamp: float = field(default_factory=time.monotonic)


# ── FSM → Mode mapping ───────────────────────────────────────────────

STATE_ATTENTION_MAP: Dict[str, AttentionMode] = {
    "idle": AttentionMode.FULL_LISTEN,
    "listening": AttentionMode.FULL_LISTEN,
    "thinking": AttentionMode.WAKE_ONLY,
    "planning": AttentionMode.WAKE_ONLY,
    "executing": AttentionMode.COMMAND_ONLY,
    "speaking": AttentionMode.MUTED,
    "responding": AttentionMode.MUTED,
    "confirming": AttentionMode.FULL_LISTEN,
    "error": AttentionMode.FULL_LISTEN,
    "cancelled": AttentionMode.FULL_LISTEN,
}

# ── Transition log entry ─────────────────────────────────────────────

@dataclass
class ModeTransition:
    """Record of an attention mode change."""

    old_mode: AttentionMode
    new_mode: AttentionMode
    reason: str              # "fsm_state_change", "tts_start", "tts_end", "wakeword_override"
    timestamp: float = field(default_factory=time.monotonic)


# ── Gate ──────────────────────────────────────────────────────────────

ModeCallback = Callable[[AttentionMode, AttentionMode, str], None]


class AttentionGateV0:
    """FSM-driven attention gate that filters audio events.

    Parameters
    ----------
    initial_mode:
        Starting mode (default ``FULL_LISTEN``).
    wakeword_override_duration:
        Seconds to keep gate open after wakeword in COMMAND_ONLY (default 10).
    max_history:
        Max mode transitions to retain.
    """

    def __init__(
        self,
        initial_mode: AttentionMode = AttentionMode.FULL_LISTEN,
        wakeword_override_duration: float = 10.0,
        max_history: int = 500,
    ) -> None:
        self._mode = initial_mode
        self._pre_mute_mode: Optional[AttentionMode] = None
        self._wakeword_override_until: Optional[float] = None
        self._wakeword_override_duration = wakeword_override_duration
        self._transitions: List[ModeTransition] = []
        self._max_history = max_history
        self._callbacks: List[ModeCallback] = []

    # ── mode property ─────────────────────────────────────────────────

    @property
    def mode(self) -> AttentionMode:
        """Current attention mode (accounts for wakeword override expiry)."""
        self._expire_wakeword_override()
        return self._mode

    def get_mode(self) -> AttentionMode:
        """Alias for mode property."""
        return self.mode

    # ── set mode ──────────────────────────────────────────────────────

    def set_mode(self, mode: AttentionMode, *, reason: str = "manual") -> None:
        """Explicitly set the attention mode."""
        old = self._mode
        if old == mode:
            return
        self._mode = mode
        self._record(old, mode, reason)

    # ── FSM callback ──────────────────────────────────────────────────

    def on_state_change(self, old_state: str, new_state: str) -> None:
        """Called when conversation FSM transitions.

        Maps *new_state* through :data:`STATE_ATTENTION_MAP` and updates mode.
        """
        target = STATE_ATTENTION_MAP.get(new_state)
        if target is None:
            logger.warning("Unknown FSM state for attention mapping: %s", new_state)
            return

        old = self._mode
        if old == target:
            return

        self._mode = target
        self._wakeword_override_until = None  # clear any override
        self._record(old, target, f"fsm:{old_state}->{new_state}")

    # ── TTS mute / unmute ─────────────────────────────────────────────

    def on_tts_start(self) -> None:
        """Mute gate while TTS is speaking."""
        if self._mode == AttentionMode.MUTED:
            return
        self._pre_mute_mode = self._mode
        old = self._mode
        self._mode = AttentionMode.MUTED
        self._record(old, AttentionMode.MUTED, "tts_start")

    def on_tts_end(self) -> None:
        """Restore mode after TTS finishes."""
        if self._mode != AttentionMode.MUTED:
            return
        restore = self._pre_mute_mode or AttentionMode.FULL_LISTEN
        self._pre_mute_mode = None
        old = self._mode
        self._mode = restore
        self._record(old, restore, "tts_end")

    # ── should_process ────────────────────────────────────────────────

    def should_process(self, event: AudioEvent) -> bool:
        """Decide whether an audio event should be processed.

        Rules per mode:
        - FULL_LISTEN → always True
        - WAKE_ONLY → True only if wakeword
        - COMMAND_ONLY → True if wakeword or interrupt keyword
        - MUTED → always False
        """
        current = self.mode  # triggers override expiry check

        if current == AttentionMode.FULL_LISTEN:
            return True
        if current == AttentionMode.MUTED:
            return False
        if current == AttentionMode.WAKE_ONLY:
            return event.is_wakeword
        if current == AttentionMode.COMMAND_ONLY:
            if event.is_wakeword:
                self._activate_wakeword_override()
                return True
            return event.is_interrupt_keyword

        return False  # pragma: no cover

    # ── wakeword override ─────────────────────────────────────────────

    def _activate_wakeword_override(self) -> None:
        """Temporarily open gate to FULL_LISTEN after wakeword."""
        if self._mode == AttentionMode.COMMAND_ONLY:
            old = self._mode
            self._mode = AttentionMode.FULL_LISTEN
            self._wakeword_override_until = (
                time.monotonic() + self._wakeword_override_duration
            )
            self._record(old, AttentionMode.FULL_LISTEN, "wakeword_override")

    def _expire_wakeword_override(self) -> None:
        """Revert wakeword override if expired."""
        if (
            self._wakeword_override_until is not None
            and time.monotonic() > self._wakeword_override_until
        ):
            old = self._mode
            self._mode = AttentionMode.COMMAND_ONLY
            self._wakeword_override_until = None
            self._record(old, AttentionMode.COMMAND_ONLY, "wakeword_override_expired")

    # ── callbacks ─────────────────────────────────────────────────────

    def on_mode_change(self, callback: ModeCallback) -> None:
        """Register a callback ``(old, new, reason)`` for mode transitions."""
        self._callbacks.append(callback)

    # ── history ───────────────────────────────────────────────────────

    @property
    def transitions(self) -> List[ModeTransition]:
        """Copy of mode transition history."""
        return list(self._transitions)

    # ── internals ─────────────────────────────────────────────────────

    def _record(
        self, old: AttentionMode, new: AttentionMode, reason: str
    ) -> None:
        """Record transition + notify callbacks."""
        rec = ModeTransition(old_mode=old, new_mode=new, reason=reason)
        self._transitions.append(rec)
        if len(self._transitions) > self._max_history:
            self._transitions = self._transitions[-self._max_history:]

        logger.info("AttentionGate: %s → %s (%s)", old, new, reason)

        for cb in self._callbacks:
            try:
                cb(old, new, reason)
            except Exception:
                logger.exception("Attention mode callback error")
