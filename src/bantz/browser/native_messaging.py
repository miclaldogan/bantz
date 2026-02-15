"""
Bantz Native Messaging Host

This module provides the native messaging interface between
the browser extension and the Bantz daemon.

Native messaging uses stdin/stdout with length-prefixed JSON messages.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from queue import Queue
import logging

logger = logging.getLogger(__name__)


@dataclass
class NativeMessage:
    """A message from/to the browser extension."""
    
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"type": self.type}
        if self.data:
            result["data"] = self.data
        if self.request_id:
            result["requestId"] = self.request_id
        if self.error:
            result["error"] = self.error
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NativeMessage":
        """Create from dictionary."""
        return cls(
            type=data.get("type", "unknown"),
            data=data.get("data", {}),
            request_id=data.get("requestId"),
            error=data.get("error"),
        )
    
    @classmethod
    def error_response(
        cls,
        error: str,
        request_id: Optional[str] = None,
    ) -> "NativeMessage":
        """Create an error response."""
        return cls(
            type="error",
            error=error,
            request_id=request_id,
        )
    
    @classmethod
    def success_response(
        cls,
        data: Dict[str, Any],
        request_id: Optional[str] = None,
    ) -> "NativeMessage":
        """Create a success response."""
        return cls(
            type="response",
            data=data,
            request_id=request_id,
        )


class NativeMessagingIO:
    """Low-level native messaging I/O."""
    
    @staticmethod
    def read_message() -> Optional[Dict[str, Any]]:
        """Read a single message from stdin.
        
        Native messaging uses a 4-byte length prefix (native byte order)
        followed by UTF-8 JSON.
        """
        try:
            # Read 4-byte length prefix
            raw_length = sys.stdin.buffer.read(4)
            if len(raw_length) < 4:
                return None
            
            # Unpack as native unsigned int
            message_length = struct.unpack("@I", raw_length)[0]
            
            # Read message content
            message_bytes = sys.stdin.buffer.read(message_length)
            if len(message_bytes) < message_length:
                return None
            
            # Decode and parse JSON
            message_text = message_bytes.decode("utf-8")
            return json.loads(message_text)
            
        except (json.JSONDecodeError, struct.error) as e:
            logger.error(f"Error reading native message: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error reading native message: {e}")
            return None
    
    @staticmethod
    def write_message(message: Dict[str, Any]) -> bool:
        """Write a message to stdout.
        
        Uses 4-byte length prefix followed by UTF-8 JSON.
        """
        try:
            # Encode message
            message_text = json.dumps(message, ensure_ascii=False)
            message_bytes = message_text.encode("utf-8")
            
            # Write length prefix
            length_bytes = struct.pack("@I", len(message_bytes))
            sys.stdout.buffer.write(length_bytes)
            
            # Write message
            sys.stdout.buffer.write(message_bytes)
            sys.stdout.buffer.flush()
            
            return True
            
        except Exception as e:
            logger.error(f"Error writing native message: {e}")
            return False


class NativeMessagingHost:
    """Native messaging host for browser extension communication.
    
    This class handles:
    - Reading messages from the extension
    - Writing responses back
    - Dispatching messages to handlers
    - Forwarding messages to the Bantz daemon
    
    Usage:
        host = NativeMessagingHost()
        
        @host.handler("scan")
        def handle_scan(message):
            return {"elements": [...]}
        
        host.run()
    """
    
    def __init__(self):
        self.handlers: Dict[str, Callable] = {}
        self.running = False
        self.message_queue: Queue = Queue()
        self.daemon_callback: Optional[Callable] = None
        
    def handler(self, message_type: str):
        """Decorator to register a message handler."""
        def decorator(func: Callable):
            self.handlers[message_type] = func
            return func
        return decorator
    
    def register_handler(
        self,
        message_type: str,
        handler: Callable,
    ) -> None:
        """Register a message handler."""
        self.handlers[message_type] = handler
    
    def set_daemon_callback(self, callback: Callable) -> None:
        """Set callback for forwarding messages to daemon."""
        self.daemon_callback = callback
    
    def handle_message(self, raw_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process an incoming message and return response."""
        message = NativeMessage.from_dict(raw_message)
        
        logger.debug(f"Handling native message: {message.type}")
        
        # Check for handler
        handler = self.handlers.get(message.type)
        
        if handler:
            try:
                result = handler(message)
                
                if isinstance(result, NativeMessage):
                    result.request_id = message.request_id
                    return result.to_dict()
                elif isinstance(result, dict):
                    return NativeMessage.success_response(
                        result,
                        message.request_id,
                    ).to_dict()
                else:
                    return NativeMessage.success_response(
                        {"result": result},
                        message.request_id,
                    ).to_dict()
                    
            except Exception as e:
                logger.error(f"Handler error for {message.type}: {e}")
                return NativeMessage.error_response(
                    str(e),
                    message.request_id,
                ).to_dict()
        
        # Forward to daemon if no handler
        if self.daemon_callback:
            try:
                result = self.daemon_callback(raw_message)
                return result
            except Exception as e:
                logger.error(f"Daemon callback error: {e}")
                return NativeMessage.error_response(
                    str(e),
                    message.request_id,
                ).to_dict()
        
        # No handler found
        return NativeMessage.error_response(
            f"Unknown message type: {message.type}",
            message.request_id,
        ).to_dict()
    
    def send(self, message: NativeMessage) -> bool:
        """Send a message to the extension."""
        return NativeMessagingIO.write_message(message.to_dict())
    
    def send_dict(self, data: Dict[str, Any]) -> bool:
        """Send a raw dictionary message."""
        return NativeMessagingIO.write_message(data)
    
    def send_command(
        self,
        command: str,
        params: Optional[Dict[str, Any]] = None,
        tab_id: Optional[int] = None,
    ) -> bool:
        """Send a command to the extension."""
        message = {
            "type": "command",
            "command": command,
            "params": params or {},
        }
        if tab_id:
            message["tabId"] = tab_id
        return self.send_dict(message)
    
    def run(self) -> None:
        """Run the native messaging host (blocking).
        
        This reads messages from stdin and processes them.
        Call this from the main thread.
        """
        self.running = True
        logger.info("Native messaging host starting")
        
        try:
            while self.running:
                message = NativeMessagingIO.read_message()
                
                if message is None:
                    # End of input or error
                    break
                
                response = self.handle_message(message)
                
                if response:
                    NativeMessagingIO.write_message(response)
                    
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Native messaging host error: {e}")
        finally:
            self.running = False
            logger.info("Native messaging host stopped")
    
    def run_async(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Run in a background thread for async integration."""
        def _run():
            self.run()
        
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return thread


class NativeMessagingClient:
    """Client for communicating with native messaging from Python.
    
    This is used by the Bantz daemon to send messages to the extension.
    """
    
    def __init__(self, host: NativeMessagingHost):
        self.host = host
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.request_counter = 0
    
    def send(
        self,
        message_type: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a message without waiting for response."""
        message = NativeMessage(
            type=message_type,
            data=data or {},
        )
        return self.host.send(message)
    
    async def request(
        self,
        message_type: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """Send a request and wait for response."""
        self.request_counter += 1
        request_id = f"req_{self.request_counter}"
        
        message = NativeMessage(
            type=message_type,
            data=data or {},
            request_id=request_id,
        )
        
        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future
        
        try:
            # Send message
            if not self.host.send(message):
                raise RuntimeError("Failed to send message")
            
            # Wait for response
            return await asyncio.wait_for(future, timeout)
            
        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            raise
    
    def handle_response(self, message: Dict[str, Any]) -> bool:
        """Handle a response message."""
        request_id = message.get("requestId")
        
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests.pop(request_id)
            
            if message.get("error"):
                future.set_exception(RuntimeError(message["error"]))
            else:
                future.set_result(message.get("data", message))
            
            return True
        
        return False


# ============================================================================
# Default Handlers
# ============================================================================

def create_default_host() -> NativeMessagingHost:
    """Create a native messaging host with default handlers."""
    host = NativeMessagingHost()
    
    @host.handler("ping")
    def handle_ping(message: NativeMessage) -> Dict[str, Any]:
        return {"pong": True, "timestamp": __import__("time").time()}
    
    @host.handler("version")
    def handle_version(message: NativeMessage) -> Dict[str, Any]:
        return {
            "version": "2.0.0",
            "name": "bantz_native",
            "python_version": sys.version,
        }
    
    @host.handler("log")
    def handle_log(message: NativeMessage) -> Dict[str, Any]:
        level = message.data.get("level", "info")
        text = message.data.get("text", "")
        logger.log(getattr(logging, level.upper(), logging.INFO), f"[Extension] {text}")
        return {"logged": True}
    
    return host


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point for native messaging host."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Bantz Native Messaging Host")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    # Setup logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("/tmp/bantz-native.log"),
        ],
    )
    
    logger.info("Starting Bantz Native Messaging Host")
    
    # Create and run host
    host = create_default_host()
    
    # Issue #857: Connect to Bantz daemon via Unix socket
    def _daemon_callback(raw_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Forward unhandled extension messages to the Bantz daemon."""
        from bantz.server import send_to_server, is_server_running

        if not is_server_running():
            logger.warning("Bantz daemon is not running — cannot forward message")
            return NativeMessage.error_response(
                "Bantz daemon is not running. Start with 'bantz --serve'.",
                raw_message.get("requestId"),
            ).to_dict()

        # The daemon expects a 'command' string; extract from extension message
        user_text = (
            raw_message.get("text")
            or raw_message.get("data", {}).get("text")
            or raw_message.get("command")
            or ""
        )
        if not user_text:
            return NativeMessage.error_response(
                "Mesaj metni bulunamadı.",
                raw_message.get("requestId"),
            ).to_dict()

        try:
            result = send_to_server(user_text)
            return {
                "type": "response",
                "requestId": raw_message.get("requestId"),
                "success": result.get("ok", False),
                "data": result,
            }
        except Exception as exc:
            logger.error("Daemon iletişim hatası: %s", exc)
            return NativeMessage.error_response(
                f"Daemon hatası: {exc}",
                raw_message.get("requestId"),
            ).to_dict()

    host.set_daemon_callback(_daemon_callback)
    
    host.run()


if __name__ == "__main__":
    main()
