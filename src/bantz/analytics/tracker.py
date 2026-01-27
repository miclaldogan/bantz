"""
Usage Analytics Tracker.

Records and analyzes command execution patterns:
- Command events with timing
- Success/failure tracking
- Intent distribution
- Error patterns
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
import logging
import sqlite3
import threading
import json

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CommandEvent:
    """Record of a command execution."""
    
    timestamp: datetime
    intent: str
    raw_transcript: str
    corrected_transcript: str
    success: bool
    execution_time_ms: int
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "intent": self.intent,
            "raw_transcript": self.raw_transcript,
            "corrected_transcript": self.corrected_transcript,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandEvent":
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            intent=data["intent"],
            raw_transcript=data["raw_transcript"],
            corrected_transcript=data["corrected_transcript"],
            success=data["success"],
            execution_time_ms=data["execution_time_ms"],
            error_message=data.get("error_message"),
            metadata=data.get("metadata"),
        )


@dataclass
class UsageStats:
    """Aggregated usage statistics."""
    
    total_commands: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_execution_time_ms: float
    top_intents: Dict[str, int]
    top_errors: Dict[str, int]
    time_range_days: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_commands": self.total_commands,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "avg_execution_time_ms": self.avg_execution_time_ms,
            "top_intents": self.top_intents,
            "top_errors": self.top_errors,
            "time_range_days": self.time_range_days,
        }


@dataclass
class FailurePattern:
    """Pattern in command failures."""
    
    intent: str
    error_message: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_transcripts: List[str]


# =============================================================================
# Usage Analytics
# =============================================================================


class UsageAnalytics:
    """
    Track and analyze usage patterns.
    
    Records all command executions with timing and success/failure info.
    Provides analytics on usage patterns and failure modes.
    
    Example:
        analytics = UsageAnalytics(Path("~/.bantz/analytics.db"))
        
        # Record command
        analytics.record(CommandEvent(
            timestamp=datetime.now(),
            intent="open_browser",
            raw_transcript="open chrome",
            corrected_transcript="open chrome",
            success=True,
            execution_time_ms=150,
        ))
        
        # Get statistics
        stats = analytics.get_stats(days=7)
        print(f"Success rate: {stats.success_rate:.1%}")
    """
    
    DEFAULT_DB_PATH = Path.home() / ".config" / "bantz" / "analytics.db"
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize usage analytics.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    raw_transcript TEXT NOT NULL,
                    corrected_transcript TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    execution_time_ms INTEGER NOT NULL,
                    error_message TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON events(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_intent 
                ON events(intent)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_success 
                ON events(success)
            """)
            conn.commit()
        finally:
            conn.close()
    
    def record(self, event: CommandEvent) -> int:
        """
        Record a command event.
        
        Args:
            event: Command event to record
            
        Returns:
            Event ID
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute("""
                    INSERT INTO events (
                        timestamp, intent, raw_transcript, 
                        corrected_transcript, success, 
                        execution_time_ms, error_message, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.timestamp.isoformat(),
                    event.intent,
                    event.raw_transcript,
                    event.corrected_transcript,
                    1 if event.success else 0,
                    event.execution_time_ms,
                    event.error_message,
                    json.dumps(event.metadata) if event.metadata else None,
                ))
                conn.commit()
                event_id = cursor.lastrowid
                logger.debug(f"Recorded event {event_id}: {event.intent}")
                return event_id
            finally:
                conn.close()
    
    def get_stats(self, days: int = 30) -> UsageStats:
        """
        Get usage statistics.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            UsageStats object
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Total commands
                total = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE timestamp > ?",
                    (cutoff_str,)
                ).fetchone()[0]
                
                # Success count
                success = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE timestamp > ? AND success = 1",
                    (cutoff_str,)
                ).fetchone()[0]
                
                # Average execution time
                avg_time = conn.execute(
                    "SELECT AVG(execution_time_ms) FROM events WHERE timestamp > ?",
                    (cutoff_str,)
                ).fetchone()[0] or 0
                
                # Top intents
                intents = conn.execute("""
                    SELECT intent, COUNT(*) as cnt 
                    FROM events WHERE timestamp > ?
                    GROUP BY intent ORDER BY cnt DESC LIMIT 10
                """, (cutoff_str,)).fetchall()
                
                # Top errors
                errors = conn.execute("""
                    SELECT error_message, COUNT(*) as cnt 
                    FROM events 
                    WHERE timestamp > ? AND success = 0 AND error_message IS NOT NULL
                    GROUP BY error_message ORDER BY cnt DESC LIMIT 10
                """, (cutoff_str,)).fetchall()
                
                return UsageStats(
                    total_commands=total,
                    success_count=success,
                    failure_count=total - success,
                    success_rate=success / total if total > 0 else 0.0,
                    avg_execution_time_ms=avg_time,
                    top_intents=dict(intents),
                    top_errors=dict(errors),
                    time_range_days=days,
                )
            finally:
                conn.close()
    
    def get_failure_patterns(self, min_count: int = 2) -> List[FailurePattern]:
        """
        Analyze failure patterns.
        
        Args:
            min_count: Minimum occurrences to include
            
        Returns:
            List of failure patterns
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Group failures by intent and error
                patterns = conn.execute("""
                    SELECT 
                        intent, 
                        error_message,
                        COUNT(*) as cnt,
                        MIN(timestamp) as first_seen,
                        MAX(timestamp) as last_seen,
                        GROUP_CONCAT(raw_transcript, '|||') as samples
                    FROM events 
                    WHERE success = 0 AND error_message IS NOT NULL
                    GROUP BY intent, error_message
                    HAVING cnt >= ?
                    ORDER BY cnt DESC
                """, (min_count,)).fetchall()
                
                result = []
                for row in patterns:
                    intent, error, count, first, last, samples = row
                    sample_list = samples.split("|||")[:5] if samples else []
                    
                    result.append(FailurePattern(
                        intent=intent,
                        error_message=error,
                        count=count,
                        first_seen=datetime.fromisoformat(first),
                        last_seen=datetime.fromisoformat(last),
                        sample_transcripts=sample_list,
                    ))
                
                return result
            finally:
                conn.close()
    
    def get_intent_stats(self, intent: str, days: int = 30) -> Dict[str, Any]:
        """
        Get statistics for a specific intent.
        
        Args:
            intent: Intent to analyze
            days: Number of days to analyze
            
        Returns:
            Statistics dictionary
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                total = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE intent = ? AND timestamp > ?",
                    (intent, cutoff)
                ).fetchone()[0]
                
                success = conn.execute(
                    "SELECT COUNT(*) FROM events WHERE intent = ? AND timestamp > ? AND success = 1",
                    (intent, cutoff)
                ).fetchone()[0]
                
                avg_time = conn.execute(
                    "SELECT AVG(execution_time_ms) FROM events WHERE intent = ? AND timestamp > ?",
                    (intent, cutoff)
                ).fetchone()[0] or 0
                
                return {
                    "intent": intent,
                    "total": total,
                    "success": success,
                    "failure": total - success,
                    "success_rate": success / total if total > 0 else 0.0,
                    "avg_execution_time_ms": avg_time,
                }
            finally:
                conn.close()
    
    def get_hourly_distribution(self, days: int = 7) -> Dict[int, int]:
        """
        Get command distribution by hour of day.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary mapping hour (0-23) to command count
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                rows = conn.execute("""
                    SELECT 
                        CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                        COUNT(*) as cnt
                    FROM events 
                    WHERE timestamp > ?
                    GROUP BY hour
                """, (cutoff,)).fetchall()
                
                # Initialize all hours
                distribution = {h: 0 for h in range(24)}
                for hour, count in rows:
                    distribution[hour] = count
                
                return distribution
            finally:
                conn.close()
    
    def get_recent_events(self, limit: int = 100) -> List[CommandEvent]:
        """
        Get recent command events.
        
        Args:
            limit: Maximum number of events
            
        Returns:
            List of recent events
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                rows = conn.execute("""
                    SELECT 
                        timestamp, intent, raw_transcript, corrected_transcript,
                        success, execution_time_ms, error_message, metadata
                    FROM events
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                
                events = []
                for row in rows:
                    events.append(CommandEvent(
                        timestamp=datetime.fromisoformat(row[0]),
                        intent=row[1],
                        raw_transcript=row[2],
                        corrected_transcript=row[3],
                        success=bool(row[4]),
                        execution_time_ms=row[5],
                        error_message=row[6],
                        metadata=json.loads(row[7]) if row[7] else None,
                    ))
                
                return events
            finally:
                conn.close()
    
    def get_sequence_patterns(self, min_support: int = 3) -> List[Tuple[str, str, int]]:
        """
        Find common command sequences.
        
        Args:
            min_support: Minimum occurrences to include
            
        Returns:
            List of (intent1, intent2, count) tuples
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Get all intents in order
                rows = conn.execute("""
                    SELECT intent FROM events ORDER BY timestamp
                """).fetchall()
                
                if len(rows) < 2:
                    return []
                
                # Count pairs
                pairs = Counter()
                for i in range(len(rows) - 1):
                    pair = (rows[i][0], rows[i + 1][0])
                    pairs[pair] += 1
                
                # Filter by min_support
                result = [
                    (a, b, count)
                    for (a, b), count in pairs.most_common()
                    if count >= min_support
                ]
                
                return result
            finally:
                conn.close()
    
    def cleanup_old_events(self, days: int = 90) -> int:
        """
        Delete events older than specified days.
        
        Args:
            days: Events older than this will be deleted
            
        Returns:
            Number of deleted events
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute(
                    "DELETE FROM events WHERE timestamp < ?",
                    (cutoff,)
                )
                conn.commit()
                deleted = cursor.rowcount
                
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old events")
                
                return deleted
            finally:
                conn.close()
    
    def clear_all(self) -> int:
        """
        Delete all events.
        
        Returns:
            Number of deleted events
        """
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute("DELETE FROM events")
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()


