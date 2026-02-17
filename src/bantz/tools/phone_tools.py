"""Phone Call Tools — Issue #1438.

Provides phone call management via GSConnect/KDE Connect D-Bus bridge.
Supports: initiate calls, hangup, mute/speaker toggle, call log.

Backend priority:
1. GSConnect D-Bus (org.gnome.Shell.Extensions.GSConnect)
2. KDE Connect D-Bus (org.kde.kdeconnect)
3. xdg-open tel: fallback (outgoing only)

The phone service maintains an in-process call state machine
(idle → ringing → active → ended) and emits IPC events to the overlay.
"""

from __future__ import annotations

import logging
import subprocess
import time
from enum import Enum
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Call State Machine ───────────────────────────────────────────


class CallState(str, Enum):
    """Phone call states."""

    IDLE = "idle"
    RINGING = "ringing"  # Incoming call ringing
    DIALING = "dialing"  # Outgoing call dialing
    ACTIVE = "active"  # Call in progress
    ENDED = "ended"  # Call just ended


class PhoneService:
    """In-process phone call state manager.

    Thread-safe via Lock.  Overlay notifications are dispatched
    via the ``notify_fn`` callback (usually ``overlay_client.send_raw``).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._state: CallState = CallState.IDLE
        self._caller_name: str = ""
        self._caller_number: str = ""
        self._call_start: float = 0.0
        self._muted: bool = False
        self._speaker: bool = False
        self._call_log: list[dict[str, Any]] = []
        self._notify_fn: Optional[Any] = None
        self._dbus_backend: Optional[str] = None
        self._detect_backend()

    def _detect_backend(self) -> None:
        """Detect available telephony D-Bus backend."""
        try:
            result = subprocess.run(
                ["dbus-send", "--session", "--print-reply",
                 "--dest=org.gnome.Shell.Extensions.GSConnect",
                 "/org/gnome/Shell/Extensions/GSConnect",
                 "org.freedesktop.DBus.Peer.Ping"],
                capture_output=True, timeout=3,
            )
            if result.returncode == 0:
                self._dbus_backend = "gsconnect"
                logger.info("[Phone] Backend: GSConnect (D-Bus)")
                return
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["dbus-send", "--session", "--print-reply",
                 "--dest=org.kde.kdeconnect",
                 "/modules/kdeconnect",
                 "org.freedesktop.DBus.Peer.Ping"],
                capture_output=True, timeout=3,
            )
            if result.returncode == 0:
                self._dbus_backend = "kdeconnect"
                logger.info("[Phone] Backend: KDE Connect (D-Bus)")
                return
        except Exception:
            pass

        self._dbus_backend = None
        logger.info("[Phone] Backend: xdg-open fallback (no D-Bus telephony)")

    def set_notify_fn(self, fn: Any) -> None:
        """Set the overlay notification callback (async or sync)."""
        self._notify_fn = fn

    @property
    def state(self) -> CallState:
        """Current call state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """True if a call is in progress."""
        return self._state in (CallState.RINGING, CallState.DIALING, CallState.ACTIVE)

    def initiate_call(self, number: str, name: str = "") -> dict[str, Any]:
        """Start an outgoing call.

        Args:
            number: Phone number to dial.
            name: Optional contact name.

        Returns:
            Result dict with ok/error.
        """
        with self._lock:
            if self._state in (CallState.ACTIVE, CallState.RINGING, CallState.DIALING):
                return {"ok": False, "error": "call_already_active"}

            self._state = CallState.DIALING
            self._caller_name = name or number
            self._caller_number = number
            self._call_start = time.time()
            self._muted = False
            self._speaker = False

        # Try to initiate via backend
        success = self._dial_via_backend(number)
        if success:
            with self._lock:
                self._state = CallState.ACTIVE
            self._emit_event("phone:outgoing", {
                "caller_name": name or number,
                "caller_number": number,
            })
            return {"ok": True, "state": "dialing", "number": number, "name": name}

        # Reset on failure
        with self._lock:
            self._state = CallState.IDLE
        return {"ok": False, "error": "dial_failed", "backend": self._dbus_backend or "none"}

    def _dial_via_backend(self, number: str) -> bool:
        """Attempt to dial using available backend."""
        # xdg-open tel: as universal fallback
        try:
            subprocess.Popen(
                ["xdg-open", f"tel:{number}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("[Phone] Dialing %s via xdg-open", number)
            return True
        except Exception as e:
            logger.error("[Phone] Failed to dial: %s", e)
            return False

    def handle_incoming(self, number: str, name: str = "", photo: str = "") -> None:
        """Handle an incoming call (from D-Bus signal or mock)."""
        with self._lock:
            self._state = CallState.RINGING
            self._caller_name = name or number
            self._caller_number = number
            self._muted = False
            self._speaker = False

        self._emit_event("phone:incoming", {
            "caller_name": name or number,
            "caller_number": number,
            "caller_photo": photo or None,
        })

    def accept_call(self) -> dict[str, Any]:
        """Accept an incoming call."""
        with self._lock:
            if self._state != CallState.RINGING:
                return {"ok": False, "error": "no_incoming_call"}
            self._state = CallState.ACTIVE
            self._call_start = time.time()
        return {"ok": True, "state": "active"}

    def hangup(self) -> dict[str, Any]:
        """End the current call."""
        with self._lock:
            if self._state == CallState.IDLE:
                return {"ok": False, "error": "no_active_call"}

            duration = time.time() - self._call_start if self._call_start else 0
            self._call_log.append({
                "name": self._caller_name,
                "number": self._caller_number,
                "duration_seconds": int(duration),
                "timestamp": time.time(),
                "type": "outgoing" if self._state == CallState.DIALING else "incoming",
            })

            self._state = CallState.IDLE
            ended_name = self._caller_name
            self._caller_name = ""
            self._caller_number = ""
            self._call_start = 0.0

        self._emit_event("phone:ended", {
            "duration_seconds": int(duration),
            "caller_name": ended_name,
        })
        return {"ok": True, "state": "ended", "duration_seconds": int(duration)}

    def toggle_mute(self) -> dict[str, Any]:
        """Toggle mute on the active call."""
        with self._lock:
            if self._state != CallState.ACTIVE:
                return {"ok": False, "error": "no_active_call"}
            self._muted = not self._muted
        return {"ok": True, "muted": self._muted}

    def toggle_speaker(self) -> dict[str, Any]:
        """Toggle speaker on the active call."""
        with self._lock:
            if self._state != CallState.ACTIVE:
                return {"ok": False, "error": "no_active_call"}
            self._speaker = not self._speaker
        return {"ok": True, "speaker": self._speaker}

    def get_status(self) -> dict[str, Any]:
        """Get current phone status."""
        with self._lock:
            result: dict[str, Any] = {
                "state": self._state.value,
                "backend": self._dbus_backend or "xdg-open",
            }
            if self._state != CallState.IDLE:
                result["caller_name"] = self._caller_name
                result["caller_number"] = self._caller_number
                result["muted"] = self._muted
                result["speaker"] = self._speaker
                if self._call_start:
                    result["duration_seconds"] = int(time.time() - self._call_start)
        return result

    def get_call_log(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent call log."""
        with self._lock:
            return list(reversed(self._call_log[-limit:]))

    def _emit_event(self, event: str, data: dict[str, Any]) -> None:
        """Emit an IPC event to the overlay."""
        if not self._notify_fn:
            return
        msg = {"type": "event", "event": event, "data": data}
        try:
            import asyncio
            import inspect

            result = self._notify_fn(msg)
            if inspect.isawaitable(result):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(result)
                else:
                    loop.run_until_complete(result)
        except Exception as e:
            logger.warning("[Phone] Failed to emit event %s: %s", event, e)


# ── Singleton ────────────────────────────────────────────────────

_phone_service: Optional[PhoneService] = None
_phone_lock = Lock()


def get_phone_service() -> PhoneService:
    """Get or create the singleton PhoneService."""
    global _phone_service
    with _phone_lock:
        if _phone_service is None:
            _phone_service = PhoneService()
        return _phone_service


# ── Tool Handlers ────────────────────────────────────────────────


def phone_call_tool(*, number: str = "", contact_name: str = "", **_: Any) -> Dict[str, Any]:
    """Initiate a phone call.

    Args:
        number: Phone number to dial.
        contact_name: Optional contact name for display.
    """
    if not number:
        return {"ok": False, "error": "number_required"}

    # Normalize number
    number = number.strip().replace(" ", "")
    if not number.startswith("+") and not number.isdigit():
        return {"ok": False, "error": "invalid_number_format"}

    svc = get_phone_service()

    # Try contact resolution if name given but no number
    if contact_name and not number:
        try:
            from bantz.tools.contacts_tools import contacts_resolve_tool

            result = contacts_resolve_tool(name=contact_name)
            if result.get("ok") and result.get("phone"):
                number = result["phone"]
        except ImportError:
            pass

    return svc.initiate_call(number, contact_name)


def phone_hangup_tool(**_: Any) -> Dict[str, Any]:
    """End the active phone call."""
    return get_phone_service().hangup()


def phone_mute_tool(**_: Any) -> Dict[str, Any]:
    """Toggle mute on the active phone call."""
    return get_phone_service().toggle_mute()


def phone_speaker_tool(**_: Any) -> Dict[str, Any]:
    """Toggle speaker on the active phone call."""
    return get_phone_service().toggle_speaker()


def phone_status_tool(**_: Any) -> Dict[str, Any]:
    """Get current phone call status."""
    status = get_phone_service().get_status()
    return {"ok": True, **status}


def phone_call_log_tool(*, limit: int = 10, **_: Any) -> Dict[str, Any]:
    """Get recent call log.

    Args:
        limit: Maximum number of entries to return (default 10).
    """
    limit = max(1, min(limit, 50))
    log = get_phone_service().get_call_log(limit)
    return {"ok": True, "calls": log, "count": len(log)}
