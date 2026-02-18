"""Gmail channel connector — adapts existing gmail_tool.py to ChannelConnector.

Issue #1294: Kontrollü Mesajlaşma — Gmail kanal adaptörü.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from bantz.messaging.channel import ChannelConnector
from bantz.messaging.models import ChannelType, Draft, Message, SendResult

logger = logging.getLogger(__name__)


class GmailChannel(ChannelConnector):
    """Gmail channel that delegates to the existing gmail backend."""

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.EMAIL

    # ── read ─────────────────────────────────────────────────────

    async def read_inbox(
        self,
        *,
        filter_query: str | None = None,
        max_results: int = 10,
        unread_only: bool = False,
    ) -> list[Message]:
        """Read Gmail inbox, converting results to Message objects."""
        from bantz.google.gmail import gmail_list_messages

        try:
            result = gmail_list_messages(
                max_results=max_results,
                unread_only=unread_only,
                query=filter_query,
                interactive=False,
            )
        except Exception as exc:
            logger.error("[GmailChannel] read_inbox error: %s", exc)
            return []

        if not isinstance(result, dict):
            return []

        raw_msgs = result.get("messages")
        if not isinstance(raw_msgs, list):
            return []

        messages: list[Message] = []
        for raw in raw_msgs:
            if not isinstance(raw, dict):
                continue
            messages.append(self._raw_to_message(raw))

        return messages

    # ── send ─────────────────────────────────────────────────────

    async def send(self, draft: Draft) -> SendResult:
        """Send a draft via Gmail."""
        from bantz.google.gmail import gmail_send

        try:
            result = gmail_send(
                to=draft.to,
                subject=draft.subject,
                body=draft.body,
                cc=draft.cc or None,
                bcc=draft.bcc or None,
                interactive=False,
            )
        except Exception as exc:
            logger.error("[GmailChannel] send error: %s", exc)
            return SendResult(
                ok=False,
                channel=ChannelType.EMAIL,
                error=str(exc),
            )

        if not isinstance(result, dict):
            return SendResult(
                ok=False,
                channel=ChannelType.EMAIL,
                error="Bilinmeyen Gmail yanıtı",
            )

        ok = result.get("ok", False)
        return SendResult(
            ok=bool(ok),
            channel=ChannelType.EMAIL,
            message_id=result.get("id") or result.get("message_id"),
            error=result.get("error") if not ok else None,
            metadata=result,
        )

    # ── thread ───────────────────────────────────────────────────

    async def get_thread(self, thread_id: str) -> list[Message]:
        """Fetch all messages in a Gmail thread.

        Gmail threads are grouped by threadId — we list messages with
        a query filter and collect those sharing the same thread_id.
        """
        from bantz.google.gmail import gmail_list_messages

        try:
            result = gmail_list_messages(
                max_results=50,
                unread_only=False,
                query=f"rfc822msgid:{thread_id}",
                interactive=False,
            )
        except Exception as exc:
            logger.error("[GmailChannel] get_thread error: %s", exc)
            return []

        if not isinstance(result, dict):
            return []

        raw_msgs = result.get("messages")
        if not isinstance(raw_msgs, list):
            return []

        messages = []
        for raw in raw_msgs:
            if not isinstance(raw, dict):
                continue
            msg = self._raw_to_message(raw)
            messages.append(msg)

        return sorted(messages, key=lambda m: m.timestamp)

    async def search_by_contact(
        self,
        contact: str,
        *,
        max_results: int = 20,
    ) -> list[Message]:
        """Search Gmail messages by contact (from: or to: fields)."""
        return await self.read_inbox(
            filter_query=f"from:{contact} OR to:{contact}",
            max_results=max_results,
        )

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _raw_to_message(raw: dict[str, Any]) -> Message:
        """Convert a raw Gmail dict to a :class:`Message`."""
        ts_raw = raw.get("date") or raw.get("timestamp") or ""
        try:
            timestamp = datetime.fromisoformat(str(ts_raw))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        sender = raw.get("from") or raw.get("sender") or ""
        recipients_raw = raw.get("to") or ""
        if isinstance(recipients_raw, list):
            recipients = recipients_raw
        else:
            recipients = [r.strip() for r in str(recipients_raw).split(",") if r.strip()]

        return Message(
            id=str(raw.get("id") or ""),
            channel=ChannelType.EMAIL,
            sender=sender,
            recipients=recipients,
            subject=raw.get("subject") or "",
            body=raw.get("body") or raw.get("snippet") or "",
            timestamp=timestamp,
            thread_id=raw.get("threadId") or raw.get("thread_id"),
            is_read=not raw.get("unread", True),
            labels=raw.get("labels") or raw.get("labelIds") or [],
            metadata={k: v for k, v in raw.items() if k not in {
                "id", "from", "sender", "to", "subject", "body",
                "snippet", "date", "timestamp", "threadId", "thread_id",
                "unread", "labels", "labelIds",
            }},
        )
