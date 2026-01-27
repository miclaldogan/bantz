"""Tests for Live Action Streaming & Visualization (Issue #7).

Comprehensive tests for:
- Mini Preview Window
- Action Highlighter
- Progress Tracker
- Screen Recorder
- Streaming Manager
"""
import pytest
import time
from unittest.mock import MagicMock, patch


# ====================
# Mini Preview Tests
# ====================

class TestPreviewMode:
    """Tests for PreviewMode enum."""
    
    def test_preview_modes_exist(self):
        """All preview modes are defined."""
        from bantz.ui.streaming.mini_preview import PreviewMode
        
        assert hasattr(PreviewMode, 'WINDOW')
        assert hasattr(PreviewMode, 'REGION')
        assert hasattr(PreviewMode, 'FULLSCREEN')
        assert hasattr(PreviewMode, 'ELEMENT')
    
    def test_preview_modes_are_unique(self):
        """Preview modes have unique values."""
        from bantz.ui.streaming.mini_preview import PreviewMode
        
        modes = [PreviewMode.WINDOW, PreviewMode.REGION, 
                 PreviewMode.FULLSCREEN, PreviewMode.ELEMENT]
        values = [m.value for m in modes]
        assert len(values) == len(set(values))


class TestCaptureTarget:
    """Tests for CaptureTarget dataclass."""
    
    def test_default_capture_target(self):
        """Default CaptureTarget uses fullscreen mode."""
        from bantz.ui.streaming.mini_preview import CaptureTarget, PreviewMode
        
        target = CaptureTarget()
        
        assert target.mode == PreviewMode.FULLSCREEN
        assert target.monitor == 0
        assert target.window_id is None
        assert target.capture_region is None
    
    def test_fullscreen_factory(self):
        """CaptureTarget.fullscreen() creates fullscreen target."""
        from bantz.ui.streaming.mini_preview import CaptureTarget, PreviewMode
        
        target = CaptureTarget.fullscreen(monitor=1)
        
        assert target.mode == PreviewMode.FULLSCREEN
        assert target.monitor == 1
    
    def test_window_factory(self):
        """CaptureTarget.window() creates window target."""
        from bantz.ui.streaming.mini_preview import CaptureTarget, PreviewMode
        
        target = CaptureTarget.window(window_id="12345", title="My Window")
        
        assert target.mode == PreviewMode.WINDOW
        assert target.window_id == "12345"
        assert target.window_title == "My Window"
    
    def test_region_factory(self):
        """CaptureTarget.region() creates region target."""
        from bantz.ui.streaming.mini_preview import CaptureTarget, PreviewMode
        
        target = CaptureTarget.region(100, 200, 800, 600)
        
        assert target.mode == PreviewMode.REGION
        assert target.capture_region == (100, 200, 800, 600)


class TestHighlightRect:
    """Tests for HighlightRect dataclass."""
    
    def test_highlight_rect_defaults(self):
        """HighlightRect has sensible defaults."""
        from bantz.ui.streaming.mini_preview import HighlightRect
        
        rect = HighlightRect(x=10, y=20, width=100, height=50)
        
        assert rect.x == 10
        assert rect.y == 20
        assert rect.width == 100
        assert rect.height == 50
        assert rect.color == "#00FF00"
        assert rect.line_width == 3
        assert rect.pulse == False
        assert rect.opacity == 1.0


class TestCursorOverlay:
    """Tests for CursorOverlay dataclass."""
    
    def test_cursor_overlay_defaults(self):
        """CursorOverlay has sensible defaults."""
        from bantz.ui.streaming.mini_preview import CursorOverlay
        
        cursor = CursorOverlay(x=100, y=200)
        
        assert cursor.x == 100
        assert cursor.y == 200
        assert cursor.visible == True
        assert cursor.clicking == False
        assert cursor.color == "#FF0000"
        assert cursor.show_trail == False
        assert cursor.trail == []


# ====================
# Highlighter Tests
# ====================

