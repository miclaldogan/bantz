"""Hotkey configuration and manager (Issue #298).

Reads keybinds from environment variables and provides a platform-safe
keyboard hook that works on Linux (X11 and Wayland fallback).

Env vars::

    BANTZ_PTT_KEY=ctrl+space        # Push-to-talk
    BANTZ_MUTE_KEY=ctrl+shift+m     # Mute toggle
    BANTZ_STATUS_KEY=ctrl+shift+s   # Show status
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["HotkeyConfig", "HotkeyManager"]


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────


@dataclass
class HotkeyConfig:
    """Keybind configuration from env vars.

    Attributes
    ----------
    ptt_key:
        Push-to-talk key combo (e.g. ``ctrl+space``).
    mute_key:
        Mic mute/unmute toggle (e.g. ``ctrl+shift+m``).
    status_key:
        Show status (e.g. ``ctrl+shift+s``).
    enabled:
        Master toggle for hotkey listener.
    """

    ptt_key: str = "ctrl+space"
    mute_key: str = "ctrl+shift+m"
    status_key: str = "ctrl+shift+s"
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "HotkeyConfig":
        """Load hotkey config from environment variables."""
        return cls(
            ptt_key=os.getenv("BANTZ_PTT_KEY", "ctrl+space").strip().lower(),
            mute_key=os.getenv("BANTZ_MUTE_KEY", "ctrl+shift+m").strip().lower(),
            status_key=os.getenv("BANTZ_STATUS_KEY", "ctrl+shift+s").strip().lower(),
            enabled=os.getenv("BANTZ_HOTKEYS_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"},
        )


# ─────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────


class HotkeyManager:
    """Platform-safe keyboard hook manager.

    Registers callbacks for key combinations. Uses ``pynput`` if
    available, otherwise falls back to a no-op mode (headless/CI).

    Parameters
    ----------
    config:
        Hotkey configuration.
    """

    def __init__(self, config: Optional[HotkeyConfig] = None) -> None:
        self._config = config or HotkeyConfig.from_env()
        self._callbacks: Dict[str, Callable[[], None]] = {}
        self._listener: Optional[object] = None
        self._running = False
        self._pressed_keys: set[str] = set()

    @property
    def config(self) -> HotkeyConfig:
        return self._config

    @property
    def running(self) -> bool:
        return self._running

    def register(self, key_combo: str, callback: Callable[[], None]) -> None:
        """Register a callback for a key combination.

        Parameters
        ----------
        key_combo:
            Key combination string (e.g. ``ctrl+space``).
        callback:
            Function to call when the combo is triggered.
        """
        normalized = key_combo.strip().lower()
        self._callbacks[normalized] = callback
        logger.debug("Hotkey registered: %s", normalized)

    def unregister(self, key_combo: str) -> None:
        """Remove a registered hotkey."""
        normalized = key_combo.strip().lower()
        self._callbacks.pop(normalized, None)

    def start(self) -> bool:
        """Start listening for hotkeys.

        Returns True if started, False if disabled or pynput unavailable.
        """
        if not self._config.enabled:
            logger.debug("Hotkeys disabled")
            return False

        if self._running:
            return True

        try:
            from pynput import keyboard  # type: ignore[import-untyped]

            def on_press(key):
                try:
                    k = self._key_to_str(key)
                    if k:
                        self._pressed_keys.add(k)
                        combo = "+".join(sorted(self._pressed_keys))
                        cb = self._callbacks.get(combo)
                        if cb:
                            cb()
                except Exception as exc:
                    logger.debug("Hotkey press error: %s", exc)

            def on_release(key):
                try:
                    k = self._key_to_str(key)
                    if k:
                        self._pressed_keys.discard(k)
                except Exception:
                    pass

            self._listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            )
            self._listener.start()  # type: ignore[union-attr]
            self._running = True
            logger.info("Hotkey listener started")
            return True

        except ImportError:
            logger.debug("pynput not available — hotkeys disabled (headless mode)")
            self._running = False
            return False
        except Exception as exc:
            logger.warning("Hotkey listener failed to start: %s", exc)
            self._running = False
            return False

    def stop(self) -> None:
        """Stop listening for hotkeys."""
        if self._listener and hasattr(self._listener, "stop"):
            try:
                self._listener.stop()  # type: ignore[union-attr]
            except Exception:
                pass
        self._running = False
        self._pressed_keys.clear()
        logger.debug("Hotkey listener stopped")

    def simulate_combo(self, key_combo: str) -> bool:
        """Simulate a key combination (for testing).

        Returns True if a callback was triggered.
        """
        normalized = key_combo.strip().lower()
        cb = self._callbacks.get(normalized)
        if cb:
            cb()
            return True
        return False

    @staticmethod
    def _key_to_str(key) -> Optional[str]:
        """Convert a pynput key to a normalized string."""
        try:
            # Special keys (ctrl, shift, alt, space, etc.)
            if hasattr(key, "name"):
                name = key.name
                # Normalize modifier names
                if name in ("ctrl_l", "ctrl_r"):
                    return "ctrl"
                if name in ("shift_l", "shift_r", "shift"):
                    return "shift"
                if name in ("alt_l", "alt_r", "alt_gr"):
                    return "alt"
                return name.lower()
            # Regular character keys
            if hasattr(key, "char") and key.char:
                return key.char.lower()
        except Exception:
            pass
        return None
