"""Tests for Advanced TTS System (Issue #10)."""
from __future__ import annotations

import pytest

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
    EMOTION_PATTERNS,
)


# ─────────────────────────────────────────────────────────────────
# TTSConfig Tests
# ─────────────────────────────────────────────────────────────────

class TestTTSConfig:
    """Tests for TTSConfig dataclass."""
    
    def test_default_values(self):
        """Test default config values."""
        config = TTSConfig()
        assert config.speed == 1.0
        assert config.pitch == 1.0
        assert config.volume == 1.0
        assert config.emotion == Emotion.NEUTRAL
        assert config.language == "tr"
    
    def test_speed_clamping(self):
        """Test speed is clamped to valid range."""
        config = TTSConfig(speed=3.0)
        assert config.speed == 2.0
        
        config = TTSConfig(speed=0.1)
        assert config.speed == 0.5
    
    def test_pitch_clamping(self):
        """Test pitch is clamped to valid range."""
        config = TTSConfig(pitch=5.0)
        assert config.pitch == 2.0
        
        config = TTSConfig(pitch=0.1)
        assert config.pitch == 0.5
    
    def test_volume_clamping(self):
        """Test volume is clamped to valid range."""
        config = TTSConfig(volume=2.0)
        assert config.volume == 1.0
        
        config = TTSConfig(volume=-0.5)
        assert config.volume == 0.0
    
    def test_custom_emotion(self):
        """Test setting custom emotion."""
        config = TTSConfig(emotion=Emotion.HAPPY)
        assert config.emotion == Emotion.HAPPY


# ─────────────────────────────────────────────────────────────────
# TTSResult Tests
# ─────────────────────────────────────────────────────────────────

class TestTTSResult:
    """Tests for TTSResult dataclass."""
    
    def test_default_values(self):
        """Test default result values."""
        result = TTSResult(audio_data=b"test")
        assert result.audio_data == b"test"
        assert result.sample_rate == 22050
        assert result.duration_ms == 0
        assert result.format == "wav"
    
    def test_custom_values(self):
        """Test custom result values."""
        result = TTSResult(
            audio_data=b"audio",
            sample_rate=44100,
            duration_ms=1000,
            format="mp3",
        )
        assert result.sample_rate == 44100
        assert result.duration_ms == 1000
        assert result.format == "mp3"


# ─────────────────────────────────────────────────────────────────
# MockTTS Tests
# ─────────────────────────────────────────────────────────────────

class TestMockTTS:
    """Tests for MockTTS."""
    
    def test_init(self):
        """Test MockTTS initialization."""
        tts = MockTTS()
        assert tts.current_voice == "mock_voice"
        assert not tts.is_speaking
    
    def test_speak_records_calls(self):
        """Test speak records calls."""
        tts = MockTTS()
        tts.speak("Hello")
        tts.speak("World", TTSConfig(speed=1.5))
        
        assert len(tts.speak_calls) == 2
        assert tts.speak_calls[0][0] == "Hello"
        assert tts.speak_calls[1][0] == "World"
        assert tts.speak_calls[1][1].speed == 1.5
    
    def test_synthesize(self):
        """Test synthesize returns TTSResult."""
        tts = MockTTS()
        result = tts.synthesize("Test")
        
        assert isinstance(result, TTSResult)
        assert result.audio_data.startswith(b"RIFF")
    
    def test_synthesize_stream(self):
        """Test synthesize_stream yields chunks."""
        tts = MockTTS()
        chunks = list(tts.synthesize_stream("Hello World Test"))
        
        assert len(chunks) > 0
        assert all(isinstance(c, TTSChunk) for c in chunks)
        assert chunks[-1].is_last
    
    def test_list_voices(self):
        """Test list_voices returns available voices."""
        tts = MockTTS()
        voices = tts.list_voices()
        
        assert "mock_voice" in voices
        assert "mock_voice_2" in voices
    
    def test_set_voice(self):
        """Test set_voice changes voice."""
        tts = MockTTS()
        
        assert tts.set_voice("mock_voice_2")
        assert tts.current_voice == "mock_voice_2"
        
        assert not tts.set_voice("nonexistent")
    
    def test_callbacks(self):
        """Test on_start and on_stop callbacks."""
        tts = MockTTS()
        
        started = []
        stopped = []
        
        tts.on_start(lambda: started.append(1))
        tts.on_stop(lambda: stopped.append(1))
        
        tts.speak("Test")
        
        assert len(started) == 1
        assert len(stopped) == 1
    
    def test_stop(self):
        """Test stop sets is_speaking to False."""
        tts = MockTTS()
        tts._is_speaking = True
        
        tts.stop()
        
        assert not tts.is_speaking


