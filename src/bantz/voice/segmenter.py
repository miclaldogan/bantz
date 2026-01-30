"""Speech Segmenter (Issue #11).

Segments continuous audio into speech utterances with silence detection.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .vad import AdvancedVAD


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

class SegmentState(Enum):
    """State of the segmenter."""
    IDLE = auto()        # Waiting for speech
    SPEAKING = auto()    # Recording speech
    SILENCE = auto()     # Possible end of speech (silence window)


@dataclass
class SegmenterConfig:
    """Speech segmenter configuration.
    
    Attributes:
        sample_rate: Audio sample rate
        min_speech_duration: Minimum speech duration in seconds
        max_speech_duration: Maximum speech duration in seconds
        silence_threshold: Silence duration to end speech (seconds)
        speech_start_threshold: Speech duration to confirm start (seconds)
    """
    sample_rate: int = 16000
    min_speech_duration: float = 0.3
    max_speech_duration: float = 30.0
    silence_threshold: float = 0.8
    speech_start_threshold: float = 0.1


@dataclass
class Segment:
    """A speech segment.
    
    Attributes:
        audio: Raw audio bytes
        start_time: Start time in seconds from stream start
        end_time: End time in seconds
        duration: Duration in seconds
    """
    audio: bytes
    start_time: float
    end_time: float
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    def __len__(self) -> int:
        return len(self.audio)


@dataclass
class SegmenterState:
    """Internal state of the segmenter."""
    state: SegmentState = SegmentState.IDLE
    current_audio: bytes = b''
    speech_start_time: float = 0.0
    silence_start_time: float = 0.0
    total_time: float = 0.0
    speech_frames: int = 0
    silence_frames: int = 0


# ─────────────────────────────────────────────────────────────────
# Speech Segmenter
# ─────────────────────────────────────────────────────────────────

class SpeechSegmenter:
    """Segments audio stream into speech utterances.
    
    Uses VAD to detect speech boundaries:
    - Starts segment when speech is detected
    - Ends segment when silence exceeds threshold
    - Enforces min/max duration limits
    
    Usage:
        segmenter = SpeechSegmenter(vad)
        
        for chunk in audio_stream:
            segment = segmenter.process(chunk)
            if segment:
                # Complete utterance received
                process_utterance(segment)
    """
    
    def __init__(
        self,
        vad: Optional[AdvancedVAD] = None,
        config: Optional[SegmenterConfig] = None,
    ):
        """Initialize segmenter.
        
        Args:
            vad: Voice activity detector
            config: Segmenter configuration
        """
        from .vad import AdvancedVAD, EnergyVAD
        
        self.config = config or SegmenterConfig()
        
        # Use provided VAD or create energy-based fallback
        if vad is not None:
            self._vad = vad
        else:
            self._vad = EnergyVAD(sample_rate=self.config.sample_rate)
        
        self._state = SegmenterState()
        
        # Callbacks
        self._on_segment: Optional[Callable[[Segment], Any]] = None
        self._on_speech_start: Optional[Callable[[], Any]] = None
        self._on_speech_end: Optional[Callable[[], Any]] = None
        
        # Completed segments queue
        self._segments: List[Segment] = []
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def state(self) -> SegmentState:
        """Get current state."""
        return self._state.state
    
    @property
    def is_speaking(self) -> bool:
        """Check if currently recording speech."""
        return self._state.state in (SegmentState.SPEAKING, SegmentState.SILENCE)
    
    @property
    def current_duration(self) -> float:
        """Get duration of current speech (if any)."""
        if not self.is_speaking:
            return 0.0
        return self._state.total_time - self._state.speech_start_time
    
    @property
    def total_time(self) -> float:
        """Get total stream time processed."""
        return self._state.total_time
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_segment(self, callback: Callable[[Segment], Any]) -> None:
        """Set callback for completed segment."""
        self._on_segment = callback
    
    def on_speech_start(self, callback: Callable[[], Any]) -> None:
        """Set callback for speech start."""
        self._on_speech_start = callback
    
    def on_speech_end(self, callback: Callable[[], Any]) -> None:
        """Set callback for speech end."""
        self._on_speech_end = callback
    
    # ─────────────────────────────────────────────────────────────
    # Core Processing
    # ─────────────────────────────────────────────────────────────
    
    def process(self, audio_chunk: bytes) -> Optional[Segment]:
        """Process audio chunk, return segment if complete.
        
        Args:
            audio_chunk: Raw audio bytes (16-bit PCM)
            
        Returns:
            Completed segment if speech ended, else None
        """
        # Update time
        chunk_duration = len(audio_chunk) / 2 / self.config.sample_rate
        
        # Check VAD
        is_speech = self._vad.is_speech(audio_chunk)
        
        # State machine
        segment = None
        
        if self._state.state == SegmentState.IDLE:
            segment = self._handle_idle(audio_chunk, is_speech, chunk_duration)
        
        elif self._state.state == SegmentState.SPEAKING:
            segment = self._handle_speaking(audio_chunk, is_speech, chunk_duration)
        
        elif self._state.state == SegmentState.SILENCE:
            segment = self._handle_silence(audio_chunk, is_speech, chunk_duration)
        
        # Update total time
        self._state.total_time += chunk_duration
        
        return segment
    
    def _handle_idle(
        self,
        audio_chunk: bytes,
        is_speech: bool,
        chunk_duration: float,
    ) -> Optional[Segment]:
        """Handle IDLE state."""
        if is_speech:
            # Start recording
            self._state.state = SegmentState.SPEAKING
            self._state.current_audio = audio_chunk
            self._state.speech_start_time = self._state.total_time
            self._state.speech_frames = 1
            self._state.silence_frames = 0
            
            # Fire callback
            if self._on_speech_start:
                try:
                    self._on_speech_start()
                except Exception:
                    pass
        
        return None
    
    def _handle_speaking(
        self,
        audio_chunk: bytes,
        is_speech: bool,
        chunk_duration: float,
    ) -> Optional[Segment]:
        """Handle SPEAKING state."""
        # Add to buffer
        self._state.current_audio += audio_chunk
        
        if is_speech:
            self._state.speech_frames += 1
            self._state.silence_frames = 0
        else:
            self._state.silence_frames += 1
            
            # Check if entering silence state
            if self._state.silence_frames >= 2:  # Multiple silence frames
                self._state.state = SegmentState.SILENCE
                self._state.silence_start_time = self._state.total_time
        
        # Check max duration
        current_duration = self._state.total_time - self._state.speech_start_time + chunk_duration
        if current_duration >= self.config.max_speech_duration:
            return self._complete_segment()
        
        return None
    
    def _handle_silence(
        self,
        audio_chunk: bytes,
        is_speech: bool,
        chunk_duration: float,
    ) -> Optional[Segment]:
        """Handle SILENCE state."""
        # Add to buffer
        self._state.current_audio += audio_chunk
        
        if is_speech:
            # Resume speaking
            self._state.state = SegmentState.SPEAKING
            self._state.speech_frames += 1
            self._state.silence_frames = 0
            return None
        
        # Update silence tracking
        self._state.silence_frames += 1
        
        # Check silence threshold
        silence_duration = self._state.total_time - self._state.silence_start_time + chunk_duration
        if silence_duration >= self.config.silence_threshold:
            return self._complete_segment()
        
        # Check max duration
        current_duration = self._state.total_time - self._state.speech_start_time + chunk_duration
        if current_duration >= self.config.max_speech_duration:
            return self._complete_segment()
        
        return None
    
    def _complete_segment(self) -> Optional[Segment]:
        """Complete current segment and return it."""
        duration = self._state.total_time - self._state.speech_start_time
        
        # Check minimum duration
        if duration < self.config.min_speech_duration:
            self._reset_state()
            return None
        
        # Trim trailing silence
        audio = self._trim_silence(self._state.current_audio)
        
        segment = Segment(
            audio=audio,
            start_time=self._state.speech_start_time,
            end_time=self._state.total_time,
        )
        
        # Fire callback
        if self._on_speech_end:
            try:
                self._on_speech_end()
            except Exception:
                pass
        
        if self._on_segment:
            try:
                self._on_segment(segment)
            except Exception:
                pass
        
        # Add to queue
        self._segments.append(segment)
        
        # Reset state
        self._reset_state()
        
        return segment
    
    def _trim_silence(self, audio: bytes) -> bytes:
        """Trim trailing silence from audio.
        
        Args:
            audio: Audio bytes
            
        Returns:
            Trimmed audio bytes
        """
        if len(audio) == 0:
            return audio
        
        # Calculate silence threshold in samples
        silence_samples = int(self.config.silence_threshold * self.config.sample_rate)
        silence_bytes = silence_samples * 2
        
        # Don't trim more than we have
        if silence_bytes >= len(audio):
            return audio
        
        # Keep everything except trailing silence
        return audio[:-silence_bytes] if silence_bytes > 0 else audio
    
    def _reset_state(self) -> None:
        """Reset to idle state."""
        self._state.state = SegmentState.IDLE
        self._state.current_audio = b''
        self._state.speech_frames = 0
        self._state.silence_frames = 0
    
    # ─────────────────────────────────────────────────────────────
    # Segment Queue
    # ─────────────────────────────────────────────────────────────
    
    def get_segments(self) -> List[Segment]:
        """Get all completed segments and clear queue."""
        segments = self._segments.copy()
        self._segments.clear()
        return segments
    
    def has_segments(self) -> bool:
        """Check if there are completed segments."""
        return len(self._segments) > 0
    
    # ─────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────
    
    def reset(self) -> None:
        """Reset all state."""
        self._state = SegmenterState()
        self._segments.clear()
    
    def force_complete(self) -> Optional[Segment]:
        """Force complete current segment (e.g., at end of stream).
        
        Returns:
            Segment if there was speech, else None
        """
        if self._state.state == SegmentState.IDLE:
            return None
        
        return self._complete_segment()
    
    def get_stats(self) -> dict:
        """Get segmenter statistics."""
        return {
            "state": self._state.state.name,
            "total_time": self._state.total_time,
            "current_duration": self.current_duration,
            "segments_pending": len(self._segments),
            "speech_frames": self._state.speech_frames,
            "silence_frames": self._state.silence_frames,
        }


# ─────────────────────────────────────────────────────────────────
# Mock Segmenter for Testing
# ─────────────────────────────────────────────────────────────────

class MockSegmenter:
    """Mock segmenter for testing."""
    
    def __init__(self):
        self._segments: List[Segment] = []
        self._return_segment: Optional[Segment] = None
        self._process_count = 0
        self._state = SegmentState.IDLE
    
    def set_return_segment(self, segment: Optional[Segment]) -> None:
        """Set segment to return on next process call."""
        self._return_segment = segment
    
    def add_segment(self, segment: Segment) -> None:
        """Add segment to queue."""
        self._segments.append(segment)
    
    @property
    def state(self) -> SegmentState:
        return self._state
    
    @property
    def is_speaking(self) -> bool:
        return self._state in (SegmentState.SPEAKING, SegmentState.SILENCE)
    
    @property
    def process_count(self) -> int:
        return self._process_count
    
    def process(self, audio_chunk: bytes) -> Optional[Segment]:
        self._process_count += 1
        segment = self._return_segment
        self._return_segment = None
        return segment
    
    def get_segments(self) -> List[Segment]:
        segments = self._segments.copy()
        self._segments.clear()
        return segments
    
    def has_segments(self) -> bool:
        return len(self._segments) > 0
    
    def reset(self) -> None:
        self._segments.clear()
        self._process_count = 0
        self._state = SegmentState.IDLE
    
    def force_complete(self) -> Optional[Segment]:
        return None
    
    def on_segment(self, callback: Callable[[Segment], Any]) -> None:
        pass
    
    def on_speech_start(self, callback: Callable[[], Any]) -> None:
        pass
    
    def on_speech_end(self, callback: Callable[[], Any]) -> None:
        pass
