"""Quality gating policy module.

Issue #232: Comprehensive quality gating with heuristics scoring, rate limiting,
and configurable thresholds for the hybrid vLLM/Gemini architecture.

This module provides:
- QualityScore: Combined heuristics score for quality decisions
- GatingPolicy: Policy engine for quality/fast tier decisions
- QualityRateLimiter: Rate limiting for quality tier to prevent API abuse
- PolicyConfig: Configuration via environment variables
"""

from __future__ import annotations

import os
import time
import logging
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from enum import Enum
from collections import deque
from threading import Lock

logger = logging.getLogger(__name__)


class GatingDecision(Enum):
    """Quality gating decisions."""
    USE_FAST = "fast"
    USE_QUALITY = "quality"
    BLOCKED = "blocked"  # Rate limited or policy blocked


@dataclass(frozen=True)
class QualityScore:
    """Combined quality score from multiple heuristics.
    
    Attributes:
        complexity: 0-5, multi-step/planning complexity
        writing: 0-5, writing/polish quality need
        risk: 0-5, destructive action risk
        total: Combined weighted score
        components: Individual component scores for debugging
    """
    complexity: int
    writing: int
    risk: int
    total: float
    components: Dict[str, float] = field(default_factory=dict)
    
    @classmethod
    def compute(
        cls,
        text: str,
        *,
        tool_names: Optional[List[str]] = None,
        requires_confirmation: bool = False,
        weights: Optional[Dict[str, float]] = None,
    ) -> "QualityScore":
        """Compute quality score from input text.
        
        Args:
            text: User input text
            tool_names: Names of planned tools
            requires_confirmation: Whether action requires confirmation
            weights: Optional weight overrides for each component
        
        Returns:
            QualityScore with all computed values
        """
        from bantz.llm.tiered import score_complexity, score_writing_need, score_risk
        
        complexity = score_complexity(text)
        writing = score_writing_need(text)
        risk = score_risk(text, tool_names=tool_names, requires_confirmation=requires_confirmation)
        
        # Default weights
        w = weights or {}
        w_complexity = w.get("complexity", 0.35)
        w_writing = w.get("writing", 0.45)
        w_risk = w.get("risk", 0.20)
        
        # Weighted total (normalized to 0-5 scale)
        total = (
            complexity * w_complexity +
            writing * w_writing +
            risk * w_risk
        )
        
        components = {
            "complexity": complexity * w_complexity,
            "writing": writing * w_writing,
            "risk": risk * w_risk,
        }
        
        return cls(
            complexity=complexity,
            writing=writing,
            risk=risk,
            total=round(total, 2),
            components=components,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "complexity": self.complexity,
            "writing": self.writing,
            "risk": self.risk,
            "total": self.total,
            "components": self.components,
        }


