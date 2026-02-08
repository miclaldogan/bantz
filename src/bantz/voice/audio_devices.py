"""Audio device enumeration and selection (Issue #291).

Provides helpers to list available input devices and select one.
Works with PyAudio / sounddevice backends.

Config env var::

    BANTZ_AUDIO_INPUT_DEVICE=default   # or "hw:1,0" / "USB Audio Device"
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "AudioDevice",
    "list_audio_devices",
    "select_audio_device",
    "get_default_input_device",
]


@dataclass
class AudioDevice:
    """Represents an audio input device."""

    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default: bool = False

    def __str__(self) -> str:
        default_tag = " [DEFAULT]" if self.is_default else ""
        return f"[{self.index}] {self.name} (ch={self.max_input_channels}, sr={int(self.default_sample_rate)}){default_tag}"


def list_audio_devices() -> List[AudioDevice]:
    """Return available audio input devices.

    Requires ``sounddevice`` — returns empty list if not installed.
    """
    try:
        import sounddevice as sd
    except ImportError:
        logger.warning("[audio] sounddevice not installed — cannot enumerate devices")
        return []

    devices: List[AudioDevice] = []
    try:
        default_input = sd.default.device[0] if sd.default.device else -1
    except Exception:
        default_input = -1

    for info in sd.query_devices():
        if info["max_input_channels"] > 0:
            devices.append(
                AudioDevice(
                    index=info["index"],
                    name=info["name"],
                    max_input_channels=info["max_input_channels"],
                    default_sample_rate=info["default_samplerate"],
                    is_default=(info["index"] == default_input),
                )
            )

    logger.debug("[audio] found %d input devices", len(devices))
    return devices


def get_default_input_device() -> Optional[AudioDevice]:
    """Return the system default input device, or None."""
    for dev in list_audio_devices():
        if dev.is_default:
            return dev
    # If no explicit default, return first available
    devices = list_audio_devices()
    return devices[0] if devices else None


def select_audio_device(device_id: str) -> Optional[AudioDevice]:
    """Select an audio input device by index or name substring.

    Parameters
    ----------
    device_id:
        Device index (numeric string) or name substring.

    Returns
    -------
    The matched AudioDevice, or None if not found.
    """
    if device_id == "default" or not device_id:
        return get_default_input_device()

    devices = list_audio_devices()

    # Try numeric index
    try:
        idx = int(device_id)
        for d in devices:
            if d.index == idx:
                logger.info("[audio] selected device by index: %s", d)
                return d
    except ValueError:
        pass

    # Try name substring (case-insensitive)
    needle = device_id.lower()
    for d in devices:
        if needle in d.name.lower():
            logger.info("[audio] selected device by name: %s", d)
            return d

    logger.warning("[audio] device '%s' not found", device_id)
    return None


def get_configured_device() -> Optional[AudioDevice]:
    """Get the device configured via BANTZ_AUDIO_INPUT_DEVICE env var."""
    device_id = os.getenv("BANTZ_AUDIO_INPUT_DEVICE", "default").strip()
    return select_audio_device(device_id)
