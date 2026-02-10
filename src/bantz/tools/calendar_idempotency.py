"""Calendar Idempotency - Duplicate prevention for create_event.

Issue #236: Calendar idempotency key + duplicate prevention for create_event

This module provides idempotency protection to prevent duplicate calendar events
when the same command is retried (e.g., after crash/retry scenarios).

Mechanism:
1. Generate deterministic key from: normalized_title + start + end + calendar_id
2. Store recent keys in local store with TTL (24h default)
3. On duplicate detection: return existing event info instead of creating new

Usage:
    from bantz.tools.calendar_idempotency import (
        IdempotencyStore,
        generate_idempotency_key,
        check_and_record,
    )
    
    # Generate key
    key = generate_idempotency_key(
        title="Toplantı",
        start="2026-02-01T15:00:00+03:00",
        end="2026-02-01T16:00:00+03:00",
        calendar_id="primary",
    )
    
    # Check before creating
    existing = check_and_record(key)
    if existing:
        return {"ok": True, "duplicate": True, "event": existing}
    
    # Create event...
    event = create_event(...)
    
    # Record successful creation
    record_event(key, event)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default TTL for idempotency keys (24 hours)
DEFAULT_TTL_SECONDS = 24 * 60 * 60

# Default store path
DEFAULT_STORE_PATH = "artifacts/tmp/calendar_idempotency.json"


@dataclass
class IdempotencyRecord:
    """Record of a created event for idempotency."""
    key: str
    event_id: str
    event_summary: str
    event_start: str
    event_end: str
    calendar_id: str
    created_at: float  # Unix timestamp
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    
    def is_expired(self) -> bool:
        """Check if this record has expired."""
        return time.time() > (self.created_at + self.ttl_seconds)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "IdempotencyRecord":
        """Create from dictionary."""
        return cls(
            key=data.get("key", ""),
            event_id=data.get("event_id", ""),
            event_summary=data.get("event_summary", ""),
            event_start=data.get("event_start", ""),
            event_end=data.get("event_end", ""),
            calendar_id=data.get("calendar_id", "primary"),
            created_at=float(data.get("created_at", 0)),
            ttl_seconds=int(data.get("ttl_seconds", DEFAULT_TTL_SECONDS)),
        )


class IdempotencyStore:
    """Thread-safe store for idempotency records.
    
    Persists records to a JSON file for crash resilience.
    """
    
    def __init__(
        self,
        *,
        store_path: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self.store_path = store_path or os.environ.get(
            "BANTZ_IDEMPOTENCY_STORE",
            DEFAULT_STORE_PATH,
        )
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()
        self._loaded = False
        self._last_mtime: float = 0.0
    
    def _ensure_directory(self) -> None:
        """Ensure parent directory exists."""
        path = Path(self.store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    
    def _load(self) -> None:
        """Load records from disk.

        Re-reads the file when its mtime changes so that records written
        by another process are picked up automatically.
        """
        path = Path(self.store_path)
        if not path.exists():
            self._loaded = True
            return

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            self._loaded = True
            return

        if self._loaded and current_mtime == self._last_mtime:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self._records.clear()
            for key, record_data in data.get("records", {}).items():
                record = IdempotencyRecord.from_dict(record_data)
                if not record.is_expired():
                    self._records[key] = record
            
            self._last_mtime = current_mtime
            self._loaded = True
            logger.debug("Loaded %d idempotency records from %s", len(self._records), path)
        except Exception as e:
            logger.warning("Failed to load idempotency store: %s", e)
            self._loaded = True
    
    def _save(self) -> None:
        """Persist records to disk (atomic write via temp-file + rename)."""
        try:
            self._ensure_directory()
            
            # Clean expired before saving
            now = time.time()
            active_records = {
                k: v for k, v in self._records.items()
                if not v.is_expired()
            }
            
            data = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "records": {k: v.to_dict() for k, v in active_records.items()},
            }
            
            # Atomic write: write to temp file, then os.replace (POSIX atomic)
            dir_path = os.path.dirname(self.store_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(self.store_path))
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            
            logger.debug("Saved %d idempotency records to %s", len(active_records), self.store_path)
        except Exception as e:
            logger.warning("Failed to save idempotency store: %s", e)
    
    def get(self, key: str) -> Optional[IdempotencyRecord]:
        """Get a record by key.
        
        Args:
            key: Idempotency key
        
        Returns:
            IdempotencyRecord if found and not expired, None otherwise
        """
        with self._lock:
            self._load()
            
            record = self._records.get(key)
            if record is None:
                return None
            
            if record.is_expired():
                del self._records[key]
                return None
            
            return record
    
    def put(
        self,
        key: str,
        *,
        event_id: str,
        event_summary: str,
        event_start: str,
        event_end: str,
        calendar_id: str = "primary",
    ) -> IdempotencyRecord:
        """Store a new record.
        
        Args:
            key: Idempotency key
            event_id: Created event ID
            event_summary: Event title
            event_start: Event start time
            event_end: Event end time
            calendar_id: Calendar ID
        
        Returns:
            The created IdempotencyRecord
        """
        record = IdempotencyRecord(
            key=key,
            event_id=event_id,
            event_summary=event_summary,
            event_start=event_start,
            event_end=event_end,
            calendar_id=calendar_id,
            created_at=time.time(),
            ttl_seconds=self.ttl_seconds,
        )
        
        with self._lock:
            self._load()
            self._records[key] = record
            self._save()
        
        return record
    
    def remove(self, key: str) -> bool:
        """Remove a record.
        
        Args:
            key: Idempotency key
        
        Returns:
            True if record was removed, False if not found
        """
        with self._lock:
            self._load()
            
            if key in self._records:
                del self._records[key]
                self._save()
                return True
            return False
    
    def clear(self) -> int:
        """Clear all records.
        
        Returns:
            Number of records cleared
        """
        with self._lock:
            count = len(self._records)
            self._records.clear()
            self._save()
            return count
    
    def cleanup_expired(self) -> int:
        """Remove expired records.
        
        Returns:
            Number of records removed
        """
        with self._lock:
            self._load()
            
            expired = [k for k, v in self._records.items() if v.is_expired()]
            for key in expired:
                del self._records[key]
            
            if expired:
                self._save()
            
            return len(expired)
    
    def count(self) -> int:
        """Get number of active records."""
        with self._lock:
            self._load()
            return len(self._records)
    
    def list_all(self) -> list[IdempotencyRecord]:
        """List all active (non-expired) records."""
        with self._lock:
            self._load()
            return [r for r in self._records.values() if not r.is_expired()]


# Global store instance
_store: Optional[IdempotencyStore] = None
_store_lock = threading.Lock()


def get_store() -> IdempotencyStore:
    """Get the global idempotency store.
    
    Lazily initializes the store on first access.
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = IdempotencyStore()
    return _store