class TestHighlightStyle:
    """Tests for HighlightStyle enum."""
    
    def test_all_styles_exist(self):
        """All highlight styles are defined."""
        from bantz.ui.streaming.highlighter import HighlightStyle
        
        expected = ['SOLID', 'DASHED', 'GLOW', 'PULSE', 
                    'CORNER_BRACKETS', 'SCANNING']
        
        for style in expected:
            assert hasattr(HighlightStyle, style)
    
    def test_styles_are_unique(self):
        """Highlight styles have unique values."""
        from bantz.ui.streaming.highlighter import HighlightStyle
        
        all_styles = list(HighlightStyle)
        values = [s.value for s in all_styles]
        assert len(values) == len(set(values))


class TestHighlightBox:
    """Tests for HighlightBox dataclass."""
    
    def test_highlight_box_defaults(self):
        """HighlightBox has sensible defaults."""
        from bantz.ui.streaming.highlighter import HighlightBox, HighlightStyle
        
        box = HighlightBox(x=0, y=0, width=100, height=100)
        
        assert box.color == "#00FF00"
        assert box.style == HighlightStyle.SOLID
        assert box.line_width == 3
        assert box.duration == 2.0
        assert box.opacity == 1.0
    
    def test_is_expired_permanent(self):
        """Permanent highlights never expire."""
        from bantz.ui.streaming.highlighter import HighlightBox
        
        box = HighlightBox(x=0, y=0, width=100, height=100, duration=0)
        
        assert box.is_expired == False
    
    def test_remaining_opacity_permanent(self):
        """Permanent highlights maintain full opacity."""
        from bantz.ui.streaming.highlighter import HighlightBox
        
        box = HighlightBox(x=0, y=0, width=100, height=100, duration=0, opacity=0.8)
        
        assert box.remaining_opacity == 0.8


class TestClickRipple:
    """Tests for ClickRipple dataclass."""
    
    def test_click_ripple_defaults(self):
        """ClickRipple has sensible defaults."""
        from bantz.ui.streaming.highlighter import ClickRipple
        
        ripple = ClickRipple(x=100, y=200)
        
        assert ripple.x == 100
        assert ripple.y == 200
        assert ripple.color == "#00FF00"
        assert ripple.max_radius == 50
        assert ripple.duration == 0.6
        assert ripple.rings == 3
    
    def test_progress_starts_at_zero(self):
        """Ripple progress starts at zero."""
        from bantz.ui.streaming.highlighter import ClickRipple
        
        ripple = ClickRipple(x=0, y=0)
        # Progress should be very close to 0 immediately after creation
        assert ripple.progress < 0.1
    
    def test_is_complete_false_initially(self):
        """Ripple is not complete immediately."""
        from bantz.ui.streaming.highlighter import ClickRipple
        
        ripple = ClickRipple(x=0, y=0)
        assert ripple.is_complete == False


class TestMouseTrail:
    """Tests for MouseTrail dataclass."""
    
    def test_mouse_trail_defaults(self):
        """MouseTrail has sensible defaults."""
        from bantz.ui.streaming.highlighter import MouseTrail
        
        trail = MouseTrail()
        
        assert trail.points == []
        assert trail.timestamps == []
        assert trail.color == "#00D4FF"
        assert trail.max_points == 100
        assert trail.trail_duration == 1.0
    
    def test_add_point(self):
        """add_point adds point to trail."""
        from bantz.ui.streaming.highlighter import MouseTrail
        
        trail = MouseTrail()
        trail.add_point(100, 200)
        trail.add_point(110, 210)
        
        assert len(trail.points) == 2
        assert (100, 200) in trail.points
        assert (110, 210) in trail.points
    
    def test_clear(self):
        """clear removes all points."""
        from bantz.ui.streaming.highlighter import MouseTrail
        
        trail = MouseTrail()
        trail.add_point(100, 200)
        trail.add_point(110, 210)
        trail.clear()
        
        assert trail.points == []
        assert trail.timestamps == []


# ====================
# Progress Tracker Tests
# ====================

