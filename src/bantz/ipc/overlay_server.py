"""
Bantz IPC Overlay Server - Overlay Side
v0.6.2.1

Handles:
- Unix socket server
- Receiving state updates from daemon
- Sending acks and events
- Responding to ping/pong
"""

import asyncio
import logging
import os
from typing import Optional, Callable, Awaitable

from .protocol import (
    StateMessage,
    ActionMessage,
    EventMessage,
    AckMessage,
    PingMessage,
    PongMessage,
    encode_message,
    decode_message,
    parse_message,
    get_socket_path,
    ensure_socket_dir,
    cleanup_socket,
    event_timeout,
    event_dismissed,
    MessageType,
    EventReason,
)

logger = logging.getLogger(__name__)


class OverlayServer:
    """
    IPC server running in the overlay process.
    Receives state updates from daemon and sends events back.
    """
    
    def __init__(self):
        self._server: Optional[asyncio.AbstractServer] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._running = False
        
        # Callbacks
        self._on_state: Optional[Callable[[StateMessage], Awaitable[None]]] = None
        self._on_action: Optional[Callable[[ActionMessage], Awaitable[None]]] = None
        self._on_disconnect: Optional[Callable[[], Awaitable[None]]] = None
        
        # Receive task
        self._receive_task: Optional[asyncio.Task] = None
    
    @property
    def connected(self) -> bool:
        """Check if daemon is connected."""
        return self._connected
    
    def set_state_callback(self, callback: Callable[[StateMessage], Awaitable[None]]) -> None:
        """
        Set callback for state updates.
        
        The callback receives StateMessage and should update the overlay UI.
        """
        self._on_state = callback

    def set_action_callback(self, callback: Callable[[ActionMessage], Awaitable[None]]) -> None:
        """Set callback for action messages (daemon → overlay)."""
        self._on_action = callback
    
    def set_disconnect_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """
        Set callback for disconnection.
        
        Called when daemon disconnects unexpectedly.
        """
        self._on_disconnect = callback
    
    async def start(self) -> bool:
        """
        Start the IPC server.
        
        Creates Unix socket and waits for daemon connection.
        
        Returns:
            True if server started successfully
        """
        if self._running:
            return True
        
        try:
            # Ensure socket directory exists
            socket_path = ensure_socket_dir()
            
            # Remove stale socket
            cleanup_socket()
            
            # Create Unix socket server
            self._server = await asyncio.start_unix_server(
                self._handle_connection,
                str(socket_path),
            )
            
            # Set socket permissions (read/write for user only)
            os.chmod(str(socket_path), 0o600)
            
            self._running = True
            logger.info(f"[OverlayServer] Listening on {socket_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"[OverlayServer] Failed to start: {e}")
            return False
    
    async def stop(self) -> None:
        """Stop the IPC server."""
        logger.info("[OverlayServer] Stopping...")
        self._running = False
        
        # Cancel receive task
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        # Close client connection
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        
        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        # Cleanup socket
        cleanup_socket()
        
        logger.info("[OverlayServer] Stopped")
    
    async def send_event(self, event: EventMessage) -> bool:
        """
        Send event to daemon.
        
        Args:
            event: Event message (timeout or dismissed)
            
        Returns:
            True if sent successfully
        """
        if not self._connected or not self._writer:
            logger.warning("[OverlayServer] Not connected, cannot send event")
            return False
        
        try:
            data = encode_message(event)
            self._writer.write(data)
            await self._writer.drain()
            
            logger.debug(f"[OverlayServer] Sent event: {event.event}")
            return True
            
        except Exception as e:
            logger.error(f"[OverlayServer] Send error: {e}")
            return False
    
    async def send_timeout(self, reason: str = EventReason.NO_SPEECH.value) -> bool:
        """Send timeout event to daemon."""
        return await self.send_event(event_timeout(reason))
    
    async def send_dismissed(self, reason: str = EventReason.USER_CLOSE.value) -> bool:
        """Send dismissed event to daemon."""
        return await self.send_event(event_dismissed(reason))
    
    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle new daemon connection."""
        # Only allow one connection at a time
        if self._connected:
            logger.warning("[OverlayServer] Already connected, rejecting new connection")
            writer.close()
            await writer.wait_closed()
            return
        
        self._reader = reader
        self._writer = writer
        self._connected = True
        
        peer = writer.get_extra_info('peername')
        logger.info(f"[OverlayServer] Daemon connected: {peer}")
        
        # Start receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())
        
        try:
            await self._receive_task
        except asyncio.CancelledError:
            pass
        
        # Connection closed
        self._connected = False
        self._reader = None
        self._writer = None
        
        logger.info("[OverlayServer] Daemon disconnected")
        
        # Call disconnect callback
        if self._on_disconnect:
            try:
                await self._on_disconnect()
            except Exception as e:
                logger.error(f"[OverlayServer] Disconnect callback error: {e}")
    
    async def _receive_loop(self) -> None:
        """Receive and process messages from daemon."""
        while self._running and self._connected:
            try:
                if not self._reader:
                    break
                
                # Read until newline (JSONL)
                line = await self._reader.readline()
                
                if not line:
                    logger.warning("[OverlayServer] Connection closed by daemon")
                    break
                
                # Parse message
                data = decode_message(line)
                if not data:
                    continue
                
                msg = parse_message(data)
                if not msg:
                    continue
                
                # Handle message
                await self._handle_message(msg)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OverlayServer] Receive error: {e}")
                break
    
    async def _handle_message(self, msg) -> None:
        """Handle received message."""
        if isinstance(msg, StateMessage):
            logger.debug(f"[OverlayServer] Received state: {msg.state}, text: {msg.text[:30] if msg.text else 'None'}...")
            
            # Send ack
            ack = AckMessage(id=msg.id)
            await self._send_ack(ack)
            
            # Call state callback
            if self._on_state:
                try:
                    await self._on_state(msg)
                except Exception as e:
                    logger.error(f"[OverlayServer] State callback error: {e}")

        elif isinstance(msg, ActionMessage):
            logger.debug(f"[OverlayServer] Received action: {msg.action}, text: {msg.text[:30] if msg.text else 'None'}...")

            # Send ack
            ack = AckMessage(id=msg.id)
            await self._send_ack(ack)

            if self._on_action:
                try:
                    await self._on_action(msg)
                except Exception as e:
                    logger.error(f"[OverlayServer] Action callback error: {e}")
        
        elif isinstance(msg, PingMessage):
            logger.debug("[OverlayServer] Received ping")
            
            # Send pong
            pong = PongMessage(id=msg.id)
            await self._send_pong(pong)
        
        else:
            logger.debug(f"[OverlayServer] Received unknown message type: {type(msg)}")
    
    async def _send_ack(self, ack: AckMessage) -> bool:
        """Send ack message."""
        if not self._connected or not self._writer:
            return False
        
        try:
            data = encode_message(ack)
            self._writer.write(data)
            await self._writer.drain()
            logger.debug(f"[OverlayServer] Sent ack for {ack.id}")
            return True
        except Exception as e:
            logger.error(f"[OverlayServer] Ack send error: {e}")
            return False
    
    async def _send_pong(self, pong: PongMessage) -> bool:
        """Send pong message."""
        if not self._connected or not self._writer:
            return False
        
        try:
            data = encode_message(pong)
            self._writer.write(data)
            await self._writer.drain()
            logger.debug("[OverlayServer] Sent pong")
            return True
        except Exception as e:
            logger.error(f"[OverlayServer] Pong send error: {e}")
            return False


# Global server instance
_server: Optional[OverlayServer] = None


def get_overlay_server() -> OverlayServer:
    """Get or create global overlay server instance."""
    global _server
    if _server is None:
        _server = OverlayServer()
    return _server


async def init_overlay_server() -> OverlayServer:
    """Initialize and start the global overlay server."""
    server = get_overlay_server()
    await server.start()
    return server


async def shutdown_overlay_server() -> None:
    """Shutdown the global overlay server."""
    global _server
    if _server:
        await _server.stop()
        _server = None
