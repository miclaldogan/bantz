"""Streaming Audio Playback (Issue #10).

Provides real-time audio playback for streaming TTS output.
"""
from __future__ import annotations

import threading
from queue import Queue, Empty
from typing import Optional, Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ─────────────────────────────────────────────────────────────────
# Streaming Player
# ─────────────────────────────────────────────────────────────────

class StreamingPlayer:
    """Play audio chunks as they're generated.
    
    Provides real-time audio playback with a buffer queue.
    Supports pyaudio and fallback to simpleaudio.
    
    Usage:
        player = StreamingPlayer()
        player.start()
        
        for chunk in tts.stream("Uzun metin..."):
            player.add_chunk(chunk.data)
        
        player.finish()  # Wait for playback to complete
        player.stop()
    """
    
    def __init__(
        self,
        sample_rate: int = 22050,
        channels: int = 1,
        sample_width: int = 2,
        buffer_size: int = 1024,
    ):
        """Initialize streaming player.
        
        Args:
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels (1 = mono, 2 = stereo)
            sample_width: Bytes per sample (2 = 16-bit, 4 = 32-bit)
            buffer_size: Frames per buffer
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.buffer_size = buffer_size
        
        self._queue: Queue[Optional[bytes]] = Queue()
        self._playing = False
        self._thread: Optional[threading.Thread] = None
        self._audio = None
        self._stream = None
        
        # Callbacks
        self._on_start: Optional[Callable[[], Any]] = None
        self._on_stop: Optional[Callable[[], Any]] = None
        self._on_chunk: Optional[Callable[[int], Any]] = None
        
        # Stats
        self._chunks_played = 0
        self._bytes_played = 0
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def is_playing(self) -> bool:
        """Check if player is active."""
        return self._playing
    
    @property
    def chunks_played(self) -> int:
        """Get number of chunks played."""
        return self._chunks_played
    
    @property
    def bytes_played(self) -> int:
        """Get total bytes played."""
        return self._bytes_played
    
    @property
    def queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_start(self, callback: Callable[[], Any]) -> None:
        """Set callback for playback start."""
        self._on_start = callback
    
    def on_stop(self, callback: Callable[[], Any]) -> None:
        """Set callback for playback stop."""
        self._on_stop = callback
    
    def on_chunk(self, callback: Callable[[int], Any]) -> None:
        """Set callback for each chunk played (receives chunk index)."""
        self._on_chunk = callback
    
    # ─────────────────────────────────────────────────────────────
    # Playback Control
    # ─────────────────────────────────────────────────────────────
    
    def start(self) -> None:
        """Start playback thread."""
        if self._playing:
            return
        
        self._playing = True
        self._chunks_played = 0
        self._bytes_played = 0
        
        # Try to initialize audio backend
        if not self._init_audio():
            self._playing = False
            raise RuntimeError("Could not initialize audio backend")
        
        # Start playback thread
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()
        
        if self._on_start:
            try:
                self._on_start()
            except Exception:
                pass
    
    def add_chunk(self, audio_chunk: bytes) -> None:
        """Add audio chunk to playback queue.
        
        Args:
            audio_chunk: Raw audio bytes
        """
        if self._playing:
            self._queue.put(audio_chunk)
    
    def finish(self, timeout: float = 10.0) -> None:
        """Wait for all queued audio to finish playing.
        
        Args:
            timeout: Maximum wait time in seconds
        """
        if not self._playing:
            return
        
        # Add sentinel to signal end
        self._queue.put(None)
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
    
    def stop(self) -> None:
        """Stop playback immediately."""
        self._playing = False
        
        # Clear queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break
        
        # Add sentinel to unblock thread
        self._queue.put(None)
        
        # Wait for thread
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        
        # Close audio stream
        self._close_audio()
        
        if self._on_stop:
            try:
                self._on_stop()
            except Exception:
                pass
    
    def clear(self) -> None:
        """Clear the audio queue without stopping."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break
    
    # ─────────────────────────────────────────────────────────────
    # Audio Backend
    # ─────────────────────────────────────────────────────────────
    
    def _init_audio(self) -> bool:
        """Initialize audio backend.
        
        Returns:
            True if successful
        """
        # Try pyaudio first
        try:
            import pyaudio
            
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                format=self._get_pyaudio_format(),
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.buffer_size,
            )
            return True
            
        except (ImportError, Exception):
            pass
        
        # Fallback to sounddevice
        try:
            import sounddevice as sd
            
            self._audio = "sounddevice"
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16" if self.sample_width == 2 else "float32",
            )
            self._stream.start()
            return True
            
        except (ImportError, Exception):
            pass
        
        return False
    
    def _get_pyaudio_format(self) -> int:
        """Get pyaudio format constant."""
        import pyaudio
        
        if self.sample_width == 1:
            return pyaudio.paInt8
        elif self.sample_width == 2:
            return pyaudio.paInt16
        elif self.sample_width == 4:
            return pyaudio.paFloat32
        return pyaudio.paInt16
    
    def _close_audio(self) -> None:
        """Close audio backend."""
        if self._stream:
            try:
                if hasattr(self._stream, "stop_stream"):
                    self._stream.stop_stream()
                if hasattr(self._stream, "close"):
                    self._stream.close()
            except Exception:
                pass
            self._stream = None
        
        if self._audio and self._audio != "sounddevice":
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None
    
    def _play_loop(self) -> None:
        """Main playback loop (runs in thread)."""
        while self._playing:
            try:
                chunk = self._queue.get(timeout=0.1)
                
                if chunk is None:
                    # Sentinel - stop playback
                    break
                
                # Write to stream
                if self._stream:
                    if self._audio == "sounddevice":
                        self._stream.write(chunk)
                    else:
                        self._stream.write(chunk)
                
                self._chunks_played += 1
                self._bytes_played += len(chunk)
                
                if self._on_chunk:
                    try:
                        self._on_chunk(self._chunks_played)
                    except Exception:
                        pass
                
            except Empty:
                continue
            except Exception:
                break
        
        self._playing = False
        self._close_audio()
        
        if self._on_stop:
            try:
                self._on_stop()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────
