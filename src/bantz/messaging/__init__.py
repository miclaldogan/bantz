"""Controlled Messaging — Read → Draft → Confirm → Send Pipeline.

Issue #1294: Channel-agnostic messaging layer.
"""

from __future__ import annotations

from bantz.messaging.batch import BatchDraftManager
from bantz.messaging.channel import ChannelConnector
from bantz.messaging.gmail_channel import GmailChannel
from bantz.messaging.models import (Conversation, Draft, DraftBatch,
                                    DraftDecision, Message, SendResult)
from bantz.messaging.pipeline import MessagingPipeline
from bantz.messaging.thread_tracker import ThreadTracker

__all__ = [
    "Message",
    "Draft",
    "DraftBatch",
    "DraftDecision",
    "SendResult",
    "Conversation",
    "ChannelConnector",
    "GmailChannel",
    "MessagingPipeline",
    "ThreadTracker",
    "BatchDraftManager",
]
