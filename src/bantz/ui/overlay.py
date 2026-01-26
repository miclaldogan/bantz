"""Bantz Overlay Window - Always-on-top visual feedback.

State Machine:
    IDLE -> WAKE -> LISTENING -> THINKING -> SPEAKING -> LISTENING/IDLE

Grid positions (3x3):
    top-left    | top-center    | top-right
    mid-left    | center        | mid-right
    bottom-left | bottom-center | bottom-right
"""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable
import logging

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QObject, QSize, QRect
)
from PyQt5.QtGui import QFont, QColor, QPainter, QPainterPath, QPixmap, QPen
from PyQt5.QtSvg import QSvgWidget

logger = logging.getLogger(__name__)


class AssistantState(Enum):
    """State machine states for the assistant."""
    IDLE = auto()       # Overlay hidden, wake-word listening
    WAKE = auto()       # Just woke up, "Sizi dinliyorum"
    LISTENING = auto()  # Actively listening to user
    THINKING = auto()   # Processing command
    SPEAKING = auto()   # Giving response
    ERROR = auto()      # Error state


class GridPosition(Enum):
    """3x3 grid positions for overlay."""
    TOP_LEFT = "top-left"
    TOP_CENTER = "top-center"
    TOP_RIGHT = "top-right"
    MID_LEFT = "mid-left"
    CENTER = "center"
    MID_RIGHT = "mid-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_CENTER = "bottom-center"
    BOTTOM_RIGHT = "bottom-right"


# Turkish position mappings
POSITION_ALIASES = {
    # Top row
    "sol üst": GridPosition.TOP_LEFT,
    "üst sol": GridPosition.TOP_LEFT,
    "üst orta": GridPosition.TOP_CENTER,
    "orta üst": GridPosition.TOP_CENTER,
    "sağ üst": GridPosition.TOP_RIGHT,
    "üst sağ": GridPosition.TOP_RIGHT,
    # Middle row
    "sol orta": GridPosition.MID_LEFT,
    "orta sol": GridPosition.MID_LEFT,
    "orta": GridPosition.CENTER,
    "ortaya": GridPosition.CENTER,
    "merkez": GridPosition.CENTER,
    "sağ orta": GridPosition.MID_RIGHT,
    "orta sağ": GridPosition.MID_RIGHT,
    # Bottom row
    "sol alt": GridPosition.BOTTOM_LEFT,
    "alt sol": GridPosition.BOTTOM_LEFT,
    "alt orta": GridPosition.BOTTOM_CENTER,
    "orta alt": GridPosition.BOTTOM_CENTER,
    "sağ alt": GridPosition.BOTTOM_RIGHT,
    "alt sağ": GridPosition.BOTTOM_RIGHT,
}


@dataclass
class OverlayConfig:
    """Configuration for overlay appearance."""
    width: int = 300
    height: int = 200
    opacity: float = 0.92
    corner_radius: int = 20
    bg_color: str = "#1a1a2e"
    accent_color: str = "#6366f1"
    text_color: str = "#ffffff"
    font_size: int = 14
    timeout_seconds: float = 8.0  # Auto-close after this much silence
    fade_duration: int = 300  # ms


class OverlaySignals(QObject):
    """Signals for thread-safe overlay control."""
    show_signal = pyqtSignal()
    hide_signal = pyqtSignal()
    set_state_signal = pyqtSignal(str, str)  # state, message
    set_position_signal = pyqtSignal(str)  # position name
    update_message_signal = pyqtSignal(str)
    set_action_signal = pyqtSignal(str, int)  # text, duration_ms
    clear_action_signal = pyqtSignal()


