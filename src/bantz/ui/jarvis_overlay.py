"""Jarvis-style overlay window (Issue #5).

Complete Iron Man Jarvis UI with:
- Arc reactor circular indicator
- Voice waveform visualization
- Action preview with progress
- Mini terminal output
- Draggable and transparent
- Smooth animations
"""
from __future__ import annotations

import sys
from typing import Optional, Callable, List
from enum import Enum, auto

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QGraphicsOpacityEffect, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QObject, QRect, QRectF
)
from PyQt5.QtGui import (
    QPainter, QPainterPath, QColor, QLinearGradient,
    QFont, QCursor
)

from .themes import OverlayTheme, JARVIS_THEME, get_theme, get_state_color
from .animations import (
    fade_in, fade_out, slide_to, AnimationManager,
    PulseAnimation, GlowAnimation
)
from .components import (
    ArcReactorWidget, ReactorState,
    WaveformWidget, CompactWaveform,
    ActionPreviewWidget,
    MiniTerminalWidget,
    StatusBarWidget, StatusLevel
)


class JarvisState(Enum):
    """Jarvis overlay states."""
    HIDDEN = auto()     # Overlay hidden
    IDLE = auto()       # Visible but inactive
    WAKE = auto()       # Just activated
    LISTENING = auto()  # Actively listening
    THINKING = auto()   # Processing command
    SPEAKING = auto()   # Giving response
    ACTION = auto()     # Executing action
    ERROR = auto()      # Error state


class GridPosition(Enum):
    """Screen grid positions."""
    TOP_LEFT = "top-left"
    TOP_CENTER = "top-center"
    TOP_RIGHT = "top-right"
    MID_LEFT = "mid-left"
    CENTER = "center"
    MID_RIGHT = "mid-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_CENTER = "bottom-center"
    BOTTOM_RIGHT = "bottom-right"


# Turkish position aliases
POSITION_ALIASES = {
    "sol üst": GridPosition.TOP_LEFT,
    "üst sol": GridPosition.TOP_LEFT,
    "üst orta": GridPosition.TOP_CENTER,
    "sağ üst": GridPosition.TOP_RIGHT,
    "üst sağ": GridPosition.TOP_RIGHT,
    "sol orta": GridPosition.MID_LEFT,
    "orta": GridPosition.CENTER,
    "ortaya": GridPosition.CENTER,
    "merkez": GridPosition.CENTER,
    "sağ orta": GridPosition.MID_RIGHT,
    "sol alt": GridPosition.BOTTOM_LEFT,
    "alt orta": GridPosition.BOTTOM_CENTER,
    "sağ alt": GridPosition.BOTTOM_RIGHT,
    "alt sağ": GridPosition.BOTTOM_RIGHT,
}


class JarvisOverlaySignals(QObject):
    """Thread-safe signals for overlay control."""
    show_signal = pyqtSignal()
    hide_signal = pyqtSignal()
    set_state_signal = pyqtSignal(str, str)  # state, message
    set_position_signal = pyqtSignal(str)
    update_message_signal = pyqtSignal(str)
    set_action_signal = pyqtSignal(str, list)  # description, steps
    advance_step_signal = pyqtSignal()
    add_terminal_signal = pyqtSignal(str, str)  # text, type
    set_theme_signal = pyqtSignal(str)