class TestStepStatus:
    """Tests for StepStatus enum."""
    
    def test_all_statuses_exist(self):
        """All step statuses are defined."""
        from bantz.ui.streaming.progress_tracker import StepStatus
        
        expected = ['PENDING', 'RUNNING', 'COMPLETED', 
                    'FAILED', 'SKIPPED', 'WAITING']
        
        for status in expected:
            assert hasattr(StepStatus, status)
    
    def test_status_colors(self):
        """Each status has a color."""
        from bantz.ui.streaming.progress_tracker import StepStatus
        
        for status in StepStatus:
            assert status.color is not None
            assert status.color.startswith("#")
    
    def test_status_icons(self):
        """Each status has an icon."""
        from bantz.ui.streaming.progress_tracker import StepStatus
        
        for status in StepStatus:
            assert status.icon is not None
            assert len(status.icon) == 1


class TestTaskStep:
    """Tests for TaskStep dataclass."""
    
    def test_task_step_defaults(self):
        """TaskStep has sensible defaults."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        step = TaskStep(description="Test step")
        
        assert step.description == "Test step"
        assert step.status == StepStatus.PENDING
        assert step.details is None
        assert step.start_time is None
        assert step.progress == 0.0
    
    def test_start_sets_running(self):
        """start() sets status to RUNNING."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        step = TaskStep(description="Test")
        step.start()
        
        assert step.status == StepStatus.RUNNING
        assert step.start_time is not None
    
    def test_complete_success(self):
        """complete(success=True) sets COMPLETED."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        step = TaskStep(description="Test")
        step.start()
        step.complete(success=True)
        
        assert step.status == StepStatus.COMPLETED
        assert step.progress == 1.0
        assert step.end_time is not None
    
    def test_complete_failure(self):
        """complete(success=False) sets FAILED."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        step = TaskStep(description="Test")
        step.start()
        step.complete(success=False, error="Something went wrong")
        
        assert step.status == StepStatus.FAILED
        assert step.error_message == "Something went wrong"
    
    def test_skip(self):
        """skip() sets SKIPPED."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        step = TaskStep(description="Test")
        step.skip()
        
        assert step.status == StepStatus.SKIPPED
    
    def test_is_complete(self):
        """is_complete returns True for terminal states."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        completed = TaskStep(description="Test", status=StepStatus.COMPLETED)
        failed = TaskStep(description="Test", status=StepStatus.FAILED)
        skipped = TaskStep(description="Test", status=StepStatus.SKIPPED)
        running = TaskStep(description="Test", status=StepStatus.RUNNING)
        
        assert completed.is_complete == True
        assert failed.is_complete == True
        assert skipped.is_complete == True
        assert running.is_complete == False
    
    def test_duration_calculation(self):
        """duration calculates elapsed time."""
        from bantz.ui.streaming.progress_tracker import TaskStep
        
        step = TaskStep(description="Test")
        step.start()
        time.sleep(0.1)
        step.complete(success=True)
        
        assert step.duration is not None
        assert step.duration >= 0.1


class TestProgressStyle:
    """Tests for ProgressStyle enum."""
    
    def test_all_styles_exist(self):
        """All progress styles are defined."""
        from bantz.ui.streaming.progress_tracker import ProgressStyle
        
        expected = ['CIRCLES', 'CHEVRONS', 'MINIMAL', 
                    'DETAILED', 'COMPACT']
        
        for style in expected:
            assert hasattr(ProgressStyle, style)


# ====================
# Recorder Tests
# ====================

class TestRecordingState:
    """Tests for RecordingState enum."""
    
    def test_all_states_exist(self):
        """All recording states are defined."""
        from bantz.ui.streaming.recorder import RecordingState
        
        expected = ['IDLE', 'RECORDING', 'PAUSED', 
                    'STOPPING', 'FINISHED', 'ERROR']
        
        for state in expected:
            assert hasattr(RecordingState, state)


