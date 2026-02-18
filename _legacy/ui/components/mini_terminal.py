"""Compact terminal output display widget (Issue #5).

Shows terminal command output in a mini console view.
"""
from __future__ import annotations

from collections import deque
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QTextCursor

from ..themes import OverlayTheme, JARVIS_THEME


class OutputType(Enum):
    """Terminal output types."""
    STDOUT = "stdout"
    STDERR = "stderr"
    COMMAND = "command"
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class OutputLine:
    """A single line of terminal output."""
    text: str
    output_type: OutputType = OutputType.STDOUT
    timestamp: Optional[float] = None


class MiniTerminalWidget(QWidget):
    """Compact terminal output display.
    
    Shows recent terminal output with:
    - Command highlighting
    - Stdout/stderr differentiation
    - Auto-scroll
    - Line limit for performance
    
    Signals:
        line_added: Emitted when a line is added
        cleared: Emitted when terminal is cleared
    """
    
    line_added = pyqtSignal(str)
    cleared = pyqtSignal()
    
    def __init__(
        self,
        max_lines: int = 8,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.max_lines = max_lines
        self.theme = theme or JARVIS_THEME
        self._lines: deque = deque(maxlen=max_lines)
        self._line_widgets: List[QLabel] = []
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        
        # Header
        header = QHBoxLayout()
        header.setSpacing(6)
        
        icon = QLabel("💻")
        icon.setFixedSize(16, 16)
        header.addWidget(icon)
        
        title = QLabel("Terminal")
        title.setStyleSheet(f"""
            QLabel {{
                color: {self.theme.primary};
                font-size: 11px;
                font-weight: bold;
            }}
        """)
        header.addWidget(title)
        header.addStretch()
        
        layout.addLayout(header)
        
        # Separator
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {self.theme.primary}40;")
        layout.addWidget(separator)
        
        # Output container
        self.output_container = QWidget()
        self.output_layout = QVBoxLayout(self.output_container)
        self.output_layout.setContentsMargins(0, 4, 0, 0)
        self.output_layout.setSpacing(2)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.2);
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.3);
                border-radius: 3px;
                min-height: 20px;
            }
        """)
        scroll.setWidget(self.output_container)
        self._scroll_area = scroll
        
        layout.addWidget(scroll)
        
        # Monospace font for output
        self._mono_font = QFont("Consolas", 10)
        if not self._mono_font.exactMatch():
            self._mono_font = QFont("Courier New", 10)
    
    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────
    
    def add_line(self, text: str, output_type: OutputType = OutputType.STDOUT):
        """Add a line of output.
        
        Args:
            text: Output text
            output_type: Type of output (affects styling)
        """
        line = OutputLine(text=text, output_type=output_type)
        self._lines.append(line)
        self._refresh_display()
        self.line_added.emit(text)
    
    def add_command(self, command: str):
        """Add a command line (with $ prefix)."""
        self.add_line(f"$ {command}", OutputType.COMMAND)
    
    def add_stdout(self, text: str):
        """Add stdout output."""
        for line in text.split('\n'):
            if line.strip():
                self.add_line(line, OutputType.STDOUT)
    
    def add_stderr(self, text: str):
        """Add stderr output."""
        for line in text.split('\n'):
            if line.strip():
                self.add_line(line, OutputType.STDERR)
    
    def add_info(self, text: str):
        """Add info message."""
        self.add_line(text, OutputType.INFO)
    
    def add_success(self, text: str):
        """Add success message."""
        self.add_line(text, OutputType.SUCCESS)
    
    def add_error(self, text: str):
        """Add error message."""
        self.add_line(text, OutputType.ERROR)
    
    def add_output(self, stdout: str, stderr: str = ""):
        """Add combined output from a command."""
        if stdout:
            self.add_stdout(stdout)
        if stderr:
            self.add_stderr(stderr)
    
    def clear(self):
        """Clear all output."""
        self._lines.clear()
        self._clear_widgets()
        self.cleared.emit()
    
    def set_max_lines(self, max_lines: int):
        """Set maximum number of lines to display."""
        self.max_lines = max_lines
        new_lines = deque(self._lines, maxlen=max_lines)
        self._lines = new_lines
        self._refresh_display()
    
    # ─────────────────────────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────────────────────────
    
    def _refresh_display(self):
        """Refresh the display with current lines."""
        self._clear_widgets()
        
        for line in self._lines:
            widget = self._create_line_widget(line)
            self.output_layout.addWidget(widget)
            self._line_widgets.append(widget)
        
        self.output_layout.addStretch()
        
        # Auto-scroll to bottom
        QTimer.singleShot(10, self._scroll_to_bottom)
    
    def _clear_widgets(self):
        """Remove all line widgets."""
        for widget in self._line_widgets:
            self.output_layout.removeWidget(widget)
            widget.deleteLater()
        self._line_widgets.clear()
        
        # Remove stretch if exists
        while self.output_layout.count():
            item = self.output_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _create_line_widget(self, line: OutputLine) -> QLabel:
        """Create a label for a line of output."""
        label = QLabel(line.text)
        label.setFont(self._mono_font)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Style based on output type
        color = self._get_color_for_type(line.output_type)
        prefix = self._get_prefix_for_type(line.output_type)
        
        label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                padding: 2px 0;
            }}
        """)
        
        if prefix and not line.text.startswith(prefix):
            label.setText(f"{prefix}{line.text}")
        
        return label
    
    def _get_color_for_type(self, output_type: OutputType) -> str:
        """Get color for output type."""
        colors = {
            OutputType.STDOUT: self.theme.text,
            OutputType.STDERR: self.theme.error,
            OutputType.COMMAND: self.theme.primary,
            OutputType.INFO: self.theme.text_secondary,
            OutputType.SUCCESS: self.theme.success,
            OutputType.ERROR: self.theme.error,
        }
        return colors.get(output_type, self.theme.text)
    
    def _get_prefix_for_type(self, output_type: OutputType) -> str:
        """Get prefix for output type."""
        prefixes = {
            OutputType.INFO: "ℹ️ ",
            OutputType.SUCCESS: "✅ ",
            OutputType.ERROR: "❌ ",
        }
        return prefixes.get(output_type, "")
    
    def _scroll_to_bottom(self):
        """Scroll to the bottom of the output."""
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme colors."""
        self.theme = theme
        self._refresh_display()


class CollapsibleTerminal(MiniTerminalWidget):
    """Mini terminal that can be collapsed/expanded."""
    
    collapsed_changed = pyqtSignal(bool)
    
    def __init__(
        self,
        max_lines: int = 8,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(max_lines, theme, parent)
        self._collapsed = False
        self._expanded_height = None
    
    def toggle_collapsed(self):
        """Toggle collapsed state."""
        self.set_collapsed(not self._collapsed)
    
    def set_collapsed(self, collapsed: bool):
        """Set collapsed state."""
        if self._collapsed == collapsed:
            return
        
        self._collapsed = collapsed
        
        if collapsed:
            self._expanded_height = self.height()
            self._scroll_area.hide()
            self.setFixedHeight(30)  # Just header
        else:
            self._scroll_area.show()
            if self._expanded_height:
                self.setFixedHeight(self._expanded_height)
            else:
                self.setMinimumHeight(100)
        
        self.collapsed_changed.emit(collapsed)
    
    def is_collapsed(self) -> bool:
        """Check if collapsed."""
        return self._collapsed
