"""Action Recorder for screen recording with annotations (Issue #7).

Provides screen recording capabilities:
- Record screen/window/region
- Add timestamped annotations
- Multiple output formats
- Low resource usage
- Pause/resume support
"""
from __future__ import annotations

import os
import time
import threading
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Callable, Any, BinaryIO

# Try to import recording libraries
try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class RecordingState(Enum):
    """Recording state."""
    IDLE = auto()
    RECORDING = auto()
    PAUSED = auto()
    STOPPING = auto()
    FINISHED = auto()
    ERROR = auto()


@dataclass
class RecordingAnnotation:
    """A timestamped annotation in the recording."""
    text: str
    timestamp: float  # Seconds from recording start
    duration: float = 3.0  # How long to show
    position: str = "bottom"  # top, bottom, center
    style: str = "default"  # default, highlight, error, success
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "text": self.text,
            "timestamp": self.timestamp,
            "duration": self.duration,
            "position": self.position,
            "style": self.style,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordingAnnotation":
        """Create from dictionary."""
        return cls(
            text=data["text"],
            timestamp=data["timestamp"],
            duration=data.get("duration", 3.0),
            position=data.get("position", "bottom"),
            style=data.get("style", "default"),
        )


@dataclass
class RecordingConfig:
    """Configuration for screen recording."""
    # Output
    output_path: str = ""
    filename_template: str = "bantz_recording_{timestamp}"
    format: str = "mp4"  # mp4, avi, webm
    
    # Quality
    fps: int = 20
    quality: int = 85  # 0-100
    codec: str = "mp4v"  # mp4v, XVID, avc1
    
    # Capture
    monitor: int = 0
    region: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h
    window_title: Optional[str] = None
    
    # Features
    include_cursor: bool = True
    include_annotations: bool = True
    include_audio: bool = False  # Future feature
    
    # Limits
    max_duration: int = 3600  # 1 hour max
    max_file_size_mb: int = 500
    
    def get_output_file(self) -> str:
        """Get output file path."""
        if self.output_path:
            base_dir = self.output_path
        else:
            base_dir = str(Path.home() / "Videos" / "Bantz")
        
        os.makedirs(base_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.filename_template.replace("{timestamp}", timestamp)
        
        return os.path.join(base_dir, f"{filename}.{self.format}")


@dataclass
class RecordingMetadata:
    """Metadata for a recording session."""
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    frame_count: int = 0
    file_size: int = 0
    resolution: Tuple[int, int] = (0, 0)
    fps: float = 0.0
    annotations: List[RecordingAnnotation] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "frame_count": self.frame_count,
            "file_size": self.file_size,
            "resolution": list(self.resolution),
            "fps": self.fps,
            "annotations": [a.to_dict() for a in self.annotations],
        }
    
    def save(self, path: str):
        """Save metadata to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)


class ActionRecorder:
    """Record actions for replay/review.
    
    Features:
    - Screen capture to video file
    - Region/window specific recording
    - Timestamped annotations
    - Pause/resume support
    - Low CPU usage
    - Multiple output formats
    """
    
    def __init__(self, config: RecordingConfig = None):
        """Initialize the recorder.
        
        Args:
            config: Recording configuration
        """
        self._config = config or RecordingConfig()
        self._state = RecordingState.IDLE
        self._metadata = RecordingMetadata()
        
        # Recording state
        self._output_path: Optional[str] = None
        self._video_writer = None
        self._sct = None
        self._start_time: float = 0.0
        self._pause_start: float = 0.0
        self._total_pause_time: float = 0.0
        
        # Thread control
        self._recording_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        
        # Annotations
        self._annotations: List[RecordingAnnotation] = []
        self._pending_annotations: List[RecordingAnnotation] = []
        
        # Callbacks
        self._on_frame_captured: Optional[Callable[[int, float], None]] = None
        self._on_state_changed: Optional[Callable[[RecordingState], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
    
    @property
    def state(self) -> RecordingState:
        """Get current recording state."""
        return self._state
    
    @property
    def is_recording(self) -> bool:
        """Check if actively recording."""
        return self._state == RecordingState.RECORDING
    
    @property
    def is_paused(self) -> bool:
        """Check if recording is paused."""
        return self._state == RecordingState.PAUSED
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed recording time (excluding pauses)."""
        if self._start_time == 0:
            return 0.0
        
        if self._state == RecordingState.PAUSED:
            return self._pause_start - self._start_time - self._total_pause_time
        
        return time.time() - self._start_time - self._total_pause_time
    
    @property
    def metadata(self) -> RecordingMetadata:
        """Get recording metadata."""
        return self._metadata
    
    def set_callbacks(
        self,
        on_frame: Callable[[int, float], None] = None,
        on_state: Callable[[RecordingState], None] = None,
        on_error: Callable[[str], None] = None
    ):
        """Set event callbacks.
        
        Args:
            on_frame: Called after each frame (frame_count, timestamp)
            on_state: Called on state change
            on_error: Called on error
        """
        self._on_frame_captured = on_frame
        self._on_state_changed = on_state
        self._on_error = on_error
    
    def start_recording(self, output_path: str = None) -> bool:
        """Start recording.
        
        Args:
            output_path: Output file path (optional, auto-generated if None)
        
        Returns:
            True if started successfully
        """
        if self._state not in (RecordingState.IDLE, RecordingState.FINISHED):
            return False
        
        if not HAS_MSS:
            self._set_error("mss not installed. Run: pip install mss")
            return False
        
        if not HAS_CV2:
            self._set_error("opencv-python not installed. Run: pip install opencv-python")
            return False
        
        # Get output path
        self._output_path = output_path or self._config.get_output_file()
        
        # Initialize capture
        try:
            self._sct = mss.mss()
        except Exception as e:
            self._set_error(f"Failed to initialize screen capture: {e}")
            return False
        
        # Get capture region
        if self._config.region:
            region = {
                "left": self._config.region[0],
                "top": self._config.region[1],
                "width": self._config.region[2],
                "height": self._config.region[3],
            }
        else:
            monitor = self._sct.monitors[self._config.monitor + 1]
            region = monitor
        
        # Initialize video writer
        try:
            fourcc = cv2.VideoWriter_fourcc(*self._config.codec)
            self._video_writer = cv2.VideoWriter(
                self._output_path,
                fourcc,
                self._config.fps,
                (region["width"], region["height"])
            )
            
            if not self._video_writer.isOpened():
                raise RuntimeError("Failed to open video writer")
                
        except Exception as e:
            self._set_error(f"Failed to initialize video writer: {e}")
            return False
        
        # Initialize state
        self._start_time = time.time()
        self._total_pause_time = 0.0
        self._annotations.clear()
        self._pending_annotations.clear()
        self._stop_event.clear()
        self._pause_event.set()  # Not paused
        
        self._metadata = RecordingMetadata(
            start_time=self._start_time,
            resolution=(region["width"], region["height"]),
            fps=self._config.fps,
        )
        
        # Start recording thread
        self._recording_thread = threading.Thread(
            target=self._recording_loop,
            args=(region,),
            daemon=True
        )
        self._recording_thread.start()
        
        self._set_state(RecordingState.RECORDING)
        return True
    
    def stop_recording(self) -> Optional[str]:
        """Stop recording.
        
        Returns:
            Path to recorded file, or None if error
        """
        if self._state not in (RecordingState.RECORDING, RecordingState.PAUSED):
            return None
        
        self._set_state(RecordingState.STOPPING)
        
        # Signal stop
        self._stop_event.set()
        self._pause_event.set()  # Unpause if paused
        
        # Wait for thread
        if self._recording_thread:
            self._recording_thread.join(timeout=5.0)
        
        # Cleanup
        self._cleanup()
        
        # Update metadata
        self._metadata.end_time = time.time()
        self._metadata.duration = self.elapsed_time
        self._metadata.annotations = self._annotations.copy()
        
        if self._output_path and os.path.exists(self._output_path):
            self._metadata.file_size = os.path.getsize(self._output_path)
            
            # Save metadata
            meta_path = self._output_path.rsplit('.', 1)[0] + '_meta.json'
            self._metadata.save(meta_path)
        
        self._set_state(RecordingState.FINISHED)
        return self._output_path
    
    def pause_recording(self):
        """Pause recording."""
        if self._state == RecordingState.RECORDING:
            self._pause_start = time.time()
            self._pause_event.clear()
            self._set_state(RecordingState.PAUSED)
    
    def resume_recording(self):
        """Resume recording."""
        if self._state == RecordingState.PAUSED:
            self._total_pause_time += time.time() - self._pause_start
            self._pause_event.set()
            self._set_state(RecordingState.RECORDING)
    
    def add_annotation(
        self,
        text: str,
        timestamp: float = None,
        duration: float = 3.0,
        position: str = "bottom",
        style: str = "default"
    ):
        """Add text annotation to recording.
        
        Args:
            text: Annotation text
            timestamp: Time in recording (None = current)
            duration: How long to show
            position: Position on screen
            style: Visual style
        """
        if timestamp is None:
            timestamp = self.elapsed_time
        
        annotation = RecordingAnnotation(
            text=text,
            timestamp=timestamp,
            duration=duration,
            position=position,
            style=style,
        )
        
        self._annotations.append(annotation)
        self._pending_annotations.append(annotation)
    
    def get_annotations(self) -> List[RecordingAnnotation]:
        """Get all annotations."""
        return self._annotations.copy()
    
    # === Internal Methods ===
    
    def _recording_loop(self, region: Dict):
        """Main recording loop (runs in thread)."""
        frame_interval = 1.0 / self._config.fps
        last_frame_time = time.time()
        
        while not self._stop_event.is_set():
            # Wait if paused
            self._pause_event.wait()
            
            if self._stop_event.is_set():
                break
            
            # Rate limiting
            now = time.time()
            elapsed = now - last_frame_time
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
                continue
            
            last_frame_time = now
            
            try:
                # Capture frame
                screenshot = self._sct.grab(region)
                
                # Convert to numpy array
                frame = np.array(screenshot)
                
                # Convert BGRA to BGR
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                
                # Add annotations if enabled
                if self._config.include_annotations:
                    frame = self._render_annotations(frame)
                
                # Write frame
                self._video_writer.write(frame)
                self._metadata.frame_count += 1
                
                # Callback
                if self._on_frame_captured:
                    try:
                        self._on_frame_captured(
                            self._metadata.frame_count,
                            self.elapsed_time
                        )
                    except Exception:
                        pass
                
                # Check limits
                if self.elapsed_time >= self._config.max_duration:
                    self._stop_event.set()
                    break
                
            except Exception as e:
                if self._on_error:
                    self._on_error(f"Frame capture error: {e}")
    
    def _render_annotations(self, frame: np.ndarray) -> np.ndarray:
        """Render annotations onto frame."""
        current_time = self.elapsed_time
        height, width = frame.shape[:2]
        
        # Find active annotations
        active = [
            a for a in self._annotations
            if a.timestamp <= current_time <= a.timestamp + a.duration
        ]
        
        for annotation in active:
            # Calculate opacity (fade in/out)
            age = current_time - annotation.timestamp
            if age < 0.3:
                opacity = age / 0.3
            elif age > annotation.duration - 0.3:
                opacity = (annotation.duration - age) / 0.3
            else:
                opacity = 1.0
            
            # Style colors
            style_colors = {
                "default": (255, 255, 255),
                "highlight": (255, 212, 0),
                "error": (68, 68, 255),
                "success": (136, 255, 0),
            }
            color = style_colors.get(annotation.style, (255, 255, 255))
            
            # Position
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.7
            thickness = 2
            text_size = cv2.getTextSize(annotation.text, font, font_scale, thickness)[0]
            
            x = (width - text_size[0]) // 2
            if annotation.position == "top":
                y = 40
            elif annotation.position == "center":
                y = height // 2
            else:  # bottom
                y = height - 30
            
            # Background rectangle
            padding = 10
            bg_rect = (
                x - padding,
                y - text_size[1] - padding,
                x + text_size[0] + padding,
                y + padding
            )
            
            # Create overlay for transparency
            overlay = frame.copy()
            cv2.rectangle(overlay, 
                         (bg_rect[0], bg_rect[1]), 
                         (bg_rect[2], bg_rect[3]),
                         (0, 0, 0), -1)
            
            # Blend
            alpha = 0.7 * opacity
            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
            
            # Text
            text_color = tuple(int(c * opacity) for c in color)
            cv2.putText(frame, annotation.text, (x, y), 
                       font, font_scale, text_color, thickness)
        
        return frame
    
    def _cleanup(self):
        """Cleanup resources."""
        if self._video_writer:
            self._video_writer.release()
            self._video_writer = None
        
        if self._sct:
            self._sct.close()
            self._sct = None
    
    def _set_state(self, state: RecordingState):
        """Set recording state and notify."""
        self._state = state
        if self._on_state_changed:
            try:
                self._on_state_changed(state)
            except Exception:
                pass
    
    def _set_error(self, message: str):
        """Set error state."""
        self._state = RecordingState.ERROR
        if self._on_error:
            try:
                self._on_error(message)
            except Exception:
                pass


