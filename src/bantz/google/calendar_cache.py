"""Calendar event cache for immediate visibility of new events.

Issue #315: Yeni eklenen etkinlik list_events'te görünmüyor

Problem:
- Google Calendar API'de create sonrası list'te görünme gecikmesi olabiliyor
- Kullanıcı "toplantı koy" dedikten hemen sonra "bugün için planım var mı" dediğinde
  yeni etkinlik görünmeyebiliyor

Çözüm:
- Yeni oluşturulan event'leri in-memory cache'de tutuyoruz
- list_events sonuçlarına cache'deki event'leri merge ediyoruz
- Cache TTL: 5 dakika (API sync edilince gereksiz hale gelir)
- Session-scoped: Terminal kapanınca cache temizlenir
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import threading


# Default cache TTL in seconds
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class CachedEvent:
    """A recently created calendar event held in cache."""
    
    event_id: str
    summary: str
    start: str  # ISO format
    end: str    # ISO format
    location: Optional[str] = None
    description: Optional[str] = None
    calendar_id: str = "primary"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "confirmed"
    
    def is_expired(self, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> bool:
        """Check if this cached event has expired."""
        age = datetime.now(timezone.utc) - self.created_at
        return age.total_seconds() > ttl_seconds
    
    def to_event_dict(self) -> dict[str, Any]:
        """Convert to standard event dict format for merging.

        Matches the Google Calendar API format where ``start`` and ``end``
        are dicts with either ``dateTime`` (timed events) or ``date``
        (all-day events) keys.
        """
        def _wrap_dt(value: str) -> dict[str, str]:
            """Wrap an ISO string in the Google-API style dict."""
            v = (value or "").strip()
            # All-day dates are exactly YYYY-MM-DD (10 chars)
            if len(v) == 10 and v[4] == "-" and v[7] == "-":
                return {"date": v}
            return {"dateTime": v}

        return {
            "id": self.event_id,
            "summary": self.summary,
            "start": _wrap_dt(self.start),
            "end": _wrap_dt(self.end),
            "location": self.location,
            "status": self.status,
            "htmlLink": None,  # Won't have link until API sync
            "_cached": True,  # Flag for debugging
        }
    
    def is_in_window(self, time_min: Optional[str], time_max: Optional[str]) -> bool:
        """Check if event falls within a time window."""
        if not time_min:
            return True  # No filter
        
        try:
            event_start = _parse_datetime(self.start)
            window_min = _parse_datetime(time_min)
            
            if event_start < window_min:
                return False
            
            if time_max:
                window_max = _parse_datetime(time_max)
                if event_start >= window_max:
                    return False
            
            return True
        except (ValueError, TypeError):
            # If parsing fails, include event to be safe
            return True


def _parse_datetime(value: str) -> datetime:
    """Parse ISO datetime string."""
    v = (value or "").strip()
    if not v:
        raise ValueError("empty datetime")
    
    # Handle all-day dates (YYYY-MM-DD)
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        from datetime import date
        d = date.fromisoformat(v)
        return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
    
    # Handle Z suffix
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class CalendarEventCache:
    """Thread-safe cache for recently created calendar events.
    
    This cache ensures that newly created events appear immediately in
    list_events results, even before the Google Calendar API syncs.
    
    Usage:
        cache = get_calendar_cache()
        
        # After creating an event
        cache.add_event(
            event_id="abc123",
            summary="Meeting",
            start="2026-02-05T17:00:00+03:00",
            end="2026-02-05T18:00:00+03:00",
        )
        
        # When listing events
        api_events = [...]  # From Google API
        merged = cache.merge_with_api_events(api_events, time_min=..., time_max=...)
    """
    
    def __init__(self, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._events: dict[str, CachedEvent] = {}
        self._lock = threading.RLock()
        self._ttl_seconds = ttl_seconds
    
    def add_event(
        self,
        *,
        event_id: str,
        summary: str,
        start: str,
        end: str,
        location: Optional[str] = None,
        description: Optional[str] = None,
        calendar_id: str = "primary",
    ) -> CachedEvent:
        """Add a newly created event to cache."""
        with self._lock:
            event = CachedEvent(
                event_id=event_id,
                summary=summary,
                start=start,
                end=end,
                location=location,
                description=description,
                calendar_id=calendar_id,
            )
            self._events[event_id] = event
            self._cleanup_expired()
            return event
    
    def remove_event(self, event_id: str) -> bool:
        """Remove an event from cache (e.g., after deletion)."""
        with self._lock:
            if event_id in self._events:
                del self._events[event_id]
                return True
            return False
    
    def get_events_in_window(
        self,
        *,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        calendar_id: str = "primary",
    ) -> list[CachedEvent]:
        """Get cached events within a time window."""
        with self._lock:
            self._cleanup_expired()
            
            result = []
            for event in self._events.values():
                if event.calendar_id != calendar_id:
                    continue
                if event.is_in_window(time_min, time_max):
                    result.append(event)
            
            return result
    
    def merge_with_api_events(
        self,
        api_events: list[dict[str, Any]],
        *,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        """Merge API events with cached events, deduplicating by ID.
        
        Cached events are added if they:
        1. Fall within the time window
        2. Are not already in API results (by ID)
        3. Are not expired
        
        Returns events sorted by start time.
        """
        # Get API event IDs for deduplication
        api_ids = {e.get("id") for e in api_events if e.get("id")}
        
        # Get cached events in window
        cached = self.get_events_in_window(
            time_min=time_min,
            time_max=time_max,
            calendar_id=calendar_id,
        )
        
        # Add cached events not in API results
        result = list(api_events)
        for event in cached:
            if event.event_id not in api_ids:
                result.append(event.to_event_dict())
        
        # Sort by start time
        def sort_key(e: dict) -> str:
            start = e.get("start", "")
            if isinstance(start, dict):
                start = start.get("dateTime") or start.get("date") or ""
            return start or ""
        
        result.sort(key=sort_key)
        return result
    
    def clear(self) -> int:
        """Clear all cached events. Returns count cleared."""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            return count
    
    def _cleanup_expired(self) -> int:
        """Remove expired events. Returns count removed."""
        expired_ids = [
            eid for eid, event in self._events.items()
            if event.is_expired(self._ttl_seconds)
        ]
        for eid in expired_ids:
            del self._events[eid]
        return len(expired_ids)
    
    @property
    def size(self) -> int:
        """Number of events in cache."""
        with self._lock:
            return len(self._events)
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            self._cleanup_expired()
            return {
                "size": len(self._events),
                "ttl_seconds": self._ttl_seconds,
                "events": [
                    {
                        "id": e.event_id,
                        "summary": e.summary,
                        "start": e.start,
                        "age_seconds": (datetime.now(timezone.utc) - e.created_at).total_seconds(),
                    }
                    for e in self._events.values()
                ],
            }


# Singleton instance
_calendar_cache: Optional[CalendarEventCache] = None
_cache_lock = threading.Lock()


def get_calendar_cache() -> CalendarEventCache:
    """Get the singleton calendar event cache."""
    global _calendar_cache
    with _cache_lock:
        if _calendar_cache is None:
            _calendar_cache = CalendarEventCache()
        return _calendar_cache


def reset_calendar_cache() -> None:
    """Reset the calendar cache (for testing)."""
    global _calendar_cache
    with _cache_lock:
        _calendar_cache = None


def cache_created_event(
    *,
    event_id: str,
    summary: str,
    start: str,
    end: str,
    location: Optional[str] = None,
    description: Optional[str] = None,
    calendar_id: str = "primary",
) -> CachedEvent:
    """Convenience function to cache a newly created event."""
    cache = get_calendar_cache()
    return cache.add_event(
        event_id=event_id,
        summary=summary,
        start=start,
        end=end,
        location=location,
        description=description,
        calendar_id=calendar_id,
    )


def get_merged_events(
    api_events: list[dict[str, Any]],
    *,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    calendar_id: str = "primary",
) -> list[dict[str, Any]]:
    """Convenience function to merge API events with cache."""
    cache = get_calendar_cache()
    return cache.merge_with_api_events(
        api_events,
        time_min=time_min,
        time_max=time_max,
        calendar_id=calendar_id,
    )
