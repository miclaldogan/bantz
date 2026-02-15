"""Thread tracker — conversation grouping + LLM summarisation.

Issue #1294: Kontrollü Mesajlaşma — thread takip ve özet.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from bantz.messaging.channel import ChannelConnector
from bantz.messaging.models import Conversation, Message

logger = logging.getLogger(__name__)

# Type alias for the LLM summariser callback.
SummariserFn = Callable[[list[Message]], Awaitable[str]]


async def _default_summariser(messages: list[Message]) -> str:
    """Fallback summariser when no LLM is available."""
    if not messages:
        return "Mesaj bulunamadı."

    first = messages[0]
    last = messages[-1]
    return (
        f"{len(messages)} mesaj — "
        f"{first.timestamp.strftime('%d.%m.%Y')} ile "
        f"{last.timestamp.strftime('%d.%m.%Y')} arasında."
    )


class ThreadTracker:
    """Track, group, and summarise conversation threads.

    Supports cross-channel conversation assembly: all messages with
    a given contact across multiple channels are merged into a single
    :class:`Conversation`.
    """

    def __init__(
        self,
        channels: list[ChannelConnector] | None = None,
        summariser: SummariserFn | None = None,
    ) -> None:
        self._channels: list[ChannelConnector] = channels or []
        self._summariser: SummariserFn = summariser or _default_summariser

    # ── public API ───────────────────────────────────────────────

    def add_channel(self, channel: ChannelConnector) -> None:
        """Register a channel connector for cross-channel tracking."""
        self._channels.append(channel)

    async def get_conversation(
        self,
        contact: str,
        *,
        channel_filter: str | None = None,
        max_per_channel: int = 20,
        include_summary: bool = True,
    ) -> Conversation:
        """Assemble a cross-channel conversation for *contact*.

        Args:
            contact: Name or address to search for.
            channel_filter: Restrict to a single channel type (e.g. "email").
            max_per_channel: Max messages to fetch per channel.
            include_summary: Whether to generate an LLM summary.

        Returns:
            A :class:`Conversation` with merged, sorted messages and
            an optional summary.
        """
        all_messages: list[Message] = []
        thread_ids: set[str] = set()

        for ch in self._channels:
            if channel_filter and ch.channel_type.value != channel_filter:
                continue
            try:
                msgs = await ch.search_by_contact(
                    contact, max_results=max_per_channel
                )
                all_messages.extend(msgs)
                for m in msgs:
                    if m.thread_id:
                        thread_ids.add(m.thread_id)
            except Exception as exc:
                logger.warning(
                    "[ThreadTracker] Error fetching from %s: %s",
                    ch.channel_type.value,
                    exc,
                )

        # Sort chronologically
        all_messages.sort(key=lambda m: m.timestamp)

        # Deduplicate by message id
        seen: set[str] = set()
        deduped: list[Message] = []
        for m in all_messages:
            if m.id and m.id not in seen:
                seen.add(m.id)
                deduped.append(m)
            elif not m.id:
                deduped.append(m)

        summary = ""
        if include_summary and deduped:
            try:
                summary = await self._summariser(deduped)
            except Exception as exc:
                logger.warning("[ThreadTracker] Summariser error: %s", exc)
                summary = await _default_summariser(deduped)

        return Conversation(
            contact=contact,
            messages=deduped,
            summary=summary,
            thread_ids=sorted(thread_ids),
        )

    async def get_thread(
        self,
        thread_id: str,
        *,
        channel_filter: str | None = None,
    ) -> list[Message]:
        """Fetch a specific thread by its id from all connected channels."""
        for ch in self._channels:
            if channel_filter and ch.channel_type.value != channel_filter:
                continue
            try:
                msgs = await ch.get_thread(thread_id)
                if msgs:
                    return msgs
            except Exception as exc:
                logger.warning(
                    "[ThreadTracker] get_thread %s error: %s",
                    ch.channel_type.value,
                    exc,
                )
        return []

    async def summarise_thread(
        self,
        thread_id: str,
        *,
        channel_filter: str | None = None,
    ) -> str:
        """Fetch and summarise a specific thread."""
        messages = await self.get_thread(
            thread_id, channel_filter=channel_filter
        )
        if not messages:
            return "Thread bulunamadı."
        return await self._summariser(messages)
