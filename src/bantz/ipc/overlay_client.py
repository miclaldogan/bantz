"""
Bantz IPC Overlay Client - Daemon Side
v0.6.2.1

Handles:
- Connection to overlay process
- Sending state updates
- Receiving events (timeout, dismissed)
- Ping/pong heartbeat
- Auto-reconnect with backoff
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .protocol import (
    StateMessage,
    PingMessage,
    PongMessage,
    AckMessage,
    EventMessage,
    encode_message,
    decode_message,
    parse_message,
    get_socket_path,
    ensure_socket_dir,
    cleanup_socket,
    state_idle,
    OverlayState,
    OverlayPosition,
    MessageType,
)

logger = logging.getLogger(__name__)


class OverlayClient:
    """
    IPC client for communicating with the overlay process.
    Runs in the daemon process.
    """
    
    # Reconnect backoff intervals (seconds)
    BACKOFF_INTERVALS = [1, 2, 5, 10, 30]
    
    # Ping interval (seconds)
    PING_INTERVAL = 3.0
    
    # Connection timeout (seconds)
    CONNECT_TIMEOUT = 5.0
    
    # Max pending acks before warning
    MAX_PENDING_ACKS = 10
    
    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._running = False
        self._overlay_process: Optional[subprocess.Popen] = None
        
        # Current state tracking
        self._current_state = OverlayState.IDLE.value
        self._current_position = OverlayPosition.CENTER.value
        
        # Pending acks (for debugging/monitoring)
        self._pending_acks: dict[str, float] = {}
        
        # Event callback
        self._on_event: Optional[Callable[[EventMessage], Awaitable[None]]] = None
        
        # Tasks
        self._ping_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        
        # Reconnect state
        self._reconnect_attempt = 0
        self._auto_respawn = True
    
    @property
    def connected(self) -> bool:
        """Check if connected to overlay."""
        return self._connected and self._writer is not None
    
    @property
    def current_state(self) -> str:
        """Get current overlay state."""
        return self._current_state
    
    @property
    def current_position(self) -> str:
        """Get current overlay position."""
        return self._current_position
    
    def set_event_callback(self, callback: Callable[[EventMessage], Awaitable[None]]) -> None:
        """Set callback for overlay events (timeout, dismissed)."""
        self._on_event = callback
    
    async def start(self, auto_spawn: bool = True) -> bool:
        """
        Start the overlay client.
        
        Args:
            auto_spawn: Whether to automatically spawn overlay process
            
        Returns:
            True if started successfully
        """
        if self._running:
            return True
        
        self._running = True
        logger.info("[OverlayClient] Starting...")
        
        # Ensure socket directory exists
        ensure_socket_dir()
        
        # Spawn overlay process if requested
        if auto_spawn:
            await self._spawn_overlay()
        
        # Try to connect
        connected = await self._connect()
        
        if connected:
            # Start ping loop and receiver
            self._ping_task = asyncio.create_task(self._ping_loop())
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            # Send initial idle state
            await self.send_state(state_idle(self._current_position))
        
        return connected
    
    async def stop(self) -> None:
        """Stop the overlay client and terminate overlay process."""
        logger.info("[OverlayClient] Stopping...")
        self._running = False
        self._auto_respawn = False
        
        # Cancel tasks
        for task in [self._ping_task, self._receive_task, self._reconnect_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Send idle state before disconnecting
        if self._connected:
            try:
                await self.send_state(state_idle())
            except Exception:
                pass
        
        # Disconnect
        await self._disconnect()
        
        # Terminate overlay process
        await self._terminate_overlay()
        
        logger.info("[OverlayClient] Stopped")
    
    async def send_state(self, msg: StateMessage) -> bool:
        """
        Send state update to overlay.
        
        Args:
            msg: State message to send
            
        Returns:
            True if sent successfully
        """
        if not self._connected or not self._writer:
            logger.warning("[OverlayClient] Not connected, cannot send state")
            return False
        
        try:
            data = encode_message(msg)
            self._writer.write(data)
            await self._writer.drain()
            
            # Track pending ack
            self._pending_acks[msg.id] = asyncio.get_event_loop().time()
            
            # Update local state
            self._current_state = msg.state
            if msg.position:
                self._current_position = msg.position
            
            logger.debug(f"[OverlayClient] Sent state: {msg.state}, text: {msg.text[:30] if msg.text else 'None'}...")
            return True
            
        except Exception as e:
            logger.error(f"[OverlayClient] Send error: {e}")
            await self._handle_disconnect()
            return False
    
    async def set_state(
        self,
        state: str,
        text: Optional[str] = None,
        position: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        sticky: bool = False,
    ) -> bool:
        """
        Convenience method to send state update.
        
        Args:
            state: One of idle, wake, listening, thinking, speaking
            text: Text to display
            position: Screen position
            timeout_ms: Auto-hide timeout
            sticky: If True, ignore timeout
            
        Returns:
            True if sent successfully
        """
        msg = StateMessage(
            state=state,
            text=text,
            position=position or self._current_position,
            timeout_ms=timeout_ms,
            sticky=sticky,
        )
        return await self.send_state(msg)
    
    async def set_position(self, position: str) -> bool:
        """
        Update overlay position while keeping current state.
        
        Args:
            position: One of center, top_right, top_left, bottom_right, bottom_left
            
        Returns:
            True if sent successfully
        """
        msg = StateMessage(
            state=self._current_state,
            position=position,
        )
        return await self.send_state(msg)
    
    async def hide(self) -> bool:
        """Hide overlay (set to idle state)."""
        return await self.set_state(OverlayState.IDLE.value)
    
    # --- Internal methods ---
    
    async def _spawn_overlay(self) -> bool:
        """Spawn the overlay process."""
        if self._overlay_process and self._overlay_process.poll() is None:
            logger.debug("[OverlayClient] Overlay process already running")
            return True
        
        try:
            # Prepare environment - inherit current env and ensure DISPLAY is set
            import os
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":0")
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            
            # Run overlay as a Python module (more reliable than script path)
            # This works regardless of how bantz was installed
            self._overlay_process = subprocess.Popen(
                [sys.executable, "-m", "bantz.ui.overlay_process"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=True,  # Detach from parent
            )
            
            logger.info(f"[OverlayClient] Spawned overlay process (PID: {self._overlay_process.pid})")
            
            # Give it time to start
            await asyncio.sleep(0.5)
            
            return True
            
        except Exception as e:
            logger.error(f"[OverlayClient] Failed to spawn overlay: {e}")
            return False
    
    async def _terminate_overlay(self) -> None:
        """Terminate the overlay process."""
        if not self._overlay_process:
            return
        
        try:
            # Try graceful termination first
            self._overlay_process.terminate()
            
            # Wait up to 2 seconds
            for _ in range(20):
                if self._overlay_process.poll() is not None:
                    break
                await asyncio.sleep(0.1)
            
            # Force kill if still running
            if self._overlay_process.poll() is None:
                logger.warning("[OverlayClient] Overlay not responding, sending SIGKILL")
                self._overlay_process.kill()
                await asyncio.sleep(0.1)
            
            logger.info("[OverlayClient] Overlay process terminated")
            
        except Exception as e:
            logger.error(f"[OverlayClient] Error terminating overlay: {e}")
        
        finally:
            self._overlay_process = None
    
    async def _connect(self) -> bool:
        """Connect to overlay socket."""
        socket_path = get_socket_path()
        
        for attempt in range(5):
            try:
                logger.debug(f"[OverlayClient] Connecting to {socket_path} (attempt {attempt + 1})")
                
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(str(socket_path)),
                    timeout=self.CONNECT_TIMEOUT,
                )
                
                self._connected = True
                self._reconnect_attempt = 0
                logger.info(f"[OverlayClient] Connected to overlay")
                return True
                
            except FileNotFoundError:
                logger.debug(f"[OverlayClient] Socket not found, waiting...")
                await asyncio.sleep(0.5)
                
            except asyncio.TimeoutError:
                logger.warning(f"[OverlayClient] Connection timeout")
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"[OverlayClient] Connection error: {e}")
                await asyncio.sleep(0.5)
        
        logger.error("[OverlayClient] Failed to connect after retries")
        return False
    
    async def _disconnect(self) -> None:
        """Disconnect from overlay socket."""
        self._connected = False
        
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        
        self._reader = None
        self._writer = None
    
    async def _handle_disconnect(self) -> None:
        """Handle unexpected disconnection."""
        logger.warning("[OverlayClient] Disconnected from overlay")
        await self._disconnect()
        
        # Start reconnect if running
        if self._running and self._auto_respawn:
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())
    
    async def _reconnect_loop(self) -> None:
        """Reconnect with exponential backoff."""
        while self._running and not self._connected:
            # Get backoff interval
            idx = min(self._reconnect_attempt, len(self.BACKOFF_INTERVALS) - 1)
            backoff = self.BACKOFF_INTERVALS[idx]
            
            logger.info(f"[OverlayClient] Reconnecting in {backoff}s (attempt {self._reconnect_attempt + 1})")
            await asyncio.sleep(backoff)
            
            if not self._running:
                break
            
            # Check if overlay process is alive
            if self._overlay_process and self._overlay_process.poll() is not None:
                logger.warning("[OverlayClient] Overlay process died, respawning...")
                await self._spawn_overlay()
            
            # Try to connect
            if await self._connect():
                # Restart ping and receive loops
                if self._ping_task:
                    self._ping_task.cancel()
                if self._receive_task:
                    self._receive_task.cancel()
                
                self._ping_task = asyncio.create_task(self._ping_loop())
                self._receive_task = asyncio.create_task(self._receive_loop())
                
                # Resend current state
                await self.set_state(self._current_state, position=self._current_position)
                break
            
            self._reconnect_attempt += 1
    
    async def _ping_loop(self) -> None:
        """Send periodic ping messages."""
        while self._running and self._connected:
            try:
                await asyncio.sleep(self.PING_INTERVAL)
                
                if not self._connected or not self._writer:
                    break
                
                ping = PingMessage()
                data = encode_message(ping)
                self._writer.write(data)
                await self._writer.drain()
                
                logger.debug(f"[OverlayClient] Sent ping")
                
                # Check for stale acks
                now = asyncio.get_event_loop().time()
                stale = [k for k, v in self._pending_acks.items() if now - v > 10]
                if len(stale) > self.MAX_PENDING_ACKS:
                    logger.warning(f"[OverlayClient] Too many pending acks ({len(stale)}), overlay may be unresponsive")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OverlayClient] Ping error: {e}")
                await self._handle_disconnect()
                break
    
    async def _receive_loop(self) -> None:
        """Receive and process messages from overlay."""
        while self._running and self._connected:
            try:
                if not self._reader:
                    break
                
                # Read until newline (JSONL)
                line = await self._reader.readline()
                
                if not line:
                    logger.warning("[OverlayClient] Connection closed by overlay")
                    await self._handle_disconnect()
                    break
                
                # Parse message
                data = decode_message(line)
                if not data:
                    continue
                
                msg = parse_message(data)
                if not msg:
                    continue
                
                # Handle message by type
                await self._handle_message(msg)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OverlayClient] Receive error: {e}")
                await self._handle_disconnect()
                break
    
    async def _handle_message(self, msg) -> None:
        """Handle received message."""
        if isinstance(msg, AckMessage):
            # Remove from pending
            if msg.id in self._pending_acks:
                del self._pending_acks[msg.id]
            logger.debug(f"[OverlayClient] Received ack for {msg.id}")
            
        elif isinstance(msg, PongMessage):
            logger.debug(f"[OverlayClient] Received pong")
            
        elif isinstance(msg, EventMessage):
            logger.info(f"[OverlayClient] Received event: {msg.event} ({msg.reason})")
            
            # Call event callback if set
            if self._on_event:
                try:
                    await self._on_event(msg)
                except Exception as e:
                    logger.error(f"[OverlayClient] Event callback error: {e}")
        
        else:
            logger.debug(f"[OverlayClient] Received unknown message type: {type(msg)}")


# Global client instance for convenience
_client: Optional[OverlayClient] = None


def get_overlay_client() -> OverlayClient:
    """Get or create global overlay client instance."""
    global _client
    if _client is None:
        _client = OverlayClient()
    return _client


async def init_overlay_client(auto_spawn: bool = True) -> OverlayClient:
    """Initialize and start the global overlay client."""
    client = get_overlay_client()
    await client.start(auto_spawn=auto_spawn)
    return client


async def shutdown_overlay_client() -> None:
    """Shutdown the global overlay client."""
    global _client
    if _client:
        await _client.stop()
        _client = None
