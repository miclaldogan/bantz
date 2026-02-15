"""Delivery Channels for the Proactive Secretary Engine.

Each channel implements the :class:`DeliveryChannel` ABC and is
responsible for presenting a brief or notification to the user
through a specific medium (terminal, desktop notification, etc.).

Issue #1293
"""
from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class DeliveryChannel(ABC):
    """Abstract base for brief/notification delivery."""

    @abstractmethod
    async def deliver(self, text: str) -> None:
        """Deliver a text message to the user."""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


class TerminalDelivery(DeliveryChannel):
    """Print the brief to stdout (terminal session)."""

    async def deliver(self, text: str) -> None:
        print(text)


class DesktopNotificationDelivery(DeliveryChannel):
    """Send a Linux desktop notification via ``notify-send``."""

    def __init__(
        self,
        *,
        title: str = "Bantz Daily Brief",
        urgency: str = "normal",
        timeout_ms: int = 10_000,
    ) -> None:
        self._title = title
        self._urgency = urgency
        self._timeout_ms = timeout_ms

    async def deliver(self, text: str) -> None:
        # Truncate body to avoid dbus limits
        body = text[:500]
        try:
            subprocess.run(
                [
                    "notify-send",
                    f"--urgency={self._urgency}",
                    f"--expire-time={self._timeout_ms}",
                    self._title,
                    body,
                ],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except FileNotFoundError:
            logger.debug("notify-send not available — desktop notification skipped")
        except Exception as exc:
            logger.warning("Desktop notification failed: %s", exc)


class EventBusDelivery(DeliveryChannel):
    """Publish the brief through the Bantz EventBus.

    This allows the CLI and any future UI to receive the brief
    reactively.
    """

    def __init__(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    async def deliver(self, text: str) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                event_type="bantz_message",
                data={"text": text, "proactive": True, "type": "daily_brief"},
            )
        except Exception as exc:
            logger.warning("EventBus delivery failed: %s", exc)


class CallbackDelivery(DeliveryChannel):
    """Deliver via an arbitrary async callback — useful for testing."""

    def __init__(self, callback: Any) -> None:
        self._callback = callback

    async def deliver(self, text: str) -> None:
        if self._callback:
            await self._callback(text)