@dataclass
class PolicyConfig:
    """Configuration for quality gating policy.
    
    All values can be overridden via environment variables.
    """
    # Score thresholds
    quality_threshold: float = 2.5  # Total score >= this → quality tier
    fast_max_threshold: float = 1.5  # Total score <= this → always fast
    
    # Component thresholds
    min_complexity_for_quality: int = 4
    min_writing_for_quality: int = 4
    
    # Rate limiting
    quality_rate_limit: int = 30  # Max quality requests per window
    rate_window_seconds: float = 60.0
    
    # Finalizer mode
    finalizer_mode: str = "auto"  # auto, always, never
    
    # Bypass patterns (comma-separated)
    bypass_patterns: List[str] = field(default_factory=list)
    force_quality_patterns: List[str] = field(default_factory=list)
    
    @classmethod
    def from_env(cls) -> "PolicyConfig":
        """Load configuration from environment variables."""
        def env_float(name: str, default: float) -> float:
            raw = os.getenv(name, "")
            if not raw.strip():
                return default
            try:
                return float(raw)
            except ValueError:
                return default
        
        def env_int(name: str, default: int) -> int:
            raw = os.getenv(name, "")
            if not raw.strip():
                return default
            try:
                return int(raw)
            except ValueError:
                return default
        
        def env_str(name: str, default: str) -> str:
            return os.getenv(name, default).strip() or default
        
        def env_list(name: str) -> List[str]:
            raw = os.getenv(name, "")
            if not raw.strip():
                return []
            return [x.strip() for x in raw.split(",") if x.strip()]
        
        return cls(
            quality_threshold=env_float("BANTZ_QUALITY_SCORE_THRESHOLD", 2.5),
            fast_max_threshold=env_float("BANTZ_FAST_MAX_THRESHOLD", 1.5),
            min_complexity_for_quality=env_int("BANTZ_MIN_COMPLEXITY_FOR_QUALITY", 4),
            min_writing_for_quality=env_int("BANTZ_MIN_WRITING_FOR_QUALITY", 4),
            quality_rate_limit=env_int("BANTZ_QUALITY_RATE_LIMIT", 30),
            rate_window_seconds=env_float("BANTZ_RATE_WINDOW_SECONDS", 60.0),
            finalizer_mode=env_str("BANTZ_FINALIZER_MODE", "auto"),
            bypass_patterns=env_list("BANTZ_QUALITY_BYPASS_PATTERNS"),
            force_quality_patterns=env_list("BANTZ_FORCE_QUALITY_PATTERNS"),
        )


class QualityRateLimiter:
    """Rate limiter for quality tier requests.
    
    Prevents excessive API usage for cloud-based quality models like Gemini.
    Uses sliding window algorithm for accurate rate limiting.
    """
    
    def __init__(
        self,
        max_requests: int = 30,
        window_seconds: float = 60.0,
    ):
        """Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Window duration in seconds
        """
        self.max_requests = max(1, max_requests)
        self.window_seconds = max(0.001, window_seconds)  # Allow very small windows for testing
        self._requests: deque = deque()
        self._lock = Lock()
        self._blocked_count = 0
        self._total_requests = 0
    
    def _cleanup(self, now: float) -> None:
        """Remove expired entries from the window."""
        cutoff = now - self.window_seconds
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()
    
    def check(self) -> bool:
        """Check if a request is allowed without consuming quota.
        
        Returns:
            True if request would be allowed
        """
        with self._lock:
            now = time.time()
            self._cleanup(now)
            return len(self._requests) < self.max_requests
    
    def acquire(self) -> bool:
        """Attempt to acquire a slot for a quality request.
        
        Returns:
            True if allowed, False if rate limited
        """
        with self._lock:
            now = time.time()
            self._cleanup(now)
            self._total_requests += 1
            
            if len(self._requests) >= self.max_requests:
                self._blocked_count += 1
                logger.warning(
                    "[QualityRateLimiter] Rate limited: %d/%d requests in window",
                    len(self._requests),
                    self.max_requests,
                )
                return False
            
            self._requests.append(now)
            return True
    
    def release(self) -> None:
        """Release a slot (for error recovery)."""
        with self._lock:
            if self._requests:
                self._requests.pop()
    
    @property
    def current_usage(self) -> int:
        """Get current number of requests in window."""
        with self._lock:
            self._cleanup(time.time())
            return len(self._requests)
    
    @property
    def remaining_quota(self) -> int:
        """Get remaining requests in current window."""
        return max(0, self.max_requests - self.current_usage)
    
    @property
    def blocked_count(self) -> int:
        """Get total number of blocked requests."""
        return self._blocked_count
    
    @property
    def total_requests(self) -> int:
        """Get total number of rate limit checks."""
        return self._total_requests
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "current_usage": self.current_usage,
            "max_requests": self.max_requests,
            "remaining_quota": self.remaining_quota,
            "blocked_count": self._blocked_count,
            "total_requests": self._total_requests,
            "block_rate": round(self._blocked_count / max(1, self._total_requests), 3),
        }
    
    def reset(self) -> None:
        """Reset the rate limiter state."""
        with self._lock:
            self._requests.clear()
            self._blocked_count = 0
            self._total_requests = 0