class JarvisOverlay(QWidget):
    """Iron Man Jarvis-style overlay window.
    
    Features:
    - Arc reactor circular indicator with state animations
    - Real-time voice waveform visualization
    - Action preview with step progress
    - Mini terminal for command output
    - Draggable to any position
    - Configurable themes (Jarvis, Friday, Ultron)
    - Smooth fade/slide animations
    - Transparent background with glow
    
    Signals:
        state_changed: Emitted when state changes
        position_changed: Emitted when position changes
        timeout: Emitted when auto-hide timeout triggers
    """
    
    state_changed = pyqtSignal(str)
    position_changed = pyqtSignal(str)
    timeout = pyqtSignal()
    
    def __init__(
        self,
        theme: Optional[OverlayTheme] = None,
        show_terminal: bool = True,
        show_action_preview: bool = True,
        parent: Optional[QWidget] = None,
    ):
        # Ensure QApplication exists
        self._app = QApplication.instance()
        if self._app is None:
            self._app = QApplication(sys.argv)
        
        super().__init__(parent)
        
        # Configuration
        self.theme = theme or JARVIS_THEME
        self._show_terminal = show_terminal
        self._show_action_preview = show_action_preview
        
        # State
        self._state = JarvisState.HIDDEN
        self._position = GridPosition.CENTER
        self._message = ""
        self._opacity = 0.95
        
        # Dragging
        self._dragging = False
        self._drag_position = QPoint()
        
        # Signals for thread safety
        self.signals = JarvisOverlaySignals()
        self._connect_signals()
        
        # Timeout timer
        self._timeout_timer = QTimer(self)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_seconds = 10.0
        self._timeout_callback: Optional[Callable] = None
        
        # Setup
        self._setup_window()
        self._setup_ui()
        self._setup_animations()
        
        # Animation manager
        self._anim_manager = AnimationManager(self)
    
    def _connect_signals(self):
        """Connect thread-safe signals."""
        self.signals.show_signal.connect(self._do_show)
        self.signals.hide_signal.connect(self._do_hide)
        self.signals.set_state_signal.connect(self._do_set_state)
        self.signals.set_position_signal.connect(self._do_set_position)
        self.signals.update_message_signal.connect(self._do_update_message)
        self.signals.set_action_signal.connect(self._do_set_action)
        self.signals.advance_step_signal.connect(self._do_advance_step)
        self.signals.add_terminal_signal.connect(self._do_add_terminal)
        self.signals.set_theme_signal.connect(self._do_set_theme)
    
    def _setup_window(self):
        """Configure window properties."""
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.X11BypassWindowManagerHint
        )
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        self.setMinimumSize(320, 200)
        self.setMaximumSize(500, 600)
        self.resize(380, 350)
    
    def _setup_ui(self):
        """Setup UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)
        
        # Top section: Arc reactor + waveform + status
        top_layout = QHBoxLayout()
        top_layout.setSpacing(15)
        
        # Arc reactor
        self.arc_reactor = ArcReactorWidget(size=80, theme=self.theme)
        top_layout.addWidget(self.arc_reactor)
        
        # Center: Message + waveform
        center_layout = QVBoxLayout()
        center_layout.setSpacing(8)
        
        # Message label
        self.message_label = QLabel("Sizi dinliyorum efendim.")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"""
            QLabel {{
                color: {self.theme.text};
                font-size: 14px;
                font-weight: 500;
            }}
        """)
        center_layout.addWidget(self.message_label)
        
        # Waveform
        self.waveform = WaveformWidget(
            num_bars=15,
            bar_width=4,
            bar_gap=2,
            max_height=30,
            theme=self.theme
        )
        center_layout.addWidget(self.waveform, alignment=Qt.AlignCenter)
        
        top_layout.addLayout(center_layout, 1)
        
        # Status bar (right side)
        self.status_bar = StatusBarWidget(theme=self.theme)
        top_layout.addWidget(self.status_bar)
        
        main_layout.addLayout(top_layout)
        
        # Separator
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {self.theme.primary}40;")
        main_layout.addWidget(separator)
        
        # Action preview
        if self._show_action_preview:
            self.action_preview = ActionPreviewWidget(theme=self.theme)
            self.action_preview.hide()
            main_layout.addWidget(self.action_preview)
        else:
            self.action_preview = None
        
        # Mini terminal
        if self._show_terminal:
            self.mini_terminal = MiniTerminalWidget(max_lines=5, theme=self.theme)
            self.mini_terminal.hide()
            main_layout.addWidget(self.mini_terminal)
        else:
            self.mini_terminal = None
        
        main_layout.addStretch()
        
        # Apply theme stylesheet
        self.setStyleSheet(self.theme.stylesheet)
    
    def _setup_animations(self):
        """Setup animation effects."""
        # Glow effect
        self._glow_effect = QGraphicsDropShadowEffect(self)
        self._glow_effect.setBlurRadius(20)
        self._glow_effect.setColor(QColor(self.theme.primary))
        self._glow_effect.setOffset(0, 0)
        self.setGraphicsEffect(self._glow_effect)
    
    # ─────────────────────────────────────────────────────────────────
    # Painting
    # ─────────────────────────────────────────────────────────────────
    
    def paintEvent(self, event):
        """Draw rounded rectangle background with gradient border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background path
        path = QPainterPath()
        rect = QRectF(self.rect().adjusted(2, 2, -2, -2))
        path.addRoundedRect(rect, 15.0, 15.0)
        
        # Background fill
        bg_color = QColor(self.theme.background)
        bg_color.setAlphaF(self._opacity)
        painter.fillPath(path, bg_color)
        
        # Border gradient
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        primary = QColor(self.theme.primary)
        secondary = QColor(self.theme.secondary)
        primary.setAlpha(200)
        secondary.setAlpha(150)
        gradient.setColorAt(0, primary)
        gradient.setColorAt(1, secondary)
        
        painter.strokePath(path, gradient)
    
    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────
    
    def show_overlay(self):
        """Show overlay with fade in animation (thread-safe)."""
        self.signals.show_signal.emit()
    
    def hide_overlay(self):
        """Hide overlay with fade out animation (thread-safe)."""
        self.signals.hide_signal.emit()
    
    def set_state(self, state: str, message: str = ""):
        """Set overlay state (thread-safe)."""
        self.signals.set_state_signal.emit(state, message)
    
    def set_position(self, position: str):
        """Set overlay position (thread-safe)."""
        self.signals.set_position_signal.emit(position)
    
    def update_message(self, message: str):
        """Update message text (thread-safe)."""
        self.signals.update_message_signal.emit(message)
    
    def set_action(self, description: str, steps: Optional[List[str]] = None):
        """Set current action (thread-safe)."""
        self.signals.set_action_signal.emit(description, steps or [])
    
    def advance_step(self):
        """Advance action step (thread-safe)."""
        self.signals.advance_step_signal.emit()
    
    def add_terminal_output(self, text: str, output_type: str = "stdout"):
        """Add terminal output (thread-safe)."""
        self.signals.add_terminal_signal.emit(text, output_type)
    
    def set_theme_name(self, name: str):
        """Set theme by name (thread-safe)."""
        self.signals.set_theme_signal.emit(name)
    
    # Non-thread-safe direct methods (call from main thread only)
    
    def update_audio(self, audio_chunk: bytes):
        """Update waveform with audio data."""
        self.waveform.update_audio(audio_chunk)
    
    def update_audio_level(self, level: float):
        """Update waveform with audio level."""
        self.waveform.set_level(level)
    
    def set_timeout(self, seconds: float, callback: Optional[Callable] = None):
        """Set auto-hide timeout."""
        self._timeout_seconds = seconds
        self._timeout_callback = callback
    
    def set_opacity(self, opacity: float):
        """Set background opacity (0.0-1.0)."""
        self._opacity = max(0.0, min(1.0, opacity))
        self.update()
    
    # ─────────────────────────────────────────────────────────────────
    # Slot Implementations
    # ─────────────────────────────────────────────────────────────────
    
    def _do_show(self):
        """Show overlay with animation."""
        if not self.isVisible():
            self._update_position()
            fade_in(self)
            self.waveform.start()
        
        self._reset_timeout()
    
    def _do_hide(self):
        """Hide overlay with animation."""
        self._timeout_timer.stop()
        self.waveform.stop()
        fade_out(self)
    
    def _do_set_state(self, state_str: str, message: str):
        """Set overlay state."""
        try:
            new_state = JarvisState[state_str.upper()]
        except KeyError:
            new_state = JarvisState.IDLE
        
        old_state = self._state
        self._state = new_state
        
        # Update arc reactor
        reactor_state = self._map_to_reactor_state(new_state)
        self.arc_reactor.set_state(reactor_state.value)
        
        # Update message
        if message:
            self._message = message
            self.message_label.setText(message)
        
        # Update status bar
        if new_state == JarvisState.LISTENING:
            self.status_bar.set_mic_status(StatusLevel.OK)
            self.waveform.set_demo_mode(False)
        elif new_state == JarvisState.THINKING:
            self.status_bar.set_processing_status(StatusLevel.PROCESSING)
        elif new_state == JarvisState.ERROR:
            self.status_bar.set_status("processing", StatusLevel.ERROR)
        else:
            self.status_bar.set_all_status(StatusLevel.INACTIVE)
        
        # Update glow color
        glow_color = get_state_color(new_state.name.lower(), self.theme)
        try:
            if self._glow_effect is not None:
                self._glow_effect.setColor(glow_color)
        except RuntimeError:
            pass  # Qt object may have been deleted
        
        # Show/hide if needed
        if new_state == JarvisState.HIDDEN:
            self._do_hide()
        elif not self.isVisible():
            self._do_show()
        
        self._reset_timeout()
        self.state_changed.emit(state_str)
    
    def _do_set_position(self, position_str: str):
        """Set overlay position."""
        # Check aliases
        position_str_lower = position_str.lower()
        if position_str_lower in POSITION_ALIASES:
            position = POSITION_ALIASES[position_str_lower]
        else:
            try:
                position = GridPosition(position_str_lower)
            except ValueError:
                position = GridPosition.CENTER
        
        self._position = position
        target = self._calculate_position(position)
        
        # Animate to position
        slide_to(self, target)
        self.position_changed.emit(position.value)
    
    def _do_update_message(self, message: str):
        """Update message text."""
        self._message = message
        self.message_label.setText(message)
    
    def _do_set_action(self, description: str, steps: List[str]):
        """Set action preview."""
        if self.action_preview:
            self.action_preview.set_action(description, steps)
            self.action_preview.show()
    
    def _do_advance_step(self):
        """Advance action step."""
        if self.action_preview:
            self.action_preview.advance_step()
    
    def _do_add_terminal(self, text: str, output_type: str):
        """Add terminal output."""
        if self.mini_terminal:
            self.mini_terminal.show()
            
            if output_type == "command":
                self.mini_terminal.add_command(text)
            elif output_type == "stderr":
                self.mini_terminal.add_stderr(text)
            elif output_type == "error":
                self.mini_terminal.add_error(text)
            elif output_type == "success":
                self.mini_terminal.add_success(text)
            else:
                self.mini_terminal.add_stdout(text)
    
    def _do_set_theme(self, name: str):
        """Set theme by name."""
        self.theme = get_theme(name)
        
        # Update all components
        self.arc_reactor.set_theme(self.theme)
        self.waveform.set_theme(self.theme)
        self.status_bar.set_theme(self.theme)
        
        if self.action_preview:
            self.action_preview.set_theme(self.theme)
        if self.mini_terminal:
            self.mini_terminal.set_theme(self.theme)
        
        # Update styles
        self.message_label.setStyleSheet(f"""
            QLabel {{
                color: {self.theme.text};
                font-size: 14px;
                font-weight: 500;
            }}
        """)
        self._glow_effect.setColor(QColor(self.theme.primary))
        self.setStyleSheet(self.theme.stylesheet)
        self.update()
    
    # ─────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────
    
    def _map_to_reactor_state(self, state: JarvisState) -> ReactorState:
        """Map JarvisState to ReactorState."""
        mapping = {
            JarvisState.HIDDEN: ReactorState.IDLE,
            JarvisState.IDLE: ReactorState.IDLE,
            JarvisState.WAKE: ReactorState.WAKE,
            JarvisState.LISTENING: ReactorState.LISTENING,
            JarvisState.THINKING: ReactorState.THINKING,
            JarvisState.SPEAKING: ReactorState.SPEAKING,
            JarvisState.ACTION: ReactorState.THINKING,
            JarvisState.ERROR: ReactorState.ERROR,
        }
        return mapping.get(state, ReactorState.IDLE)
    
    def _calculate_position(self, position: GridPosition) -> QPoint:
        """Calculate screen position for grid position."""
        screen = QApplication.primaryScreen().availableGeometry()
        
        # Calculate x
        if "left" in position.value:
            x = screen.left() + 20
        elif "right" in position.value:
            x = screen.right() - self.width() - 20
        else:
            x = screen.left() + (screen.width() - self.width()) // 2
        
        # Calculate y
        if "top" in position.value:
            y = screen.top() + 20
        elif "bottom" in position.value:
            y = screen.bottom() - self.height() - 20
        else:
            y = screen.top() + (screen.height() - self.height()) // 2
        
        return QPoint(x, y)
    
    def _update_position(self):
        """Update position without animation."""
        pos = self._calculate_position(self._position)
        self.move(pos)
    
    def _reset_timeout(self):
        """Reset auto-hide timeout."""
        if self._timeout_seconds > 0:
            self._timeout_timer.start(int(self._timeout_seconds * 1000))
    
    def _on_timeout(self):
        """Handle timeout."""
        self._timeout_timer.stop()
        self.timeout.emit()
        
        if self._timeout_callback:
            self._timeout_callback()
        else:
            self._do_hide()
    
    # ─────────────────────────────────────────────────────────────────
    # Mouse Events (Dragging)
    # ─────────────────────────────────────────────────────────────────
    
    def mousePressEvent(self, event):
        """Start drag."""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle drag."""
        if self._dragging:
            self.move(event.globalPos() - self._drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """End drag."""
        self._dragging = False
        event.accept()
    
    def enterEvent(self, event):
        """Stop timeout on hover."""
        self._timeout_timer.stop()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Restart timeout on leave."""
        self._reset_timeout()
        super().leaveEvent(event)


# ─────────────────────────────────────────────────────────────────
# Factory Function
# ─────────────────────────────────────────────────────────────────

def create_jarvis_overlay(
    theme_name: str = "jarvis",
    show_terminal: bool = True,
    show_action_preview: bool = True,
) -> JarvisOverlay:
    """Create a JarvisOverlay with specified options.
    
    Args:
        theme_name: Theme name (jarvis, friday, ultron, vision)
        show_terminal: Show mini terminal
        show_action_preview: Show action preview
        
    Returns:
        Configured JarvisOverlay instance
    """
    theme = get_theme(theme_name)
    return JarvisOverlay(
        theme=theme,
        show_terminal=show_terminal,
        show_action_preview=show_action_preview,
    )
