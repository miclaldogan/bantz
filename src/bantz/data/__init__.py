"""
bantz.data — Data persistence layer.

Provides:
- IngestStore: TTL-cached tool result store with fingerprint dedup
- DataClass: EPHEMERAL / SESSION / PERSISTENT lifecycle classification
"""

from bantz.data.ingest_store import IngestStore, DataClass, IngestRecord

__all__ = ["IngestStore", "DataClass", "IngestRecord"]
