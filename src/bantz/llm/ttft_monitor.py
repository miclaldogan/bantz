"""TTFT (Time To First Token) Monitoring System (Issue #158).

This module provides comprehensive TTFT tracking for "Jarvis feel" UX:
- Real-time TTFT measurement
- Statistical aggregation (p50, p95, p99)
- Alert system for threshold violations
- Dashboard integration ready
- Performance regression detection
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List, Dict, Any
import statistics

logger = logging.getLogger(__name__)


@dataclass
class TTFTMeasurement:
    """Single TTFT measurement."""
    
    timestamp: float
    ttft_ms: int
    model: str
    backend: str
    phase: str  # "router" | "finalizer" | "other"
    total_tokens: int = 0
    
    # Context
    request_id: Optional[str] = None
    user_input: Optional[str] = None


@dataclass
class TTFTStatistics:
    """TTFT statistics for a model/phase."""
    
    phase: str
    model: str
    backend: str
    
    # Measurements
    count: int = 0
    measurements: List[int] = field(default_factory=list)
    
    # Statistics
    min_ms: int = 0
    max_ms: int = 0
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    
    # Thresholds
    threshold_ms: Optional[int] = None
    violations: int = 0
    
    def add_measurement(self, ttft_ms: int):
        """Add a new TTFT measurement."""
        self.count += 1
        self.measurements.append(ttft_ms)
        
        # Update statistics
        self.min_ms = min(self.measurements)
        self.max_ms = max(self.measurements)
        self.mean_ms = statistics.mean(self.measurements)
        self.median_ms = statistics.median(self.measurements)
        
        # Percentiles
        sorted_measurements = sorted(self.measurements)
        self.p50_ms = self._percentile(sorted_measurements, 50)
        self.p95_ms = self._percentile(sorted_measurements, 95)
        self.p99_ms = self._percentile(sorted_measurements, 99)
        
        # Check threshold
        if self.threshold_ms and ttft_ms > self.threshold_ms:
            self.violations += 1
            logger.warning(
                f"[TTFT] Threshold violation: {self.phase} TTFT={ttft_ms}ms > {self.threshold_ms}ms "
                f"(p95={self.p95_ms:.0f}ms, violations={self.violations}/{self.count})"
            )
    
    @staticmethod
    def _percentile(sorted_data: List[int], p: int) -> float:
        """Calculate percentile."""
        if not sorted_data:
            return 0.0
        
        if len(sorted_data) == 1:
            return float(sorted_data[0])
        
        k = (len(sorted_data) - 1) * p / 100
        f = int(k)
        c = f + 1
        
        if c >= len(sorted_data):
            return float(sorted_data[-1])
        
        d0 = sorted_data[f]
        d1 = sorted_data[c]
        return float(d0 + (d1 - d0) * (k - f))
    
    def summary(self) -> Dict[str, Any]:
        """Get statistics summary."""
        return {
            "phase": self.phase,
            "model": self.model,
            "backend": self.backend,
            "count": self.count,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": round(self.mean_ms, 1),
            "median_ms": round(self.median_ms, 1),
            "p50_ms": round(self.p50_ms, 1),
            "p95_ms": round(self.p95_ms, 1),
            "p99_ms": round(self.p99_ms, 1),
            "threshold_ms": self.threshold_ms,
            "violations": self.violations,
            "violation_rate": round(self.violations / self.count * 100, 1) if self.count > 0 else 0.0,
        }


class TTFTMonitor:
    """Global TTFT monitoring system.
    
    Usage:
        >>> monitor = TTFTMonitor.get_instance()
        >>> monitor.record_ttft(ttft_ms=42, phase="router", model="Qwen2.5-3B")
        >>> stats = monitor.get_statistics("router")
        >>> print(f"Router p95: {stats.p95_ms}ms")
    """
    
    _instance: Optional[TTFTMonitor] = None
    
    def __init__(self):
        self._stats: Dict[str, TTFTStatistics] = {}
        self._measurements: List[TTFTMeasurement] = []
        
        # Default thresholds (Issue #158 requirements)
        self._thresholds = {
            "router": 1500,     # Issue #591: raised from 300→1500ms (RTX 4060 + Qwen 3B)
            "finalizer": 2000,  # Issue #591: raised from 500→2000ms (Gemini Flash, network)
        }
        
        self._enabled = True
        
        logger.info("[TTFT] Monitoring initialized with thresholds: %s", self._thresholds)
    
    @classmethod
    def get_instance(cls) -> TTFTMonitor:
        """Get global TTFT monitor instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset global instance (for testing)."""
        cls._instance = None
    
    def set_threshold(self, phase: str, threshold_ms: int):
        """Set TTFT threshold for a phase."""
        self._thresholds[phase] = threshold_ms
        
        # Update existing stats
        key = self._get_stats_key(phase, "", "")
        if key in self._stats:
            self._stats[key].threshold_ms = threshold_ms
        
        logger.info(f"[TTFT] Threshold updated: {phase} = {threshold_ms}ms")
    
    def record_ttft(
        self,
        ttft_ms: int,
        phase: str,
        model: str = "",
        backend: str = "",
        total_tokens: int = 0,
        request_id: Optional[str] = None,
        user_input: Optional[str] = None,
    ):
        """Record a TTFT measurement."""
        if not self._enabled:
            return
        
        # Create measurement
        measurement = TTFTMeasurement(
            timestamp=time.time(),
            ttft_ms=ttft_ms,
            model=model,
            backend=backend,
            phase=phase,
            total_tokens=total_tokens,
            request_id=request_id,
            user_input=user_input,
        )
        
        self._measurements.append(measurement)
        
        # Update statistics
        stats_key = self._get_stats_key(phase, model, backend)
        if stats_key not in self._stats:
            self._stats[stats_key] = TTFTStatistics(
                phase=phase,
                model=model,
                backend=backend,
                threshold_ms=self._thresholds.get(phase),
            )
        
        self._stats[stats_key].add_measurement(ttft_ms)
        
        # Log measurement
        logger.debug(
            f"[TTFT] {phase} TTFT={ttft_ms}ms model={model} "
            f"(p50={self._stats[stats_key].p50_ms:.0f}ms, p95={self._stats[stats_key].p95_ms:.0f}ms)"
        )
    
    def get_statistics(self, phase: str) -> Optional[TTFTStatistics]:
        """Get statistics for a phase."""
        # Find first stats matching phase
        for key, stats in self._stats.items():
            if stats.phase == phase:
                return stats
        return None
    
    def get_all_statistics(self) -> List[TTFTStatistics]:
        """Get all statistics."""
        return list(self._stats.values())
    
    def _get_stats_key(self, phase: str, model: str, backend: str) -> str:
        """Get stats dictionary key."""
        return f"{phase}|{model}|{backend}"
    
    def export_report(self, output_path: Optional[Path] = None) -> Dict[str, Any]:
        """Export TTFT report.
        
        Args:
            output_path: Optional path to save JSON report
            
        Returns:
            Report dictionary
        """
        report = {
            "summary": {
                "total_measurements": len(self._measurements),
                "phases": list(set(s.phase for s in self._stats.values())),
                "thresholds": self._thresholds,
            },
            "statistics": [stats.summary() for stats in self._stats.values()],
            "measurements": [
                {
                    "timestamp": m.timestamp,
                    "ttft_ms": m.ttft_ms,
                    "phase": m.phase,
                    "model": m.model,
                    "backend": m.backend,
                    "total_tokens": m.total_tokens,
                    "request_id": m.request_id,
                }
                for m in self._measurements[-100:]  # Last 100 measurements
            ],
        }
        
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"[TTFT] Report exported to {output_path}")
        
        return report
    
    def print_summary(self):
        """Print TTFT summary to console."""
        print("\n" + "=" * 80)
        print("TTFT MONITORING SUMMARY")
        print("=" * 80)
        
        for stats in self._stats.values():
            summary = stats.summary()
            
            print(f"\n{summary['phase'].upper()} ({summary['model']})")
            print(f"  Count:      {summary['count']}")
            print(f"  Min:        {summary['min_ms']}ms")
            print(f"  Mean:       {summary['mean_ms']}ms")
            print(f"  Median:     {summary['median_ms']}ms")
            print(f"  P50:        {summary['p50_ms']}ms")
            print(f"  P95:        {summary['p95_ms']}ms ⭐")
            print(f"  P99:        {summary['p99_ms']}ms")
            print(f"  Max:        {summary['max_ms']}ms")
            
            if summary['threshold_ms']:
                status = "✅" if summary['p95_ms'] < summary['threshold_ms'] else "❌"
                print(f"  Threshold:  {summary['threshold_ms']}ms {status}")
                print(f"  Violations: {summary['violations']}/{summary['count']} ({summary['violation_rate']}%)")
        
        print("\n" + "=" * 80)
    
    def check_thresholds(self) -> bool:
        """Check if all phases meet their thresholds.
        
        Returns:
            True if all thresholds met, False otherwise
        """
        all_pass = True
        
        for stats in self._stats.values():
            if stats.threshold_ms and stats.p95_ms >= stats.threshold_ms:
                logger.error(
                    f"[TTFT] Threshold FAILED: {stats.phase} p95={stats.p95_ms:.0f}ms >= {stats.threshold_ms}ms"
                )
                all_pass = False
        
        return all_pass
    
    def enable(self):
        """Enable TTFT monitoring."""
        self._enabled = True
        logger.info("[TTFT] Monitoring enabled")
    
    def disable(self):
        """Disable TTFT monitoring."""
        self._enabled = False
        logger.info("[TTFT] Monitoring disabled")
    
    def clear_all(self):
        """Clear all measurements and statistics."""
        self._measurements.clear()
        self._stats.clear()
        logger.debug("[TTFT] All measurements and statistics cleared")


# Convenience function
def record_ttft(
    ttft_ms: int,
    phase: str,
    model: str = "",
    backend: str = "",
    **kwargs
):
    """Record TTFT measurement to global monitor."""
    monitor = TTFTMonitor.get_instance()
    monitor.record_ttft(
        ttft_ms=ttft_ms,
        phase=phase,
        model=model,
        backend=backend,
        **kwargs
    )