# ─────────────────────────────────────────────────────────────────
# Streaming Player Tests
# ─────────────────────────────────────────────────────────────────

class TestMockStreamingPlayer:
    """Tests for MockStreamingPlayer."""
    
    def test_init(self):
        """Test initialization."""
        player = MockStreamingPlayer()
        assert player.sample_rate == 22050
        assert not player.is_playing
    
    def test_start_stop(self):
        """Test start and stop."""
        player = MockStreamingPlayer()
        
        player.start()
        assert player.is_playing
        
        player.stop()
        assert not player.is_playing
    
    def test_add_chunk(self):
        """Test adding chunks."""
        player = MockStreamingPlayer()
        player.start()
        
        player.add_chunk(b"chunk1")
        player.add_chunk(b"chunk2")
        
        assert len(player.chunks_received) == 2
        assert player.total_bytes == 12
    
    def test_clear(self):
        """Test clearing chunks."""
        player = MockStreamingPlayer()
        player.add_chunk(b"chunk1")
        
        player.clear()
        
        assert len(player.chunks_received) == 0


class TestAudioBuffer:
    """Tests for AudioBuffer."""
    
    def test_init(self):
        """Test initialization."""
        buffer = AudioBuffer()
        assert buffer.sample_rate == 22050
        assert buffer.size == 0
    
    def test_add(self):
        """Test adding data."""
        buffer = AudioBuffer()
        buffer.add(b"hello")
        buffer.add(b"world")
        
        assert buffer.size == 10
    
    def test_get_bytes(self):
        """Test getting bytes."""
        buffer = AudioBuffer()
        buffer.add(b"hello")
        buffer.add(b"world")
        
        assert buffer.get_bytes() == b"helloworld"
    
    def test_clear(self):
        """Test clearing buffer."""
        buffer = AudioBuffer()
        buffer.add(b"data")
        
        buffer.clear()
        
        assert buffer.size == 0
        assert buffer.get_bytes() == b""
    
    def test_duration_ms(self):
        """Test duration calculation."""
        buffer = AudioBuffer(sample_rate=22050)
        # Add 22050 samples (1 second at 16-bit = 44100 bytes)
        buffer.add(b"\x00" * 44100)
        
        assert buffer.duration_ms == 1000


# ─────────────────────────────────────────────────────────────────
# Emotion Selector Tests
# ─────────────────────────────────────────────────────────────────