# =============================================================================
# Mock Implementation
# =============================================================================


class MockUsageAnalytics(UsageAnalytics):
    """Mock usage analytics for testing."""
    
    def __init__(self, *args, **kwargs):
        # Don't use database - store in memory
        self._events: List[CommandEvent] = []
        self._lock = threading.Lock()
        self._next_id = 1
    
    def _init_db(self) -> None:
        """No database initialization needed."""
        pass
    
    def record(self, event: CommandEvent) -> int:
        """Record to memory."""
        with self._lock:
            self._events.append(event)
            event_id = self._next_id
            self._next_id += 1
            return event_id
    
    def get_stats(self, days: int = 30) -> UsageStats:
        """Get stats from memory."""
        cutoff = datetime.now() - timedelta(days=days)
        
        with self._lock:
            events = [e for e in self._events if e.timestamp > cutoff]
            
            if not events:
                return UsageStats(
                    total_commands=0,
                    success_count=0,
                    failure_count=0,
                    success_rate=0.0,
                    avg_execution_time_ms=0.0,
                    top_intents={},
                    top_errors={},
                    time_range_days=days,
                )
            
            success = sum(1 for e in events if e.success)
            intents = Counter(e.intent for e in events)
            errors = Counter(
                e.error_message for e in events 
                if not e.success and e.error_message
            )
            
            return UsageStats(
                total_commands=len(events),
                success_count=success,
                failure_count=len(events) - success,
                success_rate=success / len(events),
                avg_execution_time_ms=sum(e.execution_time_ms for e in events) / len(events),
                top_intents=dict(intents.most_common(10)),
                top_errors=dict(errors.most_common(10)),
                time_range_days=days,
            )
    
    def get_failure_patterns(self, min_count: int = 2) -> List[FailurePattern]:
        """Get failure patterns from memory."""
        with self._lock:
            failures = [e for e in self._events if not e.success and e.error_message]
            
            # Group by intent + error
            groups: Dict[Tuple[str, str], List[CommandEvent]] = {}
            for e in failures:
                key = (e.intent, e.error_message)
                if key not in groups:
                    groups[key] = []
                groups[key].append(e)
            
            patterns = []
            for (intent, error), events in groups.items():
                if len(events) >= min_count:
                    patterns.append(FailurePattern(
                        intent=intent,
                        error_message=error,
                        count=len(events),
                        first_seen=min(e.timestamp for e in events),
                        last_seen=max(e.timestamp for e in events),
                        sample_transcripts=[e.raw_transcript for e in events[:5]],
                    ))
            
            return sorted(patterns, key=lambda p: p.count, reverse=True)
    
    def get_recent_events(self, limit: int = 100) -> List[CommandEvent]:
        """Get recent events from memory."""
        with self._lock:
            return sorted(self._events, key=lambda e: e.timestamp, reverse=True)[:limit]
    
    def get_hourly_distribution(self, days: int = 7) -> Dict[int, int]:
        """Get hourly distribution from memory."""
        cutoff = datetime.now() - timedelta(days=days)
        
        with self._lock:
            distribution = {h: 0 for h in range(24)}
            for e in self._events:
                if e.timestamp > cutoff:
                    distribution[e.timestamp.hour] += 1
            return distribution
    
    def get_sequence_patterns(self, min_support: int = 3) -> List[Tuple[str, str, int]]:
        """Get sequence patterns from memory."""
        with self._lock:
            if len(self._events) < 2:
                return []
            
            # Sort by timestamp
            sorted_events = sorted(self._events, key=lambda e: e.timestamp)
            
            # Count pairs
            pairs: Dict[Tuple[str, str], int] = {}
            for i in range(len(sorted_events) - 1):
                pair = (sorted_events[i].intent, sorted_events[i + 1].intent)
                pairs[pair] = pairs.get(pair, 0) + 1
            
            # Filter by min_support
            result = [
                (a, b, count)
                for (a, b), count in sorted(pairs.items(), key=lambda x: x[1], reverse=True)
                if count >= min_support
            ]
            
            return result
    
    def clear_all(self) -> int:
        """Clear memory."""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            return count
