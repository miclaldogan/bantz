"""Progress Tracker for multi-step task visualization (Issue #7).

Provides visual progress tracking for complex tasks:
- Step circles with status colors
- Progress bar with percentage
- Current step description
- Animated transitions
- Multiple visual styles
- Time estimation
"""
from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Tuple, Dict, Callable

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QSizePolicy, QGraphicsDropShadowEffect, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QPropertyAnimation,
    QEasingCurve, pyqtSignal, QSequentialAnimationGroup,
    QParallelAnimationGroup
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QPen, QBrush, QColor, QImage,
    QPainterPath, QFont, QLinearGradient, QRadialGradient
)


class StepStatus(Enum):
    """Status of a task step."""
    PENDING = auto()      # Not started yet
    RUNNING = auto()      # Currently executing
    COMPLETED = auto()    # Successfully done
    FAILED = auto()       # Error occurred
    SKIPPED = auto()      # Skipped
    WAITING = auto()      # Waiting for input/condition
    
    @property
    def color(self) -> str:
        """Get status color."""
        colors = {
            StepStatus.PENDING: "#666666",
            StepStatus.RUNNING: "#00D4FF",
            StepStatus.COMPLETED: "#00FF88",
            StepStatus.FAILED: "#FF4444",
            StepStatus.SKIPPED: "#888888",
            StepStatus.WAITING: "#FFB800",
        }
        return colors.get(self, "#666666")
    
    @property
    def icon(self) -> str:
        """Get status icon/symbol."""
        icons = {
            StepStatus.PENDING: "○",
            StepStatus.RUNNING: "◉",
            StepStatus.COMPLETED: "✓",
            StepStatus.FAILED: "✗",
            StepStatus.SKIPPED: "⊘",
            StepStatus.WAITING: "◎",
        }
        return icons.get(self, "○")


@dataclass
class TaskStep:
    """A single step in a task."""
    description: str
    status: StepStatus = StepStatus.PENDING
    details: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    progress: float = 0.0  # 0.0 to 1.0 for sub-progress
    error_message: Optional[str] = None
    
    @property
    def duration(self) -> Optional[float]:
        """Get step duration in seconds."""
        if self.start_time is None:
            return None
        end = self.end_time or time.time()
        return end - self.start_time
    
    @property
    def is_complete(self) -> bool:
        """Check if step is in a terminal state."""
        return self.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)
    
    def start(self):
        """Mark step as running."""
        self.status = StepStatus.RUNNING
        self.start_time = time.time()
    
    def complete(self, success: bool = True, error: str = None):
        """Mark step as complete."""
        self.status = StepStatus.COMPLETED if success else StepStatus.FAILED
        self.end_time = time.time()
        self.progress = 1.0 if success else self.progress
        if error:
            self.error_message = error
    
    def skip(self):
        """Mark step as skipped."""
        self.status = StepStatus.SKIPPED
        self.end_time = time.time()


class ProgressStyle(Enum):
    """Visual styles for progress tracker."""
    CIRCLES = auto()      # Connected circles
    CHEVRONS = auto()     # Arrow-style steps
    MINIMAL = auto()      # Simple line with dots
    DETAILED = auto()     # Full info per step
    COMPACT = auto()      # Single line


