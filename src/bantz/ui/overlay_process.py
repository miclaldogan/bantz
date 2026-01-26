#!/usr/bin/env python3
"""
Bantz Overlay Process - Standalone IPC-driven overlay
v0.6.2.1

This runs as a separate process and communicates with the daemon via Unix socket.

Usage:
    python -m bantz.ui.overlay_process
    
Or directly:
    python overlay_process.py
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, QObject, pyqtSignal

# Import overlay components (relative import for module usage)
from bantz.ui.overlay import (
    BantzOverlay,
    OverlayConfig,
    AssistantState,
    GridPosition,
    POSITION_ALIASES,
)

# Import IPC
from bantz.ipc.overlay_server import OverlayServer, get_overlay_server
from bantz.ipc.protocol import (
    StateMessage,
    OverlayState,
    OverlayPosition,
    EventReason,
)

logger = logging.getLogger(__name__)

# Map IPC states to overlay states
STATE_MAP = {
    OverlayState.IDLE.value: AssistantState.IDLE,
    OverlayState.WAKE.value: AssistantState.WAKE,
    OverlayState.LISTENING.value: AssistantState.LISTENING,
    OverlayState.THINKING.value: AssistantState.THINKING,
    OverlayState.SPEAKING.value: AssistantState.SPEAKING,
}

# Map IPC positions to grid positions
POSITION_MAP = {
    OverlayPosition.CENTER.value: GridPosition.CENTER,
    OverlayPosition.TOP_RIGHT.value: GridPosition.TOP_RIGHT,
    OverlayPosition.TOP_LEFT.value: GridPosition.TOP_LEFT,
    OverlayPosition.BOTTOM_RIGHT.value: GridPosition.BOTTOM_RIGHT,
    OverlayPosition.BOTTOM_LEFT.value: GridPosition.BOTTOM_LEFT,
}


class OverlayBridge(QObject):
    """
    Bridge between async IPC server and Qt overlay.
    
    Handles thread-safe communication using Qt signals.
    """
    
    # Signals for thread-safe Qt updates
    state_changed = pyqtSignal(str, str, str, int, bool)  # state, text, position, timeout_ms, sticky
    hide_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    
    def __init__(self, overlay: BantzOverlay, server: OverlayServer):
        super().__init__()
        self.overlay = overlay
        self.server = server
        
        # Current state tracking
        self._current_state = OverlayState.IDLE.value
        self._timeout_ms: Optional[int] = None
        self._sticky = False
        
        # Timeout timer (Qt-based)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        
        # Connect signals to slots
        self.state_changed.connect(self._on_state_changed)
        self.hide_requested.connect(self._on_hide_requested)
        self.quit_requested.connect(self._on_quit_requested)
        
        # Set server callback
        server.set_state_callback(self._handle_state)
        server.set_disconnect_callback(self._handle_disconnect)
        
        # Set overlay timeout callback
        overlay.set_timeout_callback(self._on_overlay_timeout)
    
    async def _handle_state(self, msg: StateMessage) -> None:
        """
        Handle state message from daemon (async).
        
        This runs in the asyncio thread, emits Qt signal for thread-safe update.
        """
        logger.debug(f"[OverlayBridge] State update: {msg.state}, text: {msg.text}")
        
        # Emit signal to Qt thread
        self.state_changed.emit(
            msg.state,
            msg.text or "",
            msg.position or OverlayPosition.CENTER.value,
            msg.timeout_ms or 0,
            msg.sticky,
        )
    
    async def _handle_disconnect(self) -> None:
        """Handle daemon disconnection."""
        logger.warning("[OverlayBridge] Daemon disconnected")
        # Hide overlay on disconnect
        self.hide_requested.emit()
    
    def _on_state_changed(
        self,
        state: str,
        text: str,
        position: str,
        timeout_ms: int,
        sticky: bool,
    ):
        """
        Slot: Update overlay state (runs in Qt thread).
        """
        logger.debug(f"[OverlayBridge] Qt slot: state={state}, text={text[:30] if text else 'None'}...")
        
        self._current_state = state
        self._timeout_ms = timeout_ms if timeout_ms > 0 else None
        self._sticky = sticky
        
        # Map state
        overlay_state = STATE_MAP.get(state, AssistantState.IDLE)
        
        # Handle idle - hide overlay
        if overlay_state == AssistantState.IDLE:
            self.overlay.hide_overlay()
            self._timeout_timer.stop()
            return
        
        # Map position
        grid_position = POSITION_MAP.get(position, GridPosition.CENTER)
        
        # Update overlay
        self.overlay.set_position(grid_position)
        self.overlay.set_state(overlay_state, text)
        self.overlay.show_overlay()
        
        # Handle timeout
        self._timeout_timer.stop()
        if timeout_ms and timeout_ms > 0 and not sticky:
            self._timeout_timer.start(timeout_ms)
    
    def _on_hide_requested(self):
        """Slot: Hide overlay."""
        self.overlay.hide_overlay()
        self._timeout_timer.stop()
    
    def _on_quit_requested(self):
        """Slot: Quit application."""
        QApplication.instance().quit()
    
    def _on_timeout(self):
        """Internal timeout triggered."""
        logger.info("[OverlayBridge] Timeout triggered")
        
        # Send timeout event to daemon (async)
        asyncio.run_coroutine_threadsafe(
            self.server.send_timeout(EventReason.NO_SPEECH.value),
            asyncio.get_event_loop(),
        )
        
        # Hide overlay
        self.overlay.hide_overlay()
    
    def _on_overlay_timeout(self):
        """Overlay's internal timeout callback."""
        # This is the overlay's built-in timeout (from overlay.py)
        # We convert it to IPC event
        logger.info("[OverlayBridge] Overlay timeout callback")
        
        asyncio.run_coroutine_threadsafe(
            self.server.send_timeout(EventReason.NO_SPEECH.value),
            asyncio.get_event_loop(),
        )


