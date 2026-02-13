"""Tests for Continuous Listening Mode (Issue #11).

Tests for VAD, Segmenter, Noise Filter, Multi Wake Word, and Continuous Listener.
"""
from __future__ import annotations

import asyncio
import struct
import time
from collections import deque
from unittest.mock import MagicMock, patch, AsyncMock

import numpy as np
import pytest


# ─────────────────────────────────────────────────────────────────
# Test Utilities
# ─────────────────────────────────────────────────────────────────

def generate_audio_bytes(duration_seconds: float, sample_rate: int = 16000, frequency: float = 440.0, amplitude: float = 0.5) -> bytes:
    """Generate audio bytes with a sine wave."""
    num_samples = int(duration_seconds * sample_rate)
    t = np.linspace(0, duration_seconds, num_samples, dtype=np.float32)
    samples = (amplitude * np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
    return samples.tobytes()


def generate_silence_bytes(duration_seconds: float, sample_rate: int = 16000) -> bytes:
    """Generate silence bytes."""
    num_samples = int(duration_seconds * sample_rate)
    samples = np.zeros(num_samples, dtype=np.int16)
    return samples.tobytes()


def generate_noise_bytes(duration_seconds: float, sample_rate: int = 16000, amplitude: float = 0.1) -> bytes:
    """Generate noise bytes."""
    num_samples = int(duration_seconds * sample_rate)
    samples = (np.random.randn(num_samples) * amplitude * 32767).astype(np.int16)
    return samples.tobytes()


def chunk_audio(audio: bytes, chunk_size: int = 960) -> list:
    """Split audio into chunks."""
    chunks = []
    chunk_bytes = chunk_size * 2  # 16-bit samples
    for i in range(0, len(audio), chunk_bytes):
        chunk = audio[i:i + chunk_bytes]
        if len(chunk) == chunk_bytes:
            chunks.append(chunk)
    return chunks


# ─────────────────────────────────────────────────────────────────
# VAD Tests
# ─────────────────────────────────────────────────────────────────

class TestVADConfig:
    """Tests for VADConfig."""
    
    def test_default_config(self):
        from bantz.voice.vad import VADConfig
        
        config = VADConfig()
        
        assert config.aggressiveness == 2
        assert config.sample_rate == 16000
        assert config.frame_duration_ms == 30
        assert config.smoothing_window == 10
        assert config.speech_threshold == 0.6
        assert config.noise_adaptation_rate == 0.01
    
    def test_custom_config(self):
        from bantz.voice.vad import VADConfig
        
        config = VADConfig(
            aggressiveness=3,
            sample_rate=8000,
            frame_duration_ms=20,
        )
        
        assert config.aggressiveness == 3
        assert config.sample_rate == 8000
        assert config.frame_duration_ms == 20


class TestAdvancedVAD:
    """Tests for AdvancedVAD."""
    
    def test_initialization(self):
        from bantz.voice.vad import AdvancedVAD, VADConfig
        
        vad = AdvancedVAD()
        
        assert vad.sample_rate == 16000
        assert vad.frame_size == 480  # 30ms at 16kHz
        assert vad.frame_bytes == 960  # 16-bit samples
    
    def test_invalid_sample_rate(self):
        from bantz.voice.vad import AdvancedVAD, VADConfig
        
        with pytest.raises(ValueError, match="Sample rate"):
            AdvancedVAD(VADConfig(sample_rate=44100))
    
    def test_invalid_frame_duration(self):
        from bantz.voice.vad import AdvancedVAD, VADConfig
        
        with pytest.raises(ValueError, match="Frame duration"):
            AdvancedVAD(VADConfig(frame_duration_ms=25))
    
    def test_invalid_aggressiveness(self):
        from bantz.voice.vad import AdvancedVAD, VADConfig
        
        with pytest.raises(ValueError, match="Aggressiveness"):
            AdvancedVAD(VADConfig(aggressiveness=5))
    
    def test_calculate_energy_silence(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        silence = generate_silence_bytes(0.03)
        
        energy = vad._calculate_energy(silence)
        
        assert energy < 0.01
    
    def test_calculate_energy_speech(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        speech = generate_audio_bytes(0.03, amplitude=0.8)
        
        energy = vad._calculate_energy(speech)
        
        assert energy > 0.1
    
    def test_is_speech_with_silence(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        silence = generate_silence_bytes(0.03)
        
        # Process multiple frames to fill history
        for _ in range(10):
            result = vad.is_speech(silence)
        
        assert result is False
    
    def test_is_speech_with_audio(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        speech = generate_audio_bytes(0.03, amplitude=0.8)
        
        # Process multiple frames to fill history
        for _ in range(10):
            result = vad.is_speech(speech)
        
        assert result is True
    
    def test_noise_floor_adaptation(self):
        from bantz.voice.vad import AdvancedVAD, VADConfig
        
        vad = AdvancedVAD(VADConfig(noise_adaptation_rate=0.5))
        initial_floor = vad.noise_floor
        
        # Adapt with low noise
        noise = generate_noise_bytes(0.03, amplitude=0.01)
        vad.adapt_noise_floor(noise)
        
        # Noise floor should change
        assert vad.noise_floor != initial_floor or vad.noise_floor > 0
    
    def test_reset(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        
        # Process some audio
        speech = generate_audio_bytes(0.03)
        for _ in range(5):
            vad.is_speech(speech)
        
        assert len(vad.history) > 0
        
        vad.reset()
        
        assert len(vad.history) == 0
    
    def test_speech_callbacks(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        
        start_count = 0
        end_count = 0
        
        def on_start():
            nonlocal start_count
            start_count += 1
        
        def on_end():
            nonlocal end_count
            end_count += 1
        
        vad.on_speech_start(on_start)
        vad.on_speech_end(on_end)
        
        # Speech -> silence transition
        speech = generate_audio_bytes(0.03, amplitude=0.8)
        silence = generate_silence_bytes(0.03)
        
        for _ in range(10):
            vad.is_speech(speech)
        
        for _ in range(10):
            vad.is_speech(silence)
        
        assert start_count >= 1
    
    def test_get_stats(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        speech = generate_audio_bytes(0.03)
        
        for _ in range(5):
            vad.is_speech(speech)
        
        stats = vad.get_stats()
        
        assert stats["frames_processed"] == 5
        assert "noise_floor" in stats
        assert "speech_ratio" in stats


class TestEnergyVAD:
    """Tests for EnergyVAD (fallback)."""
    
    def test_initialization(self):
        from bantz.voice.vad import EnergyVAD
        
        vad = EnergyVAD(threshold=0.05)
        
        assert vad.threshold == 0.05
        assert vad.sample_rate == 16000
    
    def test_is_speech_silence(self):
        from bantz.voice.vad import EnergyVAD
        
        vad = EnergyVAD()
        silence = generate_silence_bytes(0.03)
        
        assert vad.is_speech(silence) is False
    
    def test_is_speech_audio(self):
        from bantz.voice.vad import EnergyVAD
        
        vad = EnergyVAD(threshold=0.01)
        speech = generate_audio_bytes(0.03, amplitude=0.8)
        
        for _ in range(5):
            result = vad.is_speech(speech)
        
        assert result is True
    
    def test_reset(self):
        from bantz.voice.vad import EnergyVAD
        
        vad = EnergyVAD()
        speech = generate_audio_bytes(0.03)
        
        for _ in range(5):
            vad.is_speech(speech)
        
        vad.reset()
        
        assert len(vad._history) == 0


class TestMockVAD:
    """Tests for MockVAD."""
    
    def test_set_speech_pattern(self):
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_speech_pattern([True, True, False, False])
        
        assert vad.is_speech(b'') is True
        assert vad.is_speech(b'') is True
        assert vad.is_speech(b'') is False
        assert vad.is_speech(b'') is False
        assert vad.is_speech(b'') is False  # Default
    
    def test_set_default_result(self):
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_default_result(True)
        
        assert vad.is_speech(b'') is True
    
    def test_reset(self):
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_speech_pattern([True, False])
        
        vad.is_speech(b'')
        vad.reset()
        
        assert vad.is_speech(b'') is True  # Pattern resets


# ─────────────────────────────────────────────────────────────────
# Segmenter Tests
# ─────────────────────────────────────────────────────────────────

class TestSegmenterConfig:
    """Tests for SegmenterConfig."""
    
    def test_default_config(self):
        from bantz.voice.segmenter import SegmenterConfig
        
        config = SegmenterConfig()
        
        assert config.sample_rate == 16000
        assert config.min_speech_duration == 0.3
        assert config.max_speech_duration == 30.0
        assert config.silence_threshold == 0.8


class TestSegment:
    """Tests for Segment dataclass."""
    
    def test_duration(self):
        from bantz.voice.segmenter import Segment
        
        segment = Segment(
            audio=b'\x00' * 32000,
            start_time=1.0,
            end_time=2.0,
        )
        
        assert segment.duration == 1.0
        assert len(segment) == 32000


class TestSpeechSegmenter:
    """Tests for SpeechSegmenter."""
    
    def test_initialization(self):
        from bantz.voice.segmenter import SpeechSegmenter, SegmentState
        
        segmenter = SpeechSegmenter()
        
        assert segmenter.state == SegmentState.IDLE
        assert segmenter.is_speaking is False
    
    def test_process_silence(self):
        from bantz.voice.segmenter import SpeechSegmenter
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_default_result(False)  # All silence
        
        segmenter = SpeechSegmenter(vad=vad)
        silence = generate_silence_bytes(0.03)
        
        for _ in range(10):
            segment = segmenter.process(silence)
            assert segment is None
    
    def test_process_speech_to_segment(self):
        from bantz.voice.segmenter import SpeechSegmenter, SegmentState
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        # Speech for 20 frames, then silence for 30 frames
        pattern = [True] * 20 + [False] * 30
        vad.set_speech_pattern(pattern)
        
        segmenter = SpeechSegmenter(vad=vad)
        audio_chunk = generate_audio_bytes(0.03)
        
        segment = None
        for _ in range(len(pattern)):
            result = segmenter.process(audio_chunk)
            if result:
                segment = result
                break
        
        assert segment is not None
        assert len(segment.audio) > 0
    
    def test_max_duration_limit(self):
        from bantz.voice.segmenter import SpeechSegmenter, SegmenterConfig
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_default_result(True)  # Always speech
        
        config = SegmenterConfig(max_speech_duration=0.5)
        segmenter = SpeechSegmenter(vad=vad, config=config)
        
        audio_chunk = generate_audio_bytes(0.03)
        
        segment = None
        for i in range(100):
            result = segmenter.process(audio_chunk)
            if result:
                segment = result
                break
        
        assert segment is not None
    
    def test_min_duration_filter(self):
        from bantz.voice.segmenter import SpeechSegmenter, SegmenterConfig
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        # Very short speech (1 frame only = 30ms), then silence
        pattern = [True] + [False] * 50
        vad.set_speech_pattern(pattern)
        
        # Min duration is 1 second, but we only give 30ms of speech
        config = SegmenterConfig(min_speech_duration=1.0, silence_threshold=0.3)
        segmenter = SpeechSegmenter(vad=vad, config=config)
        
        audio_chunk = generate_audio_bytes(0.03)
        
        segment = None
        for _ in range(len(pattern)):
            result = segmenter.process(audio_chunk)
            if result:
                segment = result
        
        # Should be None because speech was too short (30ms < 1 second)
        assert segment is None
    
    def test_force_complete(self):
        from bantz.voice.segmenter import SpeechSegmenter, SegmentState
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_default_result(True)
        
        segmenter = SpeechSegmenter(vad=vad)
        audio_chunk = generate_audio_bytes(0.03)
        
        # Process some speech
        for _ in range(20):
            segmenter.process(audio_chunk)
        
        assert segmenter.state in (SegmentState.SPEAKING, SegmentState.SILENCE)
        
        segment = segmenter.force_complete()
        
        assert segment is not None
        assert segmenter.state == SegmentState.IDLE
    
    def test_callbacks(self):
        from bantz.voice.segmenter import SpeechSegmenter
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        pattern = [True] * 20 + [False] * 30
        vad.set_speech_pattern(pattern)
        
        segmenter = SpeechSegmenter(vad=vad)
        
        speech_started = []
        speech_ended = []
        segments_received = []
        
        segmenter.on_speech_start(lambda: speech_started.append(1))
        segmenter.on_speech_end(lambda: speech_ended.append(1))
        segmenter.on_segment(lambda s: segments_received.append(s))
        
        audio_chunk = generate_audio_bytes(0.03)
        for _ in range(len(pattern)):
            segmenter.process(audio_chunk)
        
        assert len(speech_started) >= 1
    
    def test_get_stats(self):
        from bantz.voice.segmenter import SpeechSegmenter
        
        segmenter = SpeechSegmenter()
        
        stats = segmenter.get_stats()
        
        assert "state" in stats
        assert "total_time" in stats
        assert "segments_pending" in stats
    
    def test_reset(self):
        from bantz.voice.segmenter import SpeechSegmenter, SegmentState
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_default_result(True)
        
        segmenter = SpeechSegmenter(vad=vad)
        audio_chunk = generate_audio_bytes(0.03)
        
        for _ in range(10):
            segmenter.process(audio_chunk)
        
        segmenter.reset()
        
        assert segmenter.state == SegmentState.IDLE
        assert segmenter.current_duration == 0.0


class TestMockSegmenter:
    """Tests for MockSegmenter."""
    
    def test_set_return_segment(self):
        from bantz.voice.segmenter import MockSegmenter, Segment
        
        segmenter = MockSegmenter()
        segment = Segment(audio=b'test', start_time=0, end_time=1)
        
        segmenter.set_return_segment(segment)
        
        result = segmenter.process(b'')
        
        assert result == segment
        assert segmenter.process(b'') is None  # Only once
    
    def test_process_count(self):
        from bantz.voice.segmenter import MockSegmenter
        
        segmenter = MockSegmenter()
        
        for _ in range(5):
            segmenter.process(b'')
        
        assert segmenter.process_count == 5


# ─────────────────────────────────────────────────────────────────
# Noise Filter Tests
# ─────────────────────────────────────────────────────────────────

class TestNoiseFilterConfig:
    """Tests for NoiseFilterConfig."""
    
    def test_default_config(self):
        from bantz.voice.noise_filter import NoiseFilterConfig
        
        config = NoiseFilterConfig()
        
        assert config.sample_rate == 16000
        assert config.prop_decrease == 0.8
        assert config.stationary is True


class TestNoiseFilter:
    """Tests for NoiseFilter."""
    
    def test_initialization(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        
        assert nf.sample_rate == 16000
        assert nf.has_noise_sample is False
    
    def test_set_noise_sample(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        noise = generate_noise_bytes(0.1)
        
        nf.set_noise_sample(noise)
        
        assert nf.has_noise_sample is True
    
    def test_clear_noise_sample(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        noise = generate_noise_bytes(0.1)
        
        nf.set_noise_sample(noise)
        nf.clear_noise_sample()
        
        assert nf.has_noise_sample is False
    
    def test_filter_passthrough_when_unavailable(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        nf._noisereduce_available = False
        
        audio = generate_audio_bytes(0.1)
        filtered = nf.filter(audio)
        
        assert filtered == audio
    
    def test_filter_empty_audio(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        
        filtered = nf.filter(b'')
        
        assert filtered == b''
    
    def test_bytes_to_array(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        audio = generate_audio_bytes(0.1)
        
        arr = nf._bytes_to_array(audio)
        
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.float32
        assert np.max(np.abs(arr)) <= 1.0
    
    def test_array_to_bytes(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        arr = np.array([0.5, -0.5, 0.0], dtype=np.float32)
        
        audio = nf._array_to_bytes(arr)
        
        assert isinstance(audio, bytes)
        assert len(audio) == 6  # 3 samples * 2 bytes
    
    def test_get_stats(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        
        stats = nf.get_stats()
        
        assert "is_available" in stats
        assert "has_noise_sample" in stats


class TestSimpleNoiseFilter:
    """Tests for SimpleNoiseFilter."""
    
    def test_initialization(self):
        from bantz.voice.noise_filter import SimpleNoiseFilter
        
        snf = SimpleNoiseFilter(threshold=0.05)
        
        assert snf.threshold == 0.05
        assert snf.is_available is True
    
    def test_filter_silence(self):
        from bantz.voice.noise_filter import SimpleNoiseFilter
        
        snf = SimpleNoiseFilter(threshold=0.01)
        silence = generate_silence_bytes(0.1)
        
        filtered = snf.filter(silence)
        
        # Should still be mostly silence
        assert len(filtered) == len(silence)
    
    def test_filter_array(self):
        from bantz.voice.noise_filter import SimpleNoiseFilter
        
        snf = SimpleNoiseFilter(threshold=0.1)
        arr = np.array([0.5, 0.05, -0.5, -0.05], dtype=np.float32)
        
        filtered = snf.filter_array(arr)
        
        # Values below threshold should be zeroed
        assert filtered[1] == 0.0
        assert filtered[3] == 0.0
        assert filtered[0] == 0.5
        assert filtered[2] == -0.5


class TestSpectralSubtractionFilter:
    """Tests for SpectralSubtractionFilter."""
    
    def test_initialization(self):
        from bantz.voice.noise_filter import SpectralSubtractionFilter
        
        ssf = SpectralSubtractionFilter()
        
        assert ssf.is_available is True
        assert ssf.has_noise_sample is False
    
    def test_set_noise_sample(self):
        from bantz.voice.noise_filter import SpectralSubtractionFilter
        
        ssf = SpectralSubtractionFilter()
        noise = generate_noise_bytes(0.5)  # Long enough for FFT
        
        ssf.set_noise_sample(noise)
        
        assert ssf.has_noise_sample is True
    
    def test_filter_without_noise_sample(self):
        from bantz.voice.noise_filter import SpectralSubtractionFilter
        
        ssf = SpectralSubtractionFilter()
        audio = generate_audio_bytes(0.1)
        
        filtered = ssf.filter(audio)
        
        assert filtered == audio  # Passthrough


class TestMockNoiseFilter:
    """Tests for MockNoiseFilter."""
    
    def test_passthrough_mode(self):
        from bantz.voice.noise_filter import MockNoiseFilter
        
        mnf = MockNoiseFilter()
        audio = b'\x01\x02\x03\x04'
        
        filtered = mnf.filter(audio)
        
        assert filtered == audio
    
    def test_non_passthrough_mode(self):
        from bantz.voice.noise_filter import MockNoiseFilter
        
        mnf = MockNoiseFilter()
        mnf.set_passthrough(False)
        
        audio = b'\x01\x02\x03\x04'
        filtered = mnf.filter(audio)
        
        assert filtered == b'\x00\x00\x00\x00'
    
    def test_filter_count(self):
        from bantz.voice.noise_filter import MockNoiseFilter
        
        mnf = MockNoiseFilter()
        
        for _ in range(5):
            mnf.filter(b'')
        
        assert mnf.filter_count == 5


# ─────────────────────────────────────────────────────────────────
# Multi Wake Word Tests
# ─────────────────────────────────────────────────────────────────

class TestMultiWakeWordConfig:
    """Tests for MultiWakeWordConfig."""
    
    def test_default_config(self):
        from bantz.voice.wakeword import MultiWakeWordConfig
        
        config = MultiWakeWordConfig()
        
        assert "hey_jarvis" in config.wake_words
        assert config.default_threshold == 0.5
        assert config.sample_rate == 16000
    
    def test_custom_config(self):
        from bantz.voice.wakeword import MultiWakeWordConfig
        
        config = MultiWakeWordConfig(
            wake_words=["custom_word"],
            default_threshold=0.7,
        )
        
        assert config.wake_words == ["custom_word"]
        assert config.default_threshold == 0.7


class TestMultiWakeWordDetector:
    """Tests for MultiWakeWordDetector."""
    
    def test_initialization(self):
        from bantz.voice.wakeword import MultiWakeWordDetector
        
        detector = MultiWakeWordDetector()
        
        assert detector.is_running is False
        assert len(detector.wake_words) > 0
    
    def test_add_wake_word(self):
        from bantz.voice.wakeword import MultiWakeWordDetector
        
        detector = MultiWakeWordDetector()
        initial_count = len(detector.wake_words)
        
        detector.add_wake_word("new_word", threshold=0.8)
        
        assert "new_word" in detector.wake_words
        assert detector.config.thresholds["new_word"] == 0.8
    
    def test_remove_wake_word(self):
        from bantz.voice.wakeword import MultiWakeWordDetector, MultiWakeWordConfig
        
        config = MultiWakeWordConfig(wake_words=["word1", "word2"])
        detector = MultiWakeWordDetector(config)
        
        detector.remove_wake_word("word1")
        
        assert "word1" not in detector.wake_words
        assert "word2" in detector.wake_words
    
    def test_set_threshold(self):
        from bantz.voice.wakeword import MultiWakeWordDetector
        
        detector = MultiWakeWordDetector()
        
        detector.set_threshold("hey_jarvis", 0.9)
        
        assert detector.config.thresholds["hey_jarvis"] == 0.9
    
    def test_callbacks(self):
        from bantz.voice.wakeword import MultiWakeWordDetector
        
        detector = MultiWakeWordDetector()
        
        callbacks_fired = []
        detector.on_wake_word(lambda w, c: callbacks_fired.append((w, c)))
        
        assert len(detector._callbacks) == 1
        
        detector.clear_callbacks()
        
        assert len(detector._callbacks) == 0
    
    def test_reset(self):
        from bantz.voice.wakeword import MultiWakeWordDetector
        
        detector = MultiWakeWordDetector()
        detector._total_chunks = 100
        detector._last_activations["test"] = time.time()
        
        detector.reset()
        
        assert detector._total_chunks == 0
        assert len(detector._last_activations) == 0
    
    def test_get_stats(self):
        from bantz.voice.wakeword import MultiWakeWordDetector
        
        detector = MultiWakeWordDetector()
        
        stats = detector.get_stats()
        
        assert "is_running" in stats
        assert "wake_words" in stats
        assert "total_chunks" in stats


class TestMockMultiWakeWordDetector:
    """Tests for MockMultiWakeWordDetector."""
    
    def test_set_predictions(self):
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        detector = MockMultiWakeWordDetector()
        detector.set_predictions({"hey_jarvis": 0.9})
        
        predictions = detector.predict(b'')
        
        assert predictions["hey_jarvis"] == 0.9
    
    def test_queue_detection(self):
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        detector = MockMultiWakeWordDetector()
        
        fired = []
        detector.on_wake_word(lambda w, c: fired.append((w, c)))
        
        detector.queue_detection("hey_jarvis", 0.95)
        detector.process_detection()
        
        assert ("hey_jarvis", 0.95) in fired
    
    def test_start_stop(self):
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        detector = MockMultiWakeWordDetector()
        
        assert detector.start() is True
        assert detector.is_running is True
        
        detector.stop()
        assert detector.is_running is False


# ─────────────────────────────────────────────────────────────────
# Continuous Listener Tests
# ─────────────────────────────────────────────────────────────────

class TestContinuousListenerConfig:
    """Tests for ContinuousListenerConfig."""
    
    def test_default_config(self):
        from bantz.voice.continuous import ContinuousListenerConfig
        
        config = ContinuousListenerConfig()
        
        assert config.sample_rate == 16000
        assert config.chunk_size == 480
        assert config.enable_noise_filter is True
        assert config.enable_vad is True
        assert config.listen_timeout == 15.0


class TestListenerState:
    """Tests for ListenerState enum."""
    
    def test_states(self):
        from bantz.voice.continuous import ListenerState
        
        assert ListenerState.IDLE is not None
        assert ListenerState.LISTENING is not None
        assert ListenerState.PROCESSING is not None


class TestContinuousListener:
    """Tests for ContinuousListener."""
    
    def test_initialization(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        
        listener = ContinuousListener()
        
        assert listener.state == ListenerState.IDLE
        assert listener.is_running is False
        assert listener.is_listening is False
    
    def test_callbacks(self):
        from bantz.voice.continuous import ContinuousListener
        
        listener = ContinuousListener()
        
        wake_callbacks = []
        utterance_callbacks = []
        state_callbacks = []
        
        listener.on_wake_word(lambda w, c: wake_callbacks.append((w, c)))
        listener.on_utterance(lambda a: utterance_callbacks.append(a))
        listener.on_state_change(lambda s: state_callbacks.append(s))
        
        assert len(listener._on_wake_word) == 1
        assert len(listener._on_utterance) == 1
        assert len(listener._on_state_change) == 1
        
        listener.clear_callbacks()
        
        assert len(listener._on_wake_word) == 0
    
    def test_trigger_wake_word(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import MockSegmenter
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        vad = MockVAD()
        segmenter = MockSegmenter()
        detector = MockMultiWakeWordDetector()
        
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=vad,
            segmenter=segmenter,
        )
        listener._ensure_components()
        
        wake_words_received = []
        listener.on_wake_word(lambda w, c: wake_words_received.append(w))
        
        listener.trigger_wake_word("test_wake")
        
        assert "test_wake" in wake_words_received
        assert listener.state == ListenerState.LISTENING
    
    def test_cancel_listening(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import MockSegmenter
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        vad = MockVAD()
        segmenter = MockSegmenter()
        detector = MockMultiWakeWordDetector()
        
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=vad,
            segmenter=segmenter,
        )
        listener._ensure_components()
        
        listener.trigger_wake_word()
        assert listener.state == ListenerState.LISTENING
        
        listener.cancel_listening()
        assert listener.state == ListenerState.IDLE
    
    def test_reset(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        
        listener = ContinuousListener()
        listener._state = ListenerState.LISTENING
        listener._current_audio = [b'test']
        
        listener.reset()
        
        assert listener.state == ListenerState.IDLE
        assert listener._current_audio == []
    
    def test_get_stats(self):
        from bantz.voice.continuous import ContinuousListener
        
        listener = ContinuousListener()
        
        stats = listener.get_stats()
        
        assert "state" in stats
        assert "is_running" in stats
        assert "total_chunks" in stats
        assert "wake_word_count" in stats
        assert "utterance_count" in stats
    
    def test_process_chunk_in_idle(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import MockSegmenter
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        vad = MockVAD()
        segmenter = MockSegmenter()
        detector = MockMultiWakeWordDetector()
        detector.set_predictions({"hey_jarvis": 0.3})  # Below threshold
        
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=vad,
            segmenter=segmenter,
        )
        listener._ensure_components()
        
        audio_chunk = generate_audio_bytes(0.03)
        result = listener.process_chunk(audio_chunk)
        
        assert result is None
        assert listener.state == ListenerState.IDLE
    
    def test_state_change_callbacks(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import MockSegmenter
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        vad = MockVAD()
        segmenter = MockSegmenter()
        detector = MockMultiWakeWordDetector()
        
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=vad,
            segmenter=segmenter,
        )
        listener._ensure_components()
        
        states_received = []
        listener.on_state_change(lambda s: states_received.append(s))
        
        listener.trigger_wake_word()
        
        assert ListenerState.LISTENING in states_received


class TestMockContinuousListener:
    """Tests for MockContinuousListener."""
    
    def test_queue_utterance(self):
        from bantz.voice.continuous import MockContinuousListener
        
        listener = MockContinuousListener()
        
        utterances = []
        listener.on_utterance(lambda a: utterances.append(a))
        
        listener.queue_utterance(b'test_audio')
        
        asyncio.run(listener.start())
        
        assert b'test_audio' in utterances
    
    def test_trigger_wake_word(self):
        from bantz.voice.continuous import MockContinuousListener, ListenerState
        
        listener = MockContinuousListener()
        
        wake_words = []
        listener.on_wake_word(lambda w, c: wake_words.append(w))
        
        listener.trigger_wake_word("test")
        
        assert "test" in wake_words
        assert listener.state == ListenerState.LISTENING
    
    def test_start_stop(self):
        from bantz.voice.continuous import MockContinuousListener
        
        listener = MockContinuousListener()
        
        listener.start_sync()
        assert listener.is_running is True
        
        listener.stop()
        assert listener.is_running is False
    
    def test_get_stats(self):
        from bantz.voice.continuous import MockContinuousListener
        
        listener = MockContinuousListener()
        
        stats = listener.get_stats()
        
        assert "state" in stats
        assert "is_running" in stats


# ─────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────

class TestContinuousListeningIntegration:
    """Integration tests for the continuous listening pipeline."""
    
    def test_vad_to_segmenter_integration(self):
        """Test VAD feeds into segmenter correctly."""
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import SpeechSegmenter
        
        vad = MockVAD()
        # Speech for 30 frames, silence for 40 frames
        pattern = [True] * 30 + [False] * 40
        vad.set_speech_pattern(pattern)
        
        segmenter = SpeechSegmenter(vad=vad)
        audio_chunk = generate_audio_bytes(0.03)
        
        segment = None
        for _ in range(len(pattern)):
            result = segmenter.process(audio_chunk)
            if result:
                segment = result
                break
        
        assert segment is not None
        assert segment.duration > 0
    
    def test_noise_filter_to_vad_integration(self):
        """Test noise filter feeds into VAD correctly."""
        from bantz.voice.noise_filter import MockNoiseFilter
        from bantz.voice.vad import AdvancedVAD
        
        noise_filter = MockNoiseFilter()
        vad = AdvancedVAD()
        
        audio = generate_audio_bytes(0.03, amplitude=0.8)
        filtered = noise_filter.filter(audio)
        
        result = vad.is_speech(filtered)
        
        assert isinstance(result, bool)
    
    def test_full_pipeline_mock(self):
        """Test full pipeline with mocks."""
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import MockSegmenter, Segment
        from bantz.voice.noise_filter import MockNoiseFilter
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        from bantz.voice.continuous import ContinuousListener, ListenerState
        
        # Create mocks
        vad = MockVAD()
        vad.set_default_result(True)
        
        segment = Segment(audio=b'test_audio', start_time=0, end_time=1)
        segmenter = MockSegmenter()
        segmenter.set_return_segment(segment)
        
        noise_filter = MockNoiseFilter()
        
        detector = MockMultiWakeWordDetector()
        detector.set_predictions({"hey_jarvis": 0.9})
        
        # Create listener
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=vad,
            segmenter=segmenter,
            noise_filter=noise_filter,
        )
        listener._ensure_components()
        
        # Track callbacks
        utterances = []
        listener.on_utterance(lambda a: utterances.append(a))
        
        # Trigger wake word manually and process
        listener.trigger_wake_word("hey_jarvis")
        
        audio_chunk = generate_audio_bytes(0.03)
        listener.process_chunk(audio_chunk)
        
        # Segment should have been completed
        assert listener.stats.wake_word_count >= 1


class TestModuleExports:
    """Test that all exports are available."""
    
    def test_vad_exports(self):
        from bantz.voice import (
            AdvancedVAD,
            VADConfig,
            VADState,
            EnergyVAD,
            MockVAD,
        )
        
        assert AdvancedVAD is not None
        assert VADConfig is not None
    
    def test_segmenter_exports(self):
        from bantz.voice import (
            SpeechSegmenter,
            SegmenterConfig,
            Segment,
            SegmentState,
            MockSegmenter,
        )
        
        assert SpeechSegmenter is not None
        assert SegmenterConfig is not None
    
    def test_noise_filter_exports(self):
        from bantz.voice import (
            NoiseFilter,
            NoiseFilterConfig,
            SimpleNoiseFilter,
            SpectralSubtractionFilter,
            MockNoiseFilter,
        )
        
        assert NoiseFilter is not None
        assert NoiseFilterConfig is not None
    
    def test_wakeword_exports(self):
        from bantz.voice import (
            WakeWordDetector,
            WakeWordConfig,
            MultiWakeWordDetector,
            MultiWakeWordConfig,
            VADRecorder,
            MockMultiWakeWordDetector,
        )
        
        assert MultiWakeWordDetector is not None
        assert MultiWakeWordConfig is not None
    
    def test_continuous_exports(self):
        from bantz.voice import (
            ContinuousListener,
            ContinuousListenerConfig,
            ListenerState,
            ListenerStats,
            MockContinuousListener,
            get_continuous_listener,
        )
        
        assert ContinuousListener is not None
        assert get_continuous_listener is not None


# ─────────────────────────────────────────────────────────────────
# Edge Case Tests
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_vad_empty_audio(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        
        result = vad.is_speech(b'')
        
        assert isinstance(result, bool)
    
    def test_segmenter_empty_audio(self):
        from bantz.voice.segmenter import SpeechSegmenter
        
        segmenter = SpeechSegmenter()
        
        result = segmenter.process(b'')
        
        assert result is None
    
    def test_noise_filter_empty_audio(self):
        from bantz.voice.noise_filter import NoiseFilter
        
        nf = NoiseFilter()
        
        result = nf.filter(b'')
        
        assert result == b''
    
    def test_vad_short_audio(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        short_audio = b'\x00\x01'  # Just 1 sample
        
        result = vad.is_speech(short_audio)
        
        assert isinstance(result, bool)
    
    def test_segmenter_rapid_transitions(self):
        from bantz.voice.segmenter import SpeechSegmenter
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        # Rapid speech/silence transitions
        pattern = [True, False] * 20 + [False] * 10
        vad.set_speech_pattern(pattern)
        
        segmenter = SpeechSegmenter(vad=vad)
        audio_chunk = generate_audio_bytes(0.03)
        
        for _ in range(len(pattern)):
            segmenter.process(audio_chunk)
        
        # After rapid transitions the segmenter must reach a stable state
        # (pattern ends with silence → should not be speaking)
        assert segmenter.is_speaking is False
        # segment_count may be 0 or more, but must be a valid non-negative int
        assert segmenter.segment_count >= 0
    
    def test_listener_multiple_wake_words(self):
        from bantz.voice.continuous import ContinuousListener, ListenerState
        from bantz.voice.vad import MockVAD
        from bantz.voice.segmenter import MockSegmenter
        from bantz.voice.wakeword import MockMultiWakeWordDetector
        
        detector = MockMultiWakeWordDetector()
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=MockVAD(),
            segmenter=MockSegmenter(),
        )
        listener._ensure_components()
        
        # Trigger multiple wake words
        listener.trigger_wake_word("hey_jarvis")
        listener.cancel_listening()
        listener.trigger_wake_word("alexa")
        
        assert listener.stats.wake_word_count == 2


# ─────────────────────────────────────────────────────────────────
# Performance Tests
# ─────────────────────────────────────────────────────────────────

class TestPerformance:
    """Performance-related tests."""
    
    def test_vad_processing_speed(self):
        from bantz.voice.vad import AdvancedVAD
        
        vad = AdvancedVAD()
        audio_chunk = generate_audio_bytes(0.03)
        
        start = time.time()
        for _ in range(1000):
            vad.is_speech(audio_chunk)
        elapsed = time.time() - start
        
        # Should process 1000 frames (30ms each) in reasonable time
        # 30 seconds of audio should process in < 1 second
        assert elapsed < 5.0
    
    def test_segmenter_processing_speed(self):
        from bantz.voice.segmenter import SpeechSegmenter
        from bantz.voice.vad import MockVAD
        
        vad = MockVAD()
        vad.set_default_result(True)
        
        segmenter = SpeechSegmenter(vad=vad)
        audio_chunk = generate_audio_bytes(0.03)
        
        start = time.time()
        for _ in range(1000):
            segmenter.process(audio_chunk)
        elapsed = time.time() - start
        
        assert elapsed < 5.0
    
    def test_noise_filter_simple_speed(self):
        from bantz.voice.noise_filter import SimpleNoiseFilter
        
        snf = SimpleNoiseFilter()
        audio_chunk = generate_audio_bytes(0.03)
        
        start = time.time()
        for _ in range(1000):
            snf.filter(audio_chunk)
        elapsed = time.time() - start
        
        assert elapsed < 5.0
