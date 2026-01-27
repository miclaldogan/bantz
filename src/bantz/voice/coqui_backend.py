"""Coqui TTS Backend (Issue #10).

Provides Coqui TTS and XTTS integration for advanced speech synthesis.
"""
from __future__ import annotations

import io
import wave
from typing import Iterator, Optional, List, TYPE_CHECKING

from bantz.voice.advanced_tts import (
    AdvancedTTS,
    TTSConfig,
    TTSResult,
    TTSChunk,
    Emotion,
)

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────
# Coqui TTS Backend
# ─────────────────────────────────────────────────────────────────

class CoquiTTS(AdvancedTTS):
    """Coqui TTS backend with Turkish support.
    
    Uses the TTS library from Coqui AI for high-quality speech synthesis.
    Supports speed control, multiple voices, and emotion hints.
    
    Usage:
        tts = CoquiTTS()
        tts.speak("Merhaba efendim")
        
        # With speed control
        config = TTSConfig(speed=1.5)
        tts.speak("Hızlı konuşuyorum", config)
    """
    
    # Default Turkish model
    DEFAULT_MODEL = "tts_models/tr/common-voice/glow-tts"
    
    # Available Turkish models
    TURKISH_MODELS = [
        "tts_models/tr/common-voice/glow-tts",
        "tts_models/multilingual/multi-dataset/your_tts",
        "tts_models/multilingual/multi-dataset/xtts_v2",
    ]
    
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        use_cuda: bool = False,
    ):
        """Initialize Coqui TTS.
        
        Args:
            model: Model name or path
            use_cuda: Use GPU acceleration
        """
        super().__init__()
        self._model_name = model
        self._use_cuda = use_cuda
        self._tts = None
        self._sample_rate = 22050
    
    def _ensure_loaded(self) -> None:
        """Lazy load TTS model."""
        if self._tts is not None:
            return
        
        try:
            from TTS.api import TTS
            
            self._tts = TTS(self._model_name, gpu=self._use_cuda)
            
            # Get sample rate from model
            if hasattr(self._tts, "synthesizer") and self._tts.synthesizer:
                self._sample_rate = self._tts.synthesizer.output_sample_rate
            
        except ImportError:
            raise ImportError(
                "Coqui TTS not installed. "
                "Install with: pip install TTS"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load Coqui TTS model: {e}")
    
    def synthesize(self, text: str, config: Optional[TTSConfig] = None) -> TTSResult:
        """Synthesize text to audio.
        
        Args:
            text: Text to synthesize
            config: TTS configuration
            
        Returns:
            TTSResult with WAV audio data
        """
        self._ensure_loaded()
        config = config or TTSConfig()
        
        # Generate audio
        wav = self._tts.tts(text)
        
        # Convert to bytes
        import numpy as np
        
        wav_array = np.array(wav, dtype=np.float32)
        
        # Apply adjustments
        if config.speed != 1.0:
            wav_bytes = wav_array.tobytes()
            wav_bytes = self.adjust_speed(wav_bytes, config.speed, self._sample_rate)
            wav_array = np.frombuffer(wav_bytes, dtype=np.float32)
        
        if config.pitch != 1.0:
            wav_bytes = wav_array.tobytes()
            wav_bytes = self.adjust_pitch(wav_bytes, config.pitch, self._sample_rate)
            wav_array = np.frombuffer(wav_bytes, dtype=np.float32)
        
        if config.volume != 1.0:
            wav_array = wav_array * config.volume
            wav_array = np.clip(wav_array, -1.0, 1.0)
        
        # Convert to WAV format
        wav_bytes = self._to_wav(wav_array)
        
        duration_ms = int(len(wav_array) / self._sample_rate * 1000)
        
        return TTSResult(
            audio_data=wav_bytes,
            sample_rate=self._sample_rate,
            duration_ms=duration_ms,
            format="wav",
        )
    
    def synthesize_stream(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
    ) -> Iterator[TTSChunk]:
        """Synthesize text to streaming chunks.
        
        Note: Coqui TTS doesn't support native streaming,
        so we synthesize full audio and chunk it.
        
        Args:
            text: Text to synthesize
            config: TTS configuration
            
        Yields:
            TTSChunk objects
        """
        result = self.synthesize(text, config)
        
        # Chunk the audio
        chunk_size = 4096  # bytes per chunk
        data = result.audio_data
        
        # Skip WAV header for streaming
        # WAV header is 44 bytes
        header_size = 44
        audio_data = data[header_size:]
        
        total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(audio_data), chunk_size):
            chunk_data = audio_data[i:i + chunk_size]
            chunk_index = i // chunk_size
            is_last = chunk_index == total_chunks - 1
            
            yield TTSChunk(
                data=chunk_data,
                index=chunk_index,
                is_last=is_last,
                text_offset=0,
            )
    
    def list_voices(self) -> list[str]:
        """List available voice models."""
        return self.TURKISH_MODELS
    
    def set_voice(self, voice_name: str) -> bool:
        """Change voice model.
        
        Args:
            voice_name: Model name
            
        Returns:
            True if successful
        """
        if voice_name not in self.TURKISH_MODELS:
            return False
        
        self._model_name = voice_name
        self._tts = None  # Will reload on next use
        return True
    
    @property
    def current_voice(self) -> str:
        """Get current voice model."""
        return self._model_name
    
    def _to_wav(self, audio_array) -> bytes:
        """Convert numpy array to WAV bytes.
        
        Args:
            audio_array: Float32 numpy array
            
        Returns:
            WAV file bytes
        """
        import numpy as np
        
        # Convert to int16
        audio_int16 = (audio_array * 32767).astype(np.int16)
        
        # Create WAV in memory
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(audio_int16.tobytes())
        
        return buffer.getvalue()


