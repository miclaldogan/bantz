from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RecoveryDecision:
    action: str  # retry | skip | abort | timeout
    reason: str = ""


class RecoveryPolicy:
    """Recovery policy for agent step execution.

    Features:
    - Retry up to max_retries
    - Abort on exhausted retries
    - Timeout handling for long-running steps

    Interactive recovery (ask user) is handled by Router queue controls.
    """

    def __init__(
        self,
        *,
        max_retries: int = 1,
        step_timeout_seconds: int = 60,
    ):
        self.max_retries = max(0, int(max_retries))
        self.step_timeout_seconds = max(5, int(step_timeout_seconds))

    def decide(self, *, attempt: int, elapsed_seconds: Optional[float] = None) -> RecoveryDecision:
        # Check timeout first
        if elapsed_seconds is not None and elapsed_seconds >= self.step_timeout_seconds:
            return RecoveryDecision(action="timeout", reason=f"step_timeout:{elapsed_seconds:.1f}s")

        if attempt <= self.max_retries:
            return RecoveryDecision(action="retry", reason="auto_retry")
        return RecoveryDecision(action="abort", reason="retries_exhausted")

    def should_timeout(self, elapsed_seconds: float) -> bool:
        """Check if a step should be timed out."""
        return elapsed_seconds >= self.step_timeout_seconds


# Default timeout values for different step types
STEP_TIMEOUTS = {
    "browser_open": 30,
    "browser_scan": 20,
    "browser_click": 15,
    "browser_type": 15,
    "browser_wait": 35,  # can be up to 30s explicitly
    "browser_search": 25,
    "browser_back": 15,
    "browser_scroll_down": 10,
    "browser_scroll_up": 10,
    "browser_info": 10,
    "browser_detail": 10,
    "pc_hotkey": 10,
    "pc_mouse_move": 10,
    "pc_mouse_click": 10,
    "pc_mouse_scroll": 10,
    "default": 60,
}


def get_step_timeout(intent: str) -> int:
    """Get the timeout in seconds for a given step intent."""
    return STEP_TIMEOUTS.get(intent, STEP_TIMEOUTS["default"])
