"""Debug Tier Information for Router and Finalizer Decisions.

Issue #244: Debug tier decisions + quality hit/miss.

This module provides:
- Debug output for tier routing decisions
- --debug flag and BANTZ_DEBUG_TIERS=1 env support
- Show router_backend, finalizer_backend, quality called
- Performance timing metrics

Usage:
    # Enable via environment
    export BANTZ_DEBUG_TIERS=1
    
    # Or programmatically
    from bantz.debug.tier_info import TierDebugger
    debugger = TierDebugger(enabled=True)
    debugger.log_router_decision(...)
"""

from __future__ import annotations

import os
import sys
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TextIO


# =============================================================================
# Enums
# =============================================================================

class TierBackend(Enum):
    """Backend tier for routing."""
    VLLM_LOCAL = "vllm_local"      # Local Qwen2.5-3B
    GEMINI_CLOUD = "gemini_cloud"  # Gemini 1.5 Flash
    OPENAI_CLOUD = "openai_cloud"  # OpenAI fallback
    MOCK = "mock"                  # Mock for testing
    UNKNOWN = "unknown"


class TierDecisionType(Enum):
    """Type of tier decision."""
    ROUTER = "router"              # Initial routing decision
    FINALIZER = "finalizer"        # Finalizer selection
    QUALITY_CHECK = "quality"      # Quality assessment
    FALLBACK = "fallback"          # Fallback triggered
    BYPASS = "bypass"              # Rule-based bypass


class QualityResult(Enum):
    """Quality check result."""
    PASS = "pass"                  # Quality met threshold
    FAIL = "fail"                  # Quality below threshold
    SKIP = "skip"                  # Quality check skipped
    PENDING = "pending"            # Not yet checked


# =============================================================================
# Debug Configuration
# =============================================================================

def is_debug_enabled() -> bool:
    """Check if tier debug mode is enabled.
    
    Enabled by:
    - BANTZ_DEBUG_TIERS=1 environment variable
    - BANTZ_DEBUG=1 environment variable
    - --debug CLI flag (sets env var)
    """
    debug_tiers = os.getenv("BANTZ_DEBUG_TIERS", "").strip().lower()
    debug_main = os.getenv("BANTZ_DEBUG", "").strip().lower()
    
    return debug_tiers in ("1", "true", "yes") or debug_main in ("1", "true", "yes")


def enable_debug() -> None:
    """Enable tier debug mode."""
    os.environ["BANTZ_DEBUG_TIERS"] = "1"


def disable_debug() -> None:
    """Disable tier debug mode."""
    os.environ.pop("BANTZ_DEBUG_TIERS", None)


# =============================================================================
# Decision Records
# =============================================================================

@dataclass
class TierDecision:
    """Record of a tier decision.
    
    Captures what decision was made, when, and why.
    """
    decision_type: TierDecisionType
    backend: TierBackend
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    reason: str = ""
    confidence: float = 1.0
    quality_result: QualityResult = QualityResult.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "decision_type": self.decision_type.value,
            "backend": self.backend.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "reason": self.reason,
            "confidence": self.confidence,
            "quality_result": self.quality_result.value,
            "metadata": self.metadata,
        }
    
    def format_short(self) -> str:
        """Format as short one-line string."""
        return (
            f"[{self.decision_type.value.upper():10}] "
            f"{self.backend.value:15} "
            f"({self.duration_ms:6.1f}ms) "
            f"{self.reason}"
        )
    
    def format_detailed(self) -> str:
        """Format as detailed multi-line string."""
        lines = [
            f"=== Tier Decision: {self.decision_type.value.upper()} ===",
            f"  Backend: {self.backend.value}",
            f"  Time: {self.timestamp.strftime('%H:%M:%S.%f')[:-3]}",
            f"  Duration: {self.duration_ms:.1f}ms",
            f"  Confidence: {self.confidence:.2f}",
            f"  Reason: {self.reason}",
        ]
        
        if self.quality_result != QualityResult.PENDING:
            lines.append(f"  Quality: {self.quality_result.value}")
        
        if self.metadata:
            lines.append("  Metadata:")
            for key, value in self.metadata.items():
                lines.append(f"    {key}: {value}")
        
        return "\n".join(lines)