class TestEmotionSelector:
    """Tests for EmotionSelector."""
    
    def test_init(self):
        """Test initialization."""
        selector = EmotionSelector()
        assert selector is not None
    
    def test_select_happy_from_text(self):
        """Test happy emotion detection."""
        selector = EmotionSelector()
        
        result = selector.select_from_text("Harika! Başardım!")
        assert result.emotion == Emotion.HAPPY
        assert result.confidence > 0.5
    
    def test_select_concerned_from_failure(self):
        """Test concerned emotion on failure."""
        selector = EmotionSelector()
        
        context = EmotionContext(
            text="İşlem tamamlandı",
            success=False,
        )
        result = selector.select(context)
        
        assert result.emotion == Emotion.CONCERNED
    
    def test_select_serious_from_warning(self):
        """Test serious emotion from warning words."""
        selector = EmotionSelector()
        
        result = selector.select_from_text("Dikkat! Önemli uyarı.")
        assert result.emotion == Emotion.SERIOUS
    
    def test_select_excited_from_urgency(self):
        """Test excited emotion from urgency words."""
        selector = EmotionSelector()
        
        result = selector.select_from_text("Acil! Son dakika haberi!")
        assert result.emotion == Emotion.EXCITED
    
    def test_select_neutral_default(self):
        """Test neutral is default for unknown text."""
        selector = EmotionSelector()
        
        result = selector.select_from_text("Normal bir cümle.")
        assert result.emotion == Emotion.NEUTRAL
    
    def test_select_for_response(self):
        """Test simplified select_for_response."""
        selector = EmotionSelector()
        
        emotion = selector.select_for_response(
            text="Başarısız oldu",
            intent="unknown",
            success=False,
        )
        assert emotion == Emotion.CONCERNED
    
    def test_empty_text(self):
        """Test empty text returns neutral."""
        selector = EmotionSelector()
        
        result = selector.select_from_text("")
        assert result.emotion == Emotion.NEUTRAL
        assert result.confidence < 0.5


class TestEmotionContext:
    """Tests for EmotionContext dataclass."""
    
    def test_default_values(self):
        """Test default context values."""
        context = EmotionContext()
        assert context.text == ""
        assert context.intent == ""
        assert context.success is True
        assert context.urgency == 0.0
    
    def test_custom_values(self):
        """Test custom context values."""
        context = EmotionContext(
            text="Test",
            intent="browser_open",
            success=False,
            urgency=0.8,
        )
        assert context.text == "Test"
        assert context.intent == "browser_open"
        assert context.success is False
        assert context.urgency == 0.8


# ─────────────────────────────────────────────────────────────────
# Jarvis Response Formatter Tests
# ─────────────────────────────────────────────────────────────────

class TestJarvisResponseFormatter:
    """Tests for JarvisResponseFormatter."""
    
    def test_init(self):
        """Test initialization."""
        formatter = JarvisResponseFormatter()
        assert formatter.use_emoji
    
    def test_format_neutral(self):
        """Test neutral formatting adds 'efendim'."""
        formatter = JarvisResponseFormatter(use_emoji=False)
        
        result = formatter.format("İşlem tamamlandı")
        assert "efendim" in result.lower()
    
    def test_format_happy(self):
        """Test happy formatting."""
        formatter = JarvisResponseFormatter(use_emoji=True)
        
        result = formatter.format("Başardık", Emotion.HAPPY)
        assert "efendim" in result.lower()
        # May contain emoji
    
    def test_format_already_has_efendim(self):
        """Test doesn't duplicate 'efendim'."""
        formatter = JarvisResponseFormatter()
        
        result = formatter.format("Tamam efendim")
        assert result.count("efendim") == 1
    
    def test_format_no_emoji(self):
        """Test emoji disabled."""
        formatter = JarvisResponseFormatter(use_emoji=False)
        
        result = formatter.format("Test", Emotion.HAPPY)
        assert "😊" not in result


# ─────────────────────────────────────────────────────────────────
# Mock Emotion Selector Tests
# ─────────────────────────────────────────────────────────────────

class TestMockEmotionSelector:
    """Tests for MockEmotionSelector."""
    
    def test_default_emotion(self):
        """Test default emotion."""
        mock = MockEmotionSelector()
        
        result = mock.select(EmotionContext(text="anything"))
        assert result.emotion == Emotion.NEUTRAL
    
    def test_set_default(self):
        """Test setting default emotion."""
        mock = MockEmotionSelector()
        mock.set_default(Emotion.HAPPY)
        
        result = mock.select(EmotionContext(text="anything"))
        assert result.emotion == Emotion.HAPPY
    
    def test_set_emotion_for_text(self):
        """Test mapping text to emotion."""
        mock = MockEmotionSelector()
        mock.set_emotion_for_text("special", Emotion.EXCITED)
        
        result = mock.select(EmotionContext(text="special"))
        assert result.emotion == Emotion.EXCITED
    
    def test_select_for_response_failure(self):
        """Test select_for_response on failure."""
        mock = MockEmotionSelector()
        
        emotion = mock.select_for_response("test", "intent", success=False)
        assert emotion == Emotion.CONCERNED


