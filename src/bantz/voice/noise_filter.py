"""Noise Filter (Issue #11).

Background noise filtering using noisereduce library.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional, List, Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

@dataclass
class NoiseFilterConfig:
    """Noise filter configuration.
    
    Attributes:
        sample_rate: Audio sample rate
        prop_decrease: Proportion of noise to reduce (0.0 to 1.0)
        stationary: Use stationary noise reduction
        use_torch: Use PyTorch for faster processing
        n_fft: FFT size for spectral analysis
        hop_length: Hop length between frames
    """
    sample_rate: int = 16000
    prop_decrease: float = 0.8
    stationary: bool = True
    use_torch: bool = False
    n_fft: int = 512
    hop_length: int = 128


# ─────────────────────────────────────────────────────────────────
# Noise Filter
# ─────────────────────────────────────────────────────────────────

class NoiseFilter:
    """Background noise filter using noisereduce.
    
    Features:
    - Stationary noise reduction
    - Adaptive noise profile
    - Real-time compatible
    
    Usage:
        noise_filter = NoiseFilter()
        
        # Collect noise sample during silence
        noise_filter.set_noise_sample(noise_audio)
        
        # Filter audio
        clean_audio = noise_filter.filter(audio)
    """
    
    def __init__(self, config: Optional[NoiseFilterConfig] = None):
        """Initialize noise filter.
        
        Args:
            config: Filter configuration
        """
        self.config = config or NoiseFilterConfig()
        
        self._noise_sample: Optional[np.ndarray] = None
        self._noise_sample_bytes: Optional[bytes] = None
        
        # Check if noisereduce is available
        self._noisereduce_available = self._check_noisereduce()
    
    def _check_noisereduce(self) -> bool:
        """Check if noisereduce library is available."""
        try:
            import noisereduce
            return True
        except ImportError:
            return False
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def is_available(self) -> bool:
        """Check if noise reduction is available."""
        return self._noisereduce_available
    
    @property
    def has_noise_sample(self) -> bool:
        """Check if noise sample is set."""
        return self._noise_sample is not None
    
    @property
    def sample_rate(self) -> int:
        """Get sample rate."""
        return self.config.sample_rate
    
    # ─────────────────────────────────────────────────────────────
    # Noise Sample
    # ─────────────────────────────────────────────────────────────
    
    def set_noise_sample(self, audio: bytes) -> None:
        """Set noise sample for reduction.
        
        Collect a sample of background noise during silence
        to use as a reference for reduction.
        
        Args:
            audio: Raw audio bytes (16-bit PCM)
        """
        self._noise_sample_bytes = audio
        self._noise_sample = self._bytes_to_array(audio)
    
    def set_noise_sample_array(self, audio: np.ndarray) -> None:
        """Set noise sample from numpy array.
        
        Args:
            audio: Audio as numpy array
        """
        self._noise_sample = audio
        self._noise_sample_bytes = self._array_to_bytes(audio)
    
    def clear_noise_sample(self) -> None:
        """Clear the noise sample."""
        self._noise_sample = None
        self._noise_sample_bytes = None
    
    # ─────────────────────────────────────────────────────────────
    # Core Filtering
    # ─────────────────────────────────────────────────────────────
    
    def filter(self, audio: bytes) -> bytes:
        """Filter noise from audio.
        
        Args:
            audio: Raw audio bytes (16-bit PCM)
            
        Returns:
            Filtered audio bytes
        """
        if not self._noisereduce_available:
            return audio
        
        if len(audio) == 0:
            return audio
        
        # Convert to numpy
        audio_array = self._bytes_to_array(audio)
        
        # Filter
        filtered_array = self.filter_array(audio_array)
        
        # Convert back
        return self._array_to_bytes(filtered_array)
    
    def filter_array(self, audio: np.ndarray) -> np.ndarray:
        """Filter noise from numpy array.
        
        Args:
            audio: Audio as numpy array
            
        Returns:
            Filtered audio array
        """
        if not self._noisereduce_available:
            return audio
        
        if len(audio) == 0:
            return audio
        
        try:
            import noisereduce as nr
            
            # Use stationary reduction if enabled
            if self.config.stationary:
                filtered = nr.reduce_noise(
                    y=audio.astype(np.float32),
                    sr=self.config.sample_rate,
                    stationary=True,
                    prop_decrease=self.config.prop_decrease,
                    n_fft=self.config.n_fft,
                    hop_length=self.config.hop_length,
                    use_torch=self.config.use_torch,
                )
            else:
                # Use noise sample if available
                y_noise = self._noise_sample if self._noise_sample is not None else None
                
                filtered = nr.reduce_noise(
                    y=audio.astype(np.float32),
                    sr=self.config.sample_rate,
                    y_noise=y_noise,
                    stationary=False,
                    prop_decrease=self.config.prop_decrease,
                    n_fft=self.config.n_fft,
                    hop_length=self.config.hop_length,
                    use_torch=self.config.use_torch,
                )
            
            return filtered.astype(audio.dtype)
            
        except Exception:
            return audio
    
    # ─────────────────────────────────────────────────────────────
    # Conversion Utilities
    # ─────────────────────────────────────────────────────────────
    
    def _bytes_to_array(self, audio: bytes) -> np.ndarray:
        """Convert bytes to numpy array.
        
        Args:
            audio: Raw audio bytes (16-bit PCM)
            
        Returns:
            Audio as float32 array normalized to [-1, 1]
        """
        if len(audio) == 0:
            return np.array([], dtype=np.float32)
        
        # Convert to int16 samples
        num_samples = len(audio) // 2
        samples = np.frombuffer(audio[:num_samples * 2], dtype=np.int16)
        
        # Convert to float32 normalized
        return samples.astype(np.float32) / 32767.0
    
    def _array_to_bytes(self, audio: np.ndarray) -> bytes:
        """Convert numpy array to bytes.
        
        Args:
            audio: Audio as float32 array [-1, 1]
            
        Returns:
            Raw audio bytes (16-bit PCM)
        """
        if len(audio) == 0:
            return b''
        
        # Clip to valid range
        audio = np.clip(audio, -1.0, 1.0)
        
        # Convert to int16
        samples = (audio * 32767).astype(np.int16)
        
        return samples.tobytes()
    
    # ─────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────
    
    def get_stats(self) -> dict:
        """Get filter statistics."""
        return {
            "is_available": self.is_available,
            "has_noise_sample": self.has_noise_sample,
            "prop_decrease": self.config.prop_decrease,
            "stationary": self.config.stationary,
        }


# ─────────────────────────────────────────────────────────────────
# Simple Noise Filter (Fallback)
# ─────────────────────────────────────────────────────────────────

class SimpleNoiseFilter:
    """Simple noise gate filter (no external dependencies).
    
    Fallback when noisereduce is not available.
    Simply zeroes out samples below a threshold.
    """
    
    def __init__(
        self,
        threshold: float = 0.02,
        sample_rate: int = 16000,
    ):
        """Initialize simple noise filter.
        
        Args:
            threshold: Amplitude threshold (0-1)
            sample_rate: Audio sample rate
        """
        self.threshold = threshold
        self.sample_rate = sample_rate
    
    @property
    def is_available(self) -> bool:
        """Always available."""
        return True
    
    @property
    def has_noise_sample(self) -> bool:
        """No noise sample needed."""
        return True
    
    def set_noise_sample(self, audio: bytes) -> None:
        """No-op for simple filter."""
        pass
    
    def clear_noise_sample(self) -> None:
        """No-op for simple filter."""
        pass
    
    def filter(self, audio: bytes) -> bytes:
        """Apply simple noise gate.
        
        Args:
            audio: Raw audio bytes
            
        Returns:
            Filtered audio bytes
        """
        if len(audio) == 0:
            return audio
        
        # Convert to numpy
        num_samples = len(audio) // 2
        samples = np.frombuffer(audio[:num_samples * 2], dtype=np.int16)
        
        # Convert to float
        float_samples = samples.astype(np.float32) / 32767.0
        
        # Apply noise gate
        mask = np.abs(float_samples) > self.threshold
        filtered = float_samples * mask
        
        # Convert back
        int_samples = (filtered * 32767).astype(np.int16)
        
        return int_samples.tobytes()
    
    def filter_array(self, audio: np.ndarray) -> np.ndarray:
        """Apply simple noise gate to array.
        
        Args:
            audio: Audio as numpy array
            
        Returns:
            Filtered audio array
        """
        mask = np.abs(audio) > self.threshold
        return audio * mask


# ─────────────────────────────────────────────────────────────────
# Spectral Subtraction Filter
# ─────────────────────────────────────────────────────────────────

class SpectralSubtractionFilter:
    """Spectral subtraction noise filter.
    
    More sophisticated than noise gate, less computationally
    expensive than full noisereduce.
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        n_fft: int = 512,
        hop_length: int = 128,
        alpha: float = 2.0,
        beta: float = 0.1,
    ):
        """Initialize spectral subtraction filter.
        
        Args:
            sample_rate: Audio sample rate
            n_fft: FFT size
            hop_length: Hop length
            alpha: Over-subtraction factor
            beta: Spectral floor
        """
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.alpha = alpha
        self.beta = beta
        
        self._noise_spectrum: Optional[np.ndarray] = None
    
    @property
    def is_available(self) -> bool:
        return True
    
    @property
    def has_noise_sample(self) -> bool:
        return self._noise_spectrum is not None
    
    def set_noise_sample(self, audio: bytes) -> None:
        """Estimate noise spectrum from sample.
        
        Args:
            audio: Noise sample bytes
        """
        if len(audio) < self.n_fft * 2:
            return
        
        # Convert to array
        num_samples = len(audio) // 2
        samples = np.frombuffer(audio[:num_samples * 2], dtype=np.int16)
        float_samples = samples.astype(np.float32) / 32767.0
        
        # Estimate spectrum
        self._estimate_noise_spectrum(float_samples)
    
    def set_noise_sample_array(self, audio: np.ndarray) -> None:
        """Set noise sample from array."""
        self._estimate_noise_spectrum(audio)
    
    def _estimate_noise_spectrum(self, audio: np.ndarray) -> None:
        """Estimate noise spectrum using average magnitude."""
        if len(audio) < self.n_fft:
            return
        
        # Simple FFT-based estimation
        num_frames = (len(audio) - self.n_fft) // self.hop_length + 1
        if num_frames <= 0:
            return
        
        spectrum_sum = np.zeros(self.n_fft // 2 + 1)
        
        for i in range(num_frames):
            start = i * self.hop_length
            frame = audio[start:start + self.n_fft]
            
            if len(frame) < self.n_fft:
                frame = np.pad(frame, (0, self.n_fft - len(frame)))
            
            # Apply window
            windowed = frame * np.hanning(self.n_fft)
            
            # FFT
            fft = np.fft.rfft(windowed)
            spectrum_sum += np.abs(fft)
        
        self._noise_spectrum = spectrum_sum / num_frames
    
    def clear_noise_sample(self) -> None:
        """Clear noise spectrum."""
        self._noise_spectrum = None
    
    def filter(self, audio: bytes) -> bytes:
        """Apply spectral subtraction.
        
        Args:
            audio: Raw audio bytes
            
        Returns:
            Filtered audio bytes
        """
        if len(audio) == 0:
            return audio
        
        if self._noise_spectrum is None:
            return audio
        
        # Convert
        num_samples = len(audio) // 2
        samples = np.frombuffer(audio[:num_samples * 2], dtype=np.int16)
        float_samples = samples.astype(np.float32) / 32767.0
        
        # Filter
        filtered = self.filter_array(float_samples)
        
        # Convert back
        int_samples = (np.clip(filtered, -1.0, 1.0) * 32767).astype(np.int16)
        
        return int_samples.tobytes()
    
    def filter_array(self, audio: np.ndarray) -> np.ndarray:
        """Apply spectral subtraction to array."""
        if self._noise_spectrum is None or len(audio) < self.n_fft:
            return audio
        
        # Process frame by frame
        num_frames = (len(audio) - self.n_fft) // self.hop_length + 1
        output = np.zeros_like(audio)
        window = np.hanning(self.n_fft)
        
        for i in range(num_frames):
            start = i * self.hop_length
            end = start + self.n_fft
            
            frame = audio[start:end]
            if len(frame) < self.n_fft:
                break
            
            # Apply window and FFT
            windowed = frame * window
            fft = np.fft.rfft(windowed)
            
            # Spectral subtraction
            magnitude = np.abs(fft)
            phase = np.angle(fft)
            
            # Subtract noise
            clean_magnitude = magnitude - self.alpha * self._noise_spectrum
            clean_magnitude = np.maximum(clean_magnitude, self.beta * magnitude)
            
            # Reconstruct
            clean_fft = clean_magnitude * np.exp(1j * phase)
            clean_frame = np.fft.irfft(clean_fft, n=self.n_fft)
            
            # Overlap-add
            output[start:end] += clean_frame * window
        
        return output


# ─────────────────────────────────────────────────────────────────
# Mock Filter for Testing
# ─────────────────────────────────────────────────────────────────

class MockNoiseFilter:
    """Mock noise filter for testing."""
    
    def __init__(self):
        self._noise_sample: Optional[bytes] = None
        self._filter_count = 0
        self._passthrough = True
    
    @property
    def is_available(self) -> bool:
        return True
    
    @property
    def has_noise_sample(self) -> bool:
        return self._noise_sample is not None
    
    @property
    def sample_rate(self) -> int:
        return 16000
    
    @property
    def filter_count(self) -> int:
        return self._filter_count
    
    def set_passthrough(self, enabled: bool) -> None:
        """Enable/disable passthrough mode."""
        self._passthrough = enabled
    
    def set_noise_sample(self, audio: bytes) -> None:
        self._noise_sample = audio
    
    def clear_noise_sample(self) -> None:
        self._noise_sample = None
    
    def filter(self, audio: bytes) -> bytes:
        self._filter_count += 1
        if self._passthrough:
            return audio
        # Return silence
        return b'\x00' * len(audio)
    
    def filter_array(self, audio: np.ndarray) -> np.ndarray:
        self._filter_count += 1
        if self._passthrough:
            return audio
        return np.zeros_like(audio)
    
    def get_stats(self) -> dict:
        return {
            "is_available": True,
            "has_noise_sample": self.has_noise_sample,
            "filter_count": self._filter_count,
        }
