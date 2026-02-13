"""Tests for Calendar Idempotency.

Issue #236: Calendar idempotency key + duplicate prevention for create_event

Test categories:
1. Key generation and normalization
2. IdempotencyRecord behavior
3. IdempotencyStore operations
4. Duplicate detection
5. TTL and expiration
6. Thread safety
7. Persistence
8. Integration with create_event
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from bantz.tools.calendar_idempotency import (
    DEFAULT_TTL_SECONDS,
    IdempotencyRecord,
    IdempotencyStore,
    check_duplicate,
    create_event_with_idempotency,
    format_duplicate_message,
    generate_idempotency_key,
    get_store,
    normalize_datetime,
    normalize_title,
    record_event,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_store_path() -> Generator[str, None, None]:
    """Create a temporary store file path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name
    
    yield temp_path
    
    try:
        os.unlink(temp_path)
    except OSError:
        pass


@pytest.fixture
def store(temp_store_path) -> IdempotencyStore:
    """Create a test store with temp path."""
    return IdempotencyStore(store_path=temp_store_path, ttl_seconds=3600)


@pytest.fixture
def sample_event() -> dict:
    """Sample event data."""
    return {
        "title": "Team Meeting",
        "start": "2026-02-01T15:00:00+03:00",
        "end": "2026-02-01T16:00:00+03:00",
        "calendar_id": "primary",
    }


# ============================================================================
# NORMALIZATION TESTS
# ============================================================================

class TestNormalization:
    """Test title and datetime normalization."""
    
    def test_normalize_title_lowercase(self):
        """Test title lowercasing."""
        assert normalize_title("MEETING") == "meeting"
        assert normalize_title("Team Meeting") == "team meeting"
    
    def test_normalize_title_whitespace(self):
        """Test whitespace handling."""
        assert normalize_title("  Meeting  ") == "meeting"
        assert normalize_title("Team   Meeting") == "team meeting"
        assert normalize_title("\tMeeting\n") == "meeting"
    
    def test_normalize_title_unicode(self):
        """Test unicode normalization."""
        # Turkish characters (lowercase preserves Turkish characters)
        assert normalize_title("Toplantı") == "toplantı"
        # Note: str.lower() doesn't convert Turkish I/İ correctly
        assert normalize_title("TOPLANTI") == "toplanti"  # ASCII I -> i
    
    def test_normalize_title_empty(self):
        """Test empty title handling."""
        assert normalize_title("") == ""
        assert normalize_title("   ") == ""
    
    def test_normalize_datetime_iso(self):
        """Test ISO datetime normalization.
        
        normalize_datetime converts to UTC for consistent idempotency hashing.
        15:00+03:00 → 12:00 UTC.
        """
        result = normalize_datetime("2026-02-01T15:00:00+03:00")
        assert "2026-02-01" in result
        assert "12:00" in result  # 15:00+03:00 = 12:00 UTC
    
    def test_normalize_datetime_with_whitespace(self):
        """Test datetime whitespace handling."""
        result = normalize_datetime("  2026-02-01T15:00:00+03:00  ")
        assert result.strip() == result
    
    def test_normalize_datetime_date_only(self):
        """Test date-only string."""
        assert normalize_datetime("2026-02-01") == "2026-02-01"
    
    def test_normalize_datetime_empty(self):
        """Test empty datetime."""
        assert normalize_datetime("") == ""


# ============================================================================
# KEY GENERATION TESTS
# ============================================================================