class TestRecordingAnnotation:
    """Tests for RecordingAnnotation dataclass."""
    
    def test_annotation_defaults(self):
        """RecordingAnnotation has sensible defaults."""
        from bantz.ui.streaming.recorder import RecordingAnnotation
        
        annotation = RecordingAnnotation(text="Test", timestamp=5.0)
        
        assert annotation.text == "Test"
        assert annotation.timestamp == 5.0
        assert annotation.duration == 3.0
        assert annotation.position == "bottom"
        assert annotation.style == "default"
    
    def test_to_dict(self):
        """to_dict serializes correctly."""
        from bantz.ui.streaming.recorder import RecordingAnnotation
        
        annotation = RecordingAnnotation(
            text="Test",
            timestamp=5.0,
            duration=2.0,
            position="top",
            style="highlight"
        )
        
        data = annotation.to_dict()
        
        assert data["text"] == "Test"
        assert data["timestamp"] == 5.0
        assert data["duration"] == 2.0
        assert data["position"] == "top"
        assert data["style"] == "highlight"
    
    def test_from_dict(self):
        """from_dict deserializes correctly."""
        from bantz.ui.streaming.recorder import RecordingAnnotation
        
        data = {
            "text": "Test",
            "timestamp": 5.0,
            "duration": 2.0,
            "position": "center",
            "style": "error"
        }
        
        annotation = RecordingAnnotation.from_dict(data)
        
        assert annotation.text == "Test"
        assert annotation.timestamp == 5.0
        assert annotation.duration == 2.0
        assert annotation.position == "center"
        assert annotation.style == "error"


class TestRecordingConfig:
    """Tests for RecordingConfig dataclass."""
    
    def test_config_defaults(self):
        """RecordingConfig has sensible defaults."""
        from bantz.ui.streaming.recorder import RecordingConfig
        
        config = RecordingConfig()
        
        assert config.format == "mp4"
        assert config.fps == 20
        assert config.quality == 85
        assert config.include_cursor == True
        assert config.include_annotations == True
        assert config.max_duration == 3600
    
    def test_get_output_file_generates_path(self):
        """get_output_file creates valid path."""
        from bantz.ui.streaming.recorder import RecordingConfig
        import os
        
        config = RecordingConfig(output_path="/tmp/test_recordings")
        path = config.get_output_file()
        
        assert path.startswith("/tmp/test_recordings")
        assert path.endswith(".mp4")
        assert "bantz_recording" in path


# ====================
# Manager Tests
# ====================

class TestEventType:
    """Tests for EventType enum."""
    
    def test_mouse_events_exist(self):
        """Mouse event types are defined."""
        from bantz.ui.streaming.manager import EventType
        
        assert hasattr(EventType, 'MOUSE_MOVE')
        assert hasattr(EventType, 'MOUSE_CLICK')
        assert hasattr(EventType, 'MOUSE_DOUBLE_CLICK')
        assert hasattr(EventType, 'MOUSE_SCROLL')
    
    def test_task_events_exist(self):
        """Task event types are defined."""
        from bantz.ui.streaming.manager import EventType
        
        assert hasattr(EventType, 'TASK_START')
        assert hasattr(EventType, 'TASK_STEP_START')
        assert hasattr(EventType, 'TASK_STEP_COMPLETE')
        assert hasattr(EventType, 'TASK_STEP_FAIL')
        assert hasattr(EventType, 'TASK_COMPLETE')
    
    def test_element_events_exist(self):
        """Element event types are defined."""
        from bantz.ui.streaming.manager import EventType
        
        assert hasattr(EventType, 'ELEMENT_FOCUS')
        assert hasattr(EventType, 'ELEMENT_CLICK')
        assert hasattr(EventType, 'ELEMENT_TYPE')


