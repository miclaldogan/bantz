"""Advanced TTS Interface (Issue #10).

Provides emotion control, speed adjustment, and streaming audio output.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Optional, Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class Emotion(Enum):
    """TTS emotion types for expressive speech."""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SERIOUS = "serious"
    CONCERNED = "concerned"
    EXCITED = "excited"
    CALM = "calm"
    ANGRY = "angry"


class TTSBackend(Enum):
    """Available TTS backends."""
    PIPER = "piper"
    COQUI = "coqui"
    XTTS = "xtts"
    EDGE = "edge"


# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────

@dataclass
class TTSConfig:
    """TTS configuration for speech synthesis.
    
    Attributes:
        speed: Speech rate multiplier (0.5 = half speed, 2.0 = double speed)
        pitch: Voice pitch multiplier (0.5 = lower, 2.0 = higher)
        volume: Output volume (0.0 = silent, 1.0 = full)
        emotion: Emotional tone of speech
        language: Language code (e.g., "tr", "en")
        voice: Voice model name or path
    """
    speed: float = 1.0          # 0.5 - 2.0
    pitch: float = 1.0          # 0.5 - 2.0
    volume: float = 1.0         # 0.0 - 1.0
    emotion: Emotion = Emotion.NEUTRAL
    language: str = "tr"
    voice: Optional[str] = None
    
    def __post_init__(self):
        """Validate config values."""
        self.speed = max(0.5, min(2.0, self.speed))
        self.pitch = max(0.5, min(2.0, self.pitch))
        self.volume = max(0.0, min(1.0, self.volume))


@dataclass
class TTSResult:
    """Result from TTS synthesis.
    
    Attributes:
        audio_data: Raw audio bytes (PCM or WAV)
        sample_rate: Audio sample rate (Hz)
        duration_ms: Audio duration in milliseconds
        format: Audio format ("wav", "pcm", "mp3")
    """
    audio_data: bytes
    sample_rate: int = 22050
    duration_ms: int = 0
    format: str = "wav"


@dataclass
class TTSChunk:
    """Audio chunk for streaming TTS.
    
    Attributes:
        data: Audio bytes for this chunk
        index: Chunk sequence number
        is_last: True if this is the final chunk
        text_offset: Character offset in original text
    """
    data: bytes
    index: int
    is_last: bool = False
    text_offset: int = 0


# ─────────────────────────────────────────────────────────────────
# Abstract Base Class
# ─────────────────────────────────────────────────────────────────

class AdvancedTTS(ABC):
    """Abstract base class for Advanced TTS backends.
    
    Features:
    - Emotion control
    - Speed/pitch adjustment
    - Streaming audio output
    - Voice interrupt (stop mid-speech)
    - Multiple voice models
    
    Usage:
        tts = CoquiTTS()
        
        # Simple speak
        tts.speak("Merhaba efendim")
        
        # With config
        config = TTSConfig(speed=1.2, emotion=Emotion.HAPPY)
        tts.speak("Harika bir haber var!", config)
        
        # Async speak
        task = tts.speak_async("Bu işi yapıyorum...")
        # Do other things...
        await task
        
        # Streaming
        for chunk in tts.stream("Uzun bir metin..."):
            player.add_chunk(chunk.data)
        
        # Stop mid-speech
        tts.stop()
    """
    
    def __init__(self):
        """Initialize TTS."""
        self._is_speaking = False
        self._current_task: Optional[asyncio.Task] = None
        self._stop_requested = False
        self._sample_rate = 22050
        self._on_start_callbacks: list[Callable[[], Any]] = []
        self._on_stop_callbacks: list[Callable[[], Any]] = []
    
    @property
    def is_speaking(self) -> bool:
        """Check if currently speaking."""
        return self._is_speaking
    
    @property
    def sample_rate(self) -> int:
        """Get audio sample rate."""
        return self._sample_rate
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_start(self, callback: Callable[[], Any]) -> None:
        """Register callback for when speech starts."""
        self._on_start_callbacks.append(callback)
    
    def on_stop(self, callback: Callable[[], Any]) -> None:
        """Register callback for when speech stops."""
        self._on_stop_callbacks.append(callback)
    
    def _notify_start(self) -> None:
        """Notify start callbacks."""
        for cb in self._on_start_callbacks:
            try:
                cb()
            except Exception:
                pass
    
    def _notify_stop(self) -> None:
        """Notify stop callbacks."""
        for cb in self._on_stop_callbacks:
            try:
                cb()
            except Exception:
                pass
    
    # ─────────────────────────────────────────────────────────────
    # Abstract Methods (must implement)
    # ─────────────────────────────────────────────────────────────
    
    @abstractmethod
    def synthesize(self, text: str, config: Optional[TTSConfig] = None) -> TTSResult:
        """Synthesize text to audio.
        
        Args:
            text: Text to synthesize
            config: TTS configuration
            
        Returns:
            TTSResult with audio data
        """
        pass
    
    @abstractmethod
    def synthesize_stream(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
    ) -> Iterator[TTSChunk]:
        """Synthesize text to streaming audio chunks.
        
        Args:
            text: Text to synthesize
            config: TTS configuration
            
        Yields:
            TTSChunk objects with audio data
        """
        pass
    
    # ─────────────────────────────────────────────────────────────
    # Playback Methods
    # ─────────────────────────────────────────────────────────────
    
    def speak(self, text: str, config: Optional[TTSConfig] = None) -> None:
        """Speak text synchronously (blocking).
        
        Args:
            text: Text to speak
            config: TTS configuration
        """
        text = (text or "").strip()
        if not text:
            return
        
        self._is_speaking = True
        self._stop_requested = False
        self._notify_start()
        
        try:
            result = self.synthesize(text, config)
            self._play_audio(result)
        finally:
            self._is_speaking = False
            self._notify_stop()
    
    def speak_async(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
    ) -> asyncio.Task:
        """Speak text asynchronously (non-blocking).
        
        Args:
            text: Text to speak
            config: TTS configuration
            
        Returns:
            asyncio.Task that can be awaited or cancelled
        """
        async def _speak():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.speak, text, config)
        
        self._current_task = asyncio.create_task(_speak())
        return self._current_task
    
    def stream(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
    ) -> Iterator[TTSChunk]:
        """Stream audio chunks for real-time playback.
        
        Args:
            text: Text to stream
            config: TTS configuration
            
        Yields:
            TTSChunk objects with audio data
        """
        text = (text or "").strip()
        if not text:
            return
        
        self._is_speaking = True
        self._stop_requested = False
        self._notify_start()
        
        try:
            for chunk in self.synthesize_stream(text, config):
                if self._stop_requested:
                    break
                yield chunk
        finally:
            self._is_speaking = False
            self._notify_stop()
    
    def stop(self) -> None:
        """Stop current speech immediately."""
        self._stop_requested = True
        
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        
        self._is_speaking = False
        self._notify_stop()
    
    # ─────────────────────────────────────────────────────────────
    # Voice Management
    # ─────────────────────────────────────────────────────────────
    
    @abstractmethod
    def list_voices(self) -> list[str]:
        """List available voice models.
        
        Returns:
            List of voice model names
        """
        pass
    
    @abstractmethod
    def set_voice(self, voice_name: str) -> bool:
        """Change voice model.
        
        Args:
            voice_name: Voice model name or path
            
        Returns:
            True if successful
        """
        pass
    
    @property
    @abstractmethod
    def current_voice(self) -> str:
        """Get current voice model name."""
        pass
    
    # ─────────────────────────────────────────────────────────────
    # Audio Utilities
    # ─────────────────────────────────────────────────────────────
    
    def _play_audio(self, result: TTSResult) -> None:
        """Play audio result using system player.
        
        Args:
            result: TTSResult with audio data
        """
        import shutil
        import subprocess
        import tempfile
        
        # Write to temp file
        with tempfile.NamedTemporaryFile(
            prefix="bantz_tts_",
            suffix=f".{result.format}",
            delete=False,
        ) as f:
            f.write(result.audio_data)
            temp_path = f.name
        
        # Find player
        player = shutil.which("paplay") or shutil.which("aplay")
        if not player:
            raise RuntimeError("Audio player not found (paplay/aplay).")
        
        # Play
        proc = subprocess.Popen(
            [player, temp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait()
    
    @staticmethod
    def adjust_speed(audio_data: bytes, speed: float, sample_rate: int) -> bytes:
        """Adjust audio speed using time stretching.
        
        Args:
            audio_data: Raw PCM audio bytes
            speed: Speed multiplier (0.5 - 2.0)
            sample_rate: Audio sample rate
            
        Returns:
            Speed-adjusted audio bytes
        """
        if speed == 1.0:
            return audio_data
        
        try:
            import numpy as np
            from scipy import signal
            
            # Convert bytes to numpy array
            audio = np.frombuffer(audio_data, dtype=np.float32)
            
            # Resample to change speed
            new_length = int(len(audio) / speed)
            audio_resampled = signal.resample(audio, new_length)
            
            return audio_resampled.astype(np.float32).tobytes()
            
        except ImportError:
            # Fallback: no speed adjustment without scipy
            return audio_data
    
    @staticmethod
    def adjust_pitch(audio_data: bytes, pitch: float, sample_rate: int) -> bytes:
        """Adjust audio pitch.
        
        Args:
            audio_data: Raw PCM audio bytes
            pitch: Pitch multiplier (0.5 - 2.0)
            sample_rate: Audio sample rate
            
        Returns:
            Pitch-adjusted audio bytes
        """
        if pitch == 1.0:
            return audio_data
        
        try:
            import numpy as np
            from scipy import signal
            
            audio = np.frombuffer(audio_data, dtype=np.float32)
            
            # Simple pitch shift via resampling
            # This also affects speed, so we need to time-stretch back
            new_length = int(len(audio) / pitch)
            audio_pitched = signal.resample(audio, new_length)
            
            # Resample back to original length to maintain duration
            audio_final = signal.resample(audio_pitched, len(audio))
            
            return audio_final.astype(np.float32).tobytes()
            
        except ImportError:
            return audio_data
    
    @staticmethod
    def adjust_volume(audio_data: bytes, volume: float) -> bytes:
        """Adjust audio volume.
        
        Args:
            audio_data: Raw PCM audio bytes
            volume: Volume multiplier (0.0 - 1.0)
            
        Returns:
            Volume-adjusted audio bytes
        """
        if volume == 1.0:
            return audio_data
        
        try:
            import numpy as np
            
            audio = np.frombuffer(audio_data, dtype=np.float32)
            audio = audio * volume
            audio = np.clip(audio, -1.0, 1.0)
            
            return audio.astype(np.float32).tobytes()
            
        except ImportError:
            return audio_data


# ─────────────────────────────────────────────────────────────────
# Mock TTS for Testing
# ─────────────────────────────────────────────────────────────────

class MockTTS(AdvancedTTS):
    """Mock TTS for testing without actual audio."""
    
    def __init__(self):
        super().__init__()
        self._voice = "mock_voice"
        self._voices = ["mock_voice", "mock_voice_2"]
        self._speak_calls: list[tuple[str, Optional[TTSConfig]]] = []
    
    @property
    def speak_calls(self) -> list[tuple[str, Optional[TTSConfig]]]:
        """Get list of speak calls for verification."""
        return self._speak_calls
    
    def synthesize(self, text: str, config: Optional[TTSConfig] = None) -> TTSResult:
        """Mock synthesize - returns empty audio."""
        self._speak_calls.append((text, config))
        # Return empty wav header + silence
        return TTSResult(
            audio_data=b"RIFF" + b"\x00" * 40,
            sample_rate=22050,
            duration_ms=len(text) * 50,  # ~50ms per char
            format="wav",
        )
    
    def synthesize_stream(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
    ) -> Iterator[TTSChunk]:
        """Mock stream - yields empty chunks."""
        self._speak_calls.append((text, config))
        
        # Split into chunks of ~10 chars
        chunk_size = 10
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i:i + chunk_size]
            is_last = i + chunk_size >= len(text)
            yield TTSChunk(
                data=b"\x00" * 1024,
                index=i // chunk_size,
                is_last=is_last,
                text_offset=i,
            )
    
    def list_voices(self) -> list[str]:
        return self._voices
    
    def set_voice(self, voice_name: str) -> bool:
        if voice_name in self._voices:
            self._voice = voice_name
            return True
        return False
    
    @property
    def current_voice(self) -> str:
        return self._voice
    
    def _play_audio(self, result: TTSResult) -> None:
        """Mock play - does nothing."""
        pass