# Audio Buffer
# ─────────────────────────────────────────────────────────────────

class AudioBuffer:
    """Accumulate audio chunks into a buffer.
    
    Useful for collecting streamed audio before playback.
    
    Usage:
        buffer = AudioBuffer()
        
        for chunk in tts.stream(text):
            buffer.add(chunk.data)
        
        # Get complete audio
        audio = buffer.get_bytes()
        buffer.play()
    """
    
    def __init__(self, sample_rate: int = 22050):
        """Initialize buffer.
        
        Args:
            sample_rate: Audio sample rate
        """
        self.sample_rate = sample_rate
        self._chunks: list[bytes] = []
        self._total_bytes = 0
    
    def add(self, data: bytes) -> None:
        """Add audio data to buffer.
        
        Args:
            data: Audio bytes
        """
        self._chunks.append(data)
        self._total_bytes += len(data)
    
    def get_bytes(self) -> bytes:
        """Get complete audio as bytes.
        
        Returns:
            Concatenated audio bytes
        """
        return b"".join(self._chunks)
    
    def clear(self) -> None:
        """Clear the buffer."""
        self._chunks.clear()
        self._total_bytes = 0
    
    @property
    def size(self) -> int:
        """Get total bytes in buffer."""
        return self._total_bytes
    
    @property
    def duration_ms(self) -> int:
        """Estimate audio duration in milliseconds."""
        # Assuming 16-bit mono audio
        samples = self._total_bytes // 2
        return int(samples / self.sample_rate * 1000)
    
    def play(self) -> None:
        """Play buffered audio using system player."""
        import shutil
        import subprocess
        import tempfile
        import wave
        
        audio_data = self.get_bytes()
        if not audio_data:
            return
        
        # Write to temp WAV file
        with tempfile.NamedTemporaryFile(
            prefix="bantz_audio_",
            suffix=".wav",
            delete=False,
        ) as f:
            with wave.open(f.name, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.sample_rate)
                wav.writeframes(audio_data)
            temp_path = f.name
        
        # Find and use player
        player = shutil.which("paplay") or shutil.which("aplay")
        if player:
            subprocess.Popen(
                [player, temp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).wait()


# ─────────────────────────────────────────────────────────────────
# Mock Player for Testing
# ─────────────────────────────────────────────────────────────────

class MockStreamingPlayer:
    """Mock player for testing without audio hardware."""
    
    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate
        self._chunks: list[bytes] = []
        self._playing = False
        self._started_count = 0
        self._stopped_count = 0
    
    @property
    def is_playing(self) -> bool:
        return self._playing
    
    @property
    def chunks_received(self) -> list[bytes]:
        return self._chunks
    
    @property
    def total_bytes(self) -> int:
        return sum(len(c) for c in self._chunks)
    
    def start(self) -> None:
        self._playing = True
        self._started_count += 1
    
    def add_chunk(self, audio_chunk: bytes) -> None:
        self._chunks.append(audio_chunk)
    
    def finish(self, timeout: float = 10.0) -> None:
        self._playing = False
    
    def stop(self) -> None:
        self._playing = False
        self._stopped_count += 1
    
    def clear(self) -> None:
        self._chunks.clear()
