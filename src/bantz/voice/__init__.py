"""Voice module for TTS, ASR, and wakeword detection.

Includes:
- Advanced TTS with emotion and speed control
- Streaming audio playback
- Emotion detection for expressive speech
"""
from bantz.voice.advanced_tts import (
    AdvancedTTS,
    TTSConfig,
    TTSResult,
    TTSChunk,
    Emotion,
    TTSBackend,
    MockTTS,
)
from bantz.voice.streaming import (
    StreamingPlayer,
    AudioBuffer,
    MockStreamingPlayer,
)
from bantz.voice.emotion import (
    EmotionSelector,
    EmotionContext,
    EmotionResult,
    JarvisResponseFormatter,
    MockEmotionSelector,
)

__all__ = [
    # Advanced TTS
    "AdvancedTTS",
    "TTSConfig",
    "TTSResult",
    "TTSChunk",
    "Emotion",
    "TTSBackend",
    "MockTTS",
    # Streaming
    "StreamingPlayer",
    "AudioBuffer",
    "MockStreamingPlayer",
    # Emotion
    "EmotionSelector",
    "EmotionContext",
    "EmotionResult",
    "JarvisResponseFormatter",
    "MockEmotionSelector",
]
