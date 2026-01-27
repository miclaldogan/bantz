"""
Engaged Window Manager (Issue #35 - Voice-2).

Manages the "engaged" state window where the system
listens without requiring a wake word.

Window behavior:
- Starts with default timeout (10-20 seconds)
- Extends on user speech activity
- Respects max timeout limit
- Can be manually closed
"""

from typing import Optional, Callable
from dataclasses import dataclass
import time
import threading


@dataclass
class EngagedWindowConfig:
    """Configuration for engaged window."""
    min_timeout: float = 10.0      # Minimum window duration
    max_timeout: float = 20.0      # Maximum window duration
    default_timeout: float = 15.0  # Default window duration
    extension_amount: float = 5.0  # Seconds to extend on speech


class EngagedWindowManager:
    """
    Manages the engaged listening window.
    
    The engaged window is active after a wake word detection,
    allowing follow-up commands without re-triggering wake word.
    
    Usage:
        window = EngagedWindowManager()
        window.start_window()
        
        if window.is_active:
            # Accept speech without wake word
            window.on_user_speech()  # Extend window
        
        # When timeout expires or manually closed
        window.close_window()
    """
    
    def __init__(
        self,
        min_timeout: float = 10.0,
        max_timeout: float = 20.0,
        default_timeout: float = 15.0,
        on_expired: Optional[Callable[[], None]] = None
    ):
        """
        Initialize EngagedWindowManager.
        
        Args:
            min_timeout: Minimum window duration (seconds)
            max_timeout: Maximum window duration (seconds)
            default_timeout: Default window duration (seconds)
            on_expired: Callback when window expires
        """
        self._config = EngagedWindowConfig(
            min_timeout=min_timeout,
            max_timeout=max_timeout,
            default_timeout=default_timeout
        )
        
        self._on_expired = on_expired
        
        self._start_time: Optional[float] = None
        self._current_timeout: float = default_timeout
        self._lock = threading.Lock()
        
        # Timer for expiry notification
        self._expiry_timer: Optional[threading.Timer] = None
    
    def start_window(self, timeout: Optional[float] = None) -> None:
        """
        Start or restart the engaged window.
        
        Args:
            timeout: Custom timeout (uses default if None)
        """
        with self._lock:
            self._cancel_timer()
            
            self._start_time = time.time()
            self._current_timeout = timeout or self._config.default_timeout
            
            # Clamp to min/max
            self._current_timeout = max(
                self._config.min_timeout,
                min(self._current_timeout, self._config.max_timeout)
            )
            
            # Schedule expiry callback
            self._schedule_expiry()
    
    def extend_window(self, seconds: Optional[float] = None) -> None:
        """
        Extend the engaged window.
        
        Args:
            seconds: Seconds to extend (uses config default if None)
        """
        with self._lock:
            if self._start_time is None:
                return
            
            extension = seconds or self._config.extension_amount
            new_timeout = self._current_timeout + extension
            
            # Respect max timeout
            if new_timeout > self._config.max_timeout:
                new_timeout = self._config.max_timeout
            
            self._current_timeout = new_timeout
            
            # Reschedule expiry
            self._cancel_timer()
            self._schedule_expiry()
    
    def close_window(self) -> None:
        """Close the engaged window immediately."""
        with self._lock:
            self._cancel_timer()
            self._start_time = None
            self._current_timeout = self._config.default_timeout
    
    @property
    def is_active(self) -> bool:
        """Check if engaged window is currently active."""
        with self._lock:
            if self._start_time is None:
                return False
            
            elapsed = time.time() - self._start_time
            return elapsed < self._current_timeout
    
    @property
    def remaining_time(self) -> float:
        """Get remaining time in engaged window (seconds)."""
        with self._lock:
            if self._start_time is None:
                return 0.0
            
            elapsed = time.time() - self._start_time
            remaining = self._current_timeout - elapsed
            return max(0.0, remaining)
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time since window started (seconds)."""
        with self._lock:
            if self._start_time is None:
                return 0.0
            return time.time() - self._start_time
    
    @property
    def current_timeout(self) -> float:
        """Get current timeout value."""
        with self._lock:
            return self._current_timeout
    
    def on_user_speech(self) -> None:
        """
        Handle user speech activity.
        
        Extends the window on speech to allow follow-up commands.
        """
        self.extend_window()
    
    def on_expired_callback(self, callback: Callable[[], None]) -> None:
        """Register callback for window expiry."""
        self._on_expired = callback
    
    def _schedule_expiry(self) -> None:
        """Schedule expiry timer."""
        if self._start_time is None:
            return
        
        remaining = self.remaining_time
        if remaining > 0 and self._on_expired:
            self._expiry_timer = threading.Timer(remaining, self._handle_expiry)
            self._expiry_timer.daemon = True
            self._expiry_timer.start()
    
    def _cancel_timer(self) -> None:
        """Cancel pending expiry timer."""
        if self._expiry_timer:
            self._expiry_timer.cancel()
            self._expiry_timer = None
    
    def _handle_expiry(self) -> None:
        """Handle window expiry."""
        with self._lock:
            # Verify still expired (might have been extended)
            if not self.is_active and self._on_expired:
                self._on_expired()
    
    def get_stats(self) -> dict:
        """Get window statistics."""
        with self._lock:
            return {
                "is_active": self.is_active,
                "remaining_time": self.remaining_time,
                "elapsed_time": self.elapsed_time,
                "current_timeout": self._current_timeout,
                "min_timeout": self._config.min_timeout,
                "max_timeout": self._config.max_timeout,
            }


def create_engaged_window(
    min_timeout: float = 10.0,
    max_timeout: float = 20.0,
    default_timeout: float = 15.0,
    on_expired: Optional[Callable[[], None]] = None
) -> EngagedWindowManager:
    """
    Factory function to create EngagedWindowManager.
    
    Args:
        min_timeout: Minimum window duration
        max_timeout: Maximum window duration
        default_timeout: Default window duration
        on_expired: Callback when window expires
    
    Returns:
        Configured EngagedWindowManager instance
    """
    return EngagedWindowManager(
        min_timeout=min_timeout,
        max_timeout=max_timeout,
        default_timeout=default_timeout,
        on_expired=on_expired
    )
