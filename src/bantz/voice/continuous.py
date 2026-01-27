"""Continuous Listening (Issue #11).

Main async loop for continuous "Hey Jarvis" listening mode.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import struct
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, List, Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .vad import AdvancedVAD
    from .segmenter import SpeechSegmenter, Segment
    from .noise_filter import NoiseFilter
    from .wakeword import MultiWakeWordDetector

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# State Machine
# ─────────────────────────────────────────────────────────────────

class ListenerState(Enum):
    """State of the continuous listener."""
    IDLE = auto()          # Waiting for wake word
    LISTENING = auto()     # Recording speech after wake word
    PROCESSING = auto()    # Processing utterance


@dataclass
class ContinuousListenerConfig:
    """Continuous listener configuration.
    
    Attributes:
        sample_rate: Audio sample rate
        chunk_size: Audio chunk size in samples
        chunk_duration_ms: Chunk duration in milliseconds
        enable_noise_filter: Enable background noise filtering
        enable_vad: Enable voice activity detection
        listen_timeout: Timeout for listening after wake word (seconds)
        beep_on_wake: Play beep on wake word detection
        confirmation_phrase: Phrase to speak on wake word
    """
    sample_rate: int = 16000
    chunk_size: int = 480  # 30ms at 16kHz
    chunk_duration_ms: int = 30
    enable_noise_filter: bool = True
    enable_vad: bool = True
    listen_timeout: float = 15.0
    beep_on_wake: bool = True
    confirmation_phrase: str = ""


@dataclass
class ListenerStats:
    """Continuous listener statistics.
    
    Attributes:
        total_chunks: Total audio chunks processed
        wake_word_count: Number of wake word detections
        utterance_count: Number of complete utterances
        total_speech_seconds: Total speech time in seconds
        start_time: Listener start timestamp
    """
    total_chunks: int = 0
    wake_word_count: int = 0
    utterance_count: int = 0
    total_speech_seconds: float = 0.0
    start_time: float = 0.0


# ─────────────────────────────────────────────────────────────────
# Continuous Listener
# ─────────────────────────────────────────────────────────────────

class ContinuousListener:
    """Continuous listening mode with wake word activation.
    
    Flow:
    1. Listen for wake word ("Hey Jarvis")
    2. On detection, start recording speech
    3. Use VAD to detect speech end
    4. Return complete utterance for processing
    5. Resume wake word listening
    
    Usage:
        async def handle_utterance(audio: bytes, text: str):
            # Process the utterance
            response = await process_command(text)
            await speak(response)
        
        listener = ContinuousListener(
            wake_word_detector=detector,
            vad=vad,
            segmenter=segmenter,
        )
        listener.on_utterance(handle_utterance)
        
        await listener.start()
    """
    
    def __init__(
        self,
        wake_word_detector: Optional[MultiWakeWordDetector] = None,
        vad: Optional[AdvancedVAD] = None,
        segmenter: Optional[SpeechSegmenter] = None,
        noise_filter: Optional[NoiseFilter] = None,
        config: Optional[ContinuousListenerConfig] = None,
    ):
        """Initialize continuous listener.
        
        Args:
            wake_word_detector: Multi wake word detector
            vad: Voice activity detector
            segmenter: Speech segmenter
            noise_filter: Noise filter
            config: Listener configuration
        """
        self.config = config or ContinuousListenerConfig()
        
        # Components (lazy initialized if not provided)
        self._wake_word_detector = wake_word_detector
        self._vad = vad
        self._segmenter = segmenter
        self._noise_filter = noise_filter
        
        # State
        self._state = ListenerState.IDLE
        self._running = False
        self._stream = None
        self._audio_queue: queue.Queue = queue.Queue()
        
        # Current recording
        self._current_audio: List[bytes] = []
        self._listen_start_time: float = 0.0
        
        # Callbacks
        self._on_wake_word: List[Callable[[str, float], Any]] = []
        self._on_utterance: List[Callable[[bytes], Any]] = []
        self._on_state_change: List[Callable[[ListenerState], Any]] = []
        
        # Statistics
        self._stats = ListenerStats()
        
        # Thread for audio capture
        self._capture_thread: Optional[threading.Thread] = None
    
    def _ensure_components(self) -> None:
        """Lazy initialize components if not provided."""
        if self._vad is None:
            from .vad import AdvancedVAD, VADConfig
            self._vad = AdvancedVAD(VADConfig(
                sample_rate=self.config.sample_rate,
                frame_duration_ms=self.config.chunk_duration_ms,
            ))
        
        if self._segmenter is None:
            from .segmenter import SpeechSegmenter, SegmenterConfig
            self._segmenter = SpeechSegmenter(
                vad=self._vad,
                config=SegmenterConfig(
                    sample_rate=self.config.sample_rate,
                    silence_threshold=0.8,
                    max_speech_duration=self.config.listen_timeout,
                ),
            )
        
        if self._noise_filter is None and self.config.enable_noise_filter:
            from .noise_filter import NoiseFilter, NoiseFilterConfig
            self._noise_filter = NoiseFilter(NoiseFilterConfig(
                sample_rate=self.config.sample_rate,
            ))
        
        if self._wake_word_detector is None:
            from .wakeword import MultiWakeWordDetector, MultiWakeWordConfig
            self._wake_word_detector = MultiWakeWordDetector(MultiWakeWordConfig(
                sample_rate=self.config.sample_rate,
                chunk_size=self.config.chunk_size,
            ))
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def state(self) -> ListenerState:
        """Get current state."""
        return self._state
    
    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running
    
    @property
    def is_listening(self) -> bool:
        """Check if currently recording speech."""
        return self._state == ListenerState.LISTENING
    
    @property
    def stats(self) -> ListenerStats:
        """Get listener statistics."""
        return self._stats
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_wake_word(self, callback: Callable[[str, float], Any]) -> None:
        """Add callback for wake word detection.
        
        Args:
            callback: Function called with (wake_word, confidence)
        """
        self._on_wake_word.append(callback)
    
    def on_utterance(self, callback: Callable[[bytes], Any]) -> None:
        """Add callback for complete utterance.
        
        Args:
            callback: Function called with audio bytes
        """
        self._on_utterance.append(callback)
    
    def on_state_change(self, callback: Callable[[ListenerState], Any]) -> None:
        """Add callback for state changes.
        
        Args:
            callback: Function called with new state
        """
        self._on_state_change.append(callback)
    
    def clear_callbacks(self) -> None:
        """Clear all callbacks."""
        self._on_wake_word.clear()
        self._on_utterance.clear()
        self._on_state_change.clear()
    
    # ─────────────────────────────────────────────────────────────
    # State Machine
    # ─────────────────────────────────────────────────────────────
    
    def _set_state(self, state: ListenerState) -> None:
        """Set state and fire callbacks."""
        if state != self._state:
            old_state = self._state
            self._state = state
            
            logger.debug(f"[ContinuousListener] State: {old_state.name} -> {state.name}")
            
            for callback in self._on_state_change:
                try:
                    callback(state)
                except Exception as e:
                    logger.error(f"[ContinuousListener] State callback error: {e}")
    
    def _handle_wake_word(self, wake_word: str, confidence: float) -> None:
        """Handle wake word detection."""
        if self._state != ListenerState.IDLE:
            return
        
        logger.info(f"[ContinuousListener] Wake word: {wake_word} ({confidence:.2f})")
        
        self._stats.wake_word_count += 1
        
        # Fire callbacks
        for callback in self._on_wake_word:
            try:
                callback(wake_word, confidence)
            except Exception as e:
                logger.error(f"[ContinuousListener] Wake word callback error: {e}")
        
        # Start listening
        self._start_listening()
    
    def _start_listening(self) -> None:
        """Start recording speech."""
        self._current_audio = []
        self._listen_start_time = time.time()
        self._set_state(ListenerState.LISTENING)
        
        # Reset segmenter
        if self._segmenter:
            self._segmenter.reset()
    
    def _complete_utterance(self, audio: bytes) -> None:
        """Complete utterance and fire callbacks."""
        self._set_state(ListenerState.PROCESSING)
        
        self._stats.utterance_count += 1
        self._stats.total_speech_seconds += len(audio) / 2 / self.config.sample_rate
        
        logger.info(
            f"[ContinuousListener] Utterance complete: "
            f"{len(audio)} bytes, "
            f"{len(audio) / 2 / self.config.sample_rate:.1f}s"
        )
        
        # Fire callbacks
        for callback in self._on_utterance:
            try:
                callback(audio)
            except Exception as e:
                logger.error(f"[ContinuousListener] Utterance callback error: {e}")
        
        # Return to idle
        self._set_state(ListenerState.IDLE)
    
    # ─────────────────────────────────────────────────────────────
    # Audio Processing
    # ─────────────────────────────────────────────────────────────
    
    def _process_audio_chunk(self, audio_chunk: bytes) -> None:
        """Process a single audio chunk.
        
        Args:
            audio_chunk: Raw audio bytes
        """
        self._stats.total_chunks += 1
        
        # Apply noise filter if enabled
        if self._noise_filter and self.config.enable_noise_filter:
            audio_chunk = self._noise_filter.filter(audio_chunk)
        
        if self._state == ListenerState.IDLE:
            # Check wake word
            if self._wake_word_detector:
                predictions = self._wake_word_detector.predict(audio_chunk)
                
                for model, score in predictions.items():
                    threshold = self._wake_word_detector.config.thresholds.get(
                        model, self._wake_word_detector.config.default_threshold
                    )
                    if score >= threshold:
                        self._handle_wake_word(model, score)
                        return
        
        elif self._state == ListenerState.LISTENING:
            # Record audio
            self._current_audio.append(audio_chunk)
            
            # Check timeout
            elapsed = time.time() - self._listen_start_time
            if elapsed >= self.config.listen_timeout:
                logger.warning("[ContinuousListener] Listen timeout")
                self._finalize_recording()
                return
            
            # Check segmenter
            if self._segmenter:
                segment = self._segmenter.process(audio_chunk)
                if segment:
                    # Use segmented audio
                    self._complete_utterance(segment.audio)
                    return
            
            # Fallback: use VAD
            elif self._vad and self.config.enable_vad:
                if not self._vad.is_speech(audio_chunk):
                    # Track silence
                    if len(self._current_audio) > 20:  # At least 20 chunks
                        # Check if we've had enough silence
                        recent = self._vad.history[-5:] if len(self._vad.history) >= 5 else []
                        if recent and not any(recent):
                            self._finalize_recording()
    
    def _finalize_recording(self) -> None:
        """Finalize current recording."""
        if not self._current_audio:
            self._set_state(ListenerState.IDLE)
            return
        
        # Concatenate audio
        audio = b''.join(self._current_audio)
        self._current_audio = []
        
        if len(audio) > 0:
            self._complete_utterance(audio)
        else:
            self._set_state(ListenerState.IDLE)
    
    # ─────────────────────────────────────────────────────────────
    # Main Loop
    # ─────────────────────────────────────────────────────────────
    
    async def start(self) -> None:
        """Start continuous listening (async).
        
        Runs until stop() is called.
        """
        if self._running:
            return
        
        self._ensure_components()
        
        self._running = True
        self._stats.start_time = time.time()
        self._set_state(ListenerState.IDLE)
        
        logger.info("[ContinuousListener] Started")
        
        try:
            # Start audio capture in background thread
            self._capture_thread = threading.Thread(
                target=self._audio_capture_loop,
                daemon=True,
            )
            self._capture_thread.start()
            
            # Main processing loop (async)
            while self._running:
                try:
                    # Get audio chunk (non-blocking)
                    audio_chunk = self._audio_queue.get(timeout=0.1)
                    self._process_audio_chunk(audio_chunk)
                    
                except queue.Empty:
                    await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"[ContinuousListener] Process error: {e}")
        
        finally:
            self._cleanup()
    
    def start_sync(self) -> None:
        """Start continuous listening (synchronous).
        
        Blocks until stop() is called.
        """
        if self._running:
            return
        
        self._ensure_components()
        
        self._running = True
        self._stats.start_time = time.time()
        self._set_state(ListenerState.IDLE)
        
        logger.info("[ContinuousListener] Started (sync)")
        
        try:
            # Start audio capture in background thread
            self._capture_thread = threading.Thread(
                target=self._audio_capture_loop,
                daemon=True,
            )
            self._capture_thread.start()
            
            # Main processing loop
            while self._running:
                try:
                    audio_chunk = self._audio_queue.get(timeout=0.1)
                    self._process_audio_chunk(audio_chunk)
                except queue.Empty:
                    time.sleep(0.01)
                except Exception as e:
                    logger.error(f"[ContinuousListener] Process error: {e}")
        
        finally:
            self._cleanup()
    
    def _audio_capture_loop(self) -> None:
        """Audio capture loop running in background thread."""
        try:
            import sounddevice as sd
            
            def audio_callback(indata, frames, time_info, status):
                if status:
                    return
                
                # Convert to bytes
                audio_float = indata.copy().flatten()
                audio_int16 = (audio_float * 32767).astype(np.int16)
                audio_bytes = audio_int16.tobytes()
                
                self._audio_queue.put(audio_bytes)
            
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.config.chunk_size,
                callback=audio_callback,
            )
            self._stream.start()
            
            # Keep thread alive
            while self._running:
                time.sleep(0.1)
            
        except Exception as e:
            logger.error(f"[ContinuousListener] Capture error: {e}")
        finally:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
    
    def stop(self) -> None:
        """Stop continuous listening."""
        self._running = False
        
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        
        self._cleanup()
        
        logger.info("[ContinuousListener] Stopped")
    
    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        
        self._current_audio = []
        self._set_state(ListenerState.IDLE)
    
    # ─────────────────────────────────────────────────────────────
    # Manual Control
    # ─────────────────────────────────────────────────────────────
    
    def trigger_wake_word(self, wake_word: str = "manual") -> None:
        """Manually trigger wake word (for testing or hotkey).
        
        Args:
            wake_word: Wake word name
        """
        self._handle_wake_word(wake_word, 1.0)
    
    def cancel_listening(self) -> None:
        """Cancel current listening session."""
        if self._state == ListenerState.LISTENING:
            self._current_audio = []
            self._set_state(ListenerState.IDLE)
    
    def process_chunk(self, audio_chunk: bytes) -> Optional[bytes]:
        """Process a single audio chunk (for manual feeding).
        
        Args:
            audio_chunk: Raw audio bytes
            
        Returns:
            Complete utterance if ready, else None
        """
        old_utterance_count = self._stats.utterance_count
        
        self._process_audio_chunk(audio_chunk)
        
        # Check if utterance was completed
        if self._stats.utterance_count > old_utterance_count:
            # Return the last recorded audio (already sent via callback)
            return b''.join(self._current_audio) if self._current_audio else None
        
        return None
    
    # ─────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────
    
    def reset(self) -> None:
        """Reset listener state."""
        self._current_audio = []
        self._set_state(ListenerState.IDLE)
        
        if self._vad:
            self._vad.reset()
        
        if self._segmenter:
            self._segmenter.reset()
    
    def get_stats(self) -> dict:
        """Get listener statistics as dictionary."""
        return {
            "state": self._state.name,
            "is_running": self._running,
            "total_chunks": self._stats.total_chunks,
            "wake_word_count": self._stats.wake_word_count,
            "utterance_count": self._stats.utterance_count,
            "total_speech_seconds": self._stats.total_speech_seconds,
            "uptime_seconds": time.time() - self._stats.start_time if self._stats.start_time else 0,
        }


# ─────────────────────────────────────────────────────────────────
# Mock Continuous Listener
# ─────────────────────────────────────────────────────────────────

class MockContinuousListener:
    """Mock continuous listener for testing."""
    
    def __init__(self, config: Optional[ContinuousListenerConfig] = None):
        self.config = config or ContinuousListenerConfig()
        
        self._state = ListenerState.IDLE
        self._running = False
        
        self._on_wake_word: List[Callable[[str, float], Any]] = []
        self._on_utterance: List[Callable[[bytes], Any]] = []
        self._on_state_change: List[Callable[[ListenerState], Any]] = []
        
        self._stats = ListenerStats()
        self._queued_utterances: List[bytes] = []
    
    @property
    def state(self) -> ListenerState:
        return self._state
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_listening(self) -> bool:
        return self._state == ListenerState.LISTENING
    
    @property
    def stats(self) -> ListenerStats:
        return self._stats
    
    def queue_utterance(self, audio: bytes) -> None:
        """Queue an utterance to return on next process."""
        self._queued_utterances.append(audio)
    
    def on_wake_word(self, callback: Callable[[str, float], Any]) -> None:
        self._on_wake_word.append(callback)
    
    def on_utterance(self, callback: Callable[[bytes], Any]) -> None:
        self._on_utterance.append(callback)
    
    def on_state_change(self, callback: Callable[[ListenerState], Any]) -> None:
        self._on_state_change.append(callback)
    
    def clear_callbacks(self) -> None:
        self._on_wake_word.clear()
        self._on_utterance.clear()
        self._on_state_change.clear()
    
    async def start(self) -> None:
        self._running = True
        self._stats.start_time = time.time()
        
        # Process queued utterances
        while self._running and self._queued_utterances:
            audio = self._queued_utterances.pop(0)
            for callback in self._on_utterance:
                try:
                    callback(audio)
                except Exception:
                    pass
            self._stats.utterance_count += 1
            await asyncio.sleep(0.01)
    
    def start_sync(self) -> None:
        self._running = True
        self._stats.start_time = time.time()
    
    def stop(self) -> None:
        self._running = False
    
    def trigger_wake_word(self, wake_word: str = "manual") -> None:
        self._state = ListenerState.LISTENING
        self._stats.wake_word_count += 1
        for callback in self._on_wake_word:
            try:
                callback(wake_word, 1.0)
            except Exception:
                pass
    
    def cancel_listening(self) -> None:
        self._state = ListenerState.IDLE
    
    def process_chunk(self, audio_chunk: bytes) -> Optional[bytes]:
        self._stats.total_chunks += 1
        return None
    
    def reset(self) -> None:
        self._state = ListenerState.IDLE
        self._queued_utterances.clear()
    
    def get_stats(self) -> dict:
        return {
            "state": self._state.name,
            "is_running": self._running,
            "total_chunks": self._stats.total_chunks,
            "wake_word_count": self._stats.wake_word_count,
            "utterance_count": self._stats.utterance_count,
        }


# ─────────────────────────────────────────────────────────────────
# Global Instance
# ─────────────────────────────────────────────────────────────────

_listener: Optional[ContinuousListener] = None


def get_continuous_listener() -> ContinuousListener:
    """Get or create global continuous listener."""
    global _listener
    if _listener is None:
        _listener = ContinuousListener()
    return _listener