class ProgressTracker(QWidget):
    """Visual progress for multi-step tasks.
    
    Features:
    - Step circles with connecting lines
    - Status colors and icons
    - Progress percentage
    - Current step highlighting
    - Time tracking
    - Animated transitions
    - Multiple visual styles
    """
    
    # Signals
    step_started = pyqtSignal(int, str)  # index, description
    step_completed = pyqtSignal(int, bool)  # index, success
    task_completed = pyqtSignal(bool)  # success
    
    # Style constants
    CIRCLE_RADIUS = 12
    LINE_LENGTH = 40
    PADDING = 20
    
    def __init__(
        self,
        parent: QWidget = None,
        style: ProgressStyle = ProgressStyle.CIRCLES
    ):
        super().__init__(parent)
        
        # State
        self._steps: List[TaskStep] = []
        self._current_step = -1
        self._task_description = ""
        self._style = style
        self._start_time: Optional[float] = None
        
        # Animation
        self._animation_phase = 0.0
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._on_animation_tick)
        
        # Setup UI
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup widget UI."""
        self.setMinimumHeight(80)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        
        # Style
        self.setStyleSheet("""
            ProgressTracker {
                background-color: rgba(10, 10, 26, 0.9);
                border: 1px solid #00D4FF;
                border-radius: 8px;
            }
        """)
        
        # Drop shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 212, 255, 80))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.PADDING, 10, self.PADDING, 10)
        layout.setSpacing(8)
        
        # Task description label
        self._task_label = QLabel()
        self._task_label.setStyleSheet("""
            QLabel {
                color: #00D4FF;
                font-size: 12px;
                font-weight: bold;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        layout.addWidget(self._task_label)
        
        # Progress area (custom paint)
        self._progress_area = QFrame()
        self._progress_area.setMinimumHeight(40)
        layout.addWidget(self._progress_area)
        
        # Status bar (percentage + time)
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self._percent_label = QLabel("0%")
        self._percent_label.setStyleSheet("""
            QLabel {
                color: #00FF88;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        status_layout.addWidget(self._percent_label)
        
        status_layout.addStretch()
        
        self._time_label = QLabel("")
        self._time_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        status_layout.addWidget(self._time_label)
        
        layout.addLayout(status_layout)
    
    # === Public API ===
    
    def set_task(self, description: str, steps: List[str]):
        """Set new task with steps.
        
        Args:
            description: Task description
            steps: List of step descriptions
        """
        self._task_description = description
        self._steps = [TaskStep(description=s) for s in steps]
        self._current_step = -1
        self._start_time = None
        
        self._task_label.setText(description)
        self._update_display()
        self.update()
    
    def start_task(self):
        """Start the task (begin first step)."""
        self._start_time = time.time()
        if self._steps:
            self.advance()
    
    def advance(self):
        """Move to next step."""
        if self._current_step >= 0 and self._current_step < len(self._steps):
            # Complete current step
            self._steps[self._current_step].complete(success=True)
            self.step_completed.emit(self._current_step, True)
        
        self._current_step += 1
        
        if self._current_step < len(self._steps):
            # Start new step
            self._steps[self._current_step].start()
            self.step_started.emit(
                self._current_step,
                self._steps[self._current_step].description
            )
            self._start_animation()
        else:
            # Task complete
            self._stop_animation()
            self.task_completed.emit(True)
        
        self._update_display()
        self.update()
    
    def set_step_status(self, index: int, status: StepStatus, error: str = None):
        """Update step status.
        
        Args:
            index: Step index
            status: New status
            error: Error message if failed
        """
        if 0 <= index < len(self._steps):
            step = self._steps[index]
            step.status = status
            if error:
                step.error_message = error
            if status == StepStatus.RUNNING:
                step.start_time = time.time()
            elif step.is_complete:
                step.end_time = time.time()
            
            self._update_display()
            self.update()
    
    def set_step_progress(self, index: int, progress: float):
        """Set sub-progress for a step.
        
        Args:
            index: Step index
            progress: Progress 0.0 to 1.0
        """
        if 0 <= index < len(self._steps):
            self._steps[index].progress = max(0.0, min(1.0, progress))
            self._update_display()
            self.update()
    
    def fail_current_step(self, error: str = None):
        """Mark current step as failed.
        
        Args:
            error: Error message
        """
        if 0 <= self._current_step < len(self._steps):
            self._steps[self._current_step].complete(success=False, error=error)
            self.step_completed.emit(self._current_step, False)
            self._stop_animation()
            self.task_completed.emit(False)
            self._update_display()
            self.update()
    
    def skip_step(self, index: int = None):
        """Skip a step.
        
        Args:
            index: Step index (None = current)
        """
        idx = index if index is not None else self._current_step
        if 0 <= idx < len(self._steps):
            self._steps[idx].skip()
            self._update_display()
            self.update()
    
    def reset(self):
        """Reset all steps to pending."""
        for step in self._steps:
            step.status = StepStatus.PENDING
            step.start_time = None
            step.end_time = None
            step.progress = 0.0
            step.error_message = None
        self._current_step = -1
        self._start_time = None
        self._stop_animation()
        self._update_display()
        self.update()
    
    def get_progress_percent(self) -> float:
        """Get overall progress percentage."""
        if not self._steps:
            return 0.0
        
        total = 0.0
        for step in self._steps:
            if step.status == StepStatus.COMPLETED:
                total += 1.0
            elif step.status == StepStatus.RUNNING:
                total += step.progress
            elif step.status == StepStatus.SKIPPED:
                total += 1.0  # Count skipped as done
        
        return (total / len(self._steps)) * 100
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since task started."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time
    
    @property
    def current_step(self) -> int:
        """Get current step index."""
        return self._current_step
    
    @property
    def step_count(self) -> int:
        """Get total number of steps."""
        return len(self._steps)
    
    @property
    def is_complete(self) -> bool:
        """Check if task is complete."""
        return all(s.is_complete for s in self._steps) if self._steps else False
    
    @property
    def is_running(self) -> bool:
        """Check if task is running."""
        return any(s.status == StepStatus.RUNNING for s in self._steps)
    
    # === Internal Methods ===
    
    def _update_display(self):
        """Update display labels."""
        percent = self.get_progress_percent()
        self._percent_label.setText(f"{percent:.0f}%")
        
        # Color based on status
        if any(s.status == StepStatus.FAILED for s in self._steps):
            self._percent_label.setStyleSheet("""
                QLabel {
                    color: #FF4444;
                    font-size: 11px;
                    font-weight: bold;
                    font-family: 'Consolas', 'Monaco', monospace;
                }
            """)
        elif percent >= 100:
            self._percent_label.setStyleSheet("""
                QLabel {
                    color: #00FF88;
                    font-size: 11px;
                    font-weight: bold;
                    font-family: 'Consolas', 'Monaco', monospace;
                }
            """)
        else:
            self._percent_label.setStyleSheet("""
                QLabel {
                    color: #00D4FF;
                    font-size: 11px;
                    font-weight: bold;
                    font-family: 'Consolas', 'Monaco', monospace;
                }
            """)
        
        # Time display
        elapsed = self.get_elapsed_time()
        if elapsed > 0:
            if elapsed < 60:
                time_str = f"{elapsed:.1f}s"
            else:
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                time_str = f"{mins}m {secs}s"
            self._time_label.setText(time_str)
    
    def _start_animation(self):
        """Start progress animation."""
        if not self._animation_timer.isActive():
            self._animation_timer.start(50)  # 20fps
    
    def _stop_animation(self):
        """Stop progress animation."""
        self._animation_timer.stop()
    
    def _on_animation_tick(self):
        """Animation frame callback."""
        self._animation_phase += 0.15
        if self._animation_phase >= 2 * math.pi:
            self._animation_phase = 0
        
        self._update_display()
        self.update()
    
    # === Painting ===
    
    def paintEvent(self, event):
        """Custom paint for progress visualization."""
        super().paintEvent(event)
        
        if not self._steps:
            return
        
        if self._style == ProgressStyle.CIRCLES:
            self._paint_circles()
        elif self._style == ProgressStyle.CHEVRONS:
            self._paint_chevrons()
        elif self._style == ProgressStyle.MINIMAL:
            self._paint_minimal()
        elif self._style == ProgressStyle.DETAILED:
            self._paint_detailed()
        elif self._style == ProgressStyle.COMPACT:
            self._paint_compact()
    
    def _paint_circles(self):
        """Paint circle-style progress."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        area = self._progress_area.geometry()
        
        # Calculate layout
        step_count = len(self._steps)
        total_width = (step_count * self.CIRCLE_RADIUS * 2 + 
                      (step_count - 1) * self.LINE_LENGTH)
        start_x = area.x() + (area.width() - total_width) // 2
        center_y = area.y() + area.height() // 2
        
        # Draw connecting lines first
        for i in range(step_count - 1):
            x1 = start_x + i * (self.CIRCLE_RADIUS * 2 + self.LINE_LENGTH) + self.CIRCLE_RADIUS * 2
            x2 = x1 + self.LINE_LENGTH
            
            # Line color based on completion
            if i < self._current_step:
                color = QColor("#00FF88")
            elif i == self._current_step:
                # Animated gradient for current
                progress = self._steps[i].progress if i < len(self._steps) else 0
                gradient = QLinearGradient(x1, center_y, x2, center_y)
                gradient.setColorAt(0, QColor("#00FF88"))
                gradient.setColorAt(progress, QColor("#00D4FF"))
                gradient.setColorAt(1, QColor("#333333"))
                painter.setPen(QPen(QBrush(gradient), 3))
                painter.drawLine(x1, center_y, x2, center_y)
                continue
            else:
                color = QColor("#333333")
            
            painter.setPen(QPen(color, 3))
            painter.drawLine(x1, center_y, x2, center_y)
        
        # Draw circles
        for i, step in enumerate(self._steps):
            x = start_x + i * (self.CIRCLE_RADIUS * 2 + self.LINE_LENGTH) + self.CIRCLE_RADIUS
            
            color = QColor(step.status.color)
            
            # Running step animation
            if step.status == StepStatus.RUNNING:
                # Pulsing effect
                pulse = 0.7 + 0.3 * math.sin(self._animation_phase)
                painter.setOpacity(pulse)
                
                # Glow
                glow_color = QColor(color)
                glow_color.setAlphaF(0.3)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow_color)
                painter.drawEllipse(
                    QPoint(x, center_y),
                    self.CIRCLE_RADIUS + 8,
                    self.CIRCLE_RADIUS + 8
                )
                painter.setOpacity(1.0)
            
            # Circle fill
            painter.setPen(QPen(color, 2))
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.RUNNING):
                painter.setBrush(color)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
            
            painter.drawEllipse(
                QPoint(x, center_y),
                self.CIRCLE_RADIUS,
                self.CIRCLE_RADIUS
            )
            
            # Status icon
            painter.setPen(QColor("#FFFFFF") if step.status != StepStatus.PENDING else color)
            painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            icon_rect = QRect(
                x - self.CIRCLE_RADIUS,
                center_y - self.CIRCLE_RADIUS,
                self.CIRCLE_RADIUS * 2,
                self.CIRCLE_RADIUS * 2
            )
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, step.status.icon)
        
        painter.end()
    
    def _paint_chevrons(self):
        """Paint chevron-style progress."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        area = self._progress_area.geometry()
        step_count = len(self._steps)
        
        chevron_width = 60
        chevron_height = 30
        overlap = 15
        
        total_width = step_count * chevron_width - (step_count - 1) * overlap
        start_x = area.x() + (area.width() - total_width) // 2
        center_y = area.y() + area.height() // 2
        
        for i, step in enumerate(self._steps):
            x = start_x + i * (chevron_width - overlap)
            
            color = QColor(step.status.color)
            
            # Build chevron path
            path = QPainterPath()
            path.moveTo(x, center_y - chevron_height // 2)
            path.lineTo(x + chevron_width - 10, center_y - chevron_height // 2)
            path.lineTo(x + chevron_width, center_y)
            path.lineTo(x + chevron_width - 10, center_y + chevron_height // 2)
            path.lineTo(x, center_y + chevron_height // 2)
            if i > 0:
                path.lineTo(x + 10, center_y)
            path.closeSubpath()
            
            # Fill
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.RUNNING):
                painter.setBrush(color)
            else:
                painter.setBrush(QColor("#1A1A2E"))
            
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)
            
            # Step number
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            text_rect = QRect(x + 5, center_y - 8, chevron_width - 15, 16)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, str(i + 1))
        
        painter.end()
    
    def _paint_minimal(self):
        """Paint minimal line-style progress."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        area = self._progress_area.geometry()
        
        # Background line
        line_y = area.y() + area.height() // 2
        painter.setPen(QPen(QColor("#333333"), 4))
        painter.drawLine(area.x() + 20, line_y, area.right() - 20, line_y)
        
        # Progress line
        if self._steps:
            progress = self.get_progress_percent() / 100
            progress_width = int((area.width() - 40) * progress)
            
            gradient = QLinearGradient(area.x() + 20, 0, area.x() + 20 + progress_width, 0)
            gradient.setColorAt(0, QColor("#00FF88"))
            gradient.setColorAt(1, QColor("#00D4FF"))
            
            painter.setPen(QPen(QBrush(gradient), 4))
            painter.drawLine(area.x() + 20, line_y, area.x() + 20 + progress_width, line_y)
        
        # Step dots
        step_count = len(self._steps)
        if step_count > 0:
            step_spacing = (area.width() - 40) / max(1, step_count - 1) if step_count > 1 else 0
            
            for i, step in enumerate(self._steps):
                if step_count == 1:
                    x = area.x() + area.width() // 2
                else:
                    x = area.x() + 20 + int(i * step_spacing)
                
                color = QColor(step.status.color)
                
                # Dot
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QPoint(x, line_y), 6, 6)
        
        painter.end()
    
    def _paint_detailed(self):
        """Paint detailed progress with descriptions."""
        self._paint_circles()  # Use circles as base
        
        # Add step descriptions below
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        area = self._progress_area.geometry()
        step_count = len(self._steps)
        
        if step_count == 0:
            painter.end()
            return
        
        total_width = (step_count * self.CIRCLE_RADIUS * 2 + 
                      (step_count - 1) * self.LINE_LENGTH)
        start_x = area.x() + (area.width() - total_width) // 2
        
        painter.setFont(QFont("Consolas", 8))
        
        for i, step in enumerate(self._steps):
            x = start_x + i * (self.CIRCLE_RADIUS * 2 + self.LINE_LENGTH) + self.CIRCLE_RADIUS
            
            # Truncate long descriptions
            desc = step.description[:15] + "..." if len(step.description) > 15 else step.description
            
            color = QColor(step.status.color)
            painter.setPen(color)
            
            text_rect = QRect(
                x - 40,
                area.bottom() - 15,
                80,
                15
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, desc)
        
        painter.end()
    
    def _paint_compact(self):
        """Paint compact single-line progress."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        area = self._progress_area.geometry()
        
        # Single progress bar
        bar_height = 8
        bar_y = area.y() + (area.height() - bar_height) // 2
        bar_rect = QRect(area.x(), bar_y, area.width(), bar_height)
        
        # Background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1A1A2E"))
        painter.drawRoundedRect(bar_rect, 4, 4)
        
        # Progress
        if self._steps:
            progress = self.get_progress_percent() / 100
            progress_width = int(area.width() * progress)
            progress_rect = QRect(area.x(), bar_y, progress_width, bar_height)
            
            gradient = QLinearGradient(0, 0, progress_width, 0)
            gradient.setColorAt(0, QColor("#00FF88"))
            gradient.setColorAt(1, QColor("#00D4FF"))
            
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(progress_rect, 4, 4)
        
        painter.end()


class MiniProgressTracker(ProgressTracker):
    """Compact progress tracker for embedding."""
    
    def __init__(self, parent: QWidget = None):
        super().__init__(parent, style=ProgressStyle.COMPACT)
        self.setMinimumHeight(40)
        self.setMaximumHeight(50)
        
        # Hide some elements
        self._task_label.hide()


def create_progress_tracker(
    style: ProgressStyle = ProgressStyle.CIRCLES,
    parent: QWidget = None
) -> ProgressTracker:
    """Factory function to create ProgressTracker.
    
    Args:
        style: Visual style for progress
        parent: Parent widget
    
    Returns:
        ProgressTracker instance
    """
    return ProgressTracker(parent, style)
