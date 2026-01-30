"""
Bantz Wake Word Detection - "Hey Bantz" aktivasyonu
v0.6.3

OpenWakeWord kullanarak sürekli dinleme ve wake word algılama.
"""
from __future__ import annotations

import logging
import threading
import time
import queue
from dataclasses import dataclass
from typing import Optional, Callable, List
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WakeWordConfig:
    """Wake word detection configuration."""
    # Model settings
    model_path: Optional[str] = None  # Custom model path, or use default
    threshold: float = 0.5  # Detection threshold (0-1)
    
    # Audio settings
    sample_rate: int = 16000
    chunk_size: int = 1280  # ~80ms at 16kHz
    
    # Behavior
    cooldown_seconds: float = 2.0  # Minimum time between activations
    

class WakeWordDetector:
    """
    Wake word detector using OpenWakeWord.
    
    Listens continuously for "Hey Bantz" or similar wake phrases.
    """
    
    def __init__(self, config: Optional[WakeWordConfig] = None):
        self.config = config or WakeWordConfig()
        self._owwModel = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[str], None]] = None
        self._last_activation = 0.0
        self._stream = None
        
    def _load_model(self):
        """Load OpenWakeWord model."""
        if self._owwModel is not None:
            return
            
        try:
            from openwakeword.model import Model
            
            # Use default models if no custom path
            # OpenWakeWord includes: "hey_jarvis", "alexa", "hey_mycroft", etc.
            # We'll use "hey_jarvis" as closest to "hey bantz" for now
            # Later we can train a custom model
            
            if self.config.model_path:
                self._owwModel = Model(
                    wakeword_models=[self.config.model_path],
                    inference_framework="onnx",  # Use ONNX instead of tflite for NumPy 2.x compat
                )
                logger.info(f"[WakeWord] Custom model loaded: {self.config.model_path}")
            else:
                # Use built-in models with ONNX
                self._owwModel = Model(
                    inference_framework="onnx",  # Use ONNX instead of tflite
                )
                logger.info("[WakeWord] Default models loaded (hey_jarvis, alexa, etc.)")
                
        except Exception as e:
            logger.error(f"[WakeWord] Failed to load model: {e}")
            raise
    
    def set_callback(self, callback: Callable[[str], None]) -> None:
        """
        Set callback for wake word detection.
        
        Args:
            callback: Function called with detected wake word name
        """
        self._callback = callback
    
    def start(self) -> bool:
        """
        Start wake word detection.
        
        Returns:
            True if started successfully
        """
        if self._running:
            return True
            
        try:
            self._load_model()
            
            import sounddevice as sd
            
            self._running = True
            self._thread = threading.Thread(target=self._detection_loop, daemon=True)
            self._thread.start()
            
            logger.info("[WakeWord] Detection started")
            return True
            
        except Exception as e:
            logger.error(f"[WakeWord] Failed to start: {e}")
            return False
    
    def stop(self) -> None:
        """Stop wake word detection."""
        self._running = False
        
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
            
        logger.info("[WakeWord] Detection stopped")
    
    def _detection_loop(self) -> None:
        """Main detection loop running in background thread."""
        import sounddevice as sd
        
        try:
            # Audio buffer for streaming
            audio_buffer = queue.Queue()
            
            def audio_callback(indata, frames, time_info, status):
                if status:
                    return
                # Convert to mono float32
                audio_buffer.put(indata.copy().flatten())
            
            # Start audio stream
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.config.chunk_size,
                callback=audio_callback,
            )
            self._stream.start()
            
            logger.debug("[WakeWord] Audio stream started")
            
            while self._running:
                try:
                    # Get audio chunk (with timeout to check running flag)
                    try:
                        audio_chunk = audio_buffer.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    
                    # Convert to int16 for OpenWakeWord
                    audio_int16 = (audio_chunk * 32767).astype(np.int16)
                    
                    # Run detection
                    predictions = self._owwModel.predict(audio_int16)
                    
                    # Check each model's prediction
                    for model_name, score in predictions.items():
                        if score >= self.config.threshold:
                            # Check cooldown
                            now = time.time()
                            if now - self._last_activation >= self.config.cooldown_seconds:
                                self._last_activation = now
                                logger.info(f"[WakeWord] Detected: {model_name} (score: {score:.2f})")
                                
                                if self._callback:
                                    try:
                                        self._callback(model_name)
                                    except Exception as e:
                                        logger.error(f"[WakeWord] Callback error: {e}")
                                        
                except Exception as e:
                    logger.error(f"[WakeWord] Detection error: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"[WakeWord] Loop error: {e}")
        finally:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None


class VADRecorder:
    """
    Voice Activity Detection based recorder.
    
    Records audio until silence is detected (speech end).
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.01,
        silence_duration: float = 1.5,  # Seconds of silence to stop
        max_duration: float = 30.0,  # Maximum recording duration
        min_speech_duration: float = 0.3,  # Minimum speech to be valid
    ):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.min_speech_duration = min_speech_duration
        
        self._frames: List[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        self._recording = False
        
        # Speech state tracking
        self._speech_started = False
        self._silence_start: Optional[float] = None
        self._record_start: Optional[float] = None
        self._speech_duration = 0.0
    
    def start(self) -> None:
        """Start VAD-based recording."""
        import sounddevice as sd
        
        with self._lock:
            self._frames = []
            self._speech_started = False
            self._silence_start = None
            self._record_start = time.time()
            self._speech_duration = 0.0
            self._recording = True
        
        def callback(indata, frames, time_info, status):
            if status or not self._recording:
                return
                
            audio = indata.copy().flatten()
            
            # Calculate RMS energy
            rms = np.sqrt(np.mean(audio ** 2))
            
            with self._lock:
                self._frames.append(audio)
                
                now = time.time()
                
                # Check if this is speech
                if rms > self.silence_threshold:
                    self._speech_started = True
                    self._silence_start = None
                    self._speech_duration += len(audio) / self.sample_rate
                else:
                    # Silence detected
                    if self._speech_started:
                        if self._silence_start is None:
                            self._silence_start = now
        
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()
    
    def should_stop(self) -> tuple[bool, str]:
        """
        Check if recording should stop.
        
        Returns:
            (should_stop, reason) tuple
        """
        with self._lock:
            now = time.time()
            elapsed = now - (self._record_start or now)
            
            # Max duration exceeded
            if elapsed >= self.max_duration:
                return True, "max_duration"
            
            # Check for silence after speech
            if self._speech_started and self._silence_start:
                silence_elapsed = now - self._silence_start
                if silence_elapsed >= self.silence_duration:
                    # Check minimum speech
                    if self._speech_duration >= self.min_speech_duration:
                        return True, "silence_detected"
                    else:
                        return True, "too_short"
            
            return False, ""
    
    def stop(self) -> np.ndarray:
        """
        Stop recording and return audio.
        
        Returns:
            Audio data as float32 numpy array
        """
        self._recording = False
        
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        
        with self._lock:
            if not self._frames:
                return np.zeros((0,), dtype=np.float32)
            
            audio = np.concatenate(self._frames)
            self._frames = []
            return audio
    
    def get_stats(self) -> dict:
        """Get recording statistics."""
        with self._lock:
            return {
                "speech_started": self._speech_started,
                "speech_duration": self._speech_duration,
                "silence_start": self._silence_start,
            }


# ─────────────────────────────────────────────────────────────────
# Multi Wake Word Detector
# ─────────────────────────────────────────────────────────────────

@dataclass
class MultiWakeWordConfig:
    """Multi wake word detection configuration.
    
    Attributes:
        wake_words: List of wake word model names to detect
        thresholds: Per-model thresholds (model_name -> threshold)
        default_threshold: Default threshold for all models
        sample_rate: Audio sample rate
        chunk_size: Audio chunk size in samples
        cooldown_seconds: Minimum time between activations
        inference_framework: ONNX or tflite
    """
    wake_words: List[str] = None
    thresholds: dict = None
    default_threshold: float = 0.5
    sample_rate: int = 16000
    chunk_size: int = 1280
    cooldown_seconds: float = 2.0
    inference_framework: str = "onnx"
    
    def __post_init__(self):
        if self.wake_words is None:
            self.wake_words = ["hey_jarvis", "hey_mycroft", "alexa"]
        if self.thresholds is None:
            self.thresholds = {}


class MultiWakeWordDetector:
    """Multi wake word detector using OpenWakeWord.
    
    Supports multiple wake words simultaneously:
    - hey_jarvis (default)
    - hey_mycroft
    - alexa
    - Custom trained models
    
    Usage:
        detector = MultiWakeWordDetector(config)
        detector.on_wake_word(callback)
        detector.start()
        
        # ...later
        detector.stop()
    """
    
    # Built-in wake word models
    BUILTIN_MODELS = [
        "hey_jarvis",
        "hey_mycroft",
        "alexa",
        "hey_rhasspy",
        "timer",
        "weather",
    ]
    
    def __init__(self, config: Optional[MultiWakeWordConfig] = None):
        """Initialize multi wake word detector.
        
        Args:
            config: Detection configuration
        """
        self.config = config or MultiWakeWordConfig()
        
        self._model = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        
        self._callbacks: List[Callable[[str, float], None]] = []
        self._last_activations: dict = {}  # model_name -> timestamp
        
        # Statistics
        self._detections: List[dict] = []
        self._total_chunks = 0
    
    def _load_models(self) -> None:
        """Load OpenWakeWord models."""
        if self._model is not None:
            return
        
        try:
            from openwakeword.model import Model
            
            # Filter to valid wake words
            valid_models = []
            custom_models = []
            
            for ww in self.config.wake_words:
                if ww in self.BUILTIN_MODELS:
                    valid_models.append(ww)
                else:
                    # Assume it's a custom model path
                    custom_models.append(ww)
            
            # Load models
            if custom_models:
                self._model = Model(
                    wakeword_models=custom_models,
                    inference_framework=self.config.inference_framework,
                )
                logger.info(f"[MultiWakeWord] Custom models loaded: {custom_models}")
            else:
                # Use default models
                self._model = Model(
                    inference_framework=self.config.inference_framework,
                )
                logger.info(f"[MultiWakeWord] Built-in models loaded")
            
        except ImportError:
            logger.error("[MultiWakeWord] OpenWakeWord not installed")
            raise
        except Exception as e:
            logger.error(f"[MultiWakeWord] Failed to load models: {e}")
            raise
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def is_running(self) -> bool:
        """Check if detection is running."""
        return self._running
    
    @property
    def wake_words(self) -> List[str]:
        """Get list of wake words being detected."""
        return self.config.wake_words.copy()
    
    @property
    def detection_count(self) -> int:
        """Get total number of detections."""
        return len(self._detections)
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_wake_word(self, callback: Callable[[str, float], None]) -> None:
        """Add callback for wake word detection.
        
        Args:
            callback: Function called with (wake_word_name, confidence)
        """
        self._callbacks.append(callback)
    
    def clear_callbacks(self) -> None:
        """Clear all callbacks."""
        self._callbacks.clear()
    
    # ─────────────────────────────────────────────────────────────
    # Control
    # ─────────────────────────────────────────────────────────────
    
    def start(self) -> bool:
        """Start wake word detection.
        
        Returns:
            True if started successfully
        """
        if self._running:
            return True
        
        try:
            self._load_models()
            
            self._running = True
            self._thread = threading.Thread(target=self._detection_loop, daemon=True)
            self._thread.start()
            
            logger.info("[MultiWakeWord] Detection started")
            return True
            
        except Exception as e:
            logger.error(f"[MultiWakeWord] Failed to start: {e}")
            return False
    
    def stop(self) -> None:
        """Stop wake word detection."""
        self._running = False
        
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        
        logger.info("[MultiWakeWord] Detection stopped")
    
    # ─────────────────────────────────────────────────────────────
    # Detection Loop
    # ─────────────────────────────────────────────────────────────
    
    def _detection_loop(self) -> None:
        """Main detection loop."""
        import sounddevice as sd
        
        try:
            audio_queue = queue.Queue()
            
            def audio_callback(indata, frames, time_info, status):
                if status:
                    return
                audio_queue.put(indata.copy().flatten())
            
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.config.chunk_size,
                callback=audio_callback,
            )
            self._stream.start()
            
            while self._running:
                try:
                    audio = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                self._total_chunks += 1
                
                # Convert to int16
                audio_int16 = (audio * 32767).astype(np.int16)
                
                # Run prediction
                predictions = self._model.predict(audio_int16)
                
                # Check each wake word
                now = time.time()
                for model_name, score in predictions.items():
                    threshold = self.config.thresholds.get(
                        model_name, self.config.default_threshold
                    )
                    
                    if score >= threshold:
                        # Check cooldown
                        last_activation = self._last_activations.get(model_name, 0)
                        if now - last_activation >= self.config.cooldown_seconds:
                            self._last_activations[model_name] = now
                            
                            # Record detection
                            self._detections.append({
                                "model": model_name,
                                "score": score,
                                "timestamp": now,
                            })
                            
                            logger.info(
                                f"[MultiWakeWord] Detected: {model_name} "
                                f"(score: {score:.2f})"
                            )
                            
                            # Fire callbacks
                            self._fire_callbacks(model_name, score)
                
        except Exception as e:
            logger.error(f"[MultiWakeWord] Loop error: {e}")
        finally:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
    
    def _fire_callbacks(self, wake_word: str, confidence: float) -> None:
        """Fire all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(wake_word, confidence)
            except Exception as e:
                logger.error(f"[MultiWakeWord] Callback error: {e}")
    
    # ─────────────────────────────────────────────────────────────
    # Single Prediction
    # ─────────────────────────────────────────────────────────────
    
    def predict(self, audio: bytes) -> dict:
        """Run prediction on audio chunk.
        
        Args:
            audio: Raw audio bytes (16-bit PCM)
            
        Returns:
            Dictionary of model_name -> score
        """
        self._load_models()
        
        # Convert bytes to int16
        num_samples = len(audio) // 2
        audio_int16 = np.frombuffer(audio[:num_samples * 2], dtype=np.int16)
        
        return self._model.predict(audio_int16)
    
    def predict_array(self, audio: np.ndarray) -> dict:
        """Run prediction on numpy array.
        
        Args:
            audio: Audio as float32 array
            
        Returns:
            Dictionary of model_name -> score
        """
        self._load_models()
        
        audio_int16 = (audio * 32767).astype(np.int16)
        return self._model.predict(audio_int16)
    
    # ─────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────
    
    def reset(self) -> None:
        """Reset detection state."""
        self._last_activations.clear()
        self._detections.clear()
        self._total_chunks = 0
        
        if self._model:
            try:
                self._model.reset()
            except Exception:
                pass
    
    def add_wake_word(self, wake_word: str, threshold: float = None) -> None:
        """Add a wake word to detect.
        
        Args:
            wake_word: Wake word name or model path
            threshold: Detection threshold (optional)
        """
        if wake_word not in self.config.wake_words:
            self.config.wake_words.append(wake_word)
        
        if threshold is not None:
            self.config.thresholds[wake_word] = threshold
        
        # Reload models if running
        if self._model:
            self._model = None
            self._load_models()
    
    def remove_wake_word(self, wake_word: str) -> None:
        """Remove a wake word.
        
        Args:
            wake_word: Wake word name to remove
        """
        if wake_word in self.config.wake_words:
            self.config.wake_words.remove(wake_word)
        
        if wake_word in self.config.thresholds:
            del self.config.thresholds[wake_word]
    
    def set_threshold(self, wake_word: str, threshold: float) -> None:
        """Set threshold for a wake word.
        
        Args:
            wake_word: Wake word name
            threshold: Detection threshold (0-1)
        """
        self.config.thresholds[wake_word] = threshold
    
    def get_stats(self) -> dict:
        """Get detector statistics."""
        return {
            "is_running": self._running,
            "wake_words": self.config.wake_words,
            "total_chunks": self._total_chunks,
            "detection_count": len(self._detections),
            "last_activations": self._last_activations.copy(),
        }
    
    def get_recent_detections(self, limit: int = 10) -> List[dict]:
        """Get recent detections.
        
        Args:
            limit: Maximum number of detections to return
            
        Returns:
            List of detection records
        """
        return self._detections[-limit:]


# ─────────────────────────────────────────────────────────────────
# Mock Multi Wake Word Detector
# ─────────────────────────────────────────────────────────────────

class MockMultiWakeWordDetector:
    """Mock multi wake word detector for testing."""
    
    def __init__(self, config: Optional[MultiWakeWordConfig] = None):
        self.config = config or MultiWakeWordConfig()
        
        self._running = False
        self._callbacks: List[Callable[[str, float], None]] = []
        self._predictions: dict = {}
        self._detect_queue: List[tuple] = []  # (wake_word, confidence)
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def wake_words(self) -> List[str]:
        return self.config.wake_words.copy()
    
    def set_predictions(self, predictions: dict) -> None:
        """Set predictions to return."""
        self._predictions = predictions
    
    def queue_detection(self, wake_word: str, confidence: float) -> None:
        """Queue a detection to fire on next process."""
        self._detect_queue.append((wake_word, confidence))
    
    def on_wake_word(self, callback: Callable[[str, float], None]) -> None:
        self._callbacks.append(callback)
    
    def clear_callbacks(self) -> None:
        self._callbacks.clear()
    
    def start(self) -> bool:
        self._running = True
        return True
    
    def stop(self) -> None:
        self._running = False
    
    def predict(self, audio: bytes) -> dict:
        return self._predictions
    
    def predict_array(self, audio: np.ndarray) -> dict:
        return self._predictions
    
    def process_detection(self) -> None:
        """Process queued detection and fire callbacks."""
        if self._detect_queue:
            wake_word, confidence = self._detect_queue.pop(0)
            for callback in self._callbacks:
                try:
                    callback(wake_word, confidence)
                except Exception:
                    pass
    
    def reset(self) -> None:
        self._detect_queue.clear()
    
    def add_wake_word(self, wake_word: str, threshold: float = None) -> None:
        if wake_word not in self.config.wake_words:
            self.config.wake_words.append(wake_word)
    
    def remove_wake_word(self, wake_word: str) -> None:
        if wake_word in self.config.wake_words:
            self.config.wake_words.remove(wake_word)
    
    def set_threshold(self, wake_word: str, threshold: float) -> None:
        self.config.thresholds[wake_word] = threshold
    
    def get_stats(self) -> dict:
        return {
            "is_running": self._running,
            "wake_words": self.config.wake_words,
        }


# ─────────────────────────────────────────────────────────────────
# Convenience functions
# ─────────────────────────────────────────────────────────────────

_detector: Optional[WakeWordDetector] = None
_multi_detector: Optional[MultiWakeWordDetector] = None


def get_wake_word_detector() -> WakeWordDetector:
    """Get or create global wake word detector."""
    global _detector
    if _detector is None:
        _detector = WakeWordDetector()
    return _detector


def get_multi_wake_word_detector() -> MultiWakeWordDetector:
    """Get or create global multi wake word detector."""
    global _multi_detector
    if _multi_detector is None:
        _multi_detector = MultiWakeWordDetector()
    return _multi_detector