class BantzOverlay(QWidget):
    """Always-on-top overlay window for Bantz assistant."""
    
    def __init__(self, config: Optional[OverlayConfig] = None):
        # Ensure QApplication exists
        self._app = QApplication.instance()
        if self._app is None:
            self._app = QApplication(sys.argv)
        
        super().__init__()
        
        self.config = config or OverlayConfig()
        self.current_state = AssistantState.IDLE
        self.current_position = GridPosition.CENTER
        
        # Signals for thread-safe control
        self.signals = OverlaySignals()
        self.signals.show_signal.connect(self._do_show)
        self.signals.hide_signal.connect(self._do_hide)
        self.signals.set_state_signal.connect(self._do_set_state)
        self.signals.set_position_signal.connect(self._do_set_position)
        self.signals.update_message_signal.connect(self._do_update_message)
        self.signals.set_action_signal.connect(self._do_set_action)
        self.signals.clear_action_signal.connect(self._do_clear_action)
        
        # Timeout timer
        self._timeout_timer = QTimer(self)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_callback: Optional[Callable] = None
        
        # Fade animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(self.config.fade_duration)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._setup_ui()
        self._setup_window()
    
    def _setup_window(self):
        """Configure window properties."""
        # Frameless, always-on-top, tool window (no taskbar)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.X11BypassWindowManagerHint
        )
        
        # Transparent background
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        # Size
        self.setFixedSize(self.config.width, self.config.height)
        
        # Initial position
        self._update_position()
    
    def _setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Icon area
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(64, 64)
        layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        
        # Status text
        self.status_label = QLabel("Sizi dinliyorum efendim.")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {self.config.text_color};
                font-size: {self.config.font_size}px;
                font-weight: 500;
            }}
        """)
        layout.addWidget(self.status_label)

        # Action preview (ephemeral)
        self.action_label = QLabel("")
        self.action_label.setAlignment(Qt.AlignCenter)
        self.action_label.setWordWrap(True)
        self.action_label.setStyleSheet(f"""
            QLabel {{
                color: {self.config.text_color};
                font-size: {max(11, self.config.font_size - 2)}px;
                font-weight: 400;
                opacity: 0.9;
            }}
        """)
        self.action_label.hide()
        layout.addWidget(self.action_label)

        self._action_timer = QTimer(self)
        self._action_timer.setSingleShot(True)
        self._action_timer.timeout.connect(self._do_clear_action)
        
        # Load icons
        self._load_icons()
        
        self.setLayout(layout)
    
    def _load_icons(self):
        """Load state icons."""
        # Create simple colored circles as placeholder icons
        self._icons = {}
        
        # Listening icon (blue pulsing circle)
        self._icons[AssistantState.WAKE] = self._create_circle_icon("#6366f1")
        self._icons[AssistantState.LISTENING] = self._create_circle_icon("#10b981")
        self._icons[AssistantState.THINKING] = self._create_circle_icon("#f59e0b")
        self._icons[AssistantState.SPEAKING] = self._create_circle_icon("#8b5cf6")
        self._icons[AssistantState.ERROR] = self._create_circle_icon("#ef4444")
    
    def _create_circle_icon(self, color: str) -> QPixmap:
        """Create a simple circle icon."""
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, size - 8, size - 8)
        painter.end()
        
        return pixmap
    
    def paintEvent(self, event):
        """Draw rounded rectangle background."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background with rounded corners
        path = QPainterPath()
        path.addRoundedRect(
            0, 0,
            self.width(), self.height(),
            self.config.corner_radius, self.config.corner_radius
        )
        
        painter.fillPath(path, QColor(self.config.bg_color))
        
        # Accent border
        painter.setPen(QColor(self.config.accent_color))
        painter.drawPath(path)
    
    def _get_screen_geometry(self):
        """Get primary screen geometry."""
        screen = self._app.primaryScreen()
        return screen.availableGeometry()
    
    def _update_position(self):
        """Update window position based on grid position."""
        screen = self._get_screen_geometry()
        w, h = self.config.width, self.config.height
        margin = 20
        
        positions = {
            GridPosition.TOP_LEFT: (margin, margin),
            GridPosition.TOP_CENTER: ((screen.width() - w) // 2, margin),
            GridPosition.TOP_RIGHT: (screen.width() - w - margin, margin),
            GridPosition.MID_LEFT: (margin, (screen.height() - h) // 2),
            GridPosition.CENTER: ((screen.width() - w) // 2, (screen.height() - h) // 2),
            GridPosition.MID_RIGHT: (screen.width() - w - margin, (screen.height() - h) // 2),
            GridPosition.BOTTOM_LEFT: (margin, screen.height() - h - margin),
            GridPosition.BOTTOM_CENTER: ((screen.width() - w) // 2, screen.height() - h - margin),
            GridPosition.BOTTOM_RIGHT: (screen.width() - w - margin, screen.height() - h - margin),
        }
        
        x, y = positions[self.current_position]
        self.move(x + screen.x(), y + screen.y())
    
    # ─────────────────────────────────────────────────────────────
    # Public API (thread-safe via signals)
    # ─────────────────────────────────────────────────────────────
    
    def show_overlay(self):
        """Show overlay (thread-safe)."""
        self.signals.show_signal.emit()
    
    def hide_overlay(self):
        """Hide overlay (thread-safe)."""
        self.signals.hide_signal.emit()
    
    def set_state(self, state: AssistantState, message: str = ""):
        """Set assistant state and message (thread-safe)."""
        self.signals.set_state_signal.emit(state.name, message)
    
    def set_position(self, position: GridPosition):
        """Set overlay position (thread-safe)."""
        self.signals.set_position_signal.emit(position.value)
    
    def set_position_by_name(self, name: str) -> bool:
        """Set position by Turkish name. Returns True if valid."""
        name_lower = name.lower().strip()
        if name_lower in POSITION_ALIASES:
            self.set_position(POSITION_ALIASES[name_lower])
            return True
        return False
    
    def update_message(self, message: str):
        """Update status message (thread-safe)."""
        self.signals.update_message_signal.emit(message)

    def set_action(self, text: str, duration_ms: int = 1200):
        """Show ephemeral action preview text (thread-safe)."""
        self.signals.set_action_signal.emit(text, int(duration_ms))

    def clear_action(self):
        """Clear action preview (thread-safe)."""
        self.signals.clear_action_signal.emit()
    
    def set_timeout_callback(self, callback: Callable):
        """Set callback for timeout (false wake)."""
        self._timeout_callback = callback
    
    def start_timeout(self, seconds: Optional[float] = None):
        """Start timeout timer."""
        if seconds is None:
            seconds = self.config.timeout_seconds
        self._timeout_timer.start(int(seconds * 1000))
    
    def cancel_timeout(self):
        """Cancel timeout timer."""
        self._timeout_timer.stop()
    
    # ─────────────────────────────────────────────────────────────
    # Internal slot implementations
    # ─────────────────────────────────────────────────────────────
    
    def _do_show(self):
        """Show with fade-in animation."""
        self._opacity_effect.setOpacity(0)
        self.show()
        self._fade_anim.setStartValue(0)
        self._fade_anim.setEndValue(self.config.opacity)
        self._fade_anim.start()
    
    def _do_hide(self):
        """Hide with fade-out animation."""
        self._fade_anim.setStartValue(self.config.opacity)
        self._fade_anim.setEndValue(0)
        self._fade_anim.finished.connect(self._on_fade_out_done)
        self._fade_anim.start()
    
    def _on_fade_out_done(self):
        """Called when fade-out completes."""
        self._fade_anim.finished.disconnect(self._on_fade_out_done)
        self.hide()
    
    def _do_set_state(self, state_name: str, message: str):
        """Update state and display."""
        try:
            state = AssistantState[state_name]
        except KeyError:
            return
        
        self.current_state = state
        
        # Update icon
        if state in self._icons:
            self.icon_label.setPixmap(self._icons[state])
        
        # Update message
        if message:
            self.status_label.setText(message)
        else:
            # Default messages
            defaults = {
                AssistantState.WAKE: "Sizi dinliyorum efendim.",
                AssistantState.LISTENING: "Dinliyorum...",
                AssistantState.THINKING: "Anlıyorum...",
                AssistantState.SPEAKING: "",
                AssistantState.ERROR: "Bir hata oluştu.",
            }
            self.status_label.setText(defaults.get(state, ""))
        
        # Start timeout for wake/listening
        if state in (AssistantState.WAKE, AssistantState.LISTENING):
            self.start_timeout()
        else:
            self.cancel_timeout()
    
    def _do_set_position(self, position_value: str):
        """Update position."""
        try:
            position = GridPosition(position_value)
        except ValueError:
            return
        
        self.current_position = position
        self._update_position()
    
    def _do_update_message(self, message: str):
        """Update status message."""
        self.status_label.setText(message)

    def _do_set_action(self, text: str, duration_ms: int):
        text = (text or "").strip()
        if not text:
            self._do_clear_action()
            return

        self.action_label.setText(text)
        self.action_label.show()
        self._action_timer.stop()
        if duration_ms and duration_ms > 0:
            self._action_timer.start(duration_ms)

    def _do_clear_action(self):
        self._action_timer.stop()
        self.action_label.setText("")
        self.action_label.hide()


class CursorDotOverlay(QWidget):
    """Small always-on-top transparent widget to show a cursor dot/ring."""

    def __init__(self, color: str = "#6366f1", diameter: int = 22):
        super().__init__()
        self._color = QColor(color)
        self._diameter = int(diameter)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(self._diameter, self._diameter)
        self.hide()

    def show_at(self, x: int, y: int, duration_ms: int = 800) -> None:
        r = self._diameter // 2
        self.move(int(x) - r, int(y) - r)
        self.show()
        self.raise_()
        self._timer.stop()
        if duration_ms and duration_ms > 0:
            self._timer.start(int(duration_ms))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color)
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inset = 3
        painter.drawEllipse(inset, inset, self._diameter - 2 * inset, self._diameter - 2 * inset)


class HighlightOverlay(QWidget):
    """Fullscreen transparent overlay to draw a highlight rectangle."""

    def __init__(self, color: str = "#6366f1"):
        super().__init__()
        self._color = QColor(color)
        self._rect: Optional[QRect] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def show_rect(self, x: int, y: int, w: int, h: int, duration_ms: int = 1200) -> None:
        app = QApplication.instance()
        if app is None:
            return
        screen = app.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        self.setGeometry(geo)
        self._rect = QRect(int(x), int(y), int(w), int(h))
        self.show()
        self.raise_()
        self._timer.stop()
        if duration_ms and duration_ms > 0:
            self._timer.start(int(duration_ms))
        self.update()

    def paintEvent(self, event):
        if not self._rect:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color)
        pen.setWidth(4)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self._rect, 6, 6)
    
    def _on_timeout(self):
        """Handle timeout - false wake."""
        self._timeout_timer.stop()
        
        # Show farewell message
        self.set_state(AssistantState.SPEAKING, "Sanırım yanlış çağrı almışım, görüşmek üzere.")
        
        # Hide after a moment
        QTimer.singleShot(2000, self.hide_overlay)
        
        # Callback
        if self._timeout_callback:
            self._timeout_callback()


class OverlayManager:
    """Manager for overlay window - runs in separate thread."""
    
    _instance: Optional['OverlayManager'] = None
    _lock = threading.Lock()
    
    def __init__(self):
        self._overlay: Optional[BantzOverlay] = None
        self._thread: Optional[threading.Thread] = None
        self._app: Optional[QApplication] = None
        self._running = False
    
    @classmethod
    def get_instance(cls) -> 'OverlayManager':
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def start(self, config: Optional[OverlayConfig] = None):
        """Start overlay in background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_qt, args=(config,), daemon=True)
        self._thread.start()
        
        # Wait for overlay to be ready
        import time
        for _ in range(50):  # 5 seconds max
            if self._overlay is not None:
                break
            time.sleep(0.1)
    
    def _run_qt(self, config: Optional[OverlayConfig] = None):
        """Run Qt event loop in thread."""
        self._app = QApplication.instance()
        if self._app is None:
            self._app = QApplication([])
        
        self._overlay = BantzOverlay(config)
        self._app.exec_()
    
    def stop(self):
        """Stop overlay."""
        if self._overlay:
            self._overlay.hide_overlay()
        if self._app:
            self._app.quit()
        self._running = False
    
    @property
    def overlay(self) -> Optional[BantzOverlay]:
        """Get overlay instance."""
        return self._overlay
    
    # ─────────────────────────────────────────────────────────────
    # Convenience methods
    # ─────────────────────────────────────────────────────────────
    
    def wake(self, message: str = "Sizi dinliyorum efendim."):
        """Show overlay in wake state."""
        if self._overlay:
            self._overlay.set_state(AssistantState.WAKE, message)
            self._overlay.show_overlay()
    
    def listening(self, message: str = "Dinliyorum..."):
        """Set to listening state."""
        if self._overlay:
            self._overlay.set_state(AssistantState.LISTENING, message)
    
    def thinking(self, message: str = "Anlıyorum..."):
        """Set to thinking state."""
        if self._overlay:
            self._overlay.set_state(AssistantState.THINKING, message)
    
    def speaking(self, message: str):
        """Set to speaking state with message."""
        if self._overlay:
            self._overlay.set_state(AssistantState.SPEAKING, message)
    
    def dismiss(self):
        """Hide overlay and return to idle."""
        if self._overlay:
            self._overlay.hide_overlay()
    
    def move_to(self, position_name: str) -> bool:
        """Move overlay to position by Turkish name."""
        if self._overlay:
            return self._overlay.set_position_by_name(position_name)
        return False
    
    def set_timeout_callback(self, callback: Callable):
        """Set callback for timeout."""
        if self._overlay:
            self._overlay.set_timeout_callback(callback)
    
    def cancel_timeout(self):
        """Cancel timeout timer."""
        if self._overlay:
            self._overlay.cancel_timeout()


# Convenience function
def get_overlay_manager() -> OverlayManager:
    """Get the overlay manager singleton."""
    return OverlayManager.get_instance()
