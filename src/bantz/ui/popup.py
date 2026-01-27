"""
Jarvis Panel Popup/Bubble System (Issue #63).

Provides popup panels for displaying additional information:
- Image popups with captions
- Text popups with titles
- Icon popups for status
- Mixed content popups

Features:
- Auto-dismiss with timeout
- Hover pause for timeout
- Click to dismiss
- Stack/queue for multiple popups
- Smooth animations (fade, slide, scale, bounce)
- Position relative to parent panel
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Union
from enum import Enum, auto
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QSizePolicy, QFrame
)
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QPoint, QEasingCurve, QParallelAnimationGroup,
    pyqtSignal, QObject, QSize, QRect, QTimer, QSequentialAnimationGroup,
    QVariantAnimation
)
from PyQt5.QtGui import (
    QColor, QFont, QPainter, QLinearGradient, QPen, QBrush,
    QPainterPath, QPixmap, QIcon
)

from .themes import OverlayTheme, JARVIS_THEME


# =============================================================================
# Enums
# =============================================================================


class PopupContentType(Enum):
    """Types of popup content."""
    IMAGE = "image"       # Image with optional caption
    TEXT = "text"         # Text with optional title
    ICON = "icon"         # Status icon with label
    MIXED = "mixed"       # Image + text combination
    CUSTOM = "custom"     # Custom widget


class PopupPosition(Enum):
    """Popup position relative to parent panel."""
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class PopupAnimation(Enum):
    """Popup animation types."""
    NONE = "none"
    FADE = "fade"
    SLIDE_LEFT = "slide_left"
    SLIDE_RIGHT = "slide_right"
    SLIDE_UP = "slide_up"
    SLIDE_DOWN = "slide_down"
    SCALE = "scale"
    BOUNCE = "bounce"


class PopupStatus(Enum):
    """Popup status for icon popups."""
    LOADING = "loading"
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# Turkish aliases for positions
POPUP_POSITION_ALIASES = {
    "sol üst": PopupPosition.TOP_LEFT,
    "sağ üst": PopupPosition.TOP_RIGHT,
    "sol alt": PopupPosition.BOTTOM_LEFT,
    "sağ alt": PopupPosition.BOTTOM_RIGHT,
    "sol": PopupPosition.LEFT,
    "sağ": PopupPosition.RIGHT,
    "üst": PopupPosition.TOP,
    "alt": PopupPosition.BOTTOM,
}


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class PopupColors:
    """Color palette for popups (matches Jarvis panel)."""
    background: QColor = field(default_factory=lambda: QColor(10, 25, 47, 220))
    border: QColor = field(default_factory=lambda: QColor(0, 195, 255, 180))
    text: QColor = field(default_factory=lambda: QColor(255, 255, 255, 230))
    accent: QColor = field(default_factory=lambda: QColor(0, 195, 255, 255))
    success: QColor = field(default_factory=lambda: QColor(0, 255, 136, 200))
    warning: QColor = field(default_factory=lambda: QColor(255, 193, 7, 200))
    error: QColor = field(default_factory=lambda: QColor(255, 68, 68, 200))
    info: QColor = field(default_factory=lambda: QColor(0, 195, 255, 200))
    
    @classmethod
    def from_theme(cls, theme: OverlayTheme) -> "PopupColors":
        """Create colors from OverlayTheme."""
        return cls(
            background=QColor(theme.background),
            border=QColor(theme.primary),
            text=QColor(theme.text),
            accent=QColor(theme.primary),
            success=QColor(theme.success),
            warning=QColor(theme.warning),
            error=QColor(theme.error),
        )


@dataclass
class PopupConfig:
    """Configuration for a popup panel."""
    content_type: PopupContentType = PopupContentType.TEXT
    position: PopupPosition = PopupPosition.TOP_RIGHT
    timeout: float = 5.0  # seconds, 0 = no auto-dismiss
    animation: PopupAnimation = PopupAnimation.FADE
    priority: int = 0  # higher priority = shown first
    pausable: bool = True  # pause timeout on hover
    dismissable: bool = True  # click to dismiss
    width: int = 250
    height: int = 0  # 0 = auto-height
    margin: int = 10  # margin from parent panel
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content_type": self.content_type.value,
            "position": self.position.value,
            "timeout": self.timeout,
            "animation": self.animation.value,
            "priority": self.priority,
            "pausable": self.pausable,
            "dismissable": self.dismissable,
            "width": self.width,
            "height": self.height,
            "margin": self.margin,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PopupConfig":
        """Create from dictionary."""
        return cls(
            content_type=PopupContentType(data.get("content_type", "text")),
            position=PopupPosition(data.get("position", "top_right")),
            timeout=data.get("timeout", 5.0),
            animation=PopupAnimation(data.get("animation", "fade")),
            priority=data.get("priority", 0),
            pausable=data.get("pausable", True),
            dismissable=data.get("dismissable", True),
            width=data.get("width", 250),
            height=data.get("height", 0),
            margin=data.get("margin", 10),
        )


# =============================================================================
# Animation Durations
# =============================================================================


class PopupAnimationConfig:
    """Animation timing configuration."""
    FADE_DURATION = 250
    SLIDE_DURATION = 300
    SCALE_DURATION = 250
    BOUNCE_DURATION = 400
    SLIDE_DISTANCE = 50


# =============================================================================
# Popup Panel Widget
# =============================================================================


class PopupPanel(QWidget):
    """
    A popup/bubble panel for displaying additional information.
    
    Signals:
        dismissed: Emitted when popup is dismissed
        clicked: Emitted when popup is clicked
        hovered: Emitted when mouse enters/leaves (bool)
    """
    
    dismissed = pyqtSignal()
    clicked = pyqtSignal()
    hovered = pyqtSignal(bool)
    
    def __init__(
        self,
        config: Optional[PopupConfig] = None,
        colors: Optional[PopupColors] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.config = config or PopupConfig()
        self.colors = colors or PopupColors()
        
        # State
        self._timeout_timer: Optional[QTimer] = None
        self._remaining_timeout: float = 0
        self._is_hovered = False
        self._is_dismissed = False
        self._animations: List[QPropertyAnimation] = []
        
        # Setup
        self._setup_window()
        self._setup_ui()
        self._setup_effects()
    
    def _setup_window(self) -> None:
        """Configure window flags and attributes."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # Size
        if self.config.width > 0:
            self.setFixedWidth(self.config.width)
        if self.config.height > 0:
            self.setFixedHeight(self.config.height)
        else:
            self.setMinimumHeight(60)
    
    def _setup_ui(self) -> None:
        """Setup the popup UI."""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(12, 10, 12, 10)
        self._main_layout.setSpacing(8)
        
        # Title label (optional)
        self._title_label = QLabel()
        self._title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {self.colors.accent.name()};")
        self._title_label.setWordWrap(True)
        self._title_label.hide()
        self._main_layout.addWidget(self._title_label)
        
        # Image label (optional)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.hide()
        self._main_layout.addWidget(self._image_label)
        
        # Icon label (optional)
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.hide()
        self._main_layout.addWidget(self._icon_label)
        
        # Text label
        self._text_label = QLabel()
        self._text_label.setFont(QFont("Segoe UI", 9))
        self._text_label.setStyleSheet(f"color: {self.colors.text.name()};")
        self._text_label.setWordWrap(True)
        self._text_label.hide()
        self._main_layout.addWidget(self._text_label)
        
        # Status label (for icon popups)
        self._status_label = QLabel()
        self._status_label.setFont(QFont("Segoe UI", 9))
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.hide()
        self._main_layout.addWidget(self._status_label)
    
    def _setup_effects(self) -> None:
        """Setup visual effects."""
        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(self.colors.accent)
        shadow.setOffset(0, 0)
        self.setGraphicsEffect(shadow)
    
    # =========================================================================
    # Content Methods
    # =========================================================================
    
    def show_image(
        self,
        image_path: str,
        caption: Optional[str] = None,
        max_width: int = 200,
        max_height: int = 150,
    ) -> None:
        """
        Show an image popup.
        
        Args:
            image_path: Path to image file
            caption: Optional caption text
            max_width: Maximum image width
            max_height: Maximum image height
        """
        self.config.content_type = PopupContentType.IMAGE
        
        # Load and scale image
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                max_width, max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._image_label.setPixmap(scaled)
            self._image_label.show()
        
        # Caption
        if caption:
            self._text_label.setText(caption)
            self._text_label.show()
        else:
            self._text_label.hide()
        
        self._title_label.hide()
        self._icon_label.hide()
        self._status_label.hide()
        
        self.adjustSize()
    
    def show_text(
        self,
        text: str,
        title: Optional[str] = None,
    ) -> None:
        """
        Show a text popup.
        
        Args:
            text: Main text content
            title: Optional title
        """
        self.config.content_type = PopupContentType.TEXT
        
        if title:
            self._title_label.setText(title)
            self._title_label.show()
        else:
            self._title_label.hide()
        
        self._text_label.setText(text)
        self._text_label.show()
        
        self._image_label.hide()
        self._icon_label.hide()
        self._status_label.hide()
        
        self.adjustSize()
    
    def show_icon(
        self,
        status: PopupStatus,
        message: Optional[str] = None,
        icon_size: int = 32,
    ) -> None:
        """
        Show an icon/status popup.
        
        Args:
            status: Status type
            message: Optional status message
            icon_size: Icon size in pixels
        """
        self.config.content_type = PopupContentType.ICON
        
        # Status icons (Unicode symbols)
        icons = {
            PopupStatus.LOADING: "⏳",
            PopupStatus.SUCCESS: "✓",
            PopupStatus.ERROR: "✗",
            PopupStatus.WARNING: "⚠",
            PopupStatus.INFO: "ℹ",
        }
        
        colors = {
            PopupStatus.LOADING: self.colors.info,
            PopupStatus.SUCCESS: self.colors.success,
            PopupStatus.ERROR: self.colors.error,
            PopupStatus.WARNING: self.colors.warning,
            PopupStatus.INFO: self.colors.info,
        }
        
        self._icon_label.setText(icons.get(status, "ℹ"))
        self._icon_label.setFont(QFont("Segoe UI", icon_size))
        self._icon_label.setStyleSheet(f"color: {colors[status].name()};")
        self._icon_label.show()
        
        if message:
            self._status_label.setText(message)
            self._status_label.setStyleSheet(f"color: {self.colors.text.name()};")
            self._status_label.show()
        else:
            self._status_label.hide()
        
        self._title_label.hide()
        self._image_label.hide()
        self._text_label.hide()
        
        self.adjustSize()
    
    def show_mixed(
        self,
        image_path: str,
        text: str,
        title: Optional[str] = None,
        max_image_width: int = 100,
        max_image_height: int = 80,
    ) -> None:
        """
        Show a mixed content popup (image + text).
        
        Args:
            image_path: Path to image
            text: Text content
            title: Optional title
            max_image_width: Maximum image width
            max_image_height: Maximum image height
        """
        self.config.content_type = PopupContentType.MIXED
        
        # Title
        if title:
            self._title_label.setText(title)
            self._title_label.show()
        else:
            self._title_label.hide()
        
        # Image
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                max_image_width, max_image_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._image_label.setPixmap(scaled)
            self._image_label.show()
        
        # Text
        self._text_label.setText(text)
        self._text_label.show()
        
        self._icon_label.hide()
        self._status_label.hide()
        
        self.adjustSize()
    
    # =========================================================================
    # Timeout Management
    # =========================================================================
    
    def start_timeout(self) -> None:
        """Start the auto-dismiss timeout."""
        if self.config.timeout <= 0:
            return
        
        self._remaining_timeout = self.config.timeout * 1000  # ms
        
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._timeout_timer.start(int(self._remaining_timeout))
    
    def pause_timeout(self) -> None:
        """Pause the timeout (on hover)."""
        if self._timeout_timer and self._timeout_timer.isActive():
            self._remaining_timeout = self._timeout_timer.remainingTime()
            self._timeout_timer.stop()
    
    def resume_timeout(self) -> None:
        """Resume the timeout (on leave)."""
        if self._timeout_timer and self._remaining_timeout > 0:
            self._timeout_timer.start(int(self._remaining_timeout))
    
    def _on_timeout(self) -> None:
        """Handle timeout - dismiss the popup."""
        self.dismiss()
    
    # =========================================================================
    # Dismiss
    # =========================================================================
    
    def dismiss(self, animated: bool = True) -> None:
        """
        Dismiss the popup.
        
        Args:
            animated: Whether to animate the dismissal
        """
        if self._is_dismissed:
            return
        
        self._is_dismissed = True
        
        if self._timeout_timer:
            self._timeout_timer.stop()
        
        if animated:
            self._animate_out(callback=self._finish_dismiss)
        else:
            self._finish_dismiss()
    
    def _finish_dismiss(self) -> None:
        """Finish dismissal after animation."""
        self.dismissed.emit()
        self.hide()
        self.deleteLater()
    
    # =========================================================================
    # Animations
    # =========================================================================
    
    def show_animated(self) -> None:
        """Show the popup with animation."""
        self.show()
        self._animate_in()
        self.start_timeout()
    
    def _animate_in(self) -> None:
        """Animate popup appearance."""
        anim_type = self.config.animation
        
        if anim_type == PopupAnimation.NONE:
            return
        elif anim_type == PopupAnimation.FADE:
            self._fade_in()
        elif anim_type in (PopupAnimation.SLIDE_LEFT, PopupAnimation.SLIDE_RIGHT,
                           PopupAnimation.SLIDE_UP, PopupAnimation.SLIDE_DOWN):
            self._slide_in(anim_type)
        elif anim_type == PopupAnimation.SCALE:
            self._scale_in()
        elif anim_type == PopupAnimation.BOUNCE:
            self._bounce_in()
    
    def _animate_out(self, callback: Optional[Callable] = None) -> None:
        """Animate popup disappearance."""
        anim_type = self.config.animation
        
        if anim_type == PopupAnimation.NONE:
            if callback:
                callback()
            return
        elif anim_type == PopupAnimation.FADE:
            self._fade_out(callback)
        elif anim_type in (PopupAnimation.SLIDE_LEFT, PopupAnimation.SLIDE_RIGHT,
                           PopupAnimation.SLIDE_UP, PopupAnimation.SLIDE_DOWN):
            self._slide_out(anim_type, callback)
        elif anim_type == PopupAnimation.SCALE:
            self._scale_out(callback)
        elif anim_type == PopupAnimation.BOUNCE:
            self._fade_out(callback)  # Use fade for bounce out
    
    def _fade_in(self) -> None:
        """Fade in animation."""
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(PopupAnimationConfig.FADE_DURATION)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        
        self._animations.append(anim)
    
    def _fade_out(self, callback: Optional[Callable] = None) -> None:
        """Fade out animation."""
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(PopupAnimationConfig.FADE_DURATION)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        
        if callback:
            anim.finished.connect(callback)
        
        anim.start()
        self._animations.append(anim)
    
    def _slide_in(self, direction: PopupAnimation) -> None:
        """Slide in animation."""
        start_pos = self.pos()
        offset = PopupAnimationConfig.SLIDE_DISTANCE
        
        offsets = {
            PopupAnimation.SLIDE_LEFT: QPoint(offset, 0),
            PopupAnimation.SLIDE_RIGHT: QPoint(-offset, 0),
            PopupAnimation.SLIDE_UP: QPoint(0, offset),
            PopupAnimation.SLIDE_DOWN: QPoint(0, -offset),
        }
        
        self.move(start_pos + offsets[direction])
        
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(PopupAnimationConfig.SLIDE_DURATION)
        anim.setStartValue(self.pos())
        anim.setEndValue(start_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        
        self._animations.append(anim)
    
    def _slide_out(self, direction: PopupAnimation, callback: Optional[Callable] = None) -> None:
        """Slide out animation."""
        start_pos = self.pos()
        offset = PopupAnimationConfig.SLIDE_DISTANCE
        
        offsets = {
            PopupAnimation.SLIDE_LEFT: QPoint(-offset, 0),
            PopupAnimation.SLIDE_RIGHT: QPoint(offset, 0),
            PopupAnimation.SLIDE_UP: QPoint(0, -offset),
            PopupAnimation.SLIDE_DOWN: QPoint(0, offset),
        }
        
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(PopupAnimationConfig.SLIDE_DURATION)
        anim.setStartValue(start_pos)
        anim.setEndValue(start_pos + offsets[direction])
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        
        if callback:
            anim.finished.connect(callback)
        
        anim.start()
        self._animations.append(anim)
    
    def _scale_in(self) -> None:
        """Scale in animation (from small to normal)."""
        # Use a combination of opacity and size animation
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(PopupAnimationConfig.SCALE_DURATION)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutBack)
        anim.start()
        
        self._animations.append(anim)
    
    def _scale_out(self, callback: Optional[Callable] = None) -> None:
        """Scale out animation."""
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(PopupAnimationConfig.SCALE_DURATION)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InBack)
        
        if callback:
            anim.finished.connect(callback)
        
        anim.start()
        self._animations.append(anim)
    
    def _bounce_in(self) -> None:
        """Bounce in animation."""
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(PopupAnimationConfig.BOUNCE_DURATION)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutBounce)
        anim.start()
        
        self._animations.append(anim)
    
    # =========================================================================
    # Events
    # =========================================================================
    
    def enterEvent(self, event) -> None:
        """Handle mouse enter."""
        self._is_hovered = True
        self.hovered.emit(True)
        
        if self.config.pausable:
            self.pause_timeout()
        
        super().enterEvent(event)
    
    def leaveEvent(self, event) -> None:
        """Handle mouse leave."""
        self._is_hovered = False
        self.hovered.emit(False)
        
        if self.config.pausable:
            self.resume_timeout()
        
        super().leaveEvent(event)
    
    def mousePressEvent(self, event) -> None:
        """Handle mouse click."""
        self.clicked.emit()
        
        if self.config.dismissable:
            self.dismiss()
        
        super().mousePressEvent(event)
    
    def paintEvent(self, event) -> None:
        """Custom paint for rounded rectangle with glow border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background path
        path = QPainterPath()
        rect = self.rect().adjusted(2, 2, -2, -2)
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), 8, 8)
        
        # Fill background
        painter.fillPath(path, self.colors.background)
        
        # Draw gradient border
        pen = QPen(self.colors.border, 1.5)
        painter.setPen(pen)
        painter.drawPath(path)
        
        painter.end()


# =============================================================================
# Popup Manager
# =============================================================================


class PopupManagerSignals(QObject):
    """Thread-safe signals for PopupManager."""
    show_popup_signal = pyqtSignal(dict, object)  # config dict, content
    dismiss_all_signal = pyqtSignal()
    dismiss_popup_signal = pyqtSignal(int)  # popup id


class PopupManager:
    """
    Central manager for popup panels.
    
    Handles:
    - Creating and positioning popups
    - Queue management for multiple popups
    - Maximum popup limits
    - Priority-based ordering
    
    Example:
        manager = PopupManager(parent_panel=jarvis_panel)
        
        # Show text popup
        popup = manager.show_text("Görev tamamlandı", title="Başarılı")
        
        # Show image popup
        popup = manager.show_image("/path/to/image.png", caption="Görsel")
        
        # Show status
        popup = manager.show_status(PopupStatus.SUCCESS, "İşlem başarılı")
        
        # Dismiss all
        manager.dismiss_all()
    """
    
    def __init__(
        self,
        parent_panel: Optional[QWidget] = None,
        max_popups: int = 5,
        colors: Optional[PopupColors] = None,
        default_position: PopupPosition = PopupPosition.TOP_RIGHT,
        default_timeout: float = 5.0,
        default_animation: PopupAnimation = PopupAnimation.FADE,
    ):
        """
        Initialize popup manager.
        
        Args:
            parent_panel: Parent Jarvis panel for positioning
            max_popups: Maximum simultaneous popups
            colors: Color palette
            default_position: Default popup position
            default_timeout: Default auto-dismiss timeout
            default_animation: Default animation type
        """
        self.parent_panel = parent_panel
        self.max_popups = max_popups
        self.colors = colors or PopupColors()
        self.default_position = default_position
        self.default_timeout = default_timeout
        self.default_animation = default_animation
        
        # Active popups
        self._popups: List[PopupPanel] = []
        self._popup_queue: List[tuple] = []  # (config, content, method)
        self._next_id = 0
        
        # Thread-safe signals
        self.signals = PopupManagerSignals()
        self._connect_signals()
    
    def _connect_signals(self) -> None:
        """Connect thread-safe signals."""
        self.signals.dismiss_all_signal.connect(self._dismiss_all_impl)
    
    # =========================================================================
    # Show Methods
    # =========================================================================
    
    def show_popup(
        self,
        config: Optional[PopupConfig] = None,
        content: Optional[Any] = None,
    ) -> Optional[PopupPanel]:
        """
        Show a popup with custom configuration.
        
        Args:
            config: Popup configuration
            content: Content data (varies by content_type)
            
        Returns:
            The created PopupPanel or None if queued
        """
        config = config or PopupConfig()
        
        # Check max popups
        if len(self._popups) >= self.max_popups:
            # Queue the popup
            self._popup_queue.append((config, content, "custom"))
            return None
        
        # Create popup
        popup = self._create_popup(config)
        
        # Set content based on type
        if content:
            if config.content_type == PopupContentType.TEXT:
                popup.show_text(content.get("text", ""), content.get("title"))
            elif config.content_type == PopupContentType.IMAGE:
                popup.show_image(content.get("path", ""), content.get("caption"))
            elif config.content_type == PopupContentType.ICON:
                popup.show_icon(content.get("status", PopupStatus.INFO), content.get("message"))
            elif config.content_type == PopupContentType.MIXED:
                popup.show_mixed(
                    content.get("path", ""),
                    content.get("text", ""),
                    content.get("title"),
                )
        
        return popup
    
    def show_text(
        self,
        text: str,
        title: Optional[str] = None,
        position: Optional[PopupPosition] = None,
        timeout: Optional[float] = None,
        animation: Optional[PopupAnimation] = None,
        priority: int = 0,
    ) -> Optional[PopupPanel]:
        """
        Show a text popup.
        
        Args:
            text: Main text content
            title: Optional title
            position: Position (uses default if None)
            timeout: Auto-dismiss timeout (uses default if None)
            animation: Animation type (uses default if None)
            priority: Priority (higher = shown first)
            
        Returns:
            The created PopupPanel or None if queued
        """
        config = PopupConfig(
            content_type=PopupContentType.TEXT,
            position=position or self.default_position,
            timeout=timeout if timeout is not None else self.default_timeout,
            animation=animation or self.default_animation,
            priority=priority,
        )
        
        if len(self._popups) >= self.max_popups:
            self._popup_queue.append((config, {"text": text, "title": title}, "text"))
            return None
        
        popup = self._create_popup(config)
        popup.show_text(text, title)
        return popup
    
    def show_image(
        self,
        image_path: str,
        caption: Optional[str] = None,
        position: Optional[PopupPosition] = None,
        timeout: Optional[float] = None,
        animation: Optional[PopupAnimation] = None,
        priority: int = 0,
    ) -> Optional[PopupPanel]:
        """
        Show an image popup.
        
        Args:
            image_path: Path to image file
            caption: Optional caption
            position: Position (uses default if None)
            timeout: Auto-dismiss timeout (uses default if None)
            animation: Animation type (uses default if None)
            priority: Priority
            
        Returns:
            The created PopupPanel or None if queued
        """
        config = PopupConfig(
            content_type=PopupContentType.IMAGE,
            position=position or self.default_position,
            timeout=timeout if timeout is not None else self.default_timeout,
            animation=animation or self.default_animation,
            priority=priority,
        )
        
        if len(self._popups) >= self.max_popups:
            self._popup_queue.append((config, {"path": image_path, "caption": caption}, "image"))
            return None
        
        popup = self._create_popup(config)
        popup.show_image(image_path, caption)
        return popup
    
    def show_status(
        self,
        status: PopupStatus,
        message: Optional[str] = None,
        position: Optional[PopupPosition] = None,
        timeout: Optional[float] = None,
        animation: Optional[PopupAnimation] = None,
        priority: int = 0,
    ) -> Optional[PopupPanel]:
        """
        Show a status/icon popup.
        
        Args:
            status: Status type (LOADING, SUCCESS, ERROR, etc.)
            message: Optional status message
            position: Position (uses default if None)
            timeout: Auto-dismiss timeout (uses default if None)
            animation: Animation type (uses default if None)
            priority: Priority
            
        Returns:
            The created PopupPanel or None if queued
        """
        config = PopupConfig(
            content_type=PopupContentType.ICON,
            position=position or self.default_position,
            timeout=timeout if timeout is not None else self.default_timeout,
            animation=animation or self.default_animation,
            priority=priority,
            width=180,
        )
        
        if len(self._popups) >= self.max_popups:
            self._popup_queue.append((config, {"status": status, "message": message}, "status"))
            return None
        
        popup = self._create_popup(config)
        popup.show_icon(status, message)
        return popup
    
    def show_mixed(
        self,
        image_path: str,
        text: str,
        title: Optional[str] = None,
        position: Optional[PopupPosition] = None,
        timeout: Optional[float] = None,
        animation: Optional[PopupAnimation] = None,
        priority: int = 0,
    ) -> Optional[PopupPanel]:
        """
        Show a mixed content popup (image + text).
        
        Args:
            image_path: Path to image
            text: Text content
            title: Optional title
            position: Position (uses default if None)
            timeout: Auto-dismiss timeout (uses default if None)
            animation: Animation type (uses default if None)
            priority: Priority
            
        Returns:
            The created PopupPanel or None if queued
        """
        config = PopupConfig(
            content_type=PopupContentType.MIXED,
            position=position or self.default_position,
            timeout=timeout if timeout is not None else self.default_timeout,
            animation=animation or self.default_animation,
            priority=priority,
        )
        
        if len(self._popups) >= self.max_popups:
            content = {"path": image_path, "text": text, "title": title}
            self._popup_queue.append((config, content, "mixed"))
            return None
        
        popup = self._create_popup(config)
        popup.show_mixed(image_path, text, title)
        return popup
    
    # =========================================================================
    # Popup Creation
    # =========================================================================
    
    def _create_popup(self, config: PopupConfig) -> PopupPanel:
        """Create and setup a popup panel."""
        popup = PopupPanel(config=config, colors=self.colors)
        
        # Position
        self._position_popup(popup, config.position)
        
        # Connect signals
        popup.dismissed.connect(lambda: self._on_popup_dismissed(popup))
        
        # Track
        self._popups.append(popup)
        
        # Show with animation
        popup.show_animated()
        
        return popup
    
    def _position_popup(self, popup: PopupPanel, position: PopupPosition) -> None:
        """Position popup relative to parent panel or screen."""
        if self.parent_panel and self.parent_panel.isVisible():
            self._position_relative_to_parent(popup, position)
        else:
            self._position_on_screen(popup, position)
    
    def _position_relative_to_parent(self, popup: PopupPanel, position: PopupPosition) -> None:
        """Position popup relative to parent panel."""
        parent_rect = self.parent_panel.geometry()
        popup_size = popup.sizeHint()
        margin = popup.config.margin
        
        # Calculate base position
        x, y = 0, 0
        
        if position in (PopupPosition.TOP_LEFT, PopupPosition.LEFT, PopupPosition.BOTTOM_LEFT):
            x = parent_rect.left() - popup_size.width() - margin
        elif position in (PopupPosition.TOP_RIGHT, PopupPosition.RIGHT, PopupPosition.BOTTOM_RIGHT):
            x = parent_rect.right() + margin
        elif position == PopupPosition.TOP:
            x = parent_rect.center().x() - popup_size.width() // 2
        elif position == PopupPosition.BOTTOM:
            x = parent_rect.center().x() - popup_size.width() // 2
        
        if position in (PopupPosition.TOP_LEFT, PopupPosition.TOP, PopupPosition.TOP_RIGHT):
            y = parent_rect.top()
        elif position in (PopupPosition.BOTTOM_LEFT, PopupPosition.BOTTOM, PopupPosition.BOTTOM_RIGHT):
            y = parent_rect.bottom() - popup_size.height()
        elif position in (PopupPosition.LEFT, PopupPosition.RIGHT):
            y = parent_rect.center().y() - popup_size.height() // 2
        
        # Stack offset for multiple popups at same position
        stack_offset = self._get_stack_offset(position, popup_size.height())
        
        if position in (PopupPosition.TOP_LEFT, PopupPosition.TOP, PopupPosition.TOP_RIGHT):
            y += stack_offset
        else:
            y -= stack_offset
        
        popup.move(x, y)
    
    def _position_on_screen(self, popup: PopupPanel, position: PopupPosition) -> None:
        """Position popup on screen when no parent."""
        screen = QApplication.primaryScreen().geometry()
        popup_size = popup.sizeHint()
        margin = popup.config.margin + 20
        
        x, y = 0, 0
        
        if position in (PopupPosition.TOP_LEFT, PopupPosition.LEFT, PopupPosition.BOTTOM_LEFT):
            x = margin
        elif position in (PopupPosition.TOP_RIGHT, PopupPosition.RIGHT, PopupPosition.BOTTOM_RIGHT):
            x = screen.width() - popup_size.width() - margin
        else:
            x = screen.width() // 2 - popup_size.width() // 2
        
        if position in (PopupPosition.TOP_LEFT, PopupPosition.TOP, PopupPosition.TOP_RIGHT):
            y = margin
        elif position in (PopupPosition.BOTTOM_LEFT, PopupPosition.BOTTOM, PopupPosition.BOTTOM_RIGHT):
            y = screen.height() - popup_size.height() - margin
        else:
            y = screen.height() // 2 - popup_size.height() // 2
        
        # Stack offset
        stack_offset = self._get_stack_offset(position, popup_size.height())
        
        if position in (PopupPosition.TOP_LEFT, PopupPosition.TOP, PopupPosition.TOP_RIGHT):
            y += stack_offset
        else:
            y -= stack_offset
        
        popup.move(x, y)
    
    def _get_stack_offset(self, position: PopupPosition, height: int) -> int:
        """Calculate stack offset for multiple popups at same position."""
        same_position_count = sum(
            1 for p in self._popups
            if p.config.position == position
        ) - 1  # Exclude current popup
        
        return same_position_count * (height + 10)
    
    # =========================================================================
    # Dismiss
    # =========================================================================
    
    def dismiss_all(self) -> None:
        """Dismiss all active popups (thread-safe)."""
        self.signals.dismiss_all_signal.emit()
    
    def _dismiss_all_impl(self) -> None:
        """Dismiss all popups implementation."""
        for popup in self._popups[:]:
            popup.dismiss()
        self._popups.clear()
        self._popup_queue.clear()
    
    def _on_popup_dismissed(self, popup: PopupPanel) -> None:
        """Handle popup dismissal."""
        if popup in self._popups:
            self._popups.remove(popup)
        
        # Process queue
        self._process_queue()
    
    def _process_queue(self) -> None:
        """Process queued popups."""
        if not self._popup_queue:
            return
        
        if len(self._popups) >= self.max_popups:
            return
        
        # Sort by priority
        self._popup_queue.sort(key=lambda x: x[0].priority, reverse=True)
        
        # Show next popup
        config, content, method = self._popup_queue.pop(0)
        
        if method == "text":
            popup = self._create_popup(config)
            popup.show_text(content.get("text", ""), content.get("title"))
        elif method == "image":
            popup = self._create_popup(config)
            popup.show_image(content.get("path", ""), content.get("caption"))
        elif method == "status":
            popup = self._create_popup(config)
            popup.show_icon(content.get("status", PopupStatus.INFO), content.get("message"))
        elif method == "mixed":
            popup = self._create_popup(config)
            popup.show_mixed(
                content.get("path", ""),
                content.get("text", ""),
                content.get("title"),
            )
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def active_count(self) -> int:
        """Number of active popups."""
        return len(self._popups)
    
    @property
    def queue_count(self) -> int:
        """Number of queued popups."""
        return len(self._popup_queue)
    
    def set_max_popups(self, count: int) -> None:
        """Set maximum simultaneous popups."""
        self.max_popups = max(1, count)
    
    def set_default_timeout(self, timeout: float) -> None:
        """Set default timeout for new popups."""
        self.default_timeout = max(0, timeout)
    
    def set_default_position(self, position: PopupPosition) -> None:
        """Set default position for new popups."""
        self.default_position = position


# =============================================================================
# Helper Functions
# =============================================================================


def parse_popup_position(text: str) -> Optional[PopupPosition]:
    """
    Parse popup position from Turkish text.
    
    Examples:
        "sağ üst" -> PopupPosition.TOP_RIGHT
        "sol alt" -> PopupPosition.BOTTOM_LEFT
    """
    text_lower = text.lower().strip()
    return POPUP_POSITION_ALIASES.get(text_lower)


def is_popup_dismiss_intent(text: str) -> bool:
    """
    Check if text is a popup dismiss intent.
    
    Examples:
        "popup kapat" -> True
        "bildirimleri kapat" -> True
        "balonları gizle" -> True
    """
    text_lower = text.lower()
    
    dismiss_patterns = [
        "popup kapat",
        "popupları kapat",
        "popup'ları kapat",
        "bildirim kapat",
        "bildirimleri kapat",
        "balon kapat",
        "balonları kapat",
        "bubble kapat",
        "hepsini kapat",
        "kapat hepsini",
    ]
    
    return any(pattern in text_lower for pattern in dismiss_patterns)