class TestKeyGeneration:
    """Test idempotency key generation."""
    
    def test_generate_key_basic(self, sample_event):
        """Test basic key generation."""
        key = generate_idempotency_key(**sample_event)
        
        assert isinstance(key, str)
        assert len(key) == 32  # SHA-256 truncated to 32 hex chars
    
    def test_generate_key_deterministic(self, sample_event):
        """Test that same inputs produce same key."""
        key1 = generate_idempotency_key(**sample_event)
        key2 = generate_idempotency_key(**sample_event)
        
        assert key1 == key2
    
    def test_generate_key_different_inputs(self, sample_event):
        """Test that different inputs produce different keys."""
        key1 = generate_idempotency_key(**sample_event)
        
        # Different title
        modified = sample_event.copy()
        modified["title"] = "Different Meeting"
        key2 = generate_idempotency_key(**modified)
        
        assert key1 != key2
    
    def test_generate_key_different_times(self, sample_event):
        """Test that different times produce different keys."""
        key1 = generate_idempotency_key(**sample_event)
        
        modified = sample_event.copy()
        modified["start"] = "2026-02-01T16:00:00+03:00"
        key2 = generate_idempotency_key(**modified)
        
        assert key1 != key2
    
    def test_generate_key_case_insensitive_title(self, sample_event):
        """Test that title case doesn't affect key."""
        key1 = generate_idempotency_key(**sample_event)
        
        modified = sample_event.copy()
        modified["title"] = "TEAM MEETING"
        key2 = generate_idempotency_key(**modified)
        
        assert key1 == key2
    
    def test_generate_key_whitespace_insensitive(self, sample_event):
        """Test that extra whitespace doesn't affect key."""
        key1 = generate_idempotency_key(**sample_event)
        
        modified = sample_event.copy()
        modified["title"] = "  Team   Meeting  "
        key2 = generate_idempotency_key(**modified)
        
        assert key1 == key2
    
    def test_generate_key_default_calendar(self):
        """Test default calendar_id handling."""
        key1 = generate_idempotency_key(
            title="Meeting",
            start="2026-02-01T15:00:00",
            end="2026-02-01T16:00:00",
        )
        key2 = generate_idempotency_key(
            title="Meeting",
            start="2026-02-01T15:00:00",
            end="2026-02-01T16:00:00",
            calendar_id="primary",
        )
        
        assert key1 == key2


# ============================================================================
# IDEMPOTENCY RECORD TESTS
# ============================================================================

