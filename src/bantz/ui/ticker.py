"""
Ticker Widget (Issue #34 - UI-2).

Scrolling/fading text ticker for status messages:
- SCROLL mode: continuous horizontal scroll
- FADE mode: fade in/out transitions
- STATIC mode: no animation
"""

from typing import Optional, List, Deque
from collections import deque
from enum import Enum, auto
from PyQt5.QtWidgets import (
    QFrame, QLabel, QHBoxLayout, QGraphicsOpacityEffect, QSizePolicy
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QTimer, QPropertyAnimation,
    QEasingCurve, QPoint
)
from PyQt5.QtGui import QFont, QColor


class TickerMode(Enum):
    """Ticker animation mode."""
    SCROLL = auto()   # Continuous horizontal scroll
    FADE = auto()     # Fade in/out transitions
    STATIC = auto()   # No animation, static display


# Default configuration
DEFAULT_SCROLL_SPEED = 50       # Pixels per second
DEFAULT_FADE_DURATION = 300     # Milliseconds
DEFAULT_MESSAGE_DURATION = 5000 # Milliseconds for static/fade modes


class Ticker(QFrame):
    """
    Ticker widget for status messages.
    
    Supports three modes:
    - SCROLL: Text scrolls horizontally
    - FADE: Text fades in/out
    - STATIC: Text displays without animation
    
    Can queue multiple messages.
    """
    
    # Signals
    message_changed = pyqtSignal(str)      # Emits when message changes
    queue_empty = pyqtSignal()             # Emits when queue is empty
    
    def __init__(
        self,
        mode: TickerMode = TickerMode.SCROLL,
        parent: Optional[QFrame] = None
    ):
        super().__init__(parent)
        
        self._mode = mode
        self._current_message = ""
        self._message_queue: Deque[str] = deque()
        self._scroll_position = 0
        
        # Animation state
        self._scroll_timer: Optional[QTimer] = None
        self._fade_animation: Optional[QPropertyAnimation] = None
        self._message_timer: Optional[QTimer] = None
        self._is_animating = False
        
        self._setup_ui()
        self._setup_style()
    
    def _setup_ui(self):
        """Setup ticker UI."""
        self.setObjectName("ticker")
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)
        
        # Text label
        self._label = QLabel("")
        self._label.setFont(QFont("Consolas", 10))
        self._label.setStyleSheet("color: #00CCFF;")
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._label)
        
        # Opacity effect for fade mode
        self._opacity_effect = QGraphicsOpacityEffect(self._label)
        self._opacity_effect.setOpacity(1.0)
        self._label.setGraphicsEffect(self._opacity_effect)
    
    def _setup_style(self):
        """Setup ticker styling."""
        self.setStyleSheet("""
            QFrame#ticker {
                background-color: rgba(0, 20, 40, 0.8);
                border: 1px solid rgba(0, 162, 255, 0.3);
                border-radius: 4px;
            }
        """)
    
    def set_message(self, message: str) -> None:
        """
        Set current message immediately.
        
        Args:
            message: Message to display
        """
        self._current_message = message
        self._label.setText(message)
        self.message_changed.emit(message)
        
        self._stop_animations()
        self._start_animation()
    
    def queue_message(self, message: str) -> None:
        """
        Queue a message for display.
        
        Args:
            message: Message to queue
        """
        self._message_queue.append(message)
        
        # If not currently showing anything, start
        if not self._current_message:
            self._next_message()
    
    def clear(self) -> None:
        """Clear current message and queue."""
        self._message_queue.clear()
        self._current_message = ""
        self._label.setText("")
        self._stop_animations()
        self.queue_empty.emit()
    
    def set_mode(self, mode: TickerMode) -> None:
        """
        Set ticker animation mode.
        
        Args:
            mode: Animation mode
        """
        if mode == self._mode:
            return
        
        self._stop_animations()
        self._mode = mode
        self._start_animation()
    
    def get_mode(self) -> TickerMode:
        """Get current ticker mode."""
        return self._mode
    
    def is_animating(self) -> bool:
        """Check if ticker is currently animating."""
        return self._is_animating
    
    def _next_message(self):
        """Show next message from queue."""
        if self._message_queue:
            message = self._message_queue.popleft()
            self._current_message = message
            self._label.setText(message)
            self.message_changed.emit(message)
            
            self._stop_animations()
            self._start_animation()
        else:
            self._current_message = ""
            self._label.setText("")
            self.queue_empty.emit()
    
    def _start_animation(self):
        """Start animation based on current mode."""
        if not self._current_message:
            return
        
        self._is_animating = True
        
        if self._mode == TickerMode.SCROLL:
            self._start_scroll_animation()
        elif self._mode == TickerMode.FADE:
            self._start_fade_animation()
        else:  # STATIC
            self._start_static_display()
    
    def _start_scroll_animation(self):
        """Start scroll animation."""
        self._scroll_position = 0
        
        # Start scroll timer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.timeout.connect(self._scroll_tick)
        self._scroll_timer.start(20)  # ~50 FPS
    
    def _scroll_tick(self):
        """Handle scroll tick."""
        label_width = self._label.fontMetrics().horizontalAdvance(self._current_message)
        frame_width = self.width() - 24  # Account for margins
        
        # Calculate scroll step
        step = DEFAULT_SCROLL_SPEED * 0.02  # Speed * frame time
        self._scroll_position += step
        
        # Reset when fully scrolled
        if self._scroll_position > label_width + 20:
            self._scroll_position = -frame_width
        
        # Apply scroll offset using padding
        self._label.setStyleSheet(f"""
            color: #00CCFF;
            padding-left: {int(-self._scroll_position)}px;
        """)
    
    def _start_fade_animation(self):
        """Start fade in animation."""
        self._opacity_effect.setOpacity(0.0)
        
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_animation.setDuration(DEFAULT_FADE_DURATION)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_animation.finished.connect(self._on_fade_in_complete)
        self._fade_animation.start()
    
    def _on_fade_in_complete(self):
        """Handle fade in complete."""
        # Start message display timer
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._start_fade_out)
        self._message_timer.start(DEFAULT_MESSAGE_DURATION)
    
    def _start_fade_out(self):
        """Start fade out animation."""
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_animation.setDuration(DEFAULT_FADE_DURATION)
        self._fade_animation.setStartValue(1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
        self._fade_animation.finished.connect(self._on_fade_out_complete)
        self._fade_animation.start()
    
    def _on_fade_out_complete(self):
        """Handle fade out complete."""
        self._is_animating = False
        self._next_message()
    
    def _start_static_display(self):
        """Start static display with timer for next message."""
        self._opacity_effect.setOpacity(1.0)
        
        # If queue has more messages, set timer for next
        if self._message_queue:
            self._message_timer = QTimer(self)
            self._message_timer.setSingleShot(True)
            self._message_timer.timeout.connect(self._on_static_complete)
            self._message_timer.start(DEFAULT_MESSAGE_DURATION)
        else:
            self._is_animating = False
    
    def _on_static_complete(self):
        """Handle static display complete."""
        self._is_animating = False
        self._next_message()
    
    def _stop_animations(self):
        """Stop all running animations."""
        self._is_animating = False
        
        # Stop scroll timer
        if self._scroll_timer and self._scroll_timer.isActive():
            self._scroll_timer.stop()
            self._scroll_timer = None
        
        # Stop fade animation
        if self._fade_animation:
            self._fade_animation.stop()
            self._fade_animation = None
        
        # Stop message timer
        if self._message_timer and self._message_timer.isActive():
            self._message_timer.stop()
            self._message_timer = None
        
        # Reset opacity
        self._opacity_effect.setOpacity(1.0)
        
        # Reset scroll position
        self._scroll_position = 0
        self._label.setStyleSheet("color: #00CCFF;")
