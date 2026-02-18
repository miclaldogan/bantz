"""Streaming Manager - Coordinates all visualization components (Issue #7).

Central manager that:
- Coordinates preview, highlighter, progress, recorder
- Handles action events
- Provides unified API
- Manages resource usage
- Supports event-driven updates
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional, List, Tuple, Dict, Callable, Any
from queue import Queue, Empty

from PyQt5.QtCore import QObject, pyqtSignal, QTimer


class EventType(Enum):
    """Types of action events."""
    # Mouse events
    MOUSE_MOVE = auto()
    MOUSE_CLICK = auto()
    MOUSE_DOUBLE_CLICK = auto()
    MOUSE_DRAG_START = auto()
    MOUSE_DRAG_END = auto()
    MOUSE_SCROLL = auto()
    
    # Keyboard events
    KEY_PRESS = auto()
    KEY_RELEASE = auto()
    KEY_COMBO = auto()
    
    # Element events
    ELEMENT_FOCUS = auto()
    ELEMENT_CLICK = auto()
    ELEMENT_TYPE = auto()
    ELEMENT_SELECT = auto()
    
    # Task events
    TASK_START = auto()
    TASK_STEP_START = auto()
    TASK_STEP_COMPLETE = auto()
    TASK_STEP_FAIL = auto()
    TASK_COMPLETE = auto()
    TASK_FAIL = auto()
    
    # Window events
    WINDOW_FOCUS = auto()
    WINDOW_OPEN = auto()
    WINDOW_CLOSE = auto()
    WINDOW_RESIZE = auto()
    
    # Custom
    ANNOTATION = auto()
    CUSTOM = auto()


@dataclass
class ActionEvent:
    """An action event to visualize."""
    type: EventType
    timestamp: float = field(default_factory=time.time)
    
    # Position data
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    
    # Additional data
    target: Optional[str] = None
    description: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Visualization options
    color: Optional[str] = None
    duration: float = 2.0
    animate: bool = True
    
    @classmethod
    def mouse_click(cls, x: int, y: int, button: str = "left") -> "ActionEvent":
        """Create mouse click event."""
        return cls(
            type=EventType.MOUSE_CLICK,
            x=x, y=y,
            data={"button": button}
        )
    
    @classmethod
    def mouse_move(cls, x: int, y: int) -> "ActionEvent":
        """Create mouse move event."""
        return cls(type=EventType.MOUSE_MOVE, x=x, y=y)
    
    @classmethod
    def element_click(
        cls, x: int, y: int, width: int, height: int,
        target: str = None, description: str = None
    ) -> "ActionEvent":
        """Create element click event."""
        return cls(
            type=EventType.ELEMENT_CLICK,
            x=x, y=y, width=width, height=height,
            target=target, description=description
        )
    
    @classmethod
    def task_start(cls, description: str, steps: List[str]) -> "ActionEvent":
        """Create task start event."""
        return cls(
            type=EventType.TASK_START,
            description=description,
            data={"steps": steps}
        )
    
    @classmethod
    def task_step(cls, index: int, description: str, status: str) -> "ActionEvent":
        """Create task step event."""
        event_type = {
            "start": EventType.TASK_STEP_START,
            "complete": EventType.TASK_STEP_COMPLETE,
            "fail": EventType.TASK_STEP_FAIL,
        }.get(status, EventType.TASK_STEP_START)
        
        return cls(
            type=event_type,
            description=description,
            data={"index": index, "status": status}
        )
    
    @classmethod
    def annotation(cls, text: str, position: str = "bottom") -> "ActionEvent":
        """Create annotation event."""
        return cls(
            type=EventType.ANNOTATION,
            description=text,
            data={"position": position}
        )


@dataclass
class StreamingConfig:
    """Configuration for streaming manager."""
    # Features
    enable_preview: bool = True
    enable_highlighting: bool = True
    enable_progress: bool = True
    enable_recording: bool = False
    
    # Preview settings
    preview_width: int = 320
    preview_height: int = 180
    preview_fps: int = 30
    
    # Highlighting settings
    highlight_color: str = "#00FF00"
    highlight_duration: float = 2.0
    show_click_ripples: bool = True
    show_mouse_trail: bool = False
    
    # Progress settings
    progress_style: str = "circles"  # circles, chevrons, minimal
    
    # Recording settings
    record_fps: int = 20
    record_format: str = "mp4"
    record_path: str = ""
    
    # Performance
    event_queue_size: int = 100
    update_interval_ms: int = 16  # ~60fps
    low_cpu_mode: bool = False


class StreamingSignals(QObject):
    """Thread-safe signals for streaming events."""
    event_received = pyqtSignal(object)  # ActionEvent
    preview_updated = pyqtSignal(object)  # QPixmap
    progress_updated = pyqtSignal(float)  # percentage
    recording_state_changed = pyqtSignal(str)  # state name
    error_occurred = pyqtSignal(str)


class StreamingManager:
    """Central manager for live action streaming.
    
    Coordinates all visualization components:
    - MiniPreviewWidget for screen preview
    - ActionHighlighter for visual feedback
    - ProgressTracker for task progress
    - ActionRecorder for recording
    
    Features:
    - Event-driven architecture
    - Thread-safe operations
    - Low CPU usage (<10%)
    - Unified API
    """
    
    def __init__(self, config: StreamingConfig = None):
        """Initialize streaming manager.
        
        Args:
            config: Streaming configuration
        """
        self._config = config or StreamingConfig()
        self._signals = StreamingSignals()
        
        # Components (lazy initialization)
        self._preview = None
        self._highlighter = None
        self._progress = None
        self._recorder = None
        
        # Event handling
        self._event_queue: Queue = Queue(maxsize=self._config.event_queue_size)
        self._processing_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # State
        self._is_running = False
        self._current_task: Optional[str] = None
        self._current_steps: List[str] = []
        self._current_step_index = -1
        
        # Update timer
        self._update_timer: Optional[QTimer] = None
        
        # Callbacks
        self._callbacks: Dict[EventType, List[Callable]] = {}
    
    @property
    def signals(self) -> StreamingSignals:
        """Get signals object for connecting."""
        return self._signals
    
    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._is_running
    
    @property
    def preview(self):
        """Get preview widget (creates if needed)."""
        if self._preview is None and self._config.enable_preview:
            from .mini_preview import MiniPreviewWidget
            self._preview = MiniPreviewWidget(
                size=(self._config.preview_width, self._config.preview_height)
            )
        return self._preview
    
    @property
    def highlighter(self):
        """Get highlighter (creates if needed)."""
        if self._highlighter is None and self._config.enable_highlighting:
            from .highlighter import ActionHighlighter
            self._highlighter = ActionHighlighter()
            self._highlighter.set_default_color(self._config.highlight_color)
            if self._config.show_mouse_trail:
                self._highlighter.enable_trail(True)
        return self._highlighter
    
    @property
    def progress(self):
        """Get progress tracker (creates if needed)."""
        if self._progress is None and self._config.enable_progress:
            from .progress_tracker import ProgressTracker, ProgressStyle
            style_map = {
                "circles": ProgressStyle.CIRCLES,
                "chevrons": ProgressStyle.CHEVRONS,
                "minimal": ProgressStyle.MINIMAL,
                "detailed": ProgressStyle.DETAILED,
                "compact": ProgressStyle.COMPACT,
            }
            style = style_map.get(self._config.progress_style, ProgressStyle.CIRCLES)
            self._progress = ProgressTracker(style=style)
        return self._progress
    
    @property
    def recorder(self):
        """Get recorder (creates if needed)."""
        if self._recorder is None and self._config.enable_recording:
            from .recorder import ActionRecorder, RecordingConfig
            rec_config = RecordingConfig(
                fps=self._config.record_fps,
                format=self._config.record_format,
                output_path=self._config.record_path,
            )
            self._recorder = ActionRecorder(rec_config)
        return self._recorder
    
    # === Lifecycle ===
    
    def start(self):
        """Start the streaming manager."""
        if self._is_running:
            return
        
        self._is_running = True
        self._stop_event.clear()
        
        # Start event processing thread
        self._processing_thread = threading.Thread(
            target=self._event_processing_loop,
            daemon=True
        )
        self._processing_thread.start()
        
        # Start components
        if self._config.enable_preview and self.preview:
            self.preview.start()
            self.preview.show()
        
        if self._config.enable_highlighting and self.highlighter:
            self.highlighter.show()
    
    def stop(self):
        """Stop the streaming manager."""
        if not self._is_running:
            return
        
        self._is_running = False
        self._stop_event.set()
        
        # Wait for processing thread
        if self._processing_thread:
            self._processing_thread.join(timeout=2.0)
        
        # Stop components
        if self._preview:
            self._preview.stop()
            self._preview.hide()
        
        if self._highlighter:
            self._highlighter.hide()
            self._highlighter.clear()
        
        if self._recorder and self._recorder.is_recording:
            self._recorder.stop_recording()
    
    def cleanup(self):
        """Cleanup all resources."""
        self.stop()
        
        if self._preview:
            self._preview.close()
            self._preview = None
        
        if self._highlighter:
            self._highlighter.close()
            self._highlighter = None
        
        if self._progress:
            self._progress.close()
            self._progress = None
        
        if self._recorder:
            self._recorder = None
    
    # === Event Handling ===
    
    def emit_event(self, event: ActionEvent):
        """Emit an action event.
        
        Args:
            event: The action event to emit
        """
        try:
            self._event_queue.put_nowait(event)
        except Exception:
            pass  # Queue full, drop event
    
    def on_event(self, event_type: EventType, callback: Callable[[ActionEvent], None]):
        """Register callback for event type.
        
        Args:
            event_type: Type of event to listen for
            callback: Function to call with event
        """
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(callback)
    
    def _event_processing_loop(self):
        """Process events from queue."""
        while not self._stop_event.is_set():
            try:
                event = self._event_queue.get(timeout=0.1)
                self._handle_event(event)
            except Empty:
                continue
            except Exception as e:
                self._signals.error_occurred.emit(str(e))
    
    def _handle_event(self, event: ActionEvent):
        """Handle a single event.
        
        Args:
            event: The event to handle
        """
        # Emit signal
        self._signals.event_received.emit(event)
        
        # Call registered callbacks
        if event.type in self._callbacks:
            for callback in self._callbacks[event.type]:
                try:
                    callback(event)
                except Exception:
                    pass
        
        # Handle based on type
        handlers = {
            EventType.MOUSE_MOVE: self._handle_mouse_move,
            EventType.MOUSE_CLICK: self._handle_mouse_click,
            EventType.ELEMENT_CLICK: self._handle_element_click,
            EventType.ELEMENT_FOCUS: self._handle_element_focus,
            EventType.TASK_START: self._handle_task_start,
            EventType.TASK_STEP_START: self._handle_task_step_start,
            EventType.TASK_STEP_COMPLETE: self._handle_task_step_complete,
            EventType.TASK_STEP_FAIL: self._handle_task_step_fail,
            EventType.TASK_COMPLETE: self._handle_task_complete,
            EventType.ANNOTATION: self._handle_annotation,
        }
        
        handler = handlers.get(event.type)
        if handler:
            try:
                handler(event)
            except Exception as e:
                self._signals.error_occurred.emit(f"Event handler error: {e}")
    
    # === Event Handlers ===
    
    def _handle_mouse_move(self, event: ActionEvent):
        """Handle mouse move event."""
        if self._highlighter and self._config.show_mouse_trail:
            self._highlighter.update_trail_point(event.x, event.y)
        
        if self._preview:
            self._preview.show_cursor(event.x, event.y)
    
    def _handle_mouse_click(self, event: ActionEvent):
        """Handle mouse click event."""
        if self._highlighter and self._config.show_click_ripples:
            self._highlighter.show_click_ripple(
                event.x, event.y,
                color=event.color or self._config.highlight_color
            )
        
        if self._preview:
            self._preview.show_cursor(event.x, event.y, clicking=True)
        
        if self._recorder and self._recorder.is_recording:
            self._recorder.add_annotation(
                f"Click at ({event.x}, {event.y})",
                duration=1.5
            )
    
    def _handle_element_click(self, event: ActionEvent):
        """Handle element click event."""
        if self._highlighter:
            self._highlighter.highlight_click_target(
                event.x, event.y, event.width, event.height,
                color=event.color or self._config.highlight_color,
                label=event.target,
                duration=event.duration
            )
            
            if self._config.show_click_ripples:
                center_x = event.x + event.width // 2
                center_y = event.y + event.height // 2
                self._highlighter.show_click_ripple(center_x, center_y)
        
        if self._preview:
            self._preview.highlight_element(
                event.x, event.y, event.width, event.height,
                label=event.target
            )
    
    def _handle_element_focus(self, event: ActionEvent):
        """Handle element focus event."""
        if self._highlighter:
            from .highlighter import HighlightStyle
            self._highlighter.highlight_click_target(
                event.x, event.y, event.width, event.height,
                color="#00D4FF",
                style=HighlightStyle.GLOW,
                duration=event.duration
            )
        
        if self._preview:
            self._preview.highlight_element(
                event.x, event.y, event.width, event.height,
                color="#00D4FF",
                label=event.target
            )
    
    def _handle_task_start(self, event: ActionEvent):
        """Handle task start event."""
        self._current_task = event.description
        self._current_steps = event.data.get("steps", [])
        self._current_step_index = -1
        
        if self._progress:
            self._progress.set_task(event.description, self._current_steps)
            self._progress.start_task()
        
        if self._recorder and self._recorder.is_recording:
            self._recorder.add_annotation(
                f"Task: {event.description}",
                style="highlight",
                duration=3.0
            )
    
    def _handle_task_step_start(self, event: ActionEvent):
        """Handle task step start event."""
        index = event.data.get("index", 0)
        self._current_step_index = index
        
        if self._progress:
            from .progress_tracker import StepStatus
            self._progress.set_step_status(index, StepStatus.RUNNING)
        
        self._signals.progress_updated.emit(self._get_progress_percent())
    
    def _handle_task_step_complete(self, event: ActionEvent):
        """Handle task step complete event."""
        index = event.data.get("index", self._current_step_index)
        
        if self._progress:
            from .progress_tracker import StepStatus
            self._progress.set_step_status(index, StepStatus.COMPLETED)
        
        self._signals.progress_updated.emit(self._get_progress_percent())
    
    def _handle_task_step_fail(self, event: ActionEvent):
        """Handle task step fail event."""
        index = event.data.get("index", self._current_step_index)
        error = event.data.get("error", "Unknown error")
        
        if self._progress:
            from .progress_tracker import StepStatus
            self._progress.set_step_status(index, StepStatus.FAILED, error)
        
        if self._recorder and self._recorder.is_recording:
            self._recorder.add_annotation(
                f"Error: {error}",
                style="error",
                duration=5.0
            )
        
        self._signals.progress_updated.emit(self._get_progress_percent())
    
    def _handle_task_complete(self, event: ActionEvent):
        """Handle task complete event."""
        success = event.data.get("success", True)
        
        if self._recorder and self._recorder.is_recording:
            if success:
                self._recorder.add_annotation("Task completed!", style="success")
            else:
                self._recorder.add_annotation("Task failed!", style="error")
        
        self._signals.progress_updated.emit(100.0 if success else self._get_progress_percent())
    
    def _handle_annotation(self, event: ActionEvent):
        """Handle annotation event."""
        if self._recorder and self._recorder.is_recording:
            self._recorder.add_annotation(
                event.description,
                position=event.data.get("position", "bottom"),
                style=event.data.get("style", "default"),
                duration=event.duration
            )
    
    def _get_progress_percent(self) -> float:
        """Get current progress percentage."""
        if self._progress:
            return self._progress.get_progress_percent()
        return 0.0
    
    # === Convenience Methods ===
    
    def click(self, x: int, y: int, width: int = 0, height: int = 0, target: str = None):
        """Shortcut to emit click event.
        
        Args:
            x, y: Click position (or element position if width/height given)
            width, height: Element dimensions (0 for point click)
            target: Target element name
        """
        if width > 0 and height > 0:
            event = ActionEvent.element_click(x, y, width, height, target)
        else:
            event = ActionEvent.mouse_click(x, y)
        self.emit_event(event)
    
    def move(self, x: int, y: int):
        """Shortcut to emit mouse move event."""
        self.emit_event(ActionEvent.mouse_move(x, y))
    
    def start_task(self, description: str, steps: List[str]):
        """Start a new task.
        
        Args:
            description: Task description
            steps: List of step descriptions
        """
        self.emit_event(ActionEvent.task_start(description, steps))
    
    def advance_step(self):
        """Advance to next step."""
        if self._current_step_index >= 0:
            # Complete current
            self.emit_event(ActionEvent.task_step(
                self._current_step_index,
                self._current_steps[self._current_step_index] if self._current_step_index < len(self._current_steps) else "",
                "complete"
            ))
        
        # Start next
        self._current_step_index += 1
        if self._current_step_index < len(self._current_steps):
            self.emit_event(ActionEvent.task_step(
                self._current_step_index,
                self._current_steps[self._current_step_index],
                "start"
            ))
    
    def fail_step(self, error: str = None):
        """Fail current step.
        
        Args:
            error: Error message
        """
        if self._current_step_index >= 0:
            event = ActionEvent.task_step(
                self._current_step_index,
                self._current_steps[self._current_step_index] if self._current_step_index < len(self._current_steps) else "",
                "fail"
            )
            event.data["error"] = error or "Unknown error"
            self.emit_event(event)
    
    def complete_task(self, success: bool = True):
        """Complete the current task.
        
        Args:
            success: Whether task succeeded
        """
        event = ActionEvent(
            type=EventType.TASK_COMPLETE,
            data={"success": success}
        )
        self.emit_event(event)
    
    def annotate(self, text: str, position: str = "bottom", style: str = "default"):
        """Add annotation.
        
        Args:
            text: Annotation text
            position: Position on screen
            style: Visual style
        """
        self.emit_event(ActionEvent.annotation(text, position))
    
    def highlight(self, x: int, y: int, width: int, height: int, 
                  color: str = None, label: str = None, duration: float = 2.0):
        """Highlight an element.
        
        Args:
            x, y: Position
            width, height: Dimensions
            color: Highlight color
            label: Label text
            duration: How long to show
        """
        event = ActionEvent(
            type=EventType.ELEMENT_FOCUS,
            x=x, y=y, width=width, height=height,
            target=label,
            color=color,
            duration=duration
        )
        self.emit_event(event)
    
    # === Recording Control ===
    
    def start_recording(self, output_path: str = None) -> bool:
        """Start screen recording.
        
        Args:
            output_path: Output file path
        
        Returns:
            True if started successfully
        """
        if not self._config.enable_recording:
            self._config.enable_recording = True
        
        if self.recorder:
            result = self.recorder.start_recording(output_path)
            if result:
                self._signals.recording_state_changed.emit("recording")
            return result
        return False
    
    def stop_recording(self) -> Optional[str]:
        """Stop screen recording.
        
        Returns:
            Path to recorded file
        """
        if self._recorder:
            path = self._recorder.stop_recording()
            self._signals.recording_state_changed.emit("stopped")
            return path
        return None
    
    def pause_recording(self):
        """Pause recording."""
        if self._recorder:
            self._recorder.pause_recording()
            self._signals.recording_state_changed.emit("paused")
    
    def resume_recording(self):
        """Resume recording."""
        if self._recorder:
            self._recorder.resume_recording()
            self._signals.recording_state_changed.emit("recording")


def create_streaming_manager(config: StreamingConfig = None) -> StreamingManager:
    """Factory function to create StreamingManager.
    
    Args:
        config: Streaming configuration
    
    Returns:
        StreamingManager instance
    """
    return StreamingManager(config)
