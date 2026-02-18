"""Abstract channel connector interface.

Issue #1294: Channel-agnostic messaging — every channel implements this ABC.
"""

from __future__ import annotations

import abc
from typing import Any

from bantz.messaging.models import ChannelType, Draft, Message, SendResult


class ChannelConnector(abc.ABC):
    """Abstract interface for messaging channel connectors.

    Every channel (Gmail, Telegram, Slack, …) must implement these
    three methods.  The pipeline talks to channels exclusively through
    this interface, making the rest of the stack channel-agnostic.
    """

    @property
    @abc.abstractmethod
    def channel_type(self) -> ChannelType:
        """Return the channel type this connector handles."""

    @abc.abstractmethod
    async def read_inbox(
        self,
        *,
        filter_query: str | None = None,
        max_results: int = 10,
        unread_only: bool = False,
    ) -> list[Message]:
        """Read messages from the channel inbox.

        Args:
            filter_query: Optional search / filter string.
            max_results: Maximum number of messages to return.
            unread_only: If *True*, only return unread messages.

        Returns:
            List of :class:`Message` objects.
        """

    @abc.abstractmethod
    async def send(self, draft: Draft) -> SendResult:
        """Send a message using this channel.

        Args:
            draft: The :class:`Draft` to send.

        Returns:
            A :class:`SendResult` with delivery status.
        """

    @abc.abstractmethod
    async def get_thread(self, thread_id: str) -> list[Message]:
        """Fetch all messages in a conversation thread.

        Args:
            thread_id: The channel-specific thread identifier.

        Returns:
            List of :class:`Message` sorted chronologically.
        """

    async def search_by_contact(
        self,
        contact: str,
        *,
        max_results: int = 20,
    ) -> list[Message]:
        """Search messages by contact name or address.

        Default implementation delegates to :meth:`read_inbox` with the
        contact as a filter query.  Channels may override for more
        precise behaviour.
        """
        return await self.read_inbox(
            filter_query=contact, max_results=max_results
        )

    # ── convenience helpers ──────────────────────────────────────

    @staticmethod
    def _ok(**data: Any) -> dict[str, Any]:
        return {"ok": True, **data}

    @staticmethod
    def _err(message: str, **data: Any) -> dict[str, Any]:
        return {"ok": False, "error": message, **data}
