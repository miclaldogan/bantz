"""
Bantz Orchestrator - Full System Startup Controller.

Tüm Bantz bileşenlerini koordine eden ana sınıf:
- Wake Word Detection ("Hey Jarvis")
- Voice Recognition (ASR/Whisper)
- Text-to-Speech (TTS/Piper)
- Router & NLU
- Jarvis Panel & Overlay UI
- Browser Extension Bridge

Tek komutla sistemi tam olarak ayağa kaldırır.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from bantz.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

class ComponentState(Enum):
    """State of a system component."""
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    ERROR = auto()
    STOPPING = auto()


class SystemState(Enum):
    """Overall system state."""
    OFFLINE = auto()        # Sistem kapalı
    BOOTING = auto()        # Başlatılıyor
    READY = auto()          # Hazır - wake word dinliyor
    LISTENING = auto()      # "Hey Jarvis" algılandı, konuşma dinleniyor
    PROCESSING = auto()     # Komut işleniyor
    SPEAKING = auto()       # Yanıt söyleniyor
    ERROR = auto()          # Hata durumu


@dataclass
class OrchestratorConfig:
    """Orchestrator configuration.
    
    Attributes:
        session_name: Session name for server
        policy_path: Path to policy.json
        log_path: Path to log file
        
        enable_wake_word: Enable "Hey Jarvis" detection
        enable_tts: Enable text-to-speech
        enable_overlay: Enable Jarvis overlay UI
        enable_panel: Enable Jarvis panel UI
        enable_browser: Enable browser extension bridge
        
        wake_words: List of wake words to detect
        piper_model: Path to Piper TTS model
        whisper_model: Whisper model size
        
        ollama_url: Ollama server URL
        ollama_model: Ollama model name
        
        startup_sound: Play startup sound
        wake_confirmation: What Jarvis says on wake
    """
    # Server
    session_name: str = "default"
    policy_path: str = "config/policy.json"
    log_path: str = "bantz.log.jsonl"
    
    # Components
    enable_wake_word: bool = True
    enable_tts: bool = True
    enable_overlay: bool = True
    enable_panel: bool = False  # Panel is optional, overlay is primary
    enable_browser: bool = True
    
    # Wake Word
    wake_words: List[str] = field(default_factory=lambda: ["hey_jarvis"])
    wake_threshold: float = 0.5
    wake_cooldown: float = 2.0
    
    # Voice
    piper_model: str = ""  # Path to Piper model
    whisper_model: str = "base"
    language: str = "tr"
    sample_rate: int = 16000
    
    # LLM
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    
    # UX
    startup_sound: bool = True
    wake_confirmation: str = "Sizi dinliyorum efendim."
    thinking_phrase: str = "Anlıyorum..."
    error_phrase: str = "Bir sorun oluştu."
    
    @classmethod
    def from_env(cls) -> OrchestratorConfig:
        """Create config from environment variables."""
        return cls(
            session_name=os.getenv("BANTZ_SESSION", "default"),
            policy_path=os.getenv("BANTZ_POLICY", "config/policy.json"),
            log_path=os.getenv("BANTZ_LOG", "bantz.log.jsonl"),
            
            enable_wake_word=os.getenv("BANTZ_WAKE_WORD", "1") == "1",
            enable_tts=os.getenv("BANTZ_TTS", "1") == "1",
            enable_overlay=os.getenv("BANTZ_OVERLAY", "1") == "1",
            enable_panel=os.getenv("BANTZ_PANEL", "0") == "1",
            enable_browser=os.getenv("BANTZ_BROWSER", "1") == "1",
            
            piper_model=os.getenv("BANTZ_PIPER_MODEL", ""),
            whisper_model=os.getenv("BANTZ_WHISPER_MODEL", "base"),
            language=os.getenv("BANTZ_LANGUAGE", "tr"),
            
            ollama_url=os.getenv("BANTZ_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("BANTZ_OLLAMA_MODEL", "qwen2.5:3b-instruct"),
        )


# ─────────────────────────────────────────────────────────────────
# Component Status
# ─────────────────────────────────────────────────────────────────

@dataclass
class ComponentStatus:
    """Status of a single component."""
    name: str
    state: ComponentState = ComponentState.STOPPED
    error: Optional[str] = None
    started_at: Optional[float] = None
    
    @property
    def is_running(self) -> bool:
        return self.state == ComponentState.RUNNING
    
    @property
    def uptime_seconds(self) -> float:
        if self.started_at:
            return time.time() - self.started_at
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.name.lower(),
            "error": self.error,
            "uptime": round(self.uptime_seconds, 1),
        }


# ─────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────

class BantzOrchestrator:
    """
    Main system orchestrator.
    
    Coordinates all Bantz components:
    - Server (router, policy, context)
    - Wake Word Detector
    - ASR (Speech-to-Text)
    - TTS (Text-to-Speech)
    - Overlay UI
    - Browser Extension Bridge
    
    Usage:
        orchestrator = BantzOrchestrator()
        orchestrator.start()  # Blocks until shutdown
    
    Or async:
        async with BantzOrchestrator() as orchestrator:
            await orchestrator.run_forever()
    """
    
    def __init__(self, config: Optional[OrchestratorConfig] = None):
        """Initialize orchestrator.
        
        Args:
            config: Configuration (uses env vars if not provided)
        """
        self.config = config or OrchestratorConfig.from_env()
        
        # State
        self._state = SystemState.OFFLINE
        self._running = False
        self._shutdown_event = threading.Event()
        
        # Components
        self._server = None
        self._wake_word_detector = None
        self._asr = None
        self._tts = None
        self._overlay_hook = None
        self._browser_bridge = None
        self._continuous_listener = None
        
        # Component status tracking
        self._component_status: Dict[str, ComponentStatus] = {
            "server": ComponentStatus("server"),
            "wake_word": ComponentStatus("wake_word"),
            "asr": ComponentStatus("asr"),
            "tts": ComponentStatus("tts"),
            "overlay": ComponentStatus("overlay"),
            "browser": ComponentStatus("browser"),
        }
        
        # Event bus
        self._event_bus = get_event_bus()
        
        # Callbacks
        self._on_state_change: List[Callable[[SystemState], None]] = []
        self._on_wake: List[Callable[[str, float], None]] = []
        self._on_command: List[Callable[[str], None]] = []
        self._on_response: List[Callable[[str], None]] = []
        
        # Async loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None
        
        logger.info("[Orchestrator] Initialized")
    
    # ─────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────
    
    @property
    def state(self) -> SystemState:
        """Current system state."""
        return self._state
    
    @property
    def is_running(self) -> bool:
        """Whether system is running."""
        return self._running
    
    @property
    def is_ready(self) -> bool:
        """Whether system is ready to accept commands."""
        return self._state in (SystemState.READY, SystemState.LISTENING)
    
    def get_status(self) -> Dict[str, Any]:
        """Get full system status."""
        return {
            "state": self._state.name.lower(),
            "running": self._running,
            "components": {
                name: status.to_dict()
                for name, status in self._component_status.items()
            },
            "config": {
                "session": self.config.session_name,
                "wake_words": self.config.wake_words,
                "tts_enabled": self.config.enable_tts,
                "overlay_enabled": self.config.enable_overlay,
            },
        }
    
    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def on_state_change(self, callback: Callable[[SystemState], None]) -> None:
        """Register state change callback."""
        self._on_state_change.append(callback)
    
    def on_wake(self, callback: Callable[[str, float], None]) -> None:
        """Register wake word callback."""
        self._on_wake.append(callback)
    
    def on_command(self, callback: Callable[[str], None]) -> None:
        """Register command callback."""
        self._on_command.append(callback)
    
    def on_response(self, callback: Callable[[str], None]) -> None:
        """Register response callback."""
        self._on_response.append(callback)
    
    def _set_state(self, state: SystemState) -> None:
        """Set system state and notify callbacks."""
        if self._state != state:
            old_state = self._state
            self._state = state
            logger.info(f"[Orchestrator] State: {old_state.name} -> {state.name}")
            
            for callback in self._on_state_change:
                try:
                    callback(state)
                except Exception as e:
                    logger.error(f"[Orchestrator] State callback error: {e}")
    
    def _set_component_state(
        self,
        name: str,
        state: ComponentState,
        error: Optional[str] = None,
    ) -> None:
        """Update component state."""
        if name in self._component_status:
            status = self._component_status[name]
            status.state = state
            status.error = error
            if state == ComponentState.RUNNING:
                status.started_at = time.time()
    
    # ─────────────────────────────────────────────────────────────
    # Startup
    # ─────────────────────────────────────────────────────────────
    
    def start(self) -> int:
        """Start the orchestrator (blocking).
        
        Returns:
            Exit code (0 for success)
        """
        self._print_banner()
        self._set_state(SystemState.BOOTING)
        self._running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        try:
            # Start all components
            self._start_components()
            
            # Check if minimum components are ready
            if not self._check_minimum_ready():
                logger.error("[Orchestrator] Minimum components not ready")
                return 1
            
            # System ready
            self._set_state(SystemState.READY)
            self._play_startup_sound()
            
            print("\n✅ Sistem hazır! 'Hey Jarvis' diyerek başlayabilirsiniz.\n")
            print("   Çıkmak için: Ctrl+C\n")
            
            # Run main loop
            self._run_main_loop()
            
            return 0
            
        except KeyboardInterrupt:
            print("\n🛑 Kapatılıyor...")
        except Exception as e:
            logger.error(f"[Orchestrator] Fatal error: {e}", exc_info=True)
            print(f"❌ Kritik hata: {e}")
            return 1
        finally:
            self._shutdown()
        
        return 0
    
    async def start_async(self) -> None:
        """Start the orchestrator (async version)."""
        self._print_banner()
        self._set_state(SystemState.BOOTING)
        self._running = True
        
        try:
            # Start components
            self._start_components()
            
            if not self._check_minimum_ready():
                raise RuntimeError("Minimum components not ready")
            
            self._set_state(SystemState.READY)
            self._play_startup_sound()
            
            # Run async main loop
            await self._run_async_loop()
            
        finally:
            self._shutdown()
    
    def _print_banner(self) -> None:
        """Print startup banner."""
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║      ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗                ║
║      ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝                ║
║      ██║███████║██████╔╝██║   ██║██║███████╗                ║
║ ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║                ║
║ ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║                ║
║  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝                ║
║                                                              ║
║            Just A Rather Very Intelligent System             ║
║                         v0.7.0                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    def _start_components(self) -> None:
        """Start all enabled components."""
        print("\n📦 Bileşenler başlatılıyor...\n")
        
        # 1. Server (Router + Policy)
        self._start_server()
        
        # 2. Overlay UI
        if self.config.enable_overlay:
            self._start_overlay()
        
        # 3. Browser Bridge
        if self.config.enable_browser:
            self._start_browser_bridge()
        
        # 4. TTS
        if self.config.enable_tts:
            self._start_tts()
        
        # 5. ASR
        self._start_asr()
        
        # 6. Wake Word Detector
        if self.config.enable_wake_word:
            self._start_wake_word()
        
        print()
    
    def _start_server(self) -> None:
        """Start the Bantz server."""
        print("   [1/6] Server...", end=" ", flush=True)
        self._set_component_state("server", ComponentState.STARTING)
        
        try:
            from bantz.server import BantzServer, get_ipc_overlay_hook, set_overlay_hook
            from bantz.router.engine import set_overlay_hook as engine_set_hook
            
            self._server = BantzServer(
                session_name=self.config.session_name,
                policy_path=self.config.policy_path,
                log_path=self.config.log_path,
            )
            
            self._set_component_state("server", ComponentState.RUNNING)
            print("✓")
            
        except Exception as e:
            self._set_component_state("server", ComponentState.ERROR, str(e))
            print(f"✗ ({e})")
            logger.error(f"[Orchestrator] Server start failed: {e}")
    
    def _start_overlay(self) -> None:
        """Start the overlay UI."""
        print("   [2/6] Overlay...", end=" ", flush=True)
        self._set_component_state("overlay", ComponentState.STARTING)
        
        try:
            from bantz.server import get_ipc_overlay_hook
            from bantz.router.engine import set_overlay_hook
            
            self._overlay_hook = get_ipc_overlay_hook()
            connected = self._overlay_hook.start()
            
            if connected:
                # Set overlay hook for router
                set_overlay_hook(self._overlay_hook)
                self._set_component_state("overlay", ComponentState.RUNNING)
                print("✓")
            else:
                self._set_component_state("overlay", ComponentState.ERROR, "Connection failed")
                print("✗ (bağlanamadı)")
                
        except Exception as e:
            self._set_component_state("overlay", ComponentState.ERROR, str(e))
            print(f"✗ ({e})")
            logger.error(f"[Orchestrator] Overlay start failed: {e}")
    
    def _start_browser_bridge(self) -> None:
        """Start the browser extension bridge."""
        print("   [3/6] Browser Bridge...", end=" ", flush=True)
        self._set_component_state("browser", ComponentState.STARTING)
        
        try:
            from bantz.browser.extension_bridge import start_extension_bridge
            
            started = start_extension_bridge()
            
            if started:
                self._set_component_state("browser", ComponentState.RUNNING)
                print("✓")
            else:
                self._set_component_state("browser", ComponentState.ERROR, "Start failed")
                print("✗ (başlatılamadı)")
                
        except Exception as e:
            self._set_component_state("browser", ComponentState.ERROR, str(e))
            print(f"✗ ({e})")
            logger.error(f"[Orchestrator] Browser bridge start failed: {e}")
    
    def _start_tts(self) -> None:
        """Start the TTS engine."""
        print("   [4/6] TTS...", end=" ", flush=True)
        self._set_component_state("tts", ComponentState.STARTING)
        
        try:
            # Check if Piper model is available
            if not self.config.piper_model:
                # Try to find a default model
                default_paths = [
                    Path.home() / ".local/share/piper/tr_TR-dfki-medium.onnx",
                    Path("/usr/share/piper/tr_TR-dfki-medium.onnx"),
                    Path("models/piper/tr.onnx"),
                ]
                
                for p in default_paths:
                    if p.exists():
                        self.config.piper_model = str(p)
                        break
            
            if not self.config.piper_model or not Path(self.config.piper_model).exists():
                self._set_component_state("tts", ComponentState.ERROR, "Model not found")
                print("✗ (model bulunamadı)")
                return
            
            from bantz.voice.tts import PiperTTS, PiperTTSConfig
            
            self._tts = PiperTTS(PiperTTSConfig(
                model_path=self.config.piper_model,
            ))
            
            self._set_component_state("tts", ComponentState.RUNNING)
            print("✓")
            
        except Exception as e:
            self._set_component_state("tts", ComponentState.ERROR, str(e))
            print(f"✗ ({e})")
            logger.error(f"[Orchestrator] TTS start failed: {e}")
    
    def _start_asr(self) -> None:
        """Start the ASR engine."""
        print("   [5/6] ASR...", end=" ", flush=True)
        self._set_component_state("asr", ComponentState.STARTING)
        
        try:
            from bantz.voice.asr import ASR, ASRConfig
            
            self._asr = ASR(ASRConfig(
                whisper_model=self.config.whisper_model,
                language=self.config.language,
                sample_rate=self.config.sample_rate,
                allow_download=True,
                vad_filter=False,  # VAD causes issues with short utterances
            ))
            
            self._set_component_state("asr", ComponentState.RUNNING)
            print("✓")
            
        except Exception as e:
            self._set_component_state("asr", ComponentState.ERROR, str(e))
            print(f"✗ ({e})")
            logger.error(f"[Orchestrator] ASR start failed: {e}")
    
    def _start_wake_word(self) -> None:
        """Start the wake word detector."""
        print("   [6/6] Wake Word...", end=" ", flush=True)
        self._set_component_state("wake_word", ComponentState.STARTING)
        
        try:
            from bantz.voice.wakeword import MultiWakeWordDetector, MultiWakeWordConfig
            
            config = MultiWakeWordConfig(
                wake_words=self.config.wake_words,
                default_threshold=self.config.wake_threshold,
                sample_rate=self.config.sample_rate,
            )
            
            self._wake_word_detector = MultiWakeWordDetector(config)
            self._wake_word_detector.on_wake_word(self._on_wake_word_detected)
            
            self._set_component_state("wake_word", ComponentState.RUNNING)
            print("✓")
            
        except Exception as e:
            self._set_component_state("wake_word", ComponentState.ERROR, str(e))
            print(f"✗ ({e})")
            logger.error(f"[Orchestrator] Wake word start failed: {e}")
    
    def _check_minimum_ready(self) -> bool:
        """Check if minimum components are ready."""
        # Server is required
        if not self._component_status["server"].is_running:
            return False
        
        # ASR is required for voice
        if not self._component_status["asr"].is_running:
            logger.warning("[Orchestrator] ASR not running - voice disabled")
        
        return True
    
    # ─────────────────────────────────────────────────────────────
    # Main Loop
    # ─────────────────────────────────────────────────────────────
    
    def _run_main_loop(self) -> None:
        """Run the main blocking loop."""
        # If wake word is enabled, use continuous listening
        if self._wake_word_detector and self._component_status["wake_word"].is_running:
            self._run_continuous_listening()
        else:
            # Fallback: just keep server running
            self._shutdown_event.wait()
    
    def _run_continuous_listening(self) -> None:
        """Run continuous listening loop with wake word."""
        try:
            from bantz.voice.continuous import (
                ContinuousListener,
                ContinuousListenerConfig,
            )
            from bantz.voice.vad import AdvancedVAD
            from bantz.voice.segmenter import SpeechSegmenter
            
            # Create listener
            config = ContinuousListenerConfig(
                sample_rate=self.config.sample_rate,
                listen_timeout=15.0,
                beep_on_wake=True,
                confirmation_phrase=self.config.wake_confirmation,
            )
            
            self._continuous_listener = ContinuousListener(
                wake_word_detector=self._wake_word_detector,
                vad=AdvancedVAD(),
                segmenter=SpeechSegmenter(),
                config=config,
            )
            
            # Register callbacks
            self._continuous_listener.on_wake_word(self._on_wake_word_detected)
            self._continuous_listener.on_utterance(self._on_utterance_received)
            self._continuous_listener.on_state_change(self._on_listener_state_change)
            
            # Start async loop in background
            self._loop = asyncio.new_event_loop()
            
            def run_listener():
                asyncio.set_event_loop(self._loop)
                try:
                    self._loop.run_until_complete(self._continuous_listener.start())
                except Exception as e:
                    logger.error(f"[Orchestrator] Listener error: {e}")
            
            listener_thread = threading.Thread(target=run_listener, daemon=True)
            listener_thread.start()
            
            # Wait for shutdown
            self._shutdown_event.wait()
            
        except ImportError as e:
            logger.warning(f"[Orchestrator] Continuous listening not available: {e}")
            self._shutdown_event.wait()
    
    async def _run_async_loop(self) -> None:
        """Run the async main loop."""
        while self._running:
            await asyncio.sleep(0.1)
    
    # ─────────────────────────────────────────────────────────────
    # Voice Callbacks
    # ─────────────────────────────────────────────────────────────
    
    def _on_wake_word_detected(self, wake_word: str, confidence: float) -> None:
        """Handle wake word detection."""
        logger.info(f"[Orchestrator] Wake word: {wake_word} ({confidence:.2f})")
        self._set_state(SystemState.LISTENING)
        
        # Notify callbacks
        for callback in self._on_wake:
            try:
                callback(wake_word, confidence)
            except Exception as e:
                logger.error(f"[Orchestrator] Wake callback error: {e}")
        
        # Update overlay
        if self._overlay_hook and self._overlay_hook.is_connected():
            self._overlay_hook.wake_sync(self.config.wake_confirmation)
        
        # Speak confirmation
        if self._tts and self.config.wake_confirmation:
            try:
                self._tts.speak(self.config.wake_confirmation)
            except Exception as e:
                logger.error(f"[Orchestrator] TTS error: {e}")
    
    def _on_utterance_received(self, audio: bytes) -> None:
        """Handle received utterance."""
        self._set_state(SystemState.PROCESSING)
        
        # Update overlay
        if self._overlay_hook and self._overlay_hook.is_connected():
            self._overlay_hook.thinking_sync(self.config.thinking_phrase)
        
        # Transcribe
        if not self._asr:
            logger.error("[Orchestrator] ASR not available")
            return
        
        try:
            import numpy as np
            
            # ContinuousListener sends audio as int16 bytes
            # Convert int16 bytes to float32 for ASR
            audio_int16 = np.frombuffer(audio, dtype=np.int16)
            audio_np = audio_int16.astype(np.float32) / 32768.0
            
            logger.debug(f"[Orchestrator] Audio: {len(audio)} bytes, {len(audio_np)} samples, max={np.max(np.abs(audio_np)):.4f}")
            
            # ASR returns (text, meta) tuple
            text, meta = self._asr.transcribe(audio_np)
            text = text.strip()
            
            if text:
                self._process_command(text)
            else:
                logger.debug("[Orchestrator] Empty transcription")
                self._set_state(SystemState.READY)
                
        except Exception as e:
            logger.error(f"[Orchestrator] Transcription error: {e}")
            self._speak_error(self.config.error_phrase)
            self._set_state(SystemState.READY)
    
    def _on_listener_state_change(self, state) -> None:
        """Handle listener state change."""
        from bantz.voice.continuous import ListenerState
        
        if state == ListenerState.IDLE:
            self._set_state(SystemState.READY)
        elif state == ListenerState.LISTENING:
            self._set_state(SystemState.LISTENING)
        elif state == ListenerState.PROCESSING:
            self._set_state(SystemState.PROCESSING)
    
    # ─────────────────────────────────────────────────────────────
    # Command Processing
    # ─────────────────────────────────────────────────────────────
    
    def _process_command(self, text: str) -> None:
        """Process a voice command."""
        logger.info(f"[Orchestrator] Command: {text}")
        
        # Notify callbacks
        for callback in self._on_command:
            try:
                callback(text)
            except Exception as e:
                logger.error(f"[Orchestrator] Command callback error: {e}")
        
        # Process through server
        if not self._server:
            logger.error("[Orchestrator] Server not available")
            return
        
        try:
            result = self._server.handle_command(text)
            
            response_text = result.get("text", "")
            ok = result.get("ok", False)
            
            # Update overlay
            self._set_state(SystemState.SPEAKING)
            if self._overlay_hook and self._overlay_hook.is_connected():
                self._overlay_hook.speaking_sync(response_text[:100] if response_text else "Tamam!")
            
            # Speak response
            if self._tts and response_text:
                try:
                    self._tts.speak(response_text)
                except Exception as e:
                    logger.error(f"[Orchestrator] TTS error: {e}")
            
            # Notify callbacks
            for callback in self._on_response:
                try:
                    callback(response_text)
                except Exception as e:
                    logger.error(f"[Orchestrator] Response callback error: {e}")
            
            # Return to ready state
            self._set_state(SystemState.READY)
            
        except Exception as e:
            logger.error(f"[Orchestrator] Command processing error: {e}")
            self._speak_error(self.config.error_phrase)
            self._set_state(SystemState.READY)
    
    def _speak_error(self, message: str) -> None:
        """Speak an error message."""
        if self._overlay_hook and self._overlay_hook.is_connected():
            self._overlay_hook.speaking_sync(message)
        
        if self._tts:
            try:
                self._tts.speak(message)
            except Exception:
                pass
    
    # ─────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────
    
    def _play_startup_sound(self) -> None:
        """Play startup sound if enabled."""
        if not self.config.startup_sound:
            return
        
        # Try to play a beep or startup sound
        try:
            # Simple beep using TTS
            if self._tts:
                # Say nothing but make a brief sound
                pass
        except Exception:
            pass
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"[Orchestrator] Signal {signum} received")
        self._running = False
        self._shutdown_event.set()
    
    # ─────────────────────────────────────────────────────────────
    # Shutdown
    # ─────────────────────────────────────────────────────────────
    
    def _shutdown(self) -> None:
        """Shutdown all components."""
        print("\n🛑 Sistem kapatılıyor...")
        self._set_state(SystemState.OFFLINE)
        self._running = False
        
        # Stop continuous listener
        if self._continuous_listener:
            try:
                if self._loop:
                    asyncio.run_coroutine_threadsafe(
                        self._continuous_listener.stop(),
                        self._loop,
                    ).result(timeout=2.0)
            except Exception:
                pass
        
        # Stop overlay
        if self._overlay_hook:
            try:
                self._overlay_hook.stop()
            except Exception:
                pass
        
        # Stop browser bridge
        try:
            from bantz.browser.extension_bridge import get_bridge
            bridge = get_bridge()
            if bridge:
                bridge.stop()
        except Exception:
            pass
        
        # Stop async loop
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        print("   Güle güle! 👋")
        logger.info("[Orchestrator] Shutdown complete")
    
    def stop(self) -> None:
        """Request graceful shutdown."""
        self._running = False
        self._shutdown_event.set()
    
    # ─────────────────────────────────────────────────────────────
    # Context Manager
    # ─────────────────────────────────────────────────────────────
    
    async def __aenter__(self) -> BantzOrchestrator:
        await self.start_async()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._shutdown()


# ─────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────

_orchestrator: Optional[BantzOrchestrator] = None


def get_orchestrator() -> Optional[BantzOrchestrator]:
    """Get the global orchestrator instance."""
    return _orchestrator


def start_jarvis(config: Optional[OrchestratorConfig] = None) -> int:
    """Start Jarvis system.
    
    Args:
        config: Configuration (uses env vars if not provided)
    
    Returns:
        Exit code
    """
    global _orchestrator
    _orchestrator = BantzOrchestrator(config)
    return _orchestrator.start()


def stop_jarvis() -> None:
    """Stop the Jarvis system."""
    global _orchestrator
    if _orchestrator:
        _orchestrator.stop()
        _orchestrator = None


# ─────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────

def main() -> int:
    """Main entry point for Jarvis."""
    import argparse
    
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="Jarvis - Just A Rather Very Intelligent System",
    )
    
    parser.add_argument(
        "--session",
        default="default",
        help="Session name",
    )
    parser.add_argument(
        "--policy",
        default="config/policy.json",
        help="Policy file path",
    )
    parser.add_argument(
        "--piper-model",
        default="",
        help="Path to Piper TTS model",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        help="Whisper model size (tiny, base, small, medium, large)",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Disable text-to-speech",
    )
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Disable overlay UI",
    )
    parser.add_argument(
        "--no-wake-word",
        action="store_true",
        help="Disable wake word detection",
    )
    
    args = parser.parse_args()
    
    config = OrchestratorConfig(
        session_name=args.session,
        policy_path=args.policy,
        piper_model=args.piper_model,
        whisper_model=args.whisper_model,
        enable_tts=not args.no_tts,
        enable_overlay=not args.no_overlay,
        enable_wake_word=not args.no_wake_word,
    )
    
    return start_jarvis(config)


if __name__ == "__main__":
    sys.exit(main())
