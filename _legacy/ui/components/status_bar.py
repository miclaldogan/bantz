"""Status bar widget with indicators (Issue #5).

Shows various status indicators like:
- Connection status
- Audio status
- Processing status
- Battery/resource usage
"""
from __future__ import annotations

from typing import Optional, Dict, List
from enum import Enum

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen

from ..themes import OverlayTheme, JARVIS_THEME


class StatusLevel(Enum):
    """Status indicator levels."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INACTIVE = "inactive"
    PROCESSING = "processing"


class StatusIndicator(QWidget):
    """Single status indicator with icon and optional label."""
    
    clicked = pyqtSignal()
    
    def __init__(
        self,
        icon: str = "●",
        label: str = "",
        status: StatusLevel = StatusLevel.INACTIVE,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.theme = theme or JARVIS_THEME
        self._icon = icon
        self._label_text = label
        self._status = status
        self._blinking = False
        self._blink_visible = True
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._setup_ui()
        
        # Blink timer
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_blink)
    
    def _setup_ui(self):
        """Setup UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        
        self.icon_label = QLabel(self._icon)
        self.icon_label.setFixedSize(14, 14)
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)
        
        if self._label_text:
            self.text_label = QLabel(self._label_text)
            self.text_label.setStyleSheet(f"color: {self.theme.text_secondary}; font-size: 10px;")
            layout.addWidget(self.text_label)
        else:
            self.text_label = None
        
        self._update_style()
    
    @property
    def status(self) -> StatusLevel:
        """Get current status."""
        return self._status
    
    @status.setter
    def status(self, value: StatusLevel):
        """Set status."""
        self._status = value
        self._update_style()
        
        # Auto-blink for processing
        if value == StatusLevel.PROCESSING:
            self.start_blink()
        else:
            self.stop_blink()
    
    def set_status(self, status: StatusLevel):
        """Set status."""
        self.status = status
    
    def set_icon(self, icon: str):
        """Set icon text."""
        self._icon = icon
        self.icon_label.setText(icon)
    
    def set_label(self, text: str):
        """Set label text."""
        if self.text_label:
            self.text_label.setText(text)
    
    def start_blink(self, interval: int = 500):
        """Start blinking animation."""
        if not self._blinking:
            self._blinking = True
            self._blink_timer.start(interval)
    
    def stop_blink(self):
        """Stop blinking animation."""
        self._blinking = False
        self._blink_timer.stop()
        self._blink_visible = True
        self._update_style()
    
    def _toggle_blink(self):
        """Toggle blink visibility."""
        self._blink_visible = not self._blink_visible
        self._update_style()
    
    def _update_style(self):
        """Update icon color based on status."""
        colors = {
            StatusLevel.OK: self.theme.success,
            StatusLevel.WARNING: self.theme.warning,
            StatusLevel.ERROR: self.theme.error,
            StatusLevel.INACTIVE: self.theme.text_secondary,
            StatusLevel.PROCESSING: self.theme.primary,
        }
        
        color = colors.get(self._status, self.theme.text_secondary)
        
        if not self._blink_visible:
            color = "transparent"
        
        self.icon_label.setStyleSheet(f"color: {color}; font-size: 12px;")
    
    def mousePressEvent(self, event):
        """Handle click."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme."""
        self.theme = theme
        self._update_style()
        if self.text_label:
            self.text_label.setStyleSheet(f"color: {theme.text_secondary}; font-size: 10px;")


class StatusBarWidget(QWidget):
    """Status bar with multiple indicators.
    
    Provides indicators for:
    - Audio input (microphone)
    - Network connection
    - Processing status
    - Custom indicators
    
    Signals:
        indicator_clicked: Emitted when an indicator is clicked (name)
    """
    
    indicator_clicked = pyqtSignal(str)
    
    # Default indicators
    DEFAULT_INDICATORS = {
        "mic": {"icon": "🎤", "label": ""},
        "network": {"icon": "📶", "label": ""},
        "processing": {"icon": "⚡", "label": ""},
    }
    
    def __init__(
        self,
        indicators: Optional[Dict] = None,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.theme = theme or JARVIS_THEME
        self._indicators: Dict[str, StatusIndicator] = {}
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._setup_ui()
        
        # Add default indicators
        config = indicators or self.DEFAULT_INDICATORS
        for name, opts in config.items():
            self.add_indicator(name, **opts)
    
    def _setup_ui(self):
        """Setup UI."""
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(8)
        self._layout.addStretch()
    
    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────
    
    def add_indicator(
        self,
        name: str,
        icon: str = "●",
        label: str = "",
        status: StatusLevel = StatusLevel.INACTIVE,
    ) -> StatusIndicator:
        """Add a status indicator.
        
        Args:
            name: Unique identifier
            icon: Icon text
            label: Optional label
            status: Initial status
            
        Returns:
            The created indicator
        """
        if name in self._indicators:
            return self._indicators[name]
        
        indicator = StatusIndicator(
            icon=icon,
            label=label,
            status=status,
            theme=self.theme,
            parent=self,
        )
        indicator.clicked.connect(lambda: self.indicator_clicked.emit(name))
        
        # Insert before the stretch
        self._layout.insertWidget(self._layout.count() - 1, indicator)
        self._indicators[name] = indicator
        
        return indicator
    
    def remove_indicator(self, name: str):
        """Remove an indicator."""
        if name in self._indicators:
            indicator = self._indicators.pop(name)
            self._layout.removeWidget(indicator)
            indicator.deleteLater()
    
    def get_indicator(self, name: str) -> Optional[StatusIndicator]:
        """Get an indicator by name."""
        return self._indicators.get(name)
    
    def set_status(self, name: str, status: StatusLevel):
        """Set status for an indicator."""
        if name in self._indicators:
            self._indicators[name].status = status
    
    def set_all_status(self, status: StatusLevel):
        """Set status for all indicators."""
        for indicator in self._indicators.values():
            indicator.status = status
    
    # Convenience methods for common indicators
    def set_mic_status(self, status: StatusLevel):
        """Set microphone status."""
        self.set_status("mic", status)
    
    def set_network_status(self, status: StatusLevel):
        """Set network status."""
        self.set_status("network", status)
    
    def set_processing_status(self, status: StatusLevel):
        """Set processing status."""
        self.set_status("processing", status)
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme."""
        self.theme = theme
        for indicator in self._indicators.values():
            indicator.set_theme(theme)
    
    def clear_all(self):
        """Remove all indicators."""
        for name in list(self._indicators.keys()):
            self.remove_indicator(name)


class CompactStatusBar(StatusBarWidget):
    """Minimal status bar with just icons."""
    
    DEFAULT_INDICATORS = {
        "status": {"icon": "●", "label": ""},
    }
    
    def __init__(
        self,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(self.DEFAULT_INDICATORS, theme, parent)
    
    def set_ok(self):
        """Set OK status."""
        self.set_status("status", StatusLevel.OK)
    
    def set_warning(self):
        """Set warning status."""
        self.set_status("status", StatusLevel.WARNING)
    
    def set_error(self):
        """Set error status."""
        self.set_status("status", StatusLevel.ERROR)
    
    def set_processing(self):
        """Set processing status."""
        self.set_status("status", StatusLevel.PROCESSING)
