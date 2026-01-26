"""WebSocket Bridge Server for Firefox Extension.

Runs alongside the Unix socket server to handle browser extension communication.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional, Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Try to import websockets, gracefully handle if not installed
try:
    import websockets
    from websockets.server import serve as ws_serve
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets not installed. Extension bridge disabled.")


class ExtensionBridge:
    """WebSocket server for Firefox extension communication."""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 9876,
        command_handler: Optional[Callable[[str], dict]] = None,
    ):
        self.host = host
        self.port = port
        self.command_handler = command_handler
        self._server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._clients: set = set()
        self._running = False
        
    async def _handle_client(self, websocket):
        """Handle a single WebSocket client connection."""
        self._clients.add(websocket)
        client_id = id(websocket)
        logger.info(f"[ExtBridge] Client connected: {client_id}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    response = await self._process_message(data)
                    await websocket.send(json.dumps(response))
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "ok": False,
                        "error": "Invalid JSON"
                    }))
                except Exception as e:
                    logger.error(f"[ExtBridge] Error processing message: {e}")
                    await websocket.send(json.dumps({
                        "ok": False,
                        "error": str(e)
                    }))
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[ExtBridge] Client disconnected: {client_id}")
        finally:
            self._clients.discard(websocket)
    
    async def _process_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming message from extension."""
        msg_type = data.get("type", "")
        
        # Scan result from extension
        if msg_type == "scan_result":
            elements = data.get("elements", [])
            url = data.get("url", "")
            title = data.get("title", "")
            logger.info(f"[ExtBridge] Scan result: {len(elements)} elements from {url}")
            
            # Store in memory for commands
            self._last_scan = {
                "elements": elements,
                "url": url,
                "title": title,
                "timestamp": __import__('time').time(),
            }
            return {"ok": True, "message": f"Received {len(elements)} elements"}
        
        # Page loaded notification
        if msg_type == "page_loaded":
            url = data.get("url", "")
            title = data.get("title", "")
            logger.info(f"[ExtBridge] Page loaded: {title} ({url})")
            self._current_page = {"url": url, "title": title}
            return {"ok": True}
        
        # Tab activated notification
        if msg_type == "tab_activated":
            url = data.get("url", "")
            title = data.get("title", "")
            logger.info(f"[ExtBridge] Tab activated: {title}")
            self._current_page = {"url": url, "title": title}
            return {"ok": True}
        
        # Click result from extension
        if msg_type == "click_result":
            success = data.get("success", False)
            message = data.get("message", "")
            logger.info(f"[ExtBridge] Click result: {success} - {message}")
            self._last_action_result = {"success": success, "message": message}
            return {"ok": True}
        
        # Scroll result
        if msg_type == "scroll_result":
            success = data.get("success", False)
            message = data.get("message", "")
            self._last_action_result = {"success": success, "message": message}
            return {"ok": True}
        
        # Profile activated
        if msg_type == "profile_activated":
            domain = data.get("domain", "")
            logger.info(f"[ExtBridge] Profile activated: {domain}")
            return {"ok": True}
        
        # Tabs query result
        if msg_type == "tabs_result":
            tabs = data.get("tabs", [])
            logger.info(f"[ExtBridge] Received {len(tabs)} tabs")
            self._tabs_result = tabs
            return {"ok": True}
        
        # Tab focus result
        if msg_type == "focus_result":
            success = data.get("success", False)
            logger.info(f"[ExtBridge] Tab focus result: {success}")
            return {"ok": True}
        
        # Command from extension (forward to handler)
        if msg_type == "command" and self.command_handler:
            command = data.get("command", "")
            if command:
                # Run command handler in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, 
                    self.command_handler, 
                    command
                )
                return result
            return {"ok": False, "error": "Empty command"}
        
        # Unknown message type
        return {"ok": False, "error": f"Unknown message type: {msg_type}"}
    
    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        if not self._clients:
            return
        
        msg_json = json.dumps(message)
        await asyncio.gather(
            *[client.send(msg_json) for client in self._clients],
            return_exceptions=True
        )
    
    def send_command(self, command_type: str, **kwargs) -> bool:
        """Send command to connected extension clients."""
        if not self._running or not self._loop or not self._clients:
            return False
        
        message = {"type": command_type, **kwargs}
        asyncio.run_coroutine_threadsafe(
            self.broadcast(message),
            self._loop
        )
        return True
    
    # Convenience methods for common commands
    def request_scan(self) -> Optional[Dict[str, Any]]:
        """Request page scan from extension and return cached result."""
        self.send_command("scan")
        # Wait briefly for scan result
        import time
        time.sleep(0.5)
        return self._last_scan
    
    def request_click(self, index: Optional[int] = None, text: Optional[str] = None) -> bool:
        """Request click on element."""
        return self.send_command("click", index=index, text=text)
    
    def request_scroll(self, direction: str = "down", amount: int = 500) -> bool:
        """Request page scroll."""
        return self.send_command("scroll", direction=direction, amount=amount)
    
    def request_type(self, text: str, element_index: Optional[int] = None, submit: bool = False) -> bool:
        """Request text input."""
        return self.send_command("type", text=text, index=element_index, submit=submit)
    
    def request_navigate(self, url: str) -> bool:
        """Request navigation to URL."""
        return self.send_command("navigate", url=url)
    
    def request_find_tabs(self, url_pattern: str) -> Optional[list]:
        """Request tabs matching URL pattern from extension.
        
        Args:
            url_pattern: URL pattern to match (e.g., "*://www.youtube.com/*")
            
        Returns:
            List of tabs or None if no extension connected
        """
        if not self.has_client():
            return None
            
        self._tabs_result = None
        self.send_command("find_tabs", url_pattern=url_pattern)
        
        # Wait briefly for response
        import time
        for _ in range(10):  # 1 second max
            time.sleep(0.1)
            if self._tabs_result is not None:
                return self._tabs_result
        return None
    
    def request_focus_tab(self, tab_id: int, window_id: Optional[int] = None) -> bool:
        """Request to focus a specific tab.
        
        Args:
            tab_id: Tab ID to focus
            window_id: Window ID (optional, will focus window too)
            
        Returns:
            True if command sent
        """
        return self.send_command("focus_tab", tab_id=tab_id, window_id=window_id)
    
    def request_get_all_tabs(self) -> Optional[list]:
        """Get all open tabs from extension.
        
        Returns:
            List of all tabs with id, title, url, windowId, active
        """
        if not self.has_client():
            return None
            
        self._tabs_result = None
        self.send_command("get_all_tabs")
        
        # Wait briefly for response
        import time
        for _ in range(10):  # 1 second max
            time.sleep(0.1)
            if self._tabs_result is not None:
                return self._tabs_result
        return None
    
    def toggle_overlay(self, enabled: bool) -> bool:
        """Toggle overlay visibility."""
        return self.send_command("overlay", enabled=enabled)
    
    def get_current_page(self) -> Optional[Dict[str, str]]:
        """Get current page info."""
        return getattr(self, '_current_page', None)
    
    def get_page_elements(self) -> list:
        """Get elements from last scan."""
        scan = getattr(self, '_last_scan', None)
        if scan:
            return scan.get('elements', [])
        return []
    
    def find_element_by_text(self, text: str) -> Optional[Dict]:
        """Find element by text match in last scan."""
        text_lower = text.lower()
        for el in self.get_page_elements():
            if text_lower in el.get('text', '').lower():
                return el
        return None
    
    async def _run_server(self) -> None:
        """Run the WebSocket server."""
        async with ws_serve(self._handle_client, self.host, self.port):
            logger.info(f"[ExtBridge] WebSocket server started on ws://{self.host}:{self.port}")
            while self._running:
                await asyncio.sleep(1)
    
    def start(self) -> bool:
        """Start the WebSocket server in a background thread."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("[ExtBridge] websockets not available, skipping")
            return False
        
        if self._running:
            return True
        
        self._running = True
        self._last_scan = None
        
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run_server())
            except Exception as e:
                logger.error(f"[ExtBridge] Server error: {e}")
            finally:
                self._loop.close()
        
        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        return True
    
    def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        logger.info("[ExtBridge] WebSocket server stopped")
    
    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()
    
    @property
    def client_count(self) -> int:
        return len(self._clients)
    
    def has_client(self) -> bool:
        """Check if any extension client is connected."""
        return len(self._clients) > 0
    
    def get_last_scan(self) -> Optional[Dict[str, Any]]:
        """Get the last scan result."""
        return getattr(self, '_last_scan', None)


# Global instance
_bridge: Optional[ExtensionBridge] = None


def get_extension_bridge() -> Optional[ExtensionBridge]:
    """Get or create the global extension bridge instance."""
    global _bridge
    if _bridge is None and WEBSOCKETS_AVAILABLE:
        _bridge = ExtensionBridge()
    return _bridge


def get_bridge() -> Optional[ExtensionBridge]:
    """Alias for get_extension_bridge."""
    return get_extension_bridge()


def start_extension_bridge(command_handler: Optional[Callable[[str], dict]] = None) -> bool:
    """Start the extension bridge server."""
    bridge = get_extension_bridge()
    if bridge:
        bridge.command_handler = command_handler
        return bridge.start()
    return False


def stop_extension_bridge() -> None:
    """Stop the extension bridge server."""
    global _bridge
    if _bridge:
        _bridge.stop()
        _bridge = None
