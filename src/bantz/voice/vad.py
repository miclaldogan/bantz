"""Advanced Voice Activity Detection (Issue #11).

WebRTC VAD with smoothing, energy-based check, and noise adaptation.
"""
from __future__ import annotations

import struct
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

@dataclass
class VADConfig:
    """VAD configuration.
    
    Attributes:
        aggressiveness: WebRTC VAD aggressiveness (0-3, higher = more aggressive)
        sample_rate: Audio sample rate (must be 8000, 16000, 32000, or 48000)
        frame_duration_ms: Frame duration (10, 20, or 30 ms)
        smoothing_window: Number of frames for smoothing
        speech_threshold: Fraction of positive frames to consider speech
        noise_adaptation_rate: Rate of noise floor adaptation
        min_noise_floor: Minimum noise floor value
    """
    aggressiveness: int = 2
    sample_rate: int = 16000
    frame_duration_ms: int = 30
    smoothing_window: int = 10
    speech_threshold: float = 0.6
    noise_adaptation_rate: float = 0.01
    min_noise_floor: float = 0.001


@dataclass
class VADState:
    """VAD internal state.
    
    Attributes:
        history: Recent detection results
        noise_floor: Current noise floor estimate
        frames_processed: Total frames processed
        speech_frames: Total speech frames detected
    """
    history: deque = field(default_factory=lambda: deque(maxlen=10))
    noise_floor: float = 0.01
    frames_processed: int = 0
    speech_frames: int = 0


# ─────────────────────────────────────────────────────────────────
# Advanced VAD
# ─────────────────────────────────────────────────────────────────