def normalize_title(title: str) -> str:
    """Normalize event title for consistent key generation.
    
    - Lowercase
    - Strip whitespace
    - Unicode normalization (NFKC)
    - Remove extra whitespace
    
    Args:
        title: Event title
    
    Returns:
        Normalized title
    """
    if not title:
        return ""
    
    # Unicode normalization
    normalized = unicodedata.normalize("NFKC", title)
    
    # Lowercase
    normalized = normalized.lower()
    
    # Strip and collapse whitespace
    normalized = " ".join(normalized.split())
    
    return normalized


def normalize_datetime(dt_str: str) -> str:
    """Normalize datetime string for consistent key generation.
    
    Parses the datetime, converts to UTC, and formats in a consistent way.
    This ensures that the same moment in time (e.g. Europe/Istanbul vs UTC+3)
    always produces the same normalized string for idempotency key hashing.
    Falls back to stripping whitespace if parsing fails.
    
    Args:
        dt_str: Datetime string (ISO format expected)
    
    Returns:
        Normalized datetime string (UTC)
    """
    if not dt_str:
        return ""
    
    dt_str = dt_str.strip()
    
    try:
        # Try to parse ISO format
        # Handle various formats
        if "T" in dt_str:
            # ISO format with time
            dt = datetime.fromisoformat(dt_str)
            # Convert to UTC for consistent hashing
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        else:
            # Date only
            return dt_str
    except Exception:
        # Fallback: just strip whitespace
        return dt_str


