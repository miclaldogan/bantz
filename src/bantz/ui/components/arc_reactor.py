"""Arc Reactor circular indicator widget (Issue #5).

Iron Man style circular indicator with:
- Multiple concentric rings
- State-based color changes
- Pulsing glow effects
- Smooth state transitions
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Optional, List

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import (
    Qt, QTimer, QRectF, QPointF, pyqtSignal, pyqtProperty,
    QPropertyAnimation, QEasingCurve, QVariantAnimation, QSequentialAnimationGroup
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QConicalGradient,
    QPainterPath, QFont
)

from ..themes import OverlayTheme, JARVIS_THEME, get_state_color


class ReactorState(Enum):
    """Arc reactor states."""
    IDLE = "idle"
    WAKE = "wake"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    SUCCESS = "success"


class ArcReactorWidget(QWidget):
    """Circular Jarvis-style indicator widget.
    
    Displays a multi-ring arc reactor with:
    - Outer rotating ring
    - Middle pulsing ring
    - Inner core with glow
    - State indicator in center
    
    Signals:
        state_changed: Emitted when state changes
        clicked: Emitted when reactor is clicked
    """
    
    state_changed = pyqtSignal(str)  # state name
    clicked = pyqtSignal()
    
    # Animation properties
    _pulse_value = 0.0
    _rotation_angle = 0.0
    _glow_intensity = 0.5
    
    def __init__(
        self,
        size: int = 120,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.reactor_size = size
        self.theme = theme or JARVIS_THEME
        self._state = ReactorState.IDLE
        self._text = ""
        
        # Ring configuration
        self._ring_widths = [3, 5, 8, 12]  # outer to inner
        self._ring_gaps = [8, 12, 15]  # gaps between rings
        
        # Colors (will be updated based on state)
        self._primary_color = QColor(self.theme.primary)
        self._secondary_color = QColor(self.theme.secondary)
        self._core_color = QColor("#FFFFFF")
        
        # Setup
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Animation timers
        self._rotation_timer = QTimer(self)
        self._rotation_timer.timeout.connect(self._update_rotation)
        self._rotation_speed = 1.0  # degrees per tick
        
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_phase = 0.0
        
        # Start animations
        self._start_animations()
    
    # ─────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────
    
    @property
    def state(self) -> ReactorState:
        """Current reactor state."""
        return self._state
    
    @state.setter
    def state(self, value: ReactorState):
        """Set reactor state with animation."""
        if self._state != value:
            old_state = self._state
            self._state = value
            self._update_state_colors()
            self._update_animation_speed()
            self.state_changed.emit(value.value)
            self.update()
    
    def set_state(self, state: str):
        """Set state by name string."""
        try:
            self.state = ReactorState(state.lower())
        except ValueError:
            self.state = ReactorState.IDLE
    
    @property
    def text(self) -> str:
        """Center text."""
        return self._text
    
    @text.setter
    def text(self, value: str):
        """Set center text."""
        self._text = value
        self.update()
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme colors."""
        self.theme = theme
        self._primary_color = QColor(theme.primary)
        self._secondary_color = QColor(theme.secondary)
        self.update()
    
    # ─────────────────────────────────────────────────────────────────
    # State Management
    # ─────────────────────────────────────────────────────────────────
    
    def _update_state_colors(self):
        """Update colors based on current state."""
        color = get_state_color(self._state.value, self.theme)
        self._primary_color = color
        
        # Adjust secondary color (slightly darker)
        self._secondary_color = QColor(color)
        self._secondary_color.setHsv(
            self._secondary_color.hue(),
            self._secondary_color.saturation(),
            max(0, self._secondary_color.value() - 40),
        )
    
    def _update_animation_speed(self):
        """Adjust animation speed based on state."""
        if self._state == ReactorState.IDLE:
            self._rotation_speed = 0.5
            self._pulse_timer.setInterval(50)
        elif self._state == ReactorState.WAKE:
            self._rotation_speed = 2.0
            self._pulse_timer.setInterval(30)
        elif self._state == ReactorState.LISTENING:
            self._rotation_speed = 1.5
            self._pulse_timer.setInterval(40)
        elif self._state == ReactorState.THINKING:
            self._rotation_speed = 3.0
            self._pulse_timer.setInterval(20)
        elif self._state == ReactorState.SPEAKING:
            self._rotation_speed = 1.0
            self._pulse_timer.setInterval(35)
        elif self._state == ReactorState.ERROR:
            self._rotation_speed = 0.2
            self._pulse_timer.setInterval(100)
        else:
            self._rotation_speed = 1.0
            self._pulse_timer.setInterval(40)
    
    # ─────────────────────────────────────────────────────────────────
    # Animations
    # ─────────────────────────────────────────────────────────────────
    
    def _start_animations(self):
        """Start all animations."""
        self._rotation_timer.start(16)  # ~60fps
        self._pulse_timer.start(40)
    
    def _stop_animations(self):
        """Stop all animations."""
        self._rotation_timer.stop()
        self._pulse_timer.stop()
    
    def _update_rotation(self):
        """Update rotation angle."""
        self._rotation_angle = (self._rotation_angle + self._rotation_speed) % 360
        self.update()
    
    def _update_pulse(self):
        """Update pulse value (0.0 to 1.0)."""
        self._pulse_phase += 0.1
        self._pulse_value = (math.sin(self._pulse_phase) + 1) / 2
        self._glow_intensity = 0.3 + 0.4 * self._pulse_value
        self.update()
    
    # ─────────────────────────────────────────────────────────────────
    # Painting
    # ─────────────────────────────────────────────────────────────────
    
    def paintEvent(self, event):
        """Draw the arc reactor."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center = QPointF(self.width() / 2, self.height() / 2)
        max_radius = min(self.width(), self.height()) / 2 - 5
        
        # Draw from outside in
        self._draw_outer_glow(painter, center, max_radius)
        self._draw_outer_ring(painter, center, max_radius)
        self._draw_middle_rings(painter, center, max_radius)
        self._draw_inner_core(painter, center, max_radius)
        self._draw_center_text(painter, center)
    
    def _draw_outer_glow(self, painter: QPainter, center: QPointF, radius: float):
        """Draw the outer glow effect."""
        glow_radius = radius + 10
        
        gradient = QRadialGradient(center, glow_radius)
        glow_color = QColor(self._primary_color)
        glow_color.setAlphaF(0.3 * self._glow_intensity)
        gradient.setColorAt(0.5, glow_color)
        glow_color.setAlpha(0)
        gradient.setColorAt(1.0, glow_color)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, glow_radius, glow_radius)
    
    def _draw_outer_ring(self, painter: QPainter, center: QPointF, radius: float):
        """Draw the outer rotating ring with segments."""
        ring_width = self._ring_widths[0]
        ring_radius = radius - ring_width / 2
        
        # Create segmented ring
        pen = QPen(self._primary_color)
        pen.setWidth(ring_width)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        
        # Draw arc segments with rotation
        rect = QRectF(
            center.x() - ring_radius,
            center.y() - ring_radius,
            ring_radius * 2,
            ring_radius * 2,
        )
        
        # 8 segments with gaps
        segment_angle = 35
        gap_angle = 10
        for i in range(8):
            start_angle = int((i * 45 + self._rotation_angle) * 16)
            painter.drawArc(rect, start_angle, int(segment_angle * 16))
    
    def _draw_middle_rings(self, painter: QPainter, center: QPointF, radius: float):
        """Draw middle concentric rings."""
        current_radius = radius - self._ring_widths[0] - self._ring_gaps[0]
        
        for i, (width, gap) in enumerate(zip(self._ring_widths[1:3], self._ring_gaps[1:])):
            ring_radius = current_radius - width / 2
            
            # Alternate between primary and secondary colors
            color = self._primary_color if i % 2 == 0 else self._secondary_color
            
            # Apply pulse effect
            alpha = int(150 + 105 * self._pulse_value) if i == 0 else int(100 + 155 * self._pulse_value)
            color = QColor(color)
            color.setAlpha(alpha)
            
            pen = QPen(color)
            pen.setWidth(width)
            painter.setPen(pen)
            painter.drawEllipse(center, ring_radius, ring_radius)
            
            current_radius -= width + gap
    
    def _draw_inner_core(self, painter: QPainter, center: QPointF, radius: float):
        """Draw the inner glowing core."""
        # Calculate core radius
        core_radius = radius * 0.25
        
        # Gradient for core glow
        gradient = QRadialGradient(center, core_radius * 1.5)
        
        # Core color with pulse
        core_alpha = int(200 + 55 * self._pulse_value)
        core_color = QColor(self._core_color)
        core_color.setAlpha(core_alpha)
        
        primary_glow = QColor(self._primary_color)
        primary_glow.setAlpha(int(150 * self._glow_intensity))
        
        gradient.setColorAt(0.0, core_color)
        gradient.setColorAt(0.5, primary_glow)
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, core_radius * 1.5, core_radius * 1.5)
        
        # Solid core center
        painter.setBrush(core_color)
        painter.drawEllipse(center, core_radius * 0.5, core_radius * 0.5)
    
    def _draw_center_text(self, painter: QPainter, center: QPointF):
        """Draw text in the center if set."""
        if not self._text:
            return
        
        painter.setPen(QColor(self.theme.text))
        font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(font)
        
        # Center the text
        text_rect = painter.fontMetrics().boundingRect(self._text)
        text_x = center.x() - text_rect.width() / 2
        text_y = center.y() + text_rect.height() / 4
        
        painter.drawText(QPointF(text_x, text_y), self._text)
    
    # ─────────────────────────────────────────────────────────────────
    # Events
    # ─────────────────────────────────────────────────────────────────
    
    def mousePressEvent(self, event):
        """Handle mouse click."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        """Handle mouse enter."""
        self._glow_intensity = min(1.0, self._glow_intensity + 0.2)
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Handle mouse leave."""
        super().leaveEvent(event)
    
    def showEvent(self, event):
        """Start animations when shown."""
        self._start_animations()
        super().showEvent(event)
    
    def hideEvent(self, event):
        """Stop animations when hidden."""
        self._stop_animations()
        super().hideEvent(event)


class MiniArcReactor(ArcReactorWidget):
    """Smaller version of arc reactor for status indicators."""
    
    def __init__(
        self,
        size: int = 40,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(size, theme, parent)
        
        # Simplified ring configuration for small size
        self._ring_widths = [2, 3, 4, 6]
        self._ring_gaps = [3, 4, 5]
    
    def _draw_center_text(self, painter: QPainter, center: QPointF):
        """Skip text for mini reactor."""
        pass