class AdvancedVAD:
    """Advanced Voice Activity Detection with WebRTC VAD.
    
    Features:
    - WebRTC VAD core (highly optimized C library)
    - Energy-based speech detection
    - Smoothing over multiple frames
    - Adaptive noise floor
    
    Usage:
        vad = AdvancedVAD()
        
        for chunk in audio_stream:
            if vad.is_speech(chunk):
                # Speech detected
                process_speech(chunk)
            else:
                # Silence - adapt noise floor
                vad.adapt_noise_floor(chunk)
    """
    
    # Valid sample rates for WebRTC VAD
    VALID_SAMPLE_RATES = [8000, 16000, 32000, 48000]
    
    # Valid frame durations
    VALID_FRAME_DURATIONS = [10, 20, 30]
    
    def __init__(self, config: Optional[VADConfig] = None):
        """Initialize VAD.
        
        Args:
            config: VAD configuration
        """
        self.config = config or VADConfig()
        self._validate_config()
        
        self._state = VADState(
            history=deque(maxlen=self.config.smoothing_window),
        )
        
        # Compute frame size in samples
        self.frame_size = int(
            self.config.sample_rate * self.config.frame_duration_ms / 1000
        )
        
        # Frame size in bytes (16-bit audio)
        self.frame_bytes = self.frame_size * 2
        
        # WebRTC VAD (lazy loaded)
        self._vad = None
        
        # Callbacks
        self._on_speech_start: Optional[Callable[[], Any]] = None
        self._on_speech_end: Optional[Callable[[], Any]] = None
        self._was_speech = False
    
    def _validate_config(self) -> None:
        """Validate configuration."""
        if self.config.sample_rate not in self.VALID_SAMPLE_RATES:
            raise ValueError(
                f"Sample rate must be one of {self.VALID_SAMPLE_RATES}"
            )
        
        if self.config.frame_duration_ms not in self.VALID_FRAME_DURATIONS:
            raise ValueError(
                f"Frame duration must be one of {self.VALID_FRAME_DURATIONS}"
            )
        
        if not 0 <= self.config.aggressiveness <= 3:
            raise ValueError("Aggressiveness must be 0-3")
    
    def _ensure_vad(self) -> None:
        """Lazy load WebRTC VAD."""
        if self._vad is not None:
            return
        
        try:
            import webrtcvad
            
            self._vad = webrtcvad.Vad(self.config.aggressiveness)
            
        except ImportError:
            # Fallback to energy-only detection
            self._vad = None
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def sample_rate(self) -> int:
        """Get sample rate."""
        return self.config.sample_rate
    
    @property
    def noise_floor(self) -> float:
        """Get current noise floor estimate."""
        return self._state.noise_floor
    
    @property
    def speech_ratio(self) -> float:
        """Get ratio of speech frames to total frames."""
        if self._state.frames_processed == 0:
            return 0.0
        return self._state.speech_frames / self._state.frames_processed
    
    @property
    def history(self) -> List[bool]:
        """Get recent detection history."""
        return list(self._state.history)
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_speech_start(self, callback: Callable[[], Any]) -> None:
        """Set callback for speech start."""
        self._on_speech_start = callback
    
    def on_speech_end(self, callback: Callable[[], Any]) -> None:
        """Set callback for speech end."""
        self._on_speech_end = callback
    
    # ─────────────────────────────────────────────────────────────
    # Core Detection
    # ─────────────────────────────────────────────────────────────
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        """Detect if chunk contains speech.
        
        Combines WebRTC VAD with energy-based detection and smoothing.
        
        Args:
            audio_chunk: Raw audio bytes (16-bit PCM)
            
        Returns:
            True if speech detected
        """
        self._ensure_vad()
        
        # 1. WebRTC VAD check
        vad_result = self._webrtc_check(audio_chunk)
        
        # 2. Energy-based check
        energy = self._calculate_energy(audio_chunk)
        energy_above_noise = energy > self._state.noise_floor * 2
        
        # 3. Combine results
        if self._vad is not None:
            result = vad_result and energy_above_noise
        else:
            # Fallback: energy-only
            result = energy_above_noise
        
        # 4. Add to history and smooth
        self._state.history.append(result)
        self._state.frames_processed += 1
        
        # 5. Compute smoothed result
        if len(self._state.history) == 0:
            smoothed = result
        else:
            positive_count = sum(self._state.history)
            smoothed = positive_count > len(self._state.history) * self.config.speech_threshold
        
        # 6. Track speech frames
        if smoothed:
            self._state.speech_frames += 1
        
        # 7. Fire callbacks on transitions
        self._check_transitions(smoothed)
        
        return smoothed
    
    def _webrtc_check(self, audio_chunk: bytes) -> bool:
        """Check speech using WebRTC VAD.
        
        Args:
            audio_chunk: Audio bytes
            
        Returns:
            True if WebRTC VAD detects speech
        """
        if self._vad is None:
            return True
        
        try:
            # Ensure chunk is correct size
            if len(audio_chunk) != self.frame_bytes:
                # Pad or truncate
                if len(audio_chunk) < self.frame_bytes:
                    audio_chunk = audio_chunk + b'\x00' * (self.frame_bytes - len(audio_chunk))
                else:
                    audio_chunk = audio_chunk[:self.frame_bytes]
            
            return self._vad.is_speech(audio_chunk, self.config.sample_rate)
            
        except Exception:
            return True  # Assume speech on error
    
    def _calculate_energy(self, audio_chunk: bytes) -> float:
        """Calculate RMS energy of audio chunk.
        
        Args:
            audio_chunk: Audio bytes (16-bit PCM)
            
        Returns:
            RMS energy normalized to 0-1 range
        """
        if len(audio_chunk) == 0:
            return 0.0
        
        try:
            # Convert bytes to samples
            num_samples = len(audio_chunk) // 2
            if num_samples == 0:
                return 0.0
            
            samples = struct.unpack(f'<{num_samples}h', audio_chunk[:num_samples * 2])
            
            # Calculate RMS
            sum_squares = sum(s * s for s in samples)
            rms = (sum_squares / num_samples) ** 0.5
            
            # Normalize to 0-1 (16-bit audio max is 32767)
            return rms / 32767.0
            
        except Exception:
            return 0.0
    
    def _check_transitions(self, is_speech: bool) -> None:
        """Check for speech start/end transitions.
        
        Args:
            is_speech: Current speech state
        """
        if is_speech and not self._was_speech:
            # Speech started
            if self._on_speech_start:
                try:
                    self._on_speech_start()
                except Exception:
                    pass
        
        elif not is_speech and self._was_speech:
            # Speech ended
            if self._on_speech_end:
                try:
                    self._on_speech_end()
                except Exception:
                    pass
        
        self._was_speech = is_speech
    
    # ─────────────────────────────────────────────────────────────
    # Noise Adaptation
    # ─────────────────────────────────────────────────────────────
    
    def adapt_noise_floor(self, audio_chunk: bytes) -> None:
        """Adapt noise floor based on current audio.
        
        Should be called during silence to update noise estimate.
        
        Args:
            audio_chunk: Audio bytes (assumed to be silence/noise)
        """
        energy = self._calculate_energy(audio_chunk)
        
        # Only adapt if this doesn't look like speech
        if not self.is_speech(audio_chunk):
            self._state.noise_floor = (
                (1 - self.config.noise_adaptation_rate) * self._state.noise_floor +
                self.config.noise_adaptation_rate * energy
            )
            
            # Enforce minimum
            self._state.noise_floor = max(
                self._state.noise_floor,
                self.config.min_noise_floor,
            )
    
    def reset_noise_floor(self, value: Optional[float] = None) -> None:
        """Reset noise floor to default or specified value.
        
        Args:
            value: New noise floor value (default 0.01)
        """
        self._state.noise_floor = value if value is not None else 0.01
    
    # ─────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────
    
    def reset(self) -> None:
        """Reset all state."""
        self._state = VADState(
            history=deque(maxlen=self.config.smoothing_window),
        )
        self._was_speech = False
    
    def get_stats(self) -> dict:
        """Get VAD statistics.
        
        Returns:
            Dictionary with stats
        """
        return {
            "frames_processed": self._state.frames_processed,
            "speech_frames": self._state.speech_frames,
            "speech_ratio": self.speech_ratio,
            "noise_floor": self._state.noise_floor,
            "history_length": len(self._state.history),
        }