class QuickRecorder:
    """Simplified recorder for quick captures."""
    
    def __init__(self, output_dir: str = None):
        """Initialize quick recorder.
        
        Args:
            output_dir: Directory for recordings
        """
        config = RecordingConfig(
            output_path=output_dir or str(Path.home() / "Videos" / "Bantz"),
            fps=15,  # Lower fps for quick captures
            quality=75,
        )
        self._recorder = ActionRecorder(config)
    
    def record(self, duration: float = 10.0) -> Optional[str]:
        """Record for specified duration.
        
        Args:
            duration: Recording duration in seconds
        
        Returns:
            Path to recorded file
        """
        if not self._recorder.start_recording():
            return None
        
        # Wait for duration
        start = time.time()
        while time.time() - start < duration:
            if self._recorder.state == RecordingState.ERROR:
                return None
            time.sleep(0.1)
        
        return self._recorder.stop_recording()
    
    def start(self) -> bool:
        """Start recording."""
        return self._recorder.start_recording()
    
    def stop(self) -> Optional[str]:
        """Stop and return file path."""
        return self._recorder.stop_recording()
    
    def annotate(self, text: str):
        """Add annotation."""
        self._recorder.add_annotation(text)


def create_recorder(config: RecordingConfig = None) -> ActionRecorder:
    """Factory function to create ActionRecorder.
    
    Args:
        config: Recording configuration
    
    Returns:
        ActionRecorder instance
    """
    return ActionRecorder(config)