# ─────────────────────────────────────────────────────────────────
# XTTS Backend (Voice Cloning)
# ─────────────────────────────────────────────────────────────────

class XTTS(AdvancedTTS):
    """XTTS backend for voice cloning and high-quality multilingual TTS.
    
    Features:
    - Voice cloning from reference audio
    - High-quality multilingual synthesis
    - Emotion control through reference audio selection
    
    Usage:
        # With voice cloning
        tts = XTTS(reference_audio="my_voice.wav")
        tts.speak("Bu benim sesimle konuşuyor")
        
        # Without cloning
        tts = XTTS()
        tts.speak("Varsayılan ses")
    """
    
    MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
    
    def __init__(
        self,
        reference_audio: Optional[str] = None,
        use_cuda: bool = True,
    ):
        """Initialize XTTS.
        
        Args:
            reference_audio: Path to reference audio for voice cloning
            use_cuda: Use GPU acceleration (recommended for XTTS)
        """
        super().__init__()
        self._reference = reference_audio
        self._use_cuda = use_cuda
        self._tts = None
        self._sample_rate = 24000  # XTTS uses 24kHz
        self._speakers: List[str] = []
    
    def _ensure_loaded(self) -> None:
        """Lazy load XTTS model."""
        if self._tts is not None:
            return
        
        try:
            from TTS.api import TTS
            
            self._tts = TTS(self.MODEL, gpu=self._use_cuda)
            
            # Get available speakers
            if hasattr(self._tts, "speakers") and self._tts.speakers:
                self._speakers = list(self._tts.speakers)
            
        except ImportError:
            raise ImportError(
                "Coqui TTS not installed. "
                "Install with: pip install TTS"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load XTTS model: {e}")
    
    def synthesize(self, text: str, config: Optional[TTSConfig] = None) -> TTSResult:
        """Synthesize text with optional voice cloning.
        
        Args:
            text: Text to synthesize
            config: TTS configuration
            
        Returns:
            TTSResult with audio data
        """
        self._ensure_loaded()
        config = config or TTSConfig()
        
        import numpy as np
        
        # Generate audio
        if self._reference:
            # Voice cloning mode
            wav = self._tts.tts_with_vc(
                text=text,
                speaker_wav=self._reference,
                language=config.language,
            )
        else:
            # Default mode
            wav = self._tts.tts(
                text=text,
                language=config.language,
            )
        
        wav_array = np.array(wav, dtype=np.float32)
        
        # Apply adjustments
        if config.speed != 1.0:
            wav_bytes = wav_array.tobytes()
            wav_bytes = self.adjust_speed(wav_bytes, config.speed, self._sample_rate)
            wav_array = np.frombuffer(wav_bytes, dtype=np.float32)
        
        if config.volume != 1.0:
            wav_array = wav_array * config.volume
            wav_array = np.clip(wav_array, -1.0, 1.0)
        
        # Convert to WAV
        wav_bytes = self._to_wav(wav_array)
        duration_ms = int(len(wav_array) / self._sample_rate * 1000)
        
        return TTSResult(
            audio_data=wav_bytes,
            sample_rate=self._sample_rate,
            duration_ms=duration_ms,
            format="wav",
        )
    
    def synthesize_stream(
        self,
        text: str,
        config: Optional[TTSConfig] = None,
    ) -> Iterator[TTSChunk]:
        """Synthesize to streaming chunks.
        
        XTTS supports native streaming, but we use chunked approach here.
        
        Args:
            text: Text to synthesize
            config: TTS configuration
            
        Yields:
            TTSChunk objects
        """
        result = self.synthesize(text, config)
        
        chunk_size = 4096
        header_size = 44
        audio_data = result.audio_data[header_size:]
        
        total_chunks = (len(audio_data) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(audio_data), chunk_size):
            chunk_data = audio_data[i:i + chunk_size]
            chunk_index = i // chunk_size
            is_last = chunk_index == total_chunks - 1
            
            yield TTSChunk(
                data=chunk_data,
                index=chunk_index,
                is_last=is_last,
                text_offset=0,
            )
    
    def set_reference(self, audio_path: str) -> None:
        """Set reference audio for voice cloning.
        
        Args:
            audio_path: Path to reference WAV file
        """
        self._reference = audio_path
    
    def list_voices(self) -> list[str]:
        """List available voices/speakers."""
        self._ensure_loaded()
        return self._speakers or ["default"]
    
    def set_voice(self, voice_name: str) -> bool:
        """Set speaker voice (not applicable for XTTS with reference)."""
        # XTTS uses reference audio, not named voices
        return False
    
    @property
    def current_voice(self) -> str:
        """Get current voice description."""
        if self._reference:
            return f"cloned:{self._reference}"
        return "default"
    
    def _to_wav(self, audio_array) -> bytes:
        """Convert numpy array to WAV bytes."""
        import numpy as np
        
        audio_int16 = (audio_array * 32767).astype(np.int16)
        
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(audio_int16.tobytes())
        
        return buffer.getvalue()


# ─────────────────────────────────────────────────────────────────
# Factory Function
# ─────────────────────────────────────────────────────────────────

def create_coqui_tts(
    model: str = CoquiTTS.DEFAULT_MODEL,
    use_xtts: bool = False,
    reference_audio: Optional[str] = None,
    use_cuda: bool = False,
) -> AdvancedTTS:
    """Create a Coqui TTS instance.
    
    Args:
        model: Model name for CoquiTTS
        use_xtts: Use XTTS instead of standard Coqui
        reference_audio: Reference audio for XTTS voice cloning
        use_cuda: Use GPU acceleration
        
    Returns:
        AdvancedTTS instance
    """
    if use_xtts or reference_audio:
        return XTTS(reference_audio=reference_audio, use_cuda=use_cuda)
    return CoquiTTS(model=model, use_cuda=use_cuda)