# ─────────────────────────────────────────────────────────────────
# Simple Energy VAD (Fallback)
# ─────────────────────────────────────────────────────────────────

class EnergyVAD:
    """Simple energy-based VAD (no external dependencies).
    
    Fallback when WebRTC VAD is not available.
    
    Usage:
        vad = EnergyVAD(threshold=0.02)
        
        if vad.is_speech(chunk):
            # Speech detected
            pass
    """
    
    def __init__(
        self,
        threshold: float = 0.02,
        sample_rate: int = 16000,
        smoothing_window: int = 5,
    ):
        """Initialize energy VAD.
        
        Args:
            threshold: Energy threshold for speech detection
            sample_rate: Audio sample rate
            smoothing_window: Frames to smooth over
        """
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._history = deque(maxlen=smoothing_window)
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        """Detect speech based on energy.
        
        Args:
            audio_chunk: Audio bytes
            
        Returns:
            True if speech detected
        """
        energy = self._calculate_energy(audio_chunk)
        result = energy > self.threshold
        
        self._history.append(result)
        
        if len(self._history) == 0:
            return result
        
        return sum(self._history) > len(self._history) * 0.5
    
    def _calculate_energy(self, audio_chunk: bytes) -> float:
        """Calculate RMS energy."""
        if len(audio_chunk) == 0:
            return 0.0
        
        try:
            num_samples = len(audio_chunk) // 2
            if num_samples == 0:
                return 0.0
            
            samples = struct.unpack(f'<{num_samples}h', audio_chunk[:num_samples * 2])
            sum_squares = sum(s * s for s in samples)
            rms = (sum_squares / num_samples) ** 0.5
            
            return rms / 32767.0
            
        except Exception:
            return 0.0
    
    def reset(self) -> None:
        """Reset history."""
        self._history.clear()


# ─────────────────────────────────────────────────────────────────
# Mock VAD for Testing
# ─────────────────────────────────────────────────────────────────

class MockVAD:
    """Mock VAD for testing."""
    
    def __init__(self):
        self._speech_pattern: List[bool] = []
        self._pattern_index = 0
        self._default_result = False
        self.sample_rate = 16000
        self.frame_size = 480
        self._state = VADState()
        self._callbacks_fired: List[str] = []
    
    def set_speech_pattern(self, pattern: List[bool]) -> None:
        """Set pattern of speech/silence results."""
        self._speech_pattern = pattern
        self._pattern_index = 0
    
    def set_default_result(self, result: bool) -> None:
        """Set default result when pattern exhausted."""
        self._default_result = result
    
    @property
    def noise_floor(self) -> float:
        return self._state.noise_floor
    
    @property
    def callbacks_fired(self) -> List[str]:
        return self._callbacks_fired
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        if self._pattern_index < len(self._speech_pattern):
            result = self._speech_pattern[self._pattern_index]
            self._pattern_index += 1
            return result
        return self._default_result
    
    def adapt_noise_floor(self, audio_chunk: bytes) -> None:
        pass
    
    def reset(self) -> None:
        self._pattern_index = 0
        self._callbacks_fired.clear()
    
    def on_speech_start(self, callback: Callable[[], Any]) -> None:
        self._callbacks_fired.append("on_speech_start_registered")
    
    def on_speech_end(self, callback: Callable[[], Any]) -> None:
        self._callbacks_fired.append("on_speech_end_registered")
