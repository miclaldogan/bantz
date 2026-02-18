"""Voice → Overlay IPC Bridge — Issue #1440.

Translates voice pipeline state changes into overlay IPC messages
so the particle sphere and HUD react to voice activity in real time.

State mapping::

    ContinuousListener.IDLE       → overlay "idle"      (slow rotation)
    ContinuousListener.LISTENING  → overlay "listening"  (breathing pulse)
    ContinuousListener.PROCESSING → overlay "thinking"   (fast spin)

    VoiceFSM.ACTIVE_LISTEN        → overlay "listening"  (if no utterance)
    VoiceFSM.WAKE_ONLY            → overlay "idle"
    VoiceFSM.IDLE_SLEEP           → overlay "idle"

Wake word detection fires a transient "wake" state (500ms flash).

Usage::

    from bantz.voice.voice_overlay_bridge import VoiceOverlayBridge

    bridge = VoiceOverlayBridge(overlay_client)
    bridge.bind_listener(continuous_listener)
    bridge.bind_fsm(voice_fsm)
    # ...
    bridge.unbind_all()  # cleanup
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Mapping from voice pipeline states to overlay sphere states
_LISTENER_STATE_MAP = {
    "IDLE": "idle",
    "LISTENING": "listening",
    "PROCESSING": "thinking",
}

_FSM_STATE_MAP = {
    "active_listen": "listening",
    "wake_only": "idle",
    "idle_sleep": "idle",
}


class VoiceOverlayBridge:
    """Bridge between voice pipeline and overlay IPC.

    Registers callbacks on ``ContinuousListener`` and ``VoiceFSM``
    to push real-time state changes to the overlay sphere via
    ``OverlayClient.send_raw()`` or ``OverlayClient.set_state()``.

    Thread-safe: callbacks may fire from the voice capture thread.
    """

    def __init__(self, overlay_client: Any) -> None:
        self._client = overlay_client
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_state: str = "idle"
        self._last_wake_time: float = 0.0
        self._wake_cooldown: float = 2.0  # seconds between wake flashes
        self._bound_listener: Any = None
        self._bound_fsm: Any = None

        # Try to get or create event loop for async scheduling
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None

    # ── Public API ───────────────────────────────────────────────

    def bind_listener(self, listener: Any) -> None:
        """Register callbacks on a ContinuousListener.

        Parameters
        ----------
        listener:
            ``ContinuousListener`` instance with ``on_state_change()``
            and ``on_wake_word()`` callback registration methods.
        """
        if hasattr(listener, "on_state_change"):
            listener.on_state_change(self._on_listener_state)
        if hasattr(listener, "on_wake_word"):
            listener.on_wake_word(self._on_wake_word)
        self._bound_listener = listener
        logger.info("[VoiceOverlayBridge] Bound to ContinuousListener")

    def bind_fsm(self, fsm: Any) -> None:
        """Register callback on a VoiceFSM.

        Parameters
        ----------
        fsm:
            ``VoiceFSM`` instance with ``set_on_transition()`` method.
        """
        if hasattr(fsm, "set_on_transition"):
            fsm.set_on_transition(self._on_fsm_transition)
        self._bound_fsm = fsm
        logger.info("[VoiceOverlayBridge] Bound to VoiceFSM")

    def unbind_all(self) -> None:
        """Remove all registered callbacks (cleanup)."""
        if self._bound_listener:
            # ContinuousListener doesn't have remove_callback, but
            # clear_callbacks() is available if needed
            self._bound_listener = None
        if self._bound_fsm:
            if hasattr(self._bound_fsm, "clear_on_transition"):
                self._bound_fsm.clear_on_transition()
            self._bound_fsm = None
        logger.info("[VoiceOverlayBridge] Unbound all callbacks")

    # ── Callback Handlers ────────────────────────────────────────

    def _on_listener_state(self, state: Any) -> None:
        """Handle ContinuousListener state change.

        Called from the voice capture thread — schedule async send.
        """
        state_name = state.name if hasattr(state, "name") else str(state)
        overlay_state = _LISTENER_STATE_MAP.get(state_name, "idle")

        if overlay_state != self._last_state:
            self._last_state = overlay_state
            self._send_voice_state(overlay_state, trigger=f"listener:{state_name}")

    def _on_wake_word(self, wake_word: str, confidence: float) -> None:
        """Handle wake word detection — send transient 'wake' flash.

        Called from the voice capture thread.
        """
        now = time.monotonic()
        if now - self._last_wake_time < self._wake_cooldown:
            return  # debounce rapid wake detections

        self._last_wake_time = now
        self._send_voice_state(
            "wake",
            trigger=f"wake_word:{wake_word}",
            extra={"wake_word": wake_word, "confidence": round(confidence, 2)},
        )
        logger.info(
            "[VoiceOverlayBridge] Wake word: %s (%.2f)", wake_word, confidence
        )

    def _on_fsm_transition(self, transition: Any) -> None:
        """Handle VoiceFSM state transition.

        Only updates overlay if the listener isn't in a more specific state
        (e.g., PROCESSING overrides FSM's active_listen).
        """
        to_state = transition.to_state
        to_value = to_state.value if hasattr(to_state, "value") else str(to_state)
        overlay_state = _FSM_STATE_MAP.get(to_value, "idle")

        # Don't downgrade from "thinking" (PROCESSING) to "listening"
        # when FSM stays in active_listen
        if self._last_state == "thinking" and overlay_state == "listening":
            return

        if overlay_state != self._last_state:
            self._last_state = overlay_state
            self._send_voice_state(
                overlay_state,
                trigger=f"fsm:{transition.trigger}",
            )

    # ── IPC Sending ──────────────────────────────────────────────

    def _send_voice_state(
        self,
        state: str,
        trigger: str = "",
        extra: Optional[dict] = None,
    ) -> None:
        """Send voice state to overlay via IPC.

        Tries ``set_state()`` first (proper StateMessage), falls back
        to ``send_raw()`` for custom data.
        """
        msg = {
            "type": "voice_state",
            "state": state,
            "trigger": trigger,
            "ts": int(time.time() * 1000),
        }
        if extra:
            msg["data"] = extra

        logger.debug("[VoiceOverlayBridge] → %s (trigger: %s)", state, trigger)

        try:
            if self._loop and self._loop.is_running():
                asyncio.ensure_future(
                    self._client.send_raw(msg), loop=self._loop
                )
            else:
                # If called from a sync context, try to run
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self._client.send_raw(msg))
                loop.close()
        except Exception as e:
            logger.warning("[VoiceOverlayBridge] Send failed: %s", e)

    # ── Speaking State (called externally) ───────────────────────

    def on_speaking_start(self) -> None:
        """Notify bridge that TTS is speaking."""
        self._last_state = "speaking"
        self._send_voice_state("speaking", trigger="tts:start")

    def on_speaking_end(self) -> None:
        """Notify bridge that TTS finished speaking."""
        self._last_state = "idle"
        self._send_voice_state("idle", trigger="tts:end")