class TestActionEvent:
    """Tests for ActionEvent dataclass."""
    
    def test_action_event_defaults(self):
        """ActionEvent has sensible defaults."""
        from bantz.ui.streaming.manager import ActionEvent, EventType
        
        event = ActionEvent(type=EventType.MOUSE_CLICK)
        
        assert event.type == EventType.MOUSE_CLICK
        assert event.x is None
        assert event.y is None
        assert event.data == {}
        assert event.animate == True
    
    def test_mouse_click_factory(self):
        """mouse_click creates mouse click event."""
        from bantz.ui.streaming.manager import ActionEvent, EventType
        
        event = ActionEvent.mouse_click(100, 200, button="right")
        
        assert event.type == EventType.MOUSE_CLICK
        assert event.x == 100
        assert event.y == 200
        assert event.data["button"] == "right"
    
    def test_mouse_move_factory(self):
        """mouse_move creates mouse move event."""
        from bantz.ui.streaming.manager import ActionEvent, EventType
        
        event = ActionEvent.mouse_move(150, 250)
        
        assert event.type == EventType.MOUSE_MOVE
        assert event.x == 150
        assert event.y == 250
    
    def test_element_click_factory(self):
        """element_click creates element click event."""
        from bantz.ui.streaming.manager import ActionEvent, EventType
        
        event = ActionEvent.element_click(
            x=10, y=20, width=100, height=50,
            target="Submit Button",
            description="Click submit"
        )
        
        assert event.type == EventType.ELEMENT_CLICK
        assert event.x == 10
        assert event.y == 20
        assert event.width == 100
        assert event.height == 50
        assert event.target == "Submit Button"
    
    def test_task_start_factory(self):
        """task_start creates task start event."""
        from bantz.ui.streaming.manager import ActionEvent, EventType
        
        event = ActionEvent.task_start("My Task", ["Step 1", "Step 2"])
        
        assert event.type == EventType.TASK_START
        assert event.description == "My Task"
        assert event.data["steps"] == ["Step 1", "Step 2"]
    
    def test_annotation_factory(self):
        """annotation creates annotation event."""
        from bantz.ui.streaming.manager import ActionEvent, EventType
        
        event = ActionEvent.annotation("Important note", position="top")
        
        assert event.type == EventType.ANNOTATION
        assert event.description == "Important note"
        assert event.data["position"] == "top"


class TestStreamingConfig:
    """Tests for StreamingConfig dataclass."""
    
    def test_config_defaults(self):
        """StreamingConfig has sensible defaults."""
        from bantz.ui.streaming.manager import StreamingConfig
        
        config = StreamingConfig()
        
        assert config.enable_preview == True
        assert config.enable_highlighting == True
        assert config.enable_progress == True
        assert config.enable_recording == False
        assert config.preview_width == 320
        assert config.preview_height == 180
        assert config.preview_fps == 30
        assert config.highlight_color == "#00FF00"
        assert config.show_click_ripples == True
    
    def test_custom_config(self):
        """StreamingConfig can be customized."""
        from bantz.ui.streaming.manager import StreamingConfig
        
        config = StreamingConfig(
            enable_preview=False,
            enable_recording=True,
            highlight_color="#FF0000",
            preview_fps=15
        )
        
        assert config.enable_preview == False
        assert config.enable_recording == True
        assert config.highlight_color == "#FF0000"
        assert config.preview_fps == 15


# ====================
# Package Exports Tests
# ====================

