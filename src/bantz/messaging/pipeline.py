"""Messaging pipeline — read → draft → confirm → send.

Issue #1294: Kontrollü Mesajlaşma — kanal-bağımsız mesajlaşma pipeline'ı.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from bantz.messaging.batch import BatchDraftManager, DraftGeneratorFn
from bantz.messaging.channel import ChannelConnector
from bantz.messaging.models import (Conversation, Draft, DraftBatch, Message,
                                    SendResult)
from bantz.messaging.thread_tracker import ThreadTracker

logger = logging.getLogger(__name__)

# Policy evaluation callback — mirrors the existing Bantz policy engine.
PolicyFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MessagingPipeline:
    """Channel-agnostic messaging pipeline: read → draft → confirm → send.

    Brings together :class:`ChannelConnector`, :class:`ThreadTracker`,
    and :class:`BatchDraftManager` into a unified workflow the LLM
    router can invoke with simple tool calls.

    Usage::

        pipeline = MessagingPipeline()
        pipeline.register_channel(gmail_channel)
        msgs = await pipeline.read_inbox("email")
        batch = await pipeline.draft_replies(msgs, "Kısa cevap yaz")
        results = await pipeline.confirm_and_send(batch)
    """

    def __init__(
        self,
        *,
        policy_fn: PolicyFn | None = None,
        draft_generator: DraftGeneratorFn | None = None,
    ) -> None:
        self._channels: dict[str, ChannelConnector] = {}
        self._tracker = ThreadTracker()
        self._policy_fn = policy_fn
        self._draft_generator = draft_generator
        self._batch_managers: dict[str, BatchDraftManager] = {}

    # ── channel management ───────────────────────────────────────

    def register_channel(self, channel: ChannelConnector) -> None:
        """Register a messaging channel."""
        key = channel.channel_type.value
        self._channels[key] = channel
        self._tracker.add_channel(channel)
        self._batch_managers[key] = BatchDraftManager(
            channel, self._draft_generator
        )
        logger.info("[MessagingPipeline] Channel registered: %s", key)

    def get_channel(self, channel: str) -> ChannelConnector | None:
        """Retrieve a registered channel by name."""
        return self._channels.get(channel)

    @property
    def available_channels(self) -> list[str]:
        """Return list of registered channel names."""
        return list(self._channels.keys())

    # ── READ ─────────────────────────────────────────────────────

    async def read_inbox(
        self,
        channel: str = "all",
        *,
        filter_query: str | None = None,
        max_results: int = 10,
        unread_only: bool = False,
    ) -> list[Message]:
        """Read messages from one or all channels.

        Args:
            channel: Channel name ("email", "telegram", …) or "all".
            filter_query: Optional search filter.
            max_results: Max messages per channel.
            unread_only: Only return unread messages.
        """
        if channel == "all":
            all_msgs: list[Message] = []
            for ch in self._channels.values():
                try:
                    msgs = await ch.read_inbox(
                        filter_query=filter_query,
                        max_results=max_results,
                        unread_only=unread_only,
                    )
                    all_msgs.extend(msgs)
                except Exception as exc:
                    logger.warning(
                        "[MessagingPipeline] read_inbox %s error: %s",
                        ch.channel_type.value,
                        exc,
                    )
            return sorted(all_msgs, key=lambda m: m.timestamp, reverse=True)

        connector = self._channels.get(channel)
        if connector is None:
            logger.warning("[MessagingPipeline] Unknown channel: %s", channel)
            return []

        return await connector.read_inbox(
            filter_query=filter_query,
            max_results=max_results,
            unread_only=unread_only,
        )

    # ── DRAFT ────────────────────────────────────────────────────

    async def draft_reply(
        self,
        message: Message,
        instruction: str = "Kısa ve profesyonel yanıt yaz",
    ) -> Draft:
        """Generate a single draft reply for a message using the LLM.

        Args:
            message: The original message to reply to.
            instruction: Tone / style instruction.

        Returns:
            A :class:`Draft` object ready for review.
        """
        channel_key = message.channel.value
        manager = self._batch_managers.get(channel_key)
        if manager is None:
            raise ValueError(f"Kanal kayıtlı değil: {channel_key}")

        batch = await manager.generate_drafts([message], instruction)
        if batch.drafts:
            return batch.drafts[0]
        raise RuntimeError("Taslak oluşturulamadı.")

    async def draft_replies(
        self,
        messages: list[Message],
        instruction: str = "Kısa ve profesyonel yanıt yaz",
    ) -> DraftBatch:
        """Generate draft replies for multiple messages (batch mode).

        Groups messages by channel and uses the appropriate
        :class:`BatchDraftManager` for each.
        """
        if not messages:
            return DraftBatch()

        # Group by channel
        by_channel: dict[str, list[Message]] = {}
        for msg in messages:
            by_channel.setdefault(msg.channel.value, []).append(msg)

        combined = DraftBatch()
        for chan_key, chan_msgs in by_channel.items():
            manager = self._batch_managers.get(chan_key)
            if manager is None:
                logger.warning(
                    "[MessagingPipeline] No manager for %s", chan_key
                )
                continue
            batch = await manager.generate_drafts(chan_msgs, instruction)
            combined.drafts.extend(batch.drafts)

        return combined

    # ── CONFIRM & SEND ───────────────────────────────────────────

    async def confirm_and_send(
        self,
        batch: DraftBatch,
    ) -> list[SendResult]:
        """Send all approved drafts, evaluating policy for each.

        Drafts without a decision are skipped.  Policy evaluation
        happens before each send — if denied, the draft is not sent.

        Returns:
            List of :class:`SendResult` for each attempted send.
        """
        results: list[SendResult] = []
        for draft in batch.get_approved_drafts():
            # Policy check
            if self._policy_fn is not None:
                try:
                    decision = await self._policy_fn(
                        f"{draft.channel.value}.send_message",
                        {"to": draft.to, "subject": draft.subject},
                    )
                    action = decision.get("action", "allow")
                    if action == "deny":
                        results.append(
                            SendResult(
                                ok=False,
                                channel=draft.channel,
                                error=decision.get("reason", "Policy denied"),
                            )
                        )
                        continue
                except Exception as exc:
                    logger.warning(
                        "[MessagingPipeline] Policy eval error: %s", exc
                    )

            # Send
            ch = self._channels.get(draft.channel.value)
            if ch is None:
                results.append(
                    SendResult(
                        ok=False,
                        channel=draft.channel,
                        error=f"Kanal bulunamadı: {draft.channel.value}",
                    )
                )
                continue

            try:
                result = await ch.send(draft)
            except Exception as exc:
                result = SendResult(
                    ok=False,
                    channel=draft.channel,
                    error=str(exc),
                )
            results.append(result)

        return results

    async def send_single(self, draft: Draft) -> SendResult:
        """Send a single draft (bypasses batch flow)."""
        batch = DraftBatch(drafts=[draft])
        batch.approve(draft.id)
        results = await self.confirm_and_send(batch)
        return results[0] if results else SendResult(
            ok=False, channel=draft.channel, error="Gönderim başarısız"
        )

    # ── THREAD / CONVERSATION ────────────────────────────────────

    async def get_conversation(
        self,
        contact: str,
        *,
        channel: str | None = None,
        include_summary: bool = True,
    ) -> Conversation:
        """Retrieve a cross-channel conversation with a contact."""
        return await self._tracker.get_conversation(
            contact,
            channel_filter=channel,
            include_summary=include_summary,
        )

    async def summarise_thread(
        self,
        thread_id: str,
        *,
        channel: str | None = None,
    ) -> str:
        """Summarise a specific thread."""
        return await self._tracker.summarise_thread(
            thread_id, channel_filter=channel
        )

    # ── status ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return pipeline status for diagnostics."""
        return {
            "channels": self.available_channels,
            "channel_count": len(self._channels),
        }
