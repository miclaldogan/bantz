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


# Convenience functions
_detector: Optional[WakeWordDetector] = None


def get_wake_word_detector() -> WakeWordDetector:
    """Get or create global wake word detector."""
    global _detector
    if _detector is None:
        _detector = WakeWordDetector()
    return _detector
