"""Mini Preview Window for live action visualization (Issue #7).

Provides a small, always-on-top window showing:
- Target application/window preview
- Specific region capture
- Cursor position overlay
- Element highlighting
- Smooth 30fps updates with low CPU usage
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple, List, Dict, Callable, Any

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QSizePolicy, QApplication, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QPropertyAnimation,
    QEasingCurve, pyqtSignal, QObject
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QPen, QBrush, QColor, QImage,
    QPainterPath, QFont, QLinearGradient, QRadialGradient
)

# Try to import screen capture libraries
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class PreviewMode(Enum):
    """Preview display modes."""
    WINDOW = auto()      # Capture specific window
    REGION = auto()      # Capture screen region
    FULLSCREEN = auto()  # Capture full screen
    ELEMENT = auto()     # Focus on specific element


@dataclass
class CaptureTarget:
    """Defines what to capture for preview."""
    mode: PreviewMode = PreviewMode.FULLSCREEN
    window_id: Optional[str] = None
    window_title: Optional[str] = None
    capture_region: Optional[Tuple[int, int, int, int]] = None  # x, y, width, height
    monitor: int = 0
    
    @classmethod
    def fullscreen(cls, monitor: int = 0) -> "CaptureTarget":
        """Capture full screen."""
        return cls(mode=PreviewMode.FULLSCREEN, monitor=monitor)
    
    @classmethod
    def window(cls, window_id: str = None, title: str = None) -> "CaptureTarget":
        """Capture specific window."""
        return cls(mode=PreviewMode.WINDOW, window_id=window_id, window_title=title)
    
    @classmethod
    def region(cls, x: int, y: int, width: int, height: int) -> "CaptureTarget":
        """Capture screen region."""
        return cls(mode=PreviewMode.REGION, capture_region=(x, y, width, height))


@dataclass
class HighlightRect:
    """Rectangle to highlight on preview."""
    x: int
    y: int
    width: int
    height: int
    color: str = "#00FF00"
    line_width: int = 3
    label: Optional[str] = None
    pulse: bool = False
    opacity: float = 1.0


@dataclass
class CursorOverlay:
    """Cursor position overlay on preview."""
    x: int
    y: int
    visible: bool = True
    clicking: bool = False
    color: str = "#FF0000"
    size: int = 16
    trail: List[Tuple[int, int]] = field(default_factory=list)
    show_trail: bool = False


class PreviewSignals(QObject):
    """Thread-safe signals for preview updates."""
    update_requested = pyqtSignal()
    target_changed = pyqtSignal(object)  # CaptureTarget
    highlight_added = pyqtSignal(object)  # HighlightRect
    cursor_moved = pyqtSignal(int, int)
    capture_completed = pyqtSignal(object)  # QPixmap


class MiniPreviewWidget(QWidget):
    """Small window showing current action target.
    
    Features:
    - Configurable size (default 320x180)
    - Multiple capture modes (window, region, fullscreen)
    - Highlight overlays for elements
    - Cursor position visualization
    - Mouse trail rendering
    - Smooth scaling with aspect ratio
    - Low CPU usage (<10%)
    - 30fps update rate
    """
    
    # Signals
    clicked = pyqtSignal(int, int)  # Preview clicked at position
    target_acquired = pyqtSignal(str)  # Window found
    capture_error = pyqtSignal(str)  # Capture failed
    
    # Default size maintaining 16:9 aspect ratio
    DEFAULT_WIDTH = 320
    DEFAULT_HEIGHT = 180
    
    # Update rate (30 fps = ~33ms)
    UPDATE_INTERVAL_MS = 33
    
    def __init__(
        self,
        size: Tuple[int, int] = None,
        parent: QWidget = None,
        always_on_top: bool = True,
        frameless: bool = True
    ):
        super().__init__(parent)
        
        # Size
        self._width = size[0] if size else self.DEFAULT_WIDTH
        self._height = size[1] if size else self.DEFAULT_HEIGHT
        
        # State
        self._target = CaptureTarget.fullscreen()
        self._current_frame: Optional[QPixmap] = None
        self._highlights: List[HighlightRect] = []
        self._cursor = CursorOverlay(0, 0, visible=False)
        self._is_capturing = False
        self._fps_counter = 0
        self._fps_timestamp = time.time()
        self._current_fps = 0.0
        self._scale_factor = 1.0
        self._original_size: Optional[Tuple[int, int]] = None
        
        # Dragging
        self._dragging = False
        self._drag_offset = QPoint()
        
        # Signals for thread safety
        self._signals = PreviewSignals()
        self._signals.update_requested.connect(self._do_capture)
        
        # Setup UI
        self._setup_ui(always_on_top, frameless)
        
        # Update timer (30fps)
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._on_timer)
        
        # Pulse animation timer for highlights
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._update_pulse)
        self._pulse_phase = 0.0
        
        # Screen capture (mss)
        self._sct = None
        if HAS_MSS:
            try:
                self._sct = mss.mss()
            except Exception:
                pass
    
    def _setup_ui(self, always_on_top: bool, frameless: bool):
        """Setup the widget UI."""
        # Window flags
        flags = Qt.WindowType.Tool
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if frameless:
            flags |= Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        
        # Size
        self.setFixedSize(self._width, self._height)
        
        # Style
        self.setStyleSheet("""
            MiniPreviewWidget {
                background-color: #0A0A1A;
                border: 2px solid #00D4FF;
                border-radius: 8px;
            }
        """)
        
        # Drop shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 212, 255, 100))
        shadow.setOffset(0, 0)
        self.setGraphicsEffect(shadow)
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        
        # Header with title
        self._header = QLabel("PREVIEW")
        self._header.setStyleSheet("""
            QLabel {
                color: #00D4FF;
                font-size: 10px;
                font-weight: bold;
                font-family: 'Consolas', 'Monaco', monospace;
                padding: 2px 4px;
                background: transparent;
            }
        """)
        self._header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._header)
        
        # Preview area (custom paint)
        self._preview_area = QFrame()
        self._preview_area.setStyleSheet("""
            QFrame {
                background-color: #000000;
                border: 1px solid #333333;
                border-radius: 4px;
            }
        """)
        self._preview_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._preview_area)
        
        # Footer with FPS and status
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(4, 2, 4, 2)
        
        self._status_label = QLabel("IDLE")
        self._status_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 9px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        footer_layout.addWidget(self._status_label)
        
        footer_layout.addStretch()
        
        self._fps_label = QLabel("0 FPS")
        self._fps_label.setStyleSheet("""
            QLabel {
                color: #00FF88;
                font-size: 9px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        footer_layout.addWidget(self._fps_label)
        
        layout.addLayout(footer_layout)
    
    # === Public API ===
    
    def set_target_window(self, window_id: str = None, title: str = None):
        """Set which window to preview.
        
        Args:
            window_id: Window ID to capture
            title: Window title to find
        """
        self._target = CaptureTarget.window(window_id, title)
        self._update_header()
    
    def set_target_region(self, x: int, y: int, w: int, h: int):
        """Set specific region to preview.
        
        Args:
            x, y: Top-left corner
            w, h: Width and height
        """
        self._target = CaptureTarget.region(x, y, w, h)
        self._original_size = (w, h)
        self._calculate_scale()
        self._update_header()
    
    def set_target_fullscreen(self, monitor: int = 0):
        """Set to capture full screen.
        
        Args:
            monitor: Monitor index (0 = primary)
        """
        self._target = CaptureTarget.fullscreen(monitor)
        self._update_header()
    
    def highlight_element(
        self,
        x: int, y: int, width: int, height: int,
        color: str = "#00FF00",
        label: str = None,
        pulse: bool = False
    ):
        """Draw highlight box on preview.
        
        Args:
            x, y: Position in original coordinates
            width, height: Size in original coordinates
            color: Highlight color
            label: Optional label text
            pulse: Whether to pulse/animate
        """
        rect = HighlightRect(
            x=x, y=y, width=width, height=height,
            color=color, label=label, pulse=pulse
        )
        self._highlights.append(rect)
        
        if pulse and not self._pulse_timer.isActive():
            self._pulse_timer.start(50)  # 20fps pulse
        
        self.update()
    
    def clear_highlights(self):
        """Remove all highlights."""
        self._highlights.clear()
        if self._pulse_timer.isActive():
            self._pulse_timer.stop()
        self.update()
    
    def show_cursor(self, x: int, y: int, clicking: bool = False):
        """Show cursor position on preview.
        
        Args:
            x, y: Cursor position in original coordinates
            clicking: Whether mouse is clicking
        """
        # Add to trail
        if self._cursor.show_trail:
            self._cursor.trail.append((x, y))
            # Keep last 50 points
            if len(self._cursor.trail) > 50:
                self._cursor.trail = self._cursor.trail[-50:]
        
        self._cursor.x = x
        self._cursor.y = y
        self._cursor.visible = True
        self._cursor.clicking = clicking
        self.update()
    
    def hide_cursor(self):
        """Hide cursor overlay."""
        self._cursor.visible = False
        self._cursor.trail.clear()
        self.update()
    
    def set_cursor_trail(self, enabled: bool):
        """Enable/disable cursor trail."""
        self._cursor.show_trail = enabled
        if not enabled:
            self._cursor.trail.clear()
    
    def start(self):
        """Start preview capture at 30fps."""
        if not self._is_capturing:
            self._is_capturing = True
            self._status_label.setText("LIVE")
            self._status_label.setStyleSheet("""
                QLabel {
                    color: #00FF88;
                    font-size: 9px;
                    font-family: 'Consolas', 'Monaco', monospace;
                }
            """)
            self._update_timer.start(self.UPDATE_INTERVAL_MS)
    
    def stop(self):
        """Stop preview capture."""
        if self._is_capturing:
            self._is_capturing = False
            self._status_label.setText("PAUSED")
            self._status_label.setStyleSheet("""
                QLabel {
                    color: #FFB800;
                    font-size: 9px;
                    font-family: 'Consolas', 'Monaco', monospace;
                }
            """)
            self._update_timer.stop()
    
    def capture_once(self) -> Optional[QPixmap]:
        """Capture a single frame and return it."""
        self._do_capture()
        return self._current_frame
    
    def get_current_frame(self) -> Optional[QPixmap]:
        """Get the current frame."""
        return self._current_frame
    
    def set_size(self, width: int, height: int):
        """Change preview size."""
        self._width = width
        self._height = height
        self.setFixedSize(width, height)
        self._calculate_scale()
    
    @property
    def current_fps(self) -> float:
        """Get current FPS."""
        return self._current_fps
    
    @property
    def is_capturing(self) -> bool:
        """Check if capturing is active."""
        return self._is_capturing
    
    # === Internal Methods ===
    
    def _update_header(self):
        """Update header text based on target."""
        mode_text = {
            PreviewMode.WINDOW: f"WINDOW: {self._target.window_title or self._target.window_id or 'Unknown'}",
            PreviewMode.REGION: "REGION CAPTURE",
            PreviewMode.FULLSCREEN: f"SCREEN {self._target.monitor}",
            PreviewMode.ELEMENT: "ELEMENT FOCUS",
        }
        self._header.setText(mode_text.get(self._target.mode, "PREVIEW"))
    
    def _calculate_scale(self):
        """Calculate scale factor for coordinate mapping."""
        if self._original_size:
            preview_rect = self._preview_area.rect()
            self._scale_factor = min(
                preview_rect.width() / self._original_size[0],
                preview_rect.height() / self._original_size[1]
            )
    
    def _on_timer(self):
        """Timer callback for updates."""
        self._signals.update_requested.emit()
    
    def _do_capture(self):
        """Perform screen capture."""
        if not HAS_MSS or not self._sct:
            self._draw_no_capture_message()
            return
        
        try:
            # Determine capture region
            if self._target.mode == PreviewMode.REGION and self._target.capture_region:
                x, y, w, h = self._target.capture_region
                region = {"left": x, "top": y, "width": w, "height": h}
            elif self._target.mode == PreviewMode.FULLSCREEN:
                monitor = self._sct.monitors[self._target.monitor + 1]  # 0 is "all"
                region = monitor
                self._original_size = (monitor["width"], monitor["height"])
            else:
                # Default to primary monitor
                monitor = self._sct.monitors[1]
                region = monitor
                self._original_size = (monitor["width"], monitor["height"])
            
            # Capture
            screenshot = self._sct.grab(region)
            
            # Convert to QPixmap
            img = QImage(
                screenshot.raw,
                screenshot.width,
                screenshot.height,
                QImage.Format.Format_BGRA8888
            )
            self._current_frame = QPixmap.fromImage(img)
            
            # Calculate scale
            self._calculate_scale()
            
            # Update FPS counter
            self._fps_counter += 1
            now = time.time()
            if now - self._fps_timestamp >= 1.0:
                self._current_fps = self._fps_counter / (now - self._fps_timestamp)
                self._fps_label.setText(f"{self._current_fps:.1f} FPS")
                self._fps_counter = 0
                self._fps_timestamp = now
            
            # Trigger repaint
            self.update()
            
            # Emit signal
            self._signals.capture_completed.emit(self._current_frame)
            
        except Exception as e:
            self.capture_error.emit(str(e))
            self._draw_error_message(str(e))
    
    def _draw_no_capture_message(self):
        """Draw message when capture is not available."""
        pixmap = QPixmap(self._width - 10, self._height - 50)
        pixmap.fill(QColor("#0A0A1A"))
        
        painter = QPainter(pixmap)
        painter.setPen(QColor("#666666"))
        painter.setFont(QFont("Consolas", 10))
        painter.drawText(
            pixmap.rect(),
            Qt.AlignmentFlag.AlignCenter,
            "Screen capture not available\nInstall: pip install mss"
        )
        painter.end()
        
        self._current_frame = pixmap
        self.update()
    
    def _draw_error_message(self, error: str):
        """Draw error message."""
        pixmap = QPixmap(self._width - 10, self._height - 50)
        pixmap.fill(QColor("#1A0A0A"))
        
        painter = QPainter(pixmap)
        painter.setPen(QColor("#FF4444"))
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(
            pixmap.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"Capture Error:\n{error[:50]}"
        )
        painter.end()
        
        self._current_frame = pixmap
        self.update()
    
    def _update_pulse(self):
        """Update pulse animation phase."""
        self._pulse_phase += 0.1
        if self._pulse_phase >= 6.28:  # 2*pi
            self._pulse_phase = 0
        self.update()
    
    def _scale_rect(self, rect: HighlightRect) -> QRect:
        """Scale a highlight rect to preview coordinates."""
        preview_rect = self._preview_area.rect()
        
        if not self._original_size:
            return QRect(rect.x, rect.y, rect.width, rect.height)
        
        # Calculate offset for centering
        scaled_w = self._original_size[0] * self._scale_factor
        scaled_h = self._original_size[1] * self._scale_factor
        offset_x = (preview_rect.width() - scaled_w) / 2 + self._preview_area.x()
        offset_y = (preview_rect.height() - scaled_h) / 2 + self._preview_area.y() + 20  # Header offset
        
        return QRect(
            int(rect.x * self._scale_factor + offset_x),
            int(rect.y * self._scale_factor + offset_y),
            int(rect.width * self._scale_factor),
            int(rect.height * self._scale_factor)
        )
    
    def _scale_point(self, x: int, y: int) -> Tuple[int, int]:
        """Scale a point to preview coordinates."""
        preview_rect = self._preview_area.rect()
        
        if not self._original_size:
            return x, y
        
        scaled_w = self._original_size[0] * self._scale_factor
        scaled_h = self._original_size[1] * self._scale_factor
        offset_x = (preview_rect.width() - scaled_w) / 2 + self._preview_area.x()
        offset_y = (preview_rect.height() - scaled_h) / 2 + self._preview_area.y() + 20
        
        return (
            int(x * self._scale_factor + offset_x),
            int(y * self._scale_factor + offset_y)
        )
    
    # === Events ===
    
    def paintEvent(self, event):
        """Custom paint for preview."""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw current frame in preview area
        if self._current_frame and not self._current_frame.isNull():
            preview_rect = self._preview_area.geometry()
            
            # Scale frame to fit preview area
            scaled = self._current_frame.scaled(
                preview_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            # Center in preview area
            x = preview_rect.x() + (preview_rect.width() - scaled.width()) // 2
            y = preview_rect.y() + (preview_rect.height() - scaled.height()) // 2
            
            painter.drawPixmap(x, y, scaled)
        
        # Draw highlights
        for highlight in self._highlights:
            rect = self._scale_rect(highlight)
            color = QColor(highlight.color)
            
            # Pulse effect
            if highlight.pulse:
                import math
                pulse_opacity = 0.5 + 0.5 * math.sin(self._pulse_phase)
                color.setAlphaF(pulse_opacity)
            
            # Draw box
            pen = QPen(color, highlight.line_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            
            # Draw label
            if highlight.label:
                painter.setFont(QFont("Consolas", 8))
                label_rect = rect.adjusted(0, -15, 0, 0)
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft, highlight.label)
        
        # Draw cursor trail
        if self._cursor.show_trail and self._cursor.trail:
            trail_color = QColor(self._cursor.color)
            for i, (tx, ty) in enumerate(self._cursor.trail):
                opacity = (i + 1) / len(self._cursor.trail) * 0.5
                trail_color.setAlphaF(opacity)
                sx, sy = self._scale_point(tx, ty)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(trail_color)
                painter.drawEllipse(QPoint(sx, sy), 3, 3)
        
        # Draw cursor
        if self._cursor.visible:
            sx, sy = self._scale_point(self._cursor.x, self._cursor.y)
            cursor_color = QColor(self._cursor.color)
            
            # Click ripple effect
            if self._cursor.clicking:
                ripple_color = QColor(cursor_color)
                ripple_color.setAlphaF(0.3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ripple_color)
                painter.drawEllipse(QPoint(sx, sy), 20, 20)
            
            # Cursor dot
            painter.setPen(QPen(cursor_color, 2))
            painter.setBrush(cursor_color)
            painter.drawEllipse(QPoint(sx, sy), self._cursor.size // 2, self._cursor.size // 2)
            
            # Crosshair
            painter.setPen(QPen(cursor_color, 1))
            painter.drawLine(sx - 10, sy, sx + 10, sy)
            painter.drawLine(sx, sy - 10, sx, sy + 10)
        
        painter.end()
    
    def mousePressEvent(self, event):
        """Handle mouse press for dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.pos()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging."""
        if self._dragging:
            self.move(self.mapToParent(event.pos() - self._drag_offset))
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            
            # Check if clicked on preview area
            if self._preview_area.geometry().contains(event.pos()):
                # Convert to original coordinates
                preview_rect = self._preview_area.geometry()
                rel_x = event.pos().x() - preview_rect.x()
                rel_y = event.pos().y() - preview_rect.y()
                
                if self._scale_factor > 0:
                    orig_x = int(rel_x / self._scale_factor)
                    orig_y = int(rel_y / self._scale_factor)
                    self.clicked.emit(orig_x, orig_y)
    
    def closeEvent(self, event):
        """Cleanup on close."""
        self.stop()
        if self._sct:
            self._sct.close()
        super().closeEvent(event)


class CompactPreview(MiniPreviewWidget):
    """Even smaller preview widget (160x90)."""
    
    DEFAULT_WIDTH = 160
    DEFAULT_HEIGHT = 90
    UPDATE_INTERVAL_MS = 50  # 20fps for compact
    
    def __init__(self, parent: QWidget = None):
        super().__init__(
            size=(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT),
            parent=parent
        )
        # Simpler header
        self._header.hide()
        self._fps_label.hide()


def create_mini_preview(
    width: int = 320,
    height: int = 180,
    always_on_top: bool = True,
    frameless: bool = True
) -> MiniPreviewWidget:
    """Factory function to create a MiniPreviewWidget.
    
    Args:
        width: Preview width (default 320)
        height: Preview height (default 180)
        always_on_top: Keep window on top
        frameless: Remove window frame
    
    Returns:
        MiniPreviewWidget instance
    """
    return MiniPreviewWidget(
        size=(width, height),
        always_on_top=always_on_top,
        frameless=frameless
    )