class OverlayProcess:
    """
    Main overlay process class.
    
    Integrates Qt event loop with asyncio for IPC.
    """
    
    def __init__(self):
        self._app: Optional[QApplication] = None
        self._overlay: Optional[BantzOverlay] = None
        self._server: Optional[OverlayServer] = None
        self._bridge: Optional[OverlayBridge] = None
        self._running = False
        
        # Asyncio event loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_task: Optional[asyncio.Task] = None
    
    def run(self) -> int:
        """
        Run the overlay process.
        
        Returns:
            Exit code (0 = success)
        """
        try:
            # Setup logging
            logging.basicConfig(
                level=logging.DEBUG,
                format="[%(asctime)s] [%(levelname)s] [overlay] %(message)s",
                datefmt="%H:%M:%S",
            )
            
            logger.info("[OverlayProcess] Starting...")
            
            # Create Qt application
            self._app = QApplication.instance()
            if self._app is None:
                self._app = QApplication(sys.argv)
            
            # Create overlay window
            self._overlay = BantzOverlay(OverlayConfig())
            
            # Create IPC server
            self._server = get_overlay_server()
            
            # Create bridge
            self._bridge = OverlayBridge(self._overlay, self._server)
            
            # Setup asyncio integration
            self._setup_asyncio()
            
            # Setup signal handlers
            self._setup_signals()
            
            self._running = True
            logger.info("[OverlayProcess] Running...")
            
            # Run Qt event loop
            return self._app.exec_()
            
        except Exception as e:
            logger.error(f"[OverlayProcess] Fatal error: {e}", exc_info=True)
            return 1
        
        finally:
            self._cleanup()
    
    def _setup_asyncio(self):
        """Setup asyncio event loop integration with Qt."""
        # Create new event loop
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        # Start IPC server
        async def start_server():
            await self._server.start()
            
            # Keep server running
            while self._running:
                await asyncio.sleep(0.1)
        
        # Run asyncio in background thread
        import threading
        
        def run_asyncio():
            try:
                self._loop.run_until_complete(start_server())
            except Exception as e:
                logger.error(f"[OverlayProcess] Asyncio error: {e}")
        
        self._async_thread = threading.Thread(target=run_asyncio, daemon=True)
        self._async_thread.start()
        
        logger.info("[OverlayProcess] Asyncio started")
    
    def _setup_signals(self):
        """Setup Unix signal handlers."""
        # Handle SIGTERM/SIGINT gracefully
        def signal_handler(signum, frame):
            logger.info(f"[OverlayProcess] Received signal {signum}")
            self._running = False
            if self._app:
                self._app.quit()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    def _cleanup(self):
        """Cleanup resources."""
        logger.info("[OverlayProcess] Cleaning up...")
        self._running = False
        
        # Stop asyncio loop
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        # Stop server (sync version)
        if self._server:
            try:
                # Create new loop for cleanup
                cleanup_loop = asyncio.new_event_loop()
                cleanup_loop.run_until_complete(self._server.stop())
                cleanup_loop.close()
            except Exception as e:
                logger.error(f"[OverlayProcess] Cleanup error: {e}")
        
        logger.info("[OverlayProcess] Stopped")


def main():
    """Entry point for overlay process."""
    process = OverlayProcess()
    sys.exit(process.run())


if __name__ == "__main__":
    main()