# ─────────────────────────────────────────────────────────────────
# Emotion Enum Tests
# ─────────────────────────────────────────────────────────────────

class TestEmotionEnum:
    """Tests for Emotion enum."""
    
    def test_all_emotions_exist(self):
        """Test all expected emotions exist."""
        assert Emotion.NEUTRAL.value == "neutral"
        assert Emotion.HAPPY.value == "happy"
        assert Emotion.SERIOUS.value == "serious"
        assert Emotion.CONCERNED.value == "concerned"
        assert Emotion.EXCITED.value == "excited"
        assert Emotion.CALM.value == "calm"
        assert Emotion.ANGRY.value == "angry"
    
    def test_emotion_patterns_coverage(self):
        """Test emotion patterns cover main emotions."""
        assert Emotion.HAPPY in EMOTION_PATTERNS
        assert Emotion.SERIOUS in EMOTION_PATTERNS
        assert Emotion.CONCERNED in EMOTION_PATTERNS


# ─────────────────────────────────────────────────────────────────
# TTSBackend Enum Tests
# ─────────────────────────────────────────────────────────────────

class TestTTSBackendEnum:
    """Tests for TTSBackend enum."""
    
    def test_backends_exist(self):
        """Test all backends exist."""
        assert TTSBackend.PIPER.value == "piper"
        assert TTSBackend.COQUI.value == "coqui"
        assert TTSBackend.XTTS.value == "xtts"
        assert TTSBackend.EDGE.value == "edge"


# ─────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────

class TestTTSIntegration:
    """Integration tests for TTS system."""
    
    def test_full_flow_mock(self):
        """Test full TTS flow with mock."""
        tts = MockTTS()
        selector = EmotionSelector()
        formatter = JarvisResponseFormatter(use_emoji=False)
        
        # Select emotion
        text = "Harika! İşlem başarılı!"
        emotion_result = selector.select_from_text(text)
        
        # Format response
        formatted = formatter.format(text, emotion_result.emotion)
        
        # Synthesize
        config = TTSConfig(emotion=emotion_result.emotion)
        result = tts.synthesize(formatted, config)
        
        assert "efendim" in formatted.lower()
        assert emotion_result.emotion == Emotion.HAPPY
        assert result.audio_data is not None
    
    def test_streaming_flow_mock(self):
        """Test streaming TTS flow with mock."""
        tts = MockTTS()
        player = MockStreamingPlayer()
        
        player.start()
        
        for chunk in tts.stream("Bu uzun bir test cümlesi, streaming için"):
            player.add_chunk(chunk.data)
        
        player.finish()
        
        assert len(player.chunks_received) > 0
        assert player.total_bytes > 0
    
    def test_speed_config(self):
        """Test speed configuration."""
        tts = MockTTS()
        
        # Fast
        config_fast = TTSConfig(speed=1.5)
        result_fast = tts.synthesize("Test", config_fast)
        
        # Slow
        config_slow = TTSConfig(speed=0.5)
        result_slow = tts.synthesize("Test", config_slow)
        
        # Both should work
        assert result_fast.audio_data is not None
        assert result_slow.audio_data is not None
    
    def test_emotion_to_config_flow(self):
        """Test emotion detection to TTS config flow."""
        selector = EmotionSelector()
        
        # Error case
        error_result = selector.select(EmotionContext(
            text="Hata oluştu",
            success=False,
        ))
        
        config = TTSConfig(emotion=error_result.emotion)
        assert config.emotion == Emotion.CONCERNED
        
        # Success case  
        success_result = selector.select(EmotionContext(
            text="Başarıyla tamamlandı",
            success=True,
        ))
        
        config = TTSConfig(emotion=success_result.emotion)
        # Should be happy or neutral
        assert config.emotion in [Emotion.HAPPY, Emotion.NEUTRAL]
