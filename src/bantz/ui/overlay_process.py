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

# Import Jarvis overlay (Issue #5) as the primary UI.
# Keep cursor/highlight visuals from overlay.py.
from bantz.ui.jarvis_overlay import (
    JarvisOverlay,
    JarvisState,
    GridPosition,
    POSITION_ALIASES,
)
from bantz.ui.overlay import (
    CursorDotOverlay,
    HighlightOverlay,
)

# Import IPC
from bantz.ipc.overlay_server import OverlayServer, get_overlay_server
from bantz.ipc.protocol import (
    StateMessage,
    ActionMessage,
    ActionType,
    OverlayState,
    OverlayPosition,
    EventReason,
)

logger = logging.getLogger(__name__)

# Map IPC states to Jarvis overlay states
STATE_MAP = {
    OverlayState.IDLE.value: JarvisState.HIDDEN,
    OverlayState.WAKE.value: JarvisState.WAKE,
    OverlayState.LISTENING.value: JarvisState.LISTENING,
    OverlayState.THINKING.value: JarvisState.THINKING,
    OverlayState.SPEAKING.value: JarvisState.SPEAKING,
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
    action_received = pyqtSignal(str, str, int, int, int, int, int, int, int)  # type, text, x, y, rx, ry, rw, rh, duration
    hide_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    
    def __init__(self, overlay: JarvisOverlay, server: OverlayServer):
        super().__init__()
        self.overlay = overlay
        self.server = server

        # Resolve an accent color for cursor/highlight visuals.
        # Legacy overlay used overlay.config.accent_color; JarvisOverlay uses theme.primary.
        accent_color = "#6366f1"
        try:
            theme = getattr(self.overlay, "theme", None)
            if theme is not None:
                accent_color = str(getattr(theme, "primary", accent_color) or accent_color)
        except Exception:
            pass

        # Action visuals
        self._cursor = CursorDotOverlay(color=accent_color)
        self._highlight = HighlightOverlay(color=accent_color)
        
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
        self.action_received.connect(self._on_action_received)
        self.hide_requested.connect(self._on_hide_requested)
        self.quit_requested.connect(self._on_quit_requested)
        
        # Set server callback
        server.set_state_callback(self._handle_state)
        server.set_action_callback(self._handle_action)
        server.set_disconnect_callback(self._handle_disconnect)
        
        # Best-effort: keep overlay's internal timeout wired to IPC.
        # JarvisOverlay uses set_timeout(seconds, callback).
        try:
            overlay.set_timeout(10.0, callback=self._on_overlay_timeout)
        except Exception:
            pass
    
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

    async def _handle_action(self, msg: ActionMessage) -> None:
        """Handle action message from daemon (async) and forward to Qt thread."""
        self.action_received.emit(
            msg.action or ActionType.PREVIEW.value,
            msg.text or "",
            int(msg.x or 0),
            int(msg.y or 0),
            int(msg.rect_x or 0),
            int(msg.rect_y or 0),
            int(msg.rect_w or 0),
            int(msg.rect_h or 0),
            int(msg.duration_ms or 0),
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
        overlay_state = STATE_MAP.get(state, JarvisState.HIDDEN)

        # Handle idle/hidden - hide overlay
        if overlay_state == JarvisState.HIDDEN:
            self.overlay.set_state(JarvisState.HIDDEN.name, "")
            self.overlay.hide_overlay()
            self._timeout_timer.stop()
            return
        
        # Map position
        grid_position = POSITION_MAP.get(position, GridPosition.CENTER)
        
        # Update overlay
        self.overlay.set_position(grid_position.value)
        self.overlay.set_state(overlay_state.name, text)
        self.overlay.show_overlay()
        
        # Handle timeout
        self._timeout_timer.stop()
        if timeout_ms and timeout_ms > 0 and not sticky:
            self._timeout_timer.start(timeout_ms)
    
    def _on_hide_requested(self):
        """Slot: Hide overlay."""
        self.overlay.hide_overlay()
        self._timeout_timer.stop()

        # Hide action visuals
        self._cursor.hide()
        self._highlight.hide()
    
    def _on_quit_requested(self):
        """Slot: Quit application."""
        QApplication.instance().quit()

    def _on_action_received(
        self,
        action_type: str,
        text: str,
        x: int,
        y: int,
        rx: int,
        ry: int,
        rw: int,
        rh: int,
        duration_ms: int,
    ):
        """Slot: Render action visuals (runs in Qt thread)."""
        try:
            if action_type == ActionType.PREVIEW.value:
                if text.strip():
                    self.overlay.set_action(text.strip(), duration_ms or 1200)
            elif action_type == ActionType.CURSOR_DOT.value:
                if x and y:
                    self._cursor.show_at(x, y, duration_ms or 800)
            elif action_type == ActionType.HIGHLIGHT.value:
                if rw and rh:
                    self._highlight.show_rect(rx, ry, rw, rh, duration_ms or 1200)
        except Exception as e:
            logger.error(f"[OverlayBridge] Action render error: {e}")
    
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
        self._overlay: Optional[JarvisOverlay] = None
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
            
            # Create Jarvis overlay window
            self._overlay = JarvisOverlay()
            
            # Create IPC server
            self._server = get_overlay_server()
            
            # Create bridge
            self._bridge = OverlayBridge(self._overlay, self._server)

            # Mark running *before* starting asyncio thread.
            # Otherwise the IPC server loop can exit immediately.
            self._running = True

            # Setup asyncio integration
            self._setup_asyncio()

            # Setup signal handlers
            self._setup_signals()
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
