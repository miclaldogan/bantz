"""Data models for the messaging pipeline.

Issue #1294: Controlled Messaging
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class ChannelType(str, enum.Enum):
    """Supported messaging channels."""

    EMAIL = "email"
    TELEGRAM = "telegram"
    SLACK = "slack"
    WHATSAPP = "whatsapp"


class DraftDecision(str, enum.Enum):
    """User decision on a draft message."""

    APPROVE = "approve"
    EDIT = "edit"
    SKIP = "skip"


@dataclass
class Message:
    """A single message from any channel."""

    id: str
    channel: ChannelType
    sender: str
    recipients: list[str]
    subject: str
    body: str
    timestamp: datetime
    thread_id: str | None = None
    is_read: bool = False
    labels: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def preview(self) -> str:
        """Return a short preview of the message body (max 120 chars)."""
        text = self.body.replace("\n", " ").strip()
        return text[:120] + "…" if len(text) > 120 else text


@dataclass
class Draft:
    """A draft reply ready for user review."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    channel: ChannelType = ChannelType.EMAIL
    to: str = ""
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    body: str = ""
    in_reply_to: str | None = None
    thread_id: str | None = None
    instruction: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_display(self) -> dict[str, Any]:
        """Return a user-friendly display dict."""
        return {
            "id": self.id,
            "channel": self.channel.value,
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
        }


@dataclass
class SendResult:
    """Result of sending a message."""

    ok: bool
    channel: ChannelType
    message_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    """A grouped conversation thread with optional summary."""

    contact: str
    channel: ChannelType | None = None
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    thread_ids: list[str] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def last_message(self) -> Message | None:
        return self.messages[-1] if self.messages else None


@dataclass
class DraftBatch:
    """A batch of drafts for bulk review/send."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    drafts: list[Draft] = field(default_factory=list)
    decisions: dict[str, DraftDecision] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def total(self) -> int:
        return len(self.drafts)

    @property
    def approved_count(self) -> int:
        return sum(
            1 for d in self.decisions.values() if d == DraftDecision.APPROVE
        )

    @property
    def pending_count(self) -> int:
        decided = set(self.decisions.keys())
        return sum(1 for d in self.drafts if d.id not in decided)

    def approve(self, draft_id: str) -> None:
        """Mark a draft as approved."""
        self.decisions[draft_id] = DraftDecision.APPROVE

    def skip(self, draft_id: str) -> None:
        """Mark a draft as skipped."""
        self.decisions[draft_id] = DraftDecision.SKIP

    def get_approved_drafts(self) -> list[Draft]:
        """Return all approved drafts."""
        approved_ids = {
            k for k, v in self.decisions.items() if v == DraftDecision.APPROVE
        }
        return [d for d in self.drafts if d.id in approved_ids]
