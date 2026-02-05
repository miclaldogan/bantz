"""Tests for calendar event cache module.

Issue #315: Yeni eklenen etkinlik list_events'te görünmüyor

Tests cover:
- CachedEvent creation and expiration
- CalendarEventCache operations
- Event merging with API results
- Time window filtering
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from bantz.google.calendar_cache import (
    CachedEvent,
    CalendarEventCache,
    DEFAULT_CACHE_TTL_SECONDS,
    cache_created_event,
    get_calendar_cache,
    get_merged_events,
    reset_calendar_cache,
)


# =============================================================================
# CachedEvent Tests
# =============================================================================

class TestCachedEvent:
    """Tests for CachedEvent dataclass."""
    
    def test_creation(self) -> None:
        """Test creating a cached event."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert event.event_id == "abc123"
        assert event.summary == "Meeting"
        assert event.status == "confirmed"
        assert event.calendar_id == "primary"
    
    def test_is_expired_false(self) -> None:
        """Test event is not expired when fresh."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert event.is_expired() is False
    
    def test_is_expired_true(self) -> None:
        """Test event is expired after TTL."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS + 10)
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
            created_at=old_time,
        )
        assert event.is_expired() is True
    
    def test_to_event_dict(self) -> None:
        """Test conversion to event dict."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
            location="Office",
        )
        d = event.to_event_dict()
        assert d["id"] == "abc123"
        assert d["summary"] == "Meeting"
        assert d["start"] == "2026-02-05T17:00:00+03:00"
        assert d["end"] == "2026-02-05T18:00:00+03:00"
        assert d["location"] == "Office"
        assert d["_cached"] is True
    
    def test_is_in_window_no_filter(self) -> None:
        """Test in window with no time filter."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert event.is_in_window(None, None) is True
    
    def test_is_in_window_inside(self) -> None:
        """Test event inside window."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert event.is_in_window(
            "2026-02-05T00:00:00+03:00",
            "2026-02-05T23:59:00+03:00",
        ) is True
    
    def test_is_in_window_before(self) -> None:
        """Test event before window."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-04T17:00:00+03:00",
            end="2026-02-04T18:00:00+03:00",
        )
        assert event.is_in_window(
            "2026-02-05T00:00:00+03:00",
            "2026-02-05T23:59:00+03:00",
        ) is False
    
    def test_is_in_window_after(self) -> None:
        """Test event after window."""
        event = CachedEvent(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-06T17:00:00+03:00",
            end="2026-02-06T18:00:00+03:00",
        )
        assert event.is_in_window(
            "2026-02-05T00:00:00+03:00",
            "2026-02-05T23:59:00+03:00",
        ) is False
    
    def test_is_in_window_all_day_event(self) -> None:
        """Test all-day event in window."""
        event = CachedEvent(
            event_id="abc123",
            summary="Conference",
            start="2026-02-05",
            end="2026-02-06",
        )
        assert event.is_in_window(
            "2026-02-05T00:00:00+03:00",
            "2026-02-05T23:59:00+03:00",
        ) is True


# =============================================================================
# CalendarEventCache Tests
# =============================================================================

class TestCalendarEventCache:
    """Tests for CalendarEventCache class."""
    
    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_calendar_cache()
    
    def test_add_event(self) -> None:
        """Test adding an event to cache."""
        cache = CalendarEventCache()
        event = cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert event.event_id == "abc123"
        assert cache.size == 1
    
    def test_add_multiple_events(self) -> None:
        """Test adding multiple events."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="abc123",
            summary="Meeting 1",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        cache.add_event(
            event_id="def456",
            summary="Meeting 2",
            start="2026-02-05T19:00:00+03:00",
            end="2026-02-05T20:00:00+03:00",
        )
        assert cache.size == 2
    
    def test_remove_event(self) -> None:
        """Test removing an event from cache."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert cache.remove_event("abc123") is True
        assert cache.size == 0
    
    def test_remove_nonexistent_event(self) -> None:
        """Test removing non-existent event."""
        cache = CalendarEventCache()
        assert cache.remove_event("nonexistent") is False
    
    def test_get_events_in_window(self) -> None:
        """Test getting events in a time window."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        events = cache.get_events_in_window(
            time_min="2026-02-05T00:00:00+03:00",
            time_max="2026-02-05T23:59:00+03:00",
        )
        assert len(events) == 1
        assert events[0].event_id == "abc123"
    
    def test_get_events_outside_window(self) -> None:
        """Test getting events outside window returns empty."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        events = cache.get_events_in_window(
            time_min="2026-02-06T00:00:00+03:00",
            time_max="2026-02-06T23:59:00+03:00",
        )
        assert len(events) == 0
    
    def test_merge_with_api_events(self) -> None:
        """Test merging with API events."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="cached123",
            summary="Cached Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        api_events = [
            {
                "id": "api456",
                "summary": "API Meeting",
                "start": "2026-02-05T10:00:00+03:00",
                "end": "2026-02-05T11:00:00+03:00",
            }
        ]
        
        merged = cache.merge_with_api_events(
            api_events,
            time_min="2026-02-05T00:00:00+03:00",
            time_max="2026-02-05T23:59:00+03:00",
        )
        
        assert len(merged) == 2
        assert merged[0]["id"] == "api456"  # Earlier event first
        assert merged[1]["id"] == "cached123"
    
    def test_merge_deduplicates_by_id(self) -> None:
        """Test that merge deduplicates by ID."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="same123",
            summary="Cached Version",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        api_events = [
            {
                "id": "same123",
                "summary": "API Version",
                "start": "2026-02-05T17:00:00+03:00",
                "end": "2026-02-05T18:00:00+03:00",
            }
        ]
        
        merged = cache.merge_with_api_events(
            api_events,
            time_min="2026-02-05T00:00:00+03:00",
            time_max="2026-02-05T23:59:00+03:00",
        )
        
        # Should have only 1 event (API version takes precedence)
        assert len(merged) == 1
        assert merged[0]["id"] == "same123"
        assert merged[0]["summary"] == "API Version"
    
    def test_clear(self) -> None:
        """Test clearing cache."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        count = cache.clear()
        assert count == 1
        assert cache.size == 0
    
    def test_get_stats(self) -> None:
        """Test getting cache stats."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        stats = cache.get_stats()
        assert stats["size"] == 1
        assert len(stats["events"]) == 1
        assert stats["events"][0]["id"] == "abc123"
    
    def test_custom_ttl(self) -> None:
        """Test custom TTL setting."""
        cache = CalendarEventCache(ttl_seconds=60)
        assert cache._ttl_seconds == 60


