"""
Source Card Widget (Issue #34 - UI-2).

Displays a research source with:
- Title
- URL (shortened)
- Date
- Snippet preview
- Reliability indicator
- Click to open URL
"""

from dataclasses import dataclass
from typing import Optional, Callable
import webbrowser
from PyQt5.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QFont, QCursor, QPainter


@dataclass
class SourceCardData:
    """Data for a source card."""
    title: str
    url: str
    date: Optional[str] = None
    snippet: Optional[str] = None
    favicon: Optional[str] = None
    reliability: Optional[str] = None  # "high", "medium", "low"
    
    def get_short_url(self, max_length: int = 40) -> str:
        """Get shortened URL for display."""
        # Remove protocol
        url = self.url
        for prefix in ["https://", "http://", "www."]:
            if url.startswith(prefix):
                url = url[len(prefix):]
        
        # Truncate if needed
        if len(url) > max_length:
            url = url[:max_length - 3] + "..."
        
        return url


# Reliability color mapping
RELIABILITY_COLORS = {
    "high": "#00FF88",      # Green
    "medium": "#FFB800",    # Amber
    "low": "#FF4444",       # Red
    None: "#00A2FF",        # Default blue
}

RELIABILITY_LABELS = {
    "high": "Reliable",
    "medium": "Medium",
    "low": "Low",
    None: "",
}


class SourceCard(QFrame):
    """
    Source card widget for displaying research sources.
    
    Features:
    - Title with hover effect
    - Shortened URL
    - Date display
    - Snippet preview
    - Reliability indicator
    - Click to open URL
    """
    
    # Signals
    clicked = pyqtSignal(str)  # Emits URL when clicked
    
    def __init__(
        self,
        data: SourceCardData,
        parent: Optional[QFrame] = None
    ):
        super().__init__(parent)
        
        self.data = data
        self._highlighted = False
        
        self._setup_ui()
        self._setup_style()
    
    def _setup_ui(self):
        """Setup card UI elements."""
        self.setObjectName("source_card")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        
        # Top row: Title + Reliability
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        
        # Title
        self._title_label = QLabel(self.data.title)
        self._title_label.setWordWrap(True)
        self._title_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self._title_label.setStyleSheet("color: #FFFFFF;")
        top_row.addWidget(self._title_label, 1)
        
        # Reliability badge
        if self.data.reliability:
            reliability_color = RELIABILITY_COLORS.get(self.data.reliability, RELIABILITY_COLORS[None])
            reliability_text = RELIABILITY_LABELS.get(self.data.reliability, "")
            self._reliability_label = QLabel(reliability_text)
            self._reliability_label.setFont(QFont("Segoe UI", 8))
            self._reliability_label.setStyleSheet(f"""
                color: {reliability_color};
                background-color: rgba(0, 0, 0, 0.3);
                padding: 2px 6px;
                border-radius: 3px;
            """)
            top_row.addWidget(self._reliability_label)
        
        layout.addLayout(top_row)
        
        # URL row
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        
        self._url_label = QLabel(self.data.get_short_url())
        self._url_label.setFont(QFont("Consolas", 9))
        self._url_label.setStyleSheet("color: #00A2FF;")
        url_row.addWidget(self._url_label)
        
        # Date
        if self.data.date:
            self._date_label = QLabel(self.data.date)
            self._date_label.setFont(QFont("Segoe UI", 9))
            self._date_label.setStyleSheet("color: #888888;")
            url_row.addWidget(self._date_label)
        
        url_row.addStretch()
        layout.addLayout(url_row)
        
        # Snippet
        if self.data.snippet:
            self._snippet_label = QLabel(self._truncate_snippet(self.data.snippet))
            self._snippet_label.setWordWrap(True)
            self._snippet_label.setFont(QFont("Segoe UI", 9))
            self._snippet_label.setStyleSheet("color: #CCCCCC;")
            layout.addWidget(self._snippet_label)
    
    def _setup_style(self):
        """Setup card styling."""
        self._update_style()
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 162, 255, 50))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
    
    def _update_style(self):
        """Update card style based on state."""
        if self._highlighted:
            border_color = "rgba(0, 255, 136, 0.8)"
            bg_color = "rgba(0, 50, 100, 0.9)"
        else:
            border_color = "rgba(0, 162, 255, 0.4)"
            bg_color = "rgba(20, 35, 55, 0.85)"
        
        self.setStyleSheet(f"""
            QFrame#source_card {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
            QFrame#source_card:hover {{
                background-color: rgba(30, 50, 80, 0.95);
                border: 1px solid rgba(0, 200, 255, 0.7);
            }}
        """)
    
    def _truncate_snippet(self, snippet: str, max_length: int = 150) -> str:
        """Truncate snippet to max length."""
        if len(snippet) <= max_length:
            return snippet
        return snippet[:max_length - 3] + "..."
    
    def update_data(self, data: SourceCardData) -> None:
        """
        Update card with new data.
        
        Args:
            data: New source card data
        """
        self.data = data
        self._title_label.setText(data.title)
        self._url_label.setText(data.get_short_url())
        
        if hasattr(self, '_date_label') and data.date:
            self._date_label.setText(data.date)
        
        if hasattr(self, '_snippet_label') and data.snippet:
            self._snippet_label.setText(self._truncate_snippet(data.snippet))
        
        if hasattr(self, '_reliability_label') and data.reliability:
            reliability_color = RELIABILITY_COLORS.get(data.reliability, RELIABILITY_COLORS[None])
            reliability_text = RELIABILITY_LABELS.get(data.reliability, "")
            self._reliability_label.setText(reliability_text)
            self._reliability_label.setStyleSheet(f"""
                color: {reliability_color};
                background-color: rgba(0, 0, 0, 0.3);
                padding: 2px 6px;
                border-radius: 3px;
            """)
    
    def set_highlighted(self, highlighted: bool) -> None:
        """
        Set card highlighted state.
        
        Args:
            highlighted: Whether card should be highlighted
        """
        self._highlighted = highlighted
        self._update_style()
    
    def on_click(self) -> None:
        """Handle card click - open URL in browser."""
        if self.data.url:
            webbrowser.open(self.data.url)
    
    def mousePressEvent(self, event):
        """Handle mouse press."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.data.url)
            self.on_click()
        super().mousePressEvent(event)
    
    def enterEvent(self, event):
        """Handle mouse enter."""
        self._title_label.setStyleSheet("color: #00CCFF;")
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Handle mouse leave."""
        self._title_label.setStyleSheet("color: #FFFFFF;")
        super().leaveEvent(event)