@dataclass
class GatingResult:
    """Result of quality gating decision."""
    decision: GatingDecision
    score: QualityScore
    reason: str
    rate_limited: bool = False
    config_used: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "score": self.score.to_dict(),
            "reason": self.reason,
            "rate_limited": self.rate_limited,
        }


class GatingPolicy:
    """Policy engine for quality/fast tier decisions.
    
    Combines heuristics scoring, rate limiting, and configuration-based
    overrides to determine the optimal processing tier.
    
    Usage:
        policy = GatingPolicy()
        result = policy.evaluate(
            user_input="Draft a formal email to professor",
            tool_names=["gmail_send"],
        )
        if result.decision == GatingDecision.USE_QUALITY:
            # Use Gemini finalizer
        else:
            # Use fast vLLM path
    """
    
    def __init__(self, config: Optional[PolicyConfig] = None):
        """Initialize gating policy.
        
        Args:
            config: Policy configuration. Defaults to env-based config.
        """
        self.config = config or PolicyConfig.from_env()
        self.rate_limiter = QualityRateLimiter(
            max_requests=self.config.quality_rate_limit,
            window_seconds=self.config.rate_window_seconds,
        )
        self._decision_history: List[GatingResult] = []
        self._max_history = 100
    
    def _matches_patterns(self, text: str, patterns: List[str]) -> bool:
        """Check if text matches any pattern."""
        if not patterns:
            return False
        t = (text or "").lower()
        for p in patterns:
            if p.lower() in t:
                return True
        return False
    
    def evaluate(
        self,
        user_input: str,
        *,
        tool_names: Optional[List[str]] = None,
        requires_confirmation: bool = False,
        enforce_rate_limit: bool = True,
        score_weights: Optional[Dict[str, float]] = None,
    ) -> GatingResult:
        """Evaluate quality gating policy for a request.
        
        Args:
            user_input: User's input text
            tool_names: Names of planned tools
            requires_confirmation: Whether action requires confirmation
            enforce_rate_limit: Whether to enforce rate limiting
            score_weights: Optional custom weights for scoring
        
        Returns:
            GatingResult with decision and details
        """
        # Compute quality score
        score = QualityScore.compute(
            user_input,
            tool_names=tool_names,
            requires_confirmation=requires_confirmation,
            weights=score_weights,
        )
        
        # Check bypass patterns (always fast)
        if self._matches_patterns(user_input, self.config.bypass_patterns):
            result = GatingResult(
                decision=GatingDecision.USE_FAST,
                score=score,
                reason="bypass_pattern_match",
            )
            self._record_decision(result)
            return result
        
        # Check force quality patterns
        if self._matches_patterns(user_input, self.config.force_quality_patterns):
            if enforce_rate_limit and not self.rate_limiter.acquire():
                result = GatingResult(
                    decision=GatingDecision.BLOCKED,
                    score=score,
                    reason="force_quality_rate_limited",
                    rate_limited=True,
                )
                self._record_decision(result)
                return result
            
            result = GatingResult(
                decision=GatingDecision.USE_QUALITY,
                score=score,
                reason="force_quality_pattern_match",
            )
            self._record_decision(result)
            return result
        
        # Check finalizer mode
        if self.config.finalizer_mode == "never":
            result = GatingResult(
                decision=GatingDecision.USE_FAST,
                score=score,
                reason="finalizer_mode_never",
            )
            self._record_decision(result)
            return result
        
        if self.config.finalizer_mode == "always":
            if enforce_rate_limit and not self.rate_limiter.acquire():
                result = GatingResult(
                    decision=GatingDecision.BLOCKED,
                    score=score,
                    reason="finalizer_mode_always_rate_limited",
                    rate_limited=True,
                )
                self._record_decision(result)
                return result
            
            result = GatingResult(
                decision=GatingDecision.USE_QUALITY,
                score=score,
                reason="finalizer_mode_always",
            )
            self._record_decision(result)
            return result
        
        # Auto mode: use thresholds
        # Fast path for very low scores
        if score.total <= self.config.fast_max_threshold:
            result = GatingResult(
                decision=GatingDecision.USE_FAST,
                score=score,
                reason="score_below_fast_threshold",
            )
            self._record_decision(result)
            return result
        
        # Quality path for high scores
        if score.total >= self.config.quality_threshold:
            if enforce_rate_limit and not self.rate_limiter.acquire():
                result = GatingResult(
                    decision=GatingDecision.USE_FAST,  # Fallback to fast
                    score=score,
                    reason="quality_rate_limited_fallback",
                    rate_limited=True,
                )
                self._record_decision(result)
                return result
            
            result = GatingResult(
                decision=GatingDecision.USE_QUALITY,
                score=score,
                reason="score_above_quality_threshold",
            )
            self._record_decision(result)
            return result
        
        # Component-based escalation
        if (
            score.complexity >= self.config.min_complexity_for_quality or
            score.writing >= self.config.min_writing_for_quality
        ):
            if enforce_rate_limit and not self.rate_limiter.acquire():
                result = GatingResult(
                    decision=GatingDecision.USE_FAST,
                    score=score,
                    reason="component_escalation_rate_limited",
                    rate_limited=True,
                )
                self._record_decision(result)
                return result
            
            result = GatingResult(
                decision=GatingDecision.USE_QUALITY,
                score=score,
                reason="component_threshold_exceeded",
            )
            self._record_decision(result)
            return result
        
        # Default to fast
        result = GatingResult(
            decision=GatingDecision.USE_FAST,
            score=score,
            reason="default_fast",
        )
        self._record_decision(result)
        return result
    
    def _record_decision(self, result: GatingResult) -> None:
        """Record decision in history for debugging."""
        self._decision_history.append(result)
        if len(self._decision_history) > self._max_history:
            self._decision_history = self._decision_history[-self._max_history:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get policy statistics."""
        if not self._decision_history:
            return {
                "total_decisions": 0,
                "quality_count": 0,
                "fast_count": 0,
                "blocked_count": 0,
                "rate_limiter": self.rate_limiter.get_stats(),
            }
        
        quality_count = sum(
            1 for r in self._decision_history
            if r.decision == GatingDecision.USE_QUALITY
        )
        fast_count = sum(
            1 for r in self._decision_history
            if r.decision == GatingDecision.USE_FAST
        )
        blocked_count = sum(
            1 for r in self._decision_history
            if r.decision == GatingDecision.BLOCKED
        )
        
        return {
            "total_decisions": len(self._decision_history),
            "quality_count": quality_count,
            "fast_count": fast_count,
            "blocked_count": blocked_count,
            "quality_ratio": round(quality_count / len(self._decision_history), 3),
            "rate_limiter": self.rate_limiter.get_stats(),
        }
    
    def reset_stats(self) -> None:
        """Reset policy statistics."""
        self._decision_history.clear()
        self.rate_limiter.reset()


# Module-level singleton for convenience
_default_policy: Optional[GatingPolicy] = None


def get_default_policy() -> GatingPolicy:
    """Get the default gating policy singleton."""
    global _default_policy
    if _default_policy is None:
        _default_policy = GatingPolicy()
    return _default_policy


def evaluate_quality_gating(
    user_input: str,
    *,
    tool_names: Optional[List[str]] = None,
    requires_confirmation: bool = False,
) -> GatingResult:
    """Convenience function for quality gating evaluation.
    
    Args:
        user_input: User's input text
        tool_names: Names of planned tools
        requires_confirmation: Whether action requires confirmation
    
    Returns:
        GatingResult with decision and details
    """
    policy = get_default_policy()
    return policy.evaluate(
        user_input,
        tool_names=tool_names,
        requires_confirmation=requires_confirmation,
    )


def should_use_quality(
    user_input: str,
    *,
    tool_names: Optional[List[str]] = None,
) -> bool:
    """Simple check for whether to use quality tier.
    
    Returns:
        True if quality tier should be used
    """
    result = evaluate_quality_gating(user_input, tool_names=tool_names)
    return result.decision == GatingDecision.USE_QUALITY
