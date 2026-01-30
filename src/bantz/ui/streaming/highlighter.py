"""Action Highlighter for visual feedback (Issue #7).

Provides visual feedback for user actions:
- Highlight boxes around click targets
- Click ripple animations
- Mouse movement trails
- Animated transitions
- Multiple highlight styles
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Tuple, Dict, Callable

from PyQt5.QtWidgets import (
    QWidget, QApplication, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QPropertyAnimation,
    QEasingCurve, pyqtSignal, QSequentialAnimationGroup,
    QParallelAnimationGroup, QObject
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QPen, QBrush, QColor, QImage,
    QPainterPath, QFont, QLinearGradient, QRadialGradient,
    QPaintEvent, QRegion
)


class HighlightStyle(Enum):
    """Visual styles for highlights."""
    SOLID = auto()       # Solid color border
    DASHED = auto()      # Dashed border
    GLOW = auto()        # Glowing effect
    PULSE = auto()       # Pulsing animation
    CORNER_BRACKETS = auto()  # Only corners highlighted
    SCANNING = auto()    # Scanning line animation


@dataclass
class HighlightBox:
    """A highlight box configuration."""
    x: int
    y: int
    width: int
    height: int
    color: str = "#00FF00"
    style: HighlightStyle = HighlightStyle.SOLID
    line_width: int = 3
    corner_length: int = 20
    label: Optional[str] = None
    label_position: str = "top"  # top, bottom, left, right
    duration: float = 2.0  # seconds, 0 = permanent
    opacity: float = 1.0
    
    # Animation state
    _start_time: float = field(default_factory=time.time)
    _phase: float = 0.0
    
    @property
    def is_expired(self) -> bool:
        """Check if highlight has expired."""
        if self.duration <= 0:
            return False
        return time.time() - self._start_time >= self.duration
    
    @property
    def remaining_opacity(self) -> float:
        """Get opacity based on time remaining."""
        if self.duration <= 0:
            return self.opacity
        elapsed = time.time() - self._start_time
        if elapsed >= self.duration:
            return 0.0
        # Fade out in last 0.5 seconds
        if elapsed >= self.duration - 0.5:
            fade_progress = (self.duration - elapsed) / 0.5
            return self.opacity * fade_progress
        return self.opacity


@dataclass
class ClickRipple:
    """A click ripple animation."""
    x: int
    y: int
    color: str = "#00FF00"
    max_radius: int = 50
    duration: float = 0.6
    rings: int = 3
    
    # Animation state
    _start_time: float = field(default_factory=time.time)
    
    @property
    def progress(self) -> float:
        """Get animation progress (0.0 to 1.0)."""
        elapsed = time.time() - self._start_time
        return min(1.0, elapsed / self.duration)
    
    @property
    def is_complete(self) -> bool:
        """Check if animation is complete."""
        return self.progress >= 1.0
    
    def get_ring_states(self) -> List[Tuple[float, float]]:
        """Get (radius, opacity) for each ring."""
        states = []
        for i in range(self.rings):
            # Stagger ring start times
            ring_delay = i * 0.1
            ring_progress = max(0, (self.progress - ring_delay) / (1 - ring_delay * self.rings))
            
            if ring_progress > 0:
                radius = ring_progress * self.max_radius
                opacity = 1.0 - ring_progress
                states.append((radius, opacity))
        return states


@dataclass
class MouseTrail:
    """Mouse movement trail."""
    points: List[Tuple[int, int]] = field(default_factory=list)
    timestamps: List[float] = field(default_factory=list)
    color: str = "#00D4FF"
    max_points: int = 100
    trail_duration: float = 1.0  # How long points stay visible
    line_width: int = 2
    gradient: bool = True
    glow: bool = True
    
    def add_point(self, x: int, y: int):
        """Add a point to the trail."""
        self.points.append((x, y))
        self.timestamps.append(time.time())
        
        # Remove old points
        self._cleanup()
    
    def _cleanup(self):
        """Remove expired points."""
        now = time.time()
        cutoff = now - self.trail_duration
        
        # Find first valid point
        valid_start = 0
        for i, ts in enumerate(self.timestamps):
            if ts >= cutoff:
                valid_start = i
                break
        
        if valid_start > 0:
            self.points = self.points[valid_start:]
            self.timestamps = self.timestamps[valid_start:]
        
        # Also limit by max_points
        if len(self.points) > self.max_points:
            self.points = self.points[-self.max_points:]
            self.timestamps = self.timestamps[-self.max_points:]
    
    def get_visible_points(self) -> List[Tuple[Tuple[int, int], float]]:
        """Get points with their opacity values."""
        self._cleanup()
        now = time.time()
        result = []
        
        for point, ts in zip(self.points, self.timestamps):
            age = now - ts
            opacity = max(0, 1.0 - age / self.trail_duration)
            result.append((point, opacity))
        
        return result
    
    def clear(self):
        """Clear all points."""
        self.points.clear()
        self.timestamps.clear()


class TransparentOverlay(QWidget):
    """Transparent overlay window for drawing highlights.
    
    This creates a full-screen transparent window that sits
    on top of all other windows for drawing visual feedback.
    """
    
    def __init__(self, screen_index: int = 0):
        super().__init__()
        
        # Get screen geometry
        screens = QApplication.screens()
        if screen_index < len(screens):
            screen = screens[screen_index]
            geometry = screen.geometry()
        else:
            geometry = QApplication.primaryScreen().geometry()
        
        # Window flags for transparent overlay
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        
        # Transparent background
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        # Cover the screen
        self.setGeometry(geometry)
        
        # Drawing state
        self._highlights: List[HighlightBox] = []
        self._ripples: List[ClickRipple] = []
        self._trail = MouseTrail()
        self._enabled = True
        
        # Animation timer
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._on_animation_tick)
        self._animation_interval = 16  # ~60fps
        
        # Phase for animations
        self._phase = 0.0
    
    def start_animations(self):
        """Start the animation timer."""
        if not self._animation_timer.isActive():
            self._animation_timer.start(self._animation_interval)
    
    def stop_animations(self):
        """Stop the animation timer."""
        self._animation_timer.stop()
    
    def _on_animation_tick(self):
        """Handle animation frame."""
        self._phase += 0.1
        if self._phase >= 2 * math.pi:
            self._phase = 0
        
        # Update highlight phases
        for highlight in self._highlights:
            highlight._phase = self._phase
        
        # Remove expired items
        self._highlights = [h for h in self._highlights if not h.is_expired]
        self._ripples = [r for r in self._ripples if not r.is_complete]
        
        # Stop timer if nothing to animate
        if not self._highlights and not self._ripples and not self._trail.points:
            self.stop_animations()
        
        self.update()
    
    def add_highlight(self, highlight: HighlightBox):
        """Add a highlight box."""
        highlight._start_time = time.time()
        self._highlights.append(highlight)
        self.start_animations()
        self.update()
    
    def add_ripple(self, ripple: ClickRipple):
        """Add a click ripple."""
        ripple._start_time = time.time()
        self._ripples.append(ripple)
        self.start_animations()
        self.update()
    
    def update_trail(self, x: int, y: int):
        """Add point to mouse trail."""
        self._trail.add_point(x, y)
        self.start_animations()
        self.update()
    
    def clear_trail(self):
        """Clear the mouse trail."""
        self._trail.clear()
        self.update()
    
    def clear_all(self):
        """Clear all overlays."""
        self._highlights.clear()
        self._ripples.clear()
        self._trail.clear()
        self.update()
    
    def paintEvent(self, event: QPaintEvent):
        """Draw all overlays."""
        if not self._enabled:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw trail first (behind everything)
        self._draw_trail(painter)
        
        # Draw highlights
        for highlight in self._highlights:
            self._draw_highlight(painter, highlight)
        
        # Draw ripples on top
        for ripple in self._ripples:
            self._draw_ripple(painter, ripple)
        
        painter.end()
    
    def _draw_highlight(self, painter: QPainter, h: HighlightBox):
        """Draw a single highlight box."""
        color = QColor(h.color)
        color.setAlphaF(h.remaining_opacity)
        
        rect = QRect(h.x, h.y, h.width, h.height)
        
        if h.style == HighlightStyle.SOLID:
            pen = QPen(color, h.line_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            
        elif h.style == HighlightStyle.DASHED:
            pen = QPen(color, h.line_width, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            
        elif h.style == HighlightStyle.GLOW:
            # Multiple layers for glow effect
            for i in range(5):
                glow_color = QColor(color)
                glow_color.setAlphaF(color.alphaF() * (0.2 - i * 0.04))
                pen = QPen(glow_color, h.line_width + i * 4)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
            # Core line
            pen = QPen(color, h.line_width)
            painter.setPen(pen)
            painter.drawRect(rect)
            
        elif h.style == HighlightStyle.PULSE:
            # Pulsing opacity
            pulse = 0.5 + 0.5 * math.sin(h._phase)
            pulse_color = QColor(color)
            pulse_color.setAlphaF(color.alphaF() * pulse)
            pen = QPen(pulse_color, h.line_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            
        elif h.style == HighlightStyle.CORNER_BRACKETS:
            # Only draw corners
            pen = QPen(color, h.line_width)
            painter.setPen(pen)
            
            cl = h.corner_length
            # Top-left
            painter.drawLine(h.x, h.y, h.x + cl, h.y)
            painter.drawLine(h.x, h.y, h.x, h.y + cl)
            # Top-right
            painter.drawLine(h.x + h.width - cl, h.y, h.x + h.width, h.y)
            painter.drawLine(h.x + h.width, h.y, h.x + h.width, h.y + cl)
            # Bottom-left
            painter.drawLine(h.x, h.y + h.height - cl, h.x, h.y + h.height)
            painter.drawLine(h.x, h.y + h.height, h.x + cl, h.y + h.height)
            # Bottom-right
            painter.drawLine(h.x + h.width - cl, h.y + h.height, h.x + h.width, h.y + h.height)
            painter.drawLine(h.x + h.width, h.y + h.height - cl, h.x + h.width, h.y + h.height)
            
        elif h.style == HighlightStyle.SCANNING:
            # Draw box
            pen = QPen(color, h.line_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            
            # Scanning line
            scan_y = h.y + int((h._phase / (2 * math.pi)) * h.height)
            scan_color = QColor(color)
            scan_color.setAlphaF(0.8)
            gradient = QLinearGradient(h.x, scan_y - 10, h.x, scan_y + 10)
            gradient.setColorAt(0, QColor(0, 0, 0, 0))
            gradient.setColorAt(0.5, scan_color)
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(h.x, scan_y - 10, h.width, 20, gradient)
        
        # Draw label if present
        if h.label:
            self._draw_label(painter, h, rect, color)
    
    def _draw_label(self, painter: QPainter, h: HighlightBox, rect: QRect, color: QColor):
        """Draw highlight label."""
        font = QFont("Consolas", 10, QFont.Weight.Bold)
        painter.setFont(font)
        
        # Background for label
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(h.label) + 10
        text_height = fm.height() + 4
        
        if h.label_position == "top":
            label_rect = QRect(rect.x(), rect.y() - text_height - 2, text_width, text_height)
        elif h.label_position == "bottom":
            label_rect = QRect(rect.x(), rect.bottom() + 2, text_width, text_height)
        elif h.label_position == "left":
            label_rect = QRect(rect.x() - text_width - 2, rect.y(), text_width, text_height)
        else:  # right
            label_rect = QRect(rect.right() + 2, rect.y(), text_width, text_height)
        
        # Draw background
        bg_color = QColor(color)
        bg_color.setAlphaF(0.8)
        painter.fillRect(label_rect, bg_color)
        
        # Draw text
        text_color = QColor("#000000") if color.lightness() > 128 else QColor("#FFFFFF")
        painter.setPen(text_color)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, h.label)
    
    def _draw_ripple(self, painter: QPainter, r: ClickRipple):
        """Draw a click ripple animation."""
        color = QColor(r.color)
        center = QPoint(r.x, r.y)
        
        for radius, opacity in r.get_ring_states():
            ring_color = QColor(color)
            ring_color.setAlphaF(opacity * 0.6)
            
            pen = QPen(ring_color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, int(radius), int(radius))
        
        # Center dot
        if r.progress < 0.3:
            dot_opacity = 1.0 - r.progress / 0.3
            dot_color = QColor(color)
            dot_color.setAlphaF(dot_opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_color)
            painter.drawEllipse(center, 5, 5)
    
    def _draw_trail(self, painter: QPainter):
        """Draw the mouse trail."""
        points = self._trail.get_visible_points()
        if len(points) < 2:
            return
        
        color = QColor(self._trail.color)
        
        # Draw glow layer
        if self._trail.glow:
            for i in range(len(points) - 1):
                (x1, y1), op1 = points[i]
                (x2, y2), op2 = points[i + 1]
                
                avg_opacity = (op1 + op2) / 2 * 0.3
                glow_color = QColor(color)
                glow_color.setAlphaF(avg_opacity)
                
                pen = QPen(glow_color, self._trail.line_width + 6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(x1, y1, x2, y2)
        
        # Draw main line
        for i in range(len(points) - 1):
            (x1, y1), op1 = points[i]
            (x2, y2), op2 = points[i + 1]
            
            if self._trail.gradient:
                # Gradient between points
                avg_opacity = (op1 + op2) / 2
            else:
                avg_opacity = op2
            
            line_color = QColor(color)
            line_color.setAlphaF(avg_opacity)
            
            pen = QPen(line_color, self._trail.line_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(x1, y1, x2, y2)


class ActionHighlighter:
    """Highlight elements being interacted with.
    
    Provides high-level API for visual feedback:
    - Highlight click targets
    - Show click ripple effects
    - Draw mouse trails
    - Multiple visual styles
    """
    
    def __init__(self, screen_index: int = 0):
        """Initialize the highlighter.
        
        Args:
            screen_index: Which screen to overlay (0 = primary)
        """
        self._overlay = TransparentOverlay(screen_index)
        self._default_color = "#00FF00"
        self._default_style = HighlightStyle.CORNER_BRACKETS
        self._trail_enabled = False
    
    def show(self):
        """Show the overlay."""
        self._overlay.show()
    
    def hide(self):
        """Hide the overlay."""
        self._overlay.hide()
    
    def highlight_click_target(
        self,
        x: int, y: int, w: int, h: int,
        color: str = None,
        style: HighlightStyle = None,
        duration: float = 2.0,
        label: str = None
    ):
        """Show highlight box around click target.
        
        Args:
            x, y: Top-left corner position
            w, h: Width and height
            color: Highlight color (default green)
            style: Visual style
            duration: How long to show (0 = permanent)
            label: Optional label text
        """
        highlight = HighlightBox(
            x=x, y=y, width=w, height=h,
            color=color or self._default_color,
            style=style or self._default_style,
            duration=duration,
            label=label
        )
        self._overlay.add_highlight(highlight)
    
    def highlight_element(
        self,
        rect: Dict[str, int],
        color: str = None,
        label: str = None,
        duration: float = 2.0
    ):
        """Highlight element by rect dict.
        
        Args:
            rect: Dict with x, y, width, height keys
            color: Highlight color
            label: Optional label
            duration: Display duration
        """
        self.highlight_click_target(
            x=rect["x"], y=rect["y"],
            w=rect["width"], h=rect["height"],
            color=color, label=label, duration=duration
        )
    
    def show_click_ripple(
        self,
        x: int, y: int,
        color: str = None,
        rings: int = 3
    ):
        """Animate click ripple effect.
        
        Args:
            x, y: Click position
            color: Ripple color
            rings: Number of expanding rings
        """
        ripple = ClickRipple(
            x=x, y=y,
            color=color or self._default_color,
            rings=rings
        )
        self._overlay.add_ripple(ripple)
    
    def draw_mouse_trail(self, path: List[Tuple[int, int]]):
        """Draw mouse movement trail.
        
        Args:
            path: List of (x, y) positions
        """
        for x, y in path:
            self._overlay.update_trail(x, y)
    
    def update_trail_point(self, x: int, y: int):
        """Add single point to trail.
        
        Args:
            x, y: Current mouse position
        """
        if self._trail_enabled:
            self._overlay.update_trail(x, y)
    
    def enable_trail(self, enabled: bool = True, color: str = None):
        """Enable/disable mouse trail.
        
        Args:
            enabled: Whether to track trail
            color: Trail color
        """
        self._trail_enabled = enabled
        if color:
            self._overlay._trail.color = color
        if not enabled:
            self._overlay.clear_trail()
    
    def set_trail_duration(self, duration: float):
        """Set how long trail points stay visible.
        
        Args:
            duration: Duration in seconds
        """
        self._overlay._trail.trail_duration = duration
    
    def clear(self):
        """Clear all highlights."""
        self._overlay.clear_all()
    
    def set_default_color(self, color: str):
        """Set default highlight color.
        
        Args:
            color: Color in hex format (#RRGGBB)
        """
        self._default_color = color
    
    def set_default_style(self, style: HighlightStyle):
        """Set default highlight style.
        
        Args:
            style: HighlightStyle enum value
        """
        self._default_style = style
    
    @property
    def is_visible(self) -> bool:
        """Check if overlay is visible."""
        return self._overlay.isVisible()
    
    def close(self):
        """Close and cleanup."""
        self._overlay.close()


def create_highlighter(screen_index: int = 0) -> ActionHighlighter:
    """Factory function to create ActionHighlighter.
    
    Args:
        screen_index: Which screen (0 = primary)
    
    Returns:
        ActionHighlighter instance
    """
    return ActionHighlighter(screen_index)
