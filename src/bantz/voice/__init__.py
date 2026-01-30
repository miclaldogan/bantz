"""Voice module for TTS, ASR, wakeword detection, continuous listening, and conversation flow.

Includes:
- Advanced TTS with emotion and speed control
- Streaming audio playback
- Emotion detection for expressive speech
- Voice Activity Detection (VAD)
- Speech segmentation
- Noise filtering
- Multi wake word detection
- Continuous listening mode
- Jarvis conversation flow management
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
from bantz.voice.vad import (
    AdvancedVAD,
    VADConfig,
    VADState,
    EnergyVAD,
    MockVAD,
)
from bantz.voice.segmenter import (
    SpeechSegmenter,
    SegmenterConfig,
    Segment,
    SegmentState,
    MockSegmenter,
)
from bantz.voice.noise_filter import (
    NoiseFilter,
    NoiseFilterConfig,
    SimpleNoiseFilter,
    SpectralSubtractionFilter,
    MockNoiseFilter,
)
from bantz.voice.wakeword import (
    WakeWordDetector,
    WakeWordConfig,
    MultiWakeWordDetector,
    MultiWakeWordConfig,
    VADRecorder,
    MockMultiWakeWordDetector,
)
from bantz.voice.continuous import (
    ContinuousListener,
    ContinuousListenerConfig,
    ListenerState,
    ListenerStats,
    MockContinuousListener,
    get_continuous_listener,
)
from bantz.voice.conversation import (
    ConversationManager,
    ConversationConfig,
    ConversationContext,
    ConversationState,
    MockConversationManager,
)

# Issue #35: Attention Gate (Voice-2)
from bantz.voice.attention_gate import (
    AttentionGate,
    AttentionGateConfig,
    ListeningMode,
    create_attention_gate,
)
from bantz.voice.engaged_window import (
    EngagedWindowManager,
    EngagedWindowConfig,
    create_engaged_window,
)
from bantz.voice.interrupt_handler import (
    InterruptHandler,
    InterruptAction,
    InterruptResult,
    create_interrupt_handler,
)
from bantz.voice.task_policy import (
    TaskListeningPolicy,
    INTENT_KEYWORDS,
    classify_task_command,
    create_task_policy,
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
    # VAD
    "AdvancedVAD",
    "VADConfig",
    "VADState",
    "EnergyVAD",
    "MockVAD",
    # Segmenter
    "SpeechSegmenter",
    "SegmenterConfig",
    "Segment",
    "SegmentState",
    "MockSegmenter",
    # Noise Filter
    "NoiseFilter",
    "NoiseFilterConfig",
    "SimpleNoiseFilter",
    "SpectralSubtractionFilter",
    "MockNoiseFilter",
    # Wake Word
    "WakeWordDetector",
    "WakeWordConfig",
    "MultiWakeWordDetector",
    "MultiWakeWordConfig",
    "VADRecorder",
    "MockMultiWakeWordDetector",
    # Continuous Listening
    "ContinuousListener",
    "ContinuousListenerConfig",
    "ListenerState",
    "ListenerStats",
    "MockContinuousListener",
    "get_continuous_listener",
    # Conversation Flow
    "ConversationManager",
    "ConversationConfig",
    "ConversationContext",
    "ConversationState",
    "MockConversationManager",
    # Attention Gate (Issue #35)
    "AttentionGate",
    "AttentionGateConfig",
    "ListeningMode",
    "create_attention_gate",
    # Engaged Window
    "EngagedWindowManager",
    "EngagedWindowConfig",
    "create_engaged_window",
    # Interrupt Handler
    "InterruptHandler",
    "InterruptAction",
    "InterruptResult",
    "create_interrupt_handler",
    # Task Policy
    "TaskListeningPolicy",
    "INTENT_KEYWORDS",
    "classify_task_command",
    "create_task_policy",
]