def generate_idempotency_key(
    *,
    title: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
) -> str:
    """Generate a deterministic idempotency key.
    
    The key is a SHA-256 hash of normalized inputs to ensure
    consistent key generation across retries.
    
    Args:
        title: Event title
        start: Start time (ISO format)
        end: End time (ISO format)
        calendar_id: Calendar ID
    
    Returns:
        Idempotency key (hex string)
    """
    # Normalize inputs
    norm_title = normalize_title(title)
    norm_start = normalize_datetime(start)
    norm_end = normalize_datetime(end)
    norm_calendar = (calendar_id or "primary").strip().lower()
    
    # Build canonical string
    canonical = f"{norm_title}|{norm_start}|{norm_end}|{norm_calendar}"
    
    # Hash to fixed-length key
    key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    
    return key


def check_duplicate(
    *,
    title: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
) -> Optional[IdempotencyRecord]:
    """Check if an event with the same parameters already exists.
    
    Args:
        title: Event title
        start: Start time
        end: End time
        calendar_id: Calendar ID
    
    Returns:
        IdempotencyRecord if duplicate found, None otherwise
    """
    key = generate_idempotency_key(
        title=title,
        start=start,
        end=end,
        calendar_id=calendar_id,
    )
    
    return get_store().get(key)


def record_event(
    *,
    title: str,
    start: str,
    end: str,
    event_id: str,
    calendar_id: str = "primary",
) -> IdempotencyRecord:
    """Record a newly created event for idempotency.
    
    Call this after successfully creating an event.
    
    Args:
        title: Event title
        start: Start time
        end: End time
        event_id: Created event ID
        calendar_id: Calendar ID
    
    Returns:
        Created IdempotencyRecord
    """
    key = generate_idempotency_key(
        title=title,
        start=start,
        end=end,
        calendar_id=calendar_id,
    )
    
    return get_store().put(
        key,
        event_id=event_id,
        event_summary=title,
        event_start=start,
        event_end=end,
        calendar_id=calendar_id,
    )


def create_event_with_idempotency(
    *,
    title: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
    create_fn: Any,
) -> dict[str, Any]:
    """Create an event with idempotency protection.
    
    This is the main entry point for idempotent event creation.
    
    Args:
        title: Event title
        start: Start time
        end: End time
        calendar_id: Calendar ID
        create_fn: Function to call for actual creation (returns dict with event)
    
    Returns:
        Result dict with "ok", "event", and optionally "duplicate"
    """
    # Check for existing
    existing = check_duplicate(
        title=title,
        start=start,
        end=end,
        calendar_id=calendar_id,
    )
    
    if existing:
        logger.info(
            "Duplicate event detected: %s at %s (existing event_id=%s)",
            title,
            start,
            existing.event_id,
        )
        return {
            "ok": True,
            "duplicate": True,
            "event": {
                "id": existing.event_id,
                "summary": existing.event_summary,
                "start": {"dateTime": existing.event_start},
                "end": {"dateTime": existing.event_end},
            },
            "message": "Bu etkinlik zaten ekli.",
        }
    
    # Create the event
    result = create_fn()
    
    if not isinstance(result, dict):
        return {"ok": False, "error": "Invalid create_fn result"}
    
    if not result.get("ok", True):
        # Creation failed, don't record
        return result
    
    # Extract event info
    event = result.get("event", result)
    event_id = event.get("id", "")
    
    if event_id:
        # Record for idempotency
        record_event(
            title=title,
            start=start,
            end=end,
            event_id=event_id,
            calendar_id=calendar_id,
        )
    
    result["duplicate"] = False
    return result


def format_duplicate_message(record: IdempotencyRecord) -> str:
    """Format a user-friendly duplicate message.
    
    Args:
        record: The existing IdempotencyRecord
    
    Returns:
        Turkish message for the user
    """
    try:
        dt = datetime.fromisoformat(record.event_start)
        time_str = dt.strftime("%H:%M")
        date_str = dt.strftime("%d.%m.%Y")
        return f"'{record.event_summary}' etkinliği {date_str} {time_str}'de zaten ekli."
    except Exception:
        return f"'{record.event_summary}' etkinliği zaten ekli."
