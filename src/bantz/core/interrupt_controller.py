"""Unified Interrupt Controller (Issue #456).

Provides a centralized interrupt system with four signal types:

- **STOP** — cancel current tool, end conversation
- **CANCEL** — cancel current task, conversation continues
- **PAUSE** — freeze current task (resumable)
- **RESUME** — continue a paused task

Features
--------
- Thread-safe signal delivery via :pyclass:`threading.Event`
- Handler registry with priority ordering
- Keyword detection for Turkish voice commands
- Ctrl+C / SIGTERM graceful handling helpers
- FSM + TaskRun integration hooks

See Also
--------
- ``src/bantz/core/interrupt.py`` — legacy InterruptManager (job-level)
- ``src/bantz/conversation/bargein.py`` — barge-in / CancellationToken
- ``src/bantz/voice/interrupt_handler.py`` — voice interrupt handler
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "InterruptType",
    "InterruptSignal",
    "InterruptController",
    "INTERRUPT_KEYWORDS",
]


# ── Signal types ──────────────────────────────────────────────────────

class InterruptType(Enum):
    """Interrupt signal types."""

    STOP = "stop"        # Cancel tool + end conversation
    CANCEL = "cancel"    # Cancel task, conversation continues
    PAUSE = "pause"      # Freeze task (resumable)
    RESUME = "resume"    # Continue paused task

    def __str__(self) -> str:
        return self.value


# ── Signal record ─────────────────────────────────────────────────────

@dataclass
class InterruptSignal:
    """Immutable record of a delivered interrupt."""

    interrupt_type: InterruptType
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"        # e.g. "keyboard", "voice", "api"
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Keyword map ───────────────────────────────────────────────────────

# Turkish + English keywords → InterruptType
INTERRUPT_KEYWORDS: Dict[str, InterruptType] = {
    # STOP
    "dur": InterruptType.STOP,
    "stop": InterruptType.STOP,
    "kapat": InterruptType.STOP,
    # CANCEL
    "iptal": InterruptType.CANCEL,
    "cancel": InterruptType.CANCEL,
    "vazgeç": InterruptType.CANCEL,
    "vazgec": InterruptType.CANCEL,
    # PAUSE
    "bekle": InterruptType.PAUSE,
    "pause": InterruptType.PAUSE,
    "duraklat": InterruptType.PAUSE,
    # RESUME
    "devam": InterruptType.RESUME,
    "devam et": InterruptType.RESUME,
    "resume": InterruptType.RESUME,
    "continue": InterruptType.RESUME,
}


# ── Handler type ──────────────────────────────────────────────────────

InterruptHandler = Callable[[InterruptSignal], None]


# ── Controller ────────────────────────────────────────────────────────

class InterruptController:
    """Centralized, thread-safe interrupt controller.

    Usage::

        ctrl = InterruptController()
        ctrl.register_handler(my_handler, priority=10)
        ctrl.signal(InterruptType.CANCEL, source="voice")

        # In tool-execution loop:
        if ctrl.is_interrupted():
            pending = ctrl.get_pending()
            ...

    Parameters
    ----------
    max_history:
        Maximum number of interrupt signals to retain in history.
    """

    def __init__(self, *, max_history: int = 200) -> None:
        self._lock = threading.Lock()
        self._pending: Optional[InterruptSignal] = None
        self._event = threading.Event()
        self._handlers: List[tuple[int, InterruptHandler]] = []   # (priority, fn)
        self._history: List[InterruptSignal] = []
        self._max_history = max_history
        self._paused = False
        self._ctrl_c_count = 0
        self._ctrl_c_ts: Optional[float] = None

    # ── signal delivery ───────────────────────────────────────────────

    def signal(
        self,
        interrupt_type: InterruptType | str,
        *,
        source: str = "api",
        **metadata: Any,
    ) -> InterruptSignal:
        """Deliver an interrupt signal.

        Parameters
        ----------
        interrupt_type:
            The signal to send (enum or string name).
        source:
            Origin of the signal (``"voice"``, ``"keyboard"``, ``"api"``).
        **metadata:
            Extra context stored in the signal record.

        Returns
        -------
        InterruptSignal
            The created signal object.
        """
        if isinstance(interrupt_type, str):
            interrupt_type = InterruptType(interrupt_type)

        sig = InterruptSignal(
            interrupt_type=interrupt_type,
            source=source,
            metadata=metadata,
        )

        with self._lock:
            self._pending = sig
            self._event.set()
            self._history.append(sig)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            if interrupt_type == InterruptType.PAUSE:
                self._paused = True
            elif interrupt_type == InterruptType.RESUME:
                self._paused = False

        logger.info("Interrupt signal: %s (source=%s)", interrupt_type, source)

        # Notify handlers (sorted by priority, higher first)
        for _, handler in sorted(self._handlers, key=lambda h: -h[0]):
            try:
                handler(sig)
            except Exception:
                logger.exception("Interrupt handler error")

        return sig

    # ── query API ─────────────────────────────────────────────────────

    def is_interrupted(self) -> bool:
        """Check whether an unacknowledged interrupt is pending."""
        return self._event.is_set()

    def get_pending(self) -> Optional[InterruptSignal]:
        """Return (and consume) the pending interrupt signal, if any."""
        with self._lock:
            sig = self._pending
            self._pending = None
            self._event.clear()
            return sig

    def is_paused(self) -> bool:
        """Whether the system is in a paused state."""
        with self._lock:
            return self._paused

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until an interrupt arrives. Returns ``True`` if signaled."""
        return self._event.wait(timeout=timeout)

    # ── handler registry ──────────────────────────────────────────────

    def register_handler(
        self,
        handler: InterruptHandler,
        *,
        priority: int = 0,
    ) -> None:
        """Register a handler called on every signal delivery.

        Handlers with higher *priority* execute first.
        """
        with self._lock:
            self._handlers.append((priority, handler))

    def unregister_handler(self, handler: InterruptHandler) -> bool:
        """Remove a previously registered handler. Returns ``True`` if found."""
        with self._lock:
            before = len(self._handlers)
            self._handlers = [(p, h) for p, h in self._handlers if h is not handler]
            return len(self._handlers) < before

    # ── history ───────────────────────────────────────────────────────

    @property
    def history(self) -> List[InterruptSignal]:
        """Copy of past interrupt signals (newest last)."""
        with self._lock:
            return list(self._history)

    # ── clear / reset ─────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear pending signal and paused flag."""
        with self._lock:
            self._pending = None
            self._event.clear()
            self._paused = False

    def reset(self) -> None:
        """Full reset: clear pending, paused, history."""
        with self._lock:
            self._pending = None
            self._event.clear()
            self._paused = False
            self._history.clear()
            self._ctrl_c_count = 0
            self._ctrl_c_ts = None

    # ── keyword detection ─────────────────────────────────────────────

    @staticmethod
    def detect_keyword(text: str) -> Optional[InterruptType]:
        """Match user utterance against interrupt keywords.

        The longest matching keyword wins (e.g. "devam et" beats "devam").

        Returns
        -------
        InterruptType or None
        """
        text_lower = text.strip().lower()
        if not text_lower:
            return None

        # Try longest keywords first so "devam et" is preferred over "devam"
        for kw in sorted(INTERRUPT_KEYWORDS, key=len, reverse=True):
            if kw in text_lower:
                return INTERRUPT_KEYWORDS[kw]
        return None

    # ── Ctrl+C / signal helpers ───────────────────────────────────────

    def handle_ctrl_c(self) -> str:
        """Process a Ctrl+C press.

        - 1st press within 2 s window → CANCEL
        - 2nd press within 2 s → STOP

        Returns
        -------
        str
            ``"cancel"`` or ``"stop"``
        """
        now = time.monotonic()
        with self._lock:
            if self._ctrl_c_ts is not None and (now - self._ctrl_c_ts) < 2.0:
                self._ctrl_c_count += 1
            else:
                self._ctrl_c_count = 1
                self._ctrl_c_ts = now

            count = self._ctrl_c_count

        if count >= 2:
            self.signal(InterruptType.STOP, source="keyboard")
            return "stop"
        else:
            self.signal(InterruptType.CANCEL, source="keyboard")
            return "cancel"

    def install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers (main thread only).

        - SIGINT  → :meth:`handle_ctrl_c`
        - SIGTERM → STOP
        """
        def _sigint(_signum: int, _frame: Any) -> None:
            self.handle_ctrl_c()

        def _sigterm(_signum: int, _frame: Any) -> None:
            self.signal(InterruptType.STOP, source="signal")

        signal.signal(signal.SIGINT, _sigint)
        signal.signal(signal.SIGTERM, _sigterm)

    # ── tool execution helper ─────────────────────────────────────────

    def check_before_tool(self) -> Optional[InterruptSignal]:
        """Pre-tool interrupt check.

        Call before each tool invocation in the execution loop.
        Returns the pending signal if interrupted, else ``None``.
        """
        if self.is_interrupted():
            return self.get_pending()
        return None
