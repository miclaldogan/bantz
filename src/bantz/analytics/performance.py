"""
Performance Metrics.

Track and analyze performance of various operations:
- Execution time tracking
- Statistical analysis
- Performance reports
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Iterator, Tuple
from contextlib import contextmanager
from datetime import datetime
import logging
import time
import threading
import statistics

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class OperationStats:
    """Statistics for an operation."""
    
    operation: str
    count: int
    min_ms: float
    max_ms: float
    avg_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    total_ms: float
    std_dev_ms: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "operation": self.operation,
            "count": self.count,
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
            "median_ms": round(self.median_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "total_ms": round(self.total_ms, 2),
            "std_dev_ms": round(self.std_dev_ms, 2),
        }


@dataclass
class TimingRecord:
    """Individual timing record."""
    
    operation: str
    duration_ms: float
    timestamp: datetime
    success: bool = True
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# Performance Tracker
# =============================================================================


class PerformanceTracker:
    """
    Track performance metrics for operations.
    
    Provides context managers for easy timing and statistical analysis.
    
    Example:
        perf = PerformanceTracker()
        
        # Track with context manager
        with perf.track("asr_transcription"):
            text = asr.transcribe(audio)
        
        # Track with context manager
        with perf.track("llm_response"):
            response = llm.complete(prompt)
        
        # Get statistics
        stats = perf.get_stats("asr_transcription")
        print(f"ASR avg: {stats.avg_ms:.1f}ms")
        
        # Get full report
        report = perf.report()
    """
    
    def __init__(self, max_samples: int = 10000):
        """
        Initialize performance tracker.
        
        Args:
            max_samples: Maximum samples to keep per operation
        """
        self.max_samples = max_samples
        self._metrics: Dict[str, List[float]] = {}
        self._records: Dict[str, List[TimingRecord]] = {}
        self._lock = threading.Lock()
    
    @contextmanager
    def track(
        self,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[None]:
        """
        Context manager to track execution time.
        
        Args:
            operation: Operation name
            metadata: Optional metadata to record
            
        Yields:
            None
        """
        start = time.perf_counter()
        success = True
        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._record_timing(operation, elapsed_ms, success, metadata)
    
    def _record_timing(
        self,
        operation: str,
        duration_ms: float,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a timing measurement."""
        with self._lock:
            # Simple metrics list
            if operation not in self._metrics:
                self._metrics[operation] = []
            
            self._metrics[operation].append(duration_ms)
            
            # Trim if too many samples
            if len(self._metrics[operation]) > self.max_samples:
                self._metrics[operation] = self._metrics[operation][-self.max_samples:]
            
            # Detailed records
            if operation not in self._records:
                self._records[operation] = []
            
            self._records[operation].append(TimingRecord(
                operation=operation,
                duration_ms=duration_ms,
                timestamp=datetime.now(),
                success=success,
                metadata=metadata,
            ))
            
            if len(self._records[operation]) > self.max_samples:
                self._records[operation] = self._records[operation][-self.max_samples:]
    
    def record(
        self,
        operation: str,
        duration_ms: float,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Manually record a timing.
        
        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            success: Whether operation succeeded
            metadata: Optional metadata
        """
        self._record_timing(operation, duration_ms, success, metadata)
    
    def get_stats(self, operation: str) -> Optional[OperationStats]:
        """
        Get statistics for an operation.
        
        Args:
            operation: Operation name
            
        Returns:
            OperationStats or None if no data
        """
        with self._lock:
            times = self._metrics.get(operation, [])
            
            if not times:
                return None
            
            sorted_times = sorted(times)
            count = len(times)
            
            # Calculate percentiles
            p95_idx = int(count * 0.95)
            p99_idx = int(count * 0.99)
            
            return OperationStats(
                operation=operation,
                count=count,
                min_ms=min(times),
                max_ms=max(times),
                avg_ms=statistics.mean(times),
                median_ms=statistics.median(times),
                p95_ms=sorted_times[min(p95_idx, count - 1)],
                p99_ms=sorted_times[min(p99_idx, count - 1)],
                total_ms=sum(times),
                std_dev_ms=statistics.stdev(times) if count > 1 else 0.0,
            )
    
    def report(self) -> Dict[str, OperationStats]:
        """
        Get full performance report.
        
        Returns:
            Dictionary mapping operation names to stats
        """
        with self._lock:
            operations = list(self._metrics.keys())
        
        report = {}
        for op in operations:
            stats = self.get_stats(op)
            if stats:
                report[op] = stats
        
        return report
    
    def report_dict(self) -> Dict[str, Dict[str, Any]]:
        """
        Get performance report as dictionaries.
        
        Returns:
            Dictionary of operation stats as dicts
        """
        return {op: stats.to_dict() for op, stats in self.report().items()}
    
    def list_operations(self) -> List[str]:
        """
        List all tracked operations.
        
        Returns:
            List of operation names
        """
        with self._lock:
            return list(self._metrics.keys())
    
    def get_recent(
        self,
        operation: str,
        limit: int = 100,
    ) -> List[TimingRecord]:
        """
        Get recent timing records.
        
        Args:
            operation: Operation name
            limit: Maximum records to return
            
        Returns:
            List of recent records
        """
        with self._lock:
            records = self._records.get(operation, [])
            return records[-limit:][::-1]  # Most recent first
    
    def get_slow_operations(
        self,
        threshold_ms: float = 1000,
        limit: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        Get operations that exceed threshold.
        
        Args:
            threshold_ms: Time threshold
            limit: Maximum results
            
        Returns:
            List of (operation, max_time) tuples
        """
        with self._lock:
            slow = []
            for op, times in self._metrics.items():
                max_time = max(times) if times else 0
                if max_time >= threshold_ms:
                    slow.append((op, max_time))
            
            return sorted(slow, key=lambda x: x[1], reverse=True)[:limit]
    
    def compare_operations(
        self,
        op1: str,
        op2: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Compare two operations.
        
        Args:
            op1: First operation
            op2: Second operation
            
        Returns:
            Comparison dictionary or None
        """
        stats1 = self.get_stats(op1)
        stats2 = self.get_stats(op2)
        
        if not stats1 or not stats2:
            return None
        
        return {
            "operations": [op1, op2],
            "avg_diff_ms": stats1.avg_ms - stats2.avg_ms,
            "avg_ratio": stats1.avg_ms / stats2.avg_ms if stats2.avg_ms > 0 else 0,
            op1: stats1.to_dict(),
            op2: stats2.to_dict(),
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get overall summary.
        
        Returns:
            Summary dictionary
        """
        report = self.report()
        
        if not report:
            return {
                "total_operations": 0,
                "total_measurements": 0,
            }
        
        total_measurements = sum(s.count for s in report.values())
        total_time_ms = sum(s.total_ms for s in report.values())
        
        # Find slowest operation
        slowest = max(report.values(), key=lambda s: s.avg_ms)
        # Find most called operation
        most_called = max(report.values(), key=lambda s: s.count)
        
        return {
            "total_operations": len(report),
            "total_measurements": total_measurements,
            "total_time_ms": round(total_time_ms, 2),
            "slowest_operation": slowest.operation,
            "slowest_avg_ms": round(slowest.avg_ms, 2),
            "most_called_operation": most_called.operation,
            "most_called_count": most_called.count,
        }
    
    def reset(self, operation: Optional[str] = None) -> None:
        """
        Reset metrics.
        
        Args:
            operation: Specific operation to reset (all if None)
        """
        with self._lock:
            if operation:
                self._metrics.pop(operation, None)
                self._records.pop(operation, None)
            else:
                self._metrics.clear()
                self._records.clear()


# =============================================================================
# Mock Implementation
# =============================================================================


class MockPerformanceTracker(PerformanceTracker):
    """Mock performance tracker for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._track_calls: List[Tuple[str, Optional[Dict]]] = []
    
    @contextmanager
    def track(
        self,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[None]:
        """Track calls for testing."""
        self._track_calls.append((operation, metadata))
        start = time.perf_counter()
        success = True
        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._record_timing(operation, elapsed_ms, success, metadata)
    
    def get_track_calls(self) -> List[Tuple[str, Optional[Dict]]]:
        """Get all track() calls."""
        return self._track_calls.copy()
    
    def simulate_timing(
        self,
        operation: str,
        times: List[float],
    ) -> None:
        """
        Simulate timing data for testing.
        
        Args:
            operation: Operation name
            times: List of durations to add
        """
        for t in times:
            self.record(operation, t)
