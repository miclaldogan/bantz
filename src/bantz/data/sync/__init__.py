"""
bantz.data.sync — Proactive data synchronization layer.

Periodically pulls data from external sources (Gmail, Calendar, News)
into the IngestStore so the agent can query locally instead of
making live API calls on every request.

Modules:
    gmail_sync     — Gmail inbox → IngestStore with sender classification
    calendar_sync  — Google Calendar → IngestStore
    news_sync      — RSS feeds → IngestStore
    classifier     — Rule-based sender/content classification engine
    scheduler      — Async scheduler orchestrating all sync tasks
"""

from bantz.data.sync.classifier import SenderClassifier, classify_sender
from bantz.data.sync.scheduler import SyncScheduler

__all__ = [
    "SenderClassifier",
    "classify_sender",
    "SyncScheduler",
]
