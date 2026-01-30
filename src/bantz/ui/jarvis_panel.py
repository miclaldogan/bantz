"""Iron Man Jarvis Transparent Panel UI (Issue #19).

A floating, draggable, futuristic panel for displaying:
- Search results (news, web search)
- Page summaries with key points
- Lists with pagination
- Interactive content with hover effects

Design inspired by Iron Man's Jarvis HUD:
- Arc reactor blue color palette
- Semi-transparent background with glow
- Gradient borders and shadows
- Smooth animations (fade, slide)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from enum import Enum, auto

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QSpacerItem
)
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QPoint, QEasingCurve,
    pyqtSignal, QObject, QSize, QRect, QTimer
)
from PyQt5.QtGui import (
    QColor, QFont, QPainter, QLinearGradient, QPen, QBrush,
    QPainterPath, QCursor
)

from .themes import OverlayTheme, JARVIS_THEME


class PanelPosition(Enum):
    """Panel screen positions."""
    RIGHT = "right"
    LEFT = "left"
    TOP_RIGHT = "top_right"
    TOP_LEFT = "top_left"
    CENTER = "center"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_LEFT = "bottom_left"


# Screen position ratios (x_ratio, y_ratio)
POSITION_RATIOS = {
    PanelPosition.RIGHT: (0.65, 0.1),
    PanelPosition.LEFT: (0.02, 0.1),
    PanelPosition.TOP_RIGHT: (0.65, 0.02),
    PanelPosition.TOP_LEFT: (0.02, 0.02),
    PanelPosition.CENTER: (0.3, 0.2),
    PanelPosition.BOTTOM_RIGHT: (0.65, 0.6),
    PanelPosition.BOTTOM_LEFT: (0.02, 0.6),
}


# Turkish position aliases
PANEL_POSITION_ALIASES = {
    "sağ": PanelPosition.RIGHT,
    "sağa": PanelPosition.RIGHT,
    "sol": PanelPosition.LEFT,
    "sola": PanelPosition.LEFT,
    "sağ üst": PanelPosition.TOP_RIGHT,
    "sağ üste": PanelPosition.TOP_RIGHT,
    "sol üst": PanelPosition.TOP_LEFT,
    "sol üste": PanelPosition.TOP_LEFT,
    "orta": PanelPosition.CENTER,
    "ortaya": PanelPosition.CENTER,
    "merkez": PanelPosition.CENTER,
    "sağ alt": PanelPosition.BOTTOM_RIGHT,
    "sol alt": PanelPosition.BOTTOM_LEFT,
}


@dataclass
class PanelColors:
    """Color palette for Jarvis panel (Arc Reactor blue)."""
    background: QColor = field(default_factory=lambda: QColor(10, 25, 47, 200))
    border: QColor = field(default_factory=lambda: QColor(0, 195, 255, 180))
    text: QColor = field(default_factory=lambda: QColor(255, 255, 255, 230))
    accent: QColor = field(default_factory=lambda: QColor(0, 195, 255, 255))
    highlight: QColor = field(default_factory=lambda: QColor(0, 195, 255, 50))
    success: QColor = field(default_factory=lambda: QColor(0, 255, 136, 200))
    warning: QColor = field(default_factory=lambda: QColor(255, 193, 7, 200))
    error: QColor = field(default_factory=lambda: QColor(255, 68, 68, 200))
    
    @classmethod
    def from_theme(cls, theme: OverlayTheme) -> "PanelColors":
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
class ResultItem:
    """A single result item to display."""
    title: str
    source: str = ""
    time: str = ""
    snippet: str = ""
    url: str = ""
    index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class SummaryData:
    """Summary data for display."""
    title: str
    summary: str
    key_points: List[str] = field(default_factory=list)
    source_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class JarvisPanelSignals(QObject):
    """Thread-safe signals for panel control."""
    show_signal = pyqtSignal()
    hide_signal = pyqtSignal()
    show_results_signal = pyqtSignal(list, str)  # results, title
    show_summary_signal = pyqtSignal(dict)  # summary dict
    show_plan_signal = pyqtSignal(dict)  # plan dict for agent tasks
    move_to_signal = pyqtSignal(str)  # position name
    minimize_signal = pyqtSignal()
    maximize_signal = pyqtSignal()
    next_page_signal = pyqtSignal()
    prev_page_signal = pyqtSignal()
    clear_signal = pyqtSignal()


class JarvisPanel(QWidget):
    """Iron Man tarzı transparent bilgi paneli.
    
    Features:
    - Semi-transparent blue background with glow
    - Gradient border effect
    - Header with title and control buttons
    - Scrollable content area
    - Footer with pagination and hints
    - Drag support
    - Fade/slide animations
    - Result list display
    - Summary display with key points
    
    Signals:
        item_clicked: Emitted when a result item is clicked (index)
        panel_closed: Emitted when panel is closed
        page_changed: Emitted when pagination changes (page, total)
    """
    
    item_clicked = pyqtSignal(int)
    panel_closed = pyqtSignal()
    page_changed = pyqtSignal(int, int)
    
    def __init__(
        self,
        colors: Optional[PanelColors] = None,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        # Ensure QApplication exists
        self._app = QApplication.instance()
        if self._app is None:
            self._app = QApplication(sys.argv)
        
        super().__init__(parent)
        
        # Colors
        if colors:
            self.colors = colors
        elif theme:
            self.colors = PanelColors.from_theme(theme)
        else:
            self.colors = PanelColors()
        
        # State
        self._minimized = False
        self._dragging = False
        self._drag_position = QPoint()
        self._position = PanelPosition.RIGHT
        self._current_title = "SONUÇLAR"
        
        # Thread-safe signals
        self.signals = JarvisPanelSignals()
        self._connect_signals()
        
        # Setup
        self._setup_window()
        self._setup_ui()
        self._setup_animations()
        self._setup_glow()
    
    def _connect_signals(self):
        """Connect thread-safe signals to methods."""
        self.signals.show_signal.connect(self._do_show)
        self.signals.hide_signal.connect(self._do_hide)
        self.signals.show_results_signal.connect(self._show_results_internal)
        self.signals.show_summary_signal.connect(self._show_summary_internal)
        self.signals.show_plan_signal.connect(self._show_plan_internal)
        self.signals.move_to_signal.connect(self._move_to_internal)
        self.signals.minimize_signal.connect(self.toggle_minimize)
        self.signals.maximize_signal.connect(self._restore_from_minimize)
        self.signals.next_page_signal.connect(self._on_next_clicked)
        self.signals.prev_page_signal.connect(self._on_prev_clicked)
        self.signals.clear_signal.connect(self._clear_content)
    
    def _setup_window(self):
        """Setup window flags and attributes."""
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        # Size constraints
        self.setMinimumSize(400, 300)
        self.setMaximumSize(600, 800)
        self.resize(500, 500)
    
    def _setup_ui(self):
        """Setup UI components."""
        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.setSpacing(0)
        
        # Header
        self.header = self._create_header()
        self.main_layout.addWidget(self.header)
        
        # Separator line
        self.separator = QFrame()
        self.separator.setFixedHeight(2)
        self.separator.setStyleSheet(
            f"background-color: {self.colors.border.name()};"
        )
        self.main_layout.addWidget(self.separator)
        
        # Content area (scrollable)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(0, 195, 255, 30);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 195, 255, 150);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(8)
        
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        # Footer
        self.footer = self._create_footer()
        self.main_layout.addWidget(self.footer)
    
    def _create_header(self) -> QWidget:
        """Create header widget with title and controls."""
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background: transparent;")
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 10, 10, 5)
        
        # Icon + Title
        self.title_label = QLabel("🔍 SONUÇLAR")
        self.title_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.title_label.setStyleSheet(
            f"color: {self.colors.accent.name()};"
        )
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Control buttons
        button_style = f"""
            QPushButton {{
                background-color: rgba(0, 195, 255, 30);
                color: {self.colors.accent.name()};
                border: 1px solid {self.colors.border.name()};
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 195, 255, 80);
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 195, 255, 120);
            }}
        """
        
        self.minimize_btn = QPushButton("─")
        self.minimize_btn.setFixedSize(30, 30)
        self.minimize_btn.setStyleSheet(button_style)
        self.minimize_btn.clicked.connect(self.toggle_minimize)
        self.minimize_btn.setCursor(QCursor(Qt.PointingHandCursor))
        layout.addWidget(self.minimize_btn)
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet(button_style)
        self.close_btn.clicked.connect(self._do_hide)
        self.close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        layout.addWidget(self.close_btn)
        
        return header
    
    def _create_footer(self) -> QWidget:
        """Create footer widget with hints and pagination."""
        footer = QWidget()
        footer.setFixedHeight(45)
        footer.setStyleSheet("background: transparent;")
        
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(15, 5, 15, 10)
        
        # Hint text
        self.hint_label = QLabel('💬 "3. sonucu aç" diyebilirsiniz')
        self.hint_label.setStyleSheet(
            f"color: rgba(255, 255, 255, 150); font-style: italic; font-size: 11px;"
        )
        layout.addWidget(self.hint_label)
        
        layout.addStretch()
        
        # Pagination
        nav_button_style = f"""
            QPushButton {{
                background-color: rgba(0, 195, 255, 30);
                color: {self.colors.accent.name()};
                border: 1px solid {self.colors.border.name()};
                border-radius: 5px;
                font-size: 12px;
                padding: 3px 8px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 195, 255, 80);
            }}
            QPushButton:disabled {{
                background-color: rgba(50, 50, 50, 50);
                color: rgba(100, 100, 100, 150);
                border-color: rgba(100, 100, 100, 100);
            }}
        """
        
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedSize(35, 28)
        self.prev_btn.setStyleSheet(nav_button_style)
        self.prev_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.prev_btn.clicked.connect(self._on_prev_clicked)
        layout.addWidget(self.prev_btn)
        
        self.page_label = QLabel("1/1")
        self.page_label.setStyleSheet(
            f"color: {self.colors.text.name()}; font-size: 12px; margin: 0 5px;"
        )
        layout.addWidget(self.page_label)
        
        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedSize(35, 28)
        self.next_btn.setStyleSheet(nav_button_style)
        self.next_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.next_btn.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_btn)
        
        return footer
    
    def _setup_animations(self):
        """Setup animations."""
        # Slide animation for position changes
        self.slide_animation = QPropertyAnimation(self, b"pos")
        self.slide_animation.setDuration(300)
        self.slide_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Fade animation
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(200)
        self.fade_animation.setEasingCurve(QEasingCurve.InOutQuad)
    
    def _setup_glow(self):
        """Setup glow/shadow effect."""
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(self.colors.border)
        shadow.setOffset(0, 0)
        self.setGraphicsEffect(shadow)
    
    def paintEvent(self, event):
        """Custom paint - rounded rect with gradient border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect().adjusted(5, 5, -5, -5)
        
        # Background
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        
        bg_color = QColor(self.colors.background)
        bg_color.setAlpha(200)
        painter.fillPath(path, QBrush(bg_color))
        
        # Gradient border
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, self.colors.border)
        gradient.setColorAt(0.5, QColor(0, 100, 200, 200))
        gradient.setColorAt(1, self.colors.border)
        
        pen = QPen(QBrush(gradient), 2)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 10, 10)
    
    # --- Public API ---
    
    def show_results(self, results: List[Dict[str, Any]], title: str = "SONUÇLAR"):
        """Show a list of results (thread-safe).
        
        Args:
            results: List of result dicts with keys: title, source, time, snippet, url
            title: Header title
        """
        self.signals.show_results_signal.emit(results, title)
    
    def _show_results_internal(self, results: List[Dict[str, Any]], title: str):
        """Internal method to show results."""
        self._current_title = title
        self.title_label.setText(f"🔍 {title}")
        
        # Clear existing content
        self._clear_content()
        
        # Add result items
        for i, item in enumerate(results):
            item_widget = self._create_result_item(i + 1, item)
            self.content_layout.addWidget(item_widget)
        
        # Add stretch at end
        self.content_layout.addStretch()
        
        # Update pagination
        self._update_pagination(1, 1)
        
        # Show with animation
        self._fade_in()
    
    def show_summary(self, summary: Dict[str, Any]):
        """Show a summary (thread-safe).
        
        Args:
            summary: Dict with keys: title, summary, key_points, source_url
        """
        self.signals.show_summary_signal.emit(summary)
    
    def _show_summary_internal(self, summary: Dict[str, Any]):
        """Internal method to show summary."""
        self.title_label.setText("📖 ÖZET")
        
        # Clear existing content
        self._clear_content()
        
        # Title
        if summary.get("title"):
            title_label = QLabel(summary["title"])
            title_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
            title_label.setStyleSheet(f"color: {self.colors.accent.name()};")
            title_label.setWordWrap(True)
            self.content_layout.addWidget(title_label)
        
        # Source URL
        if summary.get("source_url"):
            url_label = QLabel(f"🔗 {summary['source_url'][:50]}...")
            url_label.setStyleSheet("color: rgba(255, 255, 255, 120); font-size: 10px;")
            self.content_layout.addWidget(url_label)
        
        # Spacer
        self.content_layout.addSpacing(10)
        
        # Summary text
        if summary.get("summary"):
            summary_label = QLabel(summary["summary"])
            summary_label.setStyleSheet(
                f"color: {self.colors.text.name()}; font-size: 12px; line-height: 1.5;"
            )
            summary_label.setWordWrap(True)
            self.content_layout.addWidget(summary_label)
        
        # Key points
        if summary.get("key_points"):
            self.content_layout.addSpacing(15)
            
            points_header = QLabel("📌 Önemli Noktalar:")
            points_header.setFont(QFont("Segoe UI", 11, QFont.Bold))
            points_header.setStyleSheet(f"color: {self.colors.accent.name()};")
            self.content_layout.addWidget(points_header)
            
            for point in summary["key_points"]:
                point_label = QLabel(f"  • {point}")
                point_label.setStyleSheet(
                    f"color: {self.colors.text.name()}; font-size: 11px;"
                )
                point_label.setWordWrap(True)
                self.content_layout.addWidget(point_label)
        
        # Add stretch
        self.content_layout.addStretch()
        
        # Hide pagination for summaries
        self.prev_btn.hide()
        self.page_label.hide()
        self.next_btn.hide()
        self.hint_label.setText('💬 "Daha detaylı anlat" diyebilirsiniz')
        
        # Show with animation
        self._fade_in()
    
    def show_plan(self, plan: Dict[str, Any]):
        """Show a task plan (thread-safe).
        
        Args:
            plan: Dict with keys: title, description, steps, current_step, status, progress_percent
                  Each step has: index, description, status, icon, color
        """
        self.signals.show_plan_signal.emit(plan)
    
    def _show_plan_internal(self, plan: Dict[str, Any]):
        """Internal method to show task plan."""
        self.title_label.setText(f"📋 {plan.get('title', 'GÖREV PLANI')}")
        
        # Clear existing content
        self._clear_content()
        
        # Description (original request)
        if plan.get("description"):
            desc_label = QLabel(f'"{plan["description"]}"')
            desc_label.setStyleSheet(
                f"color: rgba(255, 255, 255, 180); font-style: italic; font-size: 11px;"
            )
            desc_label.setWordWrap(True)
            self.content_layout.addWidget(desc_label)
            self.content_layout.addSpacing(10)
        
        # Progress bar
        progress = plan.get("progress_percent", 0)
        progress_frame = QFrame()
        progress_frame.setFixedHeight(8)
        progress_frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(0, 195, 255, 30);
                border-radius: 4px;
            }}
        """)
        
        # Progress fill (nested frame)
        progress_fill = QFrame(progress_frame)
        fill_width = int(progress_frame.width() * progress / 100) if progress > 0 else 0
        progress_fill.setFixedHeight(8)
        progress_fill.setStyleSheet(f"""
            QFrame {{
                background-color: {self.colors.success.name() if progress == 100 else self.colors.accent.name()};
                border-radius: 4px;
            }}
        """)
        self.content_layout.addWidget(progress_frame)
        self.content_layout.addSpacing(15)
        
        # Separator line
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(0, 195, 255, 50);")
        self.content_layout.addWidget(sep)
        self.content_layout.addSpacing(10)
        
        # Steps
        steps = plan.get("steps", [])
        current_step = plan.get("current_step", 0)
        
        for step in steps:
            step_widget = self._create_plan_step_widget(step, current_step)
            self.content_layout.addWidget(step_widget)
        
        # Add stretch
        self.content_layout.addStretch()
        
        # Footer buttons for plan
        status = plan.get("status", "planning")
        if status == "awaiting_confirmation":
            self.hint_label.setText('💬 "Başla" veya "İptal" diyebilirsiniz')
        elif status == "executing":
            self.hint_label.setText('💬 "Duraklat" veya "Atla" diyebilirsiniz')
        else:
            self.hint_label.setText(f'📊 {plan.get("completed", 0)}/{plan.get("total_steps", len(steps))} adım tamamlandı')
        
        # Hide pagination for plans
        self.prev_btn.hide()
        self.page_label.hide()
        self.next_btn.hide()
        
        # Show with animation
        self._fade_in()
    
    def _create_plan_step_widget(self, step: Dict[str, Any], current_step: int) -> QFrame:
        """Create a single plan step widget."""
        frame = QFrame()
        
        index = step.get("index", 0)
        status = step.get("status", "pending")
        is_current = (index == current_step + 1)
        
        # Style based on status
        if status == "completed":
            bg_color = "rgba(0, 255, 136, 30)"
            border_color = "rgba(0, 255, 136, 80)"
        elif status == "running":
            bg_color = "rgba(255, 215, 0, 40)"
            border_color = "rgba(255, 215, 0, 150)"
        elif status == "failed":
            bg_color = "rgba(255, 68, 68, 30)"
            border_color = "rgba(255, 68, 68, 80)"
        elif status == "skipped":
            bg_color = "rgba(100, 100, 100, 30)"
            border_color = "rgba(100, 100, 100, 80)"
        else:  # pending
            bg_color = "rgba(0, 195, 255, 15)"
            border_color = "rgba(0, 195, 255, 40)"
        
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 6px;
                border: 1px solid {border_color};
                margin: 2px 0;
            }}
        """)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        
        # Status icon
        icon = step.get("icon", "○")
        icon_label = QLabel(icon)
        icon_label.setFixedWidth(20)
        icon_label.setStyleSheet(f"""
            color: {step.get('color', '#888888')};
            font-size: 14px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(icon_label)
        
        # Description
        desc = step.get("description", "")
        desc_label = QLabel(desc)
        desc_label.setStyleSheet(f"""
            color: {self.colors.text.name()};
            font-size: 11px;
            background: transparent;
        """)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label, 1)
        
        # Elapsed time (if completed)
        elapsed = step.get("elapsed_time")
        if elapsed is not None:
            time_label = QLabel(f"{elapsed:.1f}s")
            time_label.setStyleSheet("color: rgba(255, 255, 255, 100); font-size: 10px; background: transparent;")
            layout.addWidget(time_label)
        
        return frame
    
    def move_to_position(self, position: str):
        """Move panel to position (thread-safe).
        
        Args:
            position: Position name (e.g., "right", "sol üst")
        """
        self.signals.move_to_signal.emit(position)
    
    def _move_to_internal(self, position_str: str):
        """Internal method to move panel."""
        # Resolve position
        pos = PANEL_POSITION_ALIASES.get(position_str.lower())
        if pos is None:
            try:
                pos = PanelPosition(position_str.lower())
            except ValueError:
                return
        
        self._position = pos
        
        # Calculate new position
        screen = self.screen().geometry() if self.screen() else QRect(0, 0, 1920, 1080)
        x_ratio, y_ratio = POSITION_RATIOS.get(pos, (0.65, 0.1))
        
        new_x = int(screen.width() * x_ratio)
        new_y = int(screen.height() * y_ratio)
        
        # Animate
        self.slide_animation.setStartValue(self.pos())
        self.slide_animation.setEndValue(QPoint(new_x, new_y))
        self.slide_animation.start()
    
    def toggle_minimize(self):
        """Toggle minimize/restore state."""
        if self._minimized:
            self._restore_from_minimize()
        else:
            self._minimize()
    
    def _minimize(self):
        """Minimize panel - show only header."""
        self._minimized = True
        self.scroll_area.hide()
        self.footer.hide()
        self.separator.hide()
        self.setFixedHeight(55)
        self.minimize_btn.setText("□")
    
    def _restore_from_minimize(self):
        """Restore panel from minimized state."""
        self._minimized = False
        self.scroll_area.show()
        self.footer.show()
        self.separator.show()
        self.setFixedHeight(500)
        self.setMinimumHeight(300)
        self.setMaximumHeight(800)
        self.minimize_btn.setText("─")
    
    def _clear_content(self):
        """Clear all content from content layout."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                pass  # Spacers are automatically cleaned up
    
    def _create_result_item(self, index: int, item: Dict[str, Any]) -> QFrame:
        """Create a single result item widget."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(0, 195, 255, 25);
                border-radius: 8px;
                border: 1px solid rgba(0, 195, 255, 40);
            }}
            QFrame:hover {{
                background-color: rgba(0, 195, 255, 50);
                border: 1px solid rgba(0, 195, 255, 100);
            }}
        """)
        frame.setCursor(QCursor(Qt.PointingHandCursor))
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        
        # Title with index
        title_text = f"{index}. {item.get('title', 'Başlık yok')}"
        title = QLabel(title_text)
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet(f"color: {self.colors.text.name()}; background: transparent;")
        title.setWordWrap(True)
        layout.addWidget(title)
        
        # Source & time
        source = item.get('source', '')
        time = item.get('time', '')
        if source or time:
            meta_parts = [p for p in [source, time] if p]
            meta = QLabel(" • ".join(meta_parts))
            meta.setStyleSheet(
                "color: rgba(255, 255, 255, 120); font-size: 10px; background: transparent;"
            )
            layout.addWidget(meta)
        
        # Snippet
        snippet = item.get('snippet', '')
        if snippet:
            snippet_text = snippet[:120] + "..." if len(snippet) > 120 else snippet
            snippet_label = QLabel(snippet_text)
            snippet_label.setStyleSheet(
                "color: rgba(255, 255, 255, 160); font-size: 10px; background: transparent;"
            )
            snippet_label.setWordWrap(True)
            layout.addWidget(snippet_label)
        
        # Store index for click handling
        frame.setProperty("result_index", index)
        
        # Make clickable
        frame.mousePressEvent = lambda e, idx=index: self.item_clicked.emit(idx)
        
        return frame
    
    def _update_pagination(self, current: int, total: int):
        """Update pagination controls."""
        self.page_label.setText(f"{current}/{total}")
        self.prev_btn.setEnabled(current > 1)
        self.next_btn.setEnabled(current < total)
        
        # Show pagination controls
        self.prev_btn.show()
        self.page_label.show()
        self.next_btn.show()
        self.hint_label.setText('💬 "3. sonucu aç" diyebilirsiniz')
        
        self.page_changed.emit(current, total)
    
    def _on_next_clicked(self):
        """Handle next button click."""
        # Pagination logic will be in controller
        pass
    
    def _on_prev_clicked(self):
        """Handle prev button click."""
        # Pagination logic will be in controller
        pass
    
    def _fade_in(self):
        """Show with fade-in animation."""
        self.setWindowOpacity(0)
        self.show()
        self.raise_()
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
    
    def _fade_out(self):
        """Hide with fade-out animation."""
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.finished.connect(self._on_fade_out_done)
        self.fade_animation.start()
    
    def _on_fade_out_done(self):
        """Called when fade out completes."""
        self.hide()
        try:
            self.fade_animation.finished.disconnect(self._on_fade_out_done)
        except:
            pass
    
    def _do_show(self):
        """Thread-safe show."""
        self._fade_in()
    
    def _do_hide(self):
        """Thread-safe hide."""
        self._fade_out()
        self.panel_closed.emit()
    
    # --- Drag Support ---
    
    def mousePressEvent(self, event):
        """Start dragging on left click."""
        if event.button() == Qt.LeftButton:
            # Only start drag if clicking on header area
            if event.pos().y() < 55:
                self._dragging = True
                self._drag_position = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle drag movement."""
        if self._dragging:
            self.move(event.globalPos() - self._drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """End dragging."""
        self._dragging = False


class JarvisPanelController:
    """Controller for JarvisPanel with pagination and command integration.
    
    Manages:
    - Result list pagination
    - Position control
    - Integration with router commands
    - State persistence
    """
    
    def __init__(self, panel: JarvisPanel, items_per_page: int = 5):
        self.panel = panel
        self.items_per_page = items_per_page
        
        # State
        self._results: List[Dict[str, Any]] = []
        self._current_page = 0
        self._title = "SONUÇLAR"
        
        # Connect signals
        self.panel.item_clicked.connect(self._on_item_clicked)
    
    @property
    def total_pages(self) -> int:
        """Calculate total pages."""
        if not self._results:
            return 1
        return max(1, (len(self._results) + self.items_per_page - 1) // self.items_per_page)
    
    @property
    def current_page(self) -> int:
        """Get current page (1-indexed)."""
        return self._current_page + 1
    
    def show_results(self, results: List[Dict[str, Any]], title: str = "SONUÇLAR"):
        """Show results with pagination.
        
        Args:
            results: List of result dicts
            title: Panel title
        """
        self._results = results
        self._current_page = 0
        self._title = title
        self._update_display()
    
    def show_summary(self, summary: Dict[str, Any]):
        """Show a summary."""
        self._results = []
        self.panel.show_summary(summary)
    
    def show_plan(self, plan):
        """Show a task plan.
        
        Args:
            plan: PlanDisplay object or dict with plan data
        """
        self._results = []
        
        # Convert PlanDisplay to dict if needed
        if hasattr(plan, "__dict__"):
            plan_dict = {
                "id": getattr(plan, "id", ""),
                "title": getattr(plan, "title", "GÖREV PLANI"),
                "description": getattr(plan, "description", ""),
                "steps": [
                    {
                        "index": getattr(s, "index", i + 1),
                        "description": getattr(s, "description", ""),
                        "status": getattr(s, "status", "pending"),
                        "icon": getattr(s, "icon", "○"),
                        "color": getattr(s, "color", "#888888"),
                        "elapsed_time": getattr(s, "elapsed_time", None),
                    }
                    for i, s in enumerate(getattr(plan, "steps", []))
                ],
                "current_step": getattr(plan, "current_step", 0),
                "total_steps": getattr(plan, "total_steps", 0),
                "status": getattr(plan, "status", "planning"),
                "progress_percent": getattr(plan, "progress_percent", 0),
            }
        else:
            plan_dict = plan
        
        self.panel.show_plan(plan_dict)
    
    def next_page(self):
        """Go to next page."""
        if self._current_page < self.total_pages - 1:
            self._current_page += 1
            self._update_display()
    
    def prev_page(self):
        """Go to previous page."""
        if self._current_page > 0:
            self._current_page -= 1
            self._update_display()
    
    def move_panel(self, position: str):
        """Move panel to position."""
        self.panel.move_to_position(position)
    
    def show_panel(self):
        """Show the panel."""
        self.panel.signals.show_signal.emit()
    
    def hide_panel(self):
        """Hide the panel."""
        self.panel.signals.hide_signal.emit()
    
    def minimize_panel(self):
        """Minimize the panel."""
        self.panel.signals.minimize_signal.emit()
    
    def maximize_panel(self):
        """Maximize the panel."""
        self.panel.signals.maximize_signal.emit()
    
    def get_item_by_index(self, index: int) -> Optional[Dict[str, Any]]:
        """Get result item by 1-indexed index."""
        if 1 <= index <= len(self._results):
            return self._results[index - 1]
        return None
    
    def _update_display(self):
        """Update panel display with current page items."""
        if not self._results:
            return
        
        # Calculate slice
        start = self._current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self._results[start:end]
        
        # Re-index items for display
        display_items = []
        for i, item in enumerate(page_items):
            display_item = dict(item)
            display_item["_global_index"] = start + i + 1
            display_items.append(display_item)
        
        # Show on panel
        self.panel._show_results_internal(display_items, self._title)
        self.panel._update_pagination(self.current_page, self.total_pages)
    
    def _on_item_clicked(self, index: int):
        """Handle item click."""
        # Index is from display (1-indexed within page)
        # Convert to global index
        global_index = self._current_page * self.items_per_page + index
        item = self.get_item_by_index(global_index)
        if item:
            # Could emit signal or callback here
            pass


def create_jarvis_panel(
    theme: Optional[OverlayTheme] = None,
) -> tuple[JarvisPanel, JarvisPanelController]:
    """Factory function to create panel with controller.
    
    Args:
        theme: Optional theme (defaults to JARVIS_THEME)
    
    Returns:
        Tuple of (JarvisPanel, JarvisPanelController)
    """
    panel = JarvisPanel(theme=theme or JARVIS_THEME)
    controller = JarvisPanelController(panel)
    return panel, controller


# --- Mock for Testing ---

class MockJarvisPanel:
    """Mock panel for testing without Qt."""
    
    def __init__(self):
        self._visible = False
        self._minimized = False
        self._position = PanelPosition.RIGHT
        self._results: List[Dict[str, Any]] = []
        self._summary: Optional[Dict[str, Any]] = None
        self._title = "SONUÇLAR"
    
    def show_results(self, results: List[Dict[str, Any]], title: str = "SONUÇLAR"):
        self._results = results
        self._title = title
        self._visible = True
        self._summary = None
    
    def show_summary(self, summary: Dict[str, Any]):
        self._summary = summary
        self._results = []
        self._visible = True
    
    def move_to_position(self, position: str):
        pos = PANEL_POSITION_ALIASES.get(position.lower())
        if pos:
            self._position = pos
    
    def toggle_minimize(self):
        self._minimized = not self._minimized
    
    def show(self):
        self._visible = True
    
    def hide(self):
        self._visible = False
    
    @property
    def is_visible(self) -> bool:
        return self._visible
    
    @property
    def is_minimized(self) -> bool:
        return self._minimized
    
    @property
    def position(self) -> PanelPosition:
        return self._position


class MockJarvisPanelController:
    """Mock controller for testing."""
    
    def __init__(self, panel: Optional[MockJarvisPanel] = None):
        self.panel = panel or MockJarvisPanel()
        self._results: List[Dict[str, Any]] = []
        self._current_page = 0
        self.items_per_page = 5
        self._current_plan: Optional[Dict[str, Any]] = None
    
    @property
    def total_pages(self) -> int:
        if not self._results:
            return 1
        return max(1, (len(self._results) + self.items_per_page - 1) // self.items_per_page)
    
    @property
    def current_page(self) -> int:
        return self._current_page + 1
    
    def show_results(self, results: List[Dict[str, Any]], title: str = "SONUÇLAR"):
        self._results = results
        self._current_page = 0
        self._current_plan = None
        self.panel.show_results(results[:self.items_per_page], title)
    
    def show_summary(self, summary: Dict[str, Any]):
        self._results = []
        self._current_plan = None
        self.panel.show_summary(summary)
    
    def show_plan(self, plan):
        """Show a task plan.
        
        Args:
            plan: PlanDisplay object or dict with plan data
        """
        self._results = []
        
        # Convert PlanDisplay to dict if needed
        if hasattr(plan, "__dict__"):
            plan_dict = {
                "id": getattr(plan, "id", ""),
                "title": getattr(plan, "title", "GÖREV PLANI"),
                "description": getattr(plan, "description", ""),
                "steps": [
                    {
                        "index": getattr(s, "index", i + 1),
                        "description": getattr(s, "description", ""),
                        "status": getattr(s, "status", "pending"),
                        "icon": getattr(s, "icon", "○"),
                        "color": getattr(s, "color", "#888888"),
                    }
                    for i, s in enumerate(getattr(plan, "steps", []))
                ],
                "current_step": getattr(plan, "current_step", 0),
                "total_steps": getattr(plan, "total_steps", 0),
                "status": getattr(plan, "status", "planning"),
                "progress_percent": getattr(plan, "progress_percent", 0),
            }
        else:
            plan_dict = plan
        
        self._current_plan = plan_dict
        self.panel._visible = True
    
    @property
    def current_plan(self) -> Optional[Dict[str, Any]]:
        return self._current_plan
    
    def next_page(self):
        if self._current_page < self.total_pages - 1:
            self._current_page += 1
    
    def prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
    
    def move_panel(self, position: str):
        self.panel.move_to_position(position)
    
    def show_panel(self):
        self.panel.show()
    
    def hide_panel(self):
        self.panel.hide()
    
    def minimize_panel(self):
        self.panel.toggle_minimize()
    
    def get_item_by_index(self, index: int) -> Optional[Dict[str, Any]]:
        if 1 <= index <= len(self._results):
            return self._results[index - 1]
        return None
