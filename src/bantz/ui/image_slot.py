"""
Image Slot Widget (Issue #34 - UI-2).

Displays images with:
- Async loading
- Placeholder fallback
- Click handler
- Fit/fill modes
"""

from typing import Optional, Callable
from pathlib import Path
from PyQt5.QtWidgets import (
    QLabel, QFrame, QVBoxLayout, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QThread, pyqtSlot
from PyQt5.QtGui import (
    QPixmap, QImage, QColor, QPainter, QBrush, QPen, QFont
)


# Default placeholder color
PLACEHOLDER_COLOR = QColor(30, 50, 70)
PLACEHOLDER_BORDER = QColor(0, 162, 255, 80)


class ImageLoader(QThread):
    """Async image loader thread."""
    
    loaded = pyqtSignal(QPixmap)
    error = pyqtSignal(str)
    
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
    
    def run(self):
        """Load image in background."""
        try:
            pixmap = QPixmap(self.path)
            if pixmap.isNull():
                self.error.emit(f"Failed to load: {self.path}")
            else:
                self.loaded.emit(pixmap)
        except Exception as e:
            self.error.emit(str(e))


class ImageSlot(QFrame):
    """
    Image slot widget for displaying visual content.
    
    Features:
    - Async image loading
    - Placeholder display
    - Click handling
    - Aspect ratio preservation
    """
    
    # Signals
    clicked = pyqtSignal()
    image_loaded = pyqtSignal()
    image_error = pyqtSignal(str)
    
    def __init__(
        self,
        width: int = 200,
        height: int = 150,
        parent: Optional[QFrame] = None
    ):
        super().__init__(parent)
        
        self._target_width = width
        self._target_height = height
        self._current_pixmap: Optional[QPixmap] = None
        self._placeholder_text = "No Image"
        self._loader: Optional[ImageLoader] = None
        
        self._setup_ui()
        self._setup_style()
        self._set_placeholder_display()
    
    def _setup_ui(self):
        """Setup image slot UI."""
        self.setObjectName("image_slot")
        self.setFixedSize(self._target_width, self._target_height)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Image label
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setFixedSize(self._target_width, self._target_height)
        self._image_label.setScaledContents(False)
        layout.addWidget(self._image_label)
    
    def _setup_style(self):
        """Setup styling."""
        self.setStyleSheet("""
            QFrame#image_slot {
                background-color: rgba(30, 50, 70, 0.8);
                border: 1px solid rgba(0, 162, 255, 0.3);
                border-radius: 6px;
            }
            QFrame#image_slot:hover {
                border: 1px solid rgba(0, 200, 255, 0.6);
            }
        """)
        
        # Add shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
    
    def set_image(self, source: str, async_load: bool = True) -> None:
        """
        Set image from file path.
        
        Args:
            source: Path to image file
            async_load: Whether to load asynchronously
        """
        if async_load:
            self._load_async(source)
        else:
            self._load_sync(source)
    
    def set_image_pixmap(self, pixmap: QPixmap) -> None:
        """
        Set image from QPixmap directly.
        
        Args:
            pixmap: QPixmap to display
        """
        if pixmap.isNull():
            self._set_placeholder_display()
            return
        
        self._current_pixmap = pixmap
        self._display_pixmap(pixmap)
        self.image_loaded.emit()
    
    def set_placeholder(self, text: str = "No Image") -> None:
        """
        Set placeholder text.
        
        Args:
            text: Placeholder text to display
        """
        self._placeholder_text = text
        if self._current_pixmap is None:
            self._set_placeholder_display()
    
    def clear(self) -> None:
        """Clear image and show placeholder."""
        self._current_pixmap = None
        self._set_placeholder_display()
    
    def on_click(self) -> None:
        """Handle click event."""
        self.clicked.emit()
    
    def has_image(self) -> bool:
        """Check if slot has an image loaded."""
        return self._current_pixmap is not None
    
    def get_pixmap(self) -> Optional[QPixmap]:
        """Get current pixmap if any."""
        return self._current_pixmap
    
    def _load_sync(self, path: str):
        """Load image synchronously."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._set_placeholder_display()
            self.image_error.emit(f"Failed to load: {path}")
        else:
            self._current_pixmap = pixmap
            self._display_pixmap(pixmap)
            self.image_loaded.emit()
    
    def _load_async(self, path: str):
        """Load image asynchronously."""
        # Cancel previous loader
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
        
        self._loader = ImageLoader(path, self)
        self._loader.loaded.connect(self._on_image_loaded)
        self._loader.error.connect(self._on_image_error)
        self._loader.start()
    
    @pyqtSlot(QPixmap)
    def _on_image_loaded(self, pixmap: QPixmap):
        """Handle async image load complete."""
        self._current_pixmap = pixmap
        self._display_pixmap(pixmap)
        self.image_loaded.emit()
    
    @pyqtSlot(str)
    def _on_image_error(self, error: str):
        """Handle async image load error."""
        self._set_placeholder_display()
        self.image_error.emit(error)
    
    def _display_pixmap(self, pixmap: QPixmap):
        """Display pixmap with proper scaling."""
        # Scale to fit while preserving aspect ratio
        scaled = pixmap.scaled(
            self._target_width,
            self._target_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._image_label.setPixmap(scaled)
    
    def _set_placeholder_display(self):
        """Display placeholder."""
        # Create placeholder pixmap
        placeholder = QPixmap(self._target_width, self._target_height)
        placeholder.fill(PLACEHOLDER_COLOR)
        
        # Draw border and text
        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Border
        pen = QPen(PLACEHOLDER_BORDER)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRoundedRect(
            1, 1,
            self._target_width - 2,
            self._target_height - 2,
            5, 5
        )
        
        # Text
        painter.setPen(QPen(QColor(100, 130, 160)))
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        painter.drawText(
            0, 0,
            self._target_width,
            self._target_height,
            Qt.AlignCenter,
            self._placeholder_text
        )
        
        painter.end()
        self._image_label.setPixmap(placeholder)
    
    def mousePressEvent(self, event):
        """Handle mouse press."""
        if event.button() == Qt.LeftButton:
            self.on_click()
        super().mousePressEvent(event)
    
    def resize_slot(self, width: int, height: int) -> None:
        """
        Resize the image slot.
        
        Args:
            width: New width
            height: New height
        """
        self._target_width = width
        self._target_height = height
        self.setFixedSize(width, height)
        self._image_label.setFixedSize(width, height)
        
        # Redisplay current content
        if self._current_pixmap:
            self._display_pixmap(self._current_pixmap)
        else:
            self._set_placeholder_display()