@dataclass
class TierSession:
    """Session of tier decisions for a single request.
    
    Groups related decisions together for analysis.
    """
    session_id: str
    start_time: datetime = field(default_factory=datetime.now)
    decisions: list[TierDecision] = field(default_factory=list)
    user_query: str = ""
    final_response: str = ""
    total_duration_ms: float = 0.0
    
    def add_decision(self, decision: TierDecision) -> None:
        """Add a decision to the session."""
        self.decisions.append(decision)
    
    def get_router_backend(self) -> Optional[TierBackend]:
        """Get the router backend used."""
        for d in self.decisions:
            if d.decision_type == TierDecisionType.ROUTER:
                return d.backend
        return None
    
    def get_finalizer_backend(self) -> Optional[TierBackend]:
        """Get the finalizer backend used."""
        for d in self.decisions:
            if d.decision_type == TierDecisionType.FINALIZER:
                return d.backend
        return None
    
    def was_quality_called(self) -> bool:
        """Check if quality check was called."""
        return any(
            d.decision_type == TierDecisionType.QUALITY_CHECK
            for d in self.decisions
        )
    
    def quality_passed(self) -> bool:
        """Check if quality check passed."""
        for d in self.decisions:
            if d.decision_type == TierDecisionType.QUALITY_CHECK:
                return d.quality_result == QualityResult.PASS
        return False
    
    def format_summary(self) -> str:
        """Format session summary."""
        router = self.get_router_backend()
        finalizer = self.get_finalizer_backend()
        quality = "called" if self.was_quality_called() else "skipped"
        
        return (
            f"[TIER DEBUG] session={self.session_id} "
            f"router={router.value if router else 'none'} "
            f"finalizer={finalizer.value if finalizer else 'none'} "
            f"quality={quality} "
            f"total={self.total_duration_ms:.1f}ms"
        )
    
    def format_full(self) -> str:
        """Format full session details."""
        lines = [
            "=" * 60,
            f"TIER DEBUG SESSION: {self.session_id}",
            "=" * 60,
            f"Query: {self.user_query[:50]}..." if len(self.user_query) > 50 else f"Query: {self.user_query}",
            f"Start: {self.start_time.strftime('%H:%M:%S.%f')[:-3]}",
            "",
            "Decisions:",
        ]
        
        for i, decision in enumerate(self.decisions, 1):
            lines.append(f"  {i}. {decision.format_short()}")
        
        lines.extend([
            "",
            f"Total Duration: {self.total_duration_ms:.1f}ms",
            "=" * 60,
        ])
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "user_query": self.user_query,
            "decisions": [d.to_dict() for d in self.decisions],
            "total_duration_ms": self.total_duration_ms,
            "router_backend": self.get_router_backend().value if self.get_router_backend() else None,
            "finalizer_backend": self.get_finalizer_backend().value if self.get_finalizer_backend() else None,
            "quality_called": self.was_quality_called(),
        }


# =============================================================================
# Timer Context Manager
# =============================================================================

class TierTimer:
    """Context manager for timing tier operations."""
    
    def __init__(self) -> None:
        self._start: float = 0.0
        self._end: float = 0.0
    
    def __enter__(self) -> "TierTimer":
        self._start = time.perf_counter()
        return self
    
    def __exit__(self, *args: Any) -> None:
        self._end = time.perf_counter()
    
    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        return (self._end - self._start) * 1000


# =============================================================================
# Tier Debugger
# =============================================================================