class TestPackageExports:
    """Tests for package exports."""
    
    def test_mini_preview_exports(self):
        """mini_preview module exports correctly."""
        from bantz.ui.streaming.mini_preview import (
            MiniPreviewWidget,
            PreviewMode,
            CaptureTarget,
            CursorOverlay,
        )
        
        assert MiniPreviewWidget is not None
        assert PreviewMode is not None
    
    def test_highlighter_exports(self):
        """highlighter module exports correctly."""
        from bantz.ui.streaming.highlighter import (
            ActionHighlighter,
            HighlightBox,
            ClickRipple,
            MouseTrail,
            HighlightStyle,
        )
        
        assert ActionHighlighter is not None
        assert HighlightStyle is not None
    
    def test_progress_tracker_exports(self):
        """progress_tracker module exports correctly."""
        from bantz.ui.streaming.progress_tracker import (
            ProgressTracker,
            TaskStep,
            StepStatus,
            ProgressStyle,
        )
        
        assert ProgressTracker is not None
        assert StepStatus is not None
    
    def test_recorder_exports(self):
        """recorder module exports correctly."""
        from bantz.ui.streaming.recorder import (
            ActionRecorder,
            RecordingAnnotation,
            RecordingConfig,
            RecordingState,
        )
        
        assert ActionRecorder is not None
        assert RecordingState is not None
    
    def test_manager_exports(self):
        """manager module exports correctly."""
        from bantz.ui.streaming.manager import (
            StreamingManager,
            StreamingConfig,
            ActionEvent,
            EventType,
        )
        
        assert StreamingManager is not None
        assert EventType is not None
    
    def test_package_init_exports(self):
        """Package __init__ exports all modules."""
        from bantz.ui.streaming import (
            MiniPreviewWidget,
            ActionHighlighter,
            ProgressTracker,
            ActionRecorder,
            StreamingManager,
            EventType,
            StepStatus,
        )
        
        assert MiniPreviewWidget is not None
        assert ActionHighlighter is not None
        assert ProgressTracker is not None
        assert ActionRecorder is not None
        assert StreamingManager is not None


# ====================
# Integration Tests
# ====================

class TestStreamingManagerIntegration:
    """Integration tests for StreamingManager."""
    
    def test_manager_creation(self):
        """StreamingManager can be created."""
        from bantz.ui.streaming.manager import StreamingManager, StreamingConfig
        
        config = StreamingConfig(
            enable_preview=False,
            enable_highlighting=False,
            enable_progress=False,
            enable_recording=False
        )
        
        manager = StreamingManager(config)
        
        assert manager is not None
        assert manager.is_running == False
    
    def test_manager_config_access(self):
        """StreamingManager exposes configuration."""
        from bantz.ui.streaming.manager import StreamingManager, StreamingConfig
        
        config = StreamingConfig(highlight_color="#FF00FF")
        manager = StreamingManager(config)
        
        assert manager._config.highlight_color == "#FF00FF"
    
    def test_factory_function(self):
        """create_streaming_manager factory works."""
        from bantz.ui.streaming.manager import create_streaming_manager
        
        manager = create_streaming_manager()
        
        assert manager is not None


class TestProgressTrackerIntegration:
    """Integration tests for ProgressTracker."""
    
    def test_progress_calculation(self):
        """Progress percentage is calculated correctly."""
        from bantz.ui.streaming.progress_tracker import TaskStep, StepStatus
        
        steps = [
            TaskStep(description="Step 1", status=StepStatus.COMPLETED),
            TaskStep(description="Step 2", status=StepStatus.COMPLETED),
            TaskStep(description="Step 3", status=StepStatus.RUNNING, progress=0.5),
            TaskStep(description="Step 4", status=StepStatus.PENDING),
        ]
        
        # Manual calculation: (1 + 1 + 0.5 + 0) / 4 = 62.5%
        total = sum(
            1.0 if s.status == StepStatus.COMPLETED else s.progress
            for s in steps
        )
        expected = (total / len(steps)) * 100
        
        assert expected == pytest.approx(62.5)


class TestRecorderIntegration:
    """Integration tests for ActionRecorder."""
    
    def test_recorder_initial_state(self):
        """ActionRecorder starts in IDLE state."""
        from bantz.ui.streaming.recorder import ActionRecorder, RecordingState
        
        recorder = ActionRecorder()
        
        assert recorder.state == RecordingState.IDLE
        assert recorder.is_recording == False
        assert recorder.is_paused == False
        assert recorder.elapsed_time == 0.0
    
    def test_recorder_annotations(self):
        """ActionRecorder can store annotations."""
        from bantz.ui.streaming.recorder import ActionRecorder
        
        recorder = ActionRecorder()
        
        recorder.add_annotation("First annotation", timestamp=0.0)
        recorder.add_annotation("Second annotation", timestamp=1.0)
        
        annotations = recorder.get_annotations()
        
        assert len(annotations) == 2
        assert annotations[0].text == "First annotation"
        assert annotations[1].text == "Second annotation"
