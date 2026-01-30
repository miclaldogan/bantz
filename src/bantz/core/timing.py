"""
Timing requirements for Jarvis V2 MVP.

This module defines the canonical timing constants used across the Bantz system
for measuring and validating response times.

Reference: docs/jarvis-roadmap-v2.md
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TimingRequirements:
    """
    V2 MVP timing requirements.
    
    These constants define the performance targets for Jarvis V2.
    All times are in their respective units (ms for milliseconds, s for seconds).
    
    Usage:
        >>> from bantz.core.timing import TIMING
        >>> if response_time_ms > TIMING.ACK_MAX_MS:
        ...     logger.warning("ACK too slow")
    """
    
    # === ACK (Acknowledgment) ===
    # Time from voice input end to TTS "Anladım/Bakıyorum" response start
    ACK_MAX_MS: int = 200  # 0.2 seconds
    
    # === Source Finding ===
    # Time to find first web source
    FIRST_SOURCE_MIN_S: int = 3   # Minimum realistic time
    FIRST_SOURCE_MAX_S: int = 10  # Maximum acceptable time
    
    # === Summary Generation ===
    # Time to generate full summary with citations
    SUMMARY_MAX_S: int = 30  # Maximum summary generation time
    
    # === Permission ===
    # Whether to require permission prompts for MEDIUM+ actions
    PERMISSION_PROMPT_REQUIRED: bool = True
    
    # === Progress Updates ===
    # Interval between progress update events
    PROGRESS_UPDATE_INTERVAL_S: int = 3
    
    # === Timeouts ===
    # Tool execution timeout
    TOOL_TIMEOUT_S: int = 60
    
    # User response timeout (waiting for user input)
    USER_RESPONSE_TIMEOUT_S: int = 30
    
    # === Retry ===
    # Retry delays (exponential backoff)
    RETRY_DELAY_1_S: float = 1.0
    RETRY_DELAY_2_S: float = 3.0
    RETRY_DELAY_3_S: float = 7.0
    
    # Maximum retry attempts
    MAX_RETRIES: int = 3
    
    # === Barge-in ===
    # Minimum speech duration to trigger barge-in
    BARGE_IN_MIN_SPEECH_MS: int = 200
    
    # === Engaged Window ===
    # Time after command to stay in "engaged" mode (no wake word needed)
    ENGAGED_WINDOW_S: int = 15
    ENGAGED_WINDOW_MAX_S: int = 20


# Singleton instance for easy access
TIMING = TimingRequirements()


# === Validation Helpers ===

def is_ack_fast_enough(response_time_ms: float) -> bool:
    """Check if ACK response time meets requirements."""
    return response_time_ms <= TIMING.ACK_MAX_MS


def is_source_time_valid(source_time_s: float) -> bool:
    """Check if source finding time is within expected range."""
    return TIMING.FIRST_SOURCE_MIN_S <= source_time_s <= TIMING.FIRST_SOURCE_MAX_S


def is_summary_fast_enough(summary_time_s: float) -> bool:
    """Check if summary generation time meets requirements."""
    return summary_time_s <= TIMING.SUMMARY_MAX_S


def get_retry_delay(attempt: int) -> float:
    """Get retry delay for given attempt number (1-indexed)."""
    delays = [
        TIMING.RETRY_DELAY_1_S,
        TIMING.RETRY_DELAY_2_S,
        TIMING.RETRY_DELAY_3_S,
    ]
    # Clamp to available delays
    index = min(attempt - 1, len(delays) - 1)
    return delays[max(0, index)]


# === Metric Recording ===

@dataclass
class TimingMetric:
    """Record of a timing measurement."""
    name: str
    value_ms: float
    threshold_ms: float
    passed: bool
    
    @property
    def value_s(self) -> float:
        """Value in seconds."""
        return self.value_ms / 1000.0
    
    @property
    def threshold_s(self) -> float:
        """Threshold in seconds."""
        return self.threshold_ms / 1000.0
    
    def __str__(self) -> str:
        status = "✓" if self.passed else "✗"
        return f"{status} {self.name}: {self.value_ms:.1f}ms (threshold: {self.threshold_ms:.1f}ms)"


def measure_ack_timing(response_time_ms: float) -> TimingMetric:
    """Create timing metric for ACK response."""
    return TimingMetric(
        name="ACK Response",
        value_ms=response_time_ms,
        threshold_ms=float(TIMING.ACK_MAX_MS),
        passed=is_ack_fast_enough(response_time_ms)
    )


def measure_summary_timing(summary_time_s: float) -> TimingMetric:
    """Create timing metric for summary generation."""
    return TimingMetric(
        name="Summary Generation",
        value_ms=summary_time_s * 1000,
        threshold_ms=float(TIMING.SUMMARY_MAX_S * 1000),
        passed=is_summary_fast_enough(summary_time_s)
    )