# =============================================================================
# Singleton and Convenience Function Tests
# =============================================================================

class TestSingletonAndConvenienceFunctions:
    """Tests for singleton and convenience functions."""
    
    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_calendar_cache()
    
    def test_get_calendar_cache_singleton(self) -> None:
        """Test that get_calendar_cache returns singleton."""
        cache1 = get_calendar_cache()
        cache2 = get_calendar_cache()
        assert cache1 is cache2
    
    def test_reset_calendar_cache(self) -> None:
        """Test resetting the singleton."""
        cache1 = get_calendar_cache()
        cache1.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        reset_calendar_cache()
        cache2 = get_calendar_cache()
        assert cache2.size == 0
    
    def test_cache_created_event(self) -> None:
        """Test convenience function to cache event."""
        event = cache_created_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        assert event.event_id == "abc123"
        assert get_calendar_cache().size == 1
    
    def test_get_merged_events(self) -> None:
        """Test convenience function to merge events."""
        cache_created_event(
            event_id="cached123",
            summary="Cached",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        api_events: list[dict[str, Any]] = []
        merged = get_merged_events(
            api_events,
            time_min="2026-02-05T00:00:00+03:00",
            time_max="2026-02-05T23:59:00+03:00",
        )
        
        assert len(merged) == 1
        assert merged[0]["id"] == "cached123"


# =============================================================================
# Thread Safety Tests
# =============================================================================

class TestThreadSafety:
    """Tests for thread safety."""
    
    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_calendar_cache()
    
    def test_concurrent_add(self) -> None:
        """Test concurrent add operations."""
        import threading
        
        cache = CalendarEventCache()
        
        def add_events(start_id: int) -> None:
            for i in range(10):
                cache.add_event(
                    event_id=f"event_{start_id}_{i}",
                    summary=f"Meeting {start_id}_{i}",
                    start="2026-02-05T17:00:00+03:00",
                    end="2026-02-05T18:00:00+03:00",
                )
        
        threads = [threading.Thread(target=add_events, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert cache.size == 50


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for calendar cache."""
    
    def setup_method(self) -> None:
        """Reset cache before each test."""
        reset_calendar_cache()
    
    def test_create_then_list_scenario(self) -> None:
        """Test the create-then-list scenario from issue #315."""
        # Simulate creating an event
        cache_created_event(
            event_id="new_meeting_123",
            summary="toplantı",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        # Simulate API returning empty (hasn't synced yet)
        api_events: list[dict[str, Any]] = []
        
        # Merge should include cached event
        merged = get_merged_events(
            api_events,
            time_min="2026-02-05T00:00:00+03:00",
            time_max="2026-02-05T23:59:00+03:00",
        )
        
        assert len(merged) == 1
        assert merged[0]["summary"] == "toplantı"
    
    def test_delete_removes_from_cache(self) -> None:
        """Test that deleting an event removes it from cache."""
        cache = get_calendar_cache()
        cache_created_event(
            event_id="to_delete_123",
            summary="Will be deleted",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        # Remove from cache
        cache.remove_event("to_delete_123")
        
        # Should not appear in merged
        merged = get_merged_events(
            [],
            time_min="2026-02-05T00:00:00+03:00",
            time_max="2026-02-05T23:59:00+03:00",
        )
        
        assert len(merged) == 0
    
    def test_cache_expires_after_ttl(self) -> None:
        """Test that cached events expire after TTL."""
        cache = CalendarEventCache(ttl_seconds=1)  # 1 second TTL
        cache.add_event(
            event_id="short_lived",
            summary="Will expire",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        import time
        time.sleep(1.5)  # Wait for expiration
        
        events = cache.get_events_in_window()
        assert len(events) == 0
    
    def test_multiple_calendars(self) -> None:
        """Test events on different calendars are separated."""
        cache = CalendarEventCache()
        cache.add_event(
            event_id="primary_event",
            summary="Primary Calendar Event",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
            calendar_id="primary",
        )
        cache.add_event(
            event_id="work_event",
            summary="Work Calendar Event",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
            calendar_id="work@example.com",
        )
        
        primary_events = cache.get_events_in_window(calendar_id="primary")
        work_events = cache.get_events_in_window(calendar_id="work@example.com")
        
        assert len(primary_events) == 1
        assert len(work_events) == 1
        assert primary_events[0].event_id == "primary_event"
        assert work_events[0].event_id == "work_event"