class TierDebugger:
    """Main debugger for tier decisions.
    
    Tracks and logs tier routing decisions for debugging.
    
    Usage:
        debugger = TierDebugger()
        
        with debugger.session("req-123", "Bugün hava nasıl?") as session:
            with debugger.timer() as t:
                # Do routing
                result = router.route(query)
            debugger.log_router_decision(
                session, TierBackend.VLLM_LOCAL,
                duration_ms=t.duration_ms, reason="local capable"
            )
    """
    
    def __init__(
        self,
        enabled: Optional[bool] = None,
        output: Optional[TextIO] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize tier debugger.
        
        Args:
            enabled: Override for debug enabled (uses env if None).
            output: Output stream (uses stderr if None).
            logger: Logger to use (creates one if None).
        """
        self._enabled = enabled if enabled is not None else is_debug_enabled()
        self._output = output or sys.stderr
        self._logger = logger or logging.getLogger("bantz.tier_debug")
        self._sessions: dict[str, TierSession] = {}
        self._current_session: Optional[TierSession] = None
    
    @property
    def enabled(self) -> bool:
        """Check if debugging is enabled."""
        return self._enabled
    
    def enable(self) -> None:
        """Enable debugging."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable debugging."""
        self._enabled = False
    
    def timer(self) -> TierTimer:
        """Create a timer for measuring operations."""
        return TierTimer()
    
    def session(
        self,
        session_id: str,
        user_query: str = "",
    ) -> "TierDebugSession":
        """Create a debug session context.
        
        Args:
            session_id: Unique session identifier.
            user_query: User's query text.
        
        Returns:
            Context manager for the session.
        """
        return TierDebugSession(self, session_id, user_query)
    
    def _start_session(self, session_id: str, user_query: str) -> TierSession:
        """Start a new debug session."""
        session = TierSession(session_id=session_id, user_query=user_query)
        self._sessions[session_id] = session
        self._current_session = session
        return session
    
    def _end_session(self, session_id: str) -> None:
        """End a debug session."""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.total_duration_ms = (
                datetime.now() - session.start_time
            ).total_seconds() * 1000
            
            if self._enabled:
                self._output.write(session.format_summary() + "\n")
                self._output.flush()
            
            if self._current_session and self._current_session.session_id == session_id:
                self._current_session = None
    
    def log_router_decision(
        self,
        session: TierSession,
        backend: TierBackend,
        duration_ms: float = 0.0,
        reason: str = "",
        confidence: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TierDecision:
        """Log a router decision.
        
        Args:
            session: The debug session.
            backend: Backend selected.
            duration_ms: Time taken for decision.
            reason: Reason for selection.
            confidence: Confidence score.
            metadata: Additional metadata.
        
        Returns:
            The logged decision.
        """
        decision = TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=backend,
            duration_ms=duration_ms,
            reason=reason,
            confidence=confidence,
            metadata=metadata or {},
        )
        session.add_decision(decision)
        
        if self._enabled:
            self._log_decision(decision)
        
        return decision
    
    def log_finalizer_decision(
        self,
        session: TierSession,
        backend: TierBackend,
        duration_ms: float = 0.0,
        reason: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> TierDecision:
        """Log a finalizer decision.
        
        Args:
            session: The debug session.
            backend: Backend selected.
            duration_ms: Time taken for decision.
            reason: Reason for selection.
            metadata: Additional metadata.
        
        Returns:
            The logged decision.
        """
        decision = TierDecision(
            decision_type=TierDecisionType.FINALIZER,
            backend=backend,
            duration_ms=duration_ms,
            reason=reason,
            metadata=metadata or {},
        )
        session.add_decision(decision)
        
        if self._enabled:
            self._log_decision(decision)
        
        return decision
    
    def log_quality_check(
        self,
        session: TierSession,
        result: QualityResult,
        score: float = 0.0,
        threshold: float = 0.0,
        duration_ms: float = 0.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TierDecision:
        """Log a quality check result.
        
        Args:
            session: The debug session.
            result: Quality result (pass/fail/skip).
            score: Quality score achieved.
            threshold: Required threshold.
            duration_ms: Time taken for check.
            metadata: Additional metadata.
        
        Returns:
            The logged decision.
        """
        meta = metadata or {}
        meta.update({"score": score, "threshold": threshold})
        
        decision = TierDecision(
            decision_type=TierDecisionType.QUALITY_CHECK,
            backend=TierBackend.UNKNOWN,
            duration_ms=duration_ms,
            reason=f"score={score:.2f} threshold={threshold:.2f}",
            quality_result=result,
            metadata=meta,
        )
        session.add_decision(decision)
        
        if self._enabled:
            self._log_decision(decision)
        
        return decision
    
    def log_fallback(
        self,
        session: TierSession,
        from_backend: TierBackend,
        to_backend: TierBackend,
        reason: str = "",
        duration_ms: float = 0.0,
    ) -> TierDecision:
        """Log a fallback event.
        
        Args:
            session: The debug session.
            from_backend: Original backend.
            to_backend: Fallback backend.
            reason: Reason for fallback.
            duration_ms: Time taken.
        
        Returns:
            The logged decision.
        """
        decision = TierDecision(
            decision_type=TierDecisionType.FALLBACK,
            backend=to_backend,
            duration_ms=duration_ms,
            reason=f"{from_backend.value} -> {to_backend.value}: {reason}",
            metadata={"from_backend": from_backend.value},
        )
        session.add_decision(decision)
        
        if self._enabled:
            self._log_decision(decision)
        
        return decision
    
    def log_bypass(
        self,
        session: TierSession,
        reason: str,
        rule_name: str = "",
    ) -> TierDecision:
        """Log a rule-based bypass.
        
        Args:
            session: The debug session.
            reason: Reason for bypass.
            rule_name: Name of the rule that triggered bypass.
        
        Returns:
            The logged decision.
        """
        decision = TierDecision(
            decision_type=TierDecisionType.BYPASS,
            backend=TierBackend.VLLM_LOCAL,
            duration_ms=0.0,
            reason=reason,
            metadata={"rule_name": rule_name},
        )
        session.add_decision(decision)
        
        if self._enabled:
            self._log_decision(decision)
        
        return decision
    
    def _log_decision(self, decision: TierDecision) -> None:
        """Log a decision to output."""
        self._output.write(f"[TIER] {decision.format_short()}\n")
        self._output.flush()
    
    def get_session(self, session_id: str) -> Optional[TierSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def get_all_sessions(self) -> list[TierSession]:
        """Get all recorded sessions."""
        return list(self._sessions.values())
    
    def clear_sessions(self) -> None:
        """Clear all recorded sessions."""
        self._sessions.clear()
        self._current_session = None
    
    def get_stats(self) -> dict[str, Any]:
        """Get aggregated statistics."""
        if not self._sessions:
            return {"total_sessions": 0}
        
        sessions = list(self._sessions.values())
        
        router_backends = [s.get_router_backend() for s in sessions]
        finalizer_backends = [s.get_finalizer_backend() for s in sessions]
        quality_calls = sum(1 for s in sessions if s.was_quality_called())
        
        # Count backend usage
        router_counts: dict[str, int] = {}
        for b in router_backends:
            if b:
                router_counts[b.value] = router_counts.get(b.value, 0) + 1
        
        finalizer_counts: dict[str, int] = {}
        for b in finalizer_backends:
            if b:
                finalizer_counts[b.value] = finalizer_counts.get(b.value, 0) + 1
        
        # Average duration
        total_duration = sum(s.total_duration_ms for s in sessions)
        avg_duration = total_duration / len(sessions) if sessions else 0
        
        return {
            "total_sessions": len(sessions),
            "router_backends": router_counts,
            "finalizer_backends": finalizer_counts,
            "quality_calls": quality_calls,
            "quality_call_rate": quality_calls / len(sessions) if sessions else 0,
            "avg_duration_ms": avg_duration,
            "total_duration_ms": total_duration,
        }


class TierDebugSession:
    """Context manager for a debug session."""
    
    def __init__(
        self,
        debugger: TierDebugger,
        session_id: str,
        user_query: str,
    ) -> None:
        self._debugger = debugger
        self._session_id = session_id
        self._user_query = user_query
        self._session: Optional[TierSession] = None
    
    def __enter__(self) -> TierSession:
        self._session = self._debugger._start_session(
            self._session_id, self._user_query
        )
        return self._session
    
    def __exit__(self, *args: Any) -> None:
        self._debugger._end_session(self._session_id)


# =============================================================================
# Global Debugger Instance
# =============================================================================

_global_debugger: Optional[TierDebugger] = None


def get_tier_debugger() -> TierDebugger:
    """Get or create the global tier debugger."""
    global _global_debugger
    if _global_debugger is None:
        _global_debugger = TierDebugger()
    return _global_debugger


def reset_tier_debugger() -> None:
    """Reset the global tier debugger."""
    global _global_debugger
    _global_debugger = None


# =============================================================================
# CLI Integration Helpers
# =============================================================================

def setup_debug_from_cli(args: Any) -> None:
    """Setup debugging from CLI arguments.
    
    Args:
        args: Parsed CLI arguments (expects args.debug attribute).
    """
    if hasattr(args, "debug") and args.debug:
        enable_debug()
        debugger = get_tier_debugger()
        debugger.enable()


def print_tier_stats() -> None:
    """Print tier statistics to stderr."""
    debugger = get_tier_debugger()
    stats = debugger.get_stats()
    
    if stats["total_sessions"] == 0:
        return
    
    sys.stderr.write("\n")
    sys.stderr.write("=" * 50 + "\n")
    sys.stderr.write("TIER DEBUG STATISTICS\n")
    sys.stderr.write("=" * 50 + "\n")
    sys.stderr.write(f"Total Sessions: {stats['total_sessions']}\n")
    sys.stderr.write(f"Average Duration: {stats['avg_duration_ms']:.1f}ms\n")
    sys.stderr.write(f"Quality Call Rate: {stats['quality_call_rate']:.1%}\n")
    sys.stderr.write("\nRouter Backends:\n")
    for backend, count in stats.get("router_backends", {}).items():
        sys.stderr.write(f"  {backend}: {count}\n")
    sys.stderr.write("\nFinalizer Backends:\n")
    for backend, count in stats.get("finalizer_backends", {}).items():
        sys.stderr.write(f"  {backend}: {count}\n")
    sys.stderr.write("=" * 50 + "\n")
    sys.stderr.flush()
