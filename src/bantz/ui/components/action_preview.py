"""Action preview widget with progress bar (Issue #5).

Shows current/upcoming action with step progress indicator.
"""
from __future__ import annotations

from typing import Optional, List
from enum import Enum

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush

from ..themes import OverlayTheme, JARVIS_THEME


class ActionStatus(Enum):
    """Action step status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionPreviewWidget(QWidget):
    """Display current action with progress.
    
    Shows:
    - Action description/intent
    - Current step indicator
    - Progress bar
    - Step status icons
    
    Signals:
        action_completed: Emitted when action completes
        step_changed: Emitted when step changes (step_num, total)
    """
    
    action_completed = pyqtSignal()
    step_changed = pyqtSignal(int, int)  # current, total
    
    def __init__(
        self,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        
        self.theme = theme or JARVIS_THEME
        
        # State
        self._action_text = ""
        self._steps: List[str] = []
        self._current_step = 0
        self._step_statuses: List[ActionStatus] = []
        self._progress = 0.0
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        
        # Action header with icon
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        
        self.icon_label = QLabel("🎯")
        self.icon_label.setFixedSize(20, 20)
        header_layout.addWidget(self.icon_label)
        
        self.action_label = QLabel("Bekliyor...")
        self.action_label.setWordWrap(True)
        self.action_label.setStyleSheet(f"""
            QLabel {{
                color: {self.theme.text};
                font-size: 13px;
                font-weight: 500;
            }}
        """)
        header_layout.addWidget(self.action_label, 1)
        
        layout.addLayout(header_layout)
        
        # Step indicator (dots)
        self.step_container = QWidget()
        self.step_layout = QHBoxLayout(self.step_container)
        self.step_layout.setContentsMargins(0, 4, 0, 4)
        self.step_layout.setSpacing(8)
        self._step_dots: List[QLabel] = []
        layout.addWidget(self.step_container)
        
        # Progress bar
        self.progress_bar = JarvisProgressBar(theme=self.theme)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)
        
        # Step description
        self.step_label = QLabel("")
        self.step_label.setStyleSheet(f"""
            QLabel {{
                color: {self.theme.text_secondary};
                font-size: 11px;
                font-style: italic;
            }}
        """)
        layout.addWidget(self.step_label)
        
        self.setLayout(layout)
    
    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────
    
    def set_action(self, description: str, steps: Optional[List[str]] = None):
        """Set the current action.
        
        Args:
            description: Main action description
            steps: Optional list of step descriptions
        """
        self._action_text = description
        self._steps = steps or []
        self._current_step = 0
        self._step_statuses = [ActionStatus.PENDING] * len(self._steps)
        self._progress = 0.0
        
        self.action_label.setText(description)
        self._update_step_dots()
        self._update_step_label()
        self.progress_bar.setValue(0)
        
        self.show()
    
    def set_step(self, step: int, status: ActionStatus = ActionStatus.RUNNING):
        """Set current step.
        
        Args:
            step: Step index (0-based)
            status: Status of the step
        """
        if 0 <= step < len(self._steps):
            self._current_step = step
            self._step_statuses[step] = status
            
            # Calculate progress
            if self._steps:
                self._progress = (step + (0.5 if status == ActionStatus.RUNNING else 1)) / len(self._steps)
                self.progress_bar.setValue(int(self._progress * 100))
            
            self._update_step_dots()
            self._update_step_label()
            self.step_changed.emit(step + 1, len(self._steps))
    
    def advance_step(self):
        """Advance to the next step."""
        if self._current_step < len(self._steps):
            # Mark current as completed
            self._step_statuses[self._current_step] = ActionStatus.COMPLETED
            
            if self._current_step + 1 < len(self._steps):
                self.set_step(self._current_step + 1)
            else:
                # All steps completed
                self._progress = 1.0
                self.progress_bar.setValue(100)
                self._update_step_dots()
                self.action_completed.emit()
    
    def set_step_status(self, step: int, status: ActionStatus):
        """Set status for a specific step."""
        if 0 <= step < len(self._step_statuses):
            self._step_statuses[step] = status
            self._update_step_dots()
    
    def set_progress(self, progress: float):
        """Set progress directly (0.0 to 1.0)."""
        self._progress = max(0.0, min(1.0, progress))
        self.progress_bar.setValue(int(self._progress * 100))
    
    def complete(self, success: bool = True):
        """Mark action as completed."""
        self._progress = 1.0
        self.progress_bar.setValue(100)
        
        if success:
            self.icon_label.setText("✅")
            for i in range(len(self._step_statuses)):
                if self._step_statuses[i] == ActionStatus.PENDING:
                    self._step_statuses[i] = ActionStatus.COMPLETED
        else:
            self.icon_label.setText("❌")
            if self._current_step < len(self._step_statuses):
                self._step_statuses[self._current_step] = ActionStatus.FAILED
        
        self._update_step_dots()
        self.action_completed.emit()
    
    def reset(self):
        """Reset to initial state."""
        self._action_text = ""
        self._steps = []
        self._current_step = 0
        self._step_statuses = []
        self._progress = 0.0
        
        self.icon_label.setText("🎯")
        self.action_label.setText("Bekliyor...")
        self.step_label.setText("")
        self.progress_bar.setValue(0)
        self._clear_step_dots()
    
    # ─────────────────────────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────────────────────────
    
    def _update_step_dots(self):
        """Update step indicator dots."""
        self._clear_step_dots()
        
        if not self._steps:
            return
        
        for i, status in enumerate(self._step_statuses):
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setAlignment(Qt.AlignCenter)
            
            if status == ActionStatus.COMPLETED:
                dot.setText("●")
                dot.setStyleSheet(f"color: {self.theme.success};")
            elif status == ActionStatus.RUNNING:
                dot.setText("◉")
                dot.setStyleSheet(f"color: {self.theme.primary};")
            elif status == ActionStatus.FAILED:
                dot.setText("●")
                dot.setStyleSheet(f"color: {self.theme.error};")
            else:  # PENDING, SKIPPED
                dot.setText("○")
                dot.setStyleSheet(f"color: {self.theme.text_secondary};")
            
            self.step_layout.addWidget(dot)
            self._step_dots.append(dot)
        
        self.step_layout.addStretch()
    
    def _clear_step_dots(self):
        """Remove all step dots."""
        for dot in self._step_dots:
            self.step_layout.removeWidget(dot)
            dot.deleteLater()
        self._step_dots.clear()
    
    def _update_step_label(self):
        """Update step description label."""
        if self._steps and 0 <= self._current_step < len(self._steps):
            step_text = f"Adım {self._current_step + 1}/{len(self._steps)}: {self._steps[self._current_step]}"
            self.step_label.setText(step_text)
        else:
            self.step_label.setText("")
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme colors."""
        self.theme = theme
        self.progress_bar.set_theme(theme)
        
        self.action_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.text};
                font-size: 13px;
                font-weight: 500;
            }}
        """)
        self.step_label.setStyleSheet(f"""
            QLabel {{
                color: {theme.text_secondary};
                font-size: 11px;
                font-style: italic;
            }}
        """)
        self._update_step_dots()


class JarvisProgressBar(QWidget):
    """Jarvis-style progress bar with glow effect."""
    
    def __init__(
        self,
        theme: Optional[OverlayTheme] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.theme = theme or JARVIS_THEME
        self._value = 0  # 0-100
        self.setAttribute(Qt.WA_TranslucentBackground)
    
    def setValue(self, value: int):
        """Set progress value (0-100)."""
        self._value = max(0, min(100, value))
        self.update()
    
    def value(self) -> int:
        """Get current value."""
        return self._value
    
    def set_theme(self, theme: OverlayTheme):
        """Update theme."""
        self.theme = theme
        self.update()
    
    def paintEvent(self, event):
        """Draw the progress bar."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background
        bg_color = QColor(self.theme.background)
        bg_color.setAlpha(100)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(self.rect(), 3, 3)
        
        # Progress fill
        if self._value > 0:
            fill_width = int(self.width() * self._value / 100)
            fill_rect = self.rect()
            fill_rect.setWidth(fill_width)
            
            # Gradient fill
            primary = QColor(self.theme.primary)
            secondary = QColor(self.theme.secondary)
            
            painter.setBrush(primary)
            painter.drawRoundedRect(fill_rect, 3, 3)
            
            # Glow on top
            glow = QColor(self.theme.primary)
            glow.setAlpha(80)
            painter.setBrush(glow)
            glow_rect = fill_rect
            glow_rect.setHeight(glow_rect.height() // 2)
            painter.drawRoundedRect(glow_rect, 3, 3)