class TestIdempotencyRecord:
    """Test IdempotencyRecord behavior."""
    
    def test_create_record(self):
        """Test record creation."""
        record = IdempotencyRecord(
            key="abc123",
            event_id="evt_123",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
            calendar_id="primary",
            created_at=time.time(),
        )
        
        assert record.key == "abc123"
        assert record.event_id == "evt_123"
        assert record.event_summary == "Meeting"
    
    def test_record_not_expired(self):
        """Test that fresh record is not expired."""
        record = IdempotencyRecord(
            key="abc123",
            event_id="evt_123",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
            calendar_id="primary",
            created_at=time.time(),
            ttl_seconds=3600,
        )
        
        assert record.is_expired() is False
    
    def test_record_expired(self):
        """Test that old record is expired."""
        record = IdempotencyRecord(
            key="abc123",
            event_id="evt_123",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
            calendar_id="primary",
            created_at=time.time() - 7200,  # 2 hours ago
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        assert record.is_expired() is True
    
    def test_record_to_dict(self):
        """Test dictionary conversion."""
        record = IdempotencyRecord(
            key="abc123",
            event_id="evt_123",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
            calendar_id="primary",
            created_at=1000000.0,
            ttl_seconds=3600,
        )
        
        data = record.to_dict()
        
        assert data["key"] == "abc123"
        assert data["event_id"] == "evt_123"
        assert data["ttl_seconds"] == 3600
    
    def test_record_from_dict(self):
        """Test dictionary parsing."""
        data = {
            "key": "abc123",
            "event_id": "evt_123",
            "event_summary": "Meeting",
            "event_start": "2026-02-01T15:00:00",
            "event_end": "2026-02-01T16:00:00",
            "calendar_id": "primary",
            "created_at": 1000000.0,
            "ttl_seconds": 3600,
        }
        
        record = IdempotencyRecord.from_dict(data)
        
        assert record.key == "abc123"
        assert record.event_id == "evt_123"
        assert record.ttl_seconds == 3600
    
    def test_record_roundtrip(self):
        """Test dict roundtrip."""
        original = IdempotencyRecord(
            key="abc123",
            event_id="evt_123",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
            calendar_id="primary",
            created_at=1000000.0,
            ttl_seconds=3600,
        )
        
        restored = IdempotencyRecord.from_dict(original.to_dict())
        
        assert restored.key == original.key
        assert restored.event_id == original.event_id


# ============================================================================
# IDEMPOTENCY STORE TESTS
# ============================================================================

class TestIdempotencyStore:
    """Test IdempotencyStore operations."""
    
    def test_store_creation(self, temp_store_path):
        """Test store creation."""
        store = IdempotencyStore(store_path=temp_store_path)
        assert store.count() == 0
    
    def test_store_put_and_get(self, store):
        """Test storing and retrieving records."""
        record = store.put(
            "key1",
            event_id="evt_1",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
        )
        
        assert record.key == "key1"
        
        retrieved = store.get("key1")
        assert retrieved is not None
        assert retrieved.event_id == "evt_1"
    
    def test_store_get_nonexistent(self, store):
        """Test getting nonexistent key."""
        assert store.get("nonexistent") is None
    
    def test_store_get_expired(self, store):
        """Test that expired records are not returned."""
        # Create with very short TTL
        short_store = IdempotencyStore(
            store_path=store.store_path,
            ttl_seconds=0,  # Immediate expiration
        )
        
        short_store.put(
            "key1",
            event_id="evt_1",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
        )
        
        # Should be expired immediately
        time.sleep(0.1)
        assert short_store.get("key1") is None
    
    def test_store_remove(self, store):
        """Test removing records."""
        store.put(
            "key1",
            event_id="evt_1",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
        )
        
        assert store.remove("key1") is True
        assert store.get("key1") is None
    
    def test_store_remove_nonexistent(self, store):
        """Test removing nonexistent key."""
        assert store.remove("nonexistent") is False
    
    def test_store_clear(self, store):
        """Test clearing all records."""
        store.put("key1", event_id="evt_1", event_summary="M1", event_start="", event_end="")
        store.put("key2", event_id="evt_2", event_summary="M2", event_start="", event_end="")
        
        count = store.clear()
        
        assert count == 2
        assert store.count() == 0
    
    def test_store_count(self, store):
        """Test record counting."""
        assert store.count() == 0
        
        store.put("key1", event_id="evt_1", event_summary="M1", event_start="", event_end="")
        assert store.count() == 1
        
        store.put("key2", event_id="evt_2", event_summary="M2", event_start="", event_end="")
        assert store.count() == 2
    
    def test_store_list_all(self, store):
        """Test listing all records."""
        store.put("key1", event_id="evt_1", event_summary="M1", event_start="", event_end="")
        store.put("key2", event_id="evt_2", event_summary="M2", event_start="", event_end="")
        
        records = store.list_all()
        
        assert len(records) == 2
        keys = {r.key for r in records}
        assert "key1" in keys
        assert "key2" in keys


# ============================================================================
# PERSISTENCE TESTS
# ============================================================================

class TestPersistence:
    """Test store persistence."""
    
    def test_persistence_save_and_load(self, temp_store_path):
        """Test that records persist to disk."""
        # Create and populate store
        store1 = IdempotencyStore(store_path=temp_store_path)
        store1.put(
            "key1",
            event_id="evt_1",
            event_summary="Meeting",
            event_start="2026-02-01T15:00:00",
            event_end="2026-02-01T16:00:00",
        )
        
        # Create new store instance, should load from disk
        store2 = IdempotencyStore(store_path=temp_store_path)
        
        record = store2.get("key1")
        assert record is not None
        assert record.event_id == "evt_1"
    
    def test_persistence_file_format(self, temp_store_path):
        """Test that file is valid JSON."""
        store = IdempotencyStore(store_path=temp_store_path)
        store.put("key1", event_id="evt_1", event_summary="M", event_start="", event_end="")
        
        with open(temp_store_path) as f:
            data = json.load(f)
        
        assert "version" in data
        assert "records" in data
        assert "key1" in data["records"]
    
    def test_persistence_creates_directory(self, tmp_path):
        """Test that nested directories are created."""
        nested_path = tmp_path / "deep" / "nested" / "store.json"
        store = IdempotencyStore(store_path=str(nested_path))
        store.put("key1", event_id="evt_1", event_summary="M", event_start="", event_end="")
        
        assert nested_path.exists()


# ============================================================================
# TTL AND EXPIRATION TESTS
# ============================================================================

class TestTTLExpiration:
    """Test TTL and expiration behavior."""
    
    def test_cleanup_expired(self, temp_store_path):
        """Test cleanup of expired records."""
        store = IdempotencyStore(store_path=temp_store_path, ttl_seconds=0)
        
        store.put("key1", event_id="evt_1", event_summary="M", event_start="", event_end="")
        store.put("key2", event_id="evt_2", event_summary="M", event_start="", event_end="")
        
        time.sleep(0.1)
        removed = store.cleanup_expired()
        
        assert removed == 2
        assert store.count() == 0
    
    def test_default_ttl(self):
        """Test default TTL value."""
        record = IdempotencyRecord(
            key="k",
            event_id="e",
            event_summary="s",
            event_start="",
            event_end="",
            calendar_id="primary",
            created_at=time.time(),
        )
        
        assert record.ttl_seconds == DEFAULT_TTL_SECONDS


# ============================================================================
# THREAD SAFETY TESTS
# ============================================================================

class TestThreadSafety:
    """Test thread-safe operations."""
    
    def test_concurrent_puts(self, temp_store_path):
        """Test concurrent put operations."""
        store = IdempotencyStore(store_path=temp_store_path)
        num_threads = 10
        puts_per_thread = 20
        
        def worker(thread_id: int):
            for i in range(puts_per_thread):
                store.put(
                    f"key_{thread_id}_{i}",
                    event_id=f"evt_{thread_id}_{i}",
                    event_summary=f"Meeting {thread_id}-{i}",
                    event_start="",
                    event_end="",
                )
        
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert store.count() == num_threads * puts_per_thread
    
    def test_concurrent_get_and_put(self, temp_store_path):
        """Test concurrent get and put operations."""
        store = IdempotencyStore(store_path=temp_store_path)
        store.put("shared_key", event_id="evt_0", event_summary="M", event_start="", event_end="")
        
        results = []
        
        def reader():
            for _ in range(50):
                record = store.get("shared_key")
                if record:
                    results.append(record.event_id)
        
        def writer():
            for i in range(50):
                store.put("shared_key", event_id=f"evt_{i}", event_summary="M", event_start="", event_end="")
        
        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All reads should have succeeded
        assert len(results) == 50


# ============================================================================
# DUPLICATE DETECTION TESTS
# ============================================================================

class TestDuplicateDetection:
    """Test duplicate detection functions."""
    
    def test_check_duplicate_not_found(self, store, sample_event):
        """Test no duplicate when none exists."""
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            result = check_duplicate(**sample_event)
            assert result is None
    
    def test_check_duplicate_found(self, store, sample_event):
        """Test duplicate detection."""
        # Record an event
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            record_event(**sample_event, event_id="evt_123")
            
            # Check for duplicate
            result = check_duplicate(**sample_event)
            
            assert result is not None
            assert result.event_id == "evt_123"
    
    def test_record_event(self, store, sample_event):
        """Test recording an event."""
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            record = record_event(**sample_event, event_id="evt_456")
            
            assert record.event_id == "evt_456"
            assert store.count() == 1


# ============================================================================
# CREATE WITH IDEMPOTENCY TESTS
# ============================================================================

class TestCreateWithIdempotency:
    """Test create_event_with_idempotency function."""
    
    def test_create_new_event(self, store, sample_event):
        """Test creating a new event."""
        mock_create = MagicMock(return_value={
            "ok": True,
            "event": {"id": "evt_new", "summary": sample_event["title"]},
        })
        
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            result = create_event_with_idempotency(
                **sample_event,
                create_fn=mock_create,
            )
        
        assert result["ok"] is True
        assert result["duplicate"] is False
        mock_create.assert_called_once()
    
    def test_create_duplicate_event(self, store, sample_event):
        """Test that duplicate is detected and returned."""
        # First create
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            record_event(**sample_event, event_id="evt_existing")
        
        mock_create = MagicMock()
        
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            result = create_event_with_idempotency(
                **sample_event,
                create_fn=mock_create,
            )
        
        assert result["ok"] is True
        assert result["duplicate"] is True
        assert result["event"]["id"] == "evt_existing"
        mock_create.assert_not_called()  # Should not create
    
    def test_create_failed(self, store, sample_event):
        """Test handling of creation failure."""
        mock_create = MagicMock(return_value={"ok": False, "error": "API error"})
        
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            result = create_event_with_idempotency(
                **sample_event,
                create_fn=mock_create,
            )
        
        assert result["ok"] is False
        assert store.count() == 0  # Should not record failed creation


# ============================================================================
# MESSAGE FORMATTING TESTS
# ============================================================================

class TestMessageFormatting:
    """Test user message formatting."""
    
    def test_format_duplicate_message(self):
        """Test duplicate message formatting."""
        record = IdempotencyRecord(
            key="k",
            event_id="e",
            event_summary="Team Meeting",
            event_start="2026-02-01T15:00:00+03:00",
            event_end="2026-02-01T16:00:00+03:00",
            calendar_id="primary",
            created_at=time.time(),
        )
        
        message = format_duplicate_message(record)
        
        assert "Team Meeting" in message
        assert "zaten ekli" in message
    
    def test_format_duplicate_message_invalid_date(self):
        """Test fallback for invalid date."""
        record = IdempotencyRecord(
            key="k",
            event_id="e",
            event_summary="Meeting",
            event_start="invalid-date",
            event_end="invalid-date",
            calendar_id="primary",
            created_at=time.time(),
        )
        
        message = format_duplicate_message(record)
        
        assert "Meeting" in message
        assert "zaten ekli" in message


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for full workflow."""
    
    def test_full_workflow_new_event(self, temp_store_path):
        """Test complete workflow for new event."""
        store = IdempotencyStore(store_path=temp_store_path)
        
        event_data = {
            "title": "New Meeting",
            "start": "2026-02-01T15:00:00+03:00",
            "end": "2026-02-01T16:00:00+03:00",
            "calendar_id": "primary",
        }
        
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            # First creation should succeed
            result = create_event_with_idempotency(
                **event_data,
                create_fn=lambda: {"ok": True, "event": {"id": "evt_1", "summary": "New Meeting"}},
            )
            
            assert result["ok"] is True
            assert result["duplicate"] is False
            assert store.count() == 1
    
    def test_full_workflow_duplicate_event(self, temp_store_path):
        """Test complete workflow for duplicate event."""
        store = IdempotencyStore(store_path=temp_store_path)
        
        event_data = {
            "title": "Meeting",
            "start": "2026-02-01T15:00:00+03:00",
            "end": "2026-02-01T16:00:00+03:00",
            "calendar_id": "primary",
        }
        
        call_count = 0
        
        def mock_create():
            nonlocal call_count
            call_count += 1
            return {"ok": True, "event": {"id": f"evt_{call_count}", "summary": "Meeting"}}
        
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            # First creation
            result1 = create_event_with_idempotency(**event_data, create_fn=mock_create)
            
            # Second attempt (same event)
            result2 = create_event_with_idempotency(**event_data, create_fn=mock_create)
        
        assert result1["ok"] is True
        assert result1["duplicate"] is False
        
        assert result2["ok"] is True
        assert result2["duplicate"] is True
        assert result2["event"]["id"] == "evt_1"  # Same event ID
        
        assert call_count == 1  # create_fn only called once
    
    def test_acceptance_same_command_twice(self, temp_store_path):
        """Acceptance test: same create twice => second returns 'zaten ekli'."""
        store = IdempotencyStore(store_path=temp_store_path)
        
        event_data = {
            "title": "Toplantı",
            "start": "2026-02-01T15:00:00+03:00",
            "end": "2026-02-01T16:00:00+03:00",
        }
        
        with patch("bantz.tools.calendar_idempotency.get_store", return_value=store):
            # First
            result1 = create_event_with_idempotency(
                **event_data,
                create_fn=lambda: {"ok": True, "event": {"id": "evt_1", "summary": "Toplantı"}},
            )
            
            # Second
            result2 = create_event_with_idempotency(
                **event_data,
                create_fn=lambda: {"ok": True, "event": {"id": "evt_2", "summary": "Toplantı"}},
            )
        
        assert result1["duplicate"] is False
        assert result2["duplicate"] is True
        assert "zaten ekli" in result2.get("message", "")
